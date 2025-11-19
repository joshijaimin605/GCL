import logging
import sqlite3
import os
import shutil
from datetime import datetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Chat,
    ChatMemberUpdated,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ChatMemberHandler,
    MessageHandler,
    filters,
)

BOT_TOKEN = "8373191488:AAGeyXRQNOpuMhJxvsRvWfcpPqWn2dcjvpQ"

ADMIN_IDS = [5658402997, 1766243373] 
ADMIN_GROUP_ID = -1003224263115  # admin group where registration requests go

MAIN_GROUP_ID = -1002723854678
MAIN_CHANNEL_ID = -1002066951574

MAIN_GROUP_URL = "https://t.me/+HxuYXqXtqo82OTI9"
MAIN_CHANNEL_URL = "https://t.me/+jHDYeZOV9klkY2Fl"

DB_PATH = "players.db"

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


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
        conn.commit()
    if first:
        logger.info("Database created: %s", DB_PATH)
    else:
        logger.info("Database loaded successfully.")


def ensure_known_user(user):
    if not user:
        return
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            INSERT OR REPLACE INTO known_users (user_id, first_name, last_name, username, added_at)
            VALUES (?, ?, ?, ?, COALESCE((SELECT added_at FROM known_users WHERE user_id=?), ?))
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
            INSERT OR REPLACE INTO known_chats (chat_id, type, title, added_at)
            VALUES (?, ?, ?, COALESCE((SELECT added_at FROM known_chats WHERE chat_id=?), ?))
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


def is_registered(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT approved FROM players WHERE user_id = ?", (user_id,))
        r = c.fetchone()
        return r is not None and r[0] == 1


def get_player_status(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT approved FROM players WHERE user_id = ?",
            (user_id,),
        )
        row = c.fetchone()
        if not row:
            return None
        return row[0]


def approve_player(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("UPDATE players SET approved = 1 WHERE user_id = ?", (user_id,))
        conn.commit()


def delete_player_registration(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            UPDATE players
            SET approved = 0, registered_at = NULL
            WHERE user_id = ?
        """,
            (user_id,),
        )
        conn.commit()


def get_player_by_userid(user_id):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT first_name, last_name, username, runs, wickets, approved FROM players WHERE user_id = ?",
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
        c.execute(
            "UPDATE players SET runs = runs + ? WHERE lower(username) = lower(?)",
            (runs, username),
        )
        conn.commit()
        return c.rowcount


def add_wickets_to_user_by_username(username, wk):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "UPDATE players SET wickets = wickets + ? WHERE lower(username) = lower(?)",
            (wk, username),
        )
        conn.commit()
        return c.rowcount


def del_runs_from_user_by_username(username, runs):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            UPDATE players
            SET runs = MAX(runs - ?, 0)
            WHERE lower(username) = lower(?)
        """,
            (runs, username),
        )
        conn.commit()
        return c.rowcount


def del_wickets_from_user_by_username(username, wk):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            UPDATE players
            SET wickets = MAX(wickets - ?, 0)
            WHERE lower(username) = lower(?)
        """,
            (wk, username),
        )
        conn.commit()
        return c.rowcount


def add_achievement_by_username(username, text):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT user_id FROM players WHERE lower(username) = lower(?)", (username,)
        )
        row = c.fetchone()
        if not row:
            return False
        user_id = row[0]
        c.execute(
            "INSERT INTO achievements (user_id, text, created_at) VALUES (?, ?, ?)",
            (user_id, text, datetime.utcnow().isoformat()),
        )
        conn.commit()
        return True


def remove_achievement_by_user_and_index(user_id, index):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            "SELECT id FROM achievements WHERE user_id = ? ORDER BY id ASC", (user_id,)
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
        c.execute(
            "SELECT text, created_at FROM achievements WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        )
        return c.fetchall()


def get_approved_players():
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            SELECT user_id, first_name, last_name, username, runs, wickets
            FROM players WHERE approved = 1
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
            "SELECT COALESCE(SUM(runs), 0), COALESCE(SUM(wickets), 0) FROM players WHERE approved = 1"
        )
        total_runs, total_wickets = c.fetchone()
        return total_players, total_runs, total_wickets


def top_players(limit=3):
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            SELECT username, first_name, last_name, runs
            FROM players WHERE approved = 1
            ORDER BY runs DESC
            LIMIT ?
        """,
            (limit,),
        )
        bats = c.fetchall()
        c.execute(
            """
            SELECT username, first_name, last_name, wickets
            FROM players WHERE approved = 1
            ORDER BY wickets DESC
            LIMIT ?
        """,
            (limit,),
        )
        bowls = c.fetchall()
        return bats, bowls


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    ensure_known_user(user)
    ensure_known_chat(chat)
    first = user.first_name or user.username or ""
    if chat.type == Chat.PRIVATE:
        await update.message.reply_text(
            f"🎉 WELCOME TO GCL SEASON-8, {first} !\n\nUse the command menu (type /) to see available commands."
        )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 GCL Bot Commands\n\n"
        "PLAYER COMMANDS:\n"
        "/start - Welcome message\n"
        "/register - Register as a player\n"
        "/career - View your runs & wickets\n"
        "/achievements - View your achievements\n"
        "/topplayers - Top batsmen & bowlers\n"
        "/stats - Tournament totals & mini leaderboard\n"
        "/list - Approved players list\n"
    )
    await update.message.reply_text(text)


async def ensure_membership(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member_group = await context.bot.get_chat_member(MAIN_GROUP_ID, user_id)
        if member_group.status in ("left", "kicked"):
            raise Exception("Not in main group")
    except Exception:
        return False
    try:
        member_channel = await context.bot.get_chat_member(MAIN_CHANNEL_ID, user_id)
        if member_channel.status in ("left", "kicked"):
            raise Exception("Not in channel")
    except Exception:
        return False
    return True


async def register_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    user_id = user.id

    if not await ensure_membership(user_id, context):
        msg = (
            "⚠️ You have not joined our main channel and group yet.\n\n"
            f"Main Group: {MAIN_GROUP_URL}\n"
            f"Main Channel: {MAIN_CHANNEL_URL}\n\n"
            "Please join both and then use /register again to register yourself in GCL tournament."
        )
        await update.message.reply_text(msg)
        return

    status = get_player_status(user_id)
    if status == 1:
        await update.message.reply_text(
            "✅ You are already registered for GCL Season-8 with APPROVED status."
        )
        return
    elif status == 0:
        await update.message.reply_text(
            "⏳ You already have a registration request pending. Please wait for admin to ACCEPT or REJECT."
        )
        return

    first = user.first_name or ""
    last = user.last_name or ""
    username = user.username or ""
    add_or_update_pending(user_id, first, last, username)

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Yes", callback_data=f"confirm_yes:{user_id}"),
                InlineKeyboardButton("No", callback_data=f"confirm_no:{user_id}"),
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
        if chat.type != Chat.PRIVATE:
            await update.message.reply_text(
                "I have sent you a private message to confirm registration. Please check your bot chat."
            )
    except Exception:
        await update.message.reply_text(
            "Please open a private chat with the bot and press Start, then tap /register again."
        )


async def confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    if data.startswith("confirm_no:"):
        await query.edit_message_text("Registration cancelled.")
        return
    if not data.startswith("confirm_yes:"):
        return

    _, uid_s = data.split(":", 1)
    player_id = int(uid_s)
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
        first = last = ""
        username = ""

    text = (
        "New Registration Request\n\n"
        f"Player Name: {first} {last}\n"
        f"Username: @{username if username else '-'}\n"
        f"User ID: {player_id}"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Accept", callback_data=f"admin_accept:{player_id}"
                ),
                InlineKeyboardButton(
                    "Reject", callback_data=f"admin_reject:{player_id}"
                ),
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
        pass

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

    if data.startswith("admin_accept:") or data.startswith("admin_reject:"):
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
            first = last = ""
            username = ""

        if action == "admin_accept":
            approve_player(player_id)
            try:
                await context.bot.send_message(
                    chat_id=player_id,
                    text="Thank you! You have successfully registered for GCL Season-8 ✅",
                )
            except Exception:
                pass
            new_text = (
                "Player Accepted\n\n"
                f"Player Name: {first} {last}\n"
                f"Username: @{username if username else '-'}\n"
                f"User ID: {player_id}\n\n"
                "Status: ACCEPTED ✅"
            )
            await query.edit_message_text(new_text)
        else:
            delete_player_registration(player_id)
            try:
                await context.bot.send_message(
                    chat_id=player_id,
                    text=(
                        "Your registration for GCL Season-8 was rejected by admin.\n"
                        "You can send /register again to apply once more."
                    ),
                )
            except Exception:
                pass
            new_text = (
                "Player Rejected\n\n"
                f"Player Name: {first} {last}\n"
                f"Username: @{username if username else '-'}\n"
                f"User ID: {player_id}\n\n"
                "Status: REJECTED ❌"
            )
            await query.edit_message_text(new_text)

        try:
            if query.message and query.message.chat and query.message.chat.id == ADMIN_GROUP_ID:
                await context.bot.pin_chat_message(
                    chat_id=query.message.chat.id,
                    message_id=query.message.message_id,
                    disable_notification=True,
                )
        except Exception as e:
            logger.warning("Failed to pin message: %s", e)


async def career_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    p = get_player_by_userid(user.id)
    if not p or p[5] != 1:
        await update.message.reply_text(
            "You are not registered yet. Use /register first."
        )
    else:
        fn, ln, username, runs, wickets, approved = p
        target_username = username if username else (fn + " " + (ln or ""))
        ach = get_achievements(user.id)
        msg = (
            f"🏏 Career of @{target_username}\n\n"
            f"Runs: {runs}\n"
            f"Wickets: {wickets}\n\n"
            "Achievements:\n"
        )
        if not ach:
            msg += "You don't have any achievements yet. Keep playing!"
        else:
            for i, (text, created) in enumerate(ach, start=1):
                msg += f"{i}. {text}\n"
        await update.message.reply_text(msg)


async def achievements_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    target_id = user.id
    if update.message.reply_to_message:
        target_id = update.message.reply_to_message.from_user.id
    ach = get_achievements(target_id)
    if not ach:
        if target_id == user.id:
            await update.message.reply_text("🏆 You don't have any achievements yet.")
        else:
            await update.message.reply_text(
                "🏆 This player doesn't have any achievements yet."
            )
        return
    if target_id == user.id:
        header_name = user.first_name or user.username
    else:
        header_name = (
            update.message.reply_to_message.from_user.first_name
            or update.message.reply_to_message.from_user.username
        )
    msg = f"🏆 Achievements of {header_name}:\n\n"
    for i, (text, created) in enumerate(ach, start=1):
        msg += f"{i}. {text}\n"
    await update.message.reply_text(msg)


async def remove_achieve_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("Only admin can use this command.")
        return
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: /remove_achieve <username or user_id> <index>"
        )
        return
    ident = args[0]
    try:
        index = int(args[1])
    except ValueError:
        await update.message.reply_text("Index must be a number.")
        return
    target_id = None
    if ident.isdigit():
        target_id = int(ident)
    else:
        row = get_player_by_username(ident.lstrip("@"))
        if not row:
            await update.message.reply_text("Player not found.")
            return
        target_id = row[0]
    ok = remove_achievement_by_user_and_index(target_id, index)
    if ok:
        await update.message.reply_text("Achievement removed.")
    else:
        await update.message.reply_text("Invalid index or player has no achievements.")


async def topplayers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bats, bowls = top_players(3)
    msg = "🔥 Top Performers:\n\n🏃 Top Batsmen:\n"
    if not bats:
        msg += "No data yet."
    else:
        for i, (username, fn, ln, runs) in enumerate(bats, start=1):
            msg += f"{i}. @{username} — {runs} runs\n"
    msg += "\n🎯 Top Bowlers:\n"
    if not bowls:
        msg += "No data yet."
    else:
        for i, (username, fn, ln, wk) in enumerate(bowls, start=1):
            msg += f"{i}. @{username} — {wk} wickets\n"
    await update.message.reply_text(msg)


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    total_players, total_runs, total_wickets = totals_summary()
    bats, bowls = top_players(3)
    msg = (
        "📊 GCL Season 8 — Stats Summary\n\n"
        f"Total Players: {total_players}\n"
        f"Total Runs: {total_runs}\n"
        f"Total Wickets: {total_wickets}\n\n"
        "Mini Leaderboard:\n"
    )
    if bats:
        msg += f"Top Scorer: @{bats[0][0]} — {bats[0][3]} runs\n"
    if bowls:
        msg += f"Top Wicket-Taker: @{bowls[0][0]} — {bowls[0][3]} wickets\n"
    await update.message.reply_text(msg)


async def list_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    players = get_approved_players()
    if not players:
        await update.message.reply_text("No approved players yet.")
        return
    msg = "✅ Approved Players:\n\n"
    for i, (uid, fn, ln, username, runs, wickets) in enumerate(players, start=1):
        name = f"{fn} {ln}".strip()
        msg += f"{i}. {name} (@{username}) — Runs: {runs}, Wickets: {wickets}\n"
    await update.message.reply_text(msg)


async def about_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "🤖 GCL Season 8 Bot\nVersion: v1\nDeveloped by: You"
    await update.message.reply_text(msg)


async def addruns_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("Only admin can use this command.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /addruns @username <runs>")
        return
    username = context.args[0].lstrip("@")
    try:
        runs = int(context.args[1])
    except ValueError:
        await update.message.reply_text("Runs must be a number.")
        return
    updated = add_runs_to_user_by_username(username, runs)
    if updated:
        await update.message.reply_text(
            f"Added {runs} runs to @{username}'s career successfully."
        )
    else:
        await update.message.reply_text("Player not found.")


async def addwickets_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("Only admin can use this command.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /addwickets @username <wickets>")
        return
    username = context.args[0].lstrip("@")
    try:
        wk = int(context.args[1])
    except ValueError:
        await update.message.reply_text("Wickets must be a number.")
        return
    updated = add_wickets_to_user_by_username(username, wk)
    if updated:
        await update.message.reply_text(
            f"Added {wk} wickets to @{username}'s career successfully."
        )
    else:
        await update.message.reply_text("Player not found.")


async def delruns_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("Only admin can use this command.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /delruns @username <runs>")
        return
    username = context.args[0].lstrip("@")
    try:
        runs = int(context.args[1])
    except ValueError:
        await update.message.reply_text("Runs must be a number.")
        return
    updated = del_runs_from_user_by_username(username, runs)
    if updated:
        await update.message.reply_text(
            f"Deleted {runs} runs from @{username}'s career successfully."
        )
    else:
        await update.message.reply_text("Player not found.")


async def delwkt_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("Only admin can use this command.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /delwkt @username <wickets>")
        return
    username = context.args[0].lstrip("@")
    try:
        wk = int(context.args[1])
    except ValueError:
        await update.message.reply_text("Wickets must be a number.")
        return
    updated = del_wickets_from_user_by_username(username, wk)
    if updated:
        await update.message.reply_text(
            f"Deleted {wk} wickets from @{username}'s career successfully."
        )
    else:
        await update.message.reply_text("Player not found.")


async def addachievement_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("Only admin can use this command.")
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /addachievement @username \"Achievement text\""
        )
        return
    username = context.args[0].lstrip("@")
    text = " ".join(context.args[1:])
    ok = add_achievement_by_username(username, text)
    if ok:
        await update.message.reply_text("Achievement added.")
    else:
        await update.message.reply_text("Player not found.")


async def backup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("Only admin can use this command.")
        return
    if not os.path.exists(DB_PATH):
        await update.message.reply_text("Database file not found.")
        return
    await update.message.reply_document(
        document=open(DB_PATH, "rb"), filename="players_backup.db"
    )


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
        "Are you sure you want to delete all registration data?", reply_markup=keyboard
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
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute(
            """
            UPDATE players
            SET approved = 0,
                registered_at = NULL
        """
        )
        conn.commit()
    await query.edit_message_text("All registration data has been cleared.")


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("Only admin can use this command.")
        return

    message_to_broadcast = None
    if update.message.reply_to_message:
        message_to_broadcast = update.message.reply_to_message
    else:
        if not context.args:
            await update.message.reply_text(
                "Usage: reply any message with /broadcast or /broadcast <text>"
            )
            return
        text = " ".join(context.args)
        message_to_broadcast = text

    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()
        c.execute("SELECT user_id FROM known_users")
        user_rows = c.fetchall()
        c.execute("SELECT chat_id FROM known_chats")
        chat_rows = c.fetchall()

    sent_count = 0
    for (uid,) in user_rows:
        try:
            if isinstance(message_to_broadcast, str):
                await context.bot.send_message(chat_id=uid, text=message_to_broadcast)
            else:
                if message_to_broadcast.text:
                    await context.bot.send_message(
                        chat_id=uid, text=message_to_broadcast.text
                    )
            sent_count += 1
        except Exception:
            continue

    for (cid,) in chat_rows:
        if cid == MAIN_CHANNEL_ID:
            continue
        try:
            if isinstance(message_to_broadcast, str):
                await context.bot.send_message(chat_id=cid, text=message_to_broadcast)
            else:
                if message_to_broadcast.text:
                    await context.bot.send_message(
                        chat_id=cid, text=message_to_broadcast.text
                    )
            sent_count += 1
        except Exception:
            continue

    await update.message.reply_text(f"Broadcast sent to {sent_count} chats/users.")


async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["👑 Admins and their commands:\n"]
    admin_commands = [
        "/addruns @username <runs>",
        "/addwickets @username <wickets>",
        "/addachievement @username <text>",
        "/remove_achieve <username/user_id> <index>",
        "/broadcast <text> or reply",
        "/backup",
        "/restore (reply to backup file)",
        "/clear",
        "/delruns @username <runs>",
        "/delwkt @username <wickets>",
        "/admin",
    ]
    for aid in ADMIN_IDS:
        lines.append(f"Admin ID: `{aid}`")
        for cmd in admin_commands:
            lines.append(f"  - {cmd}")
        lines.append("")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_member: ChatMemberUpdated = update.chat_member
    chat = chat_member.chat
    new_status = chat_member.new_chat_member.status
    old_status = chat_member.old_chat_member.status
    if old_status in ("left", "kicked") and new_status in ("member", "administrator"):
        ensure_known_chat(chat)


def main():
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("register", register_cmd))
    app.add_handler(CommandHandler("career", career_cmd))
    app.add_handler(CommandHandler("achievements", achievements_cmd))
    app.add_handler(CommandHandler("topplayers", topplayers_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("list", list_cmd))
    app.add_handler(CommandHandler("about", about_cmd))

    app.add_handler(CommandHandler("addruns", addruns_cmd))
    app.add_handler(CommandHandler("addwickets", addwickets_cmd))
    app.add_handler(CommandHandler("addachievement", addachievement_cmd))
    app.add_handler(CommandHandler("delruns", delruns_cmd))
    app.add_handler(CommandHandler("delwkt", delwkt_cmd))
    app.add_handler(CommandHandler("remove_achieve", remove_achieve_cmd))

    app.add_handler(CommandHandler("backup", backup_cmd))
    app.add_handler(CommandHandler("restore", restore_cmd))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("admin", admin_cmd))

    app.add_handler(
        CallbackQueryHandler(confirm_callback, pattern=r"^confirm_(yes|no):")
    )
    app.add_handler(
        CallbackQueryHandler(handle_admin_callback, pattern=r"^admin_(accept|reject):")
    )
    app.add_handler(CallbackQueryHandler(clear_callback, pattern=r"^clear_(yes|no)$"))

    app.add_handler(ChatMemberHandler(chat_member_update, ChatMemberHandler.CHAT_MEMBER))

    app.run_polling()


if __name__ == "__main__":
    main()