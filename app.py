import os
import random
import string
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret-key-2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chat.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

os.makedirs('uploads/images', exist_ok=True)
os.makedirs('uploads/audio', exist_ok=True)
os.makedirs('uploads/avatars', exist_ok=True)

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# ============ МОДЕЛИ ============

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    user_id_display = db.Column(db.String(8), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    avatar = db.Column(db.String(200), default='')
    bio = db.Column(db.String(200), default='')
    status = db.Column(db.String(50), default='online')
    role = db.Column(db.String(50), default='user')  # owner, admin, moderator, helper, user
    theme = db.Column(db.String(20), default='dark')
    last_avatar_change = db.Column(db.DateTime, default=None)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room = db.Column(db.String(50), default='general')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    content = db.Column(db.Text)
    file_url = db.Column(db.String(200))
    file_type = db.Column(db.String(20))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Friend(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    friend_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    status = db.Column(db.String(20), default='pending')  # pending, accepted, blocked
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    from_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    type = db.Column(db.String(50))
    content = db.Column(db.String(200))
    read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

def generate_user_id():
    while True:
        length = random.choice([4, 5, 6, 7, 8])
        user_id = ''.join(random.choices(string.ascii_letters + string.digits, k=length))
        if not User.query.filter_by(user_id_display=user_id).first():
            return user_id

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def role_required(roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('login'))
            user = User.query.get(session['user_id'])
            if user.role not in roles:
                return jsonify({'error': 'Нет прав'}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator

with app.app_context():
    db.create_all()
    # Создаём владельца если нет
    if not User.query.filter_by(role='owner').first():
        owner = User(
            username='MrAizex',
            user_id_display=generate_user_id(),
            password=generate_password_hash('admin123'),
            role='owner'
        )
        db.session.add(owner)
        db.session.commit()
        print("✅ Владелец MrAizex создан! Пароль: admin123")

# ============ МАРШРУТЫ ============

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('chat'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter(
            (User.username == username) | (User.user_id_display == username)
        ).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            user.status = 'online'
            db.session.commit()
            return redirect(url_for('chat'))
        return render_template('login.html', error='Неверный логин или пароль')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm = request.form['confirm_password']
        bio = request.form.get('bio', '')
        
        if password != confirm:
            return render_template('register.html', error='Пароли не совпадают')
        if len(username) < 3:
            return render_template('register.html', error='Имя слишком короткое')
        if User.query.filter_by(username=username).first():
            return render_template('register.html', error='Пользователь уже существует')
        
        user_id = generate_user_id()
        user = User(
            username=username,
            user_id_display=user_id,
            password=generate_password_hash(password),
            bio=bio
        )
        db.session.add(user)
        db.session.commit()
        
        session['user_id'] = user.id
        session['username'] = user.username
        session['role'] = user.role
        return redirect(url_for('chat'))
    
    return render_template('register.html')

@app.route('/chat')
@login_required
def chat():
    user = User.query.get(session['user_id'])
    return render_template('chat.html', user=user)

@app.route('/profile')
@login_required
def profile():
    user = User.query.get(session['user_id'])
    can_change = True
    days_left = 0
    if user.last_avatar_change:
        if datetime.utcnow() - user.last_avatar_change < timedelta(days=7):
            can_change = False
            days_left = 7 - (datetime.utcnow() - user.last_avatar_change).days
    return render_template('profile.html', user=user, can_change_avatar=can_change, days_left=days_left)

@app.route('/user/<int:user_id>')
@login_required
def user_profile(user_id):
    user = User.query.get_or_404(user_id)
    current_user = User.query.get(session['user_id'])
    is_friend = Friend.query.filter(
        ((Friend.user_id == session['user_id']) & (Friend.friend_id == user_id)) |
        ((Friend.user_id == user_id) & (Friend.friend_id == session['user_id']))
    ).first()
    return render_template('user_profile.html', user=user, current_user=current_user, is_friend=is_friend)

@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    user = User.query.get(session['user_id'])
    
    if 'avatar' in request.files:
        file = request.files['avatar']
        if file and file.filename:
            if user.last_avatar_change and datetime.utcnow() - user.last_avatar_change < timedelta(days=7):
                return render_template('profile.html', user=user, error='Аватар можно менять раз в неделю!')
            
            filename = f"{user.id}_{datetime.utcnow().timestamp()}_{secure_filename(file.filename)}"
            path = os.path.join('uploads/avatars', filename)
            file.save(path)
            user.avatar = f'/uploads/avatars/{filename}'
            user.last_avatar_change = datetime.utcnow()
    
    if 'bio' in request.form:
        user.bio = request.form['bio']
    
    if 'theme' in request.form:
        user.theme = request.form['theme']
    
    if 'new_password' in request.form and request.form['new_password']:
        user.password = generate_password_hash(request.form['new_password'])
    
    db.session.commit()
    return render_template('profile.html', user=user, success='Профиль обновлён!')

@app.route('/change_role', methods=['POST'])
@login_required
def change_role():
    current_user = User.query.get(session['user_id'])
    if current_user.role not in ['owner', 'admin']:
        return jsonify({'error': 'Нет прав'}), 403
    
    data = request.get_json()
    target_user = User.query.get(data['user_id'])
    if not target_user:
        return jsonify({'error': 'Пользователь не найден'}), 404
    
    if current_user.role == 'owner' and target_user.role != 'owner':
        target_user.role = data['role']
        db.session.commit()
        return jsonify({'success': True, 'new_role': target_user.role})
    elif current_user.role == 'admin' and target_user.role in ['user', 'helper', 'moderator']:
        target_user.role = data['role']
        db.session.commit()
        return jsonify({'success': True, 'new_role': target_user.role})
    
    return jsonify({'error': 'Недостаточно прав'}), 403

@app.route('/friend_request', methods=['POST'])
@login_required
def friend_request():
    data = request.get_json()
    friend = User.query.filter_by(user_id_display=data['user_id']).first()
    if not friend:
        return jsonify({'error': 'Пользователь не найден'}), 404
    
    existing = Friend.query.filter(
        ((Friend.user_id == session['user_id']) & (Friend.friend_id == friend.id)) |
        ((Friend.user_id == friend.id) & (Friend.friend_id == session['user_id']))
    ).first()
    
    if existing:
        return jsonify({'error': 'Запрос уже отправлен'}), 400
    
    friend_req = Friend(user_id=session['user_id'], friend_id=friend.id, status='pending')
    db.session.add(friend_req)
    
    notif = Notification(
        user_id=friend.id,
        from_user_id=session['user_id'],
        type='friend_request',
        content=f"{session['username']} хочет добавить вас в друзья"
    )
    db.session.add(notif)
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/accept_friend', methods=['POST'])
@login_required
def accept_friend():
    data = request.get_json()
    friend_req = Friend.query.filter_by(id=data['request_id'], friend_id=session['user_id']).first()
    if friend_req:
        friend_req.status = 'accepted'
        db.session.commit()
        return jsonify({'success': True})
    return jsonify({'error': 'Запрос не найден'}), 404

@app.route('/get_notifications')
@login_required
def get_notifications():
    notifs = Notification.query.filter_by(user_id=session['user_id'], read=False).order_by(Notification.created_at.desc()).limit(20).all()
    return jsonify([{
        'id': n.id,
        'content': n.content,
        'type': n.type,
        'from_user': User.query.get(n.from_user_id).username if n.from_user_id else None,
        'created_at': n.created_at.strftime('%H:%M')
    } for n in notifs])

@app.route('/mark_notification_read', methods=['POST'])
@login_required
def mark_notification_read():
    data = request.get_json()
    notif = Notification.query.get(data['notification_id'])
    if notif and notif.user_id == session['user_id']:
        notif.read = True
        db.session.commit()
    return jsonify({'success': True})

@app.route('/get_messages')
@login_required
def get_messages():
    room = request.args.get('room', 'general')
    messages = Message.query.filter_by(room=room).order_by(Message.timestamp).limit(100).all()
    return jsonify([{
        'id': m.id,
        'username': User.query.get(m.user_id).username,
        'user_role': User.query.get(m.user_id).role,
        'user_id': m.user_id,
        'text': m.content,
        'file_url': m.file_url,
        'file_type': m.file_type,
        'timestamp': m.timestamp.strftime('%H:%M'),
        'avatar': User.query.get(m.user_id).avatar
    } for m in messages])

@app.route('/get_users')
@login_required
def get_users():
    users = User.query.all()
    current_user_id = session['user_id']
    return jsonify([{
        'id': u.id,
        'username': u.username,
        'user_id_display': u.user_id_display,
        'status': u.status,
        'role': u.role,
        'avatar': u.avatar
    } for u in users if u.id != current_user_id])

@app.route('/get_friends')
@login_required
def get_friends():
    friends = Friend.query.filter(
        ((Friend.user_id == session['user_id']) | (Friend.friend_id == session['user_id'])),
        Friend.status == 'accepted'
    ).all()
    result = []
    for f in friends:
        friend_id = f.friend_id if f.user_id == session['user_id'] else f.user_id
        friend = User.query.get(friend_id)
        if friend:
            result.append({
                'id': friend.id,
                'username': friend.username,
                'user_id_display': friend.user_id_display,
                'status': friend.status,
                'avatar': friend.avatar
            })
    return jsonify(result)

@app.route('/get_friend_requests')
@login_required
def get_friend_requests():
    requests = Friend.query.filter_by(friend_id=session['user_id'], status='pending').all()
    return jsonify([{
        'id': r.id,
        'from_user': User.query.get(r.user_id).username,
        'from_user_id': r.user_id,
        'created_at': r.created_at.strftime('%H:%M')
    } for r in requests])

@app.route('/upload', methods=['POST'])
@login_required
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'no file'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'empty'}), 400
    
    file_type = 'image' if file.content_type.startswith('image/') else 'audio'
    folder = 'images' if file_type == 'image' else 'audio'
    filename = f"{datetime.utcnow().timestamp()}_{secure_filename(file.filename)}"
    path = os.path.join('uploads', folder, filename)
    file.save(path)
    return jsonify({'file_url': f'/uploads/{folder}/{filename}', 'file_type': file_type})

@app.route('/uploads/<path:path>')
def serve_upload(path):
    return send_from_directory('uploads', path)

@app.route('/logout')
def logout():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            user.status = 'offline'
            db.session.commit()
    session.clear()
    return redirect(url_for('login'))

# ============ SOCKET.IO ============

@socketio.on('connect')
def handle_connect():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            user.status = 'online'
            db.session.commit()
            emit('user_online', {'user_id': user.id, 'username': user.username}, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            user.status = 'offline'
            db.session.commit()
            emit('user_offline', {'user_id': user.id}, broadcast=True)

@socketio.on('message')
def handle_message(data):
    if 'user_id' not in session:
        return
    room = data.get('room', 'general')
    text = data.get('text', '').strip()
    file_url = data.get('file_url')
    file_type = data.get('file_type')
    
    msg = Message(
        room=room,
        user_id=session['user_id'],
        content=text if text else None,
        file_url=file_url,
        file_type=file_type
    )
    db.session.add(msg)
    db.session.commit()
    
    user = User.query.get(session['user_id'])
    emit('new_message', {
        'id': msg.id,
        'username': user.username,
        'user_role': user.role,
        'user_id': user.id,
        'text': text,
        'file_url': file_url,
        'file_type': file_type,
        'timestamp': msg.timestamp.strftime('%H:%M'),
        'avatar': user.avatar
    }, room=room, broadcast=True)

@socketio.on('typing')
def handle_typing(data):
    if 'user_id' in session:
        emit('user_typing', {
            'username': session['username'],
            'is_typing': data.get('is_typing', False)
        }, room=data.get('room', 'general'), include_self=False)

@socketio.on('join')
def handle_join(data):
    room = data.get('room', 'general')
    join_room(room)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
