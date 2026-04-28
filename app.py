import os
import random
import string
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify, send_from_directory
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config['SECRET_KEY'] = 'supersecretkey123'
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
    last_avatar_change = db.Column(db.DateTime, default=None)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room = db.Column(db.String(50), default='general')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    content = db.Column(db.Text)
    file_url = db.Column(db.String(200))
    file_type = db.Column(db.String(20))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

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

# Создание таблиц
with app.app_context():
    db.create_all()

# ==================== HTML ШАБЛОНЫ ====================

LOGIN_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>ChatVerse - Вход</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            margin: 0;
        }
        .container {
            background: white;
            padding: 40px;
            border-radius: 20px;
            width: 350px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
        }
        h2 { text-align: center; margin-bottom: 30px; color: #333; }
        input {
            width: 100%;
            padding: 12px;
            margin: 10px 0;
            border: 1px solid #ddd;
            border-radius: 8px;
            box-sizing: border-box;
        }
        button {
            width: 100%;
            padding: 12px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 16px;
            margin-top: 10px;
        }
        button:hover { opacity: 0.9; }
        .error { color: red; text-align: center; margin-bottom: 15px; }
        .footer { text-align: center; margin-top: 20px; }
        .footer a { color: #667eea; text-decoration: none; }
    </style>
</head>
<body>
    <div class="container">
        <h2>💬 Вход в чат</h2>
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        <form method="post">
            <input type="text" name="username" placeholder="Имя пользователя или ID" required>
            <input type="password" name="password" placeholder="Пароль" required>
            <button type="submit">Войти</button>
        </form>
        <div class="footer">
            <a href="/register">Нет аккаунта? Зарегистрируйтесь</a>
        </div>
    </div>
</body>
</html>
'''

REGISTER_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>ChatVerse - Регистрация</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            margin: 0;
        }
        .container {
            background: white;
            padding: 40px;
            border-radius: 20px;
            width: 400px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
        }
        h2 { text-align: center; margin-bottom: 30px; color: #333; }
        input, textarea {
            width: 100%;
            padding: 12px;
            margin: 10px 0;
            border: 1px solid #ddd;
            border-radius: 8px;
            box-sizing: border-box;
            font-family: Arial;
        }
        textarea { resize: vertical; min-height: 60px; }
        button {
            width: 100%;
            padding: 12px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 16px;
            margin-top: 10px;
        }
        .error { color: red; text-align: center; margin-bottom: 15px; }
        .footer { text-align: center; margin-top: 20px; }
        .footer a { color: #667eea; text-decoration: none; }
        .info { background: #e3f2fd; padding: 10px; border-radius: 8px; margin-bottom: 15px; font-size: 14px; text-align: center; }
    </style>
</head>
<body>
    <div class="container">
        <h2>📝 Регистрация</h2>
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        <div class="info">Вы получите уникальный ID (4-8 символов) для входа</div>
        <form method="post">
            <input type="text" name="username" placeholder="Имя пользователя" required minlength="3">
            <textarea name="bio" placeholder="О себе (необязательно)"></textarea>
            <input type="password" name="password" placeholder="Пароль" required minlength="4">
            <input type="password" name="confirm_password" placeholder="Подтвердите пароль" required>
            <button type="submit">Зарегистрироваться</button>
        </form>
        <div class="footer">
            <a href="/login">Уже есть аккаунт? Войдите</a>
        </div>
    </div>
</body>
</html>
'''

PROFILE_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Профиль - ChatVerse</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            margin: 0;
            padding: 20px;
        }
        .container {
            background: white;
            padding: 40px;
            border-radius: 20px;
            width: 500px;
            max-width: 100%;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
        }
        .avatar {
            width: 100px;
            height: 100px;
            background: #667eea;
            border-radius: 50%;
            margin: 0 auto 20px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 50px;
            overflow: hidden;
        }
        .avatar img { width: 100%; height: 100%; object-fit: cover; }
        h2 { text-align: center; margin-bottom: 10px; }
        .user-id { text-align: center; color: #666; margin-bottom: 30px; font-family: monospace; font-size: 18px; }
        input, textarea {
            width: 100%;
            padding: 12px;
            margin: 10px 0;
            border: 1px solid #ddd;
            border-radius: 8px;
            box-sizing: border-box;
        }
        textarea { resize: vertical; }
        button {
            width: 100%;
            padding: 12px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 16px;
            margin-top: 10px;
        }
        .back-btn {
            display: block;
            text-align: center;
            margin-top: 20px;
            color: #667eea;
            text-decoration: none;
        }
        .success { background: #d4edda; color: #155724; padding: 10px; border-radius: 8px; margin-bottom: 15px; text-align: center; }
        .error { background: #f8d7da; color: #721c24; padding: 10px; border-radius: 8px; margin-bottom: 15px; text-align: center; }
        .warning { font-size: 12px; color: #e67e22; margin-top: 5px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="avatar">
            {% if user.avatar %}
                <img src="{{ user.avatar }}" alt="avatar">
            {% else %}
                👤
            {% endif %}
        </div>
        <h2>{{ user.username }}</h2>
        <div class="user-id">ID: {{ user.user_id_display }}</div>
        
        {% if success %}<div class="success">{{ success }}</div>{% endif %}
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        
        <form method="post" enctype="multipart/form-data" action="/update_profile">
            <input type="file" name="avatar" accept="image/*">
            {% if not can_change_avatar %}
                <div class="warning">⏰ Сменить аватар можно будет через {{ days_left }} дней</div>
            {% endif %}
            <textarea name="bio" placeholder="О себе">{{ user.bio }}</textarea>
            <input type="password" name="new_password" placeholder="Новый пароль (оставьте пустым, если не хотите менять)">
            <button type="submit">Сохранить</button>
        </form>
        <a href="/chat" class="back-btn">← Вернуться в чат</a>
    </div>
</body>
</html>
'''

CHAT_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Chat - {{ username }}</title>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Arial, sans-serif;
            background: #1a1a2e;
            height: 100vh;
            display: flex;
        }
        .sidebar {
            width: 260px;
            background: #16213e;
            display: flex;
            flex-direction: column;
            color: white;
        }
        .user-info {
            padding: 20px;
            text-align: center;
            background: #0f3460;
            cursor: pointer;
        }
        .user-info .avatar {
            width: 60px;
            height: 60px;
            background: #667eea;
            border-radius: 50%;
            margin: 0 auto 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 30px;
        }
        .rooms, .users {
            padding: 20px;
            border-bottom: 1px solid #2a2a4a;
        }
        .room-item, .user-item {
            padding: 10px;
            margin: 5px 0;
            border-radius: 8px;
            cursor: pointer;
        }
        .room-item:hover, .user-item:hover { background: #2a2a4a; }
        .room-item.active { background: #667eea; }
        .chat {
            flex: 1;
            display: flex;
            flex-direction: column;
            background: #1a1a2e;
        }
        .chat-header {
            padding: 20px;
            background: #16213e;
            color: white;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #2a2a4a;
        }
        .messages {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
        }
        .message {
            margin-bottom: 15px;
            animation: fadeIn 0.3s;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .message-header { margin-bottom: 5px; }
        .username { font-weight: bold; color: #667eea; margin-right: 10px; }
        .timestamp { font-size: 11px; color: #888; }
        .message-content {
            background: #0f3460;
            padding: 10px 15px;
            border-radius: 15px;
            display: inline-block;
            max-width: 70%;
            color: white;
        }
        .message-image { max-width: 250px; border-radius: 10px; margin-top: 5px; }
        .controls {
            padding: 20px;
            background: #16213e;
            display: flex;
            gap: 10px;
        }
        #messageInput {
            flex: 1;
            padding: 12px 20px;
            border: none;
            border-radius: 25px;
            background: #0f3460;
            color: white;
        }
        button {
            padding: 10px 20px;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 25px;
            cursor: pointer;
        }
        button:hover { opacity: 0.9; }
        .online-dot { width: 8px; height: 8px; background: #4ade80; border-radius: 50%; display: inline-block; margin-right: 8px; }
        .offline-dot { width: 8px; height: 8px; background: #666; border-radius: 50%; display: inline-block; margin-right: 8px; }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="user-info" onclick="location.href='/profile'">
            <div class="avatar">👤</div>
            <strong>{{ username }}</strong>
            <div style="font-size: 12px; opacity: 0.7;">ID: {{ user_id }}</div>
        </div>
        <div class="rooms">
            <div style="margin-bottom: 10px;">📌 Комнаты</div>
            <div class="room-item active" data-room="general"># Общий чат</div>
            <div class="room-item" data-room="random">🎲 Случайный</div>
            <div class="room-item" data-room="help">❓ Помощь</div>
        </div>
        <div class="users">
            <div style="margin-bottom: 10px;">👥 Онлайн (<span id="onlineCount">0</span>)</div>
            <div id="usersList"></div>
        </div>
    </div>
    <div class="chat">
        <div class="chat-header">
            <h2><span id="currentRoomName">Общий чат</span></h2>
            <button onclick="location.href='/logout'">Выйти</button>
        </div>
        <div class="messages" id="messages"></div>
        <div class="controls">
            <input type="text" id="messageInput" placeholder="Введите сообщение...">
            <input type="file" id="imageInput" accept="image/*" style="display:none">
            <button id="imageBtn">📷</button>
            <button id="sendBtn">📤 Отправить</button>
        </div>
    </div>

    <script>
        const socket = io();
        let currentRoom = 'general';
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        function addMessage(msg) {
            const div = document.createElement('div');
            div.className = 'message';
            div.innerHTML = `
                <div class="message-header">
                    <span class="username">${escapeHtml(msg.username)}</span>
                    <span class="timestamp">${msg.timestamp}</span>
                </div>
                <div class="message-content">
                    ${msg.text ? `<p>${escapeHtml(msg.text)}</p>` : ''}
                    ${msg.file_type === 'image' ? `<img class="message-image" src="${msg.file_url}">` : ''}
                </div>
            `;
            document.getElementById('messages').appendChild(div);
            document.getElementById('messages').scrollTop = document.getElementById('messages').scrollHeight;
        }
        
        // Загрузка сообщений
        function loadMessages(room) {
            fetch(`/get_messages?room=${room}`)
                .then(res => res.json())
                .then(messages => {
                    const container = document.getElementById('messages');
                    container.innerHTML = '';
                    messages.forEach(msg => addMessage(msg));
                });
        }
        
        // Обновление списка пользователей
        function loadUsers() {
            fetch('/get_users')
                .then(res => res.json())
                .then(users => {
                    const container = document.getElementById('usersList');
                    const onlineCount = users.filter(u => u.status === 'online').length;
                    document.getElementById('onlineCount').innerText = onlineCount;
                    container.innerHTML = '';
                    users.forEach(user => {
                        if (user.id != {{ session['user_id'] }}) {
                            container.innerHTML += `
                                <div class="user-item">
                                    <span class="${user.status === 'online' ? 'online-dot' : 'offline-dot'}"></span>
                                    ${escapeHtml(user.username)}
                                </div>
                            `;
                        }
                    });
                });
        }
        
        // Socket events
        socket.on('new_message', (msg) => {
            if (msg.room === currentRoom) addMessage(msg);
        });
        
        socket.on('user_online', () => loadUsers());
        socket.on('user_offline', () => loadUsers());
        
        // Отправка сообщения
        document.getElementById('sendBtn').onclick = () => {
            const input = document.getElementById('messageInput');
            const text = input.value.trim();
            if (text) {
                socket.emit('message', { text, room: currentRoom });
                input.value = '';
            }
        };
        
        document.getElementById('messageInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') document.getElementById('sendBtn').click();
        });
        
        // Загрузка изображения
        document.getElementById('imageBtn').onclick = () => document.getElementById('imageInput').click();
        document.getElementById('imageInput').onchange = async (e) => {
            const file = e.target.files[0];
            if (!file) return;
            const formData = new FormData();
            formData.append('file', file);
            const res = await fetch('/upload', { method: 'POST', body: formData });
            const data = await res.json();
            if (data.file_url) {
                socket.emit('message', { file_url: data.file_url, file_type: 'image', room: currentRoom });
            }
            document.getElementById('imageInput').value = '';
        };
        
        // Смена комнаты
        document.querySelectorAll('.room-item').forEach(room => {
            room.onclick = () => {
                document.querySelectorAll('.room-item').forEach(r => r.classList.remove('active'));
                room.classList.add('active');
                currentRoom = room.getAttribute('data-room');
                document.getElementById('currentRoomName').innerText = room.innerText.trim();
                loadMessages(currentRoom);
                socket.emit('join', { room: currentRoom });
            };
        });
        
        loadMessages('general');
        loadUsers();
        setInterval(loadUsers, 5000);
    </script>
</body>
</html>
'''

# ==================== МАРШРУТЫ ====================

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
            session['user_id_display'] = user.user_id_display
            user.status = 'online'
            db.session.commit()
            return redirect(url_for('chat'))
        return render_template_string(LOGIN_HTML, error='Неверный логин/ID или пароль')
    return render_template_string(LOGIN_HTML)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm = request.form['confirm_password']
        bio = request.form.get('bio', '')
        
        if password != confirm:
            return render_template_string(REGISTER_HTML, error='Пароли не совпадают')
        if len(username) < 3:
            return render_template_string(REGISTER_HTML, error='Имя слишком короткое')
        if User.query.filter_by(username=username).first():
            return render_template_string(REGISTER_HTML, error='Пользователь уже существует')
        
        user_id = generate_user_id()
        hashed = generate_password_hash(password)
        
        user = User(
            username=username,
            user_id_display=user_id,
            password=hashed,
            bio=bio
        )
        db.session.add(user)
        db.session.commit()
        
        session['user_id'] = user.id
        session['username'] = user.username
        session['user_id_display'] = user.user_id_display
        
        return redirect(url_for('chat'))
    
    return render_template_string(REGISTER_HTML)

@app.route('/chat')
@login_required
def chat():
    user = User.query.get(session['user_id'])
    return render_template_string(CHAT_HTML, 
                                  username=user.username,
                                  user_id=user.user_id_display,
                                  session=session)

@app.route('/profile')
@login_required
def profile():
    user = User.query.get(session['user_id'])
    can_change = True
    days_left = 0
    if user.last_avatar_change:
        week_ago = datetime.utcnow() - timedelta(days=7)
        if user.last_avatar_change > week_ago:
            can_change = False
            days_left = 7 - (datetime.utcnow() - user.last_avatar_change).days
    return render_template_string(PROFILE_HTML, user=user, can_change_avatar=can_change, days_left=days_left)

@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    user = User.query.get(session['user_id'])
    success = None
    error = None
    
    if 'avatar' in request.files:
        file = request.files['avatar']
        if file and file.filename:
            can_change = True
            if user.last_avatar_change:
                week_ago = datetime.utcnow() - timedelta(days=7)
                if user.last_avatar_change > week_ago:
                    can_change = False
                    error = 'Аватар можно менять раз в неделю!'
            
            if can_change:
                filename = f"{user.id}_{datetime.utcnow().timestamp()}_{secure_filename(file.filename)}"
                path = os.path.join('uploads/avatars', filename)
                file.save(path)
                user.avatar = f'/uploads/avatars/{filename}'
                user.last_avatar_change = datetime.utcnow()
                success = 'Аватар обновлён!'
    
    if 'bio' in request.form:
        user.bio = request.form['bio']
        success = success or 'Профиль обновлён!'
    
    if 'new_password' in request.form and request.form['new_password']:
        user.password = generate_password_hash(request.form['new_password'])
        success = success or 'Пароль изменён!'
    
    db.session.commit()
    
    can_change = True
    days_left = 0
    if user.last_avatar_change:
        week_ago = datetime.utcnow() - timedelta(days=7)
        if user.last_avatar_change > week_ago:
            can_change = False
            days_left = 7 - (datetime.utcnow() - user.last_avatar_change).days
    
    return render_template_string(PROFILE_HTML, user=user, success=success, error=error, can_change_avatar=can_change, days_left=days_left)

@app.route('/get_messages')
@login_required
def get_messages():
    room = request.args.get('room', 'general')
    msgs = Message.query.filter_by(room=room).order_by(Message.timestamp).limit(100).all()
    return jsonify([{
        'id': m.id,
        'username': User.query.get(m.user_id).username,
        'text': m.content,
        'file_url': m.file_url,
        'file_type': m.file_type,
        'timestamp': m.timestamp.strftime('%H:%M'),
        'room': m.room
    } for m in msgs])

@app.route('/get_users')
@login_required
def get_users():
    users = User.query.all()
    return jsonify([{
        'id': u.id,
        'username': u.username,
        'user_id_display': u.user_id_display,
        'status': u.status
    } for u in users])

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

# ==================== SOCKET.IO ====================

@socketio.on('connect')
def handle_connect():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            user.status = 'online'
            db.session.commit()
            emit('user_online', {'user_id': user.id}, broadcast=True)

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
        'text': text,
        'file_url': file_url,
        'file_type': file_type,
        'timestamp': msg.timestamp.strftime('%H:%M'),
        'room': room
    }, room=room, broadcast=True)

@socketio.on('join')
def handle_join(data):
    room = data.get('room', 'general')
    join_room(room)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
