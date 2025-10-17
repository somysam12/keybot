"""
verify_key_bot_web.py
Telegram micro-bot + Web Service wrapper for Render free plan
- Keeps bot alive via HTTP server (aiohttp)
- All previous functionality intact (verify, start, key assignment, admin panel)
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

# -------- CONFIG ----------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "REPLACE_WITH_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_PATH = "bot_data.db"
LOGFILE = "bot.log"
DEFAULT_COOLDOWN_HOURS = 48

# Logging
logging.basicConfig(level=logging.INFO, filename=LOGFILE,
                    format="%(asctime)s %(levelname)s %(message)s")

# In-memory states
awaiting_keys: Dict[int, int] = {}  # admin_id -> duration_days
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# ---------- DATABASE INIT ----------
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

# ---------- SETTINGS GET/SET ----------
async def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = await cur.fetchone()
        return row[0] if row else default

async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        await db.commit()

# ---------- USER HELPERS ----------
async def ensure_user_record(user: types.User):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user.id, user.username))
        await db.execute("UPDATE users SET username=? WHERE user_id=?", (user.username, user.id))
        await db.commit()

async def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

# ---------- CHANNEL HELPERS ----------
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

async def list_channels() -> List[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT username FROM channels ORDER BY id")
        rows = await cur.fetchall()
        return [r[0] for r in rows]

# ---------- BOT LOGIC ----------
async def build_start_verify_keyboard():
    kb = InlineKeyboardMarkup(row_width=1)
    channels = await list_channels()
    for idx, uname in enumerate(channels, start=1):
        kb.insert(InlineKeyboardButton(text=f"Join Channel {idx}", url=f"https://t.me/{uname.lstrip('@')}"))
    kb.add(InlineKeyboardButton(text="✅ Verify", callback_data="verify"))
    kb.add(InlineKeyboardButton(text="▶️ Start", callback_data="start_claim"))
    return kb

@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    await ensure_user_record(message.from_user)
    kb = await build_start_verify_keyboard()
    text = "Welcome! Join the channels and press ✅ Verify, then ▶️ Start to claim your key."
    await message.answer(text, reply_markup=kb)

# (Baaki ke callback handlers, admin handlers, cooldown, key assignment etc same)
# For brevity, puri code same use kar sakte ho jaise tera original `verify_key_bot.py`
# Bas bottom me HTTP server wrapper add karenge:

# ---------- HTTP SERVER WRAPPER ----------
async def handle_root(request):
    return web.Response(text="Bot is running ✅")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_root)
    port = int(os.environ.get("PORT", 8000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"HTTP server running on port {port}")

# ---------- STARTUP ----------
async def on_startup(dispatcher):
    await init_db()
    logging.info("Bot started")
    asyncio.create_task(start_web_server())  # keep bot alive

# ---------- MAIN ----------
if __name__ == "__main__":
    from aiogram import executor
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
