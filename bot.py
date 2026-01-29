import os
import json
import random
import psycopg2
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# These will be pulled from Render Environment Variables
DATABASE_URL = os.environ.get('DATABASE_URL')
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')

def init_db():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    # Using 'pf_users' prefix to keep your other data safe
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

async def snack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    now = datetime.now()
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    
    cur.execute("SELECT last_snack, total_calories FROM pf_users WHERE user_id = %s", (user.id,))
    row = cur.fetchone()

    # 24-hour cooldown check
    if row and row[0] and (now - row[0]) < timedelta(hours=24):
        time_left = timedelta(hours=24) - (now - row[0])
        await update.message.reply_text(f"⏳ Still digesting. Try again in {time_left.seconds // 3600} hours.")
        return

    with open('foods.json', 'r') as f:
        foods = json.load(f)
    
    item = random.choice(foods)
    cals = item['calories']
    new_total = (row[1] if row else 0) + cals

    cur.execute('''
        INSERT INTO pf_users (user_id, username, total_calories, last_snack)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
        username = EXCLUDED.username,
        total_calories = pf_users.total_calories + EXCLUDED.total_calories,
        last_snack = EXCLUDED.last_snack
    ''', (user.id, user.username, cals, now))
    conn.commit()
    
    cur.execute("SELECT COUNT(*) FROM pf_users WHERE total_calories > %s", (new_total,))
    rank = cur.fetchone()[0] + 1

    await update.message.reply_text(
        f"🍕 **SNACK HIT**\n@{user.username} ate: **{item['name']}**\n"
        f"📈 **{'+' if cals >= 0 else ''}{cals:,} kcal**\n\n"
        f"🧮 Total: {new_total:,} kcal | Rank: #{rank}",
        parse_mode='Markdown'
    )
    cur.close()
    conn.close()

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    cur.execute("SELECT username, total_calories FROM pf_users ORDER BY total_calories DESC LIMIT 10")
    rows = cur.fetchall()
    text = "🏆 **THE PHATTEST** 🏆\n\n" + "\n".join([f"{i+1}. @{r[0]}: {r[1]:,} kcal" for i, r in enumerate(rows)])
    await update.message.reply_text(text, parse_mode='Markdown')
    cur.close()
    conn.close()

if __name__ == '__main__':
    init_db()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("snack", snack))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.run_polling()
