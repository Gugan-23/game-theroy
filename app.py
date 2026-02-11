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
db = client["lucky777"]  # Your actual database name
users_col = db["users"]
queue_col = db["match_queue"]
matches_col = db["matches"]

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


# ================= MATCHMAKING =================
@app.route('/api/match/join', methods=['POST'])
def join_match():
    user = get_current_user()
    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    uid = str(user["_id"])

    # Remove expired queue entries
    queue_col.delete_many({"timestamp": {"$lt": time.time() - 60}})

    opponent = queue_col.find_one({"user_id": {"$ne": uid}})

    if opponent:
        # Create match
        match = {
            "p1": opponent["user_id"],
            "p2": uid,
            "p1_name": opponent["username"],
            "p2_name": user["username"],
            "p1_score": 0,
            "p2_score": 0,
            "turn": "p1",
            "status": "active",
            "history": [],
            "winner": None,
            "created_at": time.time()
        }

        match_id = matches_col.insert_one(match).inserted_id

        queue_col.delete_one({"_id": opponent["_id"]})

        return jsonify({"match_id": str(match_id)})

    else:
        queue_col.update_one(
            {"user_id": uid},
            {"$set": {
                "username": user["username"],
                "timestamp": time.time()
            }},
            upsert=True
        )

        return jsonify({"status": "waiting"})


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

    if "p1" not in match:
        return jsonify({"error": "Old match format"}), 400

    is_p1 = str(user["_id"]) == match["p1"]

    return jsonify({
        "status": match["status"],
        "is_my_turn": match["turn"] == ("p1" if is_p1 else "p2"),
        "my_score": match["p1_score"] if is_p1 else match["p2_score"],
        "opp_score": match["p2_score"] if is_p1 else match["p1_score"],
        "opp_name": match["p2_name"] if is_p1 else match["p1_name"],
        "history": match["history"],
        "winner": match["winner"]
    })


# ================= MATCH SPIN =================
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

    # Spin logic
    reels = [random.choice(SYMBOLS) for _ in range(3)]

    if reels[0] == reels[1] == reels[2]:
        points = PAYOUTS[reels[0]]
    elif len(set(reels)) == 2:
        points = 10
    else:
        points = 0

    history_entry = {
        "player": match[f"{role}_name"],
        "reels": reels,
        "points": points
    }

    matches_col.update_one(
        {"_id": ObjectId(mid)},
        {
            "$inc": {f"{role}_score": points},
            "$push": {"history": history_entry},
            "$set": {"turn": "p2" if role == "p1" else "p1"}
        }
    )

    updated_match = matches_col.find_one({"_id": ObjectId(mid)})

    # End game condition
    if len(updated_match["history"]) >= MAX_ROUNDS * 2:
        winner = "Draw"

        if updated_match["p1_score"] > updated_match["p2_score"]:
            winner = updated_match["p1_name"]
        elif updated_match["p2_score"] > updated_match["p1_score"]:
            winner = updated_match["p2_name"]

        matches_col.update_one(
            {"_id": ObjectId(mid)},
            {"$set": {"status": "finished", "winner": winner}}
        )

        if winner != "Draw":
            users_col.update_one(
                {"username": winner},
                {"$inc": {"balance": 100}}
            )

    return jsonify({
        "reels": reels,
        "points": points
    })


# ================= LEADERBOARD =================
@app.route('/api/leaderboard')
def leaderboard():
    users = users_col.find().sort("balance", -1).limit(5)

    return jsonify([
        {"username": u["username"], "balance": u["balance"]}
        for u in users
    ])


# ================= RUN =================
if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)
