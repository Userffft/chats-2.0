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
app.config['SECRET_KEY'] = 'supersecretkeychangeit'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chat.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

os.makedirs('uploads/images', exist_ok=True)
os.makedirs('uploads/audio', exist_ok=True)
os.makedirs('uploads/avatars', exist_ok=True)

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Модели
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    user_id_display = db.Column(db.String(8), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    avatar = db.Column(db.String(200), default='')
    bio = db.Column(db.String(200), default='')
    status = db.Column(db.String(50), default='online')
    role = db.Column(db.String(50), default='user')
    theme = db.Column(db.String(20), default='dark')
    last_avatar_change = db.Column(db.DateTime, default=None)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    is_default = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('room.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    content = db.Column(db.Text)
    file_url = db.Column(db.String(200))
    file_type = db.Column(db.String(20))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class PrivateMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    from_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    to_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    content = db.Column(db.Text)
    file_url = db.Column(db.String(200))
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
    # Создаём владельца MrAizex
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
    # Создаём главную комнату
    if not Room.query.filter_by(name='general').first():
        general = Room(name='general', is_default=True, created_by=1)
        db.session.add(general)
        db.session.commit()

# Маршруты
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
        user = User(username=username, user_id_display=uid, password=generate_password_hash(password), bio=bio)
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
    can_change = True
    days_left = 0
    if user.last_avatar_change and datetime.utcnow() - user.last_avatar_change < timedelta(days=7):
        can_change = False
        days_left = 7 - (datetime.utcnow() - user.last_avatar_change).days
    return render_template('profile.html', user=user, can_change_avatar=can_change, days_left=days_left)

@app.route('/user/<int:user_id>')
@login_required
def user_profile(user_id):
    user = User.query.get_or_404(user_id)
    current_user = User.query.get(session['user_id'])
    return render_template('user_profile.html', user=user, current_user=current_user)

@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    user = User.query.get(session['user_id'])
    # Обновление аватара
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
        return jsonify({'error':'Запрос уже отправлен или вы уже друзья'}),400
    req = Friend(user_id=session['user_id'], friend_id=friend.id, status='pending')
    db.session.add(req)
    db.session.commit()
    notif = Notification(user_id=friend.id, from_user_id=session['user_id'], type='friend_request',
                         content=f"{session['username']} хочет добавить вас в друзья", data=str({'request_id':req.id}))
    db.session.add(notif)
    db.session.commit()
    socketio.emit('new_notification', {'user_id':friend.id, 'content':notif.content})
    return jsonify({'success':True})

@app.route('/accept_friend', methods=['POST'])
@login_required
def accept_friend():
    data = request.json
    req = Friend.query.get(data['request_id'])
    if not req or req.friend_id != session['user_id']:
        return jsonify({'error':'Не найдено'}),404
    req.status = 'accepted'
    db.session.commit()
    notif = Notification(user_id=req.user_id, from_user_id=session['user_id'], type='friend_accepted',
                         content=f"{session['username']} принял запрос в друзья")
    db.session.add(notif)
    db.session.commit()
    socketio.emit('new_notification', {'user_id':req.user_id, 'content':notif.content})
    return jsonify({'success':True})

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
    if room_id:
        msgs = Message.query.filter_by(room_id=room_id).order_by(Message.timestamp).limit(100).all()
    else:
        msgs = []
    return jsonify([{
        'id': m.id,
        'username': User.query.get(m.user_id).username,
        'user_role': User.query.get(m.user_id).role,
        'user_id': m.user_id,
        'avatar': User.query.get(m.user_id).avatar,
        'text': m.content,
        'file_url': m.file_url,
        'file_type': m.file_type,
        'timestamp': m.timestamp.strftime('%H:%M')
    } for m in msgs])

@app.route('/get_private_messages')
@login_required
def get_private_messages():
    with_user = request.args.get('with_user', type=int)
    if not with_user:
        return jsonify([])
    msgs = PrivateMessage.query.filter(
        ((PrivateMessage.from_user_id==session['user_id']) & (PrivateMessage.to_user_id==with_user)) |
        ((PrivateMessage.from_user_id==with_user) & (PrivateMessage.to_user_id==session['user_id']))
    ).order_by(PrivateMessage.timestamp).all()
    return jsonify([{
        'id': m.id,
        'from_user_id': m.from_user_id,
        'to_user_id': m.to_user_id,
        'from_username': User.query.get(m.from_user_id).username,
        'text': m.content,
        'file_url': m.file_url,
        'timestamp': m.timestamp.strftime('%H:%M'),
        'read': m.read
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
            result.append({
                'id': friend.id,
                'username': friend.username,
                'user_id_display': friend.user_id_display,
                'status': friend.status
            })
    return jsonify(result)

@app.route('/get_friend_requests')
@login_required
def get_friend_requests():
    reqs = Friend.query.filter_by(friend_id=session['user_id'], status='pending').all()
    return jsonify([{
        'id': r.id,
        'from_user_id': r.user_id,
        'from_user': User.query.get(r.user_id).username,
        'created_at': r.created_at.strftime('%H:%M')
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
        return jsonify({'error': 'Название не может быть пустым'}),400
    if Room.query.filter_by(name=name).first():
        return jsonify({'error': 'Комната уже существует'}),400
    room = Room(name=name, created_by=session['user_id'], is_default=False)
    db.session.add(room)
    db.session.commit()
    socketio.emit('room_created', {'id': room.id, 'name': room.name})
    return jsonify({'success': True, 'room': {'id': room.id, 'name': room.name}})

@app.route('/delete_room', methods=['POST'])
@login_required
def delete_room():
    data = request.json
    room_id = data.get('room_id')
    room = Room.query.get(room_id)
    if not room or room.is_default:
        return jsonify({'error': 'Нельзя удалить главную комнату'}),400
    # права: админ или создатель
    user = User.query.get(session['user_id'])
    if user.role not in ['owner','admin'] and room.created_by != session['user_id']:
        return jsonify({'error': 'Нет прав'}),403
    db.session.delete(room)
    db.session.commit()
    socketio.emit('room_deleted', {'room_id': room_id})
    return jsonify({'success': True})

@app.route('/upload', methods=['POST'])
@login_required
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'no file'}),400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'empty'}),400
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

# SocketIO
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
    room_id = data.get('room_id')
    text = data.get('text', '').strip()
    file_url = data.get('file_url')
    file_type = data.get('file_type')
    if not room_id:
        return
    msg = Message(
        room_id=room_id,
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
        'avatar': user.avatar,
        'text': text,
        'file_url': file_url,
        'file_type': file_type,
        'timestamp': msg.timestamp.strftime('%H:%M'),
        'room_id': room_id
    }, room=f'room_{room_id}', broadcast=True)

@socketio.on('private_message')
def handle_private_message(data):
    if 'user_id' not in session:
        return
    to_user_id = data.get('to_user_id')
    text = data.get('text', '').strip()
    if not to_user_id:
        return
    pm = PrivateMessage(
        from_user_id=session['user_id'],
        to_user_id=to_user_id,
        content=text
    )
    db.session.add(pm)
    db.session.commit()
    user = User.query.get(session['user_id'])
    # отправить получателю
    emit('new_private_message', {
        'id': pm.id,
        'from_user_id': user.id,
        'from_username': user.username,
        'text': text,
        'timestamp': pm.timestamp.strftime('%H:%M')
    }, room=f'private_{to_user_id}')
    # отправить отправителю
    emit('new_private_message', {
        'id': pm.id,
        'from_user_id': user.id,
        'from_username': user.username,
        'text': text,
        'timestamp': pm.timestamp.strftime('%H:%M')
    }, room=f'private_{session["user_id"]}')

@socketio.on('join_room')
def handle_join_room(data):
    room_id = data.get('room_id')
    if room_id:
        join_room(f'room_{room_id}')

@socketio.on('join_private')
def handle_join_private(data):
    user_id = data.get('user_id')
    if user_id:
        join_room(f'private_{user_id}')

@socketio.on('typing')
def handle_typing(data):
    if 'user_id' in session:
        emit('user_typing', {
            'username': session['username'],
            'is_typing': data.get('is_typing', False),
            'room_id': data.get('room_id')
        }, room=f'room_{data.get("room_id")}', include_self=False)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
