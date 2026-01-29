import os, logging, random, json, psycopg2, threading
from flask import Flask
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- DUMMY WEB SERVER ---
flask_app = Flask(__name__)
@flask_app.route('/')
def home(): return "Kitchen is Open!"

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome to the Judgment Free Kitchen! Type /snack to eat.")

async def snack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Parameterized to handle apostrophes in names
    username = update.effective_user.username or update.effective_user.first_name or "Chef"
    now = datetime.now()

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT total_calories, last_snack FROM pf_users WHERE user_id = %s", (user_id,))
    user = cur.fetchone()

    if user and user[1] and now - user[1] < timedelta(hours=24):
        remaining = timedelta(hours=24) - (now - user[1])
        hours = int(remaining.total_seconds() // 3600)
        # ⌛️ Emoji restored for digestion message
        await update.message.reply_text(f"⌛️ Still digesting. Try again in {hours} hours.")
        cur.close()
        conn.close()
        return

    food_item = random.choice(foods)
    current_calories = user[0] if user and user[0] is not None else 0
    new_total = current_calories + food_item['calories']
    
    cur.execute('''
        INSERT INTO pf_users (user_id, username, total_calories, last_snack)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
            username = EXCLUDED.username,
            total_calories = EXCLUDED.total_calories,
            last_snack = EXCLUDED.last_snack
    ''', (user_id, username, new_total, now))
    
    conn.commit()
    cur.close()
    conn.close()

    # Cheeseburger removed. 📈 Emoji restored for progress
    await update.message.reply_text(
        f"Item: {food_item['name']} ({food_item['calories']:+d} kcal)\n"
        f"📈 Total: {new_total:,} kcal"
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
    # 🏆 Emojis restored for the leaderboard title
    text = "🏆 THE PHATTEST 🏆\n\n"
    for i, r in enumerate(rows):
        text += f"{i+1}. {r[0]}: {r[1]:,} kcal\n"
    await update.message.reply_text(text)

# OWNER ONLY: Reset command to fix scores
async def reset_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE pf_users SET total_calories = 0 WHERE user_id = %s", (user_id,))
    conn.commit()
    cur.close()
    conn.close()
    await update.message.reply_text("✅ Calories reset to 0.")

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("snack", snack))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("reset_me", reset_me))
    # Clears old messages and helps resolve conflicts on startup
    app.run_polling(drop_pending_updates=True)
