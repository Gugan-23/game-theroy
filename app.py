from flask import Flask, render_template, jsonify, request, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import random

app = Flask(__name__)
app.secret_key = "multiplayer_secret_key_99"
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///jackpot.db'
db = SQLAlchemy(app)

# --- DATABASE MODELS ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    balance = db.Column(db.Integer, default=100) # Start with 100 points

with app.app_context():
    db.create_all()

# Symbols and their 3x match values
SYMBOLS = ['7️⃣', '💎', '🔔', '🍒', '🍋', '🍇']
PAYOUTS = {
    '7️⃣': 500,
    '💎': 200,
    '🔔': 100,
    '🍒': 50,
    '🍋': 30,
    '🍇': 20
}
SPIN_COST = 10

# --- ROUTES ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/auth/signup', methods=['POST'])
def signup():
    data = request.json
    if not data.get('username') or not data.get('password'):
        return jsonify({"error": "Missing fields"}), 400
    if User.query.filter_by(username=data['username']).first():
        return jsonify({"error": "User already exists"}), 400
    
    hashed_pw = generate_password_hash(data['password'])
    new_user = User(username=data['username'], password=hashed_pw)
    db.session.add(new_user)
    db.session.commit()
    return jsonify({"message": "Signup successful!"})

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    user = User.query.filter_by(username=data['username']).first()
    if user and check_password_hash(user.password, data['password']):
        session['user_id'] = user.id
        return jsonify({
            "message": "Logged in", 
            "user": {"username": user.username, "balance": user.balance}
        })
    return jsonify({"error": "Invalid credentials"}), 401

@app.route('/api/game/spin', methods=['POST'])
def spin():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    user = User.query.get(session['user_id'])
    if user.balance < SPIN_COST:
        return jsonify({"error": "Not enough points! Resetting to 50..."}, 400)

    # Deduct cost
    user.balance -= SPIN_COST
    
    # Generate Reels
    reels = [random.choice(SYMBOLS) for _ in range(3)]
    
    reward = 0
    is_win = False

    # Scoring Logic
    if reels[0] == reels[1] == reels[2]:
        # 3 of a kind
        reward = PAYOUTS[reels[0]]
        is_win = True
    elif reels[0] == reels[1] or reels[1] == reels[2] or reels[0] == reels[2]:
        # 2 of a kind (Small win)
        reward = 20
        is_win = True

    user.balance += reward
    db.session.commit()

    return jsonify({
        "reels": reels,
        "is_win": is_win,
        "reward": reward,
        "new_balance": user.balance
    })

@app.route('/api/leaderboard', methods=['GET'])
def leaderboard():
    # Rank by balance descending
    top_users = User.query.order_by(User.balance.desc()).limit(10).all()
    return jsonify([{"username": u.username, "balance": u.balance} for u in top_users])

@app.route('/api/auth/logout')
def logout():
    session.pop('user_id', None)
    return jsonify({"message": "Logged out"})

if __name__ == '__main__':
    app.run(debug=True)