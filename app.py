from flask import Flask, render_template, jsonify, request, session
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from bson.objectid import ObjectId
import random
import time

app = Flask(__name__)
app.secret_key = "multiplayer_777_super_secret_key_2026"
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

MONGO_URI = "mongodb+srv://vgugan16:gugan2004@cluster0.qyh1fuo.mongodb.net/casino?retryWrites=true&w=majority"
client = MongoClient(MONGO_URI)
db = client["lucky777"]
users_col = db["users"]
queue_col = db["match_queue"]

SYMBOLS = ['7️⃣', '💎', '🔔', '🍒', '🍋', '🍇']
PAYOUTS = {'7️⃣': 100, '💎': 50, '🔔': 30, '🍒': 20, '🍋': 10, '🍇': 5}
MAX_ROUNDS = 10  # 5 rounds each player (10 total spins)
SPIN_TIMEOUT = 30  # 30 seconds per spin

def get_current_user():
    if "user_id" not in session: return None
    try:
        return users_col.find_one({"_id": ObjectId(session["user_id"])})
    except: return None

@app.route('/')
def index(): return render_template('index.html')

# ================= AUTH (UNCHANGED) =================
@app.route('/api/auth/signup', methods=['POST'])
def signup():
    data = request.json
    if users_col.find_one({"username": data["username"]}): 
        return jsonify({"error": "Username taken"}), 400
    user_id = users_col.insert_one({
        "username": data["username"],
        "password": generate_password_hash(data["password"]),
        "balance": 1000
    }).inserted_id
    session["user_id"] = str(user_id)
    return jsonify({"user": {"username": data["username"], "balance": 1000}})

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    user = users_col.find_one({"username": data["username"]})
    if user and check_password_hash(user["password"], data["password"]):
        session["user_id"] = str(user["_id"])
        return jsonify({"user": {"username": user["username"], "balance": user.get("balance", 1000)}})
    return jsonify({"error": "Invalid login"}), 401

@app.route('/api/auth/check', methods=['GET'])
def auth_check():
    user = get_current_user()
    return jsonify({
        "logged_in": bool(user),
        "user": {"username": user["username"], "balance": user.get("balance", 0)} if user else {}
    })

@app.route('/api/auth/logout', methods=['POST'])
def logout(): 
    session.clear()
    return jsonify({"success": True})

# ================= QUEUE - ONLY 2 PLAYERS ✅ =================
@app.route('/api/match/join', methods=['POST'])
def join_match():
    user = get_current_user()
    if not user: return jsonify({"error": "Unauthorized"}), 401
    
    uid = str(user["_id"])
    
    # Clean expired queue entries
    queue_col.delete_many({"type": "waiting", "timestamp": {"$lt": time.time() - 60}})
    
    # Check if already in game or waiting
    if queue_col.find_one({"$or": [{"p1": uid}, {"p2": uid}, {"type": "waiting", "user_id": uid}]}):
        return jsonify({"error": "Already in game or queue"})
    
    # Check if game ongoing (only 2 players allowed)
    active_game = queue_col.find_one({"_id": "m1", "status": "active"})
    if active_game:
        return jsonify({"error": "Game in progress. Wait for next game."})
    
    # Add to waiting queue
    queue_col.delete_one({"type": "waiting", "user_id": uid})  # Remove old entry
    queue_col.insert_one({
        "type": "waiting",
        "user_id": uid,
        "username": user["username"],
        "timestamp": time.time()
    })
    
    # Check for opponent
    opponent = queue_col.find_one({"type": "waiting", "user_id": {"$ne": uid}})
    if opponent:
        # 🏆 CREATE NEW GAME - EXACTLY 2 PLAYERS
        match_data = {
            "_id": "m1",
            "type": "match",
            "p1": opponent["user_id"], "p1_name": opponent["username"],
            "p2": uid, "p2_name": user["username"],
            "p1_score": 0, "p2_score": 0,
            "current_round": 1,  # 🆕 Round tracking
            "current_spin": 1,   # 🆕 Spin tracking (1-10)
            "turn": "p1",        # 🆕 Current turn
            "status": "active",
            "spins": [],
            "last_spin": None,
            "spin_start_time": None,  # 🆕 30s timeout
            "created_at": time.time()
        }
        queue_col.replace_one({"_id": "m1"}, match_data, upsert=True)
        queue_col.delete_one({"_id": opponent["_id"]})
        print(f"🎮 NEW GAME: {opponent['username']} vs {user['username']}")
        return jsonify({"status": "match_found"})
    
    return jsonify({"status": "waiting"})

# ================= GAME STATUS - 10 ROUNDS ✅ =================
@app.route('/api/game/status', methods=['GET'])
def game_status():
    user = get_current_user()
    if not user: return jsonify({"error": "Unauthorized"}), 401
    
    match = queue_col.find_one({"_id": "m1", "type": "match"})
    if not match:
        return jsonify({"in_match": False, "status": "waiting"})
    
    is_p1 = str(user["_id"]) == match["p1"]
    
    # 🆕 TIMEOUT CHECK
    timeout_penalty = False
    if match.get("spin_start_time") and time.time() - match["spin_start_time"] > SPIN_TIMEOUT:
        timeout_penalty = True
        print(f"⏰ TIMEOUT! {match['turn'].upper()} missed turn")
    
    return jsonify({
        "in_match": True,
        "status": match["status"],
        "round": match.get("current_round", 1),
        "spin": match.get("current_spin", 1),
        "is_my_turn": match["turn"] == ("p1" if is_p1 else "p2"),
        "timeout_penalty": timeout_penalty,
        "time_left": max(0, SPIN_TIMEOUT - (time.time() - match.get("spin_start_time", 0))),
        "my_score": match.get("p1_score", 0) if is_p1 else match.get("p2_score", 0),
        "opp_score": match.get("p2_score", 0) if is_p1 else match.get("p1_score", 0),
        "opp_name": match.get("p2_name", "Unknown") if is_p1 else match.get("p1_name", "Unknown"),
        "history": match.get("spins", []),
        "last_spin": match.get("last_spin", None),
        "winner": match.get("winner")
    })

# ================= SPIN - 30s TIMEOUT + ROUNDS ✅ =================
@app.route('/api/game/spin', methods=['POST'])
def game_spin():
    user = get_current_user()
    if not user: return jsonify({"error": "Unauthorized"}), 401
    
    match = queue_col.find_one({"_id": "m1", "type": "match", "status": "active"})
    if not match: return jsonify({"error": "No active game"}), 400
    
    is_p1 = str(user["_id"]) == match["p1"]
    role = "p1" if is_p1 else "p2"
    
    # 🆕 TIMEOUT CHECK
    if match.get("spin_start_time") and time.time() - match["spin_start_time"] > SPIN_TIMEOUT:
        return jsonify({"error": "Time expired! -1 points", "points": -1})
    
    if match["turn"] != role:
        return jsonify({"error": "Not your turn"}), 400
    
    # 🆕 Generate spin with timeout check
    spin_time_left = SPIN_TIMEOUT - (time.time() - match.get("spin_start_time", time.time()))
    if spin_time_left <= 0:
        points = -1  # Penalty
        reels = ["⏰", "⏰", "⏰"]
    else:
        reels = [random.choice(SYMBOLS) for _ in range(3)]
        points = PAYOUTS[reels[0]] if reels[0] == reels[1] == reels[2] else (10 if len(set(reels)) == 2 else 0)
    
    spin_record = {
        "player": user["username"],
        "role": role,
        "reels": reels,
        "points": points,
        "round": match.get("current_round", 1),
        "spin_num": match.get("current_spin", 1),
        "timestamp": time.time()
    }
    
    # 🆕 UPDATE GAME STATE
    next_turn = "p2" if role == "p1" else "p1"
    next_spin = match.get("current_spin", 1) + 1
    
    # 🆕 ROUND LOGIC: 10 total spins (5 each)
    update_data = {
        "$inc": {f"{role}_score": points},
        "$push": {"spins": spin_record},
        "$set": { 
            "last_spin": reels,
            "turn": next_turn,
            "spin_start_time": time.time()  # 🆕 Reset 30s timer
        }
    }
    
    # 🆕 Next round logic
    if next_spin > MAX_ROUNDS:
        update_data["$set"]["current_round"] = match.get("current_round", 1) + 1
        update_data["$set"]["current_spin"] = 1
        update_data["$set"]["turn"] = "p1"  # Round starts with p1
    else:
        update_data["$set"]["current_spin"] = next_spin
    
    queue_col.update_one({"_id": "m1"}, update_data)
    
    # 🆕 GAME END: After 10 rounds (20 total spins)
    updated_match = queue_col.find_one({"_id": "m1"})
    if updated_match.get("current_round", 1) > MAX_ROUNDS:
        p1_score = updated_match.get("p1_score", 0)
        p2_score = updated_match.get("p2_score", 0)
        if p1_score > p2_score:
            winner = updated_match.get("p1_name")
            users_col.update_one({"_id": ObjectId(updated_match["p1"])}, {"$inc": {"balance": 200}})
        elif p2_score > p1_score:
            winner = updated_match.get("p2_name")
            users_col.update_one({"_id": ObjectId(updated_match["p2"])}, {"$inc": {"balance": 200}})
        else:
            winner = "Draw"
        queue_col.update_one({"_id": "m1"}, {"$set": {"status": "finished", "winner": winner}})
    
    return jsonify({"reels": reels, "points": points, "round": match.get("current_round", 1)})

@app.route('/api/leaderboard')
def leaderboard():
    return jsonify([{"u": u["username"], "b": u.get("balance", 0)} for u in users_col.find().sort("balance", -1).limit(5)])

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)
