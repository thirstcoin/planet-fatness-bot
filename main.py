import os, logging, random, json, psycopg2, threading, time
from flask import Flask
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from engine import BulkinatorEngine  # Import our logic

# --- CONFIG & DATA ---
logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("TELEGRAM_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
BURN_AMOUNT = 500

with open('foods.json', 'r') as f:
    foods = json.load(f)

# Initialize Engines
bulkinator = BulkinatorEngine(foods)

# --- DATABASE HELPERS ---
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def update_user_calories(user_id, username, cal_gain):
    """Integrates Bulkinator success into your existing DB stats."""
    conn = get_db_connection()
    cur = conn.cursor()
    now = datetime.now()
    
    cur.execute("SELECT total_calories, daily_calories, last_snack FROM pf_users WHERE user_id = %s", (user_id,))
    user = cur.fetchone()
    
    current_total = user[0] if user else 0
    current_daily = user[1] if user and user[1] else 0
    if user and user[2] and user[2].date() < now.date():
        current_daily = 0

    cur.execute('''
        INSERT INTO pf_users (user_id, username, total_calories, daily_calories, last_snack)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
            username = EXCLUDED.username,
            total_calories = pf_users.total_calories + EXCLUDED.total_calories,
            daily_calories = CASE WHEN pf_users.last_snack < CURRENT_DATE THEN EXCLUDED.daily_calories ELSE pf_users.daily_calories + EXCLUDED.daily_calories END,
            last_snack = EXCLUDED.last_snack
    ''', (user_id, username, cal_gain, cal_gain, now))
    conn.commit()
    cur.close()
    conn.close()

# --- BULKINATOR HANDLERS ---

async def bulk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Triggers the Bulkinator manually or via randomized logic."""
    chat_id = update.effective_chat.id
    user = update.effective_user
    
    session = bulkinator.initialize_session(chat_id, user.id)
    
    text = (
        f"🚨 *BULKINATOR PROTOCOL* 🚨\n\n"
        f"Listen up, @{user.username}!\n"
        f"I've served a *{session['food'].get('tier', 'Rare')}* drop: \n"
        f"👉 **{session['food']['name'].upper()}** ({session['calories']} kcal)\n\n"
        f"Inhale **{session['reps_needed']} reps** in 30s or I burn the supply!"
    )
    
    keyboard = [[InlineKeyboardButton(f"🏋️ EAT (0/{session['reps_needed']})", callback_data="bulk_rep")],
                [InlineKeyboardButton("📣 SHOUT (SPOTTER)", callback_data="bulk_shout")]]
    
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def handle_interactions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    username = query.from_user.username or query.from_user.first_name
    action = "rep" if query.data == "bulk_rep" else "shout"

    result = bulkinator.process_action(chat_id, user_id, action)
    state = bulkinator.active_bulks.get(chat_id)

    if result == "SUCCESS":
        update_user_calories(user_id, username, state['calories'])
        await query.edit_message_text(f"🏆 *GAINS SECURED*\n\n@{username} inhaled the {state['food']['name']}! +{state['calories']} Cal added to stats.")
    
    elif result == "PROGRESS":
        keyboard = [[InlineKeyboardButton(f"🏋️ EAT ({state['reps_current']}/{state['reps_needed']})", callback_data="bulk_rep")],
                    [InlineKeyboardButton("📣 SHOUT (SPOTTER)", callback_data="bulk_shout")]]
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif result == "BURN":
        await query.edit_message_text(f"🔥 *INCINERATION COMMENCED* 🔥\n\nThe plate went cold. I have burned **{BURN_AMOUNT} $PHAT**.")

    elif result == "UNAUTHORIZED":
        await query.answer("❌ Not your plate, skinny!", show_alert=True)
    elif result == "SHOUT_OK":
        await query.answer("📣 SPOTTER: +0.5s added!")
    elif result == "LIMIT_REACHED":
        await query.answer("🔇 Out of breath!")

# --- (KEEP YOUR EXISTING SNACK/LEADERBOARD HANDLERS BELOW) ---
# [Insert your existing start, snack, leaderboard, daily functions here]

if __name__ == '__main__':
    # init_db() call here...
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("bulk", bulk))
    app.add_handler(CallbackQueryHandler(handle_interactions, pattern="^bulk_"))
    # Add your existing handlers...
    app.run_polling(drop_pending_updates=True)
