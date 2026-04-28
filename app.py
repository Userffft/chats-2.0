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
app.config['SECRET_KEY'] = 'secretkey2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chat.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

os.makedirs('uploads/images', exist_ok=True)
os.makedirs('uploads/audio', exist_ok=True)
os.makedirs('uploads/avatars', exist_ok=True)

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# ---------- МОДЕЛИ ----------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    user_id_display = db.Column(db.String(8), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    avatar = db.Column(db.String(200), default='')
    bio = db.Column(db.String(200), default='')
    status = db.Column(db.String(50), default='offline')
    role = db.Column(db.String(50), default='user')
    theme = db.Column(db.String(20), default='dark')
    last_avatar_change = db.Column(db.DateTime, default=None)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    is_default = db.Column(db.Boolean, default=False)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    content = db.Column(db.Text)
    file_url = db.Column(db.String(200))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Friend(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    friend_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    status = db.Column(db.String(20), default='pending')

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    from_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    content = db.Column(db.String(200))
    type = db.Column(db.String(50))
    read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

def generate_user_id():
    while True:
        length = random.choice([4,5,6,7,8])
        uid = ''.join(random.choices(string.ascii_letters + string.digits, k=length))
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
    if not User.query.filter_by(username='MrAizex').first():
        owner = User(username='MrAizex', user_id_display=generate_user_id(),
                     password=generate_password_hash('admin123'), role='owner')
        db.session.add(owner)
        db.session.commit()
    if not Room.query.filter_by(name='general').first():
        general = Room(name='general', is_default=True, created_by=1)
        db.session.add(general)
        db.session.commit()

# ---------- МАРШРУТЫ ----------
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('chat'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter((User.username==username)|(User.user_id_display==username)).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            user.status = 'online'
            db.session.commit()
            return redirect(url_for('chat'))
        return render_template('login.html', error='Неверный логин или пароль')
    return render_template('login.html')

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm = request.form['confirm_password']
        bio = request.form.get('bio','')
        if password != confirm:
            return render_template('register.html', error='Пароли не совпадают')
        if len(username) < 3:
            return render_template('register.html', error='Слишком короткое имя')
        if User.query.filter_by(username=username).first():
            return render_template('register.html', error='Пользователь уже существует')
        uid = generate_user_id()
        user = User(username=username, user_id_display=uid,
                    password=generate_password_hash(password), bio=bio)
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
    return render_template('profile.html', user=user)

@app.route('/user/<int:user_id>')
@login_required
def user_profile(user_id):
    user = User.query.get_or_404(user_id)
    current = User.query.get(session['user_id'])
    return render_template('user_profile.html', user=user, current_user=current)

@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    user = User.query.get(session['user_id'])
    if 'avatar' in request.files:
        file = request.files['avatar']
        if file and file.filename:
            filename = f"{user.id}_{datetime.utcnow().timestamp()}_{secure_filename(file.filename)}"
            path = os.path.join('uploads/avatars', filename)
            file.save(path)
            user.avatar = f'/uploads/avatars/{filename}'
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
    cur = User.query.get(session['user_id'])
    if cur.role not in ['owner','admin']:
        return jsonify({'error': 'Нет прав'}),403
    data = request.json
    target = User.query.get(data['user_id'])
    if not target:
        return jsonify({'error':'Не найден'}),404
    if cur.role == 'owner' and target.role != 'owner':
        target.role = data['role']
        db.session.commit()
        return jsonify({'success':True})
    elif cur.role == 'admin' and target.role in ['user','helper','moderator']:
        target.role = data['role']
        db.session.commit()
        return jsonify({'success':True})
    return jsonify({'error':'Недостаточно прав'}),403

@app.route('/friend_request', methods=['POST'])
@login_required
def friend_request():
    data = request.json
    friend = User.query.get(data['user_id'])
    if not friend:
        return jsonify({'error':'Не найден'}),404
    existing = Friend.query.filter(
        ((Friend.user_id==session['user_id']) & (Friend.friend_id==friend.id)) |
        ((Friend.user_id==friend.id) & (Friend.friend_id==session['user_id']))
    ).first()
    if existing:
        return jsonify({'error':'Запрос уже отправлен'}),400
    req = Friend(user_id=session['user_id'], friend_id=friend.id, status='pending')
    db.session.add(req)
    db.session.commit()
    notif = Notification(user_id=friend.id, from_user_id=session['user_id'],
                         content=f"{session['username']} хочет добавить вас в друзья", type='friend_request')
    db.session.add(notif)
    db.session.commit()
    return jsonify({'success':True})

@app.route('/accept_friend', methods=['POST'])
@login_required
def accept_friend():
    data = request.json
    req = Friend.query.get(data['request_id'])
    if req and req.friend_id == session['user_id']:
        req.status = 'accepted'
        db.session.commit()
        return jsonify({'success':True})
    return jsonify({'error':'Не найдено'}),404

@app.route('/decline_friend', methods=['POST'])
@login_required
def decline_friend():
    data = request.json
    req = Friend.query.get(data['request_id'])
    if req and req.friend_id == session['user_id']:
        db.session.delete(req)
        db.session.commit()
    return jsonify({'success':True})

@app.route('/get_notifications')
@login_required
def get_notifications():
    notifs = Notification.query.filter_by(user_id=session['user_id'], read=False).all()
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
    data = request.json
    n = Notification.query.get(data['notification_id'])
    if n and n.user_id == session['user_id']:
        n.read = True
        db.session.commit()
    return jsonify({'success':True})

@app.route('/get_messages')
@login_required
def get_messages():
    room_id = request.args.get('room_id', type=int)
    msgs = Message.query.filter_by(room_id=room_id).order_by(Message.timestamp).all()
    return jsonify([{
        'id': m.id,
        'username': User.query.get(m.user_id).username,
        'user_id': m.user_id,
        'avatar': User.query.get(m.user_id).avatar,
        'text': m.content,
        'file_url': m.file_url,
        'timestamp': m.timestamp.strftime('%H:%M')
    } for m in msgs])

@app.route('/get_users')
@login_required
def get_users():
    users = User.query.all()
    return jsonify([{
        'id': u.id,
        'username': u.username,
        'user_id_display': u.user_id_display,
        'status': u.status,
        'role': u.role,
        'avatar': u.avatar
    } for u in users])

@app.route('/get_friends')
@login_required
def get_friends():
    friends = Friend.query.filter(
        ((Friend.user_id==session['user_id']) | (Friend.friend_id==session['user_id'])),
        Friend.status=='accepted'
    ).all()
    result = []
    for f in friends:
        fid = f.friend_id if f.user_id==session['user_id'] else f.user_id
        friend = User.query.get(fid)
        if friend:
            result.append({'id': friend.id, 'username': friend.username})
    return jsonify(result)

@app.route('/get_friend_requests')
@login_required
def get_friend_requests():
    reqs = Friend.query.filter_by(friend_id=session['user_id'], status='pending').all()
    return jsonify([{
        'id': r.id,
        'from_user': User.query.get(r.user_id).username,
        'from_user_id': r.user_id
    } for r in reqs])

@app.route('/get_rooms')
@login_required
def get_rooms():
    rooms = Room.query.all()
    return jsonify([{'id': r.id, 'name': r.name, 'is_default': r.is_default} for r in rooms])

@app.route('/create_room', methods=['POST'])
@login_required
def create_room():
    data = request.json
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Введите название'}),400
    if Room.query.filter_by(name=name).first():
        return jsonify({'error': 'Комната уже существует'}),400
    room = Room(name=name, created_by=session['user_id'], is_default=False)
    db.session.add(room)
    db.session.commit()
    return jsonify({'success': True, 'room': {'id': room.id, 'name': room.name}})

@app.route('/rename_room', methods=['POST'])
@login_required
def rename_room():
    data = request.json
    room = Room.query.get(data['room_id'])
    if not room or room.is_default:
        return jsonify({'error': 'Нельзя переименовать'}),400
    user = User.query.get(session['user_id'])
    if user.role not in ['owner','admin'] and room.created_by != session['user_id']:
        return jsonify({'error': 'Нет прав'}),403
    room.name = data['new_name']
    db.session.commit()
    return jsonify({'success': True})

@app.route('/delete_room', methods=['POST'])
@login_required
def delete_room():
    data = request.json
    room = Room.query.get(data['room_id'])
    if not room or room.is_default:
        return jsonify({'error': 'Нельзя удалить главную комнату'}),400
    user = User.query.get(session['user_id'])
    if user.role not in ['owner','admin'] and room.created_by != session['user_id']:
        return jsonify({'error': 'Нет прав'}),403
    db.session.delete(room)
    db.session.commit()
    return jsonify({'success': True})

@app.route('/upload', methods=['POST'])
@login_required
def upload():
    file = request.files['file']
    if not file:
        return jsonify({'error': 'no file'}),400
    filename = f"{datetime.utcnow().timestamp()}_{secure_filename(file.filename)}"
    path = os.path.join('uploads/images', filename)
    file.save(path)
    return jsonify({'file_url': f'/uploads/images/{filename}'})

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

# ---------- SOCKET.IO ----------
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
    msg = Message(
        room_id=data['room_id'],
        user_id=session['user_id'],
        content=data.get('text', ''),
        file_url=data.get('file_url')
    )
    db.session.add(msg)
    db.session.commit()
    user = User.query.get(session['user_id'])
    emit('new_message', {
        'id': msg.id,
        'username': user.username,
        'user_id': user.id,
        'avatar': user.avatar,
        'text': msg.content,
        'file_url': msg.file_url,
        'timestamp': msg.timestamp.strftime('%H:%M')
    }, room=f'room_{msg.room_id}', broadcast=True)

@socketio.on('join_room')
def handle_join_room(data):
    join_room(f'room_{data["room_id"]}')

@socketio.on('typing')
def handle_typing(data):
    emit('user_typing', {
        'username': session['username'],
        'is_typing': data['is_typing']
    }, room=f'room_{data["room_id"]}', include_self=False)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
