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

SYMBOLS = ['7️⃣', '💎', '🔔', '🍒', '🍋', '🍇']
PAYOUTS = {'7️⃣': 100, '💎': 50, '🔔': 30, '🍒': 20, '🍋': 10, '🍇': 5}
MAX_ROUNDS = 5 # 5 turns each

def get_current_user():
    if "user_id" in session:
        try:
            return users_col.find_one({"_id": ObjectId(session["user_id"])})
        except: return None
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
        return jsonify({"user": {"username": user["username"], "balance": user["balance"]}})
    return jsonify({"error": "Invalid login"}), 401

@app.route('/api/auth/check')
def check():
    u = get_current_user()
    return jsonify({"logged_in": u is not None, "user": {"username": u["username"], "balance": u["balance"]} if u else None})

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"success": True})

# ================= MULTIPLAYER LOGIC =================

@app.route('/api/match/join', methods=['POST'])
def join():
    u = get_current_user()
    if not u: return jsonify({"error": "Unauthorized"}), 401
    uid = str(u["_id"])

    queue_col.delete_many({"timestamp": {"$lt": time.time() - 30}})
    opp = queue_col.find_one({"user_id": {"$ne": uid}})

    if opp:
        match = {
            "p1": opp["user_id"], "p2": uid,
            "p1_name": opp["username"], "p2_name": u["username"],
            "p1_score": 0, "p2_score": 0,
            "turn": "p1", "status": "active", "history": [], "winner": None
        }
        mid = matches_col.insert_one(match).inserted_id
        queue_col.delete_one({"_id": opp["_id"]})
        return jsonify({"match_id": str(mid)})
    else:
        queue_col.update_one({"user_id": uid}, {"$set": {"username": u["username"], "timestamp": time.time()}}, upsert=True)
        return jsonify({"status": "waiting"})

@app.route('/api/match/<mid>/status')
def status(mid):
    u = get_current_user()
    m = matches_col.find_one({"_id": ObjectId(mid)})
    if not m: return jsonify({"error": "No match"}), 404
    
    is_p1 = str(u["_id"]) == m["p1"]
    return jsonify({
        "status": m["status"],
        "is_my_turn": (m["turn"] == ("p1" if is_p1 else "p2")),
        "my_score": m["p1_score"] if is_p1 else m["p2_score"],
        "opp_score": m["p2_score"] if is_p1 else m["p1_score"],
        "opp_name": m["p2_name"] if is_p1 else m["p1_name"],
        "history": m["history"],
        "winner": m["winner"]
    })

@app.route('/api/match/<mid>/spin', methods=['POST'])
def match_spin(mid):
    u = get_current_user()
    m = matches_col.find_one({"_id": ObjectId(mid)})
    is_p1 = str(u["_id"]) == m["p1"]
    role = "p1" if is_p1 else "p2"

    if m["turn"] != role or m["status"] != "active": return jsonify({"error": "Wait turn"}), 400

    reels = [random.choice(SYMBOLS) for _ in range(3)]
    pts = PAYOUTS[reels[0]] if reels[0]==reels[1]==reels[2] else (10 if len(set(reels))==2 else 0)

    # Record history
    entry = {"player": m[f"{role}_name"], "reels": reels, "points": pts}
    
    matches_col.update_one({"_id": ObjectId(mid)}, {
        "$inc": {f"{role}_score": pts},
        "$push": {"history": entry},
        "$set": {"turn": "p2" if is_p1 else "p1"}
    })

    # Check if game ends
    m_upd = matches_col.find_one({"_id": ObjectId(mid)})
    if len(m_upd["history"]) >= (MAX_ROUNDS * 2):
        win_name = "Draw"
        if m_upd["p1_score"] > m_upd["p2_score"]: win_name = m_upd["p1_name"]
        elif m_upd["p2_score"] > m_upd["p1_score"]: win_name = m_upd["p2_name"]
        
        matches_col.update_one({"_id": ObjectId(mid)}, {"$set": {"status": "finished", "winner": win_name}})
        if win_name != "Draw":
            users_col.update_one({"username": win_name}, {"$inc": {"balance": 100}})

    return jsonify({"reels": reels, "points": pts})

@app.route('/api/leaderboard')
def lead():
    users = users_col.find().sort("balance", -1).limit(5)
    return jsonify([{"u": u["username"], "b": u["balance"]} for u in users])

if __name__ == "__main__":
    # host='0.0.0.0' allows other devices on the same WiFi to connect via your IP
    app.run(debug=True, host='0.0.0.0', port=5000)
