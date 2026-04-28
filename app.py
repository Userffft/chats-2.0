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
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

os.makedirs('uploads/avatars', exist_ok=True)
os.makedirs('uploads/images', exist_ok=True)

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# ------------------- МОДЕЛИ -------------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    user_id_display = db.Column(db.String(8), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    avatar = db.Column(db.String(200), default='')
    bio = db.Column(db.String(200), default='')
    role = db.Column(db.String(20), default='user')
    theme = db.Column(db.String(20), default='dark')
    last_avatar_change = db.Column(db.DateTime, default=None)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='offline')

class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    is_default = db.Column(db.Boolean, default=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    content = db.Column(db.Text)
    file_url = db.Column(db.String(200))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class PrivateMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    from_user = db.Column(db.Integer, db.ForeignKey('user.id'))
    to_user = db.Column(db.Integer, db.ForeignKey('user.id'))
    content = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    read = db.Column(db.Boolean, default=False)

class Friend(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    friend_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    message = db.Column(db.String(200))
    link = db.Column(db.String(200))
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

def generate_user_id():
    while True:
        uid = ''.join(random.choices(string.ascii_letters + string.digits, k=random.choice([4,5,6,7,8])))
        if not User.query.filter_by(user_id_display=uid).first():
            return uid

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

with app.app_context():
    db.create_all()
    # Создаём владельца
    if not User.query.filter_by(username='MrAizex').first():
        owner = User(
            username='MrAizex',
            user_id_display=generate_user_id(),
            password=generate_password_hash('admin123'),
            role='owner'
        )
        db.session.add(owner)
        db.session.commit()
    # Создаём главную комнату
    if not Room.query.filter_by(is_default=True).first():
        general = Room(name='Общий чат', is_default=True, created_by=1)
        db.session.add(general)
        db.session.commit()

# ------------------- МАРШРУТЫ -------------------
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
        user = User.query.filter((User.username==username) | (User.user_id_display==username)).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            user.status = 'online'
            db.session.commit()
            socketio.emit('user_online', {'user_id': user.id, 'username': user.username}, broadcast=True)
            return redirect(url_for('chat'))
        return render_template('login.html', error='Неверный логин или пароль')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm = request.form['confirm_password']
        if password != confirm:
            return render_template('register.html', error='Пароли не совпадают')
        if len(username) < 3:
            return render_template('register.html', error='Имя слишком короткое')
        if User.query.filter_by(username=username).first():
            return render_template('register.html', error='Пользователь уже существует')
        uid = generate_user_id()
        user = User(username=username, user_id_display=uid, password=generate_password_hash(password))
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
    return render_template('chat.html', user=user, rooms=rooms)

@app.route('/profile')
@login_required
def profile():
    user = User.query.get(session['user_id'])
    can_change_avatar = True
    days_left = 0
    if user.last_avatar_change and datetime.utcnow() - user.last_avatar_change < timedelta(days=7):
        can_change_avatar = False
        days_left = 7 - (datetime.utcnow() - user.last_avatar_change).days
    return render_template('profile.html', user=user, can_change_avatar=can_change_avatar, days_left=days_left)

@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    user = User.query.get(session['user_id'])
    if 'avatar' in request.files:
        file = request.files['avatar']
        if file and file.filename:
            if user.last_avatar_change and datetime.utcnow() - user.last_avatar_change < timedelta(days=7):
                return jsonify({'error': 'Аватар можно менять раз в неделю'}), 400
            ext = file.filename.rsplit('.', 1)[-1].lower()
            filename = f"{user.id}_{int(datetime.utcnow().timestamp())}.{ext}"
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

@app.route('/update_role', methods=['POST'])
@login_required
def update_role():
    current = User.query.get(session['user_id'])
    data = request.json
    target = User.query.get(data['user_id'])
    if not target:
        return jsonify({'error': 'Пользователь не найден'}), 404
    if current.role != 'owner' and (current.role != 'admin' or target.role in ['owner', 'admin']):
        return jsonify({'error': 'Недостаточно прав'}), 403
    if current.role == 'owner' or (current.role == 'admin' and target.role not in ['owner', 'admin']):
        target.role = data['role']
        db.session.commit()
        return jsonify({'success': True})
    return jsonify({'error': 'Нельзя'}), 403

@app.route('/friend_request', methods=['POST'])
@login_required
def friend_request():
    data = request.json
    friend = User.query.get(data['user_id'])
    if not friend:
        return jsonify({'error': 'Пользователь не найден'}), 404
    existing = Friend.query.filter(
        ((Friend.user_id==session['user_id']) & (Friend.friend_id==friend.id)) |
        ((Friend.user_id==friend.id) & (Friend.friend_id==session['user_id']))
    ).first()
    if existing:
        return jsonify({'error': 'Запрос уже отправлен или вы уже друзья'}), 400
    req = Friend(user_id=session['user_id'], friend_id=friend.id, status='pending')
    db.session.add(req)
    # уведомление
    notif = Notification(user_id=friend.id, message=f"{session['username']} хочет добавить вас в друзья", link=f"/friend_accept/{req.id}")
    db.session.add(notif)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/friend_accept/<int:req_id>')
@login_required
def friend_accept(req_id):
    req = Friend.query.get(req_id)
    if req and req.friend_id == session['user_id']:
        req.status = 'accepted'
        db.session.commit()
    return redirect(url_for('chat'))

@app.route('/friend_decline/<int:req_id>')
@login_required
def friend_decline(req_id):
    req = Friend.query.get(req_id)
    if req and req.friend_id == session['user_id']:
        db.session.delete(req)
        db.session.commit()
    return redirect(url_for('chat'))

@app.route('/get_friends')
@login_required
def get_friends():
    friends = Friend.query.filter(
        ((Friend.user_id==session['user_id']) | (Friend.friend_id==session['user_id'])),
        Friend.status=='accepted'
    ).all()
    result = []
    for f in friends:
        fid = f.friend_id if f.user_id == session['user_id'] else f.user_id
        u = User.query.get(fid)
        if u:
            result.append({'id': u.id, 'username': u.username})
    return jsonify(result)

@app.route('/get_friend_requests')
@login_required
def get_friend_requests():
    reqs = Friend.query.filter_by(friend_id=session['user_id'], status='pending').all()
    return jsonify([{'id': r.id, 'from_user': User.query.get(r.user_id).username} for r in reqs])

@app.route('/get_notifications')
@login_required
def get_notifications():
    notifs = Notification.query.filter_by(user_id=session['user_id'], is_read=False).order_by(Notification.created_at.desc()).all()
    return jsonify([{'id': n.id, 'message': n.message, 'link': n.link} for n in notifs])

@app.route('/notifications/read', methods=['POST'])
@login_required
def read_notification():
    data = request.json
    n = Notification.query.get(data['id'])
    if n and n.user_id == session['user_id']:
        n.is_read = True
        db.session.commit()
    return jsonify({'ok': True})

@app.route('/get_messages')
@login_required
def get_messages():
    room_id = request.args.get('room_id', type=int)
    if not room_id:
        return jsonify([])
    msgs = Message.query.filter_by(room_id=room_id).order_by(Message.timestamp).limit(100).all()
    return jsonify([{
        'id': m.id,
        'username': User.query.get(m.user_id).username,
        'user_id': m.user_id,
        'avatar': User.query.get(m.user_id).avatar,
        'text': m.content,
        'file_url': m.file_url,
        'timestamp': m.timestamp.strftime('%H:%M')
    } for m in msgs])

@app.route('/get_private_messages')
@login_required
def get_private_messages():
    with_user = request.args.get('with_user', type=int)
    if not with_user:
        return jsonify([])
    msgs = PrivateMessage.query.filter(
        ((PrivateMessage.from_user==session['user_id']) & (PrivateMessage.to_user==with_user)) |
        ((PrivateMessage.from_user==with_user) & (PrivateMessage.to_user==session['user_id']))
    ).order_by(PrivateMessage.timestamp).all()
    # отметить как прочитанные
    for m in msgs:
        if m.to_user == session['user_id'] and not m.read:
            m.read = True
    db.session.commit()
    return jsonify([{
        'id': m.id,
        'from_user': m.from_user,
        'to_user': m.to_user,
        'from_username': User.query.get(m.from_user).username,
        'text': m.content,
        'timestamp': m.timestamp.strftime('%H:%M')
    } for m in msgs])

@app.route('/get_users')
@login_required
def get_users():
    users = User.query.all()
    return jsonify([{
        'id': u.id,
        'username': u.username,
        'status': u.status,
        'avatar': u.avatar,
        'role': u.role
    } for u in users if u.id != session['user_id']])

@app.route('/get_rooms')
@login_required
def get_rooms():
    rooms = Room.query.all()
    return jsonify([{'id': r.id, 'name': r.name, 'is_default': r.is_default} for r in rooms])

@app.route('/create_room', methods=['POST'])
@login_required
def create_room():
    name = request.json.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Введите название'}), 400
    if Room.query.filter_by(name=name).first():
        return jsonify({'error': 'Комната уже существует'}), 400
    room = Room(name=name, created_by=session['user_id'])
    db.session.add(room)
    db.session.commit()
    socketio.emit('room_created', {'id': room.id, 'name': room.name})
    return jsonify({'success': True, 'room': {'id': room.id, 'name': room.name}})

@app.route('/rename_room', methods=['POST'])
@login_required
def rename_room():
    data = request.json
    room = Room.query.get(data['room_id'])
    if not room:
        return jsonify({'error': 'Комната не найдена'}), 404
    if room.is_default:
        return jsonify({'error': 'Нельзя переименовать главную комнату'}), 400
    user = User.query.get(session['user_id'])
    if user.role not in ['owner','admin'] and room.created_by != session['user_id']:
        return jsonify({'error': 'Нет прав'}), 403
    new_name = data['new_name'].strip()
    if not new_name:
        return jsonify({'error': 'Введите название'}), 400
    if Room.query.filter_by(name=new_name).first():
        return jsonify({'error': 'Такое имя уже есть'}), 400
    room.name = new_name
    db.session.commit()
    socketio.emit('room_renamed', {'room_id': room.id, 'new_name': new_name})
    return jsonify({'success': True})

@app.route('/delete_room', methods=['POST'])
@login_required
def delete_room():
    data = request.json
    room = Room.query.get(data['room_id'])
    if not room or room.is_default:
        return jsonify({'error': 'Нельзя удалить главную комнату'}), 400
    user = User.query.get(session['user_id'])
    if user.role not in ['owner','admin'] and room.created_by != session['user_id']:
        return jsonify({'error': 'Нет прав'}), 403
    db.session.delete(room)
    db.session.commit()
    socketio.emit('room_deleted', {'room_id': room.id})
    return jsonify({'success': True})

@app.route('/upload', methods=['POST'])
@login_required
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'Нет файла'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Пустой файл'}), 400
    ext = file.filename.rsplit('.', 1)[-1].lower()
    filename = f"{session['user_id']}_{int(datetime.utcnow().timestamp())}.{ext}"
    path = os.path.join('uploads/images', filename)
    file.save(path)
    return jsonify({'url': f'/uploads/images/{filename}'})

@app.route('/uploads/<path:path>')
def uploaded_file(path):
    return send_from_directory('uploads', path)

@app.route('/logout')
def logout():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            user.status = 'offline'
            db.session.commit()
            socketio.emit('user_offline', {'user_id': user.id}, broadcast=True)
    session.clear()
    return redirect(url_for('login'))

# ------------------- SOCKET.IO -------------------
@socketio.on('connect')
def on_connect():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user and user.status != 'online':
            user.status = 'online'
            db.session.commit()
            emit('user_online', {'user_id': user.id, 'username': user.username}, broadcast=True)

@socketio.on('disconnect')
def on_disconnect():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            user.status = 'offline'
            db.session.commit()
            emit('user_offline', {'user_id': user.id}, broadcast=True)

@socketio.on('join_room')
def on_join_room(data):
    room_id = data['room_id']
    join_room(f'room_{room_id}')

@socketio.on('leave_room')
def on_leave_room(data):
    room_id = data['room_id']
    leave_room(f'room_{room_id}')

@socketio.on('send_message')
def on_send_message(data):
    if 'user_id' not in session:
        return
    room_id = data['room_id']
    text = data.get('text', '').strip()
    file_url = data.get('file_url', '')
    if not text and not file_url:
        return
    msg = Message(room_id=room_id, user_id=session['user_id'], content=text, file_url=file_url)
    db.session.add(msg)
    db.session.commit()
    user = User.query.get(session['user_id'])
    emit('new_message', {
        'id': msg.id,
        'username': user.username,
        'user_id': user.id,
        'avatar': user.avatar,
        'text': text,
        'file_url': file_url,
        'timestamp': msg.timestamp.strftime('%H:%M')
    }, room=f'room_{room_id}')

@socketio.on('send_private')
def on_send_private(data):
    if 'user_id' not in session:
        return
    to_user = data['to_user']
    text = data.get('text', '').strip()
    if not text:
        return
    pm = PrivateMessage(from_user=session['user_id'], to_user=to_user, content=text)
    db.session.add(pm)
    db.session.commit()
    user = User.query.get(session['user_id'])
    # отправить обоим
    emit('new_private', {
        'id': pm.id,
        'from_user': user.id,
        'from_username': user.username,
        'text': text,
        'timestamp': pm.timestamp.strftime('%H:%M')
    }, room=f'private_{to_user}')
    emit('new_private', {
        'id': pm.id,
        'from_user': user.id,
        'from_username': user.username,
        'text': text,
        'timestamp': pm.timestamp.strftime('%H:%M')
    }, room=f'private_{session["user_id"]}')

@socketio.on('join_private')
def on_join_private(data):
    user_id = data['user_id']
    join_room(f'private_{user_id}')

@socketio.on('typing')
def on_typing(data):
    if 'user_id' in session:
        emit('user_typing', {'username': session['username'], 'room_id': data['room_id'], 'is_typing': data['is_typing']}, room=f'room_{data["room_id"]}', include_self=False)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
