from flask import Flask, render_template, jsonify, request, session
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo import MongoClient
from bson.objectid import ObjectId
import random
import time
from datetime import timedelta

app = Flask(__name__)
app.secret_key = "multiplayer_777_super_secret_key_2026"

# ================= SESSION CONFIG =================
app.config['SESSION_COOKIE_NAME'] = 'lucky777_session'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False 

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
MAX_SPINS_PER_PLAYER = 5

def get_current_user():
    if "user_id" in session:
        try:
            return users_col.find_one({"_id": ObjectId(session["user_id"])})
        except:
            return None
    return None

@app.route('/')
def index():
    session.permanent = True
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
    return jsonify({"message": "Success", "user": {"username": data["username"], "balance": 1000}})

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    user = users_col.find_one({"username": data["username"]})
    if user and check_password_hash(user["password"], data["password"]):
        session.permanent = True 
        session["user_id"] = str(user["_id"])
        return jsonify({"user": {"username": user["username"], "balance": user["balance"]}})
    return jsonify({"error": "Invalid login"}), 401

@app.route('/api/auth/check', methods=['GET'])
def check_session():
    user = get_current_user()
    if user:
        return jsonify({"logged_in": True, "user": {"username": user["username"], "balance": user["balance"]}})
    return jsonify({"logged_in": False})

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"success": True})

# ================= ADMIN =================
@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.json
    if data.get("password") == "admin123":
        session["admin_access"] = True
        return jsonify({"success": True})
    return jsonify({"error": "Invalid password"}), 401

@app.route('/api/admin/alter-balance', methods=['POST'])
def alter_balance():
    if not session.get("admin_access"):
        return jsonify({"error": "Admin required"}), 403
    data = request.json
    user = users_col.find_one({"username": data["username"]})
    if user:
        users_col.update_one({"_id": user["_id"]}, {"$set": {"balance": int(data["balance"])}})
        return jsonify({"success": True})
    return jsonify({"error": "User not found"}), 404

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
        reward = 10

    new_balance = user["balance"] - SPIN_COST + reward
    users_col.update_one({"_id": user["_id"]}, {"$set": {"balance": new_balance}})
    return jsonify({"reels": reels, "reward": reward, "new_balance": new_balance})

# ================= MULTIPLAYER =================
@app.route('/api/match/join', methods=['POST'])
def join_match():
    user = get_current_user()
    if not user: 
        return jsonify({"error": "Login required"}), 401
    uid = str(user["_id"])

    # Clean old queue
    queue_col.delete_many({"timestamp": {"$lt": time.time() - 30}})
    
    # Check for waiting opponent
    opponent = queue_col.find_one({})
    if opponent and opponent["user_id"] != uid:
        opp_user = users_col.find_one({"_id": ObjectId(opponent["user_id"])})
        match_data = {
            "player1": opponent["user_id"], 
            "player2": uid,
            "p1_info": {"username": opponent["username"], "total": 0, "spins_count": 0},
            "p2_info": {"username": user["username"], "total": 0, "spins_count": 0},
            "current_turn": "p1",
            "status": "active",
            "winner": None,
            "created_at": time.time()
        }
        res = matches_col.insert_one(match_data)
        queue_col.delete_one({"_id": opponent["_id"]})
        return jsonify({"match_id": str(res.inserted_id)})
    else:
        # Add to queue
        queue_col.update_one({"user_id": uid}, 
            {"$set": {"username": user["username"], "timestamp": time.time()}}, 
            upsert=True)
        return jsonify({"status": "waiting"})

@app.route('/api/match/<match_id>/status')
def match_status(match_id):
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401
        
    try:
        match = matches_col.find_one({"_id": ObjectId(match_id)})
        if not match:
            return jsonify({"error": "Match not found"}), 404
        
        is_p1 = str(user["_id"]) == match["player1"]
        my_key = "p1_info" if is_p1 else "p2_info"
        opp_key = "p2_info" if is_p1 else "p1_info"
        
        is_my_turn = (match["current_turn"] == ("p1" if is_p1 else "p2")) and match["status"] == "active"
        
        return jsonify({
            "status": match["status"],
            "is_my_turn": is_my_turn,
            "my_total": match[my_key]["total"],
            "opp_total": match[opp_key]["total"],
            "opp_username": match[opp_key]["username"],
            "winner": match.get("winner", None),  # ✅ FIXED: Use .get() to avoid KeyError
            "p1_spins": match["p1_info"]["spins_count"],
            "p2_spins": match["p2_info"]["spins_count"]
        })
    except Exception as e:
        return jsonify({"error": "Match error"}), 500

@app.route('/api/match/<match_id>/spin', methods=['POST'])
def match_spin(match_id):
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401
        
    try:
        match = matches_col.find_one({"_id": ObjectId(match_id)})
        if not match or match["status"] != "active":
            return jsonify({"error": "Match not active"}), 400

        is_p1 = str(user["_id"]) == match["player1"]
        current_role = "p1" if is_p1 else "p2"
        
        if match["current_turn"] != current_role:
            return jsonify({"error": "Not your turn"}), 400
        
        # Spin logic
        reels = [random.choice(SYMBOLS) for _ in range(3)]
        score = 0
        if reels[0] == reels[1] == reels[2]:
            score = PAYOUTS[reels[0]]
        elif len(set(reels)) == 2:
            score = 10
        
        my_key = "p1_info" if is_p1 else "p2_info"
        next_turn = "p2" if is_p1 else "p1"
        
        # Update match
        matches_col.update_one({"_id": ObjectId(match_id)}, {
            "$inc": {f"{my_key}.total": score, f"{my_key}.spins_count": 1},
            "$set": {"current_turn": next_turn}
        })
        
        # Check if match complete
        updated_match = matches_col.find_one({"_id": ObjectId(match_id)})
        if (updated_match["p1_info"]["spins_count"] >= MAX_SPINS_PER_PLAYER and 
            updated_match["p2_info"]["spins_count"] >= MAX_SPINS_PER_PLAYER):
            
            p1_total = updated_match["p1_info"]["total"]
            p2_total = updated_match["p2_info"]["total"]
            
            winner = None
            if p1_total > p2_total:
                winner = updated_match["p1_info"]["username"]
                users_col.update_one({"_id": ObjectId(updated_match["player1"])}, {"$inc": {"balance": 100}})
            elif p2_total > p1_total:
                winner = updated_match["p2_info"]["username"]
                users_col.update_one({"_id": ObjectId(updated_match["player2"])}, {"$inc": {"balance": 100}})
            
            matches_col.update_one({"_id": ObjectId(match_id)}, {
                "$set": {"status": "finished", "winner": winner}
            })
        
        return jsonify({"reels": reels, "score": score, "match_complete": winner is not None})
    except Exception as e:
        return jsonify({"error": "Spin error"}), 500

@app.route('/api/leaderboard')
def leaderboard():
    users = users_col.find().sort("balance", -1).limit(10)
    return jsonify([{"username": u["username"], "balance": u["balance"]} for u in users])

if __name__ == "__main__":
    app.run(debug=True, port=5000)
