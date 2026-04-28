import os
import json
from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from functools import wraps

# Создаём приложение
app = Flask(__name__)

# Конфигурация
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')
database_url = os.environ.get('DATABASE_URL', 'sqlite:///chat.db')
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER_IMAGES'] = 'uploads/images'
app.config['UPLOAD_FOLDER_AUDIO'] = 'uploads/audio'
app.config['UPLOAD_FOLDER_AVATARS'] = 'uploads/avatars'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max

# Создаём папки
for folder in [app.config['UPLOAD_FOLDER_IMAGES'], app.config['UPLOAD_FOLDER_AUDIO'], app.config['UPLOAD_FOLDER_AVATARS']]:
    os.makedirs(folder, exist_ok=True)

# Инициализация
db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Модели базы данных
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    avatar = db.Column(db.String(200), default='/static/default-avatar.png')
    status = db.Column(db.String(50), default='online')  # online, offline, away
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    bio = db.Column(db.String(200), default='')
    room = db.Column(db.String(50), default='general')

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room = db.Column(db.String(50), default='general')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    content = db.Column(db.Text)
    file_url = db.Column(db.String(200))
    file_type = db.Column(db.String(20))
    reply_to = db.Column(db.Integer, default=None)  # ID сообщения, на которое отвечают
    edited = db.Column(db.Boolean, default=False)
    edited_at = db.Column(db.DateTime)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class PrivateMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    from_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    to_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    content = db.Column(db.Text)
    file_url = db.Column(db.String(200))
    file_type = db.Column(db.String(20))
    read = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# Хранилище для статусов печати и онлайн пользователей
typing_users = {}
online_users = set()

# Создаём таблицы
with app.app_context():
    db.create_all()

# Декоратор для проверки авторизации
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# HTML шаблоны
LOGIN_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Вход в чат</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            position: relative;
            overflow: hidden;
        }
        body::before {
            content: '';
            position: absolute;
            width: 200%;
            height: 200%;
            background: radial-gradient(circle, rgba(255,255,255,0.1) 1px, transparent 1px);
            background-size: 50px 50px;
            animation: move 20s linear infinite;
        }
        @keyframes move {
            0% { transform: translate(0, 0); }
            100% { transform: translate(50px, 50px); }
        }
        .container {
            background: rgba(255,255,255,0.95);
            border-radius: 30px;
            box-shadow: 0 30px 70px rgba(0,0,0,0.3);
            overflow: hidden;
            width: 450px;
            max-width: 90%;
            position: relative;
            z-index: 1;
            animation: slideIn 0.5s ease-out;
        }
        @keyframes slideIn {
            from { opacity: 0; transform: translateY(-50px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px;
            text-align: center;
        }
        .header h1 { font-size: 32px; margin-bottom: 10px; }
        .header p { opacity: 0.9; font-size: 14px; }
        .form-container { padding: 40px; }
        .form-group { margin-bottom: 25px; }
        label { display: block; margin-bottom: 8px; color: #333; font-weight: 500; }
        input {
            width: 100%;
            padding: 12px 15px;
            border: 2px solid #e0e0e0;
            border-radius: 12px;
            font-size: 14px;
            transition: all 0.3s;
        }
        input:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102,126,234,0.1);
        }
        button {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 12px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
        }
        button:hover { transform: translateY(-2px); box-shadow: 0 10px 25px rgba(102,126,234,0.3); }
        .footer { text-align: center; margin-top: 25px; color: #666; }
        .footer a { color: #667eea; text-decoration: none; font-weight: 600; }
        .footer a:hover { text-decoration: underline; }
        .error {
            background: #fee;
            color: #c33;
            padding: 12px;
            border-radius: 10px;
            margin-bottom: 20px;
            text-align: center;
        }
        .emoji {
            font-size: 24px;
            display: inline-block;
            animation: wave 1s infinite;
        }
        @keyframes wave {
            0%, 100% { transform: rotate(0deg); }
            25% { transform: rotate(20deg); }
            75% { transform: rotate(-20deg); }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>💬 <span class="emoji">✨</span> ChatVerse</h1>
            <p>Войдите в свой аккаунт</p>
        </div>
        <div class="form-container">
            {% if error %}
                <div class="error">{{ error }}</div>
            {% endif %}
            <form method="post">
                <div class="form-group">
                    <label>👤 Имя пользователя</label>
                    <input type="text" name="username" required autofocus>
                </div>
                <div class="form-group">
                    <label>🔒 Пароль</label>
                    <input type="password" name="password" required>
                </div>
                <button type="submit">Войти</button>
            </form>
            <div class="footer">
                Нет аккаунта? <a href="/register">Зарегистрироваться</a>
            </div>
        </div>
    </div>
</body>
</html>
'''

REGISTER_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Регистрация - ChatVerse</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .container {
            background: rgba(255,255,255,0.95);
            border-radius: 30px;
            box-shadow: 0 30px 70px rgba(0,0,0,0.3);
            overflow: hidden;
            width: 450px;
            max-width: 90%;
            animation: slideIn 0.5s ease-out;
        }
        @keyframes slideIn {
            from { opacity: 0; transform: translateY(-50px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px;
            text-align: center;
        }
        .header h1 { font-size: 32px; margin-bottom: 10px; }
        .header p { opacity: 0.9; font-size: 14px; }
        .form-container { padding: 40px; }
        .form-group { margin-bottom: 25px; }
        label { display: block; margin-bottom: 8px; color: #333; font-weight: 500; }
        input {
            width: 100%;
            padding: 12px 15px;
            border: 2px solid #e0e0e0;
            border-radius: 12px;
            font-size: 14px;
            transition: all 0.3s;
        }
        input:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102,126,234,0.1);
        }
        button {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 12px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
        }
        button:hover { transform: translateY(-2px); box-shadow: 0 10px 25px rgba(102,126,234,0.3); }
        .footer { text-align: center; margin-top: 25px; color: #666; }
        .footer a { color: #667eea; text-decoration: none; font-weight: 600; }
        .error {
            background: #fee;
            color: #c33;
            padding: 12px;
            border-radius: 10px;
            margin-bottom: 20px;
            text-align: center;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📝 ChatVerse</h1>
            <p>Создайте новый аккаунт</p>
        </div>
        <div class="form-container">
            {% if error %}
                <div class="error">{{ error }}</div>
            {% endif %}
            <form method="post">
                <div class="form-group">
                    <label>👤 Имя пользователя</label>
                    <input type="text" name="username" required autofocus minlength="3" maxlength="20">
                </div>
                <div class="form-group">
                    <label>🔒 Пароль</label>
                    <input type="password" name="password" required minlength="4">
                </div>
                <div class="form-group">
                    <label>🔒 Подтверждение пароля</label>
                    <input type="password" name="confirm_password" required>
                </div>
                <button type="submit">Зарегистрироваться</button>
            </form>
            <div class="footer">
                Уже есть аккаунт? <a href="/login">Войти</a>
            </div>
        </div>
    </div>
</body>
</html>
'''

# Маршруты
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
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['username'] = user.username
            user.status = 'online'
            user.last_seen = datetime.utcnow()
            db.session.commit()
            return redirect(url_for('chat'))
        return render_template_string(LOGIN_TEMPLATE, error='Неверное имя пользователя или пароль')
    return render_template_string(LOGIN_TEMPLATE)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        
        if password != confirm_password:
            return render_template_string(REGISTER_TEMPLATE, error='Пароли не совпадают')
        
        if len(username) < 3:
            return render_template_string(REGISTER_TEMPLATE, error='Имя пользователя должно содержать минимум 3 символа')
        
        if User.query.filter_by(username=username).first():
            return render_template_string(REGISTER_TEMPLATE, error='Пользователь уже существует')
        
        hashed_password = generate_password_hash(password)
        user = User(username=username, password=hashed_password, bio='', avatar='')
        db.session.add(user)
        db.session.commit()
        return redirect(url_for('login'))
    
    return render_template_string(REGISTER_TEMPLATE)

@app.route('/chat')
@login_required
def chat():
    user = User.query.get(session['user_id'])
    messages = Message.query.filter_by(room='general').order_by(Message.timestamp).limit(100).all()
    users = User.query.all()
    return render_template_string(CHAT_TEMPLATE, username=session['username'], messages=messages, users=users)

@app.route('/logout')
def logout():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            user.status = 'offline'
            db.session.commit()
    session.clear()
    return redirect(url_for('login'))

@app.route('/upload', methods=['POST'])
@login_required
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'no file'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'empty filename'}), 400
    
    file_type = 'image' if file.content_type.startswith('image/') else 'audio'
    subfolder = 'images' if file_type == 'image' else 'audio'
    filename = f"{datetime.utcnow().timestamp()}_{secure_filename(file.filename)}"
    save_path = os.path.join('uploads', subfolder, filename)
    file.save(save_path)
    file_url = f"/{save_path}"
    return jsonify({'file_url': file_url, 'file_type': file_type})

@app.route('/search', methods=['GET'])
@login_required
def search_messages():
    query = request.args.get('q', '')
    if query:
        messages = Message.query.filter(
            Message.content.contains(query),
            Message.room == 'general'
        ).order_by(Message.timestamp.desc()).limit(50).all()
        return jsonify([{
            'id': m.id,
            'content': m.content,
            'username': User.query.get(m.user_id).username,
            'timestamp': m.timestamp.strftime('%H:%M'
        )} for m in messages])
    return jsonify([])

# SocketIO события
@socketio.on('connect')
def handle_connect():
    if 'user_id' in session:
        online_users.add(session['user_id'])
        user = User.query.get(session['user_id'])
        if user:
            user.status = 'online'
            db.session.commit()
        emit('user_online', {'user_id': session['user_id'], 'username': session['username']}, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    if 'user_id' in session:
        online_users.discard(session['user_id'])
        user = User.query.get(session['user_id'])
        if user:
            user.status = 'offline'
            user.last_seen = datetime.utcnow()
            db.session.commit()
        emit('user_offline', {'user_id': session['user_id']}, broadcast=True)

@socketio.on('typing')
def handle_typing(data):
    if 'user_id' in session:
        room = data.get('room', 'general')
        emit('user_typing', {
            'username': session['username'],
            'is_typing': data.get('is_typing', False)
        }, room=room, include_self=False)

@socketio.on('message')
def handle_message(data):
    if 'user_id' not in session:
        return
    
    room = data.get('room', 'general')
    text = data.get('text', '').strip()
    file_url = data.get('file_url')
    file_type = data.get('file_type')
    reply_to = data.get('reply_to')
    
    msg = Message(
        room=room,
        user_id=session['user_id'],
        content=text if text else None,
        file_url=file_url,
        file_type=file_type,
        reply_to=reply_to
    )
    db.session.add(msg)
    db.session.commit()
    
    user = User.query.get(session['user_id'])
    reply_msg = None
    if reply_to:
        reply_msg = Message.query.get(reply_to)
    
    emit('new_message', {
        'id': msg.id,
        'username': session['username'],
        'text': text,
        'file_url': file_url,
        'file_type': file_type,
        'timestamp': msg.timestamp.strftime('%H:%M'),
        'reply_to': reply_to,
        'reply_text': reply_msg.content if reply_msg else None,
        'reply_username': User.query.get(reply_msg.user_id).username if reply_msg else None
    }, room=room, broadcast=True)

@socketio.on('edit_message')
def handle_edit_message(data):
    if 'user_id' not in session:
        return
    message_id = data.get('message_id')
    new_content = data.get('content', '').strip()
    
    msg = Message.query.get(message_id)
    if msg and msg.user_id == session['user_id']:
        msg.content = new_content
        msg.edited = True
        msg.edited_at = datetime.utcnow()
        db.session.commit()
        emit('message_edited', {
            'message_id': message_id,
            'new_content': new_content,
            'edited_at': msg.edited_at.strftime('%H:%M')
        }, room=msg.room, broadcast=True)

@socketio.on('delete_message')
def handle_delete_message(data):
    if 'user_id' not in session:
        return
    message_id = data.get('message_id')
    
    msg = Message.query.get(message_id)
    if msg and msg.user_id == session['user_id']:
        db.session.delete(msg)
        db.session.commit()
        emit('message_deleted', {'message_id': message_id}, room=msg.room, broadcast=True)

@socketio.on('private_message')
def handle_private_message(data):
    if 'user_id' not in session:
        return
    to_user_id = data.get('to_user_id')
    text = data.get('text', '').strip()
    
    pm = PrivateMessage(
        from_user_id=session['user_id'],
        to_user_id=to_user_id,
        content=text
    )
    db.session.add(pm)
    db.session.commit()
    
    emit('new_private_message', {
        'from_user': session['username'],
        'content': text,
        'timestamp': pm.timestamp.strftime('%H:%M')
    }, room=f'private_{to_user_id}')

# CHAT_TEMPLATE - полный шаблон чата (очень большой, но с полным функционалом)
CHAT_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ChatVerse - {{ username }}</title>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            height: 100vh;
        }
        .app {
            display: flex;
            height: 100vh;
        }
        /* Sidebar */
        .sidebar {
            width: 280px;
            background: rgba(255,255,255,0.95);
            backdrop-filter: blur(10px);
            box-shadow: 2px 0 10px rgba(0,0,0,0.1);
            display: flex;
            flex-direction: column;
            overflow-y: auto;
        }
        .user-profile {
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            text-align: center;
        }
        .avatar {
            width: 80px;
            height: 80px;
            background: white;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 10px;
            font-size: 40px;
        }
        .rooms {
            padding: 20px;
        }
        .room-item {
            padding: 12px;
            margin: 5px 0;
            border-radius: 10px;
            cursor: pointer;
            transition: all 0.3s;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .room-item:hover { background: #f0f0f0; }
        .room-item.active { background: linear-gradient(135deg, #667eea20 0%, #764ba220 100%); color: #667eea; font-weight: bold; }
        .online-users {
            padding: 20px;
            border-top: 1px solid #e0e0e0;
        }
        .user-item {
            padding: 10px;
            margin: 5px 0;
            border-radius: 10px;
            cursor: pointer;
            transition: all 0.3s;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .user-item:hover { background: #f0f0f0; }
        .online-dot {
            width: 10px;
            height: 10px;
            background: #4ade80;
            border-radius: 50%;
        }
        /* Main chat area */
        .chat-main {
            flex: 1;
            display: flex;
            flex-direction: column;
            background: white;
        }
        .chat-header {
            padding: 20px;
            background: white;
            border-bottom: 1px solid #e0e0e0;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .messages-area {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
            background: #f8f9fa;
        }
        .message {
            margin-bottom: 15px;
            animation: fadeIn 0.3s ease-out;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .message-content {
            background: white;
            padding: 12px;
            border-radius: 12px;
            display: inline-block;
            max-width: 70%;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            position: relative;
        }
        .message-actions {
            position: absolute;
            right: -30px;
            top: 5px;
            display: none;
            gap: 5px;
        }
        .message:hover .message-actions {
            display: flex;
        }
        .message-actions button {
            background: none;
            border: none;
            cursor: pointer;
            padding: 5px;
            border-radius: 5px;
        }
        .message-actions button:hover { background: #e0e0e0; }
        .reply-indicator {
            background: #f0f0f0;
            padding: 5px;
            margin-bottom: 5px;
            border-radius: 8px;
            font-size: 12px;
            color: #666;
        }
        .controls-area {
            padding: 20px;
            background: white;
            border-top: 1px solid #e0e0e0;
        }
        .input-group {
            display: flex;
            gap: 10px;
            margin-bottom: 10px;
        }
        #messageInput {
            flex: 1;
            padding: 12px;
            border: 2px solid #e0e0e0;
            border-radius: 25px;
            font-size: 14px;
        }
        .typing-indicator {
            font-size: 12px;
            color: #666;
            padding: 5px 20px;
        }
        button {
            padding: 12px 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 25px;
            cursor: pointer;
            transition: all 0.3s;
        }
        button:hover { transform: translateY(-1px); box-shadow: 0 5px 15px rgba(102,126,234,0.3); }
        .emoji-picker {
            position: absolute;
            bottom: 80px;
            right: 20px;
            background: white;
            border-radius: 12px;
            box-shadow: 0 5px 20px rgba(0,0,0,0.2);
            padding: 10px;
            display: none;
            grid-template-columns: repeat(6, 1fr);
            gap: 5px;
            z-index: 1000;
        }
        .emoji-picker span {
            font-size: 24px;
            cursor: pointer;
            padding: 5px;
            transition: all 0.2s;
        }
        .emoji-picker span:hover { transform: scale(1.2); }
        @media (max-width: 768px) {
            .sidebar { display: none; }
            .message-content { max-width: 90%; }
        }
    </style>
</head>
<body>
    <div class="app">
        <div class="sidebar">
            <div class="user-profile">
                <div class="avatar">👤</div>
                <h3>{{ username }}</h3>
                <small>ID: {{ session['user_id'] }}</small>
            </div>
            <div class="rooms">
                <h4><i class="fas fa-hashtag"></i> Комнаты</h4>
                <div class="room-item active" data-room="general">
                    <i class="fas fa-comment"></i> Общий чат
                </div>
                <div class="room-item" data-room="random">
                    <i class="fas fa-random"></i> Случайный
                </div>
                <div class="room-item" data-room="help">
                    <i class="fas fa-question-circle"></i> Помощь
                </div>
            </div>
            <div class="online-users">
                <h4><i class="fas fa-circle" style="color: #4ade80; font-size: 12px;"></i> Онлайн (<span id="onlineCount">0</span>)</h4>
                <div id="usersList">
                    {% for user in users %}
                        <div class="user-item" data-user-id="{{ user.id }}">
                            <div class="online-dot"></div>
                            <span>{{ user.username }}</span>
                        </div>
                    {% endfor %}
                </div>
            </div>
        </div>
        <div class="chat-main">
            <div class="chat-header">
                <h2><i class="fas fa-comments"></i> <span id="currentRoom">Общий чат</span></h2>
                <button onclick="window.location.href='/logout'"><i class="fas fa-sign-out-alt"></i> Выйти</button>
            </div>
            <div class="messages-area" id="messages">
                {% for msg in messages %}
                    <div class="message" data-message-id="{{ msg.id }}">
                        <div class="message-header">
                            <strong>{{ msg.user.username }}</strong>
                            <small>{{ msg.timestamp.strftime('%H:%M') }}</small>
                        </div>
                        <div class="message-content">
                            {% if msg.reply_to %}
                                <div class="reply-indicator">↩️ Ответ на сообщение</div>
                            {% endif %}
                            {% if msg.content %}<p>{{ msg.content }}</p>{% endif %}
                            {% if msg.file_type == 'image' %}
                                <img src="{{ msg.file_url }}" style="max-width: 200px; border-radius: 8px;">
                            {% elif msg.file_type == 'audio' %}
                                <audio controls src="{{ msg.file_url }}"></audio>
                            {% endif %}
                            {% if msg.edited %}
                                <small style="color: #999;">(изменено)</small>
                            {% endif %}
                        </div>
                    </div>
                {% endfor %}
            </div>
            <div class="typing-indicator" id="typingIndicator"></div>
            <div class="controls-area">
                <div class="input-group">
                    <input type="text" id="messageInput" placeholder="Введите сообщение...">
                    <button id="emojiBtn"><i class="far fa-smile"></i></button>
                    <input type="file" id="imageInput" accept="image/*" style="display: none;">
                    <button id="uploadImageBtn"><i class="fas fa-image"></i></button>
                    <button id="recordBtn"><i class="fas fa-microphone"></i></button>
                    <button id="sendBtn"><i class="fas fa-paper-plane"></i></button>
                </div>
                <div class="emoji-picker" id="emojiPicker">
                    <span>😀</span><span>😍</span><span>😂</span><span>😎</span><span>🔥</span><span>💯</span>
                    <span>👍</span><span>❤️</span><span>🎉</span><span>✨</span><span>⭐</span><span>🌟</span>
                    <span>🤔</span><span>😢</span><span>😡</span><span>🥳</span><span>😱</span><span>💪</span>
                </div>
            </div>
        </div>
    </div>

    <script>
        const socket = io();
        let currentRoom = 'general';
        let typingTimeout;
        let mediaRecorder;
        let audioChunks = [];

        // Функции
        function appendMessage(msg) {
            const messagesDiv = document.getElementById('messages');
            const div = document.createElement('div');
            div.className = 'message';
            div.setAttribute('data-message-id', msg.id);
            div.innerHTML = `
                <div class="message-header">
                    <strong>${escapeHtml(msg.username)}</strong>
                    <small>${msg.timestamp}</small>
                    <div class="message-actions">
                        <button onclick="replyToMessage(${msg.id})"><i class="fas fa-reply"></i></button>
                        ${msg.username === '{{ username }}' ? `<button onclick="editMessage(${msg.id})"><i class="fas fa-edit"></i></button>
                        <button onclick="deleteMessage(${msg.id})"><i class="fas fa-trash"></i></button>` : ''}
                    </div>
                </div>
                <div class="message-content">
                    ${msg.reply_to ? `<div class="reply-indicator">↩️ Ответ на: "${escapeHtml(msg.reply_text || '')}"</div>` : ''}
                    ${msg.text ? `<p>${escapeHtml(msg.text)}</p>` : ''}
                    ${msg.file_type === 'image' ? `<img src="${msg.file_url}" style="max-width: 200px; border-radius: 8px;">` : ''}
                    ${msg.file_type === 'audio' ? `<audio controls src="${msg.file_url}"></audio>` : ''}
                </div>
            `;
            messagesDiv.appendChild(div);
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // Socket события
        socket.on('new_message', (msg) => {
            if (currentRoom === 'general') appendMessage(msg);
        });

        socket.on('user_typing', (data) => {
            const indicator = document.getElementById('typingIndicator');
            if (data.is_typing) {
                indicator.innerHTML = `<i class="fas fa-ellipsis-h"></i> ${escapeHtml(data.username)} печатает...`;
            } else {
                indicator.innerHTML = '';
            }
            setTimeout(() => { indicator.innerHTML = ''; }, 3000);
        });

        // Отправка сообщения
        sendBtn.onclick = () => {
            const text = messageInput.value.trim();
            if (text) {
                socket.emit('message', { text, room: currentRoom });
                messageInput.value = '';
            }
        };

        // Эмодзи
        emojiBtn.onclick = () => {
            const picker = document.getElementById('emojiPicker');
            picker.style.display = picker.style.display === 'grid' ? 'none' : 'grid';
        };
        document.querySelectorAll('#emojiPicker span').forEach(emoji => {
            emoji.onclick = () => {
                messageInput.value += emoji.textContent;
                document.getElementById('emojiPicker').style.display = 'none';
            };
        });

        // Печатание
        let isTyping = false;
        messageInput.addEventListener('input', () => {
            if (!isTyping) {
                isTyping = true;
                socket.emit('typing', { room: currentRoom, is_typing: true });
            }
            clearTimeout(typingTimeout);
            typingTimeout = setTimeout(() => {
                isTyping = false;
                socket.emit('typing', { room: currentRoom, is_typing: false });
            }, 1000);
        });

        // Функции редактирования/удаления
        window.editMessage = (id) => {
            const newContent = prompt('Редактировать сообщение:');
            if (newContent) {
                socket.emit('edit_message', { message_id: id, content: newContent });
            }
        };
        window.deleteMessage = (id) => {
            if (confirm('Удалить сообщение?')) {
                socket.emit('delete_message', { message_id: id });
            }
        };
        window.replyToMessage = (id) => {
            messageInput.focus();
            messageInput.placeholder = `Ответ на сообщение...`;
            // Сохраняем ID в data-атрибут
            messageInput.setAttribute('data-reply-to', id);
        };

        // Смена комнаты
        document.querySelectorAll('.room-item').forEach(room => {
            room.onclick = () => {
                document.querySelectorAll('.room-item').forEach(r => r.classList.remove('active'));
                room.classList.add('active');
                currentRoom = room.getAttribute('data-room');
                document.getElementById('currentRoom').innerText = room.querySelector('span').innerText;
                socket.emit('join', { room: currentRoom });
            };
        });

        // Загрузка изображений
        uploadImageBtn.onclick = () => imageInput.click();
        imageInput.onchange = async (e) => {
            const file = e.target.files[0];
            if (!file) return;
            const formData = new FormData();
            formData.append('file', file);
            const res = await fetch('/upload', { method: 'POST', body: formData });
            const data = await res.json();
            if (data.file_url) {
                socket.emit('message', { file_url: data.file_url, file_type: 'image', room: currentRoom });
            }
        };

        // Аудио запись
        recordBtn.onclick = async () => {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorder = new MediaRecorder(stream);
            audioChunks = [];
            mediaRecorder.ondataavailable = e => audioChunks.push(e.data);
            mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                const formData = new FormData();
                formData.append('file', audioBlob, 'voice.webm');
                const res = await fetch('/upload', { method: 'POST', body: formData });
                const data = await res.json();
                if (data.file_url) {
                    socket.emit('message', { file_url: data.file_url, file_type: 'audio', room: currentRoom });
                }
                stream.getTracks().forEach(track => track.stop());
            };
            mediaRecorder.start();
            recordBtn.style.background = 'red';
            setTimeout(() => {
                if (mediaRecorder && mediaRecorder.state === 'recording') {
                    mediaRecorder.stop();
                    recordBtn.style.background = '';
                }
            }, 10000);
        };

        messageInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') sendBtn.click();
        });
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    socketio.run(app, debug=False, host='0.0.0.0', port=5000)
