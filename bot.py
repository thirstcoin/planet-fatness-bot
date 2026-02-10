import os, logging, random, json, threading, asyncio
from flask import Flask
from datetime import datetime, timedelta, time
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# ==========================================
# 1. ENGINE & WEB SERVER
# ==========================================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
flask_app = Flask(__name__)

@flask_app.route("/")
def home(): return "Planet Fatness: PROTEIN vs POISON Server LIVE 🧪💀", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

threading.Thread(target=run_flask, daemon=True).start()

try:
    import psycopg2
except:
    psycopg2 = None

TOKEN = os.getenv("TELEGRAM_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# ==========================================
# 2. DEGEN CONFIG & DATA
# ==========================================
foods, hacks = [], []
try:
    with open("foods.json", "r") as f: foods = json.load(f)
    with open("hacks.json", "r") as f: hacks = json.load(f)
except Exception as e: logger.error(f"❌ JSON Load Failed: {e}")

PUNISHMENTS = [
    {"name": "Industrial Laxative", "msg": "Daily total vanished in a flash. 🚽", "v": (-3000, -1800)},
    {"name": "Sugar-Free Gummy Bears", "msg": "The 'Haribo Horror' strikes. 📉", "v": (-1800, -1000)},
    {"name": "Diet Water", "msg": "The ultimate insult to mass. 💧", "v": (-500, -200)},
    {"name": "Personal Trainer's Card", "msg": "Calories burned in pure fear. 🏃‍♂️", "v": (-1200, -800)}
]

def get_db_connection(): return psycopg2.connect(DATABASE_URL, sslmode="require")

def escape_name(name):
    if not name: return "Degen"
    return name.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`").replace("[", "\\[")

def get_last_reset_time():
    now = datetime.utcnow()
    # 8 PM EST = 01:00 UTC
    reset_today = datetime.combine(now.date(), time(1, 0)) 
    return reset_today if now >= reset_today else reset_today - timedelta(days=1)

# ==========================================
# 3. DATABASE INITIALIZATION
# ==========================================
def init_db():
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pf_users (
            user_id BIGINT PRIMARY KEY, username TEXT,
            total_calories BIGINT DEFAULT 0, daily_calories INTEGER DEFAULT 0,
            daily_clog INTEGER DEFAULT 0, is_icu BOOLEAN DEFAULT FALSE,
            last_snack TIMESTAMP, last_hack TIMESTAMP, last_gift_sent TIMESTAMP,
            ping_sent BOOLEAN DEFAULT TRUE, sabotage_val BIGINT DEFAULT 0,
            gifts_sent_val BIGINT DEFAULT 0
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pf_airdrop_winners (
            id SERIAL PRIMARY KEY, winner_type TEXT, username TEXT, 
            score BIGINT, win_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pf_gifts (
            id SERIAL PRIMARY KEY, sender_id BIGINT, sender_name TEXT,
            receiver_id BIGINT, item_name TEXT, item_type TEXT,
            value INTEGER, flavor_text TEXT, is_opened BOOLEAN DEFAULT FALSE
        );
    """)
    conn.commit(); cur.close(); conn.close()

# ==========================================
# 4. BACKGROUND TASKS (RESET & PINGS)
# ==========================================
async def automated_reset_task(application):
    while True:
        now_utc = datetime.utcnow()
        if now_utc.hour == 1 and now_utc.minute == 0:
            try:
                conn = get_db_connection(); cur = conn.cursor()
                for leader_type, col in [('DAILY PHATTEST', 'daily_calories'), ('TOP HACKER', 'daily_clog')]:
                    cur.execute(f"""
                        WITH TopScore AS (SELECT MAX({col}) as m FROM pf_users WHERE {col} > 0)
                        SELECT username, {col} FROM pf_users, TopScore WHERE {col} = TopScore.m
                    """)
                    for w in cur.fetchall():
                        cur.execute("INSERT INTO pf_airdrop_winners (winner_type, username, score) VALUES (%s, %s, %s)", (leader_type, w[0], w[1]))

                cur.execute("UPDATE pf_users SET daily_calories = 0, daily_clog = 0, is_icu = FALSE, ping_sent = FALSE")
                conn.commit(); cur.close(); conn.close()
                logger.info("🚨 8PM EST Reset Complete.")
            except Exception as e: logger.error(f"Reset Error: {e}")
            await asyncio.sleep(61)
        await asyncio.sleep(30)

async def check_pings(application):
    while True:
        await asyncio.sleep(60)
        ago = datetime.utcnow() - timedelta(hours=1)
        try:
            conn = get_db_connection(); cur = conn.cursor()
            cur.execute("SELECT user_id FROM pf_users WHERE ping_sent=FALSE AND (last_snack <= %s OR last_snack IS NULL)", (ago,))
            for r in cur.fetchall():
                try:
                    await application.bot.send_message(chat_id=r[0], text="🔔 **READY:** Time to /snack and /hack!")
                    cur.execute("UPDATE pf_users SET ping_sent=TRUE WHERE user_id=%s", (r[0],))
                except: pass
            conn.commit(); cur.close(); conn.close()
        except: pass

# ==========================================
# 5. CORE ACTIONS
# ==========================================
async def snack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    now, uname = datetime.utcnow(), user.username or user.first_name
    last_reset = get_last_reset_time()
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("SELECT total_calories, last_snack, daily_calories FROM pf_users WHERE user_id = %s", (user.id,))
        u = cur.fetchone()
        if u and u[1] and now - u[1] < timedelta(hours=1):
            rem = timedelta(hours=1) - (now - u[1])
            return await update.message.reply_text(f"⌛️ Digesting... {int(rem.total_seconds()//60)}m left.")
        
        item = random.choice(foods)
        c_total, l_snack, c_daily = (u[0] or 0, u[1], u[2] or 0) if u else (0, None, 0)
        if l_snack and l_snack < last_reset: c_daily = 0
        new_total, new_daily = c_total + item['calories'], c_daily + item['calories']

        cur.execute("""
            INSERT INTO pf_users (user_id, username, total_calories, daily_calories, last_snack, ping_sent)
            VALUES (%s, %s, %s, %s, %s, FALSE)
            ON CONFLICT (user_id) DO UPDATE SET
            username=EXCLUDED.username, total_calories=EXCLUDED.total_calories, daily_calories=EXCLUDED.daily_calories, last_snack=EXCLUDED.last_snack, ping_sent=FALSE
        """, (user.id, uname, new_total, new_daily, now))
        conn.commit(); cur.close(); conn.close()
        await update.message.reply_text(f"🍔 **{item['name']}** (+{item['calories']} Cal)\n🔥 Daily: {new_daily:,}")
    except: await update.message.reply_text("❌ Kitchen Busy.")

async def hack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id, now, last_reset = update.effective_user.id, datetime.utcnow(), get_last_reset_time()
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT daily_clog, is_icu, last_hack FROM pf_users WHERE user_id = %s", (user_id,))
    u = cur.fetchone()
    clog, is_icu, l_hack = (u[0] or 0, u[1], u[2]) if u else (0, False, None)
    if l_hack and l_hack < last_reset: clog, is_icu = 0, False
    cd = timedelta(hours=2) if is_icu else timedelta(hours=1)
    if l_hack and now - l_hack < cd:
        rem = cd - (now - l_hack)
        return await update.message.reply_text(f"🏥 {'ICU' if is_icu else 'Recovery'}: {int(rem.total_seconds()//60)}m left.")

    h = random.choice(hacks)
    gain = random.randint(int(h.get("min_clog", 1)), int(h.get("max_clog", 5)))
    new_c = clog + gain
    if new_c >= 100:
        cur.execute("UPDATE pf_users SET daily_clog=0, is_icu=True, last_hack=%s WHERE user_id=%s", (now, user_id))
        await update.message.reply_text(f"💀 **FLATLINE!** Lab failure. ICU for 2 hours.")
    else:
        cur.execute("UPDATE pf_users SET daily_clog=daily_clog + %s, is_icu=False, last_hack=%s WHERE user_id=%s", (gain, now, user_id))
        await update.message.reply_text(f"🩺 **HACK SUCCESS:** {h.get('name')}\n📈 Clog: {new_c}% (+{gain}%)")
    conn.commit(); cur.close(); conn.close()

# ==========================================
# 6. SOCIAL (PROTEIN VS POISON)
# ==========================================
async def gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender = update.effective_user
    now = datetime.utcnow()
    if not update.message.reply_to_message:
        return await update.message.reply_text("💡 Reply to a degen with `/gift protein` or `/gift poison`!")
    if not context.args or context.args[0].lower() not in ['protein', 'poison']:
        return await update.message.reply_text("❓ Use `/gift protein` or `/gift poison`.")
    
    choice, receiver = context.args[0].lower(), update.message.reply_to_message.from_user
    if receiver.id == sender.id: return await update.message.reply_text("🚫 No self-gifting.")
    
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT id FROM pf_gifts WHERE receiver_id = %s AND is_opened = FALSE", (receiver.id,))
    if cur.fetchone():
        conn.close()
        return await update.message.reply_text(f"📦 **DOCK BLOCKED:** @{escape_name(receiver.username or receiver.first_name)} has an unopened gift.")

    cur.execute("SELECT last_gift_sent FROM pf_users WHERE user_id = %s", (sender.id,))
    res = cur.fetchone()
    if res and res[0] and now - res[0] < timedelta(hours=1):
        rem = timedelta(hours=1) - (now - res[0])
        conn.close()
        return await update.message.reply_text(f"⏳ Cooldown: {int(rem.total_seconds()//60)}m.")
    
    item = random.choice(foods) if choice == 'protein' else random.choice(PUNISHMENTS)
    val = item.get('calories') if choice == 'protein' else random.randint(*item['v'])
    i_type = "PROTEIN" if choice == 'protein' else "POISON"

    cur.execute("""
        INSERT INTO pf_gifts (sender_id, sender_name, receiver_id, item_name, item_type, value, flavor_text) 
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (sender.id, sender.first_name, receiver.id, item['name'], i_type, val, item.get('msg', 'Incoming shipment!')))
    cur.execute("UPDATE pf_users SET last_gift_sent = %s WHERE user_id = %s", (now, sender.id))
    conn.commit(); cur.close(); conn.close()
    await update.message.reply_text(f"📦 **SHIPMENT DROPPED!** @{escape_name(receiver.username or receiver.first_name)} use `/open` or `/trash`.")

async def open_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT id, sender_name, item_name, item_type, value, flavor_text, sender_id FROM pf_gifts WHERE receiver_id = %s AND is_opened = FALSE ORDER BY id DESC LIMIT 1", (user_id,))
    row = cur.fetchone()
    if not row: return await update.message.reply_text("📦 No deliveries.")
    
    cur.execute("UPDATE pf_gifts SET is_opened = TRUE WHERE id = %s", (row[0],))
    cur.execute("""
        UPDATE pf_users SET daily_calories = GREATEST(0, daily_calories + %s), 
        total_calories = GREATEST(0, total_calories + %s) WHERE user_id = %s
    """, (row[4], row[4], user_id))
    
    col = "gifts_sent_val" if row[3] == "PROTEIN" else "sabotage_val"
    cur.execute(f"UPDATE pf_users SET {col} = {col} + %s WHERE user_id = %s", (abs(row[4]), row[6]))
    conn.commit(); cur.close(); conn.close()
    
    header = "💉 **FUEL INJECTED!**" if row[3] == "PROTEIN" else "💀 **TOXIN DETECTED!**"
    await update.message.reply_text(f"{header}\nFrom **{escape_name(row[1])}**: {row[2]}!\n📈 Impact: {row[4]:+,} Cal")

async def trash_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE pf_gifts SET is_opened = TRUE WHERE receiver_id = %s AND is_opened = FALSE", (user_id,))
    cur.execute("UPDATE pf_users SET daily_calories = GREATEST(0, daily_calories - 100) WHERE user_id = %s", (user_id,))
    conn.commit(); cur.close(); conn.close()
    await update.message.reply_text("🚮 **SCRAPPED:** Paid 100 Cal fee to clear the dock.")

# ==========================================
# 7. STATUS & LEADERBOARDS
# ==========================================
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, last_reset = update.effective_user, get_last_reset_time()
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT total_calories, daily_calories, daily_clog, is_icu, last_hack, last_snack FROM pf_users WHERE user_id = %s", (user.id,))
    u = cur.fetchone(); cur.close(); conn.close()
    if not u: return await update.message.reply_text("❌ No records.")
    d_cal = u[1] if (u[5] and u[5] >= last_reset) else 0
    clog = u[2] if (u[4] and u[4] >= last_reset) else 0
    msg = f"📋 *REPORT: @{escape_name(user.first_name)}*\n━━━━━━━━━━━━━━\n🧬 Status: {'🚨 ICU' if u[3] else '🟢 STABLE'}\n🔥 Daily: {d_cal:,} Cal\n📈 Total: {u[0]:,} Cal\n🩸 Clog: {clog}%\n━━━━━━━━━━━━━━"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def clogboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    last_reset = get_last_reset_time()
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("""
        SELECT username, daily_clog, is_icu FROM pf_users 
        WHERE daily_clog > 0 AND last_hack >= %s
        ORDER BY daily_clog DESC LIMIT 10
    """, (last_reset,))
    rows = cur.fetchall(); cur.close(); conn.close()
    if not rows: return await update.message.reply_text("🏥 **CARDIAC WARD EMPTY.**")
    text = "🧪 **CARDIAC WARD** 🧪\n━━━━━━━━━━━━━━\n"
    text += "\n".join([f"{i+1}. {escape_name(r[0])}: {r[1]}% {'💀' if r[2] else ''}" for i, r in enumerate(rows)])
    await update.message.reply_text(text, parse_mode='Markdown')

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    last_reset = get_last_reset_time()
    conn = get_db_connection(); cur = conn.cursor()
    # Pull data where user was active (snack or gift) since last reset
    cur.execute("""
        SELECT username, daily_calories FROM pf_users 
        WHERE daily_calories > 0 
        AND (last_snack >= %s OR last_gift_sent >= %s)
        ORDER BY daily_calories DESC LIMIT 10
    """, (last_reset, last_reset))
    rows = cur.fetchall(); cur.close(); conn.close()
    if not rows: return await update.message.reply_text("🍔 **NO MUNCHERS YET TODAY.**")
    text = "🔥 **DAILY PHATTEST (SINCE 8PM)** 🔥\n━━━━━━━━━━━━━━\n"
    text += "\n".join([f"{i+1}. {escape_name(r[0])}: {r[1]:,} Cal" for i, r in enumerate(rows)])
    await update.message.reply_text(text, parse_mode='Markdown')

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT username, total_calories FROM pf_users ORDER BY total_calories DESC LIMIT 10")
    rows = cur.fetchall(); cur.close(); conn.close()
    text = "🏆 **ALL-TIME PHATTEST** 🏆\n\n" + "\n".join([f"{i+1}. {escape_name(r[0])}: {r[1]:,} Cal" for i, r in enumerate(rows)])
    await update.message.reply_text(text, parse_mode='Markdown')

async def winners(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT winner_type, username, score, win_date FROM pf_airdrop_winners ORDER BY win_date DESC LIMIT 15")
    rows = cur.fetchall(); cur.close(); conn.close()
    if not rows: return await update.message.reply_text("📜 Log is empty.")
    text = "🏆 **AIRDROP WINNER LOG** 🏆\n\n"
    for r in rows:
        icon = "🎰" if r[0] == 'JACKPOT' else ("🍔" if r[0] == 'DAILY PHATTEST' else "🧪")
        text += f"{icon} `{r[3].strftime('%m/%d')}` | **{r[0]}**: {escape_name(r[1])} ({r[2]:,})\n"
    await update.message.reply_text(text, parse_mode='Markdown')

# ==========================================
# 8. STARTUP
# ==========================================
if __name__ == "__main__":
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("snack", snack))
    app.add_handler(CommandHandler("hack", hack))
    app.add_handler(CommandHandler("gift", gift))
    app.add_handler(CommandHandler("open", open_gift))
    app.add_handler(CommandHandler("trash", trash_gift))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("winners", winners))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("clogboard", clogboard))
    app.add_handler(CommandHandler("daily", daily))
    
    async def post_init(application):
        application.create_task(automated_reset_task(application))
        application.create_task(check_pings(application))
    app.post_init = post_init
    app.run_polling(drop_pending_updates=True)
