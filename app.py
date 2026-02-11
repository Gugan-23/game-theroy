from flask import Flask, render_template, jsonify, request, session
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from bson.objectid import ObjectId
import random
import time
from datetime import timedelta

app = Flask(__name__)
app.secret_key = "multiplayer_777_super_secret_key_2026" # Keep this consistent

# ================= SESSION CONFIG =================
app.config['SESSION_COOKIE_NAME'] = 'lucky777_session'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7) # Session lasts 7 days
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False # Set to True if using HTTPS

# ================= MONGODB SETUP =================
MONGO_URI = "mongodb+srv://vgugan16:gugan2004@cluster0.qyh1fuo.mongodb.net/casino?retryWrites=true&w=majority"
client = MongoClient(MONGO_URI)
db = client["lucky777"]
users_col = db["users"]
queue_col = db["match_queue"]
matches_col = db["matches"]

# ================= GAME CONFIG =================
SYMBOLS = ['7️⃣', '💎', '🔔', '🍒', '🍋', '🍇']
PAYOUTS = {'7️⃣': 100, '💎': 50, '🔔': 30, '🍒': 20, '🍋': 10, '🍇': 5}
SPIN_COST = 10 # Added a small cost for single player to make it a "game"

def get_current_user():
    if "user_id" in session:
        try:
            return users_col.find_one({"_id": ObjectId(session["user_id"])})
        except:
            return None
    return None

@app.route('/')
def index():
    return render_template('index.html')

# ================= AUTH =================
@app.route('/api/auth/signup', methods=['POST'])
def signup():
    data = request.json
    if users_col.find_one({"username": data["username"]}):
        return jsonify({"error": "Username taken"}), 400
    users_col.insert_one({
        "username": data["username"],
        "password": generate_password_hash(data["password"]),
        "balance": 1000
    })
    return jsonify({"message": "Success"})

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    user = users_col.find_one({"username": data["username"]})
    if user and check_password_hash(user["password"], data["password"]):
        session.permanent = True # This makes the session last across browser restarts/refreshes
        session["user_id"] = str(user["_id"])
        return jsonify({"user": {"username": user["username"], "balance": user["balance"]}})
    return jsonify({"error": "Invalid login"}), 401

@app.route('/api/auth/check', methods=['GET'])
def check_session():
    user = get_current_user()
    if user:
        return jsonify({
            "logged_in": True,
            "user": {"username": user["username"], "balance": user["balance"]}
        })
    return jsonify({"logged_in": False})

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"success": True})

# ================= SINGLE PLAYER =================
@app.route('/api/game/spin', methods=['POST'])
def spin():
    user = get_current_user()
    if not user or user["balance"] < SPIN_COST:
        return jsonify({"error": "Insufficient funds"}), 400

    reels = [random.choice(SYMBOLS) for _ in range(3)]
    reward = 0
    if reels[0] == reels[1] == reels[2]:
        reward = PAYOUTS[reels[0]]
    elif len(set(reels)) == 2:
        reward = 5

    new_balance = user["balance"] - SPIN_COST + reward
    users_col.update_one({"_id": user["_id"]}, {"$set": {"balance": new_balance}})
    return jsonify({"reels": reels, "reward": reward, "new_balance": new_balance})

# ================= MULTIPLAYER =================
@app.route('/api/match/join', methods=['POST'])
def join_match():
    user = get_current_user()
    if not user: return jsonify({"error": "Login required"}), 401
    uid = str(user["_id"])

    # Clean old queue
    queue_col.delete_many({"timestamp": {"$lt": time.time() - 60}})
    waiting = queue_col.find_one({"user_id": {"$ne": uid}})
    
    if waiting:
        match = {
            "player1": waiting["user_id"], "player2": uid,
            "p1_info": {"username": waiting["username"], "spins": [], "total": 0},
            "p2_info": {"username": user["username"], "spins": [], "total": 0},
            "current_round": 1, "current_turn": "p1", "round_spins": 0, "status": "active"
        }
        res = matches_col.insert_one(match)
        queue_col.delete_one({"_id": waiting["_id"]})
        return jsonify({"match_id": str(res.inserted_id)})
    else:
        queue_col.update_one({"user_id": uid}, 
            {"$set": {"username": user["username"], "timestamp": time.time()}}, upsert=True)
        return jsonify({"status": "waiting"})

@app.route('/api/match/<match_id>/status')
def match_status(match_id):
    uid = session.get("user_id")
    match = matches_col.find_one({"_id": ObjectId(match_id)})
    if not match: return jsonify({"error": "Not found"}), 404
    
    is_p1 = uid == match["player1"]
    my_info = match["p1_info"] if is_p1 else match["p2_info"]
    opp_info = match["p2_info"] if is_p1 else match["p1_info"]

    return jsonify({
        "status": match["status"],
        "current_turn": match["current_turn"],
        "is_my_turn": (match["current_turn"] == ("p1" if is_p1 else "p2")),
        "my_total": my_info["total"],
        "opp_total": opp_info["total"],
        "opp_username": opp_info["username"],
        "my_spins": my_info["spins"],
        "opp_spins": opp_info["spins"]
    })

@app.route('/api/match/<match_id>/spin', methods=['POST'])
def match_spin(match_id):
    uid = session.get("user_id")
    match = matches_col.find_one({"_id": ObjectId(match_id)})
    is_p1 = uid == match["player1"]
    
    reels = [random.choice(SYMBOLS) for _ in range(3)]
    score = PAYOUTS[reels[0]] if reels[0]==reels[1]==reels[2] else (5 if len(set(reels))==2 else 0)
    
    key = "p1_info" if is_p1 else "p2_info"
    matches_col.update_one({"_id": ObjectId(match_id)}, {
        "$push": {f"{key}.spins": {"reels": reels, "score": score}},
        "$inc": {f"{key}.total": score, "round_spins": 1},
        "$set": {"current_turn": "p2" if is_p1 else "p1"}
    })
    
    return jsonify({"reels": reels, "score": score})

@app.route('/api/leaderboard')
def leaderboard():
    users = users_col.find().sort("balance", -1).limit(10)
    return jsonify([{"username": u["username"], "balance": u["balance"]} for u in users])

if __name__ == "__main__":
    app.run(debug=True, port=5000)
