from flask import Flask, render_template, jsonify, request, session
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from bson.objectid import ObjectId
import random
import time

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
PAYOUTS = {'7️⃣': 100, '💎': 50, '🔔': 30, '🍒': 20, '🍋': 10, '🍇': 5}
SPIN_COST = 0

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
        "balance": 1000
    })
    return jsonify({"message": "Success"})

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    user = users_col.find_one({"username": data["username"]})
    if user and check_password_hash(user["password"], data["password"]):
        session["user_id"] = str(user["_id"])
        return jsonify({
            "user": {"username": user["username"], "balance": user["balance"]}
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
        reward = 10

    new_balance = user["balance"] - SPIN_COST + reward
    users_col.update_one({"_id": user["_id"]}, {"$set": {"balance": new_balance}})

    return jsonify({"reels": reels, "reward": reward, "new_balance": new_balance})

# ================= MULTIPLAYER =================
@app.route('/api/match/join', methods=['POST'])
def join_match():
    uid = session.get("user_id")
    if not uid:
        return jsonify({"error": "Login required"}), 401

    # Clean old queue entries (>60 seconds)
    queue_col.delete_many({"timestamp": {"$lt": time.time() - 60}})

    waiting = queue_col.find_one({"timestamp": {"$gte": time.time() - 60}})
    if waiting:
        # Get both players' info
        p1_user = users_col.find_one({"_id": ObjectId(waiting["user_id"])})
        p1_username = p1_user["username"] if p1_user else waiting.get("username", "Player1")
        
        p2_user = users_col.find_one({"_id": ObjectId(uid)})
        p2_username = p2_user["username"] if p2_user else "Player2"
        
        match = {
            "player1": waiting["user_id"],
            "player2": uid,
            "p1_info": {"username": p1_username, "spins": [], "total": 0},
            "p2_info": {"username": p2_username, "spins": [], "total": 0},
            "current_round": 1,
            "current_turn": "p1",
            "round_spins": 0,
            "status": "waiting",
            "round1_complete_time": None,
            "match_results": [],
            "created_at": time.time()
        }
        
        result = matches_col.insert_one(match)
        queue_col.delete_one({"_id": waiting["_id"]})
        return jsonify({"match_id": str(result.inserted_id)})
    else:
        # Add to queue with timestamp
        p1_user = users_col.find_one({"_id": ObjectId(uid)})
        queue_col.insert_one({
            "user_id": uid, 
            "username": p1_user["username"] if p1_user else "Player1",
            "timestamp": time.time()
        })
        return jsonify({"status": "waiting", "search_timeout": 60})

@app.route('/api/match/<match_id>/status')
def match_status(match_id):
    uid = session.get("user_id")
    if not uid:
        return jsonify({"error": "Login required"}), 401

    match = matches_col.find_one({"_id": ObjectId(match_id)})
    if not match:
        return jsonify({"error": "Match not found"}), 404

    is_p1 = uid == match["player1"]
    my_info = match["p1_info"] if is_p1 else match["p2_info"]
    opp_info = match["p2_info"] if is_p1 else match["p1_info"]
    
    return jsonify({
        "match_id": match_id,
        "status": match["status"],
        "current_round": match["current_round"],
        "current_turn": match["current_turn"],
        "round_spins": match["round_spins"],
        "my_spins": my_info["spins"],
        "opp_spins": opp_info["spins"],
        "my_total": my_info["total"],
        "opp_total": opp_info["total"],
        "can_spin": (match["current_turn"] == ("p1" if is_p1 else "p2")),
        "opponent_username": opp_info["username"],
        "round1_complete_time": match.get("round1_complete_time")
    })

@app.route('/api/match/<match_id>/spin', methods=['POST'])
def match_spin(match_id):
    uid = session.get("user_id")
    if not uid:
        return jsonify({"error": "Login required"}), 401

    match = matches_col.find_one({"_id": ObjectId(match_id)})
    if not match:
        return jsonify({"error": "Match not found"}), 404

    is_p1 = uid == match["player1"]
    my_turn = match["current_turn"] == ("p1" if is_p1 else "p2")
    
    if not my_turn:
        return jsonify({"error": "Not your turn!"}), 400

    if match["status"] != "waiting":
        return jsonify({"error": "Match not active"}), 400

    # Generate spin
    reels = [random.choice(SYMBOLS) for _ in range(3)]
    score = 0
    if reels[0] == reels[1] == reels[2]:
        score = PAYOUTS[reels[0]]
    elif len(set(reels)) == 2:
        score = 10

    # Update player spins - CORRECTED MongoDB UPDATE
    if is_p1:
        new_spins = match["p1_info"]["spins"] + [{"reels": reels, "score": score}]
        new_total = sum(s["score"] for s in new_spins)
        matches_col.update_one(
            {"_id": ObjectId(match_id)},
            {
                "$set": {
                    "current_turn": "p2",
                    "round_spins": match["round_spins"] + 1,
                    "p1_info.spins": new_spins,
                    "p1_info.total": new_total
                }
            }
        )
    else:
        new_spins = match["p2_info"]["spins"] + [{"reels": reels, "score": score}]
        new_total = sum(s["score"] for s in new_spins)
        matches_col.update_one(
            {"_id": ObjectId(match_id)},
            {
                "$set": {
                    "current_turn": "p1",
                    "round_spins": match["round_spins"] + 1,
                    "p2_info.spins": new_spins,
                    "p2_info.total": new_total
                }
            }
        )

    # Check round completion
    updated_match = matches_col.find_one({"_id": ObjectId(match_id)})
    if updated_match["round_spins"] >= 10:
        p1_total = updated_match["p1_info"]["total"]
        p2_total = updated_match["p2_info"]["total"]
        round_winner = "p1" if p1_total > p2_total else "p2"
        
        winner_id = updated_match["player1"] if round_winner == "p1" else updated_match["player2"]
        users_col.update_one({"_id": ObjectId(winner_id)}, {"$inc": {"balance": 200}})
        
        matches_col.update_one(
            {"_id": ObjectId(match_id)},
            {
                "$set": {
                    "status": "round1_complete",
                    "round1_complete_time": time.time(),
                    "round1_winner": round_winner,
                    "match_results": updated_match.get("match_results", []) + [{
                        "round": 1, "p1_total": p1_total, "p2_total": p2_total, "winner": round_winner
                    }]
                }
            }
        )
        
        return jsonify({
            "reels": reels, "score": score, "round_complete": True,
            "round_num": 1, "p1_total": p1_total, "p2_total": p2_total, "round_winner": round_winner
        })

    return jsonify({
        "reels": reels, "score": score, "turn_switched": True,
        "next_player": "p2" if is_p1 else "p1"
    })

@app.route('/api/match/<match_id>/start_round2', methods=['POST'])
def start_round2(match_id):
    uid = session.get("user_id")
    if not uid:
        return jsonify({"error": "Login required"}), 401

    match = matches_col.find_one({"_id": ObjectId(match_id)})
    if not match or match["status"] != "round1_complete":
        return jsonify({"error": "Cannot start round 2"}), 400

    matches_col.update_one(
        {"_id": ObjectId(match_id)},
        {
            "$set": {
                "current_round": 2, "current_turn": "p1", "round_spins": 0,
                "status": "waiting", "p1_info.spins": [], "p2_info.spins": [],
                "p1_info.total": 0, "p2_info.total": 0
            }
        }
    )
    return jsonify({"success": True, "round": 2})

@app.route('/api/match/<match_id>/leave')
def leave_match(match_id):
    matches_col.delete_one({"_id": ObjectId(match_id)})
    return jsonify({"success": True})

# ================= LEADERBOARD =================
@app.route('/api/leaderboard')
def leaderboard():
    users = users_col.find().sort("balance", -1).limit(10)
    return jsonify([{"username": u["username"], "balance": u["balance"]} for u in users])

if __name__ == "__main__":
    app.run(debug=True)
