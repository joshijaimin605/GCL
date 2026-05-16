# gcl_bot.py
# Requirements:
#   python-telegram-bot==20.6
#   aiohttp
#   python-dotenv (optional, if you want .env support)
#
# Run:
#   pip install python-telegram-bot==20.6 aiohttp python-dotenv
#   python gcl_bot.py

import logging
import sqlite3
import os
import shutil
import time
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Chat,
    ChatMemberUpdated,
)
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ChatMemberHandler,
    MessageHandler,
    filters,
)

# -------------------------------------------------
# CONFIG
# -------------------------------------------------
BOT_TOKEN = "8373191488:AAGeyXRQNOpuMhJxvsRvWfcpPqWn2dcjvpQ"  # <-- Yaha apna real bot token daalo

ADMIN_IDS = [7839961753,1322398873]  # apna Telegram admin user IDs yaha daalo
ADMIN_GROUP_ID = -1002260959216  # admin group jaha registration requests jayengi

MAIN_GROUP_ID = -1002723854678
MAIN_CHANNEL_ID = -1002066951574

MAIN_GROUP_URL = "https://t.me/+KD-JcBl8s8oxZGZl"
MAIN_CHANNEL_URL = "https://t.me/GCL_OFFICIAL_CHANNEL"

DB_PATH = "players.db"

# anti-spam (simple rate limit)
_last_msg_ts = {}
SPAM_GAP_SECONDS = 2.0  # 1 second gap


# -------------------------------------------------
# LOGGING
# -------------------------------------------------
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


# -------------------------------------------------
# DB HELPERS
# -------------------------------------------------
def init_db():
    first = not os.path.exists(DB_PATH)
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS players (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT,
                last_name TEXT,
                username TEXT,
                registered_at TEXT,
                approved INTEGER DEFAULT 0,
                runs INTEGER DEFAULT 0,
                wickets INTEGER DEFAULT 0
            )
        """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS achievements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                text TEXT,
                created_at TEXT
            )
        """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS known_users (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT,
                last_name TEXT,
                username TEXT,
                added_at TEXT
            )
        """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS known_chats (
                chat_id INTEGER PRIMARY KEY,
                type TEXT,
                title TEXT,
                added_at TEXT
            )
        """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """
        )
        c.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('reg_mode', 'on')"
        )
        conn.commit()
    if first:
        logger.info("Database created: %s", DB_PATH)
    else:
        logger.info("Database loaded successfully.")


def get_setting(key, default=None):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = c.fetchone()
        return row[0] if row else default


def set_setting(key, value):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
        conn.commit()


def ensure_known_user(user):
    if not user:
        return
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT OR REPLACE INTO known_users
            (user_id, first_name, last_name, username, added_at)
            VALUES (
                ?,
                ?,
                ?,
                ?,
                COALESCE((SELECT added_at FROM known_users WHERE user_id=?), ?)
            )
        """,
            (
                user.id,
                user.first_name or "",
                user.last_name or "",
                user.username or "",
                user.id,
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()


def ensure_known_chat(chat: Chat):
    if not chat:
        return
    if chat.id == MAIN_CHANNEL_ID:
        return
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT OR REPLACE INTO known_chats
            (chat_id, type, title, added_at)
            VALUES (
                ?,
                ?,
                ?,
                COALESCE((SELECT added_at FROM known_chats WHERE chat_id=?), ?)
            )
        """,
            (
                chat.id,
                chat.type,
                chat.title or "",
                chat.id,
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()


def get_known_users():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT user_id FROM known_users")
        return [r[0] for r in c.fetchall()]


def get_known_groups():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT chat_id FROM known_chats")
        return [r[0] for r in c.fetchall()]


def create_player_if_not_exists(
    user_id=None, username=None, first_name="", last_name=""
):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        if user_id:
            c.execute("SELECT user_id FROM players WHERE user_id = ?", (user_id,))
            if c.fetchone():
                return user_id
            c.execute(
                """
                INSERT INTO players
                (user_id, first_name, last_name, username, registered_at, approved, runs, wickets)
                VALUES (?, ?, ?, ?, NULL, 0, 0, 0)
            """,
                (user_id, first_name, last_name, username or None),
            )
            conn.commit()
            return user_id
        else:
            if username:
                c.execute(
                    "SELECT user_id FROM players WHERE lower(username)=lower(?)",
                    (username,),
                )
                row = c.fetchone()
                if row:
                    return row[0]
            gen_id = -int(datetime.utcnow().timestamp() * 1000)
            c.execute(
                """
                INSERT INTO players
                (user_id, first_name, last_name, username, registered_at, approved, runs, wickets)
                VALUES (?, ?, ?, ?, NULL, 0, 0, 0)
            """,
                (gen_id, first_name, last_name, username or None),
            )
            conn.commit()
            return gen_id


def add_or_update_pending(user_id, first_name, last_name, username):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT OR REPLACE INTO players
            (user_id, first_name, last_name, username, registered_at, approved, runs, wickets)
            VALUES (
                ?,
                ?,
                ?,
                ?,
                ?,
                COALESCE((SELECT approved FROM players WHERE user_id=?), 0),
                COALESCE((SELECT runs FROM players WHERE user_id=?), 0),
                COALESCE((SELECT wickets FROM players WHERE user_id=?), 0)
            )
        """,
            (
                user_id,
                first_name,
                last_name,
                username,
                datetime.utcnow().isoformat(),
                user_id,
                user_id,
                user_id,
            ),
        )
        conn.commit()


def clear_pending_registration(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE players SET registered_at = NULL, approved = 0 WHERE user_id = ?",
            (user_id,),
        )
        conn.commit()


def approve_player(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("UPDATE players SET approved = 1 WHERE user_id = ?", (user_id,))
        conn.commit()


def is_registered(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT approved FROM players WHERE user_id = ?", (user_id,))
        row = c.fetchone()
        return row is not None and row[0] == 1


def get_player_by_userid(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            SELECT first_name, last_name, username, runs, wickets, approved
            FROM players WHERE user_id = ?
        """,
            (user_id,),
        )
        return c.fetchone()


def get_player_by_username(username):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            SELECT user_id, first_name, last_name, username, runs, wickets, approved
            FROM players WHERE lower(username) = lower(?)
        """,
            (username,),
        )
        return c.fetchone()


def add_runs_to_user_by_username(username, runs):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        row = get_player_by_username(username)
        if not row:
            uid = create_player_if_not_exists(user_id=None, username=username)
            c.execute(
                "UPDATE players SET runs = runs + ? WHERE user_id = ?", (runs, uid)
            )
            conn.commit()
            return 1
        c.execute(
            "UPDATE players SET runs = runs + ? WHERE lower(username)=lower(?)",
            (runs, username),
        )
        conn.commit()
        return c.rowcount


def add_wickets_to_user_by_username(username, wk):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        row = get_player_by_username(username)
        if not row:
            uid = create_player_if_not_exists(user_id=None, username=username)
            c.execute(
                "UPDATE players SET wickets = wickets + ? WHERE user_id = ?", (wk, uid)
            )
            conn.commit()
            return 1
        c.execute(
            "UPDATE players SET wickets = wickets + ? WHERE lower(username)=lower(?)",
            (wk, username),
        )
        conn.commit()
        return c.rowcount


def del_runs_from_user_by_username(username, runs):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        row = get_player_by_username(username)
        if not row:
            return 0
        c.execute(
            """
            UPDATE players
            SET runs = MAX(runs - ?, 0)
            WHERE lower(username)=lower(?)
        """,
            (runs, username),
        )
        conn.commit()
        return c.rowcount


def del_wickets_from_user_by_username(username, wk):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        row = get_player_by_username(username)
        if not row:
            return 0
        c.execute(
            """
            UPDATE players
            SET wickets = MAX(wickets - ?, 0)
            WHERE lower(username)=lower(?)
        """,
            (wk, username),
        )
        conn.commit()
        return c.rowcount


def add_achievement_by_username(username, text):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        row = get_player_by_username(username)
        if not row:
            uid = create_player_if_not_exists(user_id=None, username=username)
        else:
            uid = row[0]
        c.execute(
            """
            INSERT INTO achievements (user_id, text, created_at)
            VALUES (?, ?, ?)
        """,
            (uid, text, datetime.utcnow().isoformat()),
        )
        conn.commit()
        return True


def remove_achievement_by_user_and_index(user_id, index):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id FROM achievements WHERE user_id = ? ORDER BY id ASC",
            (user_id,),
        )
        rows = c.fetchall()
        if not rows or index < 1 or index > len(rows):
            return False
        ach_id = rows[index - 1][0]
        c.execute("DELETE FROM achievements WHERE id = ?", (ach_id,))
        conn.commit()
        return True


def get_achievements(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        # oldest first, new sabse niche
        c.execute(
            "SELECT text, created_at FROM achievements WHERE user_id = ? ORDER BY id ASC",
            (user_id,),
        )
        return c.fetchall()


def get_approved_players():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            SELECT user_id, first_name, last_name, username, runs, wickets
            FROM players
            WHERE approved = 1
            ORDER BY first_name
        """
        )
        return c.fetchall()


def totals_summary():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM players WHERE approved = 1")
        total_players = c.fetchone()[0]
        c.execute(
            """
            SELECT COALESCE(SUM(runs), 0), COALESCE(SUM(wickets),0)
            FROM players WHERE approved = 1
        """
        )
        total_runs, total_wickets = c.fetchone()
        return total_players, total_runs, total_wickets


def top_players(limit=3):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            SELECT user_id, first_name, last_name, runs
            FROM players
            WHERE approved = 1
            ORDER BY runs DESC
            LIMIT ?
        """,
            (limit,),
        )
        bats = c.fetchall()
        c.execute(
            """
            SELECT user_id, first_name, last_name, wickets
            FROM players
            WHERE approved = 1
            ORDER BY wickets DESC
            LIMIT ?
        """,
            (limit,),
        )
        bowls = c.fetchall()
        return bats, bowls


def clear_registration_data():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("UPDATE players SET approved = 0, registered_at = NULL")
        conn.commit()


# -------------------------------------------------
# ANTI-SPAM HELPER
# -------------------------------------------------
def is_spam(user_id: int) -> bool:
    now = time.time()
    last = _last_msg_ts.get(user_id, 0)
    if now - last < SPAM_GAP_SECONDS:
        _last_msg_ts[user_id] = now
        return True
    _last_msg_ts[user_id] = now
    return False


# -------------------------------------------------
# HANDLERS
# -------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if user and is_spam(user.id):
        return
    ensure_known_user(user)
    ensure_known_chat(chat)
    first = user.first_name or user.username or ""
    if chat.type == Chat.PRIVATE:
        await update.message.reply_text(
            f"🎉 WELCOME TO GCL SEASON-9, {first}!\n\nUse the command menu (type /) to see available commands."
        )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user and is_spam(user.id):
        return
    text = (
        "🤖 GCL Bot Commands\n\n"
        "PLAYER COMMANDS:\n"
        "/start - Welcome message\n"
        "/register - Register as a player\n"
        "/career - View your runs & wickets\n"
        "/achievements - View player achievements\n"
        "/topplayers - Top batsmen & bowlers\n"
        "/stats - Tournament totals & mini leaderboard\n"
        "/about - Bot information\n\n"
        "ADMIN ONLY:\n"
        "/addruns, /addwickets\n"
        "/removeruns, /removewickets (or /delruns, /delwkt)\n"
        "/addachievement, /remove_achieve\n"
        "/backup, /restore, /clear\n"
        "/broadcast, /request, /list\n"
        "/regmode on|off\n"
        "/admin - admin list & commands\n"
    )
    await update.message.reply_text(text)


async def register_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user and is_spam(user.id):
        return

    reg_mode = get_setting("reg_mode", "on")
    if str(reg_mode).lower() != "on":
        await update.message.reply_text(
            "Registration is currently closed. Please try later."
        )
        return

    user_id = user.id

    # check main group membership
    try:
        gm = await context.bot.get_chat_member(MAIN_GROUP_ID, user_id)
        in_group = gm.status not in ("left", "kicked")
    except Exception:
        in_group = False

    # check channel membership
    try:
        cm = await context.bot.get_chat_member(MAIN_CHANNEL_ID, user_id)
        in_channel = cm.status not in ("left", "kicked")
    except Exception:
        in_channel = False

    if not in_group or not in_channel:

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "📢 Join Channel",
                    url=MAIN_CHANNEL_URL
                )
            ],
            [
                InlineKeyboardButton(
                    "💬 Join Group",
                    url=MAIN_GROUP_URL
                )
            ]
        ])

        await update.message.reply_text(
            "❌ Please join both group and channel first,then tap /register again.",
            reply_markup=keyboard
        )

        return
    if is_registered(user_id):
        await update.message.reply_text(
            "You are already registered for GCL Season-9. Status: ✅ Approved."
        )
        return

    row = get_player_by_userid(user_id)
    if row and row[5] == 0 and row[0] is not None:
        # pending
        await update.message.reply_text(
            "Your registration request is already pending admin approval."
        )
        return

    first = user.first_name or ""
    last = user.last_name or ""
    username = user.username or ""
    add_or_update_pending(user_id, first, last, username)

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Yes", callback_data=f"confirm_yes:{user_id}"),
                InlineKeyboardButton("❌ No", callback_data=f"confirm_no:{user_id}"),
            ]
        ]
    )
    msg = (
        "Please confirm your registration details:\n\n"
        f"Name: {first} {last}\n"
        f"Username: @{username if username else '-'}\n\n"
        "Confirm registration?"
    )
    try:
        await context.bot.send_message(
            chat_id=user_id, text=msg, reply_markup=keyboard
        )
        if update.message.chat.type != "private":
            await update.message.reply_text(
                "I have sent you a private message to confirm registration. Please check your bot chat."
            )
    except Exception:
        await update.message.reply_text(
            "Please open a private chat with the bot and press Start, then tap /register again."
        )  

# =========================================
# UNREGISTER COMMAND
# =========================================

async def unregister_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    cursor.execute(
        "SELECT approved FROM registrations WHERE user_id=?",
        (user.id,)
    )

    row = cursor.fetchone()

    if not row:

        await update.message.reply_text(
            "❌ You are not registered."
        )

        return

    approved = row[0]

    if approved == 1:

        await update.message.reply_text(
            "⚠️ Approved players cannot unregister."
        )

        return

    cursor.execute(
        "DELETE FROM registrations WHERE user_id=?",
        (user.id,)
    )

    conn.commit()

    await update.message.reply_text(
        "✅ Your pending registration has been removed.\n\nYou can now register again using /register"
    )

async def confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if not data:
        return

    if data.startswith("confirm_no:"):
        _, uid_s = data.split(":", 1)
        try:
            player_id = int(uid_s)
        except ValueError:
            await query.edit_message_text("Invalid registration data.")
            return
        clear_pending_registration(player_id)
        await query.edit_message_text(
            "Registration cancelled. You can use /register again anytime."
        )
        return

    if not data.startswith("confirm_yes:"):
        return

    _, uid_s = data.split(":", 1)
    try:
        player_id = int(uid_s)
    except ValueError:
        await query.edit_message_text("Invalid registration data.")
        return

    if is_registered(player_id):
        await query.edit_message_text("You are already registered and approved.")
        return

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT first_name, last_name, username FROM players WHERE user_id = ?",
            (player_id,),
        )
        row = c.fetchone()

    if row:
        first, last, username = row
    else:
        first = last = username = ""

    text = (
        "New Registration Request\n\n"
        f"Player Name: {first} {last}\n"
        f"Username: @{username if username else '-'}\n"
        f"User ID: {player_id}"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Accept", callback_data=f"admin_accept:{player_id}"),
                InlineKeyboardButton("Reject", callback_data=f"admin_reject:{player_id}"),
            ]
        ]
    )

    sent = False
    try:
        if ADMIN_GROUP_ID:
            await context.bot.send_message(
                chat_id=ADMIN_GROUP_ID, text=text, reply_markup=keyboard
            )
            sent = True
    except Exception:
        sent = False

    if sent:
        await query.edit_message_text(
            "Your registration request has been sent to admin for approval."
        )
    else:
        await query.edit_message_text(
            "Could not contact admin. Please ask admin to start the bot."
        )


async def handle_admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if not data:
        return

    if not (data.startswith("admin_accept:") or data.startswith("admin_reject:")):
        return

    admin_user = update.effective_user
    if admin_user.id not in ADMIN_IDS:
        await query.answer("Only admin can perform this action.", show_alert=True)
        return

    action, uid_s = data.split(":", 1)
    player_id = int(uid_s)

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT first_name, last_name, username FROM players WHERE user_id = ?",
            (player_id,),
        )
        row = c.fetchone()

    if row:
        first, last, username = row
    else:
        first = last = username = ""

    if action == "admin_accept":
        approve_player(player_id)
        try:
            await context.bot.send_message(
                chat_id=player_id,
                text="Thank you for registration in GCL Season-9 ✅ Your request has been approved,auction will be conducted soon!!stay connect with us..😇",
            )
        except Exception:
            pass
        new_text = (
            "Player Accepted\n\n"
            f"Player Name: {first} {last}\n"
            f"Username: @{username if username else '-'}\n"
            f"User ID: {player_id}\n\n"
            "Status: Accepted ✅"
        )
        await query.edit_message_text(new_text)
    else:
        clear_pending_registration(player_id)
        try:
            await context.bot.send_message(
                chat_id=player_id,
                text=(
                    "Your registration for GCL Season-8 was rejected by admin. "
                    "You can register again using /register."
                ),
            )
        except Exception:
            pass
        new_text = (
            "Player Rejected\n\n"
            f"Player Name: {first} {last}\n"
            f"Username: @{username if username else '-'}\n"
            f"User ID: {player_id}\n\n"
            "Status: Rejected ❌"
        )
        await query.edit_message_text(new_text)

    # pin message in admin group
    try:
        if query.message and query.message.chat.id == ADMIN_GROUP_ID:
            await context.bot.pin_chat_message(
                chat_id=query.message.chat.id,
                message_id=query.message.message_id,
                disable_notification=True,
            )
    except Exception as e:
        logger.warning("Failed to pin message: %s", e)


async def career_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user and is_spam(user.id):
        return
    p = get_player_by_userid(user.id)
    if not p or p[5] != 1:
        await update.message.reply_text(
            "You are not registered yet. Use /register first."
        )
        return
    fn, ln, username, runs, wickets, approved = p

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()

        c.execute("""
        SELECT COUNT(*) + 1
        FROM players
        WHERE runs > ?
        AND approved = 1
        """, (runs,))

        rank = c.fetchone()[0]

    display_name = (f"{fn} {ln}".strip()) or (username or str(user.id))
    ach = get_achievements(user.id)

    msg = (
        f"🏏 Career of {display_name}\n\n"
        f"🏅 Rank: #{rank}\n"
        f"Runs: {runs}\n"
        f"Wickets: {wickets}\n\n"
        "Achievements:\n"
    )

    if not ach:
        msg += "You don't have any achievements yet. Keep playing!"
    else:
        for i, (text, created) in enumerate(ach, start=1):
            msg += f"{i}. <b>{text}</b>\n"

    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def achievements_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user and is_spam(user.id):
        return
    target_user = user
    if update.message and update.message.reply_to_message:
        target_user = update.message.reply_to_message.from_user

    ach = get_achievements(target_user.id)
    if not ach:
        await update.message.reply_text("🏆 No achievements found for this player.")
        return
    msg = (
        f"🏆 Achievements of "
        f"{target_user.first_name or target_user.username or target_user.id}:\n\n"
    )
    for i, (text, created) in enumerate(ach, start=1):
        msg += f"{i}. <b>{text}</b>\n"
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def remove_achieve_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("Only admin can use this command.")
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /remove_achieve <username or user_id> <index>"
        )
        return
    ident = context.args[0]
    try:
        index = int(context.args[1])
    except ValueError:
        await update.message.reply_text("Index must be a number.")
        return

    target_id = None
    if ident.isdigit():
        target_id = int(ident)
    else:
        row = get_player_by_username(ident.lstrip("@"))
        if row:
            target_id = row[0]
    if not target_id:
        await update.message.reply_text("Player not found.")
        return

    ok = remove_achievement_by_user_and_index(target_id, index)
    if ok:
        await update.message.reply_text("Achievement removed.")
    else:
        await update.message.reply_text(
            "Invalid index or player has no achievements."
        )


async def topplayers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user and is_spam(user.id):
        return
    bats, bowls = top_players(3)
    msg = "🔥 Top Performers:\n\n🏃 Top Batsmen:\n"
    if not bats:
        msg += "No data yet."
    else:
        for i, (uid, fn, ln, runs) in enumerate(bats, start=1):
            name = (f"{fn} {ln}".strip()) or str(uid)
            msg += f"{i}. {name} — {runs} runs\n"
    msg += "\n🎯 Top Bowlers:\n"
    if not bowls:
        msg += "No data yet."
    else:
        for i, (uid, fn, ln, wk) in enumerate(bowls, start=1):
            name = (f"{fn} {ln}".strip()) or str(uid)
            msg += f"{i}. {name} — {wk} wickets\n"
    await update.message.reply_text(msg)


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user and is_spam(user.id):
        return
    total_players, total_runs, total_wickets = totals_summary()
    bats, bowls = top_players(1)
    msg = (
        "📊 GCL Season 9 — Stats Summary\n\n"
        f"Total Players: {total_players}\n"
        f"Total Runs: {total_runs}\n"
        f"Total Wickets: {total_wickets}\n\n"
        "Mini Leaderboard:\n"
    )
    if bats:
        uid, fn, ln, runs = bats[0]
        name = (f"{fn} {ln}".strip()) or str(uid)
        msg += f"Top Scorer: {name} — {runs} runs\n"
    if bowls:
        uid2, fn2, ln2, wk = bowls[0]
        name2 = (f"{fn2} {ln2}".strip()) or str(uid2)
        msg += f"Top Wicket-Taker: {name2} — {wk} wickets\n"
    await update.message.reply_text(msg)


async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("Only admin can use this command.")
        return
    players = get_approved_players()
    if not players:
        await update.message.reply_text("No approved players yet.")
        return
    lines = ["📋 REGISTERED PLAYERS LIST\n\n"]

    for i, (uid, fn, ln, username, runs, wickets) in enumerate(players, start=1):

        if username:
            username_text = f"@{username}"
        else:
            username_text = "No Username"

        name = f"{fn} {ln}".strip()

        lines.append(
    f"{i}. 👤 {name} | 🔗 {username_text} | 🆔 {uid}\n"
)

    await update.message.reply_text("".join(lines))

async def about_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "🤖 GCL Season 9 Bot\nMade by: Jaimin Joshi ❤️\nVersion: v1.0"
    await update.message.reply_text(msg)


# ---------------- ADMIN: STATS UPDATE ----------------
async def addruns_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("Only admin can use this command.")
        return
    msg = update.message

    # reply method
    if msg.reply_to_message:
        if len(context.args) < 1:
            await msg.reply_text(
                "Usage: reply to a player with /addruns <runs>"
            )
            return
        target_user = msg.reply_to_message.from_user
        try:
            runs = int(context.args[0])
        except ValueError:
            await msg.reply_text("Runs must be a number.")
            return
        uid = create_player_if_not_exists(
            user_id=target_user.id,
            username=target_user.username or None,
            first_name=target_user.first_name or "",
            last_name=target_user.last_name or "",
        )
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute(
                "UPDATE players SET runs = runs + ? WHERE user_id = ?",
                (runs, uid),
            )
            conn.commit()
        await msg.reply_text(
            f"Added {runs} runs to {target_user.first_name or target_user.username}."
        )
        return

    # username method
    if len(context.args) < 2:
        await msg.reply_text(
            "Usage: /addruns @username <runs> OR reply to player with /addruns <runs>"
        )
        return

    username = context.args[0].lstrip("@")
    try:
        runs = int(context.args[1])
    except ValueError:
        await msg.reply_text("Runs must be a number.")
        return

    added = add_runs_to_user_by_username(username, runs)
    if added:
        await msg.reply_text(f"Added {runs} runs to @{username}.")
    else:
        await msg.reply_text("Player not found.")


async def addwickets_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("Only admin can use this command.")
        return
    msg = update.message

    if msg.reply_to_message:
        if len(context.args) < 1:
            await msg.reply_text(
                "Usage: reply to a player with /addwickets <wickets>"
            )
            return
        target_user = msg.reply_to_message.from_user
        try:
            wk = int(context.args[0])
        except ValueError:
            await msg.reply_text("Wickets must be a number.")
            return
        uid = create_player_if_not_exists(
            user_id=target_user.id,
            username=target_user.username or None,
            first_name=target_user.first_name or "",
            last_name=target_user.last_name or "",
        )
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute(
                "UPDATE players SET wickets = wickets + ? WHERE user_id = ?",
                (wk, uid),
            )
            conn.commit()
        await msg.reply_text(
            f"Added {wk} wickets to {target_user.first_name or target_user.username}."
        )
        return

    if len(context.args) < 2:
        await msg.reply_text(
            "Usage: /addwickets @username <wickets> OR reply to player with /addwickets <wickets>"
        )
        return

    username = context.args[0].lstrip("@")
    try:
        wk = int(context.args[1])
    except ValueError:
        await msg.reply_text("Wickets must be a number.")
        return

    added = add_wickets_to_user_by_username(username, wk)
    if added:
        await msg.reply_text(f"Added {wk} wickets to @{username}.")
    else:
        await msg.reply_text("Player not found.")


async def removeruns_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("Only admin can use this command.")
        return
    msg = update.message

    if msg.reply_to_message:
        if len(context.args) < 1:
            await msg.reply_text(
                "Usage: reply to a player with /removeruns <runs>"
            )
            return
        target_user = msg.reply_to_message.from_user
        try:
            runs = int(context.args[0])
        except ValueError:
            await msg.reply_text("Runs must be a number.")
            return
        uid = create_player_if_not_exists(
            user_id=target_user.id,
            username=target_user.username or None,
            first_name=target_user.first_name or "",
            last_name=target_user.last_name or "",
        )
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute(
                "UPDATE players SET runs = MAX(runs - ?, 0) WHERE user_id = ?",
                (runs, uid),
            )
            conn.commit()
        await msg.reply_text(
            f"Removed {runs} runs from {target_user.first_name or target_user.username}."
        )
        return

    if len(context.args) < 2:
        await msg.reply_text(
            "Usage: /removeruns @username <runs>"
        )
        return

    username = context.args[0].lstrip("@")
    try:
        runs = int(context.args[1])
    except ValueError:
        await msg.reply_text("Runs must be a number.")
        return

    removed = del_runs_from_user_by_username(username, runs)
    if removed:
        await msg.reply_text(f"Removed {runs} runs from @{username}.")
    else:
        await msg.reply_text("Player not found.")


async def removewickets_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("Only admin can use this command.")
        return
    msg = update.message

    if msg.reply_to_message:
        if len(context.args) < 1:
            await msg.reply_text(
                "Usage: reply to a player with /removewickets <wickets>"
            )
            return
        target_user = msg.reply_to_message.from_user
        try:
            wk = int(context.args[0])
        except ValueError:
            await msg.reply_text("Wickets must be a number.")
            return
        uid = create_player_if_not_exists(
            user_id=target_user.id,
            username=target_user.username or None,
            first_name=target_user.first_name or "",
            last_name=target_user.last_name or "",
        )
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute(
                "UPDATE players SET wickets = MAX(wickets - ?, 0) WHERE user_id = ?",
                (wk, uid),
            )
            conn.commit()
        await msg.reply_text(
            f"Removed {wk} wickets from {target_user.first_name or target_user.username}."
        )
        return

    if len(context.args) < 2:
        await msg.reply_text(
            "Usage: /removewickets @username <wickets>"
        )
        return

    username = context.args[0].lstrip("@")
    try:
        wk = int(context.args[1])
    except ValueError:
        await msg.reply_text("Wickets must be a number.")
        return

    removed = del_wickets_from_user_by_username(username, wk)
    if removed:
        await msg.reply_text(f"Removed {wk} wickets from @{username}.")
    else:
        await msg.reply_text("Player not found.")


# aliases
delruns_cmd = removeruns_cmd
delwkt_cmd = removewickets_cmd


async def addachievement_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("Only admin can use this command.")
        return
    msg = update.message

    if msg.reply_to_message:
        if not context.args:
            await msg.reply_text(
                "Usage: reply to a player with /addachievement <text>"
            )
            return
        target_user = msg.reply_to_message.from_user
        text = " ".join(context.args)
        uid = create_player_if_not_exists(
            user_id=target_user.id,
            username=target_user.username or None,
            first_name=target_user.first_name or "",
            last_name=target_user.last_name or "",
        )
        with sqlite3.connect(DB_PATH) as conn:
            c = conn.cursor()
            c.execute(
                """
                INSERT INTO achievements (user_id, text, created_at)
                VALUES (?, ?, ?)
            """,
                (uid, text, datetime.utcnow().isoformat()),
            )
            conn.commit()
        await msg.reply_text(
            f"Achievement added to {target_user.first_name or target_user.username}."
        )
        return

    if len(context.args) < 2:
        await msg.reply_text(
            "Usage: /addachievement @username <text>"
        )
        return

    username = context.args[0].lstrip("@")
    text = " ".join(context.args[1:])
    ok = add_achievement_by_username(username, text)
    if ok:
        await msg.reply_text(f"Achievement added for @{username}.")
    else:
        await msg.reply_text("Player not found.")


# ---------------- BACKUP / RESTORE / CLEAR ----------------
async def backup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("Only admin can use this command.")
        return
    if not os.path.exists(DB_PATH):
        await update.message.reply_text("Database file not found.")
        return
    try:
        with open(DB_PATH, "rb") as f:
            await update.message.reply_document(
                document=f, filename="players_backup.db"
            )
    except Exception as e:
        logger.exception("Backup error: %s", e)
        await update.message.reply_text("Failed to send backup file.")


async def restore_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("Only admin can use this command.")
        return
    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text(
            "Reply to a backup database file with /restore to restore."
        )
        return
    doc = update.message.reply_to_message.document
    file = await doc.get_file()
    tmp_path = DB_PATH + ".restore_tmp"
    await file.download_to_drive(tmp_path)
    shutil.move(tmp_path, DB_PATH)
    await update.message.reply_text("Database restored from backup.")


async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("Only admin can use this command.")
        return
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Yes", callback_data="clear_yes"),
                InlineKeyboardButton("No", callback_data="clear_no"),
            ]
        ]
    )
    await update.message.reply_text(
        "Are you sure you want to delete all registration data?",
        reply_markup=keyboard,
    )


async def clear_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if data == "clear_no":
        await query.edit_message_text("Operation cancelled.")
        return
    if data != "clear_yes":
        return
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await query.answer("Only admin can perform this action.", show_alert=True)
        return
    clear_registration_data()
    await query.edit_message_text(
        "All registration data has been cleared. Runs, wickets and achievements remain safe."
    )


# ---------------- BROADCAST / REQUEST / ADMIN / REGMODE ----------------
async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    if user.id not in ADMIN_IDS:
        await update.message.reply_text("Only admin can use this command.")
        return

    msg = update.message

    known_users = get_known_users()
    known_groups = get_known_groups()

    sent = 0

    # PHOTO BROADCAST
    if msg.reply_to_message and msg.reply_to_message.photo:

        photo = msg.reply_to_message.photo[-1].file_id
        caption = msg.reply_to_message.caption or ""

        for uid in known_users:

            try:
                await context.bot.send_photo(
                    uid,
                    photo,
                    caption=caption
                )
                sent += 1
            except:
                pass

        for gid in known_groups:

            try:
                await context.bot.send_photo(
                    gid,
                    photo,
                    caption=caption
                )
            except:
                pass

        await update.message.reply_text(
            f"✅ Photo broadcast sent to {sent} users."
        )

        return

    # TEXT BROADCAST
    if msg.reply_to_message:

        content = (
            msg.reply_to_message.text
            or msg.reply_to_message.caption
        )

    else:

        if not context.args:

            await msg.reply_text(
                "Usage:\n"
                "/broadcast <text>\n"
                "OR reply to photo/text."
            )

            return

        content = " ".join(context.args)

    for uid in known_users:

        try:

            await context.bot.send_message(
                uid,
                content
            )

            sent += 1

        except:
            pass

    for gid in known_groups:

        try:

            await context.bot.send_message(
                gid,
                content
            )

        except:
            pass

    await msg.reply_text(
        f"✅ Broadcast sent to {sent} users."
    )
async def request_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("Only admin can use this command.")
        return

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            SELECT user_id, first_name, last_name, username, registered_at
            FROM players
            WHERE registered_at IS NOT NULL AND approved = 0
        """
        )
        pending = c.fetchall()

    if not pending:
        await update.message.reply_text("No pending registration requests.")
        return

    for admin in ADMIN_IDS:
        for uid, fn, ln, uname, reg_at in pending:
            text = (
                "Pending Registration\n\n"
                f"Name: {fn} {ln}\n"
                f"Username: @{uname if uname else '-'}\n"
                f"UserID: {uid}\n"
                f"Requested at: {reg_at}"
            )
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "Accept", callback_data=f"admin_accept:{uid}"
                        ),
                        InlineKeyboardButton(
                            "Reject", callback_data=f"admin_reject:{uid}"
                        ),
                    ]
                ]
            )
            try:
                await context.bot.send_message(
                    chat_id=admin, text=text, reply_markup=keyboard
                )
            except Exception:
                pass

    await update.message.reply_text(
        "All pending requests were sent to admin DMs (where possible)."
    )


async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("Only admin can use this command.")
        return

    admin_commands = [
        "/addruns @username <runs>",
        "/addwickets @username <wickets>",
        "/addachievement @username <text>",
        "/removeruns (reply or username)",
        "/removewickets (reply or username)",
        "/remove_achieve <username/user_id> <index>",
        "/broadcast (reply or text)",
        "/request (send pending to admin DMs)",
        "/backup",
        "/restore (reply to backup file)",
        "/clear",
        "/delruns (alias removeruns)",
        "/delwkt (alias removewickets)",
        "/list",
        "/regmode <on|off>",
    ]
    lines = ["👑 Admins and their commands:"]
    for aid in ADMIN_IDS:
        try:
            chat = await context.bot.get_chat(aid)
            name = chat.full_name or chat.username or str(aid)
        except Exception:
            name = str(aid)
        lines.append(f"\nAdmin: {name} (ID: {aid})")
        for cmd in admin_commands:
            lines.append(f" - {cmd}")
    await update.message.reply_text("\n".join(lines))


async def regmode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("Only admin can change registration mode.")
        return
    if not context.args or context.args[0].lower() not in ("on", "off"):
        await update.message.reply_text("Usage: /regmode on OR /regmode off")
        return
    mode = context.args[0].lower()
    set_setting("reg_mode", mode)
    await update.message.reply_text(f"Registration mode set to: {mode.upper()}")


async def chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_member: ChatMemberUpdated = update.chat_member
    chat = chat_member.chat
    new_status = chat_member.new_chat_member.status
    old_status = chat_member.old_chat_member.status
    if old_status in ("left", "kicked") and new_status in ("member", "administrator"):
        ensure_known_chat(chat)


# ---------------- MAIN ----------------
def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # basic commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("register", register_cmd))
    app.add_handler(CommandHandler("unregister", unregister_cmd))
    app.add_handler(CommandHandler("career", career_cmd))
    app.add_handler(CommandHandler("achievements", achievements_cmd))
    app.add_handler(CommandHandler("topplayers", topplayers_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("about", about_cmd))

    # admin stats
    app.add_handler(CommandHandler("addruns", addruns_cmd))
    app.add_handler(CommandHandler("addwickets", addwickets_cmd))
    app.add_handler(CommandHandler("removeruns", removeruns_cmd))
    app.add_handler(CommandHandler("removewickets", removewickets_cmd))
    app.add_handler(CommandHandler("delruns", delruns_cmd))
    app.add_handler(CommandHandler("delwkt", delwkt_cmd))
    app.add_handler(CommandHandler("addachievement", addachievement_cmd))
    app.add_handler(CommandHandler("remove_achieve", remove_achieve_cmd))

    # db & broadcast
    app.add_handler(CommandHandler("backup", backup_cmd))
    app.add_handler(CommandHandler("restore", restore_cmd))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("request", request_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("regmode", regmode_cmd))

    # callbacks
    app.add_handler(CallbackQueryHandler(confirm_callback, pattern=r"^confirm_"))
    app.add_handler(CallbackQueryHandler(handle_admin_callback, pattern=r"^admin_"))
    app.add_handler(CallbackQueryHandler(clear_callback, pattern=r"^clear_"))

    # track groups
    app.add_handler(
        ChatMemberHandler(chat_member_update, ChatMemberHandler.CHAT_MEMBER)
    )

    # track known chats/users when any message comes
    app.add_handler(
        MessageHandler(filters.ALL, lambda u, c: (ensure_known_user(u.effective_user),
                                                 ensure_known_chat(u.effective_chat)))
    )

    app.run_polling()


if __name__ == "__main__":
    main()