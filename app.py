from flask import Flask, render_template, jsonify, request, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import random

app = Flask(__name__)
app.secret_key = "multiplayer_secret_key_99"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///jackpot.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ================= DATABASE MODELS =================
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    balance = db.Column(db.Integer, default=100)

class MatchQueue(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, unique=True)

class Match(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    player1_id = db.Column(db.Integer)
    player2_id = db.Column(db.Integer)
    p1_reward = db.Column(db.Integer)
    p2_reward = db.Column(db.Integer)
    winner_id = db.Column(db.Integer)
    status = db.Column(db.String(20))  # waiting / finished

with app.app_context():
    db.create_all()

# ================= GAME CONFIG =================
SYMBOLS = ['7️⃣', '💎', '🔔', '🍒', '🍋', '🍇']
PAYOUTS = {'7️⃣': 500, '💎': 200, '🔔': 100, '🍒': 50, '🍋': 30, '🍇': 20}
SPIN_COST = 10

# ================= AUTH =================
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/auth/signup', methods=['POST'])
def signup():
    data = request.json
    if User.query.filter_by(username=data['username']).first():
        return jsonify({"error": "Username taken"}), 400
    user = User(
        username=data['username'],
        password=generate_password_hash(data['password'])
    )
    db.session.add(user)
    db.session.commit()
    return jsonify({"message": "Success"})

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    user = User.query.filter_by(username=data['username']).first()
    if user and check_password_hash(user.password, data['password']):
        session['user_id'] = user.id
        return jsonify({"user": {"username": user.username, "balance": user.balance}})
    return jsonify({"error": "Invalid login"}), 401

@app.route('/api/auth/logout')
def logout():
    session.pop('user_id', None)
    return jsonify({"success": True})

# ================= SINGLE PLAYER SPIN =================
@app.route('/api/game/spin', methods=['POST'])
def spin():
    if 'user_id' not in session:
        return jsonify({"error": "Login required"}), 401

    user = User.query.get(session['user_id'])
    if user.balance < SPIN_COST:
        return jsonify({"error": "Insufficient funds"}), 400

    user.balance -= SPIN_COST
    reels = [random.choice(SYMBOLS) for _ in range(3)]

    reward = 0
    if reels[0] == reels[1] == reels[2]:
        reward = PAYOUTS[reels[0]]
    elif len(set(reels)) == 2:
        reward = 20

    user.balance += reward
    db.session.commit()

    return jsonify({
        "reels": reels,
        "reward": reward,
        "new_balance": user.balance
    })

# ================= MULTIPLAYER =================
@app.route('/api/match/join', methods=['POST'])
def join_match():
    uid = session.get('user_id')
    if not uid:
        return jsonify({"error": "Login required"}), 401

    waiting = MatchQueue.query.first()
    if waiting:
        match = Match(
            player1_id=waiting.user_id,
            player2_id=uid,
            status="waiting"
        )
        db.session.add(match)
        db.session.delete(waiting)
        db.session.commit()
        return jsonify({"match_id": match.id, "role": "player2"})
    else:
        db.session.add(MatchQueue(user_id=uid))
        db.session.commit()
        return jsonify({"status": "waiting"})

@app.route('/api/match/spin', methods=['POST'])
def match_spin():
    uid = session['user_id']
    match = Match.query.filter(
        ((Match.player1_id == uid) | (Match.player2_id == uid)) &
        (Match.status == "waiting")
    ).first()

    reels = [random.choice(SYMBOLS) for _ in range(3)]
    reward = PAYOUTS.get(reels[0], 20) if reels[0] == reels[1] == reels[2] else 20

    if uid == match.player1_id:
        match.p1_reward = reward
    else:
        match.p2_reward = reward

    if match.p1_reward is not None and match.p2_reward is not None:
        if match.p1_reward > match.p2_reward:
            match.winner_id = match.player1_id
        else:
            match.winner_id = match.player2_id

        winner = User.query.get(match.winner_id)
        winner.balance += 100
        match.status = "finished"

    db.session.commit()
    return jsonify({"reels": reels, "reward": reward})

# ================= LEADERBOARD =================
@app.route('/api/leaderboard')
def leaderboard():
    users = User.query.order_by(User.balance.desc()).limit(10).all()
    return jsonify([
        {"username": u.username, "balance": u.balance}
        for u in users
    ])

if __name__ == '__main__':
    app.run(debug=True)
