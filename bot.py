import os, logging, random, json, psycopg2, threading, asyncio
from flask import Flask
from datetime import datetime, timedelta, time
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- WEB SERVER ---
flask_app = Flask(__name__)

@flask_app.route('/')
def home(): 
    return "Planet Fatness: Kitchen & Clog Lab are Open!"

@flask_app.route('/health')
def health():
    return "OK", 200

def run_flask():
    # Render dynamic port binding - prioritized to fix 'No open ports' error
    port = int(os.environ.get("PORT", 10000))
    logging.info(f"🚀 Binding Flask to port {port}")
    flask_app.run(host='0.0.0.0', port=port)

# --- BOT LOGIC ---
logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("TELEGRAM_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# Load Databases
with open('foods.json', 'r') as f:
    foods = json.load(f)
with open('hacks.json', 'r') as f:
    hacks = json.load(f)

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("ALTER TABLE pf_users ADD COLUMN IF NOT EXISTS daily_calories INTEGER DEFAULT 0;")
    cur.execute("ALTER TABLE pf_users ADD COLUMN IF NOT EXISTS daily_clog INTEGER DEFAULT 0;")
    cur.execute("ALTER TABLE pf_users ADD COLUMN IF NOT EXISTS is_icu BOOLEAN DEFAULT FALSE;")
    cur.execute("ALTER TABLE pf_users ADD COLUMN IF NOT EXISTS last_hack TIMESTAMP DEFAULT NULL;")
    cur.execute("ALTER TABLE pf_users ADD COLUMN IF NOT EXISTS last_snack TIMESTAMP DEFAULT NULL;")
    cur.execute("ALTER TABLE pf_users ADD COLUMN IF NOT EXISTS ping_sent BOOLEAN DEFAULT TRUE;")
    conn.commit()
    cur.close()
    conn.close()

def get_last_reset_time():
    now = datetime.now()
    # 8 PM EST is 01:00 UTC (Next Day)
    reset_today = datetime.combine(now.date(), time(1, 0)) 
    return reset_today if now >= reset_today else reset_today - timedelta(days=1)

# --- HARD RESET TASK ---
async def hard_reset_task(application):
    """Wipes all daily stats globally at exactly 8:00 PM EST (01:00 UTC)."""
    while True:
        now_utc = datetime.utcnow()
        if now_utc.hour == 1 and now_utc.minute == 0:
            logging.info("🚨 8PM EST: Hard-resetting all daily stats.")
            try:
                conn = get_db_connection()
                cur = conn.cursor()
                cur.execute("""
                    UPDATE pf_users 
                    SET daily_calories = 0, 
                        daily_clog = 0, 
                        is_icu = FALSE, 
                        ping_sent = FALSE
                """)
                conn.commit()
                cur.close()
                conn.close()
                logging.info("✅ Database bleached successfully.")
            except Exception as e:
                logging.error(f"❌ Hard reset failed: {e}")
            await asyncio.sleep(61)
        await asyncio.sleep(30)

# --- COMMANDS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to the Judgment Free Kitchen & Clog Lab! 🍔🧪\n\n"
        "High calories = High scores. Eat your daily meal, climb the board, and embrace the phatness.\n\n"
        "⚠️ **THE RULES:**\n"
        "• /snack daily to climb the ranks.\n"
        "• /hack at your own risk. DO NOT EXCEED 100% CLOG or you will flatline.\n"
        "• **DAILY AIRDROPS:** The #1 Snacker and #1 Hacker at 8 PM EST win the drop!\n"
    )

async def snack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name or "Chef"
    now = datetime.now()
    last_reset = get_last_reset_time()

    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT total_calories, last_snack, daily_calories FROM pf_users WHERE user_id = %s", (user_id,))
    user = cur.fetchone()

    if user and user[1] and now - user[1] < timedelta(hours=1):
        rem = timedelta(hours=1) - (now - user[1])
        return await update.message.reply_text(f"⌛️ Still digesting. Try again in {int(rem.total_seconds()//60)}m.")

    item = random.choice(foods)
    current_total = user[0] if user and user[0] is not None else 0
    current_daily = user[2] if user and user[2] is not None else 0
    
    if user and user[1] and user[1] < last_reset: current_daily = 0

    new_total = current_total + item['calories']
    new_daily = current_daily + item['calories']
    phat_reward = item.get('reward_phat', 0)
    phat_text = f"\n💰 Reward: {phat_reward:,} $PHAT" if phat_reward > 0 else ""

    cur.execute('''
        INSERT INTO pf_users (user_id, username, total_calories, daily_calories, last_snack, ping_sent)
        VALUES (%s, %s, %s, %s, %s, FALSE)
        ON CONFLICT (user_id) DO UPDATE SET
            username = EXCLUDED.username,
            total_calories = EXCLUDED.total_calories, daily_calories = EXCLUDED.daily_calories,
            last_snack = EXCLUDED.last_snack, ping_sent = FALSE
    ''', (user_id, username, new_total, new_daily, now))
    
    conn.commit(); cur.close(); conn.close()
    await update.message.reply_text(f"🍔 **{item['name']}** ({item['calories']:+d} Cal){phat_text}\n🔥 Daily: {new_daily:,}\n📈 All-Time: {new_total:,}")

async def hack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name or "Hacker"
    now = datetime.now()
    last_reset = get_last_reset_time()

    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT daily_clog, is_icu, last_hack FROM pf_users WHERE user_id = %s", (user_id,))
    user = cur.fetchone()

    clog, is_icu, l_hack = (user[0] or 0, user[1], user[2]) if user else (0, False, None)

    if l_hack and l_hack < last_reset:
        clog, is_icu = 0, False

    if l_hack:
        cd = timedelta(hours=2) if is_icu else timedelta(hours=1)
        if now - l_hack < cd:
            rem = cd - (now - l_hack)
            return await update.message.reply_text(f"⚠️ {'🏥 ICU' if is_icu else '⏳ RECOVERY'}: {int(rem.total_seconds()//60)}m left.")

    h = random.choice(hacks)
    gain = random.randint(h['min_clog'], h['max_clog'])
    new_c = clog + gain
    establishment = h.get('franchise', 'Secret Menu').upper()

    if new_c >= 100:
        cur.execute("UPDATE pf_users SET daily_clog=0, is_icu=True, last_hack=%s, ping_sent=False WHERE user_id=%s", (now, user_id))
        await update.message.reply_text(f"💀 **FLATLINE!** Your heart gave out at {establishment}. ICU for 2 hours.")
    else:
        adren = random.random() < 0.10
        save_t = now - timedelta(hours=2) if adren else now
        cur.execute("UPDATE pf_users SET daily_clog=daily_clog + %s, is_icu=False, last_hack=%s, ping_sent=FALSE WHERE user_id=%s", (gain, save_t, user_id))
        msg = f"🩺 **HACK SUCCESS: {h['name']}**\n📍 *Location: {establishment}*\n📈 Artery Clog: {new_c}% (+{gain}%)"
        if adren: msg += "\n\n⚡ **ADRENALINE SHOT!** Cooldown bypassed."
        await update.message.reply_text(msg)
    
    conn.commit(); cur.close(); conn.close()

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    raw_username = update.effective_user.username or update.effective_user.first_name or "Patient"
    username = raw_username.replace("_", "\\_")
    now = datetime.now()
    last_reset = get_last_reset_time()

    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT total_calories, daily_calories, daily_clog, is_icu, last_hack, last_snack FROM pf_users WHERE user_id = %s", (user_id,))
    user = cur.fetchone(); cur.close(); conn.close()

    if not user: return await update.message.reply_text("❌ No records found.")

    total_cal, daily_cal, clog, is_icu, l_hack, l_snack = user
    if l_hack and l_hack < last_reset: clog, is_icu = 0, False
    if l_snack and l_snack < last_reset: daily_cal = 0

    health = "🚨 CRITICAL" if is_icu else ("⚠️ PRE-FLATLINE" if (clog or 0) > 80 else "🟢 STABLE")
    
    report = (
        f"📋 *OFFICIAL MEDICAL REPORT: @{username}*\n"
        f"━━━━━━━━━━━━━━\n"
        f"🧬 *Status:* {health}\n"
        f"🔥 *Daily:* {daily_cal or 0:,} Cal\n"
        f"📈 *Total:* {total_cal or 0:,} Cal\n"
        f"🩸 *Artery Clog:* {clog or 0}%\n"
        f"━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(report, parse_mode='Markdown')

async def clogboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    last_reset = get_last_reset_time()
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("""
        SELECT username, daily_clog, is_icu FROM pf_users 
        WHERE daily_clog > 0 AND last_hack >= %s 
        ORDER BY daily_clog DESC LIMIT 10
    """, (last_reset,))
    rows = cur.fetchall(); cur.close(); conn.close()
    
    if not rows: return await update.message.reply_text("🧼 The ward is clean!")
    
    text = "🏥 **CARDIAC WARD** 🏥\n\n"
    for i, r in enumerate(rows):
        safe_name = r[0].replace("_", "\\_")
        text += f"{i+1}. {safe_name}: {r[1]}%{' [ICU]' if r[2] else ''}\n"
    await update.message.reply_text(text, parse_mode='Markdown')

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    last_reset = get_last_reset_time()
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("""
        SELECT username, daily_calories FROM pf_users 
        WHERE daily_calories > 0 AND last_snack >= %s 
        ORDER BY daily_calories DESC LIMIT 10
    """, (last_reset,))
    rows = cur.fetchall(); cur.close(); conn.close()
    
    if not rows: return await update.message.reply_text("🍳 Kitchen is empty!")

    text = "🔥 TOP DAILY MUNCHERS 🔥\n\n"
    for i, r in enumerate(rows):
        safe_name = r[0].replace("_", "\\_")
        text += f"{i+1}. {safe_name}: {r[1]:,} Cal\n"
    await update.message.reply_text(text, parse_mode='Markdown')

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT username, total_calories FROM pf_users ORDER BY total_calories DESC LIMIT 10")
    rows = cur.fetchall(); cur.close(); conn.close()
    text = "🏆 ALL-TIME PHATTEST 🏆\n\n"
    for i, r in enumerate(rows):
        safe_name = r[0].replace("_", "\\_")
        text += f"{i+1}. {safe_name}: {r[1]:,} Cal\n"
    await update.message.reply_text(text, parse_mode='Markdown')

async def reset_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE pf_users SET total_calories=0, daily_calories=0, daily_clog=0, is_icu=FALSE WHERE user_id=%s", (update.effective_user.id,))
    conn.commit(); cur.close(); conn.close()
    await update.message.reply_text("✅ Stats cleared.")

async def check_pings(application):
    while True:
        await asyncio.sleep(60); now = datetime.now(); ago = now - timedelta(hours=1)
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("SELECT user_id FROM pf_users WHERE ping_sent=FALSE AND (last_snack <= %s OR last_snack IS NULL) AND (last_hack <= %s OR last_hack IS NULL)", (ago, ago))
        for r in cur.fetchall():
            try:
                await application.bot.send_message(chat_id=r[0], text="🔔 **READY:** Time to /snack and /hack!")
                cur.execute("UPDATE pf_users SET ping_sent=TRUE WHERE user_id=%s", (r[0],))
            except: pass
        conn.commit(); cur.close(); conn.close()

if __name__ == '__main__':
    init_db()
    # Prioritize Flask thread to satisfy Render's health checks
    threading.Thread(target=run_flask, daemon=True).start()
    
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("snack", snack))
    app.add_handler(CommandHandler("hack", hack))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("clogboard", clogboard))
    app.add_handler(CommandHandler("daily", daily))
    app.add_handler(CommandHandler("reset_me", reset_me))
    
    asyncio.get_event_loop().create_task(hard_reset_task(app))
    asyncio.get_event_loop().create_task(check_pings(app))
    
    app.run_polling(drop_pending_updates=True)
