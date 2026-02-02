import time
import random

class BulkinatorEngine:
    def __init__(self, food_data):
        # Filter for calorie-positive items for the game
        self.meals = [f for f in food_data if f.get('calories', 0) > 0]
        self.active_bulks = {}      
        self.SHOUT_VALUE = 0.5      # Seconds added per shout
        self.MAX_SHOUTS_TOTAL = 20  # Max total shouts per session
        self.USER_SHOUT_LIMIT = 3   # Max shouts per individual spotter

    def initialize_session(self, chat_id, target_user_id):
        """Starts a new high-stakes ambush."""
        food = random.choice(self.meals)
        calories = food.get('calories', 500)
        
        # Scaling difficulty based on calorie count
        reps_needed = 20 + (calories // 100)
        
        self.active_bulks[chat_id] = {
            "target_id": target_user_id,
            "food": food,
            "reps_needed": reps_needed,
            "reps_current": 0,
            "start_time": time.time(),
            "end_time": time.time() + 30,
            "total_shouts": 0,
            "shouters": {}, 
            "is_active": True
        }
        return self.active_bulks[chat_id]

    def get_progress_pct(self, chat_id):
        """Helper to return the current percentage for the progress bar."""
        state = self.active_bulks.get(chat_id)
        if not state:
            return 0
        return min(100, int((state["reps_current"] / state["reps_needed"]) * 100))

    def process_action(self, chat_id, user_id, action_type):
        """Handles the 'Eat' and 'Shout' logic."""
        state = self.active_bulks.get(chat_id)
        
        if not state or not state["is_active"]:
            return "EXPIRED"

        # Check if the timer has run out before processing
        if time.time() > state["end_time"]:
            state["is_active"] = False
            return "BURN"

        if action_type == "rep":
            # Only the targeted user can eat
            if user_id != state["target_id"]:
                return "UNAUTHORIZED"
            
            state["reps_current"] += 1
            
            if state["reps_current"] >= state["reps_needed"]:
                state["is_active"] = False
                return "SUCCESS"
            return "PROGRESS"

        elif action_type == "shout":
            # Target cannot shout for themselves
            if user_id == state["target_id"]:
                return "SELF_SHOUT"
                
            user_shouts = state["shouters"].get(user_id, 0)
            
            # Enforcement of shout limits to keep it balanced
            if user_shouts >= self.USER_SHOUT_LIMIT or state["total_shouts"] >= self.MAX_SHOUTS_TOTAL:
                return "LIMIT_REACHED"
            
            state["total_shouts"] += 1
            state["shouters"][user_id] = user_shouts + 1
            
            # Extension of the countdown timer
            state["end_time"] += self.SHOUT_VALUE
            return "SHOUT_OK"

    def cleanup_expired(self):
        """Housekeeping: Removes sessions that are long dead."""
        now = time.time()
        expired_chats = [cid for cid, s in self.active_bulks.items() if now > s["end_time"] + 60]
        for cid in expired_chats:
            del self.active_bulks[cid]
