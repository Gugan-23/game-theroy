from flask import Flask, render_template, jsonify, request, session
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from bson.objectid import ObjectId
from datetime import timedelta
import random
import time

app = Flask(__name__)
app.secret_key = "multiplayer_777_super_secret_key_2026"

# ================= SESSION CONFIG =================
app.config['SESSION_COOKIE_NAME'] = 'lucky777_session'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False

# ================= MONGODB - SINGLE COLLECTION =================
MONGO_URI = "mongodb+srv://vgugan16:gugan2004@cluster0.qyh1fuo.mongodb.net/casino?retryWrites=true&w=majority"
client = MongoClient(MONGO_URI)
db = client["lucky777"]
queue_col = db["match_queue"]  # EVERYTHING stored here: waiting players + active matches + finished matches
users_col = db["users"]

SYMBOLS = ['7️⃣', '💎', '🔔', '🍒', '🍋', '🍇']
PAYOUTS = {'7️⃣': 100, '💎': 50, '🔔': 30, '🍒': 20, '🍋': 10, '🍇': 5}
MAX_ROUNDS = 5

# ================= HELPER =================
def get_current_user():
    if "user_id" not in session:
        return None
    try:
        return users_col.find_one({"_id": ObjectId(session["user_id"])})
    except:
        return None

@app.route('/')
def index():
    return render_template('index.html')

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

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"success": True})

@app.route('/api/auth/check', methods=['GET'])
def auth_check():
    user = get_current_user()
    if user:
        return jsonify({"logged_in": True, "user": {"username": user["username"], "balance": user.get("balance", 0)}})
    return jsonify({"logged_in": False})

# ================= MATCHMAKING - ALL IN match_queue =================
@app.route('/api/match/join', methods=['POST'])
def join_match():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    uid = str(user["_id"])
    
    # Clean expired waiting players (type: "waiting")
    queue_col.delete_many({"type": "waiting", "timestamp": {"$lt": time.time() - 60}})
    
    # Look for another waiting player
    opponent = queue_col.find_one({"type": "waiting", "user_id": {"$ne": uid}})
    
    if opponent:
        # ✅ CREATE MATCH "m1" IN match_queue COLLECTION (NOT separate matches collection)
        match_doc = {
            "_id": "m1",  # FIXED: Always use "m1" as document ID
            "type": "match",  # Mark as active match
            "p1": opponent["user_id"],
            "p2": uid,
            "p1_name": opponent["username"],
            "p2_name": user["username"],
            "p1_score": 0,
            "p2_score": 0,
            "turn": "p1",
            "status": "active",
            "spins": [],
            "created_at": time.time(),
            "game": "lucky777"
        }
        
        # REPLACE/INSERT "m1" document
        queue_col.replace_one({"_id": "m1"}, match_doc, upsert=True)
        queue_col.delete_one({"_id": opponent["_id"]})
        
        print(f"🎮 MATCH CREATED in match_queue.m1: {opponent['username']} vs {user['username']}")
        return jsonify({"match_id": "m1", "status": "matched"})
    
    # Add to waiting queue
    queue_col.replace_one(
        {"user_id": uid},
        {
            "type": "waiting",
            "user_id": uid,
            "username": user["username"],
            "game": "lucky777",
            "timestamp": time.time()
        },
        upsert=True
    )
    print(f"⏳ {user['username']} waiting in queue")
    return jsonify({"status": "waiting", "message": "Waiting for opponent..."})

# ================= MATCH STATUS - FROM match_queue.m1 =================
@app.route('/api/match/m1/status')
def match_status():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    # Get "m1" from match_queue collection
    match = queue_col.find_one({"_id": "m1", "type": "match"})
    if not match:
        return jsonify({"error": "No active match"}), 404

    is_p1 = str(user["_id"]) == match["p1"]
    
    return jsonify({
        "status": match["status"],
        "is_my_turn": match["turn"] == ("p1" if is_p1 else "p2"),
        "my_score": match["p1_score"] if is_p1 else match["p2_score"],
        "opp_score": match["p2_score"] if is_p1 else match["p1_score"],
        "opp_name": match["p2_name"] if is_p1 else match["p1_name"],
        "history": match["spins"],
        "winner": match.get("winner")
    })

# ================= SPIN - UPDATE match_queue.m1 =================
@app.route('/api/match/m1/spin', methods=['POST'])
def match_spin():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    match = queue_col.find_one({"_id": "m1", "type": "match"})
    if not match or match["status"] != "active":
        return jsonify({"error": "Match not active"}), 400

    is_p1 = str(user["_id"]) == match["p1"]
    role = "p1" if is_p1 else "p2"
    if match["turn"] != role:
        return jsonify({"error": "Wait for your turn"}), 400

    # Spin logic
    reels = [random.choice(SYMBOLS) for _ in range(3)]
    if reels[0] == reels[1] == reels[2]:
        points = PAYOUTS[reels[0]]
    elif len(set(reels)) == 2:
        points = 10
    else:
        points = 0

    spin_record = {
        "player": user["username"],
        "reels": reels,
        "points": points
    }

    # UPDATE m1 document in match_queue
    queue_col.update_one(
        {"_id": "m1"},
        {
            "$inc": {f"{role}_score": points},
            "$push": {"spins": spin_record},
            "$set": {"turn": "p2" if role == "p1" else "p1"}
        }
    )

    # Check end game
    updated_match = queue_col.find_one({"_id": "m1"})
    if len(updated_match["spins"]) >= MAX_ROUNDS * 2:
        p1_score = updated_match["p1_score"]
        p2_score = updated_match["p2_score"]
        
        if p1_score > p2_score:
            winner = updated_match["p1_name"]
            users_col.update_one({"_id": ObjectId(updated_match["p1"])}, {"$inc": {"balance": 100}})
        elif p2_score > p1_score:
            winner = updated_match["p2_name"]
            users_col.update_one({"_id": ObjectId(updated_match["p2"])}, {"$inc": {"balance": 100}})
        else:
            winner = "Draw"
        
        queue_col.update_one(
            {"_id": "m1"},
            {"$set": {"status": "finished", "winner": winner}}
        )

    return jsonify({"reels": reels, "points": points})

# ================= LEADERBOARD =================
@app.route('/api/leaderboard')
def leaderboard():
    users = users_col.find().sort("balance", -1).limit(5)
    return jsonify([{"u": u["username"], "b": u["balance"]} for u in users])

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)
