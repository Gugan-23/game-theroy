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

# ================= MONGODB =================
MONGO_URI = "mongodb+srv://vgugan16:gugan2004@cluster0.qyh1fuo.mongodb.net/casino?retryWrites=true&w=majority"

client = MongoClient(MONGO_URI)
db = client["lucky777"]
users_col = db["users"]
queue_col = db["match_queue"]  # Stores waiting players: {user_id, username, game: "lucky777", timestamp}
matches_col = db["matches"]    # Stores match data with all spins

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

# ================= ROUTES =================
@app.route('/')
def index():
    return render_template('index.html')

# ================= AUTH =================
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
    return jsonify({
        "user": {
            "username": data["username"],
            "balance": 1000
        }
    })

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    user = users_col.find_one({"username": data["username"]})

    if user and check_password_hash(user["password"], data["password"]):
        session["user_id"] = str(user["_id"])
        return jsonify({
            "user": {
                "username": user["username"],
                "balance": user["balance"]
            }
        })

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

# ================= MATCHMAKING - YOUR LOGIC =================
@app.route('/api/match/join', methods=['POST'])
def join_match():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    uid = str(user["_id"])
    
    # Clean expired queue entries (older than 60 seconds)
    queue_col.delete_many({"timestamp": {"$lt": time.time() - 60}})
    
    # Look for another player in queue
    opponent = queue_col.find_one({"user_id": {"$ne": uid}})
    
    if opponent:
        # MATCH FOUND! Create new match with both players
        match = {
            "p1": opponent["user_id"],
            "p2": uid,
            "p1_name": opponent["username"],
            "p2_name": user["username"],
            "p1_score": 0,
            "p2_score": 0,
            "turn": "p1",  # p1 always starts
            "status": "active",
            "spins": [],   # Store ALL spinning points here
            "created_at": time.time(),
            "game": "lucky777"
        }
        
        match_id = matches_col.insert_one(match).inserted_id
        
        # Remove opponent from queue
        queue_col.delete_one({"_id": opponent["_id"]})
        
        print(f"🎮 MATCH CREATED: {opponent['username']} vs {user['username']} - Match ID: {match_id}")
        return jsonify({"match_id": str(match_id), "status": "matched"})
    
    else:
        # No opponent found - ADD TO QUEUE with username and game
        queue_col.update_one(
            {"user_id": uid},
            {"$set": {
                "user_id": uid,
                "username": user["username"],
                "game": "lucky777",
                "timestamp": time.time()
            }},
            upsert=True
        )
        
        print(f"⏳ {user['username']} added to queue for game lucky777")
        return jsonify({"status": "waiting", "message": "Waiting for opponent..."})

# ================= MATCH STATUS =================
@app.route('/api/match/<mid>/status')
def match_status(mid):
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        match = matches_col.find_one({"_id": ObjectId(mid)})
    except:
        return jsonify({"error": "Invalid match ID"}), 400

    if not match:
        return jsonify({"error": "Match not found"}), 404

    is_p1 = str(user["_id"]) == match["p1"]
    
    return jsonify({
        "status": match["status"],
        "is_my_turn": match["turn"] == ("p1" if is_p1 else "p2"),
        "my_score": match["p1_score"] if is_p1 else match["p2_score"],
        "opp_score": match["p2_score"] if is_p1 else match["p1_score"],
        "opp_name": match["p2_name"] if is_p1 else match["p1_name"],
        "spins": match["spins"],  # All spinning history
        "winner": match.get("winner")
    })

# ================= MATCH SPIN - STORE EVERY SPIN =================
@app.route('/api/match/<mid>/spin', methods=['POST'])
def match_spin(mid):
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        match = matches_col.find_one({"_id": ObjectId(mid)})
    except:
        return jsonify({"error": "Invalid match ID"}), 400

    if not match or match["status"] != "active":
        return jsonify({"error": "Match not active"}), 400

    is_p1 = str(user["_id"]) == match["p1"]
    role = "p1" if is_p1 else "p2"

    if match["turn"] != role:
        return jsonify({"error": "Wait for your turn"}), 400

    # Generate spin result
    reels = [random.choice(SYMBOLS) for _ in range(3)]
    
    # Calculate points
    if reels[0] == reels[1] == reels[2]:
        points = PAYOUTS[reels[0]]
    elif len(set(reels)) == 2:
        points = 10
    else:
        points = 0

    # Create spin record
    spin_record = {
        "timestamp": time.time(),
        "player_id": str(user["_id"]),
        "player_name": user["username"],
        "role": role,
        "reels": reels,
        "points": points
    }

    # Update match: increment score, store spin, switch turn
    matches_col.update_one(
        {"_id": ObjectId(mid)},
        {
            "$inc": {f"{role}_score": points},
            "$push": {"spins": spin_record},
            "$set": {"turn": "p2" if role == "p1" else "p1"}
        }
    )

    # Check game end condition (10 total spins = 5 rounds each)
    updated_match = matches_col.find_one({"_id": ObjectId(mid)})
    total_spins = len(updated_match["spins"])
    
    if total_spins >= MAX_ROUNDS * 2:
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
        
        matches_col.update_one(
            {"_id": ObjectId(mid)},
            {"$set": {"status": "finished", "winner": winner}}
        )
        
        print(f"🏁 MATCH FINISHED: {winner} wins! Total spins stored: {total_spins}")

    return jsonify({
        "reels": reels,
        "points": points,
        "total_spins": total_spins
    })

# ================= LEADERBOARD =================
@app.route('/api/leaderboard')
def leaderboard():
    users = users_col.find().sort("balance", -1).limit(5)
    return jsonify([
        {"u": u["username"], "b": u["balance"]}
        for u in users
    ])

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)
