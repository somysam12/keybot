"""
verify_key_bot.py
Single-file Telegram bot:
- Channel-based verification (dynamic channels)
- Start to claim a key (one per cooldown interval)
- Admin panel: addchannels, addkeys (bulk), listchannels, setmsg, setcustommsg, broadcast, stats, resetcooldown, users
- Assigned key message shows custom message + meta link/name + live countdown (updated every 60s)
- SQLite persistence: bot_data.db
- Requirements: aiogram, aiosqlite, python-dotenv
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
from dotenv import load_dotenv

# -------- CONFIG ----------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "REPLACE_WITH_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # Must be numeric
DB_PATH = "bot_data.db"
LOGFILE = "bot.log"
DEFAULT_COOLDOWN_HOURS = 48

# Logging
logging.basicConfig(level=logging.INFO, filename=LOGFILE,
                    format="%(asctime)s %(levelname)s %(message)s")

# In-memory states
awaiting_keys: Dict[int, int] = {}  # admin_id -> duration_days (waiting for keys message)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)


# ====== DATABASE HELPERS & INIT ======
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
        # default settings
        cur = await db.execute("SELECT value FROM settings WHERE key=?", ("msg_template",))
        if not await cur.fetchone():
            default_template = ("✅ Your key:\n\n"
                                "`{key}`\n\n"
                                "{custom_msg}\n\n"
                                "{meta_name}: {meta_link}\n"
                                "Expires: {expires_at}\n"
                                "Time left: {time_left}")
            await db.execute("INSERT INTO settings (key, value) VALUES (?, ?)", ("msg_template", default_template))
        cur = await db.execute("SELECT value FROM settings WHERE key=?", ("custom_msg",))
        if not await cur.fetchone():
            await db.execute("INSERT INTO settings (key, value) VALUES (?, ?)", ("custom_msg", "Enjoy your key!")))
        cur = await db.execute("SELECT value FROM settings WHERE key=?", ("cooldown_hours",))
        if not await cur.fetchone():
            await db.execute("INSERT INTO settings (key, value) VALUES (?, ?)", ("cooldown_hours", str(DEFAULT_COOLDOWN_HOURS)))
        await db.commit()


# Generic getter/setter for settings
async def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = await cur.fetchone()
        return row[0] if row else default


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        await db.commit()


# User helpers
async def ensure_user_record(user: types.User):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user.id, user.username))
        await db.execute("UPDATE users SET username=? WHERE user_id=?", (user.username, user.id))
        await db.commit()


async def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID


# Channel helpers
async def add_channel(username: str) -> bool:
    uname = username.strip()
    if not uname.startswith("@"):
        uname = "@" + uname
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute("INSERT INTO channels (username) VALUES (?)", (uname,))
            await db.commit()
            return True
        except Exception:
            return False


async def list_channels() -> List[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT username FROM channels ORDER BY id")
        rows = await cur.fetchall()
        return [r[0] for r in rows]


# Key helpers
async def bulk_add_keys(keys: List[Dict]):
    """
    keys: list of dicts with keys: key_text, duration_days, meta_name (optional), meta_link (optional)
    """
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(DB_PATH) as db:
        for k in keys:
            await db.execute(
                "INSERT INTO keys (key_text, duration_days, meta_name, meta_link, added_at) VALUES (?, ?, ?, ?, ?)",
                (k["key_text"], k["duration_days"], k.get("meta_name"), k.get("meta_link"), now)
            )
        await db.commit()


async def fetch_unused_key():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id, key_text, duration_days, meta_name, meta_link FROM keys WHERE used=0 LIMIT 1")
        row = await cur.fetchone()
        if not row:
            return None
        return {"id": row[0], "key_text": row[1], "duration_days": int(row[2]), "meta_name": row[3], "meta_link": row[4]}


async def mark_key_used(key_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE keys SET used=1 WHERE id=?", (key_id,))
        await db.commit()


# Sale record helpers
async def create_sale(user_id: int, key_id: int, key_text: str, expires_at: datetime):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO sales (user_id, key_id, key_text, assigned_at, expires_at, active) VALUES (?, ?, ?, ?, ?, 1)",
            (user_id, key_id, key_text, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
             expires_at.strftime("%Y-%m-%d %H:%M:%S"))
        )
        await db.commit()
        cur = await db.execute("SELECT last_insert_rowid()")
        row = await cur.fetchone()
        return row[0] if row else None


async def update_sale_message_ids(sale_id: int, chat_id: int, message_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE sales SET message_chat_id=?, message_id=? WHERE id=?", (chat_id, message_id, sale_id))
        await db.commit()


async def deactivate_sale(sale_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE sales SET active=0 WHERE id=?", (sale_id,))
        await db.commit()


# Users and cooldown
async def get_user_info(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id, username, verified, last_key_time FROM users WHERE user_id=?", (user_id,))
        r = await cur.fetchone()
        return r


async def set_user_verified(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET verified=1 WHERE user_id=?", (user_id,))
        await db.commit()


async def set_user_last_key_time(user_id: int, dt: datetime):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET last_key_time=? WHERE user_id=?", (dt.strftime("%Y-%m-%d %H:%M:%S"), user_id))
        await db.commit()


async def reset_cooldown_all():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET last_key_time=NULL")
        await db.commit()


async def reset_cooldown_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET last_key_time=NULL WHERE user_id=?", (user_id,))
        await db.commit()


# Utility
def parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except:
        return None


def human_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ====== KEYBOARD BUILDERS ======
async def build_start_verify_keyboard():
    kb = InlineKeyboardMarkup(row_width=1)
    channels = await list_channels()
    for idx, uname in enumerate(channels, start=1):
        # Use t.me link - works for public channels. If private, admin should provide invite links as meta_link for keys or similar.
        kb.insert(InlineKeyboardButton(text=f"Join Channel {idx}", url=f"https://t.me/{uname.lstrip('@')}"))
    kb.add(InlineKeyboardButton(text="✅ Verify", callback_data="verify"))
    kb.add(InlineKeyboardButton(text="▶️ Start", callback_data="start_claim"))
    return kb


# ====== BOT COMMANDS & HANDLERS ======
@dp.message_handler(commands=["start"])
async def cmd_start(message: types.Message):
    await ensure_user_record(message.from_user)
    kb = await build_start_verify_keyboard()
    text = ("Welcome! To claim a free key, join the required channels listed below.\n\n"
            "After joining press ✅ Verify, then press ▶️ Start to claim a key (one key per cooldown period).")
    await message.answer(text, reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data == "verify")
async def cb_verify(cq: types.CallbackQuery):
    user = cq.from_user
    await ensure_user_record(user)
    channels = await list_channels()
    not_joined = []
    for ch in channels:
        try:
            member = await bot.get_chat_member(ch, user.id)
            status = getattr(member, "status", "")
            if status in ("left", "kicked"):
                not_joined.append(ch)
        except Exception as e:
            logging.warning("Error checking membership %s in %s: %s", user.id, ch, e)
            # if bot can't check, consider not joined (more conservative)
            not_joined.append(ch)
    if not_joined:
        text = "You have NOT joined these channels yet:\n\n"
        for i, c in enumerate(not_joined, start=1):
            text += f"{i}. {c}\n"
        await cq.answer()
        await cq.message.answer(text)
        return
    # mark verified
    await set_user_verified(user.id)
    await cq.answer("Verified ✅")
    await cq.message.answer("You are verified! Now press ▶️ Start to claim your key.")


@dp.callback_query_handler(lambda c: c.data == "start_claim")
async def cb_start_claim(cq: types.CallbackQuery):
    user = cq.from_user
    await ensure_user_record(user)
    info = await get_user_info(user.id)
    if not info:
        await cq.answer("User record missing. Try /start", show_alert=True)
        return
    verified = bool(info[2])
    last_key_time = parse_dt(info[3]) if info[3] else None
    if not verified:
        await cq.answer("You must verify first.", show_alert=True)
        return
    cooldown_hours = int(await get_setting("cooldown_hours", str(DEFAULT_COOLDOWN_HOURS)))
    now = datetime.utcnow()
    if last_key_time:
        elapsed = now - last_key_time
        if elapsed < timedelta(hours=cooldown_hours):
            remaining = timedelta(hours=cooldown_hours) - elapsed
            # format remaining
            days = remaining.days
            hours = remaining.seconds // 3600
            minutes = (remaining.seconds % 3600) // 60
            await cq.answer(f"Cooldown active. Try again in {days}d {hours}h {minutes}m.", show_alert=True)
            return
    # fetch unused key
    key = await fetch_unused_key()
    if not key:
        await cq.answer("No keys available. Admin please add keys.", show_alert=True)
        return
    # mark key used & create sale
    await mark_key_used(key["id"])
    duration_days = key["duration_days"]
    expires_at = now + timedelta(days=duration_days)
    sale_id = await create_sale(user.id, key["id"], key["key_text"], expires_at)
    # update user's last_key_time
    await set_user_last_key_time(user.id, now)
    # prepare message using template
    template = await get_setting("msg_template", "{key}\n{custom_msg}\n{meta_name}: {meta_link}\nExpires: {expires_at}\nTime left: {time_left}")
    custom_msg = await get_setting("custom_msg", "Enjoy your key!")
    meta_name = key["meta_name"] or "Link"
    meta_link = key["meta_link"] or "—"
    time_left = str(expires_at - now).split(".")[0]
    content = template.format(key=key["key_text"], custom_msg=custom_msg,
                              meta_name=meta_name, meta_link=meta_link,
                              expires_at=human_dt(expires_at), time_left=time_left)
    # send DM and store message ids for live countdown updates
    try:
        sent = await bot.send_message(user.id, content, parse_mode="Markdown")
    except Exception as e:
        logging.error("Failed to DM user %s: %s", user.id, e)
        # rollback: mark key unused & delete sale & reset last_key_time
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE keys SET used=0 WHERE id=?", (key["id"],))
            await db.execute("DELETE FROM sales WHERE id=?", (sale_id,))
            await db.execute("UPDATE users SET last_key_time=NULL WHERE user_id=?", (user.id,))
            await db.commit()
        await cq.answer("Failed to DM you. Please start the bot privately and try again.", show_alert=True)
        return
    # update sale with message ids
    await update_sale_message_ids(sale_id, sent.chat.id, sent.message_id)
    await cq.answer("Key sent via DM ✅")
    # background updater will handle countdown edits


# ===== ADMIN HANDLERS =====
@dp.message_handler(commands=["addchannel"])
async def cmd_addchannel(message: types.Message):
    if not await is_admin(message.from_user.id):
        return await message.reply("You are not admin.")
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply("Usage: /addchannel @channelusername")
    uname = parts[1].strip()
    ok = await add_channel(uname)
    if ok:
        await message.reply(f"Added channel {uname}")
    else:
        await message.reply("Failed to add channel (maybe exists).")


@dp.message_handler(commands=["listchannels"])
async def cmd_listchannels(message: types.Message):
    if not await is_admin(message.from_user.id):
        return await message.reply("You are not admin.")
    channels = await list_channels()
    if not channels:
        return await message.reply("No channels set.")
    text = "Channels:\n" + "\n".join(f"{i+1}. {c}" for i, c in enumerate(channels))
    await message.reply(text)


@dp.message_handler(commands=["addkeys"])
async def cmd_addkeys(message: types.Message):
    """
    /addkeys <duration_days>
    Then send a message with keys one per line OR upload a .txt file.
    Optional format per line: key_text|meta_name|meta_link
    """
    if not await is_admin(message.from_user.id):
        return await message.reply("You are not admin.")
    parts = message.text.split()
    if len(parts) != 2:
        return await message.reply("Usage: /addkeys <duration_days>")
    try:
        duration = int(parts[1])
    except:
        return await message.reply("Duration must be integer (days).")
    awaiting_keys[message.from_user.id] = duration
    await message.reply(f"Send keys now (one per line). Optional per-line format: key|meta_name|meta_link\nDuration: {duration} days")


@dp.message_handler(lambda m: m.from_user.id in awaiting_keys)
async def process_bulk_keys(message: types.Message):
    admin_id = message.from_user.id
    if not await is_admin(admin_id):
        awaiting_keys.pop(admin_id, None)
        return
    duration = awaiting_keys.pop(admin_id, None)
    keys_list = []
    if message.text:
        lines = message.text.strip().splitlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split("|")]
            key_text = parts[0]
            meta_name = parts[1] if len(parts) >= 2 else None
            meta_link = parts[2] if len(parts) >= 3 else None
            keys_list.append({"key_text": key_text, "duration_days": duration, "meta_name": meta_name, "meta_link": meta_link})
    elif message.document:
        # try to download .txt
        file = await bot.get_file(message.document.file_id)
        b = await bot.download_file(file.file_path)
        raw = b.read().decode(errors="ignore")
        lines = raw.strip().splitlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split("|")]
            key_text = parts[0]
            meta_name = parts[1] if len(parts) >= 2 else None
            meta_link = parts[2] if len(parts) >= 3 else None
            keys_list.append({"key_text": key_text, "duration_days": duration, "meta_name": meta_name, "meta_link": meta_link})
    if not keys_list:
        return await message.reply("No valid keys found. Cancelled.")
    await bulk_add_keys(keys_list)
    await message.reply(f"Inserted {len(keys_list)} keys.")


@dp.message_handler(commands=["setmsg"])
async def cmd_setmsg(message: types.Message):
    """
    /setmsg <template>
    Placeholders: {key}, {custom_msg}, {meta_name}, {meta_link}, {expires_at}, {time_left}
    """
    if not await is_admin(message.from_user.id):
        return await message.reply("You are not admin.")
    payload = message.text.partition(" ")[2]
    if not payload:
        return await message.reply("Usage: /setmsg <template>")
    await set_setting("msg_template", payload)
    await message.reply("Template updated.")


@dp.message_handler(commands=["setcustommsg"])
async def cmd_setcustommsg(message: types.Message):
    if not await is_admin(message.from_user.id):
        return await message.reply("You are not admin.")
    payload = message.text.partition(" ")[2]
    if not payload:
        return await message.reply("Usage: /setcustommsg <text>")
    await set_setting("custom_msg", payload)
    await message.reply("Custom message set.")


@dp.message_handler(commands=["broadcast"])
async def cmd_broadcast(message: types.Message):
    if not await is_admin(message.from_user.id):
        return await message.reply("You are not admin.")
    text = message.text.partition(" ")[2]
    if not text:
        return await message.reply("Usage: /broadcast <message>")
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users")
        rows = await cur.fetchall()
    user_ids = [r[0] for r in rows]
    await message.reply(f"Broadcasting to {len(user_ids)} users...")
    sent = 0
    for uid in user_ids:
        try:
            await bot.send_message(uid, text)
            sent += 1
        except Exception:
            pass
        await asyncio.sleep(0.08)  # small delay
    await message.reply(f"Broadcast finished. Sent to ~{sent} users.")


@dp.message_handler(commands=["stats"])
async def cmd_stats(message: types.Message):
    if not await is_admin(message.from_user.id):
        return await message.reply("You are not admin.")
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM users")
        total_users = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COUNT(*) FROM users WHERE verified=1")
        verified = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COUNT(*) FROM keys WHERE used=0")
        keys_left = (await cur.fetchone())[0]
        cur = await db.execute("SELECT COUNT(*) FROM sales WHERE active=1")
        active_sales = (await cur.fetchone())[0]
    await message.reply(f"Users: {total_users}\nVerified: {verified}\nKeys left: {keys_left}\nActive keys: {active_sales}")


@dp.message_handler(commands=["resetcooldown"])
async def cmd_resetcooldown(message: types.Message):
    """
    /resetcooldown all
    /resetcooldown <user_id>
    """
    if not await is_admin(message.from_user.id):
        return await message.reply("You are not admin.")
    parts = message.text.split()
    if len(parts) != 2:
        return await message.reply("Usage: /resetcooldown all OR /resetcooldown <user_id>")
    target = parts[1]
    if target == "all":
        await reset_cooldown_all()
        await message.reply("Reset cooldown for ALL users.")
    else:
        try:
            uid = int(target)
            await reset_cooldown_user(uid)
            await message.reply(f"Reset cooldown for user {uid}.")
        except:
            await message.reply("Invalid user id.")


@dp.message_handler(commands=["users"])
async def cmd_users(message: types.Message):
    if not await is_admin(message.from_user.id):
        return await message.reply("You are not admin.")
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id, username, verified, last_key_time FROM users ORDER BY user_id DESC LIMIT 100")
        rows = await cur.fetchall()
    text = "Recent users:\n"
    for r in rows:
        text += f"{r[0]} | @{r[1]} | verified={r[2]} | last_key={r[3]}\n"
    await message.reply(text)


# ====== BACKGROUND TASK: update assigned messages (countdown) & expiry ======
async def assigned_messages_updater():
    await bot.wait_until_ready()
    while True:
        now = datetime.utcnow()
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute("SELECT id, user_id, key_text, expires_at, message_chat_id, message_id FROM sales WHERE active=1 AND message_id IS NOT NULL")
                rows = await cur.fetchall()
                for r in rows:
                    sale_id, user_id, key_text, expires_at_s, chat_id, msg_id = r
                    expires_at = parse_dt(expires_at_s)
                    if not expires_at:
                        continue
                    if now >= expires_at:
                        # expired
                        await db.execute("UPDATE sales SET active=0 WHERE id=?", (sale_id,))
                        # notify user (best-effort)
                        try:
                            await bot.send_message(user_id, f"⏰ Your key `{key_text}` has expired.", parse_mode="Markdown")
                        except:
                            pass
                        continue
                    time_left = str(expires_at - now).split(".")[0]
                    template = await get_setting("msg_template")
                    custom_msg = await get_setting("custom_msg", "Enjoy your key!")
                    # fetch meta_name/meta_link from keys table
                    cur2 = await db.execute("SELECT meta_name, meta_link FROM keys WHERE key_text=?", (key_text,))
                    meta = await cur2.fetchone()
                    meta_name = (meta[0] if meta and meta[0] else "Link")
                    meta_link = (meta[1] if meta and meta[1] else "—")
                    content = template.format(key=key_text, custom_msg=custom_msg, meta_name=meta_name, meta_link=meta_link,
                                              expires_at=human_dt(expires_at), time_left=time_left)
                    try:
                        await bot.edit_message_text(content, chat_id=chat_id, message_id=msg_id, parse_mode="Markdown")
                    except Exception:
                        # ignore edit errors (user deleted message, blocked bot, etc.)
                        pass
                await db.commit()
        except Exception as e:
            logging.exception("Updater error: %s", e)
        await asyncio.sleep(60)


# ====== STARTUP ======
async def on_startup(dispatcher):
    await init_db()
    logging.info("Bot started")
    asyncio.create_task(assigned_messages_updater())


if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
