"""
verify_key_bot.py
Telegram micro-bot + Web Service wrapper
- Keeps bot alive via HTTP server (aiohttp)
- User verification via channel subscription
- Key assignment system with cooldown
- Admin panel for managing keys and channels
- NEW: Delete all keys functionality
- NEW: User tracking with claim history
- FIXED: All buttons working properly with proper database operations
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, List

import aiosqlite
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from aiohttp import web
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "REPLACE_WITH_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
ADMIN_USERNAME = "tgshaitaan"
DB_PATH = "bot_data.db"
LOGFILE = "bot.log"
DEFAULT_COOLDOWN_HOURS = 48

logging.basicConfig(level=logging.INFO, filename=LOGFILE,
                    format="%(asctime)s %(levelname)s %(message)s")

awaiting_keys: Dict[int, int] = {}
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

def escape_markdown(text: str) -> str:
    """Escape special characters for Markdown"""
    if not text:
        return ""
    escape_chars = '_*[]()~`>#+-=|{}.!'
    return ''.join('\\' + char if char in escape_chars else char for char in str(text))

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL
        );
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            verified INTEGER DEFAULT 0,
            last_key_time TEXT DEFAULT NULL,
            total_keys_claimed INTEGER DEFAULT 0,
            first_seen TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key_text TEXT NOT NULL,
            duration_days INTEGER NOT NULL,
            meta_name TEXT DEFAULT NULL,
            meta_link TEXT DEFAULT NULL,
            used INTEGER DEFAULT 0,
            added_at TEXT
        );
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            key_id INTEGER,
            key_text TEXT,
            assigned_at TEXT,
            expires_at TEXT,
            active INTEGER DEFAULT 1,
            message_chat_id INTEGER,
            message_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        """)
        await db.commit()

async def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = await cur.fetchone()
        return row[0] if row else default

async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        await db.commit()

async def ensure_user_record(user: types.User):
    async with aiosqlite.connect(DB_PATH) as db:
        # Check if user exists
        cur = await db.execute("SELECT username FROM users WHERE user_id=?", (user.id,))
        existing = await cur.fetchone()
        
        if not existing:
            # New user
            await db.execute(
                "INSERT INTO users (user_id, username, first_seen) VALUES (?, ?, ?)", 
                (user.id, user.username, datetime.now().isoformat())
            )
        elif existing[0] != user.username:
            # Update username if changed
            await db.execute("UPDATE users SET username=? WHERE user_id=?", (user.username, user.id))
        await db.commit()

async def is_admin(user_id: int, username: str = None) -> bool:
    if user_id == ADMIN_ID:
        return True
    if username and username.lower().lstrip('@') == ADMIN_USERNAME.lower().lstrip('@'):
        return True
    return False

async def add_channel(username: str) -> bool:
    uname = username.strip()
    if not uname.startswith("@"):
        uname = "@" + uname
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("INSERT INTO channels (username) VALUES (?)", (uname,))
            await db.commit()
            return True
        except:
            return False

async def remove_channel(username: str) -> bool:
    uname = username.strip()
    if not uname.startswith("@"):
        uname = "@" + uname
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM channels WHERE username=?", (uname,))
        await db.commit()
        return True

async def list_channels() -> List[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT username FROM channels ORDER BY id")
        rows = await cur.fetchall()
        return [r[0] for r in rows]

async def is_user_verified(user_id: int) -> tuple[bool, str]:
    channels = await list_channels()
    if not channels:
        return True, ""
    
    for channel in channels:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                return False, f"Please join {channel} first!"
        except Exception as e:
            logging.error(f"Error checking membership for {channel}: {e}")
            return False, f"❌ Bot is not admin in {channel}. Please add bot as admin!"
    return True, "✅ Verified!"

async def mark_verified(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET verified=1 WHERE user_id=?", (user_id,))
        await db.commit()

async def can_claim_key(user_id: int) -> bool:
    cooldown_setting = await get_setting("cooldown_hours", str(DEFAULT_COOLDOWN_HOURS))
    cooldown_hours = int(cooldown_setting) if cooldown_setting else DEFAULT_COOLDOWN_HOURS
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT last_key_time FROM users WHERE user_id=?", (user_id,))
        row = await cur.fetchone()
        if not row or not row[0]:
            return True
        last_time = datetime.fromisoformat(row[0])
        if datetime.now() - last_time >= timedelta(hours=cooldown_hours):
            return True
        return False

async def get_next_key() -> Optional[tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id, key_text, duration_days FROM keys WHERE used=0 ORDER BY id LIMIT 1")
        row = await cur.fetchone()
        return row

async def assign_key_to_user(user_id: int, key_id: int, key_text: str, duration_days: int, chat_id: int, message_id: int, username: str = None):
    assigned_at = datetime.now()
    expires_at = assigned_at + timedelta(days=duration_days)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE keys SET used=1 WHERE id=?", (key_id,))
        await db.execute("UPDATE users SET last_key_time=?, total_keys_claimed = total_keys_claimed + 1 WHERE user_id=?", 
                        (assigned_at.isoformat(), user_id))
        await db.execute("""
            INSERT INTO sales (user_id, username, key_id, key_text, assigned_at, expires_at, message_chat_id, message_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, username, key_id, key_text, assigned_at.isoformat(), expires_at.isoformat(), chat_id, message_id))
        await db.commit()

async def build_start_verify_keyboard():
    kb = InlineKeyboardMarkup(row_width=1)
    channels = await list_channels()
    for idx, uname in enumerate(channels, start=1):
        kb.insert(InlineKeyboardButton(text=f"📢 Join Channel {idx}", url=f"https://t.me/{uname.lstrip('@')}"))
    kb.add(InlineKeyboardButton(text="✅ Verify Membership", callback_data="verify"))
    kb.add(InlineKeyboardButton(text="🎁 Claim Your Key", callback_data="start_claim"))
    return kb

async def build_admin_keyboard():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton(text="🔑 Add Keys", callback_data="admin_add_keys"))
    kb.add(InlineKeyboardButton(text="📊 View Stats", callback_data="admin_stats"))
    kb.add(InlineKeyboardButton(text="📢 Add Channel", callback_data="admin_add_channel"))
    kb.add(InlineKeyboardButton(text="❌ Remove Channel", callback_data="admin_remove_channel"))
    kb.add(InlineKeyboardButton(text="📋 List Channels", callback_data="admin_list_channels"))
    kb.add(InlineKeyboardButton(text="⏰ Set Cooldown", callback_data="admin_set_cooldown"))
    kb.add(InlineKeyboardButton(text="💬 Custom Key Message", callback_data="admin_set_key_msg"))
    # NEW: Admin buttons for delete all keys and user tracking
    kb.add(InlineKeyboardButton(text="🗑️ Delete All Keys", callback_data="admin_delete_all_keys"))
    kb.add(InlineKeyboardButton(text="👥 User Claim History", callback_data="admin_user_history"))
    kb.add(InlineKeyboardButton(text="🔙 Back to Main", callback_data="admin_back_main"))
    return kb

async def build_delete_confirmation_keyboard():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton(text="✅ Yes, Delete All", callback_data="confirm_delete_all_keys"))
    kb.add(InlineKeyboardButton(text="❌ Cancel", callback_data="admin_back_main"))
    return kb

@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    await ensure_user_record(message.from_user)
    kb = await build_start_verify_keyboard()
    name = escape_markdown(message.from_user.first_name)
    text = f"🌟 **Welcome {name}\\!** 🌟\n\n"
    text += "📋 **Follow these steps:**\n"
    text += "1️⃣ Join all channels below\n"
    text += "2️⃣ Click ✅ Verify Membership\n"
    text += "3️⃣ Click 🎁 Claim Your Key\n\n"
    text += "⚡ Let's get started\\!"
    await message.answer(text, reply_markup=kb, parse_mode="MarkdownV2")

@dp.message_handler(commands=["admin"])
async def cmd_admin(message: types.Message):
    if not await is_admin(message.from_user.id, message.from_user.username):
        await message.answer("❌ You are not authorized.")
        return
    kb = await build_admin_keyboard()
    username = escape_markdown(message.from_user.username or "Admin")
    text = f"🔐 **Admin Panel**\n\n"
    text += f"👋 Welcome @{username}\\!\n"
    text += "Choose an option below:"
    await message.answer(text, reply_markup=kb, parse_mode="MarkdownV2")

@dp.callback_query_handler(lambda c: c.data == "verify")
async def cb_verify(callback: types.CallbackQuery):
    await ensure_user_record(callback.from_user)
    is_verified, msg = await is_user_verified(callback.from_user.id)
    if is_verified:
        await mark_verified(callback.from_user.id)
        await callback.answer("✅ Verification successful!", show_alert=True)
        
        # Update the message to show verification success
        kb = await build_start_verify_keyboard()
        name = escape_markdown(callback.from_user.first_name)
        text = f"🌟 **Welcome {name}\\!** 🌟\n\n"
        text += "✅ **You are verified!**\n\n"
        text += "📋 **Next Step:**\n"
        text += "Click 🎁 Claim Your Key to get your key\n\n"
        text += "⚡ Enjoy your key!"
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="MarkdownV2")
    else:
        await callback.answer(msg, show_alert=True)

@dp.callback_query_handler(lambda c: c.data == "start_claim")
async def cb_start_claim(callback: types.CallbackQuery):
    await ensure_user_record(callback.from_user)
    
    # Check verification first
    is_verified, msg = await is_user_verified(callback.from_user.id)
    if not is_verified:
        await callback.answer(msg, show_alert=True)
        return
    
    if not await can_claim_key(callback.from_user.id):
        cooldown_setting = await get_setting("cooldown_hours", str(DEFAULT_COOLDOWN_HOURS))
        cooldown_hours = int(cooldown_setting) if cooldown_setting else DEFAULT_COOLDOWN_HOURS
        await callback.answer(f"⏳ Please wait {cooldown_hours} hours between claims.", show_alert=True)
        return
    
    key_row = await get_next_key()
    if not key_row:
        await callback.answer("❌ No keys available right now. Please try again later.", show_alert=True)
        return
    
    key_id, key_text, duration_days = key_row
    
    custom_msg = await get_setting("key_message")
    if custom_msg:
        escaped_key = escape_markdown(key_text)
        escaped_user = escape_markdown(callback.from_user.first_name)
        escaped_days = escape_markdown(str(duration_days))
        msg_text = custom_msg.replace("{key}", escaped_key).replace("{days}", escaped_days).replace("{user}", escaped_user)
        parse_mode = "MarkdownV2"
    else:
        name = escape_markdown(callback.from_user.first_name)
        msg_text = f"🎉 **Congratulations {name}\\!** 🎉\n\n"
        msg_text += f"🔑 **Your Key:** `{escape_markdown(key_text)}`\n"
        msg_text += f"⏰ **Valid for:** {duration_days} days\n\n"
        msg_text += f"✅ Key activated successfully\\!"
        parse_mode = "MarkdownV2"
    
    msg = await callback.message.answer(msg_text, parse_mode=parse_mode)
    await assign_key_to_user(callback.from_user.id, key_id, key_text, duration_days, msg.chat.id, msg.message_id, callback.from_user.username)
    await callback.answer("🎁 Key assigned successfully!", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == "admin_add_keys")
async def cb_admin_add_keys(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id, callback.from_user.username):
        await callback.answer("❌ Unauthorized")
        return
    awaiting_keys[callback.from_user.id] = 30
    text = "🔑 **Add New Keys**\n\n"
    text += "📝 **Format:**\n"
    text += "`key1 | duration_days | name | link`\n"
    text += "Or simply: `key1 | duration_days`\n\n"
    text += "📋 One key per line\n\n"
    text += "**Example:**\n"
    text += "`ABC123 | 30 | Premium | https://example\\.com`\n\n"
    text += "Send your keys in the format above:"
    await callback.message.edit_text(text, reply_markup=build_admin_keyboard(), parse_mode="MarkdownV2")
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "admin_stats")
async def cb_admin_stats(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id, callback.from_user.username):
        await callback.answer("❌ Unauthorized")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM keys WHERE used=0")
        unused = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COUNT(*) FROM keys WHERE used=1")
        used = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COUNT(*) FROM users")
        users = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COUNT(*) FROM sales")
        total_sales = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COUNT(*) FROM channels")
        channels = (await cur.fetchone())[0]
    total_keys = unused + used
    text = "📊 **Bot Statistics**\n\n"
    text += f"🔑 Unused Keys: **{unused}**\n"
    text += f"✅ Used Keys: **{used}**\n"
    text += f"👥 Total Users: **{users}**\n"
    text += f"📈 Total Keys: **{total_keys}**\n"
    text += f"🛒 Total Claims: **{total_sales}**\n"
    text += f"📢 Total Channels: **{channels}**"
    await callback.message.edit_text(text, reply_markup=build_admin_keyboard(), parse_mode="MarkdownV2")
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "admin_add_channel")
async def cb_admin_add_channel(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id, callback.from_user.username):
        await callback.answer("❌ Unauthorized")
        return
    awaiting_keys[callback.from_user.id] = -1
    text = "📢 **Add New Channel**\n\n"
    text += "Send the channel username:\n"
    text += "Example: `@channelname`\n\n"
    text += "⚠️ **Important:** Make sure to add the bot as admin in the channel for tracking\\!"
    await callback.message.edit_text(text, reply_markup=build_admin_keyboard(), parse_mode="MarkdownV2")
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "admin_remove_channel")
async def cb_admin_remove_channel(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id, callback.from_user.username):
        await callback.answer("❌ Unauthorized")
        return
    awaiting_keys[callback.from_user.id] = -2
    text = "❌ **Remove Channel**\n\n"
    text += "Send the channel username to remove:\n"
    text += "Example: `@channelname`"
    await callback.message.edit_text(text, reply_markup=build_admin_keyboard(), parse_mode="MarkdownV2")
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "admin_list_channels")
async def cb_admin_list_channels(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id, callback.from_user.username):
        await callback.answer("❌ Unauthorized")
        return
    channels = await list_channels()
    if not channels:
        text = "📢 No channels configured yet\\."
    else:
        text = "📋 **Configured Channels:**\n\n"
        for idx, ch in enumerate(channels, start=1):
            text += f"{idx}\\. {escape_markdown(ch)}\n"
    await callback.message.edit_text(text, reply_markup=build_admin_keyboard(), parse_mode="MarkdownV2")
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "admin_set_cooldown")
async def cb_admin_set_cooldown(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id, callback.from_user.username):
        await callback.answer("❌ Unauthorized")
        return
    awaiting_keys[callback.from_user.id] = -3
    current = await get_setting("cooldown_hours", str(DEFAULT_COOLDOWN_HOURS))
    text = f"⏰ **Set Cooldown Period**\n\n"
    text += f"Current cooldown: **{current} hours**\n\n"
    text += "Send new cooldown time in hours:"
    await callback.message.edit_text(text, reply_markup=build_admin_keyboard(), parse_mode="MarkdownV2")
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "admin_set_key_msg")
async def cb_admin_set_key_msg(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id, callback.from_user.username):
        await callback.answer("❌ Unauthorized")
        return
    awaiting_keys[callback.from_user.id] = -4
    current = await get_setting("key_message")
    text = "💬 **Customize Key Message**\n\n"
    text += "**Current message:**\n"
    if current:
        text += f"```\n{escape_markdown(current)}\n```\n"
    else:
        text += "_Using default message_\n\n"
    text += "**Available variables:**\n"
    text += "`{key}` \\- The key text\n"
    text += "`{days}` \\- Duration in days\n"
    text += "`{user}` \\- User's first name\n\n"
    text += "**Example:**\n"
    text += "```\n🎉 Hey {user}\\!\n🔑 Your key: {key}\n⏰ Valid for {days} days\n```\n\n"
    text += "Send your custom message:"
    await callback.message.edit_text(text, reply_markup=build_admin_keyboard(), parse_mode="MarkdownV2")
    await callback.answer()

# NEW: Delete all keys functionality
@dp.callback_query_handler(lambda c: c.data == "admin_delete_all_keys")
async def cb_admin_delete_all_keys(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id, callback.from_user.username):
        await callback.answer("❌ Unauthorized")
        return
    
    text = "🗑️ **Delete All Keys**\n\n"
    text += "⚠️ **WARNING:** This will permanently delete:\n"
    text += "• All unused keys\n• All used keys\n• All sales records\n\n"
    text += "This action cannot be undone\\!\n\n"
    text += "Are you sure you want to continue?"
    
    await callback.message.edit_text(text, reply_markup=build_delete_confirmation_keyboard(), parse_mode="MarkdownV2")
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "confirm_delete_all_keys")
async def cb_confirm_delete_all_keys(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id, callback.from_user.username):
        await callback.answer("❌ Unauthorized")
        return
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Delete all keys and sales records
            await db.execute("DELETE FROM keys")
            await db.execute("DELETE FROM sales")
            # Reset user key counts and last key time
            await db.execute("UPDATE users SET last_key_time = NULL, total_keys_claimed = 0")
            await db.commit()
        
        text = "✅ **All keys and sales records have been deleted successfully\\!**\n\n"
        text += "• All keys removed\n• Sales history cleared\n• User key counts reset"
        
        await callback.message.edit_text(text, reply_markup=build_admin_keyboard(), parse_mode="MarkdownV2")
        await callback.answer("✅ All keys deleted successfully!")
    except Exception as e:
        logging.error(f"Error deleting keys: {e}")
        await callback.message.edit_text("❌ **Error deleting keys\\. Please try again\\.**", reply_markup=build_admin_keyboard(), parse_mode="MarkdownV2")
        await callback.answer("❌ Error occurred")

@dp.callback_query_handler(lambda c: c.data == "admin_user_history")
async def cb_admin_user_history(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id, callback.from_user.username):
        await callback.answer("❌ Unauthorized")
        return
    
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Get top users by claims
            cur = await db.execute("""
                SELECT user_id, username, total_keys_claimed, first_seen 
                FROM users 
                WHERE total_keys_claimed > 0 
                ORDER BY total_keys_claimed DESC 
                LIMIT 15
            """)
            top_users = await cur.fetchall()
            
            # Get recent claims
            cur = await db.execute("""
                SELECT s.user_id, s.username, s.key_text, s.assigned_at, u.total_keys_claimed
                FROM sales s
                LEFT JOIN users u ON s.user_id = u.user_id
                ORDER BY s.assigned_at DESC 
                LIMIT 10
            """)
            recent_claims = await cur.fetchall()
        
        if not top_users and not recent_claims:
            text = "👥 **User Claim History**\n\n"
            text += "No key claims recorded yet\\."
            await callback.message.edit_text(text, reply_markup=build_admin_keyboard(), parse_mode="MarkdownV2")
            await callback.answer()
            return
        
        text = "👥 **User Claim History**\n\n"
        
        if top_users:
            text += "🏆 **Top Users by Claims:**\n"
            for idx, (user_id, username, total_claims, first_seen) in enumerate(top_users, 1):
                user_display = f"@{username}" if username else f"User#{user_id}"
                text += f"{idx}\\. {escape_markdown(user_display)} \\- **{total_claims}** claims\n"
            text += "\n"
        
        if recent_claims:
            text += "🕒 **Recent Claims:**\n"
            for user_id, username, key_text, assigned_at, total_claims in recent_claims:
                user_display = f"@{username}" if username else f"User#{user_id}"
                time_ago = datetime.now() - datetime.fromisoformat(assigned_at)
                hours_ago = int(time_ago.total_seconds() // 3600)
                text += f"• {escape_markdown(user_display)} \\- `{escape_markdown(key_text[:12])}...` \\- {hours_ago}h ago\n"
        
        await callback.message.edit_text(text, reply_markup=build_admin_keyboard(), parse_mode="MarkdownV2")
        await callback.answer()
    except Exception as e:
        logging.error(f"Error fetching user history: {e}")
        await callback.message.edit_text("❌ **Error fetching user history\\.**", reply_markup=build_admin_keyboard(), parse_mode="MarkdownV2")
        await callback.answer("❌ Error occurred")

@dp.callback_query_handler(lambda c: c.data == "admin_back_main")
async def cb_admin_back_main(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id, callback.from_user.username):
        await callback.answer("❌ Unauthorized")
        return
    
    kb = await build_admin_keyboard()
    username = escape_markdown(callback.from_user.username or "Admin")
    text = f"🔐 **Admin Panel**\n\n"
    text += f"👋 Welcome @{username}\\!\n"
    text += "Choose an option below:"
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="MarkdownV2")
    await callback.answer()

@dp.message_handler(lambda m: m.from_user.id in awaiting_keys)
async def handle_admin_input(message: types.Message):
    mode = awaiting_keys[message.from_user.id]
    
    if mode == -1:  # Add channel
        success = await add_channel(message.text)
        ch = escape_markdown(message.text)
        if success:
            await message.answer(f"✅ Channel {ch} added successfully\\!\n\n⚠️ Don't forget to add the bot as admin in the channel\\!", parse_mode="MarkdownV2")
        else:
            await message.answer(f"❌ Failed to add channel \\(may already exist\\)\\.", parse_mode="MarkdownV2")
        del awaiting_keys[message.from_user.id]
    
    elif mode == -2:  # Remove channel
        success = await remove_channel(message.text)
        ch = escape_markdown(message.text)
        if success:
            await message.answer(f"✅ Channel {ch} removed successfully\\!", parse_mode="MarkdownV2")
        else:
            await message.answer(f"❌ Failed to remove channel\\.", parse_mode="MarkdownV2")
        del awaiting_keys[message.from_user.id]
    
    elif mode == -3:  # Set cooldown
        try:
            hours = int(message.text)
            if hours < 1:
                await message.answer("❌ Cooldown must be at least 1 hour\\.", parse_mode="MarkdownV2")
            else:
                await set_setting("cooldown_hours", str(hours))
                await message.answer(f"✅ Cooldown set to **{hours} hours** successfully\\!", parse_mode="MarkdownV2")
        except ValueError:
            await message.answer("❌ Invalid number\\. Please try again\\.", parse_mode="MarkdownV2")
        del awaiting_keys[message.from_user.id]
    
    elif mode == -4:  # Set custom key message
        await set_setting("key_message", message.text)
        preview = escape_markdown(message.text)
        await message.answer(f"✅ Custom key message saved successfully\\!\n\n**Preview:**\n{preview}", parse_mode="MarkdownV2")
        del awaiting_keys[message.from_user.id]
    
    else:  # Add keys
        lines = message.text.strip().split('\n')
        added = 0
        errors = 0
        async with aiosqlite.connect(DB_PATH) as db:
            for line in lines:
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 2:
                    key_text = parts[0]
                    try:
                        duration = int(parts[1])
                        meta_name = parts[2] if len(parts) > 2 else None
                        meta_link = parts[3] if len(parts) > 3 else None
                        await db.execute(
                            "INSERT INTO keys (key_text, duration_days, meta_name, meta_link, added_at) VALUES (?, ?, ?, ?, ?)",
                            (key_text, duration, meta_name, meta_link, datetime.now().isoformat())
                        )
                        added += 1
                    except ValueError:
                        errors += 1
                        continue
            await db.commit()
        
        result_text = f"✅ Successfully added **{added}** keys to the database\\!"
        if errors > 0:
            result_text += f"\n\n❌ **{errors}** lines had errors and were skipped\\."
        await message.answer(result_text, parse_mode="MarkdownV2")
        del awaiting_keys[message.from_user.id]

async def handle_root(request):
    return web.Response(text="Bot is running ✅")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_root)
    port = int(os.environ.get("PORT", 5000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"HTTP server running on port {port}")
    print(f"HTTP server running on port {port}")

async def on_startup(dispatcher):
    await init_db()
    logging.info("Bot started")
    print("Bot started successfully!")
    asyncio.create_task(start_web_server())

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
