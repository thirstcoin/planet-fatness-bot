import os, logging, random, json, psycopg2, threading, asyncio
from flask import Flask
from datetime import datetime, timedelta, time
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- WEB SERVER ---
flask_app = Flask(__name__)
@flask_app.route('/')
def home(): return "Planet Fatness: Kitchen & Clog Lab are Open!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
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
    cur.execute("ALTER TABLE pf_users ADD COLUMN IF NOT EXISTS ping_sent BOOLEAN DEFAULT TRUE;")
    conn.commit()
    cur.close()
    conn.close()

def get_last_reset_time():
    now = datetime.now()
    reset_today = datetime.combine(now.date(), time(1, 0)) # 8 PM EST (01:00 UTC)
    return reset_today if now >= reset_today else reset_today - timedelta(days=1)

# --- COMMANDS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to the Judgment Free Kitchen & Clog Lab! 🍔🧪\n\n"
        "High calories = High scores. Eat your daily meal, climb the board, and embrace the phatness.\n\n"
        "⚠️ **THE RULES:**\n"
        "• Eat daily, climb the ranks.\n"
        "• /hack at your own risk. DO NOT EXCEED 100% CLOG or you will flatline.\n"
        "• **DAILY AIRDROPS:** The #1 Snacker and #1 Hacker at 8 PM EST win the drop!\n\n"
        "Use /snack or /hack to begin."
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

    if user:
        clog, is_icu, l_hack = user[0] or 0, user[1], user[2]
        if l_hack and l_hack < last_reset: clog, is_icu = 0, False
        cd = timedelta(hours=2) if is_icu else timedelta(hours=1)
        if l_hack and now - l_hack < cd:
            rem = cd - (now - l_hack)
            return await update.message.reply_text(f"⚠️ {'🏥 ICU' if is_icu else '⏳ RECOVERY'}: {int(rem.total_seconds()//60)}m left.")
    else: clog, is_icu = 0, False

    h = random.choice(hacks)
    gain = random.randint(h['min_clog'], h['max_clog'])
    new_c = clog + gain

    if new_c >= 100:
        roasts = [
            f"🚨 **FLATLINE!** Your heart sounded like a flip-flop in a dryer. ICU for 2 hours.",
            f"💀 **DECEASED.** Arteries are now 100% solid butter. See you in 120 minutes.",
            f"🏥 **CODE BLUE!** The paramedics found a {h['name']} in your hand. Recovery started."
        ]
        cur.execute("UPDATE pf_users SET daily_clog=0, is_icu=True, last_hack=%s, ping_sent=False WHERE user_id=%s", (now, user_id))
        await update.message.reply_text(random.choice(roasts))
    else:
        adren = random.random() < 0.10
        save_t = now - timedelta(hours=2) if adren else now
        cur.execute("UPDATE pf_users SET daily_clog=%s, is_icu=False, last_hack=%s, ping_sent=False WHERE user_id=%s", (new_c, save_t, user_id))
        msg = f"🩺 **HACK SUCCESS: {h['name']}**\n📋 {h['blueprint']}\n📈 Artery Clog: {new_c}% (+{gain}%)"
        if adren: msg += "\n\n⚡ **ADRENALINE SHOT!** Cooldown bypassed. GO AGAIN!"
        await update.message.reply_text(msg)
    
    conn.commit(); cur.close(); conn.close()

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    raw_username = update.effective_user.username or update.effective_user.first_name or "Patient"
    username = raw_username.replace("_", "\\_") # Markdown Shielding

    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT total_calories, daily_calories, daily_clog, is_icu, last_hack FROM pf_users WHERE user_id = %s", (user_id,))
    user = cur.fetchone(); cur.close(); conn.close()

    if not user: return await update.message.reply_text("❌ No records found. Go /snack or /hack first.")

    total_cal, daily_cal, clog, is_icu, l_hack = user
    total_cal = total_cal or 0
    daily_cal = daily_cal or 0
    clog = clog or 0
    
    health = "🚨 CRITICAL" if is_icu else ("⚠️ PRE-FLATLINE" if clog > 80 else "🟢 STABLE")
    
    report = (
        f"📋 *OFFICIAL MEDICAL REPORT: @{username}*\n"
        f"━━━━━━━━━━━━━━\n"
        f"🧬 *Status:* {health}\n"
        f"🔥 *Daily:* {daily_cal:,} Cal\n"
        f"📈 *Total:* {total_cal:,} Cal\n"
        f"🩸 *Artery Clog:* {clog}%\n"
        f"━━━━━━━━━━━━━━\n"
    )
    if is_icu and l_hack:
        rem = max(0, int(((l_hack + timedelta(hours=2)) - datetime.now()).total_seconds() // 60))
        report += f"🏥 _Patient unresponsive. Recovery: {rem}m._"
    else:
        note = "Blood consistency: Mayonnaise." if clog > 50 else "Patient is suspiciously thin."
        report += f"👨‍⚕️ _Note: {note}_"
    
    await update.message.reply_text(report, parse_mode='Markdown')

async def clogboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT username, daily_clog, is_icu FROM pf_users WHERE daily_clog > 0 ORDER BY daily_clog DESC LIMIT 10")
    rows = cur.fetchall(); cur.close(); conn.close()
    if not rows: return await update.message.reply_text("The ward is empty!")
    text = "🏥 **CARDIAC WARD** 🏥\n\n"
    for i, r in enumerate(rows): text += f"{i+1}. {r[0]}: {r[1]}%{' [ICU]' if r[2] else ''}\n"
    await update.message.reply_text(text)

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT username, total_calories FROM pf_users ORDER BY total_calories DESC LIMIT 10")
    rows = cur.fetchall(); cur.close(); conn.close()
    text = "🏆 ALL-TIME PHATTEST 🏆\n\n"
    for i, r in enumerate(rows): text += f"{i+1}. {r[0]}: {r[1]:,} Cal\n"
    await update.message.reply_text(text)

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT username, daily_calories FROM pf_users WHERE last_snack >= %s ORDER BY daily_calories DESC LIMIT 10", (get_last_reset_time(),))
    rows = cur.fetchall(); cur.close(); conn.close()
    text = "🔥 TOP DAILY MUNCHERS 🔥\n*(#1 eligible for 8PM EST Airdrop)*\n\n"
    for i, r in enumerate(rows): text += f"{i+1}. {r[0]}: {r[1]:,} Cal\n"
    await update.message.reply_text(text)

async def reset_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE pf_users SET total_calories=0, daily_calories=0, daily_clog=0, is_icu=FALSE WHERE user_id=%s", (update.effective_user.id,))
    conn.commit(); cur.close(); conn.close()
    await update.message.reply_text("✅ Stats cleared.")

async def wipe_everything(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username != "Degen_Eeyore": return
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("DELETE FROM pf_users"); conn.commit(); cur.close(); conn.close()
    await update.message.reply_text("Sweep complete. 🧹 DATABASE WIPED.")

async def check_pings(application):
    while True:
        await asyncio.sleep(60); now = datetime.now(); ago = now - timedelta(hours=1)
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("SELECT user_id FROM pf_users WHERE ping_sent=FALSE AND (last_snack <= %s OR last_snack IS NULL) AND (last_hack <= %s OR last_hack IS NULL)", (ago, ago))
        for r in cur.fetchall():
            try:
                await application.bot.send_message(chat_id=r[0], text="🔔 **READY:** Digestion complete. Time to /snack and /hack!")
                cur.execute("UPDATE pf_users SET ping_sent=TRUE WHERE user_id=%s", (r[0],))
            except: pass
        conn.commit(); cur.close(); conn.close()

if __name__ == '__main__':
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Explicit Individual Registration
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("snack", snack))
    app.add_handler(CommandHandler("hack", hack))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("clogboard", clogboard))
    app.add_handler(CommandHandler("daily", daily))
    app.add_handler(CommandHandler("reset_me", reset_me))
    app.add_handler(CommandHandler("wipe_everything", wipe_everything))
    
    asyncio.get_event_loop().create_task(check_pings(app))
    app.run_polling(drop_pending_updates=True)
