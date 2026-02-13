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
def home(): return "Planet Fatness: All Systems Online 🧪🍔", 200

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

# ==========================================
# 3. DATABASE INITIALIZATION
# ==========================================
def init_db(bot_id=None):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS pf_users (
            user_id BIGINT PRIMARY KEY, username TEXT,
            total_calories BIGINT DEFAULT 0, daily_calories INTEGER DEFAULT 0,
            daily_clog INTEGER DEFAULT 0, is_icu BOOLEAN DEFAULT FALSE,
            last_snack TIMESTAMP, last_hack TIMESTAMP,
            ping_sent BOOLEAN DEFAULT TRUE, last_gift_sent TIMESTAMP,
            sabotage_val BIGINT DEFAULT 0, gifts_sent_val BIGINT DEFAULT 0
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
    
    if bot_id:
        cur.execute("DELETE FROM pf_gifts WHERE receiver_id = %s", (bot_id,))
        logger.info(f"🧹 Kitchen Purge: Cleared shipments for Bot ID {bot_id}")
        
    conn.commit(); cur.close(); conn.close()

# ==========================================
# 4. BACKGROUND TASKS
# ==========================================
async def automated_reset_task(application):
    while True:
        now_utc = datetime.utcnow()
        if now_utc.hour == 1 and now_utc.minute == 0:
            try:
                conn = get_db_connection(); cur = conn.cursor()
                for label, col in [('DAILY PHATTEST', 'daily_calories'), ('TOP HACKER', 'daily_clog')]:
                    cur.execute(f"SELECT username, {col} FROM pf_users WHERE {col} > 0 ORDER BY {col} DESC LIMIT 1")
                    winner = cur.fetchone()
                    if winner:
                        cur.execute("INSERT INTO pf_airdrop_winners (winner_type, username, score) VALUES (%s, %s, %s)", (label, winner[0], winner[1]))
                cur.execute("UPDATE pf_users SET daily_calories = 0, daily_clog = 0, is_icu = FALSE, ping_sent = FALSE")
                conn.commit(); cur.close(); conn.close()
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
    user, now = update.effective_user, datetime.utcnow()
    conn = None
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("SELECT total_calories, daily_calories, last_snack FROM pf_users WHERE user_id = %s", (user.id,))
        u = cur.fetchone()
        
        if u and u[2] and now - u[2] < timedelta(hours=1):
            rem = timedelta(hours=1) - (now - u[2])
            return await update.message.reply_text(f"⌛️ Digesting... {int(rem.total_seconds()//60)}m left.")
        
        item = random.choice(foods)
        cal_val = item['calories']
        gif_url = item.get('gif') # Pull GIF URL if it exists in JSON
        
        c_total, c_daily = (u[0] or 0, u[1] or 0) if u else (0, 0)
        new_daily = c_daily + cal_val
        new_total = max(0, c_total + cal_val)

        cur.execute("""
            INSERT INTO pf_users (user_id, username, total_calories, daily_calories, last_snack, ping_sent)
            VALUES (%s, %s, %s, %s, %s, FALSE)
            ON CONFLICT (user_id) DO UPDATE SET
            username=EXCLUDED.username, total_calories=%s, 
            daily_calories=%s, last_snack=%s, ping_sent=FALSE
        """, (user.id, user.username or user.first_name, new_total, new_daily, now, new_total, new_daily, now))
        
        conn.commit(); cur.close(); conn.close()
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
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT daily_clog, is_icu, last_hack FROM pf_users WHERE user_id = %s", (user_id,))
    u = cur.fetchone()
    clog, is_icu, l_hack = (u[0] or 0, u[1], u[2]) if u else (0, False, None)
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
# 6. MYSTERY GIFT LOGIC
# ==========================================
async def gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sender, now = update.effective_user, datetime.utcnow()
    if not update.message.reply_to_message:
        return await update.message.reply_text("💡 You must **REPLY** to a message with /gift!")
    
    receiver = update.message.reply_to_message.from_user
    
    if receiver.id == context.bot.id:
        is_poison = random.choice([True, False])
        if is_poison:
            penalty = 1500
            conn = get_db_connection(); cur = conn.cursor()
            cur.execute("""
                UPDATE pf_users SET 
                daily_calories = daily_calories - %s,
                total_calories = GREATEST(0, total_calories - %s)
                WHERE user_id = %s
            """, (penalty, penalty, sender.id))
            conn.commit(); cur.close(); conn.close()
            return await update.message.reply_text(
                f"💀 **THE CHEF REFLECTS!**\n"
                f"Trying to poison the kitchen, {escape_name(sender.first_name)}?\n"
                f"Toxin bounced back. **-{penalty:,} Cal** deducted. 反射"
            )
        else:
            return await update.message.reply_text(f"😋 **OM NOM NOM...**\nThe Chef devours your offering. Delicious. You get nothing.")

    if receiver.id == sender.id: return await update.message.reply_text("🚫 Self-gifting is prohibited.")

    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("SELECT id FROM pf_gifts WHERE receiver_id = %s AND is_opened = FALSE", (receiver.id,))
        if cur.fetchone():
            conn.close()
            return await update.message.reply_text(f"📦 **DOCK BLOCKED:** {escape_name(receiver.first_name)} has an unopened shipment.")

        cur.execute("SELECT last_gift_sent FROM pf_users WHERE user_id = %s", (sender.id,))
        res = cur.fetchone()
        if res and res[0] and now - res[0] < timedelta(hours=1):
            rem = timedelta(hours=1) - (now - res[0])
            conn.close()
            return await update.message.reply_text(f"⏳ **COOLDOWN:** {int(rem.total_seconds()//60)}m remaining.")

        is_poison_roll = random.choice([True, False])
        if is_poison_roll:
            item = random.choice(PUNISHMENTS); val = random.randint(item['v'][0], item['v'][1]); i_type = "POISON"
        else:
            item = random.choice(foods); val = item.get('calories', 500); i_type = "PROTEIN"

        cur.execute("""
            INSERT INTO pf_gifts (sender_id, sender_name, receiver_id, item_name, item_type, value, flavor_text) 
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (sender.id, sender.first_name, receiver.id, item['name'], i_type, val, item.get('msg', 'Incoming Delivery!')))
        cur.execute("UPDATE pf_users SET last_gift_sent = %s WHERE user_id = %s", (now, sender.id))
        conn.commit(); cur.close(); conn.close()
        await update.message.reply_text(f"📦 **MYSTERY SHIPMENT DROPPED!**\n@{escape_name(receiver.username or receiver.first_name)}, will you `/open` or `/trash` it?")
    except Exception as e: await update.message.reply_text(f"⚠️ Error: {e}")

async def open_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = None
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("SELECT id, sender_name, item_name, item_type, value, sender_id FROM pf_gifts WHERE receiver_id = %s AND is_opened = FALSE ORDER BY id DESC LIMIT 1", (user_id,))
        row = cur.fetchone()
        if not row: return await update.message.reply_text("📦 Your dock is empty.")
        
        g_id, s_name, i_name, i_type, val, s_id = row
        cur.execute("UPDATE pf_gifts SET is_opened = TRUE WHERE id = %s", (g_id,))
        
        cur.execute("""
            UPDATE pf_users SET 
            daily_calories = daily_calories + %s, 
            total_calories = GREATEST(0, total_calories + %s) 
            WHERE user_id = %s
        """, (val, val, user_id))
        
        col = "gifts_sent_val" if i_type == "PROTEIN" else "sabotage_val"
        cur.execute(f"UPDATE pf_users SET {col} = {col} + %s WHERE user_id = %s", (abs(val), s_id))
        conn.commit(); cur.close(); conn.close()
        
        sign = "+" if val > 0 else ""
        header = "💉 **FUEL INJECTED!**" if i_type == "PROTEIN" else "💀 **TOXIN DETECTED!**"
        await update.message.reply_text(f"{header}\nFrom **{escape_name(s_name)}**: {i_name}\n📊 Impact: {sign}{val:,} Cal")
    except Exception as e:
        if conn: conn.rollback(); conn.close()
        await update.message.reply_text(f"⚠️ Error: {e}")

async def trash_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE pf_gifts SET is_opened = TRUE WHERE receiver_id = %s AND is_opened = FALSE", (user_id,))
    cur.execute("UPDATE pf_users SET daily_calories = daily_calories - 100 WHERE user_id = %s", (user_id,))
    conn.commit(); cur.close(); conn.close()
    await update.message.reply_text("🚮 **SCRAPPED:** Paid 100 Cal fee.")

# ==========================================
# 7. ENHANCED ADMIN REWARD SYSTEM
# ==========================================
async def reward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    member = await context.bot.get_chat_member(chat_id, user.id)
    if member.status not in ['administrator', 'creator']:
        return await update.message.reply_text("🚫 **UNAUTHORIZED.**")

    receiver_id, receiver_name = None, None

    # Logic: Priority to Reply, then to @Username
    if update.message.reply_to_message:
        target = update.message.reply_to_message.from_user
        receiver_id, receiver_name = target.id, target.username or target.first_name
    elif context.args:
        input_name = context.args[0].replace("@", "")
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("SELECT user_id, username FROM pf_users WHERE username ILIKE %s", (input_name,))
        res = cur.fetchone()
        cur.close(); conn.close()
        if res:
            receiver_id, receiver_name = res
        else:
            return await update.message.reply_text(f"❌ **USER NOT FOUND:** '{input_name}' is not in the database.")
    else:
        return await update.message.reply_text("💡 **HOW TO:** Reply to a user OR type `/reward @username`.")

    roll = random.random()
    if roll < 0.85:
        t_name, t_min, t_max, t_icon = "SCOUT SNACK", 300, 700, "🍪"
    elif roll < 0.97:
        t_name, t_min, t_max, t_icon = "RAIDER'S FEAST", 1000, 1800, "🍖"
    else:
        t_name, t_min, t_max, t_icon = "ALPHA RATION", 2500, 3500, "🔥"

    bonus = random.randint(t_min, t_max)
    conn = None
    try:
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("""
            UPDATE pf_users SET daily_calories = daily_calories + %s, total_calories = total_calories + %s WHERE user_id = %s
        """, (bonus, bonus, receiver_id))
        conn.commit(); cur.close(); conn.close()
        msg = (f"🎯 **RAID VERIFIED**\n━━━━━━━━━━━━━━\nUser: @{escape_name(receiver_name)}\nReward: **{t_icon} {t_name}**\nCalories: +{bonus:,}\nVerified by: @{escape_name(user.username or user.first_name)}\n━━━━━━━━━━━━━━")
        await update.message.reply_text(msg, parse_mode='Markdown')
    except Exception as e:
        if conn: conn.rollback(); conn.close()
        await update.message.reply_text("❌ Database error.")

# ==========================================
# 8. REPORTS & LEADERBOARDS
# ==========================================
async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT username, daily_calories FROM pf_users WHERE daily_calories != 0 ORDER BY daily_calories DESC LIMIT 15")
    rows = cur.fetchall(); cur.close(); conn.close()
    if not rows: return await update.message.reply_text("🍔 **NO MUNCHERS YET TODAY.**")
    text = "🔥 **DAILY FEEDING FRENZY** 🔥\n━━━━━━━━━━━━━━\n"
    text += "\n".join([f"{i+1}. {escape_name(r[0])}: {r[1]:,} Cal" for i, r in enumerate(rows)])
    await update.message.reply_text(text, parse_mode='Markdown')

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT username, total_calories FROM pf_users ORDER BY total_calories DESC LIMIT 10")
    rows = cur.fetchall(); cur.close(); conn.close()
    text = "🏆 **THE HALL OF INFINITE GIRTH** 🏆\n━━━━━━━━━━━━━━\n"
    text += "\n".join([f"{i+1}. {escape_name(r[0])}: {r[1]:,} Cal" for i, r in enumerate(rows)])
    await update.message.reply_text(text, parse_mode='Markdown')

async def clogboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT username, daily_clog, is_icu FROM pf_users WHERE daily_clog > 0 ORDER BY daily_clog DESC LIMIT 10")
    rows = cur.fetchall(); cur.close(); conn.close()
    if not rows: return await update.message.reply_text("🧪 **THE LAB IS CLEAN.**")
    text = "🧪 **BEATS FROM THE CARDIAC WARD** 🧪\n━━━━━━━━━━━━━━\n"
    text += "\n".join([f"{i+1}. {escape_name(r[0])}: {r[1]}% {'💀' if r[2] else ''}" for i, r in enumerate(rows)])
    await update.message.reply_text(text, parse_mode='Markdown')

async def winners(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT winner_type, username, score, win_date FROM pf_airdrop_winners ORDER BY win_date DESC LIMIT 15")
    rows = cur.fetchall(); cur.close(); conn.close()
    if not rows: return await update.message.reply_text("📜 Hall of Fame is empty.")
    text = "🏆 **THE 8PM AIRDROP LEGENDS** 🏆\n━━━━━━━━━━━━━━\n"
    for r in rows:
        icon = "🍔" if r[0] == 'DAILY PHATTEST' else "🧪"
        text += f"{icon} `{r[3].strftime('%m/%d')}` | **{r[0]}**: {escape_name(r[1])} ({r[2]:,})\n"
    await update.message.reply_text(text, parse_mode='Markdown')

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT total_calories, daily_calories, daily_clog, is_icu FROM pf_users WHERE user_id = %s", (user.id,))
    u = cur.fetchone(); cur.close(); conn.close()
    if not u: return await update.message.reply_text("❌ No records.")
    msg = f"📋 *VITALS: @{escape_name(user.first_name)}*\n━━━━━━━━━━━━━━\n🧬 Status: {'🚨 ICU' if u[3] else '🟢 STABLE'}\n🔥 Daily: {u[1]:,} Cal\n📈 Total: {u[0]:,} Cal\n🩸 Clog: {u[2]}%\n━━━━━━━━━━━━━━"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def set_bot_commands(application):
    cmds = [
        ("snack", "Devour a mystery feast"),
        ("hack", "Infiltrate the Secret Menu Lab"),
        ("gift", "Dispatch a Mystery Shipment [Reply]"),
        ("open", "Unbox your pending shipment"),
        ("trash", "Dump the contraband (Costs 100 Cal)"),
        ("reward", "Admins: Grant calories for raids [Reply or @]"),
        ("status", "Review your medical vitals"),
        ("daily", "The Daily Feeding Frenzy"),
        ("leaderboard", "The Hall of Infinite Girth"),
        ("clogboard", "Beats from the Cardiac Ward"),
        ("winners", "The 8PM Airdrop Legends")
    ]
    await application.bot.set_my_commands(cmds)

if __name__ == "__main__":
    try:
        b_id = int(TOKEN.split(':')[0])
    except:
        b_id = None
        
    init_db(b_id)
    
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("snack", snack))
    app.add_handler(CommandHandler("hack", hack))
    app.add_handler(CommandHandler("gift", gift))
    app.add_handler(CommandHandler("open", open_gift))
    app.add_handler(CommandHandler("trash", trash_gift))
    app.add_handler(CommandHandler("reward", reward))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("daily", daily))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("clogboard", clogboard))
    app.add_handler(CommandHandler("winners", winners))
    
    async def post_init(application):
        await set_bot_commands(application)
        application.create_task(automated_reset_task(application))
        application.create_task(check_pings(application))
        logger.info("🚀 Planet Fatness Online.")

    app.post_init = post_init
    app.run_polling(drop_pending_updates=True)
