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
    # Added daily_calories column for rewards
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
    await update.message.reply_text("Welcome to the Judgment Free Kitchen! 🍔\nNow with 3h cooldowns! Type /snack to eat.")

async def snack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name or "Chef"
    now = datetime.now()

    old_rank = get_user_rank(user_id)

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT total_calories, last_snack, daily_calories FROM pf_users WHERE user_id = %s", (user_id,))
    user = cur.fetchone()

    # 3-Hour Cooldown Logic
    if user and user[1] and now - user[1] < timedelta(hours=3):
        remaining = timedelta(hours=3) - (now - user[1])
        hours = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)
        await update.message.reply_text(f"⌛️ Still digesting. Try again in {hours}h {minutes}m.")
        cur.close()
        conn.close()
        return

    food_item = random.choice(foods)
    
    # Logic to reset daily calories if the last snack was on a different day
    current_total = user[0] if user and user[0] is not None else 0
    current_daily = user[2] if user and user[2] is not None else 0
    
    # If it's a new day, reset their daily count
    if user and user[1] and user[1].date() < now.date():
        current_daily = 0

    new_total = current_total + food_item['calories']
    new_daily = current_daily + food_item['calories']
    
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

    new_rank = get_user_rank(user_id)
    vibe_msg = f"\n🔥 Daily Gain: +{food_item['calories']} Cal"
    if old_rank and new_rank and new_rank < old_rank:
        vibe_msg += f"\n📈 **RANK UP!** You hit #{new_rank} all-time!"

    keyboard = [[InlineKeyboardButton("🎧 Burn it off: Gym Playlist", url=SPOTIFY_URL)]]
    await update.message.reply_text(
        f"Item: {food_item['name']} ({food_item['calories']:+d} Cal)\n"
        f"📈 All-Time: {new_total:,} Cal{vibe_msg}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT username, total_calories FROM pf_users ORDER BY total_calories DESC LIMIT 10")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    text = "🏆 ALL-TIME PHATTEST 🏆\n\n" + "\n".join([f"{i+1}. {r[0]}: {r[1]:,} Cal" for i, r in enumerate(rows)])
    await update.message.reply_text(text if rows else "Kitchen is empty!")

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cur = conn.cursor()
    # Only show users who ate today
    cur.execute("SELECT username, daily_calories FROM pf_users WHERE last_snack::date = CURRENT_DATE ORDER BY daily_calories DESC LIMIT 10")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    text = "🔥 TODAY'S BIGGEST MUNCHERS 🔥\n\n" + "\n".join([f"{i+1}. {r[0]}: {r[1]:,} Cal" for i, r in enumerate(rows)])
    await update.message.reply_text(text if rows else "No one has eaten today!")

async def reset_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE pf_users SET total_calories = 0, daily_calories = 0 WHERE user_id = %s", (update.effective_user.id,))
    conn.commit()
    cur.close()
    conn.close()
    await update.message.reply_text("✅ Calories reset.")

if __name__ == '__main__':
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("snack", snack))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("daily", daily))
    app.add_handler(CommandHandler("reset_me", reset_me))
    app.run_polling(drop_pending_updates=True)
