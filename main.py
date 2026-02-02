import os, logging, random, json, psycopg2, threading, time
from flask import Flask
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from engine import BulkinatorEngine

# --- CONFIG & DATA ---
logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("TELEGRAM_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
BURN_AMOUNT = 500  # The $PHAT stake

with open('foods.json', 'r') as f:
    foods = json.load(f)

# Initialize Logic Engine
bulkinator = BulkinatorEngine(foods)

# --- DATABASE HELPERS ---
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def update_user_calories(user_id, username, cal_gain):
    """Saves the massive gains to your PostgreSQL leaderboard."""
    conn = get_db_connection()
    cur = conn.cursor()
    now = datetime.now()
    
    cur.execute('''
        INSERT INTO pf_users (user_id, username, total_calories, daily_calories, last_snack)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
            username = EXCLUDED.username,
            total_calories = pf_users.total_calories + EXCLUDED.total_calories,
            daily_calories = CASE 
                WHEN pf_users.last_snack < CURRENT_DATE THEN EXCLUDED.daily_calories 
                ELSE pf_users.daily_calories + EXCLUDED.daily_calories 
            END,
            last_snack = EXCLUDED.last_snack
    ''', (user_id, username, cal_gain, cal_gain, now))
    conn.commit()
    cur.close()
    conn.close()

# --- BULKINATOR LOGIC ---

async def bulk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """The manual command for testing or admin-triggered events."""
    chat_id = update.effective_chat.id
    user = update.effective_user
    await start_bulkinator_session(chat_id, user.id, user.username, context)

async def start_bulkinator_session(chat_id, user_id, username, context):
    """The core session launcher for both manual and random events."""
    session = bulkinator.initialize_session(chat_id, user_id)
    cals = session['food'].get('calories', 0)
    
    # 🚨 BOSS BATTLE POLISH: Items over 3000 cals trigger the Siren
    is_boss = cals >= 3000
    header = "🚨🚨 **BOSS BATTLE** 🚨🚨" if is_boss else "🚨 **BULKINATOR PROTOCOL** 🚨"
    siren = "🔊 *WEE-OOO WEE-OOO WEE-OOO*\n" if is_boss else ""
    
    text = (
        f"{header}\n{siren}\n"
        f"Listen up, @{username}!\n"
        f"I've served a *{session['food'].get('tier', 'Rare')}* drop: \n"
        f"👉 **{session['food']['name'].upper()}** ({cals} kcal)\n\n"
        f"Inhale **{session['reps_needed']} reps** in 30s or I burn the supply!"
    )
    
    keyboard = [[InlineKeyboardButton(f"🏋️ EAT (0/{session['reps_needed']})", callback_data="bulk_rep")],
                [InlineKeyboardButton("📣 SHOUT (SPOTTER)", callback_data="bulk_shout")]]
    
    msg = await context.bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    
    # Force a notification to everyone if it's a Boss Fight
    if is_boss:
        try:
            await context.bot.pin_chat_message(chat_id, msg.message_id, disable_notification=False)
        except:
            pass # Fails gracefully if bot isn't admin

async def handle_interactions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the high-intensity clicking and spotting."""
    query = update.callback_query
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    username = query.from_user.username or query.from_user.first_name
    action = "rep" if query.data == "bulk_rep" else "shout"

    result = bulkinator.process_action(chat_id, user_id, action)
    state = bulkinator.active_bulks.get(chat_id)

    if result == "SUCCESS":
        update_user_calories(user_id, username, state['food']['calories'])
        await query.edit_message_text(f"🏆 *GAINS SECURED*\n\n@{username} inhaled the {state['food']['name']}! +{state['food']['calories']} Cal added.")
    
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

# --- AUTOMATION: THE RANDOM HUNT ---

async def passive_hunt_callback(context: ContextTypes.DEFAULT_TYPE):
    """This function runs in the background and 'hunts' users."""
    # Note: Replace with your actual group's Chat ID or fetch from DB
    target_chat_id = os.getenv("GROUP_CHAT_ID") 
    if not target_chat_id:
        return

    conn = get_db_connection()
    cur = conn.cursor()
    # Find a user who has eaten in the last 24 hours
    cur.execute("SELECT user_id, username FROM pf_users WHERE last_snack >= NOW() - INTERVAL '24 hours'")
    active_users = cur.fetchall()
    cur.close()
    conn.close()

    if active_users:
        victim_id, victim_name = random.choice(active_users)
        await start_bulkinator_session(target_chat_id, victim_id, victim_name, context)

# --- MAIN BOOT ---

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Background Job: Triggers every 2 to 4 hours randomly
    job_queue = app.job_queue
    job_queue.run_repeating(passive_hunt_callback, interval=random.randint(7200, 14400), first=10)

    # Command Handlers
    app.add_handler(CommandHandler("bulk", bulk))
    app.add_handler(CallbackQueryHandler(handle_interactions, pattern="^bulk_"))
    
    # (Insert your existing snack/leaderboard handlers here)
    
    print("Bulkinator is live and hunting...")
    app.run_polling(drop_pending_updates=True)
