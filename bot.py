import os, logging, random, json, psycopg2, threading
from flask import Flask
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- DUMMY WEB SERVER ---
flask_app = Flask(__name__)
@flask_app.route('/')
def home(): return "Kitchen & Gym are Open!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port)

# --- BOT LOGIC ---
logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("TELEGRAM_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
SPOTIFY_URL = "Https://open.spotify.com/playlist/0beH25TnonUVfknlIcPjvS?si=sqh_WxrlRACZJIldrYpowg&pi=kF2InpZyQS-wY" 

with open('foods.json', 'r') as f:
    foods = json.load(f)

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    # Ensures all required columns exist
    cur.execute("ALTER TABLE pf_users ADD COLUMN IF NOT EXISTS last_rank INTEGER;")
    cur.execute("ALTER TABLE pf_users ADD COLUMN IF NOT EXISTS daily_calories INTEGER DEFAULT 0;")
    conn.commit()
    cur.close()
    conn.close()

def get_user_rank(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT rank FROM (
            SELECT user_id, RANK() OVER (ORDER BY total_calories DESC) as rank 
            FROM pf_users
        ) s WHERE user_id = %s
    """, (user_id,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result[0] if result else None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # UPDATED: Changed message to reflect 1h cooldown
    await update.message.reply_text("Welcome to the Judgment Free Kitchen! 🍔\nType /snack to eat (1h cooldown).")

async def snack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name or "Chef"
    now = datetime.now()

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT total_calories, last_snack, daily_calories FROM pf_users WHERE user_id = %s", (user_id,))
    user = cur.fetchone()

    # --- 1 HOUR COOLDOWN CHECK ---
    if user and user[1] and now - user[1] < timedelta(hours=1):
        remaining = timedelta(hours=1) - (now - user[1])
        minutes = int(remaining.total_seconds() // 60)
        seconds = int(remaining.total_seconds() % 60)
        await update.message.reply_text(f"⌛️ Still digesting. Try again in {minutes}m {seconds}s.")
        cur.close()
        conn.close()
        return

    food_item = random.choice(foods)
    current_total = user[0] if user and user[0] is not None else 0
    current_daily = user[2] if user and user[2] is not None else 0
    
    # 2. Daily Reset Logic: If last snack was before today, start daily at 0
    if user and user[1] and user[1].date() < now.date():
        current_daily = 0

    new_total = current_total + food_item['calories']
    new_daily = current_daily + food_item['calories']
    
    # 3. CRITICAL: This saves BOTH total and daily numbers
    cur.execute('''
        INSERT INTO pf_users (user_id, username, total_calories, daily_calories, last_snack)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
            username = EXCLUDED.username,
            total_calories = EXCLUDED.total_calories,
            daily_calories = EXCLUDED.daily_calories,
            last_snack = EXCLUDED.last_snack
    ''', (user_id, username, new_total, new_daily, now))
    
    conn.commit()
    cur.close()
    conn.close()

    await update.message.reply_text(
        f"Item: {food_item['name']} ({food_item['calories']:+d} Cal)\n"
        f"📈 All-Time: {new_total:,} Cal\n"
        f"🔥 Daily: {new_daily:,} Cal"
    )

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT username, total_calories FROM pf_users ORDER BY total_calories DESC LIMIT 10")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    if not rows:
        await update.message.reply_text("Kitchen is empty!")
        return
    text = "🏆 ALL-TIME PHATTEST 🏆\n\n"
    for i, r in enumerate(rows):
        text += f"{i+1}. {r[0]}: {r[1]:,} Cal\n"
    await update.message.reply_text(text)

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cur = conn.cursor()
    # Pulls anyone who snacked in the last 24 hours
    cur.execute("""
        SELECT username, daily_calories FROM pf_users 
        WHERE last_snack >= NOW() - INTERVAL '24 hours' 
        AND daily_calories > 0
        ORDER BY daily_calories DESC LIMIT 10
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        await update.message.reply_text("The daily leaderboard is empty! Get snacking. 🍟")
        return

    text = "🔥 24H TOP MUNCHERS 🔥\n\n"
    for i, r in enumerate(rows):
        text += f"{i+1}. {r[0]}: {r[1]:,} Cal\n"
    await update.message.reply_text(text)

async def reset_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE pf_users SET total_calories = 0, daily_calories = 0 WHERE user_id = %s", (user_id,))
    conn.commit()
    cur.close()
    conn.close()
    await update.message.reply_text("✅ Your calories have been reset to 0.")

async def wipe_everything(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.username != "Degen_Eeyore":
        await update.message.reply_text("🚫 Admin only.")
        return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM pf_users") 
    conn.commit()
    cur.close()
    conn.close()
    await update.message.reply_text("🧹 DATABASE WIPED.")

if __name__ == '__main__':
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("snack", snack))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("daily", daily))
    app.add_handler(CommandHandler("reset_me", reset_me))
    app.add_handler(CommandHandler("wipe_everything", wipe_everything))
    app.run_polling(drop_pending_updates=True)
