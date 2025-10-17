"""
verify_key_bot.py
Telegram micro-bot + Web Service wrapper
- Keeps bot alive via HTTP server (aiohttp)
- User verification via channel subscription
- Key assignment system with cooldown
- Admin panel for managing keys and channels
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
DB_PATH = "bot_data.db"
LOGFILE = "bot.log"
DEFAULT_COOLDOWN_HOURS = 48

logging.basicConfig(level=logging.INFO, filename=LOGFILE,
                    format="%(asctime)s %(levelname)s %(message)s")

awaiting_keys: Dict[int, int] = {}
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

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

async def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

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

async def is_user_verified(user_id: int) -> bool:
    channels = await list_channels()
    for channel in channels:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                return False
        except:
            return False
    return True

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
        kb.insert(InlineKeyboardButton(text=f"Join Channel {idx}", url=f"https://t.me/{uname.lstrip('@')}"))
    kb.add(InlineKeyboardButton(text="✅ Verify", callback_data="verify"))
    kb.add(InlineKeyboardButton(text="▶️ Start", callback_data="start_claim"))
    return kb

async def build_admin_keyboard():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton(text="Add Keys", callback_data="admin_add_keys"))
    kb.add(InlineKeyboardButton(text="View Stats", callback_data="admin_stats"))
    kb.add(InlineKeyboardButton(text="Add Channel", callback_data="admin_add_channel"))
    kb.add(InlineKeyboardButton(text="Remove Channel", callback_data="admin_remove_channel"))
    kb.add(InlineKeyboardButton(text="List Channels", callback_data="admin_list_channels"))
    kb.add(InlineKeyboardButton(text="Set Cooldown", callback_data="admin_set_cooldown"))
    return kb

@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    await ensure_user_record(message.from_user)
    kb = await build_start_verify_keyboard()
    text = "Welcome! Join the channels and press ✅ Verify, then ▶️ Start to claim your key."
    await message.answer(text, reply_markup=kb)

@dp.message_handler(commands=["admin"])
async def cmd_admin(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.answer("You are not authorized.")
        return
    kb = await build_admin_keyboard()
    await message.answer("Admin Panel:", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == "verify")
async def cb_verify(callback: types.CallbackQuery):
    await ensure_user_record(callback.from_user)
    if await is_user_verified(callback.from_user.id):
        await mark_verified(callback.from_user.id)
        await callback.answer("Verification successful!", show_alert=True)
    else:
        await callback.answer("Please join all channels first!", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == "start_claim")
async def cb_start_claim(callback: types.CallbackQuery):
    await ensure_user_record(callback.from_user)
    
    if not await can_claim_key(callback.from_user.id):
        cooldown_setting = await get_setting("cooldown_hours", str(DEFAULT_COOLDOWN_HOURS))
        cooldown_hours = int(cooldown_setting) if cooldown_setting else DEFAULT_COOLDOWN_HOURS
        await callback.answer(f"Please wait {cooldown_hours} hours between claims.", show_alert=True)
        return
    
    key_row = await get_next_key()
    if not key_row:
        await callback.answer("No keys available right now. Please try again later.", show_alert=True)
        return
    
    key_id, key_text, duration_days = key_row
    msg = await callback.message.answer(f"🎉 Your Key: `{key_text}`\nValid for {duration_days} days.", parse_mode="Markdown")
    await assign_key_to_user(callback.from_user.id, key_id, key_text, duration_days, msg.chat.id, msg.message_id)
    await callback.answer("Key assigned!", show_alert=True)

@dp.callback_query_handler(lambda c: c.data == "admin_add_keys")
async def cb_admin_add_keys(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    awaiting_keys[callback.from_user.id] = 30
    await callback.message.answer("Send keys in format:\n`key1 | duration_days | name | link`\nOr just: `key1 | duration_days`\nOne per line.", parse_mode="Markdown")
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "admin_stats")
async def cb_admin_stats(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM keys WHERE used=0")
        unused = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COUNT(*) FROM keys WHERE used=1")
        used = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COUNT(*) FROM users")
        users = (await cur.fetchone())[0]
    await callback.message.answer(f"Stats:\nUnused Keys: {unused}\nUsed Keys: {used}\nTotal Users: {users}")
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "admin_add_channel")
async def cb_admin_add_channel(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    awaiting_keys[callback.from_user.id] = -1
    await callback.message.answer("Send the channel username (e.g., @channelname):")
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "admin_remove_channel")
async def cb_admin_remove_channel(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    awaiting_keys[callback.from_user.id] = -2
    await callback.message.answer("Send the channel username to remove:")
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "admin_list_channels")
async def cb_admin_list_channels(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    channels = await list_channels()
    if not channels:
        await callback.message.answer("No channels configured.")
    else:
        text = "Configured Channels:\n" + "\n".join(channels)
        await callback.message.answer(text)
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "admin_set_cooldown")
async def cb_admin_set_cooldown(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id):
        return
    awaiting_keys[callback.from_user.id] = -3
    current = await get_setting("cooldown_hours", str(DEFAULT_COOLDOWN_HOURS))
    await callback.message.answer(f"Current cooldown: {current} hours\nSend new cooldown in hours:")
    await callback.answer()

@dp.message_handler(lambda m: m.from_user.id in awaiting_keys)
async def handle_admin_input(message: types.Message):
    mode = awaiting_keys[message.from_user.id]
    
    if mode == -1:
        success = await add_channel(message.text)
        if success:
            await message.answer(f"Channel {message.text} added successfully!")
        else:
            await message.answer(f"Failed to add channel (may already exist).")
        del awaiting_keys[message.from_user.id]
    
    elif mode == -2:
        await remove_channel(message.text)
        await message.answer(f"Channel {message.text} removed.")
        del awaiting_keys[message.from_user.id]
    
    elif mode == -3:
        try:
            hours = int(message.text)
            await set_setting("cooldown_hours", str(hours))
            await message.answer(f"Cooldown set to {hours} hours.")
        except ValueError:
            await message.answer("Invalid number. Please try again.")
        del awaiting_keys[message.from_user.id]
    
    else:
        lines = message.text.strip().split('\n')
        added = 0
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
                        continue
            await db.commit()
        await message.answer(f"Added {added} keys successfully!")
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
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
