import os
import logging
import random
import json
import psycopg2
import threading
from flask import Flask
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# --- DUMMY WEB SERVER ---
flask_app = Flask(__name__)
@flask_app.route('/')
def home():
    return "Kitchen is Open!"

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
    await update.message.reply_text("Welcome to the Judgment Free Kitchen! 🍔 Type /snack to eat.")

async def snack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Apostrophe safe name handling
    username = update.effective_user.username or update.effective_user.first_name or "Chef"
    now = datetime.now()

    conn = get_db_connection()
    cur = conn.cursor()
    
    # Safe check for user
    cur.execute("SELECT total_calories, last_snack FROM pf_users WHERE user_id = %s", (user_id,))
    user = cur.fetchone()

    if user and user[1] and now - user[1] < timedelta(hours=24):
        remaining = timedelta(hours=24) - (now - user[1])
        hours = int(remaining.total_seconds() // 3600)
        await update.message.reply_text(f"⏳ Still digesting. Try again in {hours} hours.")
        cur.close()
        conn.close()
        return

    food_item = random.choice(foods)
    current_calories = user[0] if user and user[0] is not None else 0
    new_total = current_calories + food_item['calories']
    
    # PARAMETERIZED QUERY: This is the specific fix for the ' in his name
    sql = '''
        INSERT INTO pf_users (user_id, username, total_calories, last_snack)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
            username = EXCLUDED.username,
            total_calories = EXCLUDED.total_calories,
            last_snack = EXCLUDED.last_snack
    '''
    cur.execute(sql, (user_id, username, new_total, now))
    
    conn.commit()
    cur.close()
    conn.close()
    
    await update.message.reply_text(f"🍔 {food_item['name']} (+{food_item['calories']} kcal)\n📈 Total: {new_total:,} kcal")

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT username, total_calories FROM pf_users ORDER BY total_calories DESC LIMIT 10")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    
    if not rows:
        await update.message.reply_text("The kitchen is empty!")
        return
    
    text = "🏆 THE PHATTEST 🏆\n\n"
    for i, r in enumerate(rows):
        # Plain text name to prevent Markdown parsing errors
        text += f"{i+1}. {r[0]}: {r[1]:,} kcal\n"
    await update.message.reply_text(text)

if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("snack", snack))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.run_polling()
