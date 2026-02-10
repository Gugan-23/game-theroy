from flask import Flask, render_template, jsonify, request, session
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from bson.objectid import ObjectId
import random

app = Flask(__name__)
app.secret_key = "multiplayer_secret_key_99"

# ================= MONGODB SETUP =================
MONGO_URI = "mongodb+srv://vgugan16:gugan2004@cluster0.qyh1fuo.mongodb.net/casino?retryWrites=true&w=majority"
client = MongoClient(MONGO_URI)

db = client["lucky777"]
users_col = db["users"]
queue_col = db["match_queue"]
matches_col = db["matches"]

# ================= GAME CONFIG =================
SYMBOLS = ['7️⃣', '💎', '🔔', '🍒', '🍋', '🍇']
PAYOUTS = {'7️⃣': 500, '💎': 200, '🔔': 100, '🍒': 50, '🍋': 30, '🍇': 20}
SPIN_COST = 10

# ================= HOME =================
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
        "balance": 100
    })

    return jsonify({"message": "Success"})

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

@app.route('/api/auth/logout')
def logout():
    session.clear()
    return jsonify({"success": True})

# ================= SINGLE PLAYER =================
@app.route('/api/game/spin', methods=['POST'])
def spin():
    if "user_id" not in session:
        return jsonify({"error": "Login required"}), 401

    user = users_col.find_one({"_id": ObjectId(session["user_id"])})

    if user["balance"] < SPIN_COST:
        return jsonify({"error": "Insufficient funds"}), 400

    reels = [random.choice(SYMBOLS) for _ in range(3)]

    reward = 0
    if reels[0] == reels[1] == reels[2]:
        reward = PAYOUTS[reels[0]]
    elif len(set(reels)) == 2:
        reward = 20

    new_balance = user["balance"] - SPIN_COST + reward

    users_col.update_one(
        {"_id": user["_id"]},
        {"$set": {"balance": new_balance}}
    )

    return jsonify({
        "reels": reels,
        "reward": reward,
        "new_balance": new_balance
    })

# ================= MULTIPLAYER =================
@app.route('/api/match/join', methods=['POST'])
def join_match():
    uid = session.get("user_id")
    if not uid:
        return jsonify({"error": "Login required"}), 401

    waiting = queue_col.find_one()

    if waiting:
        match = {
            "player1": waiting["user_id"],
            "player2": uid,
            "p1_reward": None,
            "p2_reward": None,
            "winner": None,
            "status": "waiting"
        }
        result = matches_col.insert_one(match)
        queue_col.delete_one({"_id": waiting["_id"]})

        return jsonify({"match_id": str(result.inserted_id)})

    else:
        queue_col.insert_one({"user_id": uid})
        return jsonify({"status": "waiting"})

@app.route('/api/match/spin', methods=['POST'])
def match_spin():
    uid = session.get("user_id")
    match = matches_col.find_one({
        "status": "waiting",
        "$or": [{"player1": uid}, {"player2": uid}]
    })

    if not match:
        return jsonify({"error": "No match"}), 400

    reels = [random.choice(SYMBOLS) for _ in range(3)]
    reward = PAYOUTS.get(reels[0], 20) if reels[0] == reels[1] == reels[2] else 20

    field = "p1_reward" if uid == match["player1"] else "p2_reward"
    matches_col.update_one({"_id": match["_id"]}, {"$set": {field: reward}})

    match = matches_col.find_one({"_id": match["_id"]})

    if match["p1_reward"] is not None and match["p2_reward"] is not None:
        winner = match["player1"] if match["p1_reward"] > match["p2_reward"] else match["player2"]

        users_col.update_one(
            {"_id": ObjectId(winner)},
            {"$inc": {"balance": 100}}
        )

        matches_col.update_one(
            {"_id": match["_id"]},
            {"$set": {"winner": winner, "status": "finished"}}
        )

    return jsonify({"reels": reels, "reward": reward})

# ================= LEADERBOARD =================
@app.route('/api/leaderboard')
def leaderboard():
    users = users_col.find().sort("balance", -1).limit(10)
    return jsonify([
        {"username": u["username"], "balance": u["balance"]}
        for u in users
    ])

# ================= RUN =================
if __name__ == "__main__":
    app.run(debug=True)
