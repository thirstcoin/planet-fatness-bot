import os, logging, random, json, psycopg2, threading
from flask import Flask
from datetime import datetime, timedelta, time
from telegram import Update
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

with open('foods.json', 'r') as f:
    foods = json.load(f)

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("ALTER TABLE pf_users ADD COLUMN IF NOT EXISTS daily_calories INTEGER DEFAULT 0;")
    conn.commit()
    cur.close()
    conn.close()

# HELPER: Calculates the most recent 8:00 PM EST (01:00 UTC)
def get_last_reset_time():
    now = datetime.now()
    # 8 PM EST is 01:00 UTC
    reset_today = datetime.combine(now.date(), time(1, 0))
    if now < reset_today:
        return reset_today - timedelta(days=1)
    return reset_today

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome to the Judgment Free Kitchen! 🍔\nType /snack to eat (1h cooldown).")

async def snack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name or "Chef"
    now = datetime.now()
    last_reset = get_last_reset_time()

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT total_calories, last_snack, daily_calories FROM pf_users WHERE user_id = %s", (user_id,))
    user = cur.fetchone()

    # 1. Cooldown Check
    if user and user[1] and now - user[1] < timedelta(hours=1):
        remaining = timedelta(hours=1) - (now - user[1])
        minutes, seconds = int(remaining.total_seconds() // 60), int(remaining.total_seconds() % 60)
        await update.message.reply_text(f"⌛️ Still digesting. Try again in {minutes}m {seconds}s.")
        cur.close()
        conn.close()
        return

    food_item = random.choice(foods)
    current_total = user[0] if user and user[0] is not None else 0
    current_daily = user[2] if user and user[2] is not None else 0
    
    # 2. Synchronized 8 PM Reset Logic
    if user and user[1] and user[1] < last_reset:
        current_daily = 0

    new_total = current_total + food_item['calories']
    new_daily = current_daily + food_item['calories']
    
    # Check for $PHAT reward text
    phat_reward = food_item.get('reward_phat', 0)
    phat_text = f"\n💰 Reward: {phat_reward:,} $PHAT" if phat_reward > 0 else ""

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
        f"Item: {food_item['name']} ({food_item['calories']:+d} Cal){phat_text}\n"
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
    last_reset = get_last_reset_time()
    conn = get_db_connection()
    cur = conn.cursor()
    # Pulls anyone who snacked SINCE the last 8 PM reset
    cur.execute("""
        SELECT username, daily_calories FROM pf_users 
        WHERE last_snack >= %s 
        AND daily_calories > 0
        ORDER BY daily_calories DESC LIMIT 10
    """, (last_reset,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        await update.message.reply_text("The daily leaderboard is empty since the 8 PM reset! 🍟")
        return

    text = "🔥 TOP MUNCHERS (Since 8PM EST) 🔥\n\n"
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
    await update.message.reply_text("Sweep complete. 🧹 DATABASE WIPED.")

if __name__ == '__main__':
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handlers([
        CommandHandler("start", start),
        CommandHandler("snack", snack),
        CommandHandler("leaderboard", leaderboard),
        CommandHandler("daily", daily),
        CommandHandler("reset_me", reset_me),
        CommandHandler("wipe_everything", wipe_everything)
    ])
    app.run_polling(drop_pending_updates=True)
