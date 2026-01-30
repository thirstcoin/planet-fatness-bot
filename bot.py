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

# New: This adds the necessary 'last_rank' column to your DB without touching your data
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("ALTER TABLE pf_users ADD COLUMN IF NOT EXISTS last_rank INTEGER;")
    conn.commit()
    cur.close()
    conn.close()

# New: Helper for the Vibe Bot chatter
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
    await update.message.reply_text("Welcome to the Judgment Free Kitchen! Type /snack to eat.")

async def snack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name or "Chef"
    now = datetime.now()

    # Track rank BEFORE eating
    old_rank = get_user_rank(user_id)

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT total_calories, last_snack FROM pf_users WHERE user_id = %s", (user_id,))
    user = cur.fetchone()

    # UPDATED: 6 Hour Cooldown (instead of 24)
    if user and user[1] and now - user[1] < timedelta(hours=6):
        remaining = timedelta(hours=6) - (now - user[1])
        hours = int(remaining.total_seconds() // 3600)
        minutes = int((remaining.total_seconds() % 3600) // 60)
        await update.message.reply_text(f"⌛️ Still digesting. Try again in {hours}h {minutes}m.")
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

    # Check rank AFTER eating
    new_rank = get_user_rank(user_id)
    vibe_msg = ""
    if old_rank and new_rank and new_rank < old_rank:
        vibe_msg = f"\n\n📈 **RANK UP!** You just snatched the #{new_rank} spot!"

    # Spotify Button Integration
    keyboard = [[InlineKeyboardButton("🎧 Burn it off: Gym Playlist", url=SPOTIFY_URL)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"Item: {food_item['name']} ({food_item['calories']:+d} kcal)\n"
        f"📈 Total: {new_total:,} kcal{vibe_msg}",
        reply_markup=reply_markup
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
    text = "🏆 THE PHATTEST 🏆\n\n"
    for i, r in enumerate(rows):
        text += f"{i+1}. {r[0]}: {r[1]:,} kcal\n"
    await update.message.reply_text(text)

# Security: Reset Me works for anyone's own score
async def reset_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE pf_users SET total_calories = 0 WHERE user_id = %s", (user_id,))
    conn.commit()
    cur.close()
    conn.close()
    await update.message.reply_text("✅ Your calories have been reset to 0.")

# Security: Admin Wipe works ONLY for your username
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
    await update.message.reply_text("🧹 DATABASE WIPED. The kitchen is fresh for launch!")

if __name__ == '__main__':
    init_db() # Added to prepare database safely
    threading.Thread(target=run_flask, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("snack", snack))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("reset_me", reset_me))
    app.add_handler(CommandHandler("wipe_everything", wipe_everything)) # Added handler
    app.run_polling(drop_pending_updates=True)
