import os
import logging
import random
import json
import psycopg2
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# Setup basic logging
logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("TELEGRAM_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# Load your 150+ food items
with open('foods.json', 'r') as f:
    foods = json.load(f)

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

# Create table if it doesn't exist
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS pf_users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            total_calories INTEGER DEFAULT 0,
            last_snack TIMESTAMP
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()

init_db()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome to Judgment Free Kitchen! Use /snack to eat or /leaderboard to see the ranks.")

async def snack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Fallback to First Name if no @username is set
    username = update.effective_user.username or update.effective_user.first_name
    now = datetime.now()

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT total_calories, last_snack FROM pf_users WHERE user_id = %s", (user_id,))
    user = cur.fetchone()

    # Cooldown Logic
    if user and user[1] and now - user[1] < timedelta(hours=24):
        remaining = timedelta(hours=24) - (now - user[1])
        hours = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)
        await update.message.reply_text(f"⏳ Still digesting. Try again in {hours}h {minutes}m.")
        cur.close()
        conn.close()
        return

    # Pick food
    food_item = random.choice(foods)
    new_total = (user[0] if user else 0) + food_item['calories']

    # Update Database
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

    # Plain text output to prevent "Entity Parsing" errors
    response = (
        f"🍔 You ate: {food_item['name']}\n"
        f"🔥 Calories: +{food_item['calories']}\n"
        f"📈 Your Total: {new_total:,} kcal"
    )
    await update.message.reply_text(response)

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT total_calories FROM pf_users WHERE user_id = %s", (user_id,))
    result = cur.fetchone()
    cur.close()
    conn.close()

    if result:
        await update.message.reply_text(f"📊 Your Total Calories: {result[0]:,} kcal")
    else:
        await update.message.reply_text("You haven't eaten anything yet! Type /snack.")

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
        name = r[0] if r[0] else "Anonymous"
        text += f"{i+1}. {name}: {r[1]:,} kcal\n"
    
    await update.message.reply_text(text)

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("snack", snack))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.run_polling()
