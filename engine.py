import time
import random

class BulkinatorEngine:
    def __init__(self, food_data):
        # Filter for calorie-positive items for the game
        self.meals = [f for f in food_data if f.get('calories', 0) > 0]
        self.active_bulks = {}      
        self.SHOUT_VALUE = 0.5      
        self.MAX_SHOUTS_TOTAL = 20  
        self.USER_SHOUT_LIMIT = 3   

    def initialize_session(self, chat_id, target_user_id):
        food = random.choice(self.meals)
        calories = food.get('calories', 500)
        reps_needed = 20 + (calories // 100)
        
        self.active_bulks[chat_id] = {
            "target_id": target_user_id,
            "food": food,
            "reps_needed": reps_needed,
            "reps_current": 0,
            "end_time": time.time() + 30,
            "total_shouts": 0,
            "shouters": {}, 
            "is_active": True
        }
        return self.active_bulks[chat_id]

    def process_action(self, chat_id, user_id, action_type):
        state = self.active_bulks.get(chat_id)
        if not state or not state["is_active"]:
            return "EXPIRED"

        if time.time() > state["end_time"]:
            state["is_active"] = False
            return "BURN"

        if action_type == "rep":
            if user_id != state["target_id"]:
                return "UNAUTHORIZED"
            state["reps_current"] += 1
            if state["reps_current"] >= state["reps_needed"]:
                state["is_active"] = False
                return "SUCCESS"
            return "PROGRESS"

        elif action_type == "shout":
            if user_id == state["target_id"]:
                return "SELF_SHOUT"
            user_shouts = state["shouters"].get(user_id, 0)
            if user_shouts >= self.USER_SHOUT_LIMIT or state["total_shouts"] >= self.MAX_SHOUTS_TOTAL:
                return "LIMIT_REACHED"
            state["total_shouts"] += 1
            state["shouters"][user_id] = user_shouts + 1
            state["end_time"] += self.SHOUT_VALUE
            return "SHOUT_OK"
