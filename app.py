import sys
import asyncio

# Ensure a compatible event loop policy on Windows and that an event loop
# exists (pyrogram.sync calls `asyncio.get_event_loop()` at import time).
if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

# Create and set a new event loop if there's no current loop (prevents RuntimeError)
try:
    asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message as _PyroMessage
from pyrogram.errors import FloodWait
from pyrogram.raw import functions, types as raw_types
import sqlite3
import random
import string
import asyncio
import os
import re
import time
import aiohttp
from datetime import datetime
import pytz

SL_TZ = pytz.timezone("Asia/Colombo")

# A collection of sticker file_ids to pick randomly from for cute replies
STICKER_IDS = [
    "CAACAgIAAxkBAAERc_lqPrHjkYKmBYKYpj1pBhcTaJcP3AAC0hMAAtN88EvLRd2kOgb2sjwE",
    "CAACAgIAAxkBAAERc_dqPrHca1dnGYKlMhoHfaCwvYHbtAACHBQAAr8C-Eu4VGifF2XDXTwE",
    "CAACAgIAAxkBAAERc_NqPq3M6SpmyJdNENeLk1nY3L68UwACqhUAAlFv-UsUBf1q0D3UJzwE",
    "CAACAgIAAxkBAAERc-9qPq2q2njGddY7jjz0nyXkhy6oIAACrRYAAjBR8Uvwp-vZf5cw-TwE",
    "CAACAgIAAxkBAAERc-1qPq2hPn277mqFOGsY5TnLMyhdDwAC1BkAAjuo-EtIoO1-m_9EvzwE",
    "CAACAgIAAxkBAAERc-tqPq2Yu7E5l5vfZ2tJSmNp5INIOAACiBQAAoyH8EsJWVM-bzCz8DwE",
    "CAACAgIAAxkBAAERc-lqPq2HWbsfJujQ_mczetE-53KoawACqxcAAoeZ-EunUqLOfritAzwE",
    "CAACAgIAAxkBAAERc-VqPqyma2y7z-AtGStT9cleTbR4SgACrxQAAnJ-8EuCrNbKw8XQkDwE",
]


async def send_random_sticker(client, chat_id):
    """Send a random sticker from STICKER_IDS to chat_id. Safe no-op on error."""
    try:
        sticker = random.choice(STICKER_IDS)
        await client.send_sticker(chat_id=chat_id, sticker=sticker)
    except Exception as e:
        print(f"Sticker send error: {e}")


def _next_pinned_key(existing_rows):
    if not existing_rows:
        return "storage_index_0001"
    last_key = existing_rows[-1][0]
    if last_key == "storage_index":
        return "storage_index_0002"
    m = re.search(r"storage_index_(\d+)", last_key)
    if m:
        return f"storage_index_{int(m.group(1)) + 1:04d}"
    return "storage_index_0001"

async def _backup_pinned_text(pin_key, message_id, text):
    try:
        cursor.execute(
            "INSERT INTO pinned_backup (pin_key, message_id, appended_text, created_at) VALUES (?,?,?,?)",
            (pin_key, message_id, text, int(time.time()))
        )
        db.commit()
    except Exception as e:
        print(f"Could not save pinned backup: {e}")


def _recover_pinned_message_text(pin_key, message_id):
    try:
        cursor.execute(
            "SELECT appended_text FROM pinned_backup WHERE pin_key=? ORDER BY created_at",
            (pin_key,)
        )
        rows = cursor.fetchall()
        if not rows:
            return None
        return "\n\n".join(r[0] for r in rows if r[0])
    except Exception as e:
        print(f"Could not recover pinned backup text: {e}")
        return None


async def append_to_pinned_storage(client, text):
    """Append `text` to a chain of pinned messages in STORAGE_CHANNEL.
    If the current pinned message is full or cannot be edited, create a new one.
    Returns the pinned message_id that received the text."""
    try:
        cursor.execute("SELECT key, message_id FROM pinned_index WHERE key LIKE 'storage_index%' ORDER BY key")
        rows = cursor.fetchall()
        if rows:
            last_key, last_msg_id = rows[-1]
            old = None
            try:
                existing = await client.get_messages(STORAGE_CHANNEL, last_msg_id)
                old = existing.text or ""
            except Exception as e:
                print(f"Could not fetch pinned storage message: {e}")
                recovered = _recover_pinned_message_text(last_key, last_msg_id)
                if recovered is not None:
                    old = recovered

            if old is not None:
                candidate = old + "\n\n" + text
                if len(candidate) <= 3800:
                    try:
                        await client.edit_message_text(STORAGE_CHANNEL, last_msg_id, candidate)
                        await _backup_pinned_text(last_key, last_msg_id, text)
                        return last_msg_id
                    except Exception as e:
                        print(f"Could not edit pinned storage message: {e}")

        new_key = _next_pinned_key(rows)
        sent = await client.send_message(STORAGE_CHANNEL, text)
        try:
            await client.pin_chat_message(STORAGE_CHANNEL, sent.id)
        except Exception as e:
            print(f"Could not pin storage message: {e}")
        try:
            cursor.execute("INSERT OR REPLACE INTO pinned_index (key, message_id) VALUES (?,?)", (new_key, sent.id))
            db.commit()
        except Exception as e:
            print(f"Could not save pinned index to DB: {e}")
        await _backup_pinned_text(new_key, sent.id, text)
        return sent.id
    except Exception as e:
        print(f"append_to_pinned_storage error: {e}")
        return None


def time_based_greeting(user_name: str | None = None):
    """Return a cute greeting depending on current SL_TZ time. Optionally include the user's name."""
    try:
        now = datetime.now(SL_TZ)
    except Exception:
        now = datetime.now()
    hour = now.hour
    if 5 <= hour < 12:
        extra = "Good morning! Have a wonderful day! ☀️"
    elif 12 <= hour < 17:
        extra = "Good afternoon! Hope your day's going great! 🌤️"
    elif 17 <= hour < 22:
        extra = "Good evening! Enjoy your night! 🌙"
    else:
        extra = "Good night! Sweet dreams when you sleep! 🌙💤"

    greet_name = f" {user_name}" if user_name else ""
    return f"🌸 Konnichiwa{greet_name}! My name is Roronoa Zoro.\n{extra}"

# Always show the reply header (quote the original message) in every chat type
_orig_reply_text = _PyroMessage.reply_text
async def _reply_text_quoted(self, text, quote=True, **kwargs):
    try:
        return await _orig_reply_text(self, text, quote=quote, **kwargs)
    except ValueError as exc:
        # Invalid parse mode can happen in some Pyrogram versions.
        if "Invalid parse mode" in str(exc):
            kwargs.pop("parse_mode", None)
            try:
                return await _orig_reply_text(self, text, quote=quote, **kwargs)
            except Exception:
                pass
    except Exception:
        pass

    if quote:
        try:
            return await _orig_reply_text(self, text, quote=False, **kwargs)
        except Exception:
            pass
    raise
_PyroMessage.reply_text = _reply_text_quoted

# =========================
# CONFIG
# =========================

import os

# Load .env file if python-dotenv is available (optional)
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# Configuration via environment variables. Set these in your environment or
# in a .env file (see .env.example). Sensitive values must be provided via
# env vars. No secrets are hardcoded here.
API_ID = int(os.getenv("API_ID", "31413348"))
API_HASH = os.getenv("API_HASH", "be555bc98b4398a2f04ba02b6268615c")

# BOT_TOKEN is required for the bot to run. Do NOT commit it to source.
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise SystemExit("Missing BOT_TOKEN environment variable. Set BOT_TOKEN and restart.")

# Bot username (without @). Optional but useful for generated links.
BOT_USERNAME = os.getenv("BOT_USERNAME", "Testxcpbotand")

# STORAGE CHANNEL and ADMIN_ID are configurable via env as well.
STORAGE_CHANNEL = int(os.getenv("STORAGE_CHANNEL", "-1003915426136"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "8789607558"))

# AUTO DELETE AFTER (seconds)
DELETE_AFTER = 10 * 60

# =========================
# DATABASE
# =========================

db = sqlite3.connect("batch.db", check_same_thread=False)
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS batches(
    code TEXT PRIMARY KEY,
    name TEXT DEFAULT '',
    start_id INTEGER,
    end_id INTEGER
)
""")

# Migrate: add name column if it doesn't exist yet
try:
    cursor.execute("ALTER TABLE batches ADD COLUMN name TEXT DEFAULT ''")
    db.commit()
except Exception:
    pass

cursor.execute("""
CREATE TABLE IF NOT EXISTS auth_users(
    user_id INTEGER PRIMARY KEY
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS users(
    user_id INTEGER PRIMARY KEY,
    username TEXT DEFAULT '',
    first_name TEXT DEFAULT '',
    last_seen INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS watchlist(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    title TEXT,
    done INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS reminders(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    chat_id INTEGER,
    text TEXT,
    remind_at INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS admins(
    user_id INTEGER PRIMARY KEY
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS requests(
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    requester_id INTEGER,
    title       TEXT,
    status      TEXT DEFAULT 'pending',
    acted_by    INTEGER,
    acted_name  TEXT,
    created_at  INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS request_msgs(
    request_id  INTEGER,
    admin_id    INTEGER,
    message_id  INTEGER,
    PRIMARY KEY (request_id, admin_id)
)
""")

db.commit()

# Add fetch_count to batches if it doesn't exist yet (safe migration)
try:
    cursor.execute("ALTER TABLE batches ADD COLUMN fetch_count INTEGER DEFAULT 0")
    db.commit()
except Exception:
    pass

# Add storage_msg_id to batches if it doesn't exist yet (safe migration)
try:
    cursor.execute("ALTER TABLE batches ADD COLUMN storage_msg_id INTEGER")
    db.commit()
except Exception:
    pass

try:
    cursor.execute("ALTER TABLE name_mappings ADD COLUMN storage_msg_ids TEXT")
    db.commit()
except Exception:
    pass

try:
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS name_mappings(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        english_name TEXT,
        original_names TEXT,
        storage_msg_id INTEGER,
        storage_msg_ids TEXT,
        created_at INTEGER
    )
    """)
    db.commit()
except Exception:
    pass

try:
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pinned_index(
        key TEXT PRIMARY KEY,
        message_id INTEGER
    )
    """)
    db.commit()
except Exception:
    pass

try:
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pinned_backup(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pin_key TEXT,
        message_id INTEGER,
        appended_text TEXT,
        created_at INTEGER
    )
    """)
    db.commit()
except Exception:
    pass

# =========================
# AUTH HELPERS
# =========================

def is_admin(user_id):
    if user_id == ADMIN_ID:
        return True
    cursor.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,))
    return cursor.fetchone() is not None

def is_authorized(user_id):
    if is_admin(user_id):
        return True
    cursor.execute("SELECT 1 FROM auth_users WHERE user_id=?", (user_id,))
    return cursor.fetchone() is not None

# Custom Pyrogram filter linking to your database auth helper
async def check_auth_filter(_, __, update):
    return is_authorized(update.from_user.id)

is_auth = filters.create(check_auth_filter)

# Commands that require authorization (used for unauthorized fallback below)
_AUTH_COMMANDS = [
    "search", "anime", "trending", "upcoming", "top", "random",
    "anime_genres", "watch", "watchlist", "remind", "reminders",
    "myfiles", "clear"
]

# =========================
# ANIME GENRE CONFIG & STORAGE
# =========================

# AniList genre list (free GraphQL API, no key needed)
GENRES = [
    "Action", "Adventure", "Comedy", "Drama", "Ecchi", "Fantasy",
    "Horror", "Mahou Shoujo", "Mecha", "Music", "Mystery", "Psychological",
    "Romance", "Sci-Fi", "Slice of Life", "Sports", "Supernatural", "Thriller"
]

ANILIST_URL = "https://graphql.anilist.co"

async def anilist_query(query, variables=None):
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(ANILIST_URL, json=payload) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data.get("data")
    except Exception:
        return None

def genre_to_cb(genre):
    return genre.replace(" ", "_")

def cb_to_genre(cb):
    return cb.replace("_", " ")

user_selections = {}

def build_genre_keyboard(user_id):
    """Dynamically builds the inline keyboard with checkmarks for selected genres."""
    selected = user_selections.get(user_id, [])
    keyboard = []
    row = []
    
    for name in GENRES:
        text = f"✅ {name}" if name in selected else name
        row.append(InlineKeyboardButton(text, callback_data=f"genre_{genre_to_cb(name)}"))
        
        if len(row) == 3:
            keyboard.append(row)
            row = []
            
    if row:
        keyboard.append(row)
        
    # Bottom Action Buttons
    keyboard.append([
        InlineKeyboardButton("🔍 Find Top Anime", callback_data="search_anime")
    ])
    keyboard.append([
        InlineKeyboardButton("🗑️ Clear Checkmarks", callback_data="clear_genres"),
        InlineKeyboardButton("❌ Close Menu", callback_data="close_menu")
    ])
    
    return InlineKeyboardMarkup(keyboard)

# =========================
# BOT
# =========================

app = Client(
    "batch_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# Fallback for unauthorized users attempting auth-required commands
@app.on_message(filters.command(_AUTH_COMMANDS) & ~is_auth, group=1)
async def unauthorized_cmd_handler(client, message):
    await message.reply_text(
        "🔒 **Access Denied**\n\n"
        "This command requires an **SL Animebay Premium** plan.\n\n"
        "💎 **Get Premium Access:**\n"
        "Contact **@NexusExon** to purchase a plan and unlock:\n"
        "• Batch search by name\n"
        "• View and delete your current file deliveries\n\n"
        "_Already a member? Ask an admin to activate your account._"
    )

# =========================
# RANDOM CODE
# =========================

def generate_code(length=10):
    return ''.join(
        random.choices(
            string.ascii_letters + string.digits,
            k=length
        )
    )

# =========================
# AUTO DELETE
# =========================

async def delete_messages_later(client, chat_id, message_ids):
    await asyncio.sleep(DELETE_AFTER)
    try:
        await client.delete_messages(chat_id=chat_id, message_ids=message_ids)
    except Exception as e:
        print(f"Auto-delete error: {e}")

# Stores pending manual deletes for authorized users: key -> (chat_id, [msg_ids])
pending_deletes = {}

# Stores forwarded upload sessions from admins: user_id -> { 'msgs': [Message], 'status_id': int, 'status_chat_id': int }
pending_uploads = {}

# =========================
# START COMMAND
# =========================

@app.on_message(filters.command("start"))
async def start(client, message):

    # Send a cute random sticker first, then the start message
    try:
        await send_random_sticker(client, message.chat.id)
    except Exception:
        pass

    if len(message.command) == 1:
        first = (message.from_user.first_name or "").strip()
        greeting = time_based_greeting(first)
        await message.reply_text(greeting)
        return

    param = message.command[1]

    if not param.startswith("batch_"):
        return

    code = param.split("_", 1)[1]

    cursor.execute(
        "SELECT code, name, start_id, end_id FROM batches WHERE code=?",
        (code,)
    )

    data = cursor.fetchone()

    if not data:
        await message.reply_text("Batch not found.")
        return

    _, name, start_id, end_id = data

    user_id = message.from_user.id
    authorized = is_authorized(user_id)

    cursor.execute(
        "INSERT OR REPLACE INTO users(user_id, username, first_name, last_seen) VALUES(?,?,?,?)",
        (
            user_id,
            message.from_user.username or "",
            message.from_user.first_name or "",
            int(time.time()),
        )
    )
    cursor.execute("UPDATE batches SET fetch_count = fetch_count + 1 WHERE code=?", (code,))
    db.commit()

    title_line = f"**{name}**\n\n" if name else ""
    if authorized:
        notice_text = (
            f"{title_line}"
            "✨ Yay! Sending your episodes now — enjoy!"
        )
    else:
        notice_text = (
            f"{title_line}"
            "⚠️ These files will be **automatically deleted in 10 minutes**.\n"
            "Please save them before then!\n\n"
            "Sending episodes... Please wait."
        )

    notice = await message.reply_text(notice_text)
    sent_ids = [notice.id]

    # SEND ALL EPISODES WITH FLOOD CONTROL
    for msg_id in range(start_id, end_id + 1):
        while True:
            try:
                sent = await client.copy_message(
                    chat_id=message.chat.id,
                    from_chat_id=STORAGE_CHANNEL,
                    message_id=msg_id
                )
                sent_ids.append(sent.id)
                await asyncio.sleep(0.5)
                break

            except FloodWait as e:
                print(f"FloodWait: sleeping {e.value}s")
                await asyncio.sleep(e.value)

            except Exception as e:
                print(f"Error sending msg {msg_id}: {e}")
                break

    if authorized:
        del_key = generate_code(12)
        pending_deletes[del_key] = (message.chat.id, list(sent_ids))
        done_msg = await message.reply_text(
            "✅ Done! Enjoy watching.\n\n"
            "🗑 Use the button below when you want to delete these files.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑️ Delete Files", callback_data=f"manualdelete_{del_key}")]
            ])
        )
        pending_deletes[del_key] = (message.chat.id, user_id, name, sent_ids + [done_msg.id])
    else:
        done_msg = await message.reply_text(
            "✅ Done! Enjoy watching.\n\n"
            "🗑 Files will be deleted in **10 minutes**. Save them now!"
        )
        sent_ids.append(done_msg.id)
        asyncio.create_task(
            delete_messages_later(client, message.chat.id, sent_ids)
        )

# =========================
# HELP COMMAND
# =========================

@app.on_message(filters.command("help"))
async def help_cmd(client, message):
    user_id = message.from_user.id

    common = (
        "📖 <b>Help — Commands</b>\n\n"
        "🔎 <b>Search & Batches</b>\n"
        "• <code>/search &lt;name&gt;</code> — Search for a batch by name\n"
        "• <code>/myfiles</code> — View or delete your current file deliveries\n\n"
        "🎬 <b>Anime Discovery</b>\n"
        "• <code>/anime &lt;title&gt;</code> — Search anime details\n"
        "• <code>/trending</code> — Trending anime by type\n"
        "• <code>/upcoming</code> — Upcoming anime list\n"
        "• <code>/top</code> — Top anime by genre\n"
        "• <code>/random</code> — Get a random anime recommendation\n"
        "• <code>/anime_genres</code> — Filter anime by genres\n\n"
        "📋 <b>Watchlist</b>\n"
        "• <code>/watch &lt;title&gt;</code> — Add anime to your watchlist\n"
        "• <code>/watchlist</code> — Show and manage your list\n\n"
        "⏰ <b>Reminders</b>\n"
        "• <code>/remind DD-MM-YYYY HH:MM &lt;message&gt;</code> — Set a reminder\n"
        "• <code>/reminders</code> — List your reminders\n\n"
        "💬 <b>Misc</b>\n"
        "• <code>/request &lt;title&gt;</code> — Request an anime to be added\n"
        "• <code>/clear</code> — Reply to any bot message to delete it\n"
    )

    admin = (
        "\n━━━━━━━━━━━━━━━\n"
        "🔧 <b>Admin Commands</b>\n"
        "• <code>/batch &lt;start&gt; &lt;end&gt; &lt;name&gt;</code> — Create a new batch\n"
        "• <code>/blink &lt;English name&gt;</code> — Generate/get batch links for saved English mapping\n"
        "• <code>/listbatches</code> — List batches and manage them\n"
        "• <code>/delete &lt;code&gt;</code> — Delete a batch by code\n"
        "• <code>/addauth &lt;id&gt;</code> — Authorize a user\n"
        "• <code>/removeauth &lt;id&gt;</code> — Remove a user authorization\n"
        "• <code>/authlist</code> — List authorized users\n"
        "• <code>/requests</code> — Manage anime requests\n"
        "• <code>/cancelupload</code> — Cancel the current upload session\n"
    )

    super_admin = (
        "\n━━━━━━━━━━━━━━━\n"
        "👑 <b>Super Admin Commands</b>\n"
        "• <code>/addadmin &lt;id&gt;</code> — Add a new admin\n"
        "• <code>/removeadmin &lt;id&gt;</code> — Remove an admin\n"
        "• <code>/adminlist</code> — List admins\n"
        "• <code>/broadcast</code> — Send an announcement\n"
        "• <code>/stats</code> — Show bot stats\n"
        "• <code>/status</code> — Show last sync status\n"
    )

    text = common
    if is_admin(user_id):
        text += admin
    if user_id == ADMIN_ID:
        text += super_admin

    await message.reply_text(text, parse_mode="html")


# =========================
# CREATE BATCH
# =========================

@app.on_message(filters.command("batch"))
async def batch(client, message):

    if not is_admin(message.from_user.id):
        return

    try:
        start_id = int(message.command[1])
        end_id = int(message.command[2])
        name = " ".join(message.command[3:]) if len(message.command) > 3 else ""
    except:
        await message.reply_text(
            "Usage:\n`/batch start_id end_id Anime Name Quality`\n\n"
            "Example:\n`/batch 10 22 Naruto 720p`"
        )
        return

    code = generate_code()

    cursor.execute(
        "INSERT INTO batches (code, name, start_id, end_id) VALUES (?, ?, ?, ?)",
        (code, name, start_id, end_id)
    )

    db.commit()

    link = f"https://t.me/{BOT_USERNAME}?start=batch_{code}"
    label = f"📦 {name}" if name else "📦 Open Batch"

    # Post the new batch link to the storage channel and pin it (if possible)
    storage_msg_id = None
    try:
        storage_text = f"📦 New Batch: {name or '_(no name)_'}\n\nLink: {link}"
        storage_msg_id = await append_to_pinned_storage(client, storage_text)
    except Exception as e:
        print(f"Could not post batch to storage channel: {e}")

    if storage_msg_id:
        try:
            cursor.execute("UPDATE batches SET storage_msg_id=? WHERE code=?", (storage_msg_id, code))
            db.commit()
        except Exception as e:
            print(f"Could not update batch with storage_msg_id: {e}")

    await message.reply_text(
        f"✅ Batch Created!\n\n**Name:** {name or '_(no name)_'}\n**Link:** {link}",
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton(label, url=link)]
            ]
        )
    )


async def _create_batches_from_storage(client, english_name, storage_ids):
    if not storage_ids:
        return []

    msgs = await client.get_messages(STORAGE_CHANNEL, storage_ids)
    items = []
    for m in msgs:
        if not m:
            continue
        orig = None
        if getattr(m, 'document', None):
            orig = getattr(m.document, 'file_name', None)
        if not orig and getattr(m, 'video', None):
            orig = getattr(m.video, 'file_name', None)
        if not orig:
            orig = m.caption or m.text or "(unknown)"
        season_label, episode, quality_label = _parse_file_attributes(orig)
        items.append((m.id, orig, season_label, quality_label))

    groups = {}
    for storage_id, orig, season_label, quality_label in items:
        key = (season_label, quality_label)
        groups.setdefault(key, []).append((storage_id, orig))

    created = []
    for (season_label, quality_label), group_items in groups.items():
        ids = sorted([s for s, _ in group_items])
        ranges = _contiguous_ranges(ids)
        for s_id, e_id in ranges:
            code = generate_code()
            batch_name = f"{english_name} — {season_label} {quality_label}".strip()
            cursor.execute(
                "INSERT INTO batches (code, name, start_id, end_id) VALUES (?, ?, ?, ?)",
                (code, batch_name, s_id, e_id)
            )
            db.commit()

            link = f"https://t.me/{BOT_USERNAME}?start=batch_{code}"
            storage_msg_id = None
            try:
                storage_msg_id = await append_to_pinned_storage(client, f"📦 New Batch: {batch_name}\n\nLink: {link}")
            except Exception:
                pass

            if storage_msg_id:
                try:
                    cursor.execute("UPDATE batches SET storage_msg_id=? WHERE code=?", (storage_msg_id, code))
                    db.commit()
                except Exception:
                    pass

            created.append((code, batch_name, link))

    return created


@app.on_message(filters.command("blink") & (filters.private | filters.chat(STORAGE_CHANNEL)))
async def blink_command(client, message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return

    if len(message.command) < 2:
        await message.reply_text("Usage: `/blink <English name>`")
        return

    english_name = " ".join(message.command[1:]).strip()
    if not english_name:
        await message.reply_text("Usage: `/blink <English name>`")
        return

    search_pattern = english_name + "%"
    cursor.execute(
        "SELECT code, name FROM batches WHERE LOWER(name) LIKE LOWER(?) ORDER BY name",
        (search_pattern,)
    )
    rows = cursor.fetchall()

    if rows:
        lines = [f"✅ Batch link(s) for '{english_name}':"]
        for code, batch_name in rows:
            link = f"https://t.me/{BOT_USERNAME}?start=batch_{code}"
            lines.append(f"• {batch_name} — {link}")
        await message.reply_text("\n".join(lines))
        return

    cursor.execute(
        "SELECT original_names, storage_msg_ids FROM name_mappings WHERE LOWER(english_name)=LOWER(?)",
        (english_name,)
    )
    mapping = cursor.fetchone()
    if not mapping:
        await message.reply_text(
            "No saved English mapping or batch found for that name. "
            "Make sure the name matches exactly or create it first via the forward/save flow."
        )
        return

    original_names = []
    storage_ids = []
    try:
        original_names = _json.loads(mapping[0] or "[]")
    except Exception:
        original_names = []
    try:
        storage_ids = _json.loads(mapping[1] or "[]")
    except Exception:
        storage_ids = []

    created = []
    if storage_ids:
        created = await _create_batches_from_storage(client, english_name, storage_ids)
    
    if not created and original_names:
        # fallback: search storage channel for messages matching original filenames
        history = await client.get_history(STORAGE_CHANNEL, limit=200)
        matched_ids = []
        for m in history:
            orig = None
            if getattr(m, 'document', None):
                orig = getattr(m.document, 'file_name', None)
            if not orig and getattr(m, 'video', None):
                orig = getattr(m.video, 'file_name', None)
            if not orig:
                orig = m.caption or m.text or ""
            if orig and any(name in orig for name in original_names):
                matched_ids.append(m.id)
        if matched_ids:
            created = await _create_batches_from_storage(client, english_name, matched_ids)

    if created:
        lines = [f"✅ Created batch link(s) for '{english_name}':"]
        for code, batch_name, link in created:
            lines.append(f"• {batch_name} — {link}")
        await message.reply_text("\n".join(lines))
        return

    await message.reply_text(
        "No batch links could be generated for that English name. "
        "Please make sure the mapped files still exist in the storage channel."
    )


@app.on_message((filters.document | filters.video | filters.audio | filters.photo | filters.voice) & filters.private)
async def collect_forwarded_files(client, message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return

    await message.reply_text(
        "Please forward files directly into the storage channel. "
        "After forwarding the files there, send me the English name in private to save them as one collection."
    )


@app.on_message((filters.document | filters.video | filters.audio | filters.photo | filters.voice) & filters.chat(STORAGE_CHANNEL))
async def collect_storage_forwarded_files(client, message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return

    session = pending_uploads.setdefault(user_id, {"msgs": [], "status_id": None, "status_chat_id": None})
    session["msgs"].append(message)
    count = len(session["msgs"])

    status_text = f"Received {count} file(s) in storage channel. When finished, send the English name for these files to me in private to save them as one collection, or send /cancelupload to cancel."

    try:
        stored_chat = session.get("status_chat_id")
        stored_id = session.get("status_id")
        if stored_id and stored_chat:
            try:
                await client.edit_message_text(chat_id=stored_chat, message_id=stored_id, text=status_text)
            except Exception:
                try:
                    await client.delete_messages(chat_id=stored_chat, message_ids=[stored_id])
                except Exception:
                    pass
                sent = await client.send_message(STORAGE_CHANNEL, status_text)
                session["status_id"] = sent.id
                session["status_chat_id"] = STORAGE_CHANNEL
        else:
            sent = await client.send_message(STORAGE_CHANNEL, status_text)
            session["status_id"] = sent.id
            session["status_chat_id"] = STORAGE_CHANNEL
    except Exception as exc:
        print(f"collect_storage_forwarded_files: unexpected error: {exc}")


@app.on_message(filters.command("cancelupload") & filters.private)
async def cancel_upload(client, message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return
    session = pending_uploads.pop(user_id, None)
    if session:
        # remove status message if exists
        status_id = session.get("status_id")
        status_chat = session.get("status_chat_id")
        if status_id and status_chat:
            try:
                await client.delete_messages(chat_id=status_chat, message_ids=[status_id])
            except Exception:
                pass
        await message.reply_text("Upload session cancelled and files discarded.")
    else:
        await message.reply_text("No active upload session to cancel.")


async def _save_pending_uploads(client, message, english_name):
    user_id = message.from_user.id
    session = pending_uploads.pop(user_id, None)
    if not session:
        await message.reply_text("No pending upload session found.")
        return

    msgs = session.get("msgs", [])
    status_id = session.get("status_id")
    status_chat = session.get("status_chat_id")

    private_status_id = None
    private_status_chat = None

    if status_id and status_chat:
        try:
            await client.edit_message_text(chat_id=status_chat, message_id=status_id,
                                           text=f"Saving {len(msgs)} file(s) as '{english_name}'... This may take a moment.")
        except Exception:
            try:
                await client.delete_messages(chat_id=status_chat, message_ids=[status_id])
            except Exception:
                pass
            status_id = None
            status_chat = None

    if not msgs:
        if status_id and status_chat:
            try:
                await client.delete_messages(chat_id=status_chat, message_ids=[status_id])
            except Exception:
                pass
        await message.reply_text("No files found to save.")
        return

    try:
        sent_private = await message.reply_text(
            f"Saving {len(msgs)} file(s) as '{english_name}'... This may take a moment."
        )
        private_status_id = sent_private.id
        private_status_chat = message.chat.id
    except Exception:
        pass

    copied = []
    for m in msgs:
        if m.chat.id != STORAGE_CHANNEL:
            continue

        orig = None
        if getattr(m, 'document', None):
            orig = getattr(m.document, 'file_name', None)
        if not orig and getattr(m, 'video', None):
            orig = getattr(m.video, 'file_name', None)
        if not orig:
            orig = m.caption or m.text or "(unknown)"

        storage_id = m.id
        season_label, episode, quality_label = _parse_file_attributes(orig)
        copied.append((storage_id, orig, season_label, quality_label))

    if not copied:
        if status_id and status_chat:
            try:
                await client.delete_messages(chat_id=status_chat, message_ids=[status_id])
            except Exception:
                pass
        await message.reply_text("No files in the storage channel were found to save.")
        return

    groups = {}
    all_originals = []
    created = []
    for storage_id, orig, season_label, quality_label in copied:
        key = (season_label, quality_label)
        groups.setdefault(key, []).append((storage_id, orig))

    for (season_label, quality_label), items in groups.items():
        all_originals.extend([o for _, o in items])
        ids = sorted([s for s, _ in items])
        ranges = _contiguous_ranges(ids)
        for s_id, e_id in ranges:
            code = generate_code()
            batch_name = f"{english_name} — {season_label} {quality_label}".strip()
            cursor.execute(
                "INSERT INTO batches (code, name, start_id, end_id) VALUES (?, ?, ?, ?)",
                (code, batch_name, s_id, e_id)
            )
            db.commit()

            link = f"https://t.me/{BOT_USERNAME}?start=batch_{code}"
            storage_msg_id = None
            try:
                storage_msg_id = await append_to_pinned_storage(client, f"📦 New Batch: {batch_name}\n\nLink: {link}")
            except Exception:
                pass

            if storage_msg_id:
                try:
                    cursor.execute("UPDATE batches SET storage_msg_id=? WHERE code=?", (storage_msg_id, code))
                    db.commit()
                except Exception:
                    pass

            created.append((code, batch_name, link))

    mapping_text = f"🔖 Mapping — {english_name}\n\nOriginal filenames:\n"
    for orig in all_originals:
        mapping_text += f"• {orig}\n"
    mapping_text += "\nBatches:\n"
    for _, bname, link in created:
        mapping_text += f"• {bname} — {link}\n"

    map_msg_id = None
    try:
        map_msg_id = await append_to_pinned_storage(client, mapping_text)
    except Exception as e:
        print(f"Could not post mapping message: {e}")

    try:
        cursor.execute(
            "INSERT INTO name_mappings (english_name, original_names, storage_msg_id, storage_msg_ids, created_at) VALUES (?,?,?,?,?)",
            (english_name, _json.dumps(all_originals, ensure_ascii=False), map_msg_id,
             _json.dumps([sid for sid, _, _, _ in copied], ensure_ascii=False), int(time.time()))
        )
        db.commit()
    except Exception as e:
        print(f"Could not save name mapping to DB: {e}")

    if status_id and status_chat:
        try:
            await client.delete_messages(chat_id=status_chat, message_ids=[status_id])
        except Exception:
            pass

    if private_status_id and private_status_chat:
        try:
            await client.delete_messages(chat_id=private_status_chat, message_ids=[private_status_id])
        except Exception:
            pass

    reply_lines = [f"✅ Saved '{english_name}' and created {len(created)} batch(es):"]
    for _, bname, link in created:
        reply_lines.append(f"• {bname} — {link}")

    await message.reply_text("\n".join(reply_lines))


@app.on_message(filters.private & filters.text)
async def finish_forwarded_save(client, message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return
    if message.text.startswith("/"):
        return
    english_name = message.text.strip()
    if not english_name:
        await message.reply_text("Please send a non-empty English name.")
        return
    await _save_pending_uploads(client, message, english_name)


@app.on_message(filters.chat(STORAGE_CHANNEL) & filters.text)
async def finish_forwarded_save_channel(client, message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        return
    if message.text.startswith("/"):
        return
    english_name = message.text.strip()
    if not english_name:
        await message.reply_text("Please send a non-empty English name.")
        return
    await _save_pending_uploads(client, message, english_name)


def _parse_file_attributes(text: str):
    """Extract season, episode, and quality info from a filename or caption."""
    txt = (text or "").upper()
    season = None
    episode = None
    quality = None

    # Season patterns: S01, SEASON 1
    m = re.search(r"S(\d{1,2})", txt)
    if m:
        season = int(m.group(1))
    else:
        m = re.search(r"SEASON\s*(\d{1,2})", txt)
        if m:
            season = int(m.group(1))

    # Episode patterns: E01, EP01
    m = re.search(r"E(\d{1,3})", txt)
    if m:
        episode = int(m.group(1))
    else:
        m = re.search(r"EP(?:ISODE)?\s*(\d{1,3})", txt)
        if m:
            episode = int(m.group(1))

    # Quality patterns: 720p, 1080p etc.
    m = re.search(r"(\d{3,4}P)", txt)
    if m:
        quality = m.group(1)

    # Specials / OVA
    if re.search(r"SPECIAL|OVA|SP\b", txt):
        season_label = "Specials"
    elif season is not None:
        season_label = f"S{season:02d}"
    else:
        season_label = "All"

    quality_label = quality or "Unknown"
    return season_label, episode, quality_label


def _contiguous_ranges(sorted_ids):
    """Split sorted message ids into contiguous ranges [(start, end), ...]."""
    if not sorted_ids:
        return []
    ranges = []
    start = prev = sorted_ids[0]
    for mid in sorted_ids[1:]:
        if mid == prev + 1:
            prev = mid
            continue
        ranges.append((start, prev))
        start = prev = mid
    ranges.append((start, prev))
    return ranges


@app.on_message(filters.command("autobatch"))
async def autobatch_range(client, message):
    """Admin command: /autobatch start_id end_id Base Name
    Scans messages in STORAGE_CHANNEL between start_id and end_id (inclusive),
    groups them by season and quality parsed from filenames/captions, creates
    batch entries per contiguous sequence, posts & pins a link in STORAGE_CHANNEL,
    and returns links to the admin.
    """
    if not is_admin(message.from_user.id):
        return

    if len(message.command) < 4:
        await message.reply_text("Usage: /autobatch <start_id> <end_id> <Base Name>")
        return

    try:
        start_id = int(message.command[1])
        end_id = int(message.command[2])
    except ValueError:
        await message.reply_text("Start and end IDs must be integers.")
        return

    base_name = " ".join(message.command[3:]).strip()

    ids = list(range(start_id, end_id + 1))
    msgs = []
    try:
        # bulk fetch
        msgs = await client.get_messages(STORAGE_CHANNEL, ids)
    except Exception as e:
        await message.reply_text(f"Could not fetch messages from storage: {e}")
        return

    groups = {}  # (season_label, quality) -> set(msg_id)

    for m in msgs:
        # get filename or caption or text
        filename = None
        if getattr(m, 'document', None):
            filename = getattr(m.document, 'file_name', None)
        if not filename and getattr(m, 'video', None):
            filename = getattr(m.video, 'file_name', None)
        if not filename:
            filename = m.caption or m.text or ""

        season_label, episode, quality_label = _parse_file_attributes(filename)
        key = (season_label, quality_label)
        groups.setdefault(key, set()).add(m.id)

    if not groups:
        await message.reply_text("No parsable files found in that range.")
        return

    created = []
    for (season_label, quality_label), mids in groups.items():
        mids_sorted = sorted(mids)
        ranges = _contiguous_ranges(mids_sorted)
        for s, e in ranges:
            code = generate_code()
            batch_name = f"{base_name} — {season_label} {quality_label}".strip()
            cursor.execute(
                "INSERT INTO batches (code, name, start_id, end_id) VALUES (?, ?, ?, ?)",
                (code, batch_name, s, e)
            )
            db.commit()

            # post link to the single pinned storage message (append)
            link = f"https://t.me/{BOT_USERNAME}?start=batch_{code}"
            storage_msg_id = None
            try:
                storage_msg_id = await append_to_pinned_storage(client, f"📦 New Batch: {batch_name}\n\nLink: {link}")
            except Exception:
                pass

            if storage_msg_id:
                try:
                    cursor.execute("UPDATE batches SET storage_msg_id=? WHERE code=?", (storage_msg_id, code))
                    db.commit()
                except Exception:
                    pass

            created.append((code, batch_name, link))

    if not created:
        await message.reply_text("No batches created.")
        return

    text_lines = ["✅ Created the following batches:"]
    for code, name, link in created:
        text_lines.append(f"• {name} — {link}")

    await message.reply_text("\n".join(text_lines))

# =========================
# DELETE BATCH
# =========================

@app.on_message(filters.command("delete"))
async def delete_batch(client, message):

    if not is_admin(message.from_user.id):
        return

    if len(message.command) < 2:
        await message.reply_text(
            "Usage:\n`/delete <code>`\n\n"
            "Get the code from the batch link — it's the part after `batch_`\n"
            "Example: `https://t.me/AnimebayFS_Bot?start=batch_xrTbNWF77w` → code is `xrTbNWF77w`\n\n"
            "Or use `/search` to find a batch and its code."
        )
        return

    code = message.command[1].strip()

    cursor.execute("SELECT name FROM batches WHERE code=?", (code,))
    row = cursor.fetchone()

    if not row:
        await message.reply_text(f"❌ No batch found with code `{code}`.")
        return

    name = row[0] or code
    cursor.execute("DELETE FROM batches WHERE code=?", (code,))
    db.commit()

    await message.reply_text(f"🗑 Batch **{name}** (`{code}`) has been deleted.")


# =========================
# LIST BATCHES COMMAND
# =========================

@app.on_message(filters.command("listbatches"))
async def listbatches(client, message):
    if not is_admin(message.from_user.id):
        return

    offset = 0
    if len(message.command) == 2:
        try:
            offset = int(message.command[1])
        except ValueError:
            pass

    PAGE = 10
    cursor.execute("SELECT code, name FROM batches ORDER BY rowid DESC LIMIT ? OFFSET ?", (PAGE + 1, offset))
    rows = cursor.fetchall()

    if not rows:
        await message.reply_text("📭 No batches found." if offset == 0 else "No more batches.")
        return

    has_more = len(rows) > PAGE
    rows = rows[:PAGE]

    nav_buttons = []
    if offset > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"lbpage_{offset - PAGE}"))
    if has_more:
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"lbpage_{offset + PAGE}"))

    buttons = []
    for code, name in rows:
        label = name or code
        link = f"https://t.me/{BOT_USERNAME}?start=batch_{code}"
        buttons.append([
            InlineKeyboardButton(f"📦 {label}", url=link),
            InlineKeyboardButton("🗑", callback_data=f"delbatch_{code}")
        ])

    if nav_buttons:
        buttons.append(nav_buttons)

    cursor.execute("SELECT COUNT(*) FROM batches")
    total = cursor.fetchone()[0]

    await message.reply_text(
        f"📋 **Batch Library** — {total} total (showing {offset + 1}–{offset + len(rows)}):",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


@app.on_callback_query(filters.regex(r"^delbatch_(.+)$"))
async def delbatch_callback(client, callback_query):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("Admins only.", show_alert=True)
        return

    code = callback_query.matches[0].group(1)
    cursor.execute("SELECT name FROM batches WHERE code=?", (code,))
    row = cursor.fetchone()

    if not row:
        await callback_query.answer("Batch already deleted.", show_alert=True)
        return

    name = row[0] or code
    cursor.execute("DELETE FROM batches WHERE code=?", (code,))
    db.commit()

    await callback_query.answer(f"🗑 \"{name}\" deleted.", show_alert=False)

    # Rebuild the list in place
    orig_text = callback_query.message.text or ""
    offset_match = re.search(r"showing (\d+)–", orig_text)
    offset = (int(offset_match.group(1)) - 1) if offset_match else 0

    PAGE = 10
    cursor.execute("SELECT code, name FROM batches ORDER BY rowid DESC LIMIT ? OFFSET ?", (PAGE + 1, offset))
    rows = cursor.fetchall()

    if not rows:
        try:
            await callback_query.message.edit_text("📭 No more batches in the library.")
        except Exception:
            pass
        return

    has_more = len(rows) > PAGE
    rows = rows[:PAGE]

    nav_buttons = []
    if offset > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"lbpage_{offset - PAGE}"))
    if has_more:
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"lbpage_{offset + PAGE}"))

    buttons = []
    for c, n in rows:
        label = n or c
        link = f"https://t.me/{BOT_USERNAME}?start=batch_{c}"
        buttons.append([
            InlineKeyboardButton(f"📦 {label}", url=link),
            InlineKeyboardButton("🗑", callback_data=f"delbatch_{c}")
        ])

    if nav_buttons:
        buttons.append(nav_buttons)

    cursor.execute("SELECT COUNT(*) FROM batches")
    total = cursor.fetchone()[0]

    try:
        await callback_query.message.edit_text(
            f"📋 **Batch Library** — {total} total (showing {offset + 1}–{offset + len(rows)}):",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception:
        pass


@app.on_callback_query(filters.regex(r"^lbpage_(\d+)$"))
async def lbpage_callback(client, callback_query):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("Admins only.", show_alert=True)
        return

    offset = int(callback_query.matches[0].group(1))
    PAGE = 10
    cursor.execute("SELECT code, name FROM batches ORDER BY rowid DESC LIMIT ? OFFSET ?", (PAGE + 1, offset))
    rows = cursor.fetchall()

    if not rows:
        await callback_query.answer("No more batches.", show_alert=True)
        return

    has_more = len(rows) > PAGE
    rows = rows[:PAGE]

    nav_buttons = []
    if offset > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"lbpage_{offset - PAGE}"))
    if has_more:
        nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"lbpage_{offset + PAGE}"))

    buttons = []
    for code, name in rows:
        label = name or code
        link = f"https://t.me/{BOT_USERNAME}?start=batch_{code}"
        buttons.append([
            InlineKeyboardButton(f"📦 {label}", url=link),
            InlineKeyboardButton("🗑", callback_data=f"delbatch_{code}")
        ])

    if nav_buttons:
        buttons.append(nav_buttons)

    cursor.execute("SELECT COUNT(*) FROM batches")
    total = cursor.fetchone()[0]

    await callback_query.answer()
    try:
        await callback_query.message.edit_text(
            f"📋 **Batch Library** — {total} total (showing {offset + 1}–{offset + len(rows)}):",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception:
        pass


# =========================
# SEARCH COMMAND (DATABASE)
# =========================

@app.on_message(filters.command("search") & is_auth)
async def search(client, message):

    if len(message.command) < 2:
        await message.reply_text(
            "Usage:\n`/search Naruto 720p`"
        )
        return

    query = " ".join(message.command[1:]).strip()
    terms = query.split()

    conditions = " AND ".join(["LOWER(name) LIKE ?" for _ in terms])
    values = [f"%{t.lower()}%" for t in terms]

    cursor.execute(
        f"SELECT code, name FROM batches WHERE {conditions} ORDER BY name",
        values
    )
    results = cursor.fetchall()

    if not results and len(terms) > 1:
        cursor.execute(
            "SELECT code, name FROM batches WHERE LOWER(name) LIKE ? ORDER BY name",
            (f"%{terms[0].lower()}%",)
        )
        results = cursor.fetchall()

    if not results:
        # small sticker to soften the blow
        await send_random_sticker(client, message.chat.id)
        await message.reply_text(f"❌ No results found for: **{query}**")
        return

    results = results[:10]

    buttons = []
    for code, name in results:
        link = f"https://t.me/{BOT_USERNAME}?start=batch_{code}"
        buttons.append([InlineKeyboardButton(name or code, url=link)])

    await send_random_sticker(client, message.chat.id)
    await message.reply_text(
        f"🔎 Here are the results for **{query}** ({len(results)} found):",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# =========================
# ADD / REMOVE AUTH USERS
# =========================

@app.on_message(filters.command("addauth"))
async def addauth(client, message):
    if not is_admin(message.from_user.id): return
    if len(message.command) < 2:
        await message.reply_text("Usage:\n`/addauth user_id`")
        return
    try: target_id = int(message.command[1])
    except:
        await message.reply_text("Invalid user ID.")
        return

    cursor.execute("INSERT OR IGNORE INTO auth_users VALUES (?)", (target_id,))
    db.commit()
    await message.reply_text(f"✅ User `{target_id}` authorized.")


@app.on_message(filters.command("removeauth"))
async def removeauth(client, message):
    if not is_admin(message.from_user.id): return
    if len(message.command) < 2:
        await message.reply_text("Usage:\n`/removeauth user_id`")
        return
    try: target_id = int(message.command[1])
    except:
        await message.reply_text("Invalid user ID.")
        return

    cursor.execute("DELETE FROM auth_users WHERE user_id=?", (target_id,))
    db.commit()
    await message.reply_text(f"✅ User `{target_id}` removed from authorized list.")


@app.on_message(filters.command("authlist"))
async def authlist(client, message):
    if not is_admin(message.from_user.id): return
    cursor.execute("SELECT user_id FROM auth_users")
    rows = cursor.fetchall()
    if not rows:
        await message.reply_text("No authorized users yet.")
        return
    ids = "\n".join(f"• `{r[0]}`" for r in rows)
    await message.reply_text(f"**Authorized users:**\n{ids}")


# =========================
# ADD / REMOVE ADMINS
# =========================

@app.on_message(filters.command("addadmin"))
async def addadmin(client, message):
    if message.from_user.id != ADMIN_ID: return
    if len(message.command) < 2:
        await message.reply_text("Usage:\n`/addadmin user_id`")
        return
    try: target_id = int(message.command[1])
    except:
        await message.reply_text("Invalid user ID.")
        return
    cursor.execute("INSERT OR IGNORE INTO admins VALUES (?)", (target_id,))
    db.commit()
    await message.reply_text(f"✅ User `{target_id}` is now an admin.")


@app.on_message(filters.command("removeadmin"))
async def removeadmin(client, message):
    if message.from_user.id != ADMIN_ID: return
    if len(message.command) < 2:
        await message.reply_text("Usage:\n`/removeadmin user_id`")
        return
    try: target_id = int(message.command[1])
    except:
        await message.reply_text("Invalid user ID.")
        return
    if target_id == ADMIN_ID:
        await message.reply_text("❌ Cannot remove the super admin.")
        return
    cursor.execute("DELETE FROM admins WHERE user_id=?", (target_id,))
    db.commit()
    await message.reply_text(f"✅ User `{target_id}` removed from admins.")


@app.on_message(filters.command("adminlist"))
async def adminlist(client, message):
    if message.from_user.id != ADMIN_ID: return
    cursor.execute("SELECT user_id FROM admins")
    rows = cursor.fetchall()
    lines = [f"• `{ADMIN_ID}` _(super admin)_"]
    lines += [f"• `{r[0]}`" for r in rows]
    await message.reply_text(f"**Admins ({len(lines)} total):**\n" + "\n".join(lines))


# =========================
# REQUESTS LIST (ADMIN)
# =========================

PAGE_SIZE = 8

def _requests_text_and_buttons(status_filter, offset):
    if status_filter == "all":
        cursor.execute(
            "SELECT id, title, requester_id, status, acted_name, created_at "
            "FROM requests ORDER BY id DESC LIMIT ? OFFSET ?",
            (PAGE_SIZE + 1, offset)
        )
    else:
        cursor.execute(
            "SELECT id, title, requester_id, status, acted_name, created_at "
            "FROM requests WHERE status=? ORDER BY id DESC LIMIT ? OFFSET ?",
            (status_filter, PAGE_SIZE + 1, offset)
        )
    rows = cursor.fetchall()
    has_next = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]

    if not rows:
        text = "📭 No requests found."
    else:
        icons = {"pending": "⏳", "noted": "✅", "na": "❌"}
        lines = []
        for req_id, title, req_uid, sts, acted, created_at in rows:
            icon = icons.get(sts, "❓")
            ts = datetime.fromtimestamp(created_at, tz=SL_TZ).strftime("%d %b %H:%M") if created_at else "?"
            actor = f" · by {acted}" if acted else ""
            lines.append(f"{icon} `#{req_id}` **{title}**\n    👤 `{req_uid}` · {ts}{actor}")
        label = status_filter.upper() if status_filter != "all" else "ALL"
        text = f"📥 **Requests — {label}** (page {offset // PAGE_SIZE + 1})\n\n" + "\n\n".join(lines)

    filters_row = [
        InlineKeyboardButton("📋 All",     callback_data="reqlist_all_0"),
        InlineKeyboardButton("⏳ Pending", callback_data="reqlist_pending_0"),
        InlineKeyboardButton("✅ Noted",   callback_data="reqlist_noted_0"),
        InlineKeyboardButton("❌ N/A",     callback_data="reqlist_na_0"),
    ]
    nav_row = []
    if offset > 0:
        nav_row.append(InlineKeyboardButton("◀️ Prev", callback_data=f"reqlist_{status_filter}_{offset - PAGE_SIZE}"))
    if has_next:
        nav_row.append(InlineKeyboardButton("Next ▶️", callback_data=f"reqlist_{status_filter}_{offset + PAGE_SIZE}"))

    buttons = [filters_row]
    if nav_row:
        buttons.append(nav_row)
    return text, InlineKeyboardMarkup(buttons)


@app.on_message(filters.command("requests"))
async def requests_list(client, message):
    if not is_admin(message.from_user.id):
        return
    text, markup = _requests_text_and_buttons("pending", 0)
    await message.reply_text(text, reply_markup=markup)


@app.on_callback_query(filters.regex(r"^reqlist_(all|pending|noted|na)_(\d+)$"))
async def requests_list_callback(client, callback_query):
    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("Admins only.", show_alert=True)
        return
    sf     = callback_query.matches[0].group(1)
    offset = int(callback_query.matches[0].group(2))
    text, markup = _requests_text_and_buttons(sf, offset)
    await callback_query.message.edit_text(text, reply_markup=markup)
    await callback_query.answer()


# =========================
# REQUEST COMMAND
# =========================

@app.on_message(filters.command("request"))
async def request_cmd(client, message):
    if len(message.command) < 2:
        await message.reply_text(
            "Usage: `/request <anime title>`\n"
            "Example: `/request Demon Slayer Season 4`"
        )
        return

    title = " ".join(message.command[1:]).strip()
    user = message.from_user
    name_display = (user.first_name or "") + (f" {user.last_name}" if user.last_name else "")
    username_part = f" (@{user.username})" if user.username else ""
    chat_name = getattr(message.chat, "title", None) or "Private DM"

    # Create a central record for this request
    cursor.execute(
        "INSERT INTO requests(requester_id, title, status, created_at) VALUES(?,?,?,?)",
        (user.id, title, "pending", int(time.time()))
    )
    db.commit()
    req_id = cursor.lastrowid

    notif_text = (
        f"📥 **New Anime Request** `#{req_id}`\n\n"
        f"🎬 **Title:** {title}\n"
        f"👤 **From:** {name_display}{username_part}\n"
        f"🆔 **User ID:** `{user.id}`\n"
        f"💬 **Chat:** {chat_name}"
    )
    buttons = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Noted",         callback_data=f"reqack_noted_{req_id}"),
        InlineKeyboardButton("❌ Not Available", callback_data=f"reqack_na_{req_id}"),
    ]])

    cursor.execute("SELECT user_id FROM admins")
    all_admin_ids = list({ADMIN_ID} | {r[0] for r in cursor.fetchall()})
    for aid in all_admin_ids:
        try:
            sent = await client.send_message(aid, notif_text, reply_markup=buttons)
            cursor.execute(
                "INSERT OR IGNORE INTO request_msgs(request_id, admin_id, message_id) VALUES(?,?,?)",
                (req_id, aid, sent.id)
            )
            db.commit()
        except Exception as e:
            print(f"Could not notify admin {aid}: {e}")

    # send a small sticker to the requester, then confirm submission
    try:
        await send_random_sticker(client, message.chat.id)
    except Exception:
        pass

    await message.reply_text(
        f"✅ Your request for **{title}** has been submitted!\n"
        "Thanks — the admins will take a look soon. 🙏"
    )


@app.on_callback_query(filters.regex(r"^reqack_(noted|na)_(\d+)$"))
async def request_ack_callback(client, callback_query):
    action = callback_query.matches[0].group(1)
    req_id = int(callback_query.matches[0].group(2))

    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("Admins only.", show_alert=True)
        return

    # Check if already handled (atomic read-then-write under the GIL is fine for SQLite)
    cursor.execute("SELECT status, acted_name, requester_id, title FROM requests WHERE id=?", (req_id,))
    row = cursor.fetchone()
    if not row:
        await callback_query.answer("Request not found.", show_alert=True)
        return

    status, acted_name, requester_id, title = row

    if status != "pending":
        verdict = "✅ Noted" if status == "noted" else "❌ Not Available"
        await callback_query.answer(
            f"Already handled by {acted_name} — {verdict}",
            show_alert=True
        )
        return

    # Lock the request
    admin_name = callback_query.from_user.first_name
    cursor.execute(
        "UPDATE requests SET status=?, acted_by=?, acted_name=? WHERE id=?",
        (action, callback_query.from_user.id, admin_name, req_id)
    )
    db.commit()

    if action == "noted":
        label    = "✅ Noted"
        user_msg = f"✅ Your request for **{title}** has been **noted**! We'll add it soon. 🙏"
    else:
        label    = "❌ Not Available"
        user_msg = f"❌ Sorry, **{title}** is **not available** at this time."

    await callback_query.answer(f"{label} — marked!", show_alert=False)

    # Update ALL admin copies of this request notification
    cursor.execute("SELECT admin_id, message_id FROM request_msgs WHERE request_id=?", (req_id,))
    all_copies = cursor.fetchall()
    updated_text = (
        f"📥 **Anime Request** `#{req_id}` — {label}\n\n"
        f"🎬 **Title:** {title}\n"
        f"👤 **Requester ID:** `{requester_id}`\n\n"
        f"_Handled by {admin_name}_"
    )
    for admin_id, msg_id in all_copies:
        try:
            await client.edit_message_text(
                chat_id=admin_id,
                message_id=msg_id,
                text=updated_text,
                reply_markup=None
            )
        except Exception:
            pass

    # Notify the requester
    try:
        await client.send_message(requester_id, user_msg)
    except Exception:
        pass


# =========================
# BROADCAST COMMAND
# =========================

@app.on_message(filters.command("broadcast"))
async def broadcast(client, message):
    if message.from_user.id != ADMIN_ID:
        return

    # Accept text after the command OR a replied-to message
    reply = message.reply_to_message

    if not reply and len(message.command) < 2:
        await message.reply_text(
            "Usage:\n"
            "• Reply to any message with `/broadcast` to forward it\n"
            "• Or: `/broadcast Your announcement text here`"
        )
        return

    cursor.execute("SELECT user_id FROM users")
    user_ids = [row[0] for row in cursor.fetchall()]

    if not user_ids:
        await message.reply_text("📭 No users to broadcast to yet.")
        return

    status_msg = await message.reply_text(f"📡 Broadcasting to {len(user_ids)} users...")

    sent = 0
    failed = 0

    for uid in user_ids:
        try:
            if reply:
                await reply.copy(uid)
            else:
                text = " ".join(message.command[1:])
                await client.send_message(uid, text)
            sent += 1
            await asyncio.sleep(0.05)
        except FloodWait as e:
            await asyncio.sleep(e.value)
            try:
                if reply:
                    await reply.copy(uid)
                else:
                    await client.send_message(uid, " ".join(message.command[1:]))
                sent += 1
            except Exception:
                failed += 1
        except Exception:
            failed += 1

    await status_msg.edit_text(
        f"✅ Broadcast complete!\n\n"
        f"• Delivered: **{sent}**\n"
        f"• Failed: **{failed}**"
    )


# =========================
# STATS COMMAND
# =========================

@app.on_message(filters.command("stats"))
async def stats(client, message):
    if message.from_user.id != ADMIN_ID:
        return

    cursor.execute("SELECT COUNT(*) FROM batches")
    total_batches = cursor.fetchone()[0]

    cursor.execute("SELECT name FROM batches ORDER BY rowid DESC LIMIT 1")
    newest = cursor.fetchone()
    newest_name = newest[0] if newest and newest[0] else "_(unnamed)_"

    cursor.execute("SELECT name, fetch_count FROM batches ORDER BY fetch_count DESC LIMIT 1")
    top_row = cursor.fetchone()
    if top_row and top_row[1]:
        top_batch = f"**{top_row[0] or '_(unnamed)_'}** ({top_row[1]} fetches)"
    else:
        top_batch = "_No fetches recorded yet_"

    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM auth_users")
    total_auth = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM requests")
    total_requests = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM requests WHERE status='pending'")
    pending_requests = cursor.fetchone()[0]

    await message.reply_text(
        "📊 **Bot Stats**\n\n"
        f"📦 Total batches: **{total_batches}**\n"
        f"🆕 Newest batch: **{newest_name}**\n"
        f"🔥 Most fetched: {top_batch}\n\n"
        f"👥 Total users: **{total_users}**\n"
        f"🔑 Authorized users: **{total_auth}**\n\n"
        f"📥 Total requests: **{total_requests}**\n"
        f"⏳ Pending requests: **{pending_requests}**"
    )


# =========================
# MY FILES COMMAND
# =========================

@app.on_message(filters.command("myfiles") & is_auth)
async def myfiles(client, message):
    user_id = message.from_user.id

    user_entries = [
        (key, entry)
        for key, entry in pending_deletes.items()
        if entry[1] == user_id
    ]

    if not user_entries:
        await message.reply_text("📭 You have no pending files to delete.")
        return

    buttons = []
    for key, (chat_id, uid, batch_name, msg_ids) in user_entries:
        label = f"🗑️ {batch_name}" if batch_name else f"🗑️ Batch ({len(msg_ids) - 1} files)"
        buttons.append([InlineKeyboardButton(label, callback_data=f"manualdelete_{key}")])

    if len(user_entries) > 1:
        buttons.append([InlineKeyboardButton("🗑️ Delete All", callback_data=f"deleteall_{user_id}")])

    await message.reply_text(
        f"📂 **Your pending files** ({len(user_entries)} batch{'es' if len(user_entries) > 1 else ''}):\n\n"
        "Tap a batch to delete it, or use **Delete All** to wipe everything at once.",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# =========================
# NEW ANIME GENRES & CLEAR CMDS
# =========================

@app.on_message(filters.command("clear"))
async def clear_message(client, message):
    if not message.reply_to_message:
        await message.reply_text("❌ Reply to the bot's message you want to delete with `/clear`")
        return
    try:
        await client.delete_messages(
            chat_id=message.chat.id,
            message_ids=[message.reply_to_message.id, message.id]
        )
    except Exception as e:
        print(f"Error in clear command: {e}")


# =========================
# ANIME SEARCH COMMAND
# =========================

@app.on_message(filters.command("anime"))
async def anime_search(client, message):
    if len(message.command) < 2:
        await message.reply_text("Usage: `/anime <title>`\nExample: `/anime Attack on Titan`")
        return

    query = " ".join(message.command[1:]).strip()
    # friendly sticker before search
    await send_random_sticker(client, message.chat.id)
    await message.reply_text(f"🔍 Searching for **{query}**...")

    gql = """
    query ($search: String) {
      Page(page: 1, perPage: 5) {
        media(type: ANIME, search: $search, sort: [SEARCH_MATCH]) {
          title { romaji english native }
          format
          status
          episodes
          averageScore
          season
          seasonYear
          genres
          description(asHtml: false)
          siteUrl
        }
      }
    }
    """

    result = await anilist_query(gql, {"search": query})
    if not result:
        await send_random_sticker(client, message.chat.id)
        await message.reply_text("⚠️ AniList API is unavailable, try again later.")
        return

    results = result.get("Page", {}).get("media", [])
    if not results:
        await send_random_sticker(client, message.chat.id)
        await message.reply_text(f"❌ No results found for **{query}**.")
        return

    for anime in results[:3]:
        title_en  = anime["title"].get("english") or ""
        title_rom = anime["title"].get("romaji") or ""
        title_nat = anime["title"].get("native") or ""
        display   = title_en or title_rom
        alt       = f" / {title_rom}" if title_en and title_rom != title_en else ""
        score     = f'{anime["averageScore"] / 10:.1f}' if anime.get("averageScore") else "N/A"
        episodes  = anime.get("episodes") or "?"
        fmt       = anime.get("format") or "?"
        status    = (anime.get("status") or "").replace("_", " ").title()
        season    = (anime.get("season") or "").title()
        year      = anime.get("seasonYear") or ""
        airing    = f"{season} {year}".strip() if (season or year) else "TBA"
        genres    = ", ".join(anime.get("genres", [])[:4])
        raw_desc  = anime.get("description") or "No synopsis available."
        synopsis  = re.sub(r"<[^>]+>", "", raw_desc)[:250]
        if len(raw_desc) > 250:
            synopsis += "…"
        link      = anime.get("siteUrl", "")

        text = (
            f"**[{display}{alt}]({link})**"
            + (f"\n🇯🇵 {title_nat}" if title_nat else "")
            + f"\n\n⭐ **{score}** · {fmt} · 🎬 {episodes} eps"
            f"\n📅 {airing} · {status}"
            f"\n🏷 {genres}"
            f"\n\n{synopsis}"
        )
        await message.reply_text(text, disable_web_page_preview=True)


@app.on_message(filters.command("trending"))
async def trending(client, message):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📺 TV",      callback_data="trending_tv"),
            InlineKeyboardButton("🎬 Movie",   callback_data="trending_movie"),
        ],
        [
            InlineKeyboardButton("📼 OVA",     callback_data="trending_ova"),
            InlineKeyboardButton("✨ Special",  callback_data="trending_special"),
        ],
        [InlineKeyboardButton("🌐 All Types", callback_data="trending_all")],
        [InlineKeyboardButton("❌ Close",      callback_data="close_menu")],
    ])
    await message.reply_text(
        "🔥 **What's Trending Now?**\n\nPick a type to see the top currently-airing anime:",
        reply_markup=keyboard
    )


@app.on_callback_query(filters.regex(r"^trending_(\w+)$"))
async def trending_results(client, callback_query):
    anime_type = callback_query.matches[0].group(1)

    type_labels = {
        "tv": "TV", "movie": "MOVIE",
        "ova": "OVA", "special": "SPECIAL", "all": "All Types"
    }
    label = {"tv": "TV", "movie": "Movie", "ova": "OVA", "special": "Special", "all": "All Types"}.get(anime_type, anime_type.title())

    await callback_query.answer(f"Fetching top {label} anime...", show_alert=False)

    format_filter = f', format: {type_labels[anime_type]}' if anime_type != "all" else ""
    gql = f"""
    query {{
      Page(page: 1, perPage: 8) {{
        media(type: ANIME, status: RELEASING{format_filter}, sort: [TRENDING_DESC], isAdult: false) {{
          title {{ romaji english }}
          episodes
          averageScore
          siteUrl
          format
        }}
      }}
    }}
    """

    result = await anilist_query(gql)
    if not result:
        await callback_query.message.reply_text("⚠️ AniList API is unavailable, try again later.")
        return

    results = result.get("Page", {}).get("media", [])
    if not results:
        await callback_query.message.reply_text(f"No currently-airing {label} anime found.")
        return

    lines = [f"🔥 **Top Airing — {label}**\n"]
    for i, anime in enumerate(results, 1):
        title    = anime["title"].get("english") or anime["title"].get("romaji", "Unknown")
        score    = f'{anime["averageScore"] / 10:.1f}' if anime.get("averageScore") else "N/A"
        episodes = anime.get("episodes") or "?"
        link     = anime.get("siteUrl", "")
        lines.append(f"{i}. [{title}]({link})\n   ⭐ **{score}** · 🎬 {episodes} eps")

    close_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Search Again", callback_data="trending_reopen")],
        [InlineKeyboardButton("❌ Close",         callback_data="close_menu")],
    ])
    await callback_query.message.reply_text(
        "\n".join(lines),
        disable_web_page_preview=True,
        reply_markup=close_markup
    )


@app.on_callback_query(filters.regex("^trending_reopen$"))
async def trending_reopen(client, callback_query):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📺 TV",      callback_data="trending_tv"),
            InlineKeyboardButton("🎬 Movie",   callback_data="trending_movie"),
        ],
        [
            InlineKeyboardButton("📼 OVA",     callback_data="trending_ova"),
            InlineKeyboardButton("✨ Special",  callback_data="trending_special"),
        ],
        [InlineKeyboardButton("🌐 All Types", callback_data="trending_all")],
        [InlineKeyboardButton("❌ Close",      callback_data="close_menu")],
    ])
    await callback_query.message.reply_text(
        "🔥 **What's Trending Now?**\n\nPick a type to see the top currently-airing anime:",
        reply_markup=keyboard
    )
    await callback_query.answer()


@app.on_message(filters.command("upcoming"))
async def upcoming(client, message):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📺 TV",      callback_data="upcoming_tv"),
            InlineKeyboardButton("🎬 Movie",   callback_data="upcoming_movie"),
        ],
        [
            InlineKeyboardButton("📼 OVA",     callback_data="upcoming_ova"),
            InlineKeyboardButton("✨ Special",  callback_data="upcoming_special"),
        ],
        [InlineKeyboardButton("🌐 All Types", callback_data="upcoming_all")],
        [InlineKeyboardButton("❌ Close",      callback_data="close_menu")],
    ])
    await message.reply_text(
        "🗓 **Upcoming Anime**\n\nPick a type to see what's arriving next season:",
        reply_markup=keyboard
    )


@app.on_callback_query(filters.regex(r"^upcoming_(\w+)$"))
async def upcoming_results(client, callback_query):
    anime_type = callback_query.matches[0].group(1)

    fmt_map = {"tv": "TV", "movie": "MOVIE", "ova": "OVA", "special": "SPECIAL"}
    label_map = {"tv": "TV", "movie": "Movie", "ova": "OVA", "special": "Special", "all": "All Types"}
    label = label_map.get(anime_type, anime_type.title())

    await callback_query.answer(f"Fetching upcoming {label}...", show_alert=False)

    format_filter = f', format: {fmt_map[anime_type]}' if anime_type in fmt_map else ""
    gql = f"""
    query {{
      Page(page: 1, perPage: 10) {{
        media(type: ANIME, status: NOT_YET_RELEASED{format_filter}, sort: [POPULARITY_DESC], isAdult: false) {{
          title {{ romaji english }}
          format
          episodes
          averageScore
          season
          seasonYear
          siteUrl
        }}
      }}
    }}
    """

    result = await anilist_query(gql)
    if not result:
        await callback_query.message.reply_text("⚠️ AniList API is unavailable, try again later.")
        return

    results = result.get("Page", {}).get("media", [])
    if not results:
        await callback_query.message.reply_text(
            f"No upcoming {label} anime found yet — check back closer to the season start!"
        )
        return

    lines = [f"🗓 **Upcoming — {label}**\n"]
    for i, anime in enumerate(results, 1):
        title  = anime["title"].get("english") or anime["title"].get("romaji", "Unknown")
        score  = f'{anime["averageScore"] / 10:.1f}' if anime.get("averageScore") else "TBA"
        season = (anime.get("season") or "").title()
        year   = anime.get("seasonYear") or ""
        airing = f"{season} {year}".strip() if (season or year) else "TBA"
        link   = anime.get("siteUrl", "")
        lines.append(f"{i}. [{title}]({link})\n   📅 {airing} · ⭐ {score}")

    close_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Search Again", callback_data="upcoming_reopen")],
        [InlineKeyboardButton("❌ Close",         callback_data="close_menu")],
    ])
    await callback_query.message.reply_text(
        "\n".join(lines),
        disable_web_page_preview=True,
        reply_markup=close_markup
    )


@app.on_callback_query(filters.regex("^upcoming_reopen$"))
async def upcoming_reopen(client, callback_query):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📺 TV",      callback_data="upcoming_tv"),
            InlineKeyboardButton("🎬 Movie",   callback_data="upcoming_movie"),
        ],
        [
            InlineKeyboardButton("📼 OVA",     callback_data="upcoming_ova"),
            InlineKeyboardButton("✨ Special",  callback_data="upcoming_special"),
        ],
        [InlineKeyboardButton("🌐 All Types", callback_data="upcoming_all")],
        [InlineKeyboardButton("❌ Close",      callback_data="close_menu")],
    ])
    await callback_query.message.reply_text(
        "🗓 **Upcoming Anime**\n\nPick a type to see what's arriving next season:",
        reply_markup=keyboard
    )
    await callback_query.answer()


# =========================
# RANDOM COMMAND
# =========================

def build_random_genre_keyboard():
    keyboard = []
    row = []
    for name in GENRES:
        row.append(InlineKeyboardButton(name, callback_data=f"rndgenre_{genre_to_cb(name)}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("❌ Close", callback_data="close_menu")])
    return InlineKeyboardMarkup(keyboard)


@app.on_message(filters.command("random"))
async def random_cmd(client, message):
    await message.reply_text(
        "🎲 **Random Anime Pick**\n\nChoose a genre and I'll surprise you:",
        reply_markup=build_random_genre_keyboard()
    )


@app.on_callback_query(filters.regex(r"^rndgenre_(.+)$"))
async def random_genre_pick(client, callback_query):
    genre_cb   = callback_query.matches[0].group(1)
    genre_name = cb_to_genre(genre_cb)
    await callback_query.answer("Rolling the dice...", show_alert=False)

    page = random.randint(1, 5)
    gql = """
    query ($genre: String, $page: Int) {
      Page(page: $page, perPage: 25) {
        media(type: ANIME, genre: $genre, sort: [SCORE_DESC], averageScore_greater: 65, isAdult: false) {
          title { romaji english }
          episodes
          averageScore
          genres
          description(asHtml: false)
          siteUrl
        }
      }
    }
    """

    result = await anilist_query(gql, {"genre": genre_name, "page": page})
    media = (result or {}).get("Page", {}).get("media", [])

    if not media:
        result = await anilist_query(gql, {"genre": genre_name, "page": 1})
        media = (result or {}).get("Page", {}).get("media", [])

    if not media:
        await callback_query.message.reply_text("Couldn't find anything for that genre. Try another!")
        return

    anime    = random.choice(media)
    title    = anime["title"].get("english") or anime["title"].get("romaji", "Unknown")
    score    = f'{anime["averageScore"] / 10:.1f}' if anime.get("averageScore") else "N/A"
    episodes = anime.get("episodes") or "?"
    raw_desc = anime.get("description") or "No synopsis available."
    synopsis = re.sub(r"<[^>]+>", "", raw_desc)[:300]
    if len(raw_desc) > 300:
        synopsis += "…"
    link     = anime.get("siteUrl", "")
    genres   = ", ".join(anime.get("genres", [])[:4])

    text = (
        f"🎲 **Your Random Pick!**\n\n"
        f"**[{title}]({link})**\n"
        f"⭐ Score: **{score}** · 🎬 Episodes: **{episodes}**\n"
        f"🏷 {genres}\n\n"
        f"{synopsis}"
    )

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 Try Another", callback_data=f"rndgenre_{genre_cb}")],
        [InlineKeyboardButton("🔀 Pick New Genre", callback_data="rnd_reopen")],
        [InlineKeyboardButton("❌ Close", callback_data="close_menu")],
    ])
    await callback_query.message.reply_text(text, disable_web_page_preview=True, reply_markup=markup)


@app.on_callback_query(filters.regex("^rnd_reopen$"))
async def rnd_reopen(client, callback_query):
    await callback_query.message.reply_text(
        "🎲 **Random Anime Pick**\n\nChoose a genre and I'll surprise you:",
        reply_markup=build_random_genre_keyboard()
    )
    await callback_query.answer()


# =========================
# TOP COMMAND
# =========================

def build_top_genre_keyboard():
    keyboard = []
    row = []
    for name in GENRES:
        row.append(InlineKeyboardButton(name, callback_data=f"topgenre_{genre_to_cb(name)}"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("❌ Close", callback_data="close_menu")])
    return InlineKeyboardMarkup(keyboard)


@app.on_message(filters.command("top"))
async def top_cmd(client, message):
    await message.reply_text(
        "🏆 **All-Time Top Anime**\n\nPick a genre to see the highest-rated titles ever made in it:",
        reply_markup=build_top_genre_keyboard()
    )


@app.on_callback_query(filters.regex(r"^topgenre_(.+)$"))
async def top_genre_results(client, callback_query):
    genre_cb   = callback_query.matches[0].group(1)
    genre_name = cb_to_genre(genre_cb)
    await callback_query.answer(f"Fetching top {genre_name}...", show_alert=False)

    gql = """
    query ($genre: String) {
      Page(page: 1, perPage: 10) {
        media(type: ANIME, genre: $genre, sort: [SCORE_DESC], isAdult: false) {
          title { romaji english }
          episodes
          averageScore
          format
          siteUrl
        }
      }
    }
    """

    result = await anilist_query(gql, {"genre": genre_name})
    if not result:
        await callback_query.message.reply_text("⚠️ AniList API is unavailable, try again later.")
        return

    results = result.get("Page", {}).get("media", [])
    if not results:
        await callback_query.message.reply_text(f"No results found for **{genre_name}**. Try another genre!")
        return

    lines = [f"🏆 **All-Time Top — {genre_name}**\n"]
    for i, anime in enumerate(results, 1):
        title      = anime["title"].get("english") or anime["title"].get("romaji", "Unknown")
        score      = f'{anime["averageScore"] / 10:.1f}' if anime.get("averageScore") else "N/A"
        episodes   = anime.get("episodes") or "?"
        anime_type = anime.get("format") or "?"
        link       = anime.get("siteUrl", "")
        lines.append(f"{i}. [{title}]({link})\n   ⭐ **{score}** · {anime_type} · 🎬 {episodes} eps")

    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔀 Pick New Genre", callback_data="top_reopen")],
        [InlineKeyboardButton("❌ Close", callback_data="close_menu")],
    ])
    await callback_query.message.reply_text(
        "\n".join(lines),
        disable_web_page_preview=True,
        reply_markup=markup
    )


@app.on_callback_query(filters.regex("^top_reopen$"))
async def top_reopen(client, callback_query):
    await callback_query.message.reply_text(
        "🏆 **All-Time Top Anime**\n\nPick a genre to see the highest-rated titles ever made in it:",
        reply_markup=build_top_genre_keyboard()
    )
    await callback_query.answer()


@app.on_message(filters.command("anime_genres"))
async def start_genre_selection(client, message):
    user_id = message.from_user.id
    user_selections[user_id] = []
    
    await message.reply_text(
        "**Select genres to find top-rated anime:**",
        reply_markup=build_genre_keyboard(user_id)
    )


@app.on_callback_query(filters.regex(r"^genre_(.+)$"))
async def toggle_genre(client, callback_query):
    user_id    = callback_query.from_user.id
    genre_name = cb_to_genre(callback_query.matches[0].group(1))

    if user_id not in user_selections:
        user_selections[user_id] = []

    if genre_name in user_selections[user_id]:
        user_selections[user_id].remove(genre_name)
    else:
        user_selections[user_id].append(genre_name)

    await callback_query.edit_message_reply_markup(
        reply_markup=build_genre_keyboard(user_id)
    )


@app.on_callback_query(filters.regex("^clear_genres$"))
async def clear_genres(client, callback_query):
    user_id = callback_query.from_user.id
    user_selections[user_id] = []
    await callback_query.edit_message_reply_markup(
        reply_markup=build_genre_keyboard(user_id)
    )


# Manual delete handler for authorized users
@app.on_callback_query(filters.regex(r"^manualdelete_(.+)$"))
async def manual_delete_files(client, callback_query):
    del_key = callback_query.matches[0].group(1)
    entry = pending_deletes.pop(del_key, None)

    if not entry:
        await callback_query.answer("Files already deleted.", show_alert=True)
        return

    chat_id, _uid, _name, msg_ids = entry
    await callback_query.answer("Deleting files...", show_alert=False)
    try:
        await client.delete_messages(chat_id=chat_id, message_ids=msg_ids)
    except Exception as e:
        print(f"Manual delete error: {e}")


# Delete all batches for a user at once
@app.on_callback_query(filters.regex(r"^deleteall_(\d+)$"))
async def delete_all_files(client, callback_query):
    user_id = int(callback_query.matches[0].group(1))

    if callback_query.from_user.id != user_id:
        await callback_query.answer("This button isn't for you.", show_alert=True)
        return

    user_keys = [k for k, v in pending_deletes.items() if v[1] == user_id]

    if not user_keys:
        await callback_query.answer("Nothing left to delete.", show_alert=True)
        return

    await callback_query.answer("Deleting all files...", show_alert=False)

    for key in user_keys:
        entry = pending_deletes.pop(key, None)
        if entry:
            chat_id, _uid, _name, msg_ids = entry
            try:
                await client.delete_messages(chat_id=chat_id, message_ids=msg_ids)
            except Exception as e:
                print(f"Delete all error: {e}")

    try:
        await callback_query.message.delete()
    except Exception:
        pass


# Universal close button handler
@app.on_callback_query(filters.regex("^close_menu$"))
async def close_menu_callback(client, callback_query):
    try:
        await callback_query.message.delete()
    except Exception as e:
        print(f"Error deleting menu: {e}")


@app.on_callback_query(filters.regex("^search_anime$"))
async def search_anime(client, callback_query):
    user_id  = callback_query.from_user.id
    selected = user_selections.get(user_id, [])

    if not selected:
        await callback_query.answer("Select at least one genre first!", show_alert=True)
        return

    await callback_query.answer("Fetching top-rated series...", show_alert=False)

    gql = """
    query ($genres: [String]) {
      Page(page: 1, perPage: 5) {
        media(type: ANIME, genre_in: $genres, format: TV, sort: [SCORE_DESC], isAdult: false) {
          title { romaji english }
          episodes
          averageScore
          siteUrl
        }
      }
    }
    """

    result = await anilist_query(gql, {"genres": selected})
    if not result:
        await callback_query.message.reply_text("Ah, the API hit a snag. Try again later!")
        return

    results = result.get("Page", {}).get("media", [])
    if not results:
        await callback_query.message.reply_text("No TV anime found matching all those genres together.")
        return

    text = "**Top Rated Anime Matches (TV Series):**\n\n"
    for anime in results:
        title    = anime["title"].get("english") or anime["title"].get("romaji", "Unknown")
        score    = f'{anime["averageScore"] / 10:.1f}' if anime.get("averageScore") else "N/A"
        episodes = anime.get("episodes") or "?"
        link     = anime.get("siteUrl", "")
        text += f"• [{title}]({link}) (⭐ **{score}** | 🎬 {episodes} eps)\n"

    close_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Close Results", callback_data="close_menu")]
    ])

    await callback_query.message.reply_text(text, disable_web_page_preview=True, reply_markup=close_markup)

# =========================
# WATCHLIST COMMAND
# =========================

def watchlist_keyboard(user_id):
    cursor.execute("SELECT id, title, done FROM watchlist WHERE user_id=? ORDER BY done, id", (user_id,))
    rows = cursor.fetchall()
    if not rows:
        return None, rows
    buttons = []
    for wid, title, done in rows:
        status = "✅" if done else "⬜"
        short = title[:28] + "…" if len(title) > 28 else title
        buttons.append([
            InlineKeyboardButton(f"{status} {short}", callback_data=f"wl_toggle_{wid}"),
            InlineKeyboardButton("🗑", callback_data=f"wl_del_{wid}"),
        ])
    buttons.append([InlineKeyboardButton("🗑 Clear Completed", callback_data="wl_clear_done"),
                    InlineKeyboardButton("❌ Close", callback_data="close_menu")])
    return InlineKeyboardMarkup(buttons), rows


@app.on_message(filters.command("watch"))
async def watch_add(client, message):
    if len(message.command) < 2:
        await message.reply_text("Usage: `/watch <anime title>`\nExample: `/watch Attack on Titan`")
        return
    title = " ".join(message.command[1:]).strip()
    user_id = message.from_user.id
    cursor.execute("INSERT INTO watchlist(user_id, title) VALUES(?,?)", (user_id, title))
    db.commit()
    await message.reply_text(f"➕ **{title}** added to your watchlist!")


@app.on_message(filters.command("watchlist"))
async def show_watchlist(client, message):
    user_id = message.from_user.id
    markup, rows = watchlist_keyboard(user_id)
    if not rows:
        await message.reply_text("📭 Your watchlist is empty. Add titles with `/watch <name>`.")
        return
    total = len(rows)
    done  = sum(1 for _, _, d in rows if d)
    await message.reply_text(
        f"📋 **Your Watchlist** — {done}/{total} watched:",
        reply_markup=markup
    )


@app.on_callback_query(filters.regex(r"^wl_toggle_(\d+)$"))
async def wl_toggle(client, callback_query):
    wid = int(callback_query.matches[0].group(1))
    cursor.execute("SELECT done, user_id FROM watchlist WHERE id=?", (wid,))
    row = cursor.fetchone()
    if not row or row[1] != callback_query.from_user.id:
        await callback_query.answer("Not found.", show_alert=True)
        return
    new_done = 0 if row[0] else 1
    cursor.execute("UPDATE watchlist SET done=? WHERE id=?", (new_done, wid))
    db.commit()
    markup, rows = watchlist_keyboard(callback_query.from_user.id)
    total = len(rows)
    done  = sum(1 for _, _, d in rows if d)
    await callback_query.edit_message_text(
        f"📋 **Your Watchlist** — {done}/{total} watched:",
        reply_markup=markup
    )
    await callback_query.answer("✅ Marked!" if new_done else "↩️ Unmarked!")


@app.on_callback_query(filters.regex(r"^wl_del_(\d+)$"))
async def wl_delete(client, callback_query):
    wid = int(callback_query.matches[0].group(1))
    cursor.execute("SELECT user_id FROM watchlist WHERE id=?", (wid,))
    row = cursor.fetchone()
    if not row or row[0] != callback_query.from_user.id:
        await callback_query.answer("Not found.", show_alert=True)
        return
    cursor.execute("DELETE FROM watchlist WHERE id=?", (wid,))
    db.commit()
    markup, rows = watchlist_keyboard(callback_query.from_user.id)
    await callback_query.answer("🗑 Removed!")
    if not rows:
        await callback_query.edit_message_text("📭 Your watchlist is empty. Add titles with `/watch <name>`.")
        return
    total = len(rows)
    done  = sum(1 for _, _, d in rows if d)
    await callback_query.edit_message_text(
        f"📋 **Your Watchlist** — {done}/{total} watched:",
        reply_markup=markup
    )


@app.on_callback_query(filters.regex("^wl_clear_done$"))
async def wl_clear_done(client, callback_query):
    user_id = callback_query.from_user.id
    cursor.execute("DELETE FROM watchlist WHERE user_id=? AND done=1", (user_id,))
    db.commit()
    await callback_query.answer("🗑 Completed entries cleared!")
    markup, rows = watchlist_keyboard(user_id)
    if not rows:
        await callback_query.edit_message_text("📭 Your watchlist is empty. Add titles with `/watch <name>`.")
        return
    total = len(rows)
    done  = sum(1 for _, _, d in rows if d)
    await callback_query.edit_message_text(
        f"📋 **Your Watchlist** — {done}/{total} watched:",
        reply_markup=markup
    )


# =========================
# REMINDER COMMAND
# =========================

async def fire_reminder(client, reminder_id, chat_id, user_id, text, delay):
    await asyncio.sleep(delay)
    try:
        await client.send_message(chat_id, f"⏰ **Reminder!**\n\n{text}")
    except Exception as e:
        print(f"Reminder send error: {e}")
    cursor.execute("DELETE FROM reminders WHERE id=?", (reminder_id,))
    db.commit()


@app.on_message(filters.command("remind"))
async def remind_cmd(client, message):
    # Format: /remind DD-MM-YYYY HH:MM Your message
    if len(message.command) < 4:
        await message.reply_text(
            "Usage: `/remind DD-MM-YYYY HH:MM Your message`\n"
            "Example: `/remind 25-12-2025 20:00 Watch Demon Slayer S4!`"
        )
        return

    date_str = message.command[1]
    time_str = message.command[2]
    text     = " ".join(message.command[3:])

    try:
        naive_dt  = datetime.strptime(f"{date_str} {time_str}", "%d-%m-%Y %H:%M")
        remind_dt = SL_TZ.localize(naive_dt)
    except ValueError:
        await message.reply_text(
            "❌ Invalid format. Use:\n`/remind DD-MM-YYYY HH:MM Your message`\n"
            "Example: `/remind 25-12-2025 20:00 Watch Demon Slayer S4!`"
        )
        return

    remind_ts = int(remind_dt.timestamp())
    now_ts    = int(time.time())
    delay     = remind_ts - now_ts

    if delay <= 0:
        await message.reply_text("❌ That date/time is already in the past!")
        return

    user_id = message.from_user.id
    chat_id = message.chat.id

    cursor.execute(
        "INSERT INTO reminders(user_id, chat_id, text, remind_at) VALUES(?,?,?,?)",
        (user_id, chat_id, text, remind_ts)
    )
    db.commit()
    rid = cursor.lastrowid

    asyncio.create_task(fire_reminder(client, rid, chat_id, user_id, text, delay))

    friendly = remind_dt.strftime("%d %b %Y at %H:%M")
    await message.reply_text(
        f"✅ **Reminder set!**\n\n"
        f"📅 {friendly}\n"
        f"📝 {text}"
    )


@app.on_message(filters.command("reminders"))
async def list_reminders(client, message):
    user_id = message.from_user.id
    now_ts  = int(time.time())
    cursor.execute(
        "SELECT id, text, remind_at FROM reminders WHERE user_id=? AND remind_at>? ORDER BY remind_at",
        (user_id, now_ts)
    )
    rows = cursor.fetchall()
    if not rows:
        await message.reply_text("📭 You have no upcoming reminders.")
        return

    buttons = []
    for rid, text, remind_at in rows:
        dt      = datetime.fromtimestamp(remind_at, tz=SL_TZ)
        label   = dt.strftime("%d %b %H:%M") + " — " + (text[:25] + "…" if len(text) > 25 else text)
        buttons.append([InlineKeyboardButton(f"🗑 {label}", callback_data=f"rmcancel_{rid}")])
    buttons.append([InlineKeyboardButton("❌ Close", callback_data="close_menu")])

    await message.reply_text(
        f"⏰ **Your Reminders** ({len(rows)} upcoming)\nTap one to cancel it:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


@app.on_callback_query(filters.regex(r"^rmcancel_(\d+)$"))
async def reminder_cancel(client, callback_query):
    rid     = int(callback_query.matches[0].group(1))
    user_id = callback_query.from_user.id
    cursor.execute("SELECT user_id, text FROM reminders WHERE id=?", (rid,))
    row = cursor.fetchone()
    if not row or row[0] != user_id:
        await callback_query.answer("Reminder not found.", show_alert=True)
        return
    cursor.execute("DELETE FROM reminders WHERE id=?", (rid,))
    db.commit()
    await callback_query.answer("🗑 Reminder cancelled!")
    # Refresh the list
    now_ts = int(time.time())
    cursor.execute(
        "SELECT id, text, remind_at FROM reminders WHERE user_id=? AND remind_at>? ORDER BY remind_at",
        (user_id, now_ts)
    )
    rows = cursor.fetchall()
    if not rows:
        await callback_query.edit_message_text("📭 You have no upcoming reminders.")
        return
    buttons = []
    for r_id, text, remind_at in rows:
        dt    = datetime.fromtimestamp(remind_at, tz=SL_TZ)
        label = dt.strftime("%d %b %H:%M") + " — " + (text[:25] + "…" if len(text) > 25 else text)
        buttons.append([InlineKeyboardButton(f"🗑 {label}", callback_data=f"rmcancel_{r_id}")])
    buttons.append([InlineKeyboardButton("❌ Close", callback_data="close_menu")])
    await callback_query.edit_message_text(
        f"⏰ **Your Reminders** ({len(rows)} upcoming)\nTap one to cancel it:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# =========================
# SYNC STATUS COMMAND
# =========================

import json as _json

SYNC_STATUS_FILE = ".sync_status"

@app.on_message(filters.command("status"))
async def sync_status_cmd(client, message):
    if message.from_user.id != ADMIN_ID:
        return

    if not os.path.exists(SYNC_STATUS_FILE):
        await message.reply_text(
            "📊 **GitHub Sync Status**\n\n"
            "No sync has run yet — `.sync_status` file not found.\n"
            "The status file is written by `scripts/github-sync.sh` after each run."
        )
        return

    try:
        with open(SYNC_STATUS_FILE, "r") as f:
            data = _json.load(f)
    except Exception as e:
        await message.reply_text(f"❌ Could not read status file: `{e}`")
        return

    result    = data.get("result", "unknown")
    timestamp = data.get("timestamp", "unknown")
    branch    = data.get("branch", "")
    reason    = data.get("reason", "")

    if result == "success":
        icon  = "✅"
        label = "Success"
        body  = f"Branch `{branch}` pushed to GitHub successfully."
    elif result == "failure":
        icon  = "❌"
        label = "Failed"
        body  = f"**Reason:** {reason}" if reason else "Push failed (no reason recorded)."
    elif result == "skipped":
        icon  = "⏭"
        label = "Skipped"
        body  = reason or "Push was skipped."
    else:
        icon  = "❓"
        label = result.capitalize()
        body  = reason or ""

    branch_line = f"\n**Branch:** `{branch}`" if branch else ""
    await message.reply_text(
        f"📊 **GitHub Sync Status**\n\n"
        f"{icon} **{label}**{branch_line}\n"
        f"**Time:** {timestamp}\n\n"
        f"{body}"
    )


# =========================
# RUN BOT
# =========================

async def resolve_storage_channel():
    raw_channel_id = abs(STORAGE_CHANNEL) - 1000000000000
    try:
        result = await app.invoke(
            functions.channels.GetChannels(
                id=[raw_types.InputChannel(
                    channel_id=raw_channel_id,
                    access_hash=0
                )]
            )
        )
        print(f"Storage channel resolved: {result.chats[0].title}")
    except Exception as e:
        print(f"Could not auto-resolve storage channel: {e}")
        print("Waiting for a channel post to cache the peer automatically...")


@app.on_message(filters.chat(STORAGE_CHANNEL))
async def cache_channel_peer(client, message):
    pass


async def load_pending_reminders(client):
    now_ts = int(time.time())
    cursor.execute("SELECT id, user_id, chat_id, text, remind_at FROM reminders WHERE remind_at>?", (now_ts,))
    rows = cursor.fetchall()
    for rid, user_id, chat_id, text, remind_at in rows:
        delay = remind_at - now_ts
        asyncio.create_task(fire_reminder(client, rid, chat_id, user_id, text, delay))
    if rows:
        print(f"Loaded {len(rows)} pending reminder(s).")


async def main():
    async with app:
        await resolve_storage_channel()
        await load_pending_reminders(app)
        print("Bot Running...")
        await idle()

if __name__ == "__main__":
    print("Bot Running...")
    app.run()
