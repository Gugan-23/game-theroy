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

    waiting = queue_col.find_one()
    if waiting:
        match = {
            "player1": waiting["user_id"],
            "player2": uid,
            "p1_info": {"username": waiting.get("username", "Player1"), "spins": [], "total": 0},
            "p2_info": {"username": "", "spins": [], "total": 0},
            "current_round": 1,
            "current_turn": "p1",  # p1 starts first
            "round_spins": 0,  # spins completed in current round
            "status": "waiting",
            "round1_complete_time": None,
            "match_results": []
        }
        # Get p2 username
        p2_user = users_col.find_one({"_id": ObjectId(uid)})
        match["p2_info"]["username"] = p2_user["username"] if p2_user else "Player2"
        
        result = matches_col.insert_one(match)
        queue_col.delete_one({"_id": waiting["_id"]})
        return jsonify({"match_id": str(result.inserted_id)})
    else:
        p1_user = users_col.find_one({"_id": ObjectId(uid)})
        queue_col.insert_one({"user_id": uid, "username": p1_user["username"] if p1_user else "Player1"})
        return jsonify({"status": "waiting"})

@app.route('/api/match/<match_id>/status')
def match_status(match_id):
    uid = session.get("user_id")
    if not uid:
        return jsonify({"error": "Login required"}), 401

    match = matches_col.find_one({"_id": ObjectId(match_id)})
    if not match:
        return jsonify({"error": "Match not found"}), 404

    is_p1 = uid == match["player1"]
    opponent_id = match["player2"] if is_p1 else match["player1"]
    opponent_username = match["p2_info"]["username"] if is_p1 else match["p1_info"]["username"]
    
    my_spins = match["p1_info"]["spins"] if is_p1 else match["p2_info"]["spins"]
    opp_spins = match["p2_info"]["spins"] if is_p1 else match["p1_info"]["spins"]
    
    return jsonify({
        "match_id": match_id,
        "status": match["status"],
        "current_round": match["current_round"],
        "current_turn": match["current_turn"],
        "round_spins": match["round_spins"],
        "my_spins": my_spins,
        "opp_spins": opp_spins,
        "can_spin": (match["current_turn"] == ("p1" if is_p1 else "p2")),
        "opponent_username": opponent_username,
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

    # Update player spins
    my_spins = match["p1_info"]["spins"] if is_p1 else match["p2_info"]["spins"]
    my_spins.append({"reels": reels, "score": score, "time": time.time()})
    
    # Switch turn
    new_turn = "p2" if is_p1 else "p1"
    round_spins = match["round_spins"] + 1
    
    # Update match
    update_data = {
        "$set": {
            "current_turn": new_turn,
            "round_spins": round_spins
        }
    }
    if is_p1:
        update_data["$set"]["p1_info.spins"] = my_spins
        update_data["$set"]["p1_info.total"] = sum(s["score"] for s in my_spins)
    else:
        update_data["$set"]["p2_info.spins"] = my_spins
        update_data["$set"]["p2_info.total"] = sum(s["score"] for s in my_spins)
    
    matches_col.update_one({"_id": ObjectId(match_id)}, update_data)

    # Check round completion (10 spins total - 5 each)
    updated_match = matches_col.find_one({"_id": ObjectId(match_id)})
    if updated_match["round_spins"] >= 10:
        # Round complete
        p1_total = updated_match["p1_info"]["total"]
        p2_total = updated_match["p2_info"]["total"]
        round_winner = "p1" if p1_total > p2_total else "p2"
        
        # Award round winner
        winner_id = updated_match["player1"] if round_winner == "p1" else updated_match["player2"]
        users_col.update_one({"_id": ObjectId(winner_id)}, {"$inc": {"balance": 200}})
        
        matches_col.update_one(
            {"_id": ObjectId(match_id)},
            {
                "$set": {
                    "status": "round1_complete",
                    "round1_complete_time": time.time(),
                    "round1_winner": round_winner,
                    "match_results": updated_match["match_results"] + [{
                        "round": 1,
                        "p1_total": p1_total,
                        "p2_total": p2_total,
                        "winner": round_winner
                    }]
                }
            }
        )
        
        return jsonify({
            "reels": reels,
            "score": score,
            "round_complete": True,
            "round_num": 1,
            "p1_total": p1_total,
            "p2_total": p2_total,
            "round_winner": round_winner
        })

    return jsonify({
        "reels": reels,
        "score": score,
        "turn_switched": True,
        "next_player": new_turn
    })

@app.route('/api/match/<match_id>/start_round2', methods=['POST'])
def start_round2(match_id):
    uid = session.get("user_id")
    if not uid:
        return jsonify({"error": "Login required"}), 401

    match = matches_col.find_one({"_id": ObjectId(match_id)})
    if not match or match["status"] != "round1_complete":
        return jsonify({"error": "Cannot start round 2"}), 400

    # Reset for round 2
    matches_col.update_one(
        {"_id": ObjectId(match_id)},
        {
            "$set": {
                "current_round": 2,
                "current_turn": "p1",
                "round_spins": 0,
                "status": "waiting",
                "p1_info.spins": [],
                "p2_info.spins": [],
                "p1_info.total": 0,
                "p2_info.total": 0
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
