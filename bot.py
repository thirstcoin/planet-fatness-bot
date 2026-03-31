import os
import logging
import random
import json
import threading
import asyncio
from flask import Flask
from datetime import datetime, timedelta, time
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from telegram.error import Forbidden, BadRequest

# --- SIDE CAR IMPORT ---
try:
    from phat_engine import PhatEngine
    phat_processor = PhatEngine()
except ImportError:
    phat_processor = None
    logging.error("❌ phat_engine.py not found. /phatme will be disabled.")

# ==========================================
# 1. ENGINE & WEB SERVER
# ==========================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Planet Fatness: All Systems Online 🧪🥊", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

threading.Thread(target=run_flask, daemon=True).start()

try:
    import psycopg2
except ImportError:
    psycopg2 = None

TOKEN = os.getenv("TELEGRAM_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
METER_GOAL = 20000
MAIN_CHAT_ID = int(os.getenv("MAIN_CHAT_ID", "0"))
RAMPAGE_SNACK_PENALTY = 2500
RAMPAGE_HUNT_DAMAGE = 1500
RAMPAGE_HUNT_COOLDOWN_MINUTES = 5
RAMPAGE_REMINDER_MINUTES = 15

# passive hunt cooldown memory
LAST_CHEF_HUNT_AT = None

# users hidden from all public leaderboard displays
REMOVED_LEADERBOARD_USERS = ("pop_polo", "dooragricky")

# ==========================================
# 2. DATA LOADING & HELPERS
# ==========================================
foods, hacks, punishments = [], [], []
try:
    with open("foods.json", "r") as f:
        foods = json.load(f)
    with open("hacks.json", "r") as f:
        hacks = json.load(f)
    with open("gift_punishments.json", "r") as f:
        punishments = json.load(f)
except Exception as e:
    logger.error(f"❌ JSON Load Failed: {e}")

CHARLIE_QUOTES = [
    # Phil Roast Mode
    "Phil says you built like a before picture.",
    "You got more Ls than a diet plan.",
    "That decision was calorie-deficient.",
    "You thought that was a good idea? Be honest.",
    "Phil wouldn't even spot you on that move.",
    "You just embarrassed your bloodline.",
    "That play had zero protein in it.",
    "You moving like low-cal behavior.",
    "Even the treadmill wouldn’t claim you.",
    "You built like you skip snack time.",

    # Kitchen / Chef Authority
    "The kitchen saw that and said no.",
    "Chef just revoked your plate.",
    "That wasn’t on the menu.",
    "You reached... and got cooked.",
    "The kitchen don’t forget.",
    "Chef don’t reward stupidity.",
    "You just lost meal privileges.",
    "Plate denied.",
    "That tray was not yours.",
    "The kitchen is disappointed.",

    # Greed / Punishment Energy
    "You got greedy. Again.",
    "One more wasn’t the move.",
    "You should’ve stopped.",
    "That last click cost you.",
    "Greed got you cooked.",
    "You played yourself for calories.",
    "You almost had it… then ruined it.",
    "That was the line. You crossed it.",
    "You fumbled the bag and the snack.",
    "Perfect run… until you showed up.",

    # Food Puns / Calorie Humor
    "That was a heavy L.",
    "You just dropped calories on impact.",
    "Zero gains detected.",
    "That move burned nothing but dignity.",
    "You’re not bulking, you’re collapsing.",
    "That was not gym behavior.",
    "Snack denied. Try again later.",
    "You lost more than calories just now.",
    "That decision was deep fried garbage.",
    "You got cooked without seasoning.",

    # Smack / Aggro Energy
    "Hands rated E for everyone.",
    "That slap came with seasoning.",
    "Full force. No hesitation.",
    "That one echoed through the kitchen.",
    "You felt that in your macros.",
    "That wasn’t a warning shot.",
    "Clean hit. Ugly outcome.",
    "You got checked immediately.",
    "That was disrespectful levels of force.",
    "Somebody had to do it.",

    # Gym / Planet Fatness Tone
    "This gym don’t forgive.",
    "Tapping counts as cardio… not whatever that was.",
    "You just lost your membership.",
    "Phil is shaking his head.",
    "That’s not how we bulk here.",
    "You failed the vibe check.",
    "That was weak energy.",
    "You not built for this gym.",
    "You’re on thin ice with the kitchen.",
    "That wasn’t very phat of you.",

    # Rare / Positive Hits
    "Phil approves… this time.",
    "That was actually solid.",
    "You might be learning.",
    "Clean execution. Respect.",
    "You got away with one.",
    "That was dangerously competent.",
    "The kitchen allowed it.",
    "You earned that plate.",
    "Certified bulk behavior.",
    "That one counts."
]

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def escape_name(name):
    if not name:
        return "Degen"
    return name.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`").replace("[", "\\[")

def get_progress_bar(current, total=METER_GOAL):
    percent = min(100, int((current / total) * 100))
    blocks = int(percent / 10)
    bar = "█" * blocks + "░" * (10 - blocks)
    return f"`[{bar}] {percent}%`"

def get_icu_rank(visits):
    if visits == 0:
        return "Fresh Meat"
    if visits < 5:
        return "Lab Rat"
    if visits < 15:
        return "Code Blue Veteran"
    if visits < 30:
        return "Defibrillator Junkie"
    if visits < 50:
        return "Cardiac Immortal"
    return "Ghost of Planet Fatness"

def get_win_title(wins, is_hacker=False):
    if wins == 0:
        return None
    if is_hacker:
        if wins < 5:
            return "Script Kiddie"
        if wins < 15:
            return "System Breach"
        return "Mainframe Ghost"
    else:
        if wins < 5:
            return "Local Glutton"
        if wins < 15:
            return "Buffet Legend"
        return "Black Hole"

def random_charlie_quote():
    return random.choice(CHARLIE_QUOTES)

def roll_punishment():
    if not punishments:
        return None

    total_weight = sum(int(p.get("weight", 1)) for p in punishments)
    if total_weight <= 0:
        return None

    r = random.uniform(0, total_weight)
    upto = 0

    for p in punishments:
        w = int(p.get("weight", 1))
        if upto + w >= r:
            low = int(p.get("min", -1000))
            high = int(p.get("max", -500))
            if low > high:
                low, high = high, low
            value = random.randint(low, high)
            return {
                "name": p.get("name", "Cursed Delivery"),
                "value": value,
                "text": p.get("text", "Something went horribly wrong.")
            }
        upto += w

    p = punishments[-1]
    low = int(p.get("min", -1000))
    high = int(p.get("max", -500))
    if low > high:
        low, high = high, low
    return {
        "name": p.get("name", "Cursed Delivery"),
        "value": random.randint(low, high),
        "text": p.get("text", "Something went horribly wrong.")
    }

def is_founder(user):
    return bool(user and user.username and user.username.lower() == "tikotaco")

def safe_close(cur=None, conn=None):
    try:
        if cur:
            cur.close()
    except Exception:
        pass
    try:
        if conn:
            conn.close()
    except Exception:
        pass

def ensure_user_record(cur, user):
    username = user.username or user.first_name or f"user_{user.id}"
    cur.execute("""
        INSERT INTO pf_users (user_id, username)
        VALUES (%s, %s)
        ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username
    """, (user.id, username))

def ensure_user_id_record(cur, user_id, username="Unknown"):
    cur.execute("""
        INSERT INTO pf_users (user_id, username)
        VALUES (%s, %s)
        ON CONFLICT (user_id) DO NOTHING
    """, (user_id, username))

def rampage_active_until(rampage_until, now=None):
    now = now or datetime.utcnow()
    return bool(rampage_until and rampage_until > now)

def is_kitchen_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_id = context.bot.id
    bot_username = (context.bot.username or "").lower()

    if update.message.reply_to_message and update.message.reply_to_message.from_user.id == bot_id:
        return True

    if context.args:
        raw = context.args[0].strip().lower().lstrip("@")
        if raw in {"kitchen", "chef"}:
            return True
        if bot_username and raw == bot_username:
            return True

    return False

def get_rage_tier(rage):
    if rage >= 100:
        return 100
    if rage >= 75:
        return 75
    if rage >= 50:
        return 50
    if rage >= 25:
        return 25
    return 0

async def send_main_chat_message(bot, text):
    if not MAIN_CHAT_ID:
        return
    try:
        await bot.send_message(
            chat_id=MAIN_CHAT_ID,
            text=text,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.warning(f"Main chat send failed: {e}")

async def maybe_announce_rage(bot, cur, conn, rage):
    tier = get_rage_tier(rage)

    cur.execute("""
        SELECT last_rage_announce_level
        FROM pf_users
        WHERE user_id = 0
    """)
    row = cur.fetchone()
    last_tier = row[0] if row and row[0] is not None else 0

    if tier <= last_tier or tier == 0:
        return

    if tier == 25:
        msg = (
            f"👨‍🍳 **CHEF IS HEATING UP...**\n"
            f"🔥 **Chef Rage:** {rage}/100\n"
            f"The kitchen is starting to notice the disrespect."
        )
    elif tier == 50:
        msg = (
            f"👨‍🍳 **CHEF WARNING**\n"
            f"🔥 **Chef Rage:** {rage}/100\n"
            f"The kitchen is pissed. Rampage is getting closer."
        )
    elif tier == 75:
        msg = (
            f"🚨 **CHEF IS NEAR BOILING**\n"
            f"🔥 **Chef Rage:** {rage}/100\n"
            f"One more wave of disrespect and the kitchen could snap."
        )
    else:
        msg = (
            f"💥 **CHEF RAMPAGE ACTIVATED** 💥\n"
            f"🔥 **Chef Rage:** {rage}/100\n"
            f"⏳ **Duration:** 1 hour\n"
            f"⚠️ Snacks are now dangerous (**50/50** for **-{RAMPAGE_SNACK_PENALTY:,} Cal**)\n"
            f"⚠️ Anyone with heat is now in play.\n"
            f"The kitchen has lost control."
        )

    await send_main_chat_message(bot, msg)

    cur.execute("""
        UPDATE pf_users
        SET last_rage_announce_level = %s
        WHERE user_id = 0
    """, (tier,))
    conn.commit()

async def maybe_send_rampage_reminder(bot, cur, conn, rampage_until, now):
    if not rampage_active_until(rampage_until, now):
        return

    cur.execute("""
        SELECT last_rampage_reminder_at
        FROM pf_users
        WHERE user_id = 0
    """)
    row = cur.fetchone()
    last_reminder = row[0] if row else None

    if last_reminder and (now - last_reminder) < timedelta(minutes=RAMPAGE_REMINDER_MINUTES):
        return

    mins_left = max(1, int((rampage_until - now).total_seconds() // 60))
    await send_main_chat_message(
        bot,
        f"🔥 **CHEF RAMPAGE IS STILL LIVE**\n"
        f"⏳ **Time left:** {mins_left}m\n"
        f"⚠️ Snack risk is active (**50/50** for **-{RAMPAGE_SNACK_PENALTY:,} Cal**)\n"
        f"⚠️ Anyone with heat can be hunted."
    )

    cur.execute("""
        UPDATE pf_users
        SET last_rampage_reminder_at = %s
        WHERE user_id = 0
    """, (now,))
    conn.commit()

async def maybe_send_rampage_end(bot, cur, conn, old_until, now):
    if not old_until or old_until > now:
        return

    cur.execute("""
        SELECT rampage_end_announced_for
        FROM pf_users
        WHERE user_id = 0
    """)
    row = cur.fetchone()
    announced_for = row[0] if row else None

    if announced_for == old_until:
        return

    await send_main_chat_message(
        bot,
        "🧊 **CHEF HAS COOLED OFF**\nThe kitchen is no longer in rampage mode.\nFor now."
    )

    cur.execute("""
        UPDATE pf_users
        SET rampage_end_announced_for = %s,
            last_rampage_reminder_at = NULL
        WHERE user_id = 0
    """, (old_until,))
    conn.commit()

# ==========================================
# 3. DATABASE INITIALIZATION & MIGRATIONS
# ==========================================
def init_db(bot_id=None):
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS pf_users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                total_calories BIGINT DEFAULT 0,
                daily_calories INTEGER DEFAULT 0,
                daily_clog NUMERIC DEFAULT 0,
                is_icu BOOLEAN DEFAULT FALSE,
                last_snack TIMESTAMP,
                last_hack TIMESTAMP,
                ping_sent TIMESTAMP,
                last_gift_sent TIMESTAMP,
                last_pfp_gen TIMESTAMP,
                sabotage_val BIGINT DEFAULT 0,
                gifts_sent_val BIGINT DEFAULT 0,
                icu_lifetime INTEGER DEFAULT 0,
                smack_count INTEGER DEFAULT 0,
                last_smack_time TIMESTAMP,
                smack_ids TEXT DEFAULT '',
                daily_ko_count INTEGER DEFAULT 0,
                last_ko_time TIMESTAMP,
                lifetime_daily_wins INTEGER DEFAULT 0,
                lifetime_hack_wins INTEGER DEFAULT 0,
                heat_level INTEGER DEFAULT 0,
                rampage_until TIMESTAMP,
                last_rage_announce_level INTEGER DEFAULT 0,
                last_rampage_reminder_at TIMESTAMP,
                rampage_end_announced_for TIMESTAMP,
                leaderboard_enabled BOOLEAN DEFAULT TRUE
            );
        """)

        migrations = [
            ("last_pfp_gen", "TIMESTAMP"),
            ("icu_lifetime", "INTEGER DEFAULT 0"),
            ("smack_count", "INTEGER DEFAULT 0"),
            ("last_smack_time", "TIMESTAMP"),
            ("smack_ids", "TEXT DEFAULT ''"),
            ("daily_ko_count", "INTEGER DEFAULT 0"),
            ("last_ko_time", "TIMESTAMP"),
            ("lifetime_daily_wins", "INTEGER DEFAULT 0"),
            ("lifetime_hack_wins", "INTEGER DEFAULT 0"),
            ("heat_level", "INTEGER DEFAULT 0"),
            ("rampage_until", "TIMESTAMP"),
            ("last_rage_announce_level", "INTEGER DEFAULT 0"),
            ("last_rampage_reminder_at", "TIMESTAMP"),
            ("rampage_end_announced_for", "TIMESTAMP"),
            ("leaderboard_enabled", "BOOLEAN DEFAULT TRUE")
        ]
        for col_name, col_type in migrations:
            try:
                cur.execute(f"ALTER TABLE pf_users ADD COLUMN IF NOT EXISTS {col_name} {col_type};")
                conn.commit()
            except Exception:
                conn.rollback()

        cur.execute("""
            INSERT INTO pf_users (user_id, username, total_calories, daily_calories)
            VALUES (0, 'KITCHEN_SYSTEM', 0, 0)
            ON CONFLICT (user_id) DO NOTHING
        """)

        cur.execute("""
            UPDATE pf_users
            SET leaderboard_enabled = FALSE
            WHERE LOWER(REPLACE(COALESCE(username, ''), '@', '')) IN (%s, %s)
        """, REMOVED_LEADERBOARD_USERS)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS pf_airdrop_winners (
                id SERIAL PRIMARY KEY,
                winner_type TEXT,
                username TEXT,
                score NUMERIC,
                win_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS pf_gifts (
                id SERIAL PRIMARY KEY,
                sender_id BIGINT,
                sender_name TEXT,
                receiver_id BIGINT,
                item_name TEXT,
                item_type TEXT,
                value INTEGER,
                flavor_text TEXT,
                is_opened BOOLEAN DEFAULT FALSE
            );
        """)

        if bot_id:
            cur.execute("DELETE FROM pf_gifts WHERE receiver_id = %s", (bot_id,))

        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Init DB Error: {e}")
    finally:
        safe_close(cur, conn)

# ==========================================
# 4. AUTOMATED TASKS
# ==========================================
async def automated_reset_task(application):
    while True:
        now_utc = datetime.utcnow()
        if now_utc.hour == 1 and now_utc.minute == 0:
            conn = None
            cur = None
            try:
                conn = get_db_connection()
                cur = conn.cursor()

                for label, col in [('DAILY PHATTEST', 'daily_calories'), ('TOP HACKER', 'daily_clog')]:
                    cur.execute(f"""
                        SELECT user_id, username, {col}
                        FROM pf_users
                        WHERE user_id != 0
                          AND {col} > 0
                          AND COALESCE(leaderboard_enabled, TRUE) = TRUE
                        ORDER BY {col} DESC
                        LIMIT 1
                    """)
                    winner = cur.fetchone()
                    if winner:
                        w_id, w_name, w_score = winner
                        cur.execute(
                            "INSERT INTO pf_airdrop_winners (winner_type, username, score) VALUES (%s, %s, %s)",
                            (label, w_name, w_score)
                        )
                        win_col = "lifetime_daily_wins" if label == 'DAILY PHATTEST' else "lifetime_hack_wins"
                        cur.execute(f"UPDATE pf_users SET {win_col} = {win_col} + 1 WHERE user_id = %s", (w_id,))

                cur.execute("DELETE FROM pf_airdrop_winners WHERE win_date < NOW() - INTERVAL '7 days'")
                cur.execute("""
                    UPDATE pf_users
                    SET daily_calories = 0,
                        daily_clog = 0,
                        is_icu = FALSE,
                        daily_ko_count = 0,
                        heat_level = 0,
                        rampage_until = NULL,
                        last_rage_announce_level = 0,
                        last_rampage_reminder_at = NULL,
                        rampage_end_announced_for = NULL,
                        last_snack = NULL,
                        last_hack = NULL
                """)

                conn.commit()
                logger.info("🧹 Daily Reset & Win Tracking Complete.")
            except Exception as e:
                if conn:
                    conn.rollback()
                logger.error(f"Reset Error: {e}")
            finally:
                safe_close(cur, conn)
            await asyncio.sleep(61)
        await asyncio.sleep(30)

async def check_pings(application):
    while True:
        await asyncio.sleep(60)
        pass

async def chef_rampage_task(application):
    global LAST_CHEF_HUNT_AT
    while True:
        await asyncio.sleep(30)

        conn = None
        cur = None
        try:
            now = datetime.utcnow()

            if LAST_CHEF_HUNT_AT and (now - LAST_CHEF_HUNT_AT) < timedelta(minutes=RAMPAGE_HUNT_COOLDOWN_MINUTES):
                continue

            conn = get_db_connection()
            cur = conn.cursor()

            cur.execute("""
                SELECT daily_calories, rampage_until
                FROM pf_users
                WHERE user_id = 0
            """)
            kitchen = cur.fetchone()
            if not kitchen:
                continue

            chef_rage = kitchen[0] or 0
            rampage_until = kitchen[1]

            await maybe_send_rampage_end(application.bot, cur, conn, rampage_until, now)
            await maybe_send_rampage_reminder(application.bot, cur, conn, rampage_until, now)

            if not rampage_active_until(rampage_until, now):
                continue

            cur.execute("""
                SELECT user_id, username, heat_level
                FROM pf_users
                WHERE user_id != 0 AND heat_level > 0
                ORDER BY heat_level DESC, total_calories DESC
                LIMIT 1
            """)
            hunted = cur.fetchone()

            if not hunted:
                continue

            hunted_id, hunted_name, hunted_heat = hunted
            hunt_damage = RAMPAGE_HUNT_DAMAGE
            new_heat = max(0, (hunted_heat or 0) - 30)

            cur.execute("""
                UPDATE pf_users
                SET daily_calories = GREATEST(0, daily_calories - %s),
                    total_calories = GREATEST(0, total_calories - %s),
                    heat_level = %s
                WHERE user_id = %s
            """, (hunt_damage, hunt_damage, new_heat, hunted_id))

            conn.commit()
            LAST_CHEF_HUNT_AT = now

            try:
                mins_left = max(1, int((rampage_until - now).total_seconds() // 60))
                await send_main_chat_message(
                    application.bot,
                    (
                        f"👨‍🍳 **CHEF HUNT!** @{escape_name(hunted_name)} got caught during rampage.\n"
                        f"💥 **-{hunt_damage:,} Cal**\n"
                        f"🌡️ Heat burned down to **{new_heat}**\n"
                        f"🔥 Rampage still live: **{mins_left}m**\n"
                        f"🎤 *{random_charlie_quote()}*"
                    )
                )
            except (Forbidden, BadRequest):
                pass
            except Exception as dm_err:
                logger.warning(f"Chef hunt send failed: {dm_err}")

            logger.info(f"👨‍🍳 Passive Chef Hunt hit user_id={hunted_id} heat={hunted_heat} -> {new_heat}")
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Chef Rampage Task Error: {e}")
        finally:
            safe_close(cur, conn)

# ==========================================
# 5. CORE ACTIONS (SNACK & HACK)
# ==========================================
async def snack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, now = update.effective_user, datetime.utcnow()
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        ensure_user_record(cur, user)

        cur.execute("""
            SELECT total_calories, daily_calories, last_snack, heat_level
            FROM pf_users
            WHERE user_id = %s
        """, (user.id,))
        u = cur.fetchone()

        cur.execute("SELECT total_calories, daily_calories, rampage_until FROM pf_users WHERE user_id = 0")
        kitchen = cur.fetchone()
        kitchen_meter = kitchen[0] if kitchen else 0
        chef_rage = kitchen[1] if kitchen else 0
        kitchen_rampage_until = kitchen[2] if kitchen else None

        c_total = u[0] or 0
        c_daily = u[1] or 0
        last_snack = u[2]
        heat_level = u[3] or 0
        rampage_live = rampage_active_until(kitchen_rampage_until, now)

        if last_snack and now - last_snack < timedelta(hours=1):
            rem = timedelta(hours=1) - (now - last_snack)
            return await update.message.reply_text(f"⌛️ Digesting... {int(rem.total_seconds()//60)}m left.")

        if rampage_live:
            if random.random() < 0.50:
                ended_rampage = False

                cur.execute("""
                    UPDATE pf_users
                    SET daily_calories = GREATEST(0, daily_calories - %s),
                        total_calories = GREATEST(0, total_calories - %s),
                        last_snack = %s
                    WHERE user_id = %s
                """, (RAMPAGE_SNACK_PENALTY, RAMPAGE_SNACK_PENALTY, now, user.id))

                if random.random() < 0.25:
                    cur.execute("""
                        UPDATE pf_users
                        SET daily_calories = 0,
                            rampage_until = NULL,
                            last_rampage_reminder_at = NULL,
                            rampage_end_announced_for = NULL
                        WHERE user_id = 0
                    """)
                    ended_rampage = True

                conn.commit()

                if ended_rampage:
                    await send_main_chat_message(
                        context.bot,
                        "🧊 **CHEF HAS COOLED OFF**\nThe kitchen is no longer in rampage mode.\nFor now."
                    )

                return await update.message.reply_text(
                    f"🔥 **RAMPAGE MODE!**\n"
                    f"💀 The Chef caught you slippin! **-{RAMPAGE_SNACK_PENALTY:,} Cal**\n"
                    f"🎤 *{random_charlie_quote()}*",
                    parse_mode='Markdown'
                )

        if heat_level > 60 and random.random() < 0.50:
            cur.execute("UPDATE pf_users SET last_snack = %s WHERE user_id = %s", (now, user.id))
            conn.commit()
            return await update.message.reply_text(
                f"👨‍🍳 **FOOD CONFISCATED!** The Chef snatched your plate.\n"
                f"🎤 *{random_charlie_quote()}*",
                parse_mode='Markdown'
            )

        item = random.choice(foods)
        cal_val = item.get('calories', 0)
        gif_url = item.get('gif')
        bullish_moon = False

        # True independent 1% jackpot roll
        if random.random() < 0.01:
            cal_val = 10000
            bullish_moon = True

        new_daily = c_daily + cal_val
        new_total = max(0, c_total + cal_val)

        cur.execute("""
            INSERT INTO pf_users (user_id, username, total_calories, daily_calories, last_snack)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
            username = EXCLUDED.username,
            total_calories = %s,
            daily_calories = %s,
            last_snack = %s
        """, (
            user.id,
            user.username or user.first_name,
            new_total,
            new_daily,
            now,
            new_total,
            new_daily,
            now
        ))

        conn.commit()

        if bullish_moon:
            caption = (
                f"🚀 **BULLISH MOON!** Buy another one, ya rich mothafucka!\n"
                f"🎰 **+10,000 Cal**\n"
                f"🔥 Daily: {new_daily:,}"
            )
            await update.message.reply_text(caption, parse_mode='Markdown')
        else:
            sign = "+" if cal_val > 0 else ""
            if rampage_live:
                caption = (
                    f"🍔 **RAMPAGE SURVIVED!** You escaped the 2k punishment.\n"
                    f"**{item['name']}** ({sign}{cal_val:,} Cal)\n"
                    f"🔥 Daily: {new_daily:,}"
                )
            else:
                caption = f"🍔 **{item['name']}** ({sign}{cal_val:,} Cal)\n🔥 Daily: {new_daily:,}"
            if gif_url and not bullish_moon:
                await update.message.reply_animation(animation=gif_url, caption=caption, parse_mode='Markdown')
            else:
                await update.message.reply_text(caption, parse_mode='Markdown')

    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Snack Error: {e}")
        await update.message.reply_text("❌ Kitchen Busy.")
    finally:
        safe_close(cur, conn)

async def hack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id, now = user.id, datetime.utcnow()
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        ensure_user_record(cur, user)

        cur.execute("SELECT CAST(daily_clog AS FLOAT), is_icu, last_hack FROM pf_users WHERE user_id = %s", (user_id,))
        u = cur.fetchone()
        clog, is_icu, l_hack = (u[0] if u else 0.0, u[1] if u else False, u[2] if u else None)

        cd = timedelta(hours=2) if is_icu else timedelta(hours=1)

        if l_hack and now - l_hack < cd:
            rem = cd - (now - l_hack)
            return await update.message.reply_text(f"🏥 {'ICU' if is_icu else 'Recovery'}: {int(rem.total_seconds()//60)}m left.")

        h = random.choice(hacks)
        gain = float(random.randint(int(h.get("min_clog", 1)), int(h.get("max_clog", 5))))

        bonus_text = ""
        if random.random() < 0.10:
            gain += 0.5
            bonus_text = "🧬 **CELLULAR MUTATION:** +.5% extra clog!\n"

        new_c = clog + gain

        if new_c >= 100:
            cur.execute("""
                UPDATE pf_users
                SET daily_clog = 0,
                    is_icu = TRUE,
                    last_hack = %s,
                    icu_lifetime = icu_lifetime + 1
                WHERE user_id = %s
            """, (now, user_id))
            await update.message.reply_text("💀 **FLATLINE!** Lab failure. ICU for 2 hours.\n📈 Lifetime Visits Logged.")
        else:
            cur.execute("""
                UPDATE pf_users
                SET daily_clog = %s,
                    is_icu = FALSE,
                    last_hack = %s
                WHERE user_id = %s
            """, (new_c, now, user_id))
            await update.message.reply_text(
                f"🩺 **HACK SUCCESS:** {h.get('name')}\n"
                f"📋 **Order:** {h.get('blueprint', 'Classified information.')}\n"
                f"{bonus_text}📈 Clog: {new_c:.1f} % (+{gain}%)",
                parse_mode='Markdown'
            )
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Hack Error: {e}")
        await update.message.reply_text("⚠️ Lab system jammed.")
    finally:
        safe_close(cur, conn)

# ==========================================
# 6. SMACKDOWN PROTOCOL
# ==========================================
async def smack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    attacker, now = update.effective_user, datetime.utcnow()
    target = None
    kitchen_target = False

    if is_kitchen_target(update, context):
        kitchen_target = True
        target = type('KitchenTarget', (object,), {
            'id': 0,
            'username': 'KITCHEN_SYSTEM',
            'first_name': 'Chef'
        })
    elif update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
    elif context.args:
        target_username = context.args[0].strip('@')
        conn = None
        cur = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                "SELECT user_id, username FROM pf_users WHERE username = %s OR username = %s",
                (target_username, f"@{target_username}")
            )
            res = cur.fetchone()
            if res:
                target = type('User', (object,), {
                    'id': res[0],
                    'username': target_username,
                    'first_name': target_username
                })
            else:
                return await update.message.reply_text(
                    f"❌ Target @{target_username} not found in the lab database.\n"
                    f"🎤 *{random_charlie_quote()}*",
                    parse_mode='Markdown'
                )
        except Exception as e:
            logger.error(f"Smack Lookup Error: {e}")
            return await update.message.reply_text("⚠️ Smack lookup jammed.")
        finally:
            safe_close(cur, conn)

    if not target:
        return await update.message.reply_text(
            "🥊 **HOW TO SMACK:**\n1. Reply to a message with `/smack`\n2. Type `/smack @username`\n3. Type `/smack kitchen`\n"
            f"🎤 *{random_charlie_quote()}*",
            parse_mode='Markdown'
        )

    if target.id == attacker.id:
        return await update.message.reply_text(
            f"🚫 You cannot smack yourself.\n🎤 *{random_charlie_quote()}*",
            parse_mode='Markdown'
        )

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        ensure_user_record(cur, attacker)
        ensure_user_id_record(cur, target.id, target.username or target.first_name or "Unknown")

        cur.execute("SELECT daily_calories FROM pf_users WHERE user_id = %s", (attacker.id,))
        a_res = cur.fetchone()
        if not a_res or (a_res[0] or 0) < 200:
            return await update.message.reply_text(
                f"🦴 You are too weak. Smacking costs 200 Cal.\n🎤 *{random_charlie_quote()}*",
                parse_mode='Markdown'
            )

        rage_gain = random.randint(5, 15)
        cur.execute("""
            UPDATE pf_users
            SET daily_calories = daily_calories + %s
            WHERE user_id = 0
            RETURNING daily_calories, rampage_until
        """, (rage_gain,))
        chef_state = cur.fetchone()
        chef_rage = chef_state[0] if chef_state and chef_state[0] else 0
        current_rampage_until = chef_state[1] if chef_state else None
        await maybe_announce_rage(context.bot, cur, conn, chef_rage)

        if kitchen_target:
            kitchen_heat_gain = random.randint(5, 25)
            kitchen_bonus_rage = 15

            cur.execute("""
                UPDATE pf_users
                SET daily_calories = GREATEST(0, daily_calories - 2000),
                    total_calories = GREATEST(0, total_calories - 2000),
                    heat_level = heat_level + %s
                WHERE user_id = %s
            """, (kitchen_heat_gain, attacker.id))

            cur.execute("""
                UPDATE pf_users
                SET daily_calories = daily_calories + %s
                WHERE user_id = 0
                RETURNING daily_calories, rampage_until
            """, (kitchen_bonus_rage,))
            chef_state = cur.fetchone()
            chef_rage = chef_state[0] if chef_state and chef_state[0] else 0
            current_rampage_until = chef_state[1] if chef_state else None
            await maybe_announce_rage(context.bot, cur, conn, chef_rage)

            if chef_rage >= 100 and not rampage_active_until(current_rampage_until, now):
                new_rampage_until = now + timedelta(hours=1)
                cur.execute("""
                    UPDATE pf_users
                    SET rampage_until = %s,
                        last_rampage_reminder_at = NULL,
                        rampage_end_announced_for = NULL
                    WHERE user_id = 0
                """, (new_rampage_until,))
                current_rampage_until = new_rampage_until

            conn.commit()

            msg = (
                f"👨‍🍳 **CHEF SMACK-BACK!** You slapped the kitchen and got folded.\n"
                f"💥 **-2,000 Cal**\n"
                f"🌡️ **Heat +{kitchen_heat_gain}**\n"
                f"🔥 **CHEF RAGE:** {chef_rage}/100\n"
            )
            if rampage_active_until(current_rampage_until, now):
                mins_left = max(1, int((current_rampage_until - now).total_seconds() // 60))
                msg += f"🔥 **CHEF RAMPAGE LIVE:** {mins_left}m left.\n"
            msg += f"🎤 *{random_charlie_quote()}*"
            return await update.message.reply_text(msg, parse_mode='Markdown')

        cur.execute("""
            SELECT smack_count, last_smack_time, smack_ids, daily_ko_count, last_ko_time
            FROM pf_users
            WHERE user_id = %s
        """, (target.id,))
        t_data = cur.fetchone()
        s_count, l_smack, s_ids, ko_count, l_ko = t_data if t_data else (0, None, "", 0, None)

        if l_smack and now - l_smack > timedelta(minutes=15):
            s_count, s_ids = 0, ""

        if l_ko and now - l_ko < timedelta(hours=6):
            rem = timedelta(hours=6) - (now - l_ko)
            return await update.message.reply_text(
                f"🛡️ Target is in recovery. Immune for {int(rem.total_seconds()//60)}m.\n"
                f"🎤 *{random_charlie_quote()}*",
                parse_mode='Markdown'
            )

        if ko_count >= 2:
            return await update.message.reply_text(
                f"🛡️ Target has reached the daily limit of knockouts.\n🎤 *{random_charlie_quote()}*",
                parse_mode='Markdown'
            )

        s_list = s_ids.split(",") if s_ids else []
        if str(attacker.id) in s_list:
            return await update.message.reply_text(
                f"🚫 You already smacked this user in this window!\n🎤 *{random_charlie_quote()}*",
                parse_mode='Markdown'
            )

        if chef_rage >= 100 and not rampage_active_until(current_rampage_until, now):
            new_rampage_until = now + timedelta(hours=1)
            cur.execute("""
                UPDATE pf_users
                SET rampage_until = %s,
                    last_rampage_reminder_at = NULL,
                    rampage_end_announced_for = NULL
                WHERE user_id = 0
            """, (new_rampage_until,))
            current_rampage_until = new_rampage_until

        if chef_rage > 50 and random.random() < 0.30:
            counter_heat_gain = random.randint(5, 25)
            cur.execute("""
                UPDATE pf_users
                SET daily_calories = GREATEST(0, daily_calories - 1500),
                    total_calories = GREATEST(0, total_calories - 1500),
                    heat_level = heat_level + %s
                WHERE user_id = %s
            """, (counter_heat_gain, attacker.id))
            conn.commit()
            return await update.message.reply_text(
                f"👨‍🍳 **COUNTER-SLAP!** The Chef wasn't having it.\n"
                f"💥 **-1,500 Cal**\n"
                f"🌡️ **Heat +{counter_heat_gain}**\n"
                f"🎤 *{random_charlie_quote()}*",
                parse_mode='Markdown'
            )

        s_count += 1
        s_list.append(str(attacker.id))
        new_s_ids = ",".join(s_list)
        smack_heat_gain = random.randint(5, 25)

        cur.execute("""
            UPDATE pf_users
            SET daily_calories = GREATEST(0, daily_calories - 200),
                total_calories = GREATEST(0, total_calories - 200),
                heat_level = heat_level + %s
            WHERE user_id = %s
        """, (smack_heat_gain, attacker.id))

        if s_count >= 5:
            cur.execute("""
                UPDATE pf_users
                SET daily_calories = GREATEST(0, daily_calories - 2500),
                    total_calories = GREATEST(0, total_calories - 2500),
                    smack_count = 0,
                    smack_ids = '',
                    daily_ko_count = daily_ko_count + 1,
                    last_ko_time = %s
                WHERE user_id = %s
            """, (now, target.id))
            msg = (
                f"💥 **K.O.!** @{escape_name(target.username or target.first_name)} was jumped! **-2,500 Cal** shed.\n"
                f"🛡️ Recovery active (6 Hours).\n"
            )
        else:
            cur.execute("""
                UPDATE pf_users
                SET smack_count = %s,
                    last_smack_time = %s,
                    smack_ids = %s
                WHERE user_id = %s
            """, (s_count, now, new_s_ids, target.id))
            bar = "🟥" * s_count + "⬜" * (5 - s_count)
            msg = (
                f"🥊 **SMACKED!** @{escape_name(target.username or target.first_name)}\n"
                f"{bar} ({s_count}/5)\n"
                f"@{escape_name(attacker.username or attacker.first_name)} spent 200 Cal.\n"
                f"🌡️ Heat +{smack_heat_gain}\n"
            )

        if rampage_active_until(current_rampage_until, now):
            mins_left = max(1, int((current_rampage_until - now).total_seconds() // 60))
            msg += f"🔥 **CHEF RAMPAGE LIVE:** {mins_left}m left.\n"

        msg += f"🎤 *{random_charlie_quote()}*"
        await update.message.reply_text(msg, parse_mode='Markdown')

        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Smack Error: {e}")
        await update.message.reply_text("⚠️ Smack system jammed.")
    finally:
        safe_close(cur, conn)

# ==========================================
# 7. GIFTING
# ==========================================
async def gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender, now = update.effective_user, datetime.utcnow()
    receiver = None

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        ensure_user_record(cur, sender)

        # 1) Direct gifting via /gift @username
        if context.args:
            target_username = context.args[0].strip().lstrip("@")
            cur.execute("""
                SELECT user_id, username
                FROM pf_users
                WHERE LOWER(username) = LOWER(%s) OR LOWER(username) = LOWER(%s)
                LIMIT 1
            """, (target_username, f"@{target_username}"))
            row = cur.fetchone()

            if not row:
                return await update.message.reply_text(
                    f"❌ @{target_username} not found in the lab database."
                )

            receiver = type('GiftTarget', (object,), {
                'id': row[0],
                'username': row[1] or target_username,
                'first_name': row[1] or target_username
            })

        # 2) Fallback to reply gifting
        elif update.message.reply_to_message:
            receiver = update.message.reply_to_message.from_user
            ensure_user_record(cur, receiver)

        # 3) Neither provided
        else:
            return await update.message.reply_text(
                "💡 Use `/gift @username` or reply to a message with `/gift`.",
                parse_mode='Markdown'
            )

        if receiver.id == sender.id:
            return await update.message.reply_text("🚫 Self-gifting is prohibited.")

        is_golden_hour = now.hour == 0
        cooldown_minutes = 20 if is_founder(sender) else 60

        cur.execute("SELECT last_gift_sent FROM pf_users WHERE user_id = %s", (sender.id,))
        res = cur.fetchone()
        if res and res[0] and now - res[0] < timedelta(minutes=cooldown_minutes):
            rem = timedelta(minutes=cooldown_minutes) - (now - res[0])
            return await update.message.reply_text(f"⏳ **COOLDOWN:** {int(rem.total_seconds()//60)}m remaining.")

        if receiver.id == context.bot.id:
            cur.execute("UPDATE pf_users SET last_gift_sent = %s WHERE user_id = %s", (now, sender.id))
            outcome = random.choices([1, 2, 3], weights=[30, 40, 30], k=1)[0]

            if outcome == 1:
                penalty = 1500
                cur.execute("""
                    UPDATE pf_users
                    SET daily_calories = GREATEST(0, daily_calories - %s),
                        total_calories = GREATEST(0, total_calories - %s)
                    WHERE user_id = %s
                """, (penalty, penalty, sender.id))
                conn.commit()
                return await update.message.reply_text(f"💀 **REFLECTED!** Toxin bounced back. **-{penalty:,} Cal**.")
            elif outcome == 2:
                conn.commit()
                return await update.message.reply_text("😋 **OM NOM NOM...** The Chef devours it.")
            else:
                item = random.choice(foods)
                cur.execute("""
                    UPDATE pf_users
                    SET total_calories = total_calories + %s
                    WHERE user_id = 0
                    RETURNING total_calories
                """, (item.get('calories', 500),))
                cur_val = cur.fetchone()[0]

                if cur_val >= METER_GOAL:
                    jackpot = random.randint(10000, 20000)
                    cur.execute("UPDATE pf_users SET total_calories = 0 WHERE user_id = 0")
                    cur.execute("""
                        UPDATE pf_users
                        SET daily_calories = daily_calories + %s,
                            total_calories = total_calories + %s
                        WHERE user_id = %s
                    """, (jackpot, jackpot, sender.id))
                    conn.commit()
                    return await update.message.reply_text(
                        f"💥 **KITCHEN OVERLOAD!** 🏆 @{escape_name(sender.username or sender.first_name)}: **+{jackpot:,} Cal**",
                        parse_mode='Markdown'
                    )

                conn.commit()
                return await update.message.reply_text(f"✅ **CHEF FED.**\n{get_progress_bar(cur_val)}")

        ensure_user_id_record(cur, receiver.id, receiver.username or receiver.first_name or "Unknown")

        cur.execute("SELECT id FROM pf_gifts WHERE receiver_id = %s AND is_opened = FALSE", (receiver.id,))
        if cur.fetchone():
            return await update.message.reply_text("📦 **DOCK BLOCKED:** Shipment pending. Cooldown saved.")

        cur.execute("UPDATE pf_users SET last_gift_sent = %s WHERE user_id = %s", (now, sender.id))

        gh_tag = ""
        if is_golden_hour:
            gh_tag = "🌟 **GOLDEN HOUR:** 100% Protein Active!\n"
            item = random.choice(foods)
            val = abs(item.get('calories', 500))
            i_type = "PROTEIN"
            msg = "Golden Hour Nutrition!"
        else:
            is_p = random.choice([True, False])

            if is_p:
                curse = roll_punishment()

                if curse:
                    item = {"name": curse["name"]}
                    val = curse["value"]
                    i_type = "CURSED"
                    msg = curse["text"]
                else:
                    item = random.choice(hacks) if hacks else {"name": "Experimental Sludge", "blueprint": "Something went wrong."}
                    val = random.randint(-2500, -800)
                    i_type = "POISON"
                    msg = f"Toxin Level: {item.get('blueprint', 'Experimental Sludge.')}"
            else:
                item = random.choice(foods)
                val = item.get('calories', 500)
                i_type = "PROTEIN"
                msg = "Incoming Delivery!"

        cur.execute("""
            INSERT INTO pf_gifts (sender_id, sender_name, receiver_id, item_name, item_type, value, flavor_text)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            sender.id,
            sender.first_name,
            receiver.id,
            item['name'],
            i_type,
            val,
            msg
        ))

        conn.commit()
        await update.message.reply_text(
            f"{gh_tag}📦 MYSTERY SHIPMENT DROPPED!\n"
            f"@{receiver.username or receiver.first_name}, choose your fate:\n"
            f"/open\n"
            f"/trash",
            parse_mode='Markdown'
        )

    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Gift Error: {e}")
        await update.message.reply_text("⚠️ Kitchen glitch.")
    finally:
        safe_close(cur, conn)

async def open_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        ensure_user_record(cur, user)

        cur.execute("""
            SELECT id, sender_name, item_name, item_type, value, sender_id
            FROM pf_gifts
            WHERE receiver_id = %s AND is_opened = FALSE
            ORDER BY id DESC
            LIMIT 1
        """, (user_id,))
        row = cur.fetchone()

        if not row:
            return await update.message.reply_text("📦 Your dock is empty.")

        g_id, s_name, i_name, i_type, val, s_id = row

        cur.execute("UPDATE pf_gifts SET is_opened = TRUE WHERE id = %s", (g_id,))
        cur.execute("""
            UPDATE pf_users
            SET daily_calories = daily_calories + %s,
                total_calories = GREATEST(0, total_calories + %s)
            WHERE user_id = %s
        """, (val, val, user_id))

        ensure_user_id_record(cur, s_id, s_name or "Unknown")
        col = "gifts_sent_val" if i_type == "PROTEIN" else "sabotage_val"
        cur.execute(f"UPDATE pf_users SET {col} = {col} + %s WHERE user_id = %s", (abs(val), s_id))

        conn.commit()

        sign = "+" if val > 0 else ""
        if i_type == "PROTEIN":
            header = "💉 **FUEL INJECTED!**"
        elif i_type == "CURSED":
            header = "🧪 **CURSED DELIVERY!**"
        else:
            header = "💀 **TOXIN DETECTED!**"

        await update.message.reply_text(
            f"{header}\nFrom **{escape_name(s_name)}**: {i_name}\n📊 Impact: {sign}{val:,} Cal",
            parse_mode='Markdown'
        )

    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Open Gift Error: {e}")
        await update.message.reply_text(f"⚠️ Error: {e}")
    finally:
        safe_close(cur, conn)

async def trash_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        ensure_user_record(cur, user)

        cur.execute("UPDATE pf_gifts SET is_opened = TRUE WHERE receiver_id = %s AND is_opened = FALSE", (user_id,))
        cur.execute("""
            UPDATE pf_users
            SET daily_calories = GREATEST(0, daily_calories - 100)
            WHERE user_id = %s
        """, (user_id,))
        conn.commit()
        await update.message.reply_text("🚮 **SCRAPPED:** Paid 100 Cal fee.")
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Trash Gift Error: {e}")
        await update.message.reply_text("⚠️ Trash chute jammed.")
    finally:
        safe_close(cur, conn)

# ==========================================
# 8. STATS & LEADERBOARDS
# ==========================================
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            SELECT total_calories, daily_calories, CAST(daily_clog AS FLOAT), is_icu, icu_lifetime,
                   daily_ko_count, last_ko_time, lifetime_daily_wins, lifetime_hack_wins, heat_level
            FROM pf_users
            WHERE user_id = %s
        """, (user.id,))
        u = cur.fetchone()

        cur.execute("SELECT total_calories, daily_calories, rampage_until FROM pf_users WHERE user_id = 0")
        kitchen_row = cur.fetchone()
        meter_val = kitchen_row[0] if kitchen_row else 0
        rage_val = kitchen_row[1] if kitchen_row else 0
        rampage_until_val = kitchen_row[2] if kitchen_row else None

        if not u:
            return await update.message.reply_text("❌ No records.")

        now = datetime.utcnow()
        p_status = "🟢 VULNERABLE"
        if u[5] >= 2:
            p_status = "🛡️ MAXED (Daily Limit)"
        elif u[6] and now - u[6] < timedelta(hours=6):
            rem = timedelta(hours=6) - (now - u[6])
            p_status = f"🛡️ RECOVERING ({int(rem.total_seconds()//60)}m)"

        phat_title = get_win_title(u[7], False)
        hack_title = get_win_title(u[8], True)
        titles = []
        if phat_title:
            titles.append(f"🏆 {phat_title} ({u[7]} Wins)")
        if hack_title:
            titles.append(f"🧪 {hack_title} ({u[8]} Wins)")
        title_display = "\n".join(titles) if titles else "🎖️ *No Trophies Yet*"

        rampage_text = ""
        if rampage_active_until(rampage_until_val, now):
            mins_left = max(1, int((rampage_until_val - now).total_seconds() // 60))
            rampage_text = f"\n🔥 **CHEF RAMPAGE:** LIVE ({mins_left}m left)"
        elif rage_val >= 100:
            rampage_text = "\n🔥 **CHEF RAMPAGE:** ARMED"

        msg = (
            f"📋 *VITALS: @{escape_name(user.first_name)}*\n━━━━━━━━━━━━━━\n"
            f"🧬 Status: {'🚨 ICU' if u[3] else '🟢 STABLE'}\n"
            f"💀 ICU Visits: {u[4]} ({get_icu_rank(u[4])})\n"
            f"🔥 Daily: {u[1]:,} Cal\n"
            f"📈 Total: {u[0]:,} Cal\n"
            f"🩸 Clog: {u[2]:.1f}%\n"
            f"🌡️ Heat: {u[9]}\n"
            f"🥊 Smack Status: {p_status}\n\n"
            f"🏆 **CHAMPIONSHIPS:**\n{title_display}\n━━━━━━━━━━━━━━\n"
            f"👨‍🍳 **KITCHEN SATIETY:**\n{get_progress_bar(meter_val)}\n"
            f"🔥 **CHEF RAGE:** {rage_val}/100{rampage_text}"
        )
        await update.message.reply_text(msg, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Status Error: {e}")
        await update.message.reply_text("⚠️ Vitals monitor offline.")
    finally:
        safe_close(cur, conn)

async def halloffame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT username, lifetime_daily_wins
            FROM pf_users
            WHERE lifetime_daily_wins > 0
              AND user_id != 0
              AND COALESCE(leaderboard_enabled, TRUE) = TRUE
            ORDER BY lifetime_daily_wins DESC
            LIMIT 10
        """)
        phat_winners = cur.fetchall()

        cur.execute("""
            SELECT username, lifetime_hack_wins
            FROM pf_users
            WHERE lifetime_hack_wins > 0
              AND user_id != 0
              AND COALESCE(leaderboard_enabled, TRUE) = TRUE
            ORDER BY lifetime_hack_wins DESC
            LIMIT 10
        """)
        hack_winners = cur.fetchall()

        text = "🏆 **THE HALL OF ETERNAL GIRTH** 🏆\n━━━━━━━━━━━━━━\n"
        text += "🍔 **HEAVYWEIGHT CHAMPS**\n"
        if not phat_winners:
            text += "No champions yet.\n"
        for i, r in enumerate(phat_winners):
            text += f"{i+1}. {escape_name(r[0])}: {r[1]} Wins\n"

        text += "\n🧪 **MASTER ARCHITECTS**\n"
        if not hack_winners:
            text += "No champions yet.\n"
        for i, r in enumerate(hack_winners):
            text += f"{i+1}. {escape_name(r[0])}: {r[1]} Wins\n"
        text += "━━━━━━━━━━━━━━"
        await update.message.reply_text(text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Hall of Fame Error: {e}")
        await update.message.reply_text("⚠️ Hall of Fame offline.")
    finally:
        safe_close(cur, conn)

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT username, daily_calories
            FROM pf_users
            WHERE user_id != 0
              AND daily_calories != 0
              AND COALESCE(leaderboard_enabled, TRUE) = TRUE
            ORDER BY daily_calories DESC
            LIMIT 20
        """)
        rows = cur.fetchall()
        if not rows:
            return await update.message.reply_text("🍔 **NO MUNCHERS YET.**")
        text = "🔥 **DAILY FEEDING FRENZY (TOP 20)** 🔥\n━━━━━━━━━━━━━━\n" + "\n".join(
            [f"{i+1}. {escape_name(r[0])}: {r[1]:,} Cal" for i, r in enumerate(rows)]
        )
        await update.message.reply_text(text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Daily Error: {e}")
        await update.message.reply_text("⚠️ Daily board offline.")
    finally:
        safe_close(cur, conn)

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT username, total_calories
            FROM pf_users
            WHERE user_id != 0
              AND COALESCE(leaderboard_enabled, TRUE) = TRUE
            ORDER BY total_calories DESC
            LIMIT 20
        """)
        rows = cur.fetchall()
        text = "🏆 **THE HALL OF INFINITE GIRTH (TOP 20)** 🏆\n━━━━━━━━━━━━━━\n" + "\n".join(
            [f"{i+1}. {escape_name(r[0])}: {r[1]:,} Cal" for i, r in enumerate(rows)]
        )
        await update.message.reply_text(text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Leaderboard Error: {e}")
        await update.message.reply_text("⚠️ Leaderboard offline.")
    finally:
        safe_close(cur, conn)

async def clogboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT username, CAST(daily_clog AS FLOAT)
            FROM pf_users
            WHERE user_id != 0
              AND daily_clog > 0
              AND COALESCE(leaderboard_enabled, TRUE) = TRUE
            ORDER BY daily_clog DESC
            LIMIT 20
        """)
        rows = cur.fetchall()
        if not rows:
            return await update.message.reply_text("🧪 **THE LAB IS CLEAN.**")
        text = "🧪 **LIVE LAB RESULTS (CURRENT CLOG %)** 🧪\n━━━━━━━━━━━━━━\n" + "\n".join(
            [f"{i+1}. {escape_name(r[0])}: {r[1]:.1f}%" for i, r in enumerate(rows)]
        )
        await update.message.reply_text(text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Clogboard Error: {e}")
        await update.message.reply_text("⚠️ Clogboard offline.")
    finally:
        safe_close(cur, conn)

async def deaths(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT username, icu_lifetime
            FROM pf_users
            WHERE user_id != 0
              AND icu_lifetime > 0
              AND COALESCE(leaderboard_enabled, TRUE) = TRUE
            ORDER BY icu_lifetime DESC
            LIMIT 20
        """)
        rows = cur.fetchall()
        if not rows:
            return await update.message.reply_text("💀 **NO DEATHS LOGGED.**")
        text = "💀 **CARDIAC IMMORTALS (LIFETIME DEATHS)** 💀\n━━━━━━━━━━━━━━\n" + "\n".join(
            [f"{i+1}. {escape_name(r[0])}: {r[1]} ICU Trips" for i, r in enumerate(rows)]
        )
        await update.message.reply_text(text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Deaths Error: {e}")
        await update.message.reply_text("⚠️ Death ledger offline.")
    finally:
        safe_close(cur, conn)

# ==========================================
# 9. PHAT PFP GENERATOR
# ==========================================
async def phatme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not phat_processor:
        return await update.message.reply_text("❌ Laboratory offline. (phat_engine.py missing)")

    user, now = update.effective_user, datetime.utcnow()
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        ensure_user_record(cur, user)

        cur.execute("SELECT last_pfp_gen FROM pf_users WHERE user_id = %s", (user.id,))
        res = cur.fetchone()
        if res and res[0] and now - res[0] < timedelta(hours=24):
            rem = timedelta(hours=24) - (now - res[0])
            return await update.message.reply_text(f"⌛️ **LAB RECHARGING:** Try again in {int(rem.total_seconds()//3600)}h.")

        photos = await context.bot.get_user_profile_photos(user.id)
        if not photos.photos:
            return await update.message.reply_text("❌ No profile picture.")

        status_msg = await update.message.reply_text("🧪 Synthesizing DNA...")
        file_id = photos.photos[0][-1].file_id
        file = await context.bot.get_file(file_id)
        photo_bytes = await file.download_as_bytearray()

        task = asyncio.create_task(asyncio.to_thread(phat_processor.generate_phat_image, photo_bytes))
        result_img_bytes = await task

        if result_img_bytes:
            cur.execute("UPDATE pf_users SET last_pfp_gen = %s WHERE user_id = %s", (now, user.id))
            conn.commit()
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=result_img_bytes,
                caption=f"🏆 **TRANSFORMATION COMPLETE** @{escape_name(user.username or user.first_name)}!",
                parse_mode='Markdown'
            )
            await status_msg.delete()
        else:
            await status_msg.edit_text("⚠️ Synthesis failed.")
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"PhatMe Error: {e}")
        await update.message.reply_text("❌ Kitchen Connection Lost.")
    finally:
        safe_close(cur, conn)

# ==========================================
# 10. ADMIN & SYSTEM
# ==========================================
async def reward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, user.id)
        if member.status not in ['administrator', 'creator']:
            return await update.message.reply_text("🚫 **UNAUTHORIZED.**")
    except Exception as e:
        logger.error(f"Reward Member Check Error: {e}")
        return await update.message.reply_text("⚠️ Admin check failed.")

    target_user = update.message.reply_to_message.from_user if update.message.reply_to_message else None
    if not target_user:
        return await update.message.reply_text("💡 Reply to someone.")

    roll = random.random()
    if roll < 0.70:
        bonus = random.randint(100, 500)
        tier = "📦 STANDARD"
    elif roll < 0.90:
        bonus = random.randint(501, 1500)
        tier = "🎁 PREMIUM"
    else:
        bonus = random.randint(1501, 5000)
        tier = "💰 CRITICAL HIT"

    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        ensure_user_record(cur, target_user)
        cur.execute("""
            UPDATE pf_users
            SET daily_calories = daily_calories + %s,
                total_calories = total_calories + %s
            WHERE user_id = %s
        """, (bonus, bonus, target_user.id))
        conn.commit()
        await update.message.reply_text(
            f"🎯 **RAID REWARD: {tier}**\n"
            f"+{bonus:,} Cal to @{escape_name(target_user.username or target_user.first_name)}",
            parse_mode='Markdown'
        )
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"Reward Error: {e}")
        await update.message.reply_text("⚠️ Reward dispenser jammed.")
    finally:
        safe_close(cur, conn)

async def winners(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT winner_type, username, CAST(score AS FLOAT), win_date
            FROM pf_airdrop_winners
            ORDER BY win_date DESC
            LIMIT 15
        """)
        rows = cur.fetchall()
        if not rows:
            return await update.message.reply_text("📜 Hall of Fame is empty.")

        text = "🏆 **THE AIRDROP LEGENDS** 🏆\n━━━━━━━━━━━━━━\n"
        for r in rows:
            icon = "🍔" if r[0] == 'DAILY PHATTEST' else "🧪"
            score_val = f"{r[2]:.1f}%" if r[0] == 'TOP HACKER' else f"{int(r[2]):,}"
            text += f"{icon} `{r[3].strftime('%m/%d')}` | **{r[0]}**: {escape_name(r[1])} ({score_val})\n"
        await update.message.reply_text(text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Winners Error: {e}")
        await update.message.reply_text("⚠️ Winners archive offline.")
    finally:
        safe_close(cur, conn)

async def set_bot_commands(application):
    cmds = [
        ("snack", "Eat"),
        ("hack", "Lab"),
        ("smack", "Raid [Reply/Tag]"),
        ("gift", "Shipment [Reply/Tag]"),
        ("open", "Unbox"),
        ("trash", "Dump"),
        ("status", "Vitals"),
        ("daily", "Rank"),
        ("leaderboard", "Girth"),
        ("clogboard", "Live Clog %"),
        ("deaths", "ICU Deaths"),
        ("phatme", "Phat PFP Generator"),
        ("halloffame", "Eternal Champions")
    ]
    await application.bot.set_my_commands(cmds)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

if __name__ == "__main__":
    try:
        b_id = int(TOKEN.split(':')[0])
    except Exception:
        b_id = None

    init_db(b_id)
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_error_handler(error_handler)

    handlers = [
        ("snack", snack),
        ("hack", hack),
        ("smack", smack),
        ("gift", gift),
        ("open", open_gift),
        ("trash", trash_gift),
        ("reward", reward),
        ("status", status),
        ("daily", daily),
        ("leaderboard", leaderboard),
        ("clogboard", clogboard),
        ("deaths", deaths),
        ("winners", winners),
        ("phatme", phatme),
        ("halloffame", halloffame)
    ]
    for c, f in handlers:
        app.add_handler(CommandHandler(c, f))

    async def post_init(application):
        await set_bot_commands(application)
        application.create_task(automated_reset_task(application))
        application.create_task(check_pings(application))
        application.create_task(chef_rampage_task(application))
        logger.info("🚀 Planet Fatness Online.")

    app.post_init = post_init
    app.run_polling(drop_pending_updates=True)