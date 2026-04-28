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
app.config['SECRET_KEY'] = 'your-secret-key-2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chat.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

# Создаём папки для загрузок
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

class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class PrivateMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    from_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    to_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    content = db.Column(db.Text)
    file_url = db.Column(db.String(200))
    file_type = db.Column(db.String(20))
    read = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Friend(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    friend_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    from_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    type = db.Column(db.String(50))
    content = db.Column(db.String(200))
    data = db.Column(db.String(500))
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
    # Создаём владельца, если нет
    if not User.query.filter_by(username='MrAizex').first():
        owner = User(
            username='MrAizex',
            user_id_display=generate_user_id(),
            password=generate_password_hash('admin123'),
            role='owner'
        )
        db.session.add(owner)
        db.session.commit()
        print("✅ Владелец MrAizex создан! Пароль: admin123")
    # Создаём стандартные комнаты, если нет
    for room_name in ['general', 'random', 'help']:
        if not Room.query.filter_by(name=room_name).first():
            room = Room(name=room_name, creator_id=1)
            db.session.add(room)
    db.session.commit()

def get_ru_role(role):
    roles = {
        'owner': 'Владелец',
        'admin': 'Администратор',
        'moderator': 'Модератор',
        'helper': 'Помощник',
        'user': 'Пользователь'
    }
    return roles.get(role, 'Пользователь')

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
    rooms = Room.query.all()
    return render_template('chat.html', user=user, rooms=rooms, get_ru_role=get_ru_role)

@app.route('/profile')
@login_required
def profile():
    user = User.query.get(session['user_id'])
    return render_template('profile_modal.html', user=user, get_ru_role=get_ru_role)

@app.route('/get_user/<int:user_id>')
@login_required
def get_user(user_id):
    user = User.query.get_or_404(user_id)
    return jsonify({
        'id': user.id,
        'username': user.username,
        'user_id_display': user.user_id_display,
        'bio': user.bio or '',
        'avatar': user.avatar,
        'role': get_ru_role(user.role),
        'status': user.status,
        'created_at': user.created_at.strftime('%d.%m.%Y')
    })

@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    user = User.query.get(session['user_id'])
    if 'avatar' in request.files:
        file = request.files['avatar']
        if file and file.filename:
            if user.last_avatar_change and datetime.utcnow() - user.last_avatar_change < timedelta(days=7):
                return jsonify({'error': 'Аватар можно менять раз в неделю!'}), 400
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
    return jsonify({'success': True})

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
    allowed = ['user', 'helper', 'moderator']
    if current_user.role == 'owner':
        allowed.append('admin')
    if target_user.role == 'owner' and current_user.role != 'owner':
        return jsonify({'error': 'Нельзя изменить роль владельца'}), 403
    if data['role'] in allowed and target_user.role != 'owner':
        target_user.role = data['role']
        db.session.commit()
        return jsonify({'success': True, 'new_role': get_ru_role(target_user.role)})
    return jsonify({'error': 'Недопустимая роль'}), 403

@app.route('/create_room', methods=['POST'])
@login_required
def create_room():
    data = request.get_json()
    name = data.get('name', '').strip().lower().replace(' ', '_')
    if not name:
        return jsonify({'error': 'Название не может быть пустым'}), 400
    if Room.query.filter_by(name=name).first():
        return jsonify({'error': 'Комната уже существует'}), 400
    room = Room(name=name, creator_id=session['user_id'])
    db.session.add(room)
    db.session.commit()
    return jsonify({'success': True, 'room_name': name})

@app.route('/delete_room', methods=['POST'])
@login_required
def delete_room():
    current_user = User.query.get(session['user_id'])
    if current_user.role not in ['owner', 'admin']:
        return jsonify({'error': 'Нет прав'}), 403
    data = request.get_json()
    room_name = data.get('room_name')
    if room_name in ['general', 'random', 'help']:
        return jsonify({'error': 'Нельзя удалить стандартную комнату'}), 400
    room = Room.query.filter_by(name=room_name).first()
    if not room:
        return jsonify({'error': 'Комната не найдена'}), 404
    # Удаляем сообщения из комнаты
    Message.query.filter_by(room=room_name).delete()
    db.session.delete(room)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/friend_request', methods=['POST'])
@login_required
def friend_request():
    data = request.get_json()
    friend = User.query.get(data['user_id'])
    if not friend:
        return jsonify({'error': 'Пользователь не найден'}), 404
    existing = Friend.query.filter(
        ((Friend.user_id == session['user_id']) & (Friend.friend_id == friend.id)) |
        ((Friend.user_id == friend.id) & (Friend.friend_id == session['user_id']))
    ).first()
    if existing:
        if existing.status == 'pending':
            return jsonify({'error': 'Запрос уже отправлен'}), 400
        elif existing.status == 'accepted':
            return jsonify({'error': 'Уже в друзьях'}), 400
    friend_req = Friend(user_id=session['user_id'], friend_id=friend.id, status='pending')
    db.session.add(friend_req)
    notif = Notification(
        user_id=friend.id,
        from_user_id=session['user_id'],
        type='friend_request',
        content=f"{session['username']} хочет добавить вас в друзья",
        data=str({'request_id': friend_req.id})
    )
    db.session.add(notif)
    db.session.commit()
    socketio.emit('new_notification', {
        'user_id': friend.id,
        'content': f"{session['username']} хочет добавить вас в друзья"
    })
    return jsonify({'success': True})

@app.route('/accept_friend', methods=['POST'])
@login_required
def accept_friend():
    data = request.get_json()
    friend_req = Friend.query.filter_by(id=data['request_id'], friend_id=session['user_id']).first()
    if friend_req:
        friend_req.status = 'accepted'
        db.session.commit()
        notif = Notification(
            user_id=friend_req.user_id,
            from_user_id=session['user_id'],
            type='friend_accepted',
            content=f"{session['username']} принял запрос в друзья"
        )
        db.session.add(notif)
        db.session.commit()
        socketio.emit('new_notification', {
            'user_id': friend_req.user_id,
            'content': f"{session['username']} принял запрос в друзья"
        })
        return jsonify({'success': True})
    return jsonify({'error': 'Запрос не найден'}), 404

@app.route('/decline_friend', methods=['POST'])
@login_required
def decline_friend():
    data = request.get_json()
    friend_req = Friend.query.filter_by(id=data['request_id'], friend_id=session['user_id']).first()
    if friend_req:
        db.session.delete(friend_req)
        db.session.commit()
        return jsonify({'success': True})
    return jsonify({'error': 'Запрос не найден'}), 404

@app.route('/get_notifications')
@login_required
def get_notifications():
    notifs = Notification.query.filter_by(user_id=session['user_id'], read=False).order_by(Notification.created_at.desc()).all()
    result = []
    for n in notifs:
        result.append({
            'id': n.id,
            'content': n.content,
            'type': n.type,
            'data': n.data,
            'from_user': User.query.get(n.from_user_id).username if n.from_user_id else None,
            'created_at': n.created_at.strftime('%H:%M')
        })
    return jsonify(result)

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
        'user_role': get_ru_role(User.query.get(m.user_id).role),
        'user_id': m.user_id,
        'avatar': User.query.get(m.user_id).avatar,
        'text': m.content,
        'file_url': m.file_url,
        'file_type': m.file_type,
        'timestamp': m.timestamp.strftime('%H:%M')
    } for m in messages])

@app.route('/get_users')
@login_required
def get_users():
    users = User.query.all()
    return jsonify([{
        'id': u.id,
        'username': u.username,
        'user_id_display': u.user_id_display,
        'status': u.status,
        'role': get_ru_role(u.role),
        'avatar': u.avatar
    } for u in users])

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
        'from_user_id': r.user_id,
        'from_user': User.query.get(r.user_id).username,
        'created_at': r.created_at.strftime('%H:%M')
    } for r in requests])

@app.route('/send_private_message', methods=['POST'])
@login_required
def send_private_message():
    data = request.get_json()
    to_user = User.query.get(data['to_user_id'])
    if not to_user:
        return jsonify({'error': 'Пользователь не найден'}), 404
    content = data.get('content', '').strip()
    file_url = data.get('file_url')
    file_type = data.get('file_type')
    pm = PrivateMessage(
        from_user_id=session['user_id'],
        to_user_id=to_user.id,
        content=content,
        file_url=file_url,
        file_type=file_type
    )
    db.session.add(pm)
    db.session.commit()
    # Отправляем уведомление получателю через socket
    socketio.emit('private_message', {
        'from_user': session['username'],
        'from_user_id': session['user_id'],
        'content': content,
        'file_url': file_url,
        'file_type': file_type,
        'timestamp': pm.timestamp.strftime('%H:%M')
    }, room=f'user_{to_user.id}')
    return jsonify({'success': True})

@app.route('/get_private_messages/<int:user_id>')
@login_required
def get_private_messages(user_id):
    messages = PrivateMessage.query.filter(
        ((PrivateMessage.from_user_id == session['user_id']) & (PrivateMessage.to_user_id == user_id)) |
        ((PrivateMessage.from_user_id == user_id) & (PrivateMessage.to_user_id == session['user_id']))
    ).order_by(PrivateMessage.timestamp).limit(100).all()
    return jsonify([{
        'id': m.id,
        'from_user': User.query.get(m.from_user_id).username,
        'from_user_id': m.from_user_id,
        'to_user_id': m.to_user_id,
        'content': m.content,
        'file_url': m.file_url,
        'file_type': m.file_type,
        'timestamp': m.timestamp.strftime('%H:%M'),
        'read': m.read
    } for m in messages])

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
            socketio.emit('user_offline', {'user_id': user.id})
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
        'user_role': get_ru_role(user.role),
        'user_id': user.id,
        'avatar': user.avatar,
        'text': text,
        'file_url': file_url,
        'file_type': file_type,
        'timestamp': msg.timestamp.strftime('%H:%M')
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

@socketio.on('join_private')
def handle_join_private(data):
    user_id = data.get('user_id')
    join_room(f'user_{user_id}')

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
