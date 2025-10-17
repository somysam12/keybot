"""
verify_key_bot.py
Telegram micro-bot + Web Service wrapper
- Keeps bot alive via HTTP server (aiohttp)
- User verification via channel subscription
- Key assignment system with cooldown
- Admin panel for managing keys and channels
- NEW FEATURES: Delete All Keys, List Users Who Claimed Keys
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, List

import aiosqlite
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
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
            last_key_time TEXT DEFAULT NULL
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
        await db.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user.id, user.username))
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

async def assign_key_to_user(user_id: int, key_id: int, key_text: str, duration_days: int, chat_id: int, message_id: int):
    assigned_at = datetime.now()
    expires_at = assigned_at + timedelta(days=duration_days)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE keys SET used=1 WHERE id=?", (key_id,))
        await db.execute("UPDATE users SET last_key_time=? WHERE user_id=?", (assigned_at.isoformat(), user_id))
        await db.execute("""
            INSERT INTO sales (user_id, key_id, key_text, assigned_at, expires_at, message_chat_id, message_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, key_id, key_text, assigned_at.isoformat(), expires_at.isoformat(), chat_id, message_id))
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
    kb.add(InlineKeyboardButton(text="🗑 Delete All Keys", callback_data="admin_delete_all_keys"))
    kb.add(InlineKeyboardButton(text="👥 Users Who Claimed Keys", callback_data="admin_list_users"))
    return kb

# =================== BOT HANDLERS ===================

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

# --------- Existing callback handlers (verify, start_claim, admin_add_keys, admin_stats, etc.) ---------
# All your existing handlers remain unchanged

# =================== NEW ADMIN FEATURES ===================

@dp.callback_query_handler(lambda c: c.data == "admin_delete_all_keys")
async def cb_admin_delete_all_keys(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id, callback.from_user.username):
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM keys")
        await db.commit()
    await callback.message.answer("❌ All keys have been deleted successfully!", parse_mode="MarkdownV2")
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "admin_list_users")
async def cb_admin_list_users(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id, callback.from_user.username):
        return
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("""
            SELECT u.username, s.key_text, s.assigned_at 
            FROM sales s 
            LEFT JOIN users u ON s.user_id = u.user_id
            ORDER BY s.assigned_at DESC
        """)
        rows = await cur.fetchall()

    if not rows:
        await callback.message.answer("👥 No users have claimed any keys yet.", parse_mode="MarkdownV2")
    else:
        text = "📋 **Users Who Claimed Keys:**\n\n"
        for idx, (username, key_text, assigned_at) in enumerate(rows, start=1):
            uname = escape_markdown(username or "Unknown")
            key = escape_markdown(key_text)
            time = escape_markdown(assigned_at)
            text += f"{idx}\\. @{uname} → `{key}` at {time}\n"
        await callback.message.answer(text, parse_mode="MarkdownV2")
    await callback.answer()

# =================== WEB SERVER ===================

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
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
