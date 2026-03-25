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

# ==========================================
# 2. DATA LOADING & HELPERS
# ==========================================
foods, hacks = [], []
try:
    with open("foods.json", "r") as f:
        foods = json.load(f)
    with open("hacks.json", "r") as f:
        hacks = json.load(f)
except Exception as e: 
    logger.error(f"❌ JSON Load Failed: {e}")

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
    if visits == 0: return "Fresh Meat"
    if visits < 5: return "Lab Rat"
    if visits < 15: return "Code Blue Veteran"
    if visits < 30: return "Defibrillator Junkie"
    if visits < 50: return "Cardiac Immortal"
    return "Ghost of Planet Fatness"

# ==========================================
# 3. DATABASE INITIALIZATION & MIGRATIONS
# ==========================================
def init_db(bot_id=None):
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Core User Table
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
            last_ko_time TIMESTAMP
        );
    """)
    
    # Feature Migrations
    migrations = [
        ("last_pfp_gen", "TIMESTAMP"),
        ("icu_lifetime", "INTEGER DEFAULT 0"),
        ("smack_count", "INTEGER DEFAULT 0"),
        ("last_smack_time", "TIMESTAMP"),
        ("smack_ids", "TEXT DEFAULT ''"),
        ("daily_ko_count", "INTEGER DEFAULT 0"),
        ("last_ko_time", "TIMESTAMP")
    ]
    for col_name, col_type in migrations:
        try:
            cur.execute(f"ALTER TABLE pf_users ADD COLUMN IF NOT EXISTS {col_name} {col_type};")
        except Exception: 
            conn.rollback()

    # System Account
    cur.execute("INSERT INTO pf_users (user_id, username, total_calories) VALUES (0, 'KITCHEN_SYSTEM', 0) ON CONFLICT DO NOTHING")
    
    # Airdrop Logs
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pf_airdrop_winners (
            id SERIAL PRIMARY KEY,
            winner_type TEXT,
            username TEXT, 
            score NUMERIC,
            win_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    # Gift Queue
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
    cur.close()
    conn.close()

# ==========================================
# 4. AUTOMATED TASKS
# ==========================================
async def automated_reset_task(application):
    while True:
        now_utc = datetime.utcnow()
        # Reset at 01:00 UTC (9 PM EST)
        if now_utc.hour == 1 and now_utc.minute == 0:
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                
                # Log Winners
                for label, col in [('DAILY PHATTEST', 'daily_calories'), ('TOP HACKER', 'daily_clog')]:
                    cur.execute(f"SELECT username, {col} FROM pf_users WHERE {col} > 0 ORDER BY {col} DESC LIMIT 1")
                    winner = cur.fetchone()
                    if winner:
                        cur.execute("INSERT INTO pf_airdrop_winners (winner_type, username, score) VALUES (%s, %s, %s)", (label, winner[0], winner[1]))
                
                # Cleanup and Reset
                cur.execute("DELETE FROM pf_airdrop_winners WHERE win_date < NOW() - INTERVAL '7 days'")
                cur.execute("UPDATE pf_users SET daily_calories = 0, daily_clog = 0, is_icu = FALSE, daily_ko_count = 0")
                
                conn.commit()
                cur.close()
                conn.close()
                logger.info("🧹 Daily Reset Complete.")
            except Exception as e: 
                logger.error(f"Reset Error: {e}")
            await asyncio.sleep(61)
        await asyncio.sleep(30)

async def check_pings(application):
    while True:
        await asyncio.sleep(60)
        pass

# ==========================================
# 5. CORE ACTIONS (SNACK & HACK)
# ==========================================
async def snack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, now = update.effective_user, datetime.utcnow()
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT total_calories, daily_calories, last_snack FROM pf_users WHERE user_id = %s", (user.id,))
        u = cur.fetchone()
        
        if u and u[2] and now - u[2] < timedelta(hours=1):
            rem = timedelta(hours=1) - (now - u[2])
            cur.close()
            conn.close()
            return await update.message.reply_text(f"⌛️ Digesting... {int(rem.total_seconds()//60)}m left.")
        
        item = random.choice(foods)
        cal_val = item['calories']
        gif_url = item.get('gif') 
        
        c_total, c_daily = (u[0] or 0, u[1] or 0) if u else (0, 0)
        new_daily = c_daily + cal_val
        new_total = max(0, c_total + cal_val)
        
        cur.execute("""
            INSERT INTO pf_users (user_id, username, total_calories, daily_calories, last_snack)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
            username=EXCLUDED.username, total_calories=%s, 
            daily_calories=%s, last_snack=%s
        """, (user.id, user.username or user.first_name, new_total, new_daily, now, new_total, new_daily, now))
        
        conn.commit()
        cur.close()
        conn.close()
        
        sign = "+" if cal_val > 0 else ""
        caption = f"🍔 **{item['name']}** ({sign}{cal_val:,} Cal)\n🔥 Daily: {new_daily:,}"
        
        if gif_url: 
            await update.message.reply_animation(animation=gif_url, caption=caption, parse_mode='Markdown')
        else: 
            await update.message.reply_text(caption, parse_mode='Markdown')
            
    except Exception as e:
        if conn: conn.rollback(); conn.close()
        logger.error(f"Snack Error: {e}")
        await update.message.reply_text("❌ Kitchen Busy.")

async def hack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id, now = update.effective_user.id, datetime.utcnow()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
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
            cur.execute("UPDATE pf_users SET daily_clog=0, is_icu=True, last_hack=%s, icu_lifetime = icu_lifetime + 1 WHERE user_id=%s", (now, user_id))
            await update.message.reply_text(f"💀 **FLATLINE!** Lab failure. ICU for 2 hours.\n📈 Lifetime Visits Logged.")
        else:
            cur.execute("UPDATE pf_users SET daily_clog=%s, is_icu=False, last_hack=%s WHERE user_id=%s", (new_c, now, user_id))
            await update.message.reply_text(
                f"🩺 **HACK SUCCESS:** {h.get('name')}\n"
                f"📋 **Order:** {h.get('blueprint', 'Classified information.')}\n"
                f"{bonus_text}📈 Clog: {new_c:.1f} % (+{gain}%)",
                parse_mode='Markdown'
            )
        conn.commit()
    finally: 
        cur.close()
        conn.close()

# ==========================================
# 6. SMACKDOWN PROTOCOL
# ==========================================
async def smack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    attacker, now = update.effective_user, datetime.utcnow()
    target = None

    # --- NEW: LOGIC TO ALLOW SMACKING VIA TAGGING ---
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
    elif context.args:
        # Check if first argument is a mention
        target_username = context.args[0].strip('@')
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id, username FROM pf_users WHERE username = %s OR username = %s", (target_username, f"@{target_username}"))
        res = cur.fetchone()
        cur.close()
        conn.close()
        
        if res:
            # Create a mock user object to maintain compatibility with existing logic
            target = type('User', (object,), {
                'id': res[0], 
                'username': target_username, 
                'first_name': target_username
            })
        else:
            return await update.message.reply_text(f"❌ Target @{target_username} not found in the lab database.")
    
    if not target:
        return await update.message.reply_text("🥊 **HOW TO SMACK:**\n1. Reply to a message with `/smack`\n2. Type `/smack @username`")
    # ------------------------------------------------

    if target.id == attacker.id:
        return await update.message.reply_text("🚫 You cannot smack yourself.")
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT daily_calories FROM pf_users WHERE user_id = %s", (attacker.id,))
        a_res = cur.fetchone()
        if not a_res or a_res[0] < 200:
            return await update.message.reply_text("🦴 You are too weak. Smacking costs 200 Cal.")

        cur.execute("SELECT smack_count, last_smack_time, smack_ids, daily_ko_count, last_ko_time FROM pf_users WHERE user_id = %s", (target.id,))
        t_data = cur.fetchone()
        s_count, l_smack, s_ids, ko_count, l_ko = t_data if t_data else (0, None, "", 0, None)

        # --- FIX: CLEAR EXPIRED WINDOW FIRST ---
        if l_smack and now - l_smack > timedelta(minutes=15):
            s_count, s_ids = 0, ""
        # ----------------------------------------

        if l_ko and now - l_ko < timedelta(hours=6):
            rem = timedelta(hours=6) - (now - l_ko)
            return await update.message.reply_text(f"🛡️ Target is in recovery. Immune for {int(rem.total_seconds()//60)}m.")
        
        if ko_count >= 2:
            return await update.message.reply_text("🛡️ Target has reached the daily limit of knockouts.")

        s_list = s_ids.split(",") if s_ids else []
        if str(attacker.id) in s_list:
            return await update.message.reply_text("🚫 You already smacked this user in this window!")

        s_count += 1
        s_list.append(str(attacker.id))
        new_s_ids = ",".join(s_list)
        
        cur.execute("UPDATE pf_users SET daily_calories = daily_calories - 200, total_calories = total_calories - 200 WHERE user_id = %s", (attacker.id,))
        
        if s_count >= 5:
            cur.execute("""
                UPDATE pf_users SET 
                daily_calories = daily_calories - 2500, total_calories = GREATEST(0, total_calories - 2500),
                smack_count = 0, smack_ids = '', daily_ko_count = daily_ko_count + 1, last_ko_time = %s 
                WHERE user_id = %s
            """, (now, target.id))
            await update.message.reply_text(f"💥 **K.O.!** @{escape_name(target.username or target.first_name)} was jumped! **-2,500 Cal** shed.\n🛡️ Recovery active (6 Hours).")
        else:
            cur.execute("UPDATE pf_users SET smack_count = %s, last_smack_time = %s, smack_ids = %s WHERE user_id = %s", (s_count, now, new_s_ids, target.id))
            bar = "🟥" * s_count + "⬜" * (5 - s_count)
            await update.message.reply_text(
                f"🥊 **SMACKED!** @{escape_name(target.username or target.first_name)}\n"
                f"{bar} ({s_count}/5)\n"
                f"@{escape_name(attacker.username)} spent 200 Cal. 15m left for unique hits!"
            )
        conn.commit()
    except Exception as e:
        logger.error(f"Smack Error: {e}")
        await update.message.reply_text("⚠️ Smack system jammed.")
    finally: 
        cur.close()
        conn.close()

# ==========================================
# 7. GIFTING 
# ==========================================
async def gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender, now = update.effective_user, datetime.utcnow()
    
    if not update.message.reply_to_message:
        return await update.message.reply_text("💡 You must **REPLY** to a message with /gift!")
    
    receiver = update.message.reply_to_message.from_user
    if receiver.id == sender.id:
        return await update.message.reply_text("🚫 Self-gifting is prohibited.")
    
    is_golden_hour = now.hour == 0 
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("SELECT last_gift_sent FROM pf_users WHERE user_id = %s", (sender.id,))
        res = cur.fetchone()
        if res and res[0] and now - res[0] < timedelta(hours=1):
            rem = timedelta(hours=1) - (now - res[0])
            return await update.message.reply_text(f"⏳ **COOLDOWN:** {int(rem.total_seconds()//60)}m remaining.")

        if receiver.id == context.bot.id:
            cur.execute("UPDATE pf_users SET last_gift_sent = %s WHERE user_id = %s", (now, sender.id))
            outcome = random.choices([1, 2, 3], weights=[30, 40, 30], k=1)[0]
            if outcome == 1:
                penalty = 1500
                cur.execute("UPDATE pf_users SET daily_calories = daily_calories - %s, total_calories = GREATEST(0, total_calories - %s) WHERE user_id = %s", (penalty, penalty, sender.id))
                conn.commit()
                return await update.message.reply_text(f"💀 **REFLECTED!** Toxin bounced back. **-{penalty:,} Cal**.")
            elif outcome == 2:
                conn.commit()
                return await update.message.reply_text(f"😋 **OM NOM NOM...** The Chef devours it.")
            else:
                item = random.choice(foods)
                cur.execute("UPDATE pf_users SET total_calories = total_calories + %s WHERE user_id = 0 RETURNING total_calories", (item.get('calories', 500),))
                cur_val = cur.fetchone()[0]
                if cur_val >= METER_GOAL:
                    jackpot = random.randint(10000, 20000)
                    cur.execute("UPDATE pf_users SET total_calories = 0 WHERE user_id = 0")
                    cur.execute("UPDATE pf_users SET daily_calories = daily_calories + %s, total_calories = total_calories + %s WHERE user_id = %s", (jackpot, jackpot, sender.id))
                    conn.commit()
                    return await update.message.reply_text(f"💥 **KITCHEN OVERLOAD!** 🏆 @{escape_name(sender.username)}: **+{jackpot:,} Cal**")
                conn.commit()
                return await update.message.reply_text(f"✅ **CHEF FED.**\n{get_progress_bar(cur_val)}")

        cur.execute("SELECT id FROM pf_gifts WHERE receiver_id = %s AND is_opened = FALSE", (receiver.id,))
        if cur.fetchone():
            return await update.message.reply_text(f"📦 **DOCK BLOCKED:** Shipment pending. Cooldown saved.")

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
                item = random.choice(hacks)
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
        """, (sender.id, sender.first_name, receiver.id, item['name'], i_type, val, msg))
        
        conn.commit()
        await update.message.reply_text(f"{gh_tag}📦 **MYSTERY SHIPMENT DROPPED!**\n@{escape_name(receiver.username or receiver.first_name)}, will you `/open` or `/trash` it?")
        
    except Exception as e:
        logger.error(f"Gift Error: {e}")
        await update.message.reply_text("⚠️ Kitchen glitch.")
    finally: 
        cur.close()
        conn.close()

async def open_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, sender_name, item_name, item_type, value, sender_id FROM pf_gifts WHERE receiver_id = %s AND is_opened = FALSE ORDER BY id DESC LIMIT 1", (user_id,))
        row = cur.fetchone()
        
        if not row:
            return await update.message.reply_text("📦 Your dock is empty.")
            
        g_id, s_name, i_name, i_type, val, s_id = row
        
        cur.execute("UPDATE pf_gifts SET is_opened = TRUE WHERE id = %s", (g_id,))
        cur.execute("UPDATE pf_users SET daily_calories = daily_calories + %s, total_calories = GREATEST(0, total_calories + %s) WHERE user_id = %s", (val, val, user_id))
        
        col = "gifts_sent_val" if i_type == "PROTEIN" else "sabotage_val"
        cur.execute(f"UPDATE pf_users SET {col} = {col} + %s WHERE user_id = %s", (abs(val), s_id))
        
        conn.commit()
        cur.close()
        conn.close()
        
        sign = "+" if val > 0 else ""
        header = "💉 **FUEL INJECTED!**" if i_type == "PROTEIN" else "💀 **TOXIN DETECTED!**"
        await update.message.reply_text(f"{header}\nFrom **{escape_name(s_name)}**: {i_name}\n📊 Impact: {sign}{val:,} Cal")
        
    except Exception as e:
        if conn: conn.rollback(); conn.close()
        await update.message.reply_text(f"⚠️ Error: {e}")

async def trash_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE pf_gifts SET is_opened = TRUE WHERE receiver_id = %s AND is_opened = FALSE", (user_id,))
    cur.execute("UPDATE pf_users SET daily_calories = daily_calories - 100 WHERE user_id = %s", (user_id,))
    conn.commit()
    cur.close()
    conn.close()
    await update.message.reply_text("🚮 **SCRAPPED:** Paid 100 Cal fee.")

# ==========================================
# 8. STATS & LEADERBOARDS
# ==========================================
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT total_calories, daily_calories, CAST(daily_clog AS FLOAT), is_icu, icu_lifetime, daily_ko_count, last_ko_time FROM pf_users WHERE user_id = %s", (user.id,))
    u = cur.fetchone()
    cur.execute("SELECT total_calories FROM pf_users WHERE user_id = 0")
    meter_val = cur.fetchone()[0]
    cur.close()
    conn.close()
    
    if not u:
        return await update.message.reply_text("❌ No records.")
    
    now = datetime.utcnow()
    p_status = "🟢 VULNERABLE"
    if u[5] >= 2:
        p_status = "🛡️ MAXED (Daily Limit)"
    elif u[6] and now - u[6] < timedelta(hours=6):
        rem = (timedelta(hours=6) - (now - u[6]))
        p_status = f"🛡️ RECOVERING ({int(rem.total_seconds()//60)}m)"
        
    msg = (f"📋 *VITALS: @{escape_name(user.first_name)}*\n━━━━━━━━━━━━━━\n"
           f"🧬 Status: {'🚨 ICU' if u[3] else '🟢 STABLE'}\n"
           f"💀 ICU Visits: {u[4]} ({get_icu_rank(u[4])})\n"
           f"🔥 Daily: {u[1]:,} Cal\n"
           f"📈 Total: {u[0]:,} Cal\n"
           f"🩸 Clog: {u[2]:.1f}%\n"
           f"🥊 Smack Status: {p_status}\n━━━━━━━━━━━━━━\n"
           f"👨‍🍳 **KITCHEN SATIETY:**\n{get_progress_bar(meter_val)}")
    await update.message.reply_text(msg, parse_mode='Markdown')

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT username, daily_calories FROM pf_users WHERE daily_calories != 0 ORDER BY daily_calories DESC LIMIT 20")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if not rows:
        return await update.message.reply_text("🍔 **NO MUNCHERS YET.**")
    text = "🔥 **DAILY FEEDING FRENZY (TOP 20)** 🔥\n━━━━━━━━━━━━━━\n" + "\n".join([f"{i+1}. {escape_name(r[0])}: {r[1]:,} Cal" for i, r in enumerate(rows)])
    await update.message.reply_text(text, parse_mode='Markdown')

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT username, total_calories FROM pf_users WHERE user_id != 0 ORDER BY total_calories DESC LIMIT 20")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    text = "🏆 **THE HALL OF INFINITE GIRTH (TOP 20)** 🏆\n━━━━━━━━━━━━━━\n" + "\n".join([f"{i+1}. {escape_name(r[0])}: {r[1]:,} Cal" for i, r in enumerate(rows)])
    await update.message.reply_text(text, parse_mode='Markdown')

async def clogboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT username, CAST(daily_clog AS FLOAT) FROM pf_users WHERE daily_clog > 0 ORDER BY daily_clog DESC LIMIT 20")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if not rows:
        return await update.message.reply_text("🧪 **THE LAB IS CLEAN.**")
    text = "🧪 **LIVE LAB RESULTS (CURRENT CLOG %)** 🧪\n━━━━━━━━━━━━━━\n" + "\n".join([f"{i+1}. {escape_name(r[0])}: {r[1]:.1f}%" for i, r in enumerate(rows)])
    await update.message.reply_text(text, parse_mode='Markdown')

async def deaths(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT username, icu_lifetime FROM pf_users WHERE icu_lifetime > 0 ORDER BY icu_lifetime DESC LIMIT 20")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if not rows:
        return await update.message.reply_text("💀 **NO DEATHS LOGGED.**")
    text = "💀 **CARDIAC IMMORTALS (LIFETIME DEATHS)** 💀\n━━━━━━━━━━━━━━\n" + "\n".join([f"{i+1}. {escape_name(r[0])}: {r[1]} ICU Trips" for i, r in enumerate(rows)])
    await update.message.reply_text(text, parse_mode='Markdown')

# ==========================================
# 9. PHAT PFP GENERATOR
# ==========================================
async def phatme(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not phat_processor:
        return await update.message.reply_text("❌ Laboratory offline. (phat_engine.py missing)")
    user, now = update.effective_user, datetime.utcnow()
    conn = get_db_connection()
    cur = conn.cursor()
    try:
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
            await context.bot.send_photo(chat_id=update.effective_chat.id, photo=result_img_bytes, caption=f"🏆 **TRANSFORMATION COMPLETE** @{escape_name(user.username)}!")
            await status_msg.delete()
        else: 
            await status_msg.edit_text("⚠️ Synthesis failed.")
    except Exception as e: 
        logger.error(f"PhatMe Error: {e}")
        await update.message.reply_text("❌ Kitchen Connection Lost.")
    finally: 
        cur.close()
        conn.close()

# ==========================================
# 10. ADMIN & SYSTEM
# ==========================================
async def reward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    member = await context.bot.get_chat_member(update.effective_chat.id, user.id)
    if member.status not in ['administrator', 'creator']:
        return await update.message.reply_text("🚫 **UNAUTHORIZED.**")
    
    target_id = update.message.reply_to_message.from_user.id if update.message.reply_to_message else None
    if not target_id:
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

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE pf_users SET daily_calories = daily_calories + %s, total_calories = total_calories + %s WHERE user_id = %s", (bonus, bonus, target_id))
    conn.commit()
    cur.close()
    conn.close()
    
    await update.message.reply_text(f"🎯 **RAID REWARD: {tier}**\n+{bonus:,} Cal to @{escape_name(update.message.reply_to_message.from_user.username or update.message.reply_to_message.from_user.first_name)}")

async def winners(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT winner_type, username, CAST(score AS FLOAT), win_date FROM pf_airdrop_winners ORDER BY win_date DESC LIMIT 15")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if not rows:
        return await update.message.reply_text("📜 Hall of Fame is empty.")
    text = "🏆 **THE AIRDROP LEGENDS** 🏆\n━━━━━━━━━━━━━━\n"
    for r in rows:
        icon = "🍔" if r[0] == 'DAILY PHATTEST' else "🧪"
        score_val = f"{r[2]:.1f}%" if r[0] == 'TOP HACKER' else f"{int(r[2]):,}"
        text += f"{icon} `{r[3].strftime('%m/%d')}` | **{r[0]}**: {escape_name(r[1])} ({score_val})\n"
    await update.message.reply_text(text, parse_mode='Markdown')

async def set_bot_commands(application):
    cmds = [
        ("snack", "Eat"), ("hack", "Lab"), ("smack", "Raid [Reply/Tag]"), 
        ("gift", "Shipment [Reply]"), ("open", "Unbox"), ("trash", "Dump"), 
        ("status", "Vitals"), ("daily", "Rank"), ("leaderboard", "Girth"), 
        ("clogboard", "Live Clog %"), ("deaths", "ICU Deaths"),
        ("phatme", "Phat PFP Generator") 
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
        ("snack", snack), ("hack", hack), ("smack", smack), ("gift", gift), ("open", open_gift), 
        ("trash", trash_gift), ("reward", reward), ("status", status), 
        ("daily", daily), ("leaderboard", leaderboard), ("clogboard", clogboard), 
        ("deaths", deaths), ("winners", winners), ("phatme", phatme)
    ]
    for c, f in handlers:
        app.add_handler(CommandHandler(c, f))
        
    async def post_init(application):
        await set_bot_commands(application)
        application.create_task(automated_reset_task(application))
        application.create_task(check_pings(application))
        logger.info("🚀 Planet Fatness Online.")
        
    app.post_init = post_init
    app.run_polling(drop_pending_updates=True)
