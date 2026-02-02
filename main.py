import os, logging, random, json, psycopg2, threading, time
from flask import Flask
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from engine import BulkinatorEngine

# --- DUMMY WEB SERVER ---
flask_app = Flask(__name__)
@flask_app.route('/')
def home(): return "Kitchen & Gym are Open!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host='0.0.0.0', port=port)

# --- CONFIG & DATA ---
logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("TELEGRAM_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
BURN_AMOUNT = 500 

with open('foods.json', 'r') as f:
    foods = json.load(f)

bulkinator = BulkinatorEngine(foods)

# --- DATABASE HELPERS ---
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("ALTER TABLE pf_users ADD COLUMN IF NOT EXISTS last_rank INTEGER;")
    cur.execute("ALTER TABLE pf_users ADD COLUMN IF NOT EXISTS daily_calories INTEGER DEFAULT 0;")
    conn.commit()
    cur.close()
    conn.close()

def update_user_calories(user_id, username, cal_gain):
    """Unified helper for Snack and Bulkinator gains."""
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
        RETURNING total_calories, daily_calories;
    ''', (user_id, username, cal_gain, cal_gain, now))
    
    res = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return res

# --- BULKINATOR LOGIC ---

async def bulk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    await start_bulkinator_session(chat_id, user.id, user.username, context)

async def start_bulkinator_session(chat_id, user_id, username, context):
    session = bulkinator.initialize_session(chat_id, user_id)
    cals = session['food'].get('calories', 0)
    is_boss = cals >= 3000
    
    header = "🚨🚨 **BOSS BATTLE** 🚨🚨" if is_boss else "🚨 **BULKINATOR PROTOCOL** 🚨"
    text = (
        f"{header}\n\n@{username}, the Bulkinator has served: \n"
        f"👉 **{session['food']['name'].upper()}** ({cals} kcal)\n\n"
        f"Inhale **{session['reps_needed']} reps** in 30s or I burn the supply!"
    )
    
    keyboard = [[InlineKeyboardButton(f"🏋️ EAT (0/{session['reps_needed']})", callback_data="bulk_rep")],
                [InlineKeyboardButton("📣 SHOUT (SPOTTER)", callback_data="bulk_shout")]]
    
    msg = await context.bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    if is_boss:
        try: await context.bot.pin_chat_message(chat_id, msg.message_id)
        except: pass

async def handle_interactions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    result = bulkinator.process_action(query.message.chat_id, query.from_user.id, "rep" if query.data == "bulk_rep" else "shout")
    state = bulkinator.active_bulks.get(query.message.chat_id)

    if result == "SUCCESS":
        totals = update_user_calories(query.from_user.id, query.from_user.username, state['food']['calories'])
        await query.edit_message_text(f"🏆 *GAINS SECURED*\n\n@{query.from_user.username} inhaled the {state['food']['name']}!\n📈 All-Time: {totals[0]:,} Cal")
    elif result == "PROGRESS":
        keyboard = [[InlineKeyboardButton(f"🏋️ EAT ({state['reps_current']}/{state['reps_needed']})", callback_data="bulk_rep")],
                    [InlineKeyboardButton("📣 SHOUT (SPOTTER)", callback_data="bulk_shout")]]
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
    elif result == "BURN":
        await query.edit_message_text(f"🔥 *INCINERATION COMMENCED*\n\nThe plate went cold. {BURN_AMOUNT} $PHAT burned.")
    elif result == "UNAUTHORIZED":
        await query.answer("❌ Not your plate, skinny!", show_alert=True)

# --- SNACK & UTILITY HANDLERS ---

async def snack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name
    now = datetime.now()

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT last_snack FROM pf_users WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    
    if row and row[0] and now - row[0] < timedelta(hours=1):
        remaining = timedelta(hours=1) - (now - row[0])
        await update.message.reply_text(f"⌛️ Digesting. Try in {int(remaining.total_seconds()//60)}m.")
        return

    food_item = random.choice(foods)
    totals = update_user_calories(user_id, username, food_item['calories'])
    
    await update.message.reply_text(
        f"🍪 Snack: {food_item['name']} ({food_item['calories']:+d} Cal)\n"
        f"📈 All-Time: {totals[0]:,} | 🔥 Daily: {totals[1]:,}"
    )

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT username, total_calories FROM pf_users ORDER BY total_calories DESC LIMIT 10")
    rows = cur.fetchall()
    text = "🏆 ALL-TIME PHATTEST 🏆\n\n" + "\n".join([f"{i+1}. {r[0]}: {r[1]:,} Cal" for i, r in enumerate(rows)])
    await update.message.reply_text(text)

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT username, daily_calories FROM pf_users WHERE last_snack >= NOW() - INTERVAL '24 hours' ORDER BY daily_calories DESC LIMIT 10")
    rows = cur.fetchall()
    text = "🔥 24H TOP MUNCHERS 🔥\n\n" + "\n".join([f"{i+1}. {r[0]}: {r[1]:,} Cal" for i, r in enumerate(rows)])
    await update.message.reply_text(text)

# --- AUTOMATION ---
async def passive_hunt_callback(context: ContextTypes.DEFAULT_TYPE):
    target_chat_id = os.getenv("GROUP_CHAT_ID")
    if not target_chat_id: return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id, username FROM pf_users WHERE last_snack >= NOW() - INTERVAL '24 hours'")
    active_users = cur.fetchall()
    if active_users:
        victim = random.choice(active_users)
        await start_bulkinator_session(target_chat_id, victim[0], victim[1], context)

if __name__ == '__main__':
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()
    app = ApplicationBuilder().token(TOKEN).build()
    
    # Automation: Hunt every 2-4 hours
    app.job_queue.run_repeating(passive_hunt_callback, interval=random.randint(7200, 14400), first=10)

    app.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("Kitchen is Open!")))
    app.add_handler(CommandHandler("snack", snack))
    app.add_handler(CommandHandler("bulk", bulk))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("daily", daily))
    app.add_handler(CallbackQueryHandler(handle_interactions, pattern="^bulk_"))
    
    app.run_polling(drop_pending_updates=True)
