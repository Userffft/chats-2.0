import os
import random
import string
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify, send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')
database_url = os.environ.get('DATABASE_URL', 'sqlite:///chat.db')
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER_IMAGES'] = 'uploads/images'
app.config['UPLOAD_FOLDER_AUDIO'] = 'uploads/audio'
app.config['UPLOAD_FOLDER_AVATARS'] = 'uploads/avatars'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

for folder in [app.config['UPLOAD_FOLDER_IMAGES'], app.config['UPLOAD_FOLDER_AUDIO'], app.config['UPLOAD_FOLDER_AVATARS']]:
    os.makedirs(folder, exist_ok=True)

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Модели
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    user_id_display = db.Column(db.String(8), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    avatar = db.Column(db.String(200), default=None)
    bio = db.Column(db.String(200), default='')
    status = db.Column(db.String(50), default='online')
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_avatar_change = db.Column(db.DateTime, default=None)
    theme = db.Column(db.String(20), default='dark')  # Добавлено поле theme

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room = db.Column(db.String(50), default='general')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    content = db.Column(db.Text)
    file_url = db.Column(db.String(200))
    file_type = db.Column(db.String(20))
    reply_to = db.Column(db.Integer, default=None)
    edited = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

def generate_user_id():
    while True:
        length = random.choice([4, 5, 6, 7, 8])
        user_id = ''.join(random.choices(string.ascii_letters + string.digits, k=length))
        if not User.query.filter_by(user_id_display=user_id).first():
            return user_id

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Создание таблиц с проверкой
with app.app_context():
    db.create_all()
    # Добавляем колонку theme если её нет (для старых пользователей)
    try:
        from sqlalchemy import text
        db.session.execute(text('ALTER TABLE user ADD COLUMN theme VARCHAR(20) DEFAULT "dark"'))
        db.session.commit()
        print("Колонка theme добавлена")
    except Exception as e:
        print("Колонка theme уже существует:", e)
    
    # Обновляем существующих пользователей
    users = User.query.all()
    for user in users:
        if user.theme is None:
            user.theme = 'dark'
    db.session.commit()

# ============ HTML ШАБЛОНЫ ============

LOGIN_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ChatVerse - Вход</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
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
            <h1>💬 ChatVerse</h1>
            <p>Войдите в свой аккаунт</p>
        </div>
        <div class="form-container">
            {% if error %}
                <div class="error">{{ error }}</div>
            {% endif %}
            <form method="post">
                <div class="form-group">
                    <label>👤 Имя или ID</label>
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
    <title>ChatVerse - Регистрация</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
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
        .form-container { padding: 40px; }
        .form-group { margin-bottom: 25px; }
        label { display: block; margin-bottom: 8px; color: #333; font-weight: 500; }
        input, textarea {
            width: 100%;
            padding: 12px 15px;
            border: 2px solid #e0e0e0;
            border-radius: 12px;
            font-size: 14px;
            transition: all 0.3s;
            font-family: inherit;
        }
        textarea { resize: vertical; min-height: 80px; }
        input:focus, textarea:focus {
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
        .info {
            background: #e3f2fd;
            color: #1976d2;
            padding: 12px;
            border-radius: 10px;
            margin-bottom: 20px;
            text-align: center;
            font-size: 14px;
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
            <div class="info">
                ℹ️ Вы получите уникальный ID (4-8 символов) для входа
            </div>
            <form method="post">
                <div class="form-group">
                    <label>👤 Имя пользователя</label>
                    <input type="text" name="username" required minlength="3" maxlength="20">
                </div>
                <div class="form-group">
                    <label>📝 О себе</label>
                    <textarea name="bio" placeholder="Расскажите о себе..."></textarea>
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

# Функция для генерации HTML чата
def get_chat_template():
    return '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ChatVerse - {{ username }}</title>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style id="theme-style">
        body.dark {
            --bg-primary: #1a1a2e;
            --bg-secondary: #16213e;
            --bg-card: #0f3460;
            --text-primary: #ffffff;
            --text-secondary: #a0a0a0;
            --accent: #667eea;
            --border: #2a2a4a;
            --message-bg: #0f3460;
        }
        body.light {
            --bg-primary: #f0f2f5;
            --bg-secondary: #ffffff;
            --bg-card: #ffffff;
            --text-primary: #1a1a2e;
            --text-secondary: #666666;
            --accent: #667eea;
            --border: #e0e0e0;
            --message-bg: #ffffff;
        }
        body.purple {
            --bg-primary: #2d1b4e;
            --bg-secondary: #3d2b6e;
            --bg-card: #4d3b8e;
            --text-primary: #ffffff;
            --text-secondary: #d0c0ff;
            --accent: #c084fc;
            --border: #5d4bae;
            --message-bg: #4d3b8e;
        }
        body.blue {
            --bg-primary: #0c4a6e;
            --bg-secondary: #075985;
            --bg-card: #0284c7;
            --text-primary: #ffffff;
            --text-secondary: #bae6fd;
            --accent: #38bdf8;
            --border: #38bdf8;
            --message-bg: #0284c7;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: var(--bg-primary);
            height: 100vh;
            color: var(--text-primary);
        }
        .app { display: flex; height: 100vh; }
        .sidebar {
            width: 280px;
            background: var(--bg-secondary);
            display: flex;
            flex-direction: column;
            overflow-y: auto;
            border-right: 1px solid var(--border);
        }
        .user-profile {
            padding: 20px;
            background: var(--accent);
            text-align: center;
            cursor: pointer;
        }
        .avatar {
            width: 80px;
            height: 80px;
            background: rgba(255,255,255,0.2);
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 auto 10px;
            font-size: 40px;
            overflow: hidden;
        }
        .rooms, .online-users, .theme-selector { padding: 20px; border-bottom: 1px solid var(--border); }
        .room-item {
            padding: 12px;
            margin: 5px 0;
            border-radius: 10px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .room-item:hover { background: rgba(255,255,255,0.1); }
        .room-item.active { background: var(--accent); }
        .chat-main {
            flex: 1;
            display: flex;
            flex-direction: column;
            background: var(--bg-primary);
        }
        .chat-header {
            padding: 20px;
            background: var(--bg-secondary);
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .messages-area {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
        }
        .message { margin-bottom: 15px; animation: fadeIn 0.3s ease-out; }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .username { font-weight: bold; color: var(--accent); margin-right: 10px; }
        .timestamp { font-size: 11px; color: var(--text-secondary); }
        .message-content {
            background: var(--message-bg);
            padding: 12px;
            border-radius: 12px;
            display: inline-block;
            max-width: 70%;
        }
        .message-image { max-width: 300px; border-radius: 8px; margin-top: 5px; }
        .controls-area {
            padding: 20px;
            background: var(--bg-secondary);
            border-top: 1px solid var(--border);
        }
        .input-group { display: flex; gap: 10px; }
        #messageInput {
            flex: 1;
            padding: 12px 20px;
            border: 1px solid var(--border);
            border-radius: 25px;
            background: var(--bg-primary);
            color: var(--text-primary);
        }
        button {
            padding: 10px 18px;
            background: var(--accent);
            color: white;
            border: none;
            border-radius: 25px;
            cursor: pointer;
        }
        .theme-btn { padding: 8px 12px; margin: 3px; font-size: 12px; }
        @media (max-width: 768px) { .sidebar { display: none; } }
    </style>
</head>
<body class="{{ theme }}">
    <div class="app">
        <div class="sidebar">
            <div class="user-profile" onclick="window.location.href='/profile'">
                <div class="avatar">👤</div>
                <strong>{{ username }}</strong>
                <div style="font-size:12px;">ID: {{ user_id_display }}</div>
            </div>
            <div class="rooms">
                <h4><i class="fas fa-hashtag"></i> Комнаты</h4>
                <div class="room-item active" data-room="general"><i class="fas fa-comment"></i> Общий чат</div>
                <div class="room-item" data-room="random"><i class="fas fa-random"></i> Случайный</div>
                <div class="room-item" data-room="help"><i class="fas fa-question-circle"></i> Помощь</div>
            </div>
            <div class="online-users">
                <h4><i class="fas fa-circle" style="color: #4ade80; font-size: 12px;"></i> Онлайн (<span id="onlineCount">0</span>)</h4>
                <div id="usersList"></div>
            </div>
            <div class="theme-selector">
                <h4><i class="fas fa-palette"></i> Тема</h4>
                <button class="theme-btn" onclick="changeTheme('dark')">🌙 Тёмная</button>
                <button class="theme-btn" onclick="changeTheme('light')">☀️ Светлая</button>
                <button class="theme-btn" onclick="changeTheme('purple')">💜 Фиолетовая</button>
                <button class="theme-btn" onclick="changeTheme('blue')">💙 Синяя</button>
            </div>
        </div>
        <div class="chat-main">
            <div class="chat-header">
                <h2><i class="fas fa-comments"></i> <span id="currentRoom">Общий чат</span></h2>
                <button onclick="window.location.href='/logout'"><i class="fas fa-sign-out-alt"></i> Выйти</button>
            </div>
            <div class="messages-area" id="messages">
                {% for msg in messages %}
                    <div class="message">
                        <div class="message-header">
                            <span class="username">{{ msg.user.username }}</span>
                            <span class="timestamp">{{ msg.timestamp.strftime('%H:%M') }}</span>
                        </div>
                        <div class="message-content">
                            {% if msg.content %}<p>{{ msg.content }}</p>{% endif %}
                            {% if msg.file_type == 'image' %}
                                <img class="message-image" src="{{ msg.file_url }}">
                            {% elif msg.file_type == 'audio' %}
                                <audio controls src="{{ msg.file_url }}"></audio>
                            {% endif %}
                        </div>
                    </div>
                {% endfor %}
            </div>
            <div class="typing-indicator" id="typingIndicator"></div>
            <div class="controls-area">
                <div class="input-group">
                    <input type="text" id="messageInput" placeholder="Введите сообщение...">
                    <input type="file" id="imageInput" accept="image/*" style="display: none;">
                    <button id="uploadImageBtn"><i class="fas fa-image"></i></button>
                    <button id="sendBtn"><i class="fas fa-paper-plane"></i></button>
                </div>
            </div>
        </div>
    </div>

    <script>
        const socket = io();
        let currentRoom = 'general';
        
        function changeTheme(theme) {
            document.body.className = theme;
            fetch('/change_theme', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ theme: theme })
            });
        }

        function appendMessage(msg) {
            const messagesDiv = document.getElementById('messages');
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

        socket.on('new_message', (msg) => { appendMessage(msg); });

        function updateUsersList() {
            fetch('/get_users')
                .then(res => res.json())
                .then(users => {
                    const container = document.getElementById('usersList');
                    container.innerHTML = '';
                    let onlineCount = 0;
                    users.forEach(user => {
                        if (user.id != {{ session['user_id'] }}) {
                            const isOnline = user.status === 'online';
                            if (isOnline) onlineCount++;
                            container.innerHTML += `
                                <div style="padding:10px; display:flex; align-items:center; gap:10px;">
                                    <div style="width:10px; height:10px; background:${isOnline ? '#4ade80' : '#a0a0a0'}; border-radius:50%;"></div>
                                    <span>${escapeHtml(user.username)}</span>
                                    <small style="margin-left:auto;">${user.user_id_display}</small>
                                </div>
                            `;
                        }
                    });
                    document.getElementById('onlineCount').innerText = onlineCount;
                });
        }

        document.getElementById('sendBtn').onclick = () => {
            const text = document.getElementById('messageInput').value.trim();
            if (text) {
                socket.emit('message', { text, room: currentRoom });
                document.getElementById('messageInput').value = '';
            }
        };

        document.getElementById('uploadImageBtn').onclick = () => document.getElementById('imageInput').click();
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

        document.querySelectorAll('.room-item').forEach(room => {
            room.onclick = () => {
                document.querySelectorAll('.room-item').forEach(r => r.classList.remove('active'));
                room.classList.add('active');
                currentRoom = room.getAttribute('data-room');
                document.getElementById('currentRoom').innerText = room.querySelector('span').innerText;
                fetch(`/get_messages?room=${currentRoom}`)
                    .then(res => res.json())
                    .then(messages => {
                        document.getElementById('messages').innerHTML = '';
                        messages.forEach(msg => appendMessage(msg));
                    });
            };
        });

        document.getElementById('messageInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') document.getElementById('sendBtn').click();
        });

        updateUsersList();
        setInterval(updateUsersList, 5000);
    </script>
</body>
</html>
    '''

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
            session['user_id_display'] = user.user_id_display
            user.status = 'online'
            user.last_seen = datetime.utcnow()
            db.session.commit()
            return redirect(url_for('chat'))
        return render_template_string(LOGIN_TEMPLATE, error='Неверное имя/ID или пароль')
    return render_template_string(LOGIN_TEMPLATE)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        bio = request.form.get('bio', '')
        
        if password != confirm_password:
            return render_template_string(REGISTER_TEMPLATE, error='Пароли не совпадают')
        if len(username) < 3:
            return render_template_string(REGISTER_TEMPLATE, error='Имя пользователя должно содержать минимум 3 символа')
        if User.query.filter_by(username=username).first():
            return render_template_string(REGISTER_TEMPLATE, error='Пользователь уже существует')
        
        user_id_display = generate_user_id()
        hashed_password = generate_password_hash(password)
        
        user = User(
            username=username,
            user_id_display=user_id_display,
            password=hashed_password,
            bio=bio,
            theme='dark'
        )
        db.session.add(user)
        db.session.commit()
        
        session['user_id'] = user.id
        session['username'] = user.username
        session['user_id_display'] = user.user_id_display
        
        return redirect(url_for('chat'))
    
    return render_template_string(REGISTER_TEMPLATE)

@app.route('/chat')
@login_required
def chat():
    user = User.query.get(session['user_id'])
    messages = Message.query.filter_by(room='general').order_by(Message.timestamp).limit(100).all()
    theme = user.theme if user.theme else 'dark'
    return render_template_string(get_chat_template(), 
                                  username=user.username, 
                                  user_id_display=user.user_id_display,
                                  messages=messages,
                                  theme=theme,
                                  session=session)

@app.route('/get_messages')
@login_required
def get_messages():
    room = request.args.get('room', 'general')
    messages = Message.query.filter_by(room=room).order_by(Message.timestamp).limit(100).all()
    return jsonify([{
        'id': m.id,
        'username': User.query.get(m.user_id).username,
        'text': m.content,
        'file_url': m.file_url,
        'file_type': m.file_type,
        'timestamp': m.timestamp.strftime('%H:%M'),
        'room': m.room
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
        'avatar': u.avatar
    } for u in users])

@app.route('/change_theme', methods=['POST'])
@login_required
def change_theme():
    data = request.get_json()
    theme = data.get('theme', 'dark')
    user = User.query.get(session['user_id'])
    user.theme = theme
    db.session.commit()
    return jsonify({'status': 'ok'})

PROFILE_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Профиль - ChatVerse</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 600px;
            margin: 0 auto;
            background: white;
            border-radius: 30px;
            overflow: hidden;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px;
            text-align: center;
        }
        .avatar {
            width: 100px;
            height: 100px;
            background: white;
            border-radius: 50%;
            margin: 0 auto 15px;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
        }
        .form-container { padding: 40px; }
        .form-group { margin-bottom: 25px; }
        label { display: block; margin-bottom: 8px; color: #333; font-weight: 500; }
        input, textarea {
            width: 100%;
            padding: 12px 15px;
            border: 2px solid #e0e0e0;
            border-radius: 12px;
            font-size: 14px;
        }
        textarea { resize: vertical; min-height: 80px; }
        button {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 12px;
            cursor: pointer;
        }
        .back-btn {
            display: inline-block;
            margin-top: 20px;
            padding: 10px 20px;
            background: #666;
            color: white;
            text-decoration: none;
            border-radius: 25px;
            text-align: center;
        }
        .user-id { font-family: monospace; font-size: 18px; font-weight: bold; color: #667eea; }
        .warning { background: #fff3e0; color: #e67e22; padding: 10px; border-radius: 8px; font-size: 12px; margin-top: 10px; }
        .success { background: #d4edda; color: #155724; padding: 12px; border-radius: 10px; margin-bottom: 20px; text-align: center; }
        .error { background: #fee; color: #c33; padding: 12px; border-radius: 10px; margin-bottom: 20px; text-align: center; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="avatar">
                {% if user.avatar %}
                    <img src="{{ user.avatar }}" alt="avatar">
                {% else %}
                    <div style="font-size: 50px;">👤</div>
                {% endif %}
            </div>
            <h2>{{ user.username }}</h2>
            <p>ID: <span class="user-id">{{ user.user_id_display }}</span></p>
        </div>
        <div class="form-container">
            {% if success %}<div class="success">{{ success }}</div>{% endif %}
            {% if error %}<div class="error">{{ error }}</div>{% endif %}
            
            <form method="post" enctype="multipart/form-data" action="/update_profile">
                <div class="form-group">
                    <label>📷 Аватар</label>
                    <input type="file" name="avatar" accept="image/*">
                    {% if can_change_avatar %}
                        <div class="warning">✅ Вы можете сменить аватар</div>
                    {% else %}
                        <div class="warning">⏰ Следующая смена аватара через {{ days_left }} дн.</div>
                    {% endif %}
                </div>
                <div class="form-group">
                    <label>📝 О себе</label>
                    <textarea name="bio">{{ user.bio }}</textarea>
                </div>
                <div class="form-group">
                    <label>🔒 Новый пароль</label>
                    <input type="password" name="new_password" placeholder="Оставьте пустым, если не хотите менять">
                </div>
                <button type="submit">Сохранить изменения</button>
            </form>
            <a href="/chat" class="back-btn">← Вернуться в чат</a>
        </div>
    </div>
</body>
</html>
'''

@app.route('/profile')
@login_required
def profile():
    user = User.query.get(session['user_id'])
    can_change_avatar = True
    days_left = 0
    
    if user.last_avatar_change:
        week_ago = datetime.utcnow() - timedelta(days=7)
        if user.last_avatar_change > week_ago:
            can_change_avatar = False
            days_left = 7 - (datetime.utcnow() - user.last_avatar_change).days
    
    return render_template_string(PROFILE_TEMPLATE, user=user, can_change_avatar=can_change_avatar, days_left=days_left)

@app.route('/update_profile', methods=['POST'])
@login_required
def update_profile():
    user = User.query.get(session['user_id'])
    error = None
    success = None
    
    if 'avatar' in request.files:
        file = request.files['avatar']
        if file and file.filename:
            can_change = True
            if user.last_avatar_change:
                week_ago = datetime.utcnow() - timedelta(days=7)
                if user.last_avatar_change > week_ago:
                    can_change = False
                    error = '❌ Смену аватара можно делать не чаще 1 раза в неделю!'
            
            if can_change:
                filename = f"{user.id}_{datetime.utcnow().timestamp()}_{secure_filename(file.filename)}"
                save_path = os.path.join(app.config['UPLOAD_FOLDER_AVATARS'], filename)
                file.save(save_path)
                user.avatar = f"/{save_path}"
                user.last_avatar_change = datetime.utcnow()
                success = '✅ Аватар успешно обновлен!'
    
    if 'bio' in request.form:
        user.bio = request.form['bio']
        success = success or '✅ Профиль обновлен!'
    
    if 'new_password' in request.form and request.form['new_password']:
        user.password = generate_password_hash(request.form['new_password'])
        success = success or '✅ Пароль изменен!'
    
    db.session.commit()
    
    can_change_avatar = True
    days_left = 0
    if user.last_avatar_change:
        week_ago = datetime.utcnow() - timedelta(days=7)
        if user.last_avatar_change > week_ago:
            can_change_avatar = False
            days_left = 7 - (datetime.utcnow() - user.last_avatar_change).days
    
    return render_template_string(PROFILE_TEMPLATE, user=user, success=success, error=error, can_change_avatar=can_change_avatar, days_left=days_left)

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

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory('uploads', filename)

# ============ SOCKETIO СОБЫТИЯ ============

@socketio.on('connect')
def handle_connect():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            user.status = 'online'
            user.last_seen = datetime.utcnow()
            db.session.commit()
            emit('user_online', {
                'user_id': user.id,
                'username': user.username
            }, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            user.status = 'offline'
            user.last_seen = datetime.utcnow()
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
