import os
import random
import string
from flask import Flask, render_template_string, request, redirect, url_for, session, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from functools import wraps

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
    user_id_display = db.Column(db.String(8), unique=True, nullable=False)  # ID от 4 до 8 символов
    password = db.Column(db.String(200), nullable=False)
    avatar = db.Column(db.String(200), default=None)
    bio = db.Column(db.String(200), default='')
    status = db.Column(db.String(50), default='online')
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_avatar_change = db.Column(db.DateTime, default=None)  # Для отслеживания смены аватара

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

# Функция генерации уникального ID
def generate_user_id():
    while True:
        length = random.choice([4, 5, 6, 7, 8])
        user_id = ''.join(random.choices(string.ascii_letters + string.digits, k=length))
        if not User.query.filter_by(user_id_display=user_id).first():
            return user_id

# Создание таблиц
with app.app_context():
    db.create_all()

# Декоратор авторизации
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
    <title>ChatVerse - Вход</title>
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
            background: white;
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
    <title>ChatVerse - Регистрация</title>
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
            background: white;
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
                ℹ️ Вы получите уникальный ID (4-8 символов) для входа в систему
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

PROFILE_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Мой профиль - ChatVerse</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 600px;
            margin: 0 auto;
            background: white;
            border-radius: 30px;
            box-shadow: 0 30px 70px rgba(0,0,0,0.3);
            overflow: hidden;
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
            position: relative;
        }
        .avatar {
            width: 120px;
            height: 120px;
            background: white;
            border-radius: 50%;
            margin: 0 auto 15px;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
        }
        .avatar img {
            width: 100%;
            height: 100%;
            object-fit: cover;
        }
        .avatar-placeholder {
            font-size: 60px;
        }
        .back-btn {
            position: absolute;
            top: 20px;
            left: 20px;
            background: rgba(255,255,255,0.2);
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 20px;
            cursor: pointer;
            text-decoration: none;
            font-size: 14px;
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
        button:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }
        .info-box {
            background: #f0f0f0;
            padding: 15px;
            border-radius: 12px;
            margin-bottom: 20px;
        }
        .user-id {
            font-family: monospace;
            font-size: 18px;
            font-weight: bold;
            color: #667eea;
        }
        .warning {
            background: #fff3e0;
            color: #e67e22;
            padding: 10px;
            border-radius: 8px;
            font-size: 12px;
            margin-top: 10px;
        }
        .success {
            background: #d4edda;
            color: #155724;
            padding: 12px;
            border-radius: 10px;
            margin-bottom: 20px;
            text-align: center;
        }
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
            <a href="/chat" class="back-btn">← Назад в чат</a>
            <div class="avatar">
                {% if user.avatar %}
                    <img src="{{ user.avatar }}" alt="avatar">
                {% else %}
                    <div class="avatar-placeholder">👤</div>
                {% endif %}
            </div>
            <h2>{{ user.username }}</h2>
            <p>ID: <span class="user-id">{{ user.user_id_display }}</span></p>
        </div>
        <div class="form-container">
            {% if success %}
                <div class="success">{{ success }}</div>
            {% endif %}
            {% if error %}
                <div class="error">{{ error }}</div>
            {% endif %}
            
            <form method="post" enctype="multipart/form-data" action="/update_profile">
                <div class="form-group">
                    <label>📷 Аватар</label>
                    <input type="file" name="avatar" accept="image/*">
                    {% if can_change_avatar %}
                        <div class="warning">✅ Вы можете сменить аватар (бесплатно)</div>
                    {% else %}
                        <div class="warning">⏰ Следующая смена аватара доступна через {{ days_left }} дн.</div>
                    {% endif %}
                </div>
                <div class="form-group">
                    <label>📝 О себе</label>
                    <textarea name="bio" placeholder="Расскажите о себе...">{{ user.bio }}</textarea>
                </div>
                <div class="form-group">
                    <label>🔒 Новый пароль (оставьте пустым, если не хотите менять)</label>
                    <input type="password" name="new_password" placeholder="Новый пароль">
                </div>
                <div class="info-box">
                    <strong>Ваш ID:</strong> <span class="user-id">{{ user.user_id_display }}</span><br>
                    <small>Используйте этот ID для входа в систему</small>
                </div>
                <button type="submit">Сохранить изменения</button>
            </form>
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
        
        # Поиск по username или user_id_display
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
        return render_template_string(LOGIN_TEMPLATE, error='Неверное имя пользователя/ID или пароль')
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
            bio=bio
        )
        db.session.add(user)
        db.session.commit()
        
        # Автоматический вход после регистрации
        session['user_id'] = user.id
        session['username'] = user.username
        session['user_id_display'] = user.user_id_display
        
        return redirect(url_for('chat'))
    
    return render_template_string(REGISTER_TEMPLATE)

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
    
    # Обновление аватара
    if 'avatar' in request.files:
        file = request.files['avatar']
        if file and file.filename:
            # Проверка на возможность смены аватара
            can_change = True
            if user.last_avatar_change:
                week_ago = datetime.utcnow() - timedelta(days=7)
                if user.last_avatar_change > week_ago:
                    can_change = False
                    error = 'Смену аватара можно делать не чаще 1 раза в неделю'
            
            if can_change:
                filename = f"{user.id}_{datetime.utcnow().timestamp()}_{secure_filename(file.filename)}"
                save_path = os.path.join(app.config['UPLOAD_FOLDER_AVATARS'], filename)
                file.save(save_path)
                user.avatar = f"/{save_path}"
                user.last_avatar_change = datetime.utcnow()
                success = 'Аватар успешно обновлен'
    
    # Обновление bio
    if 'bio' in request.form:
        user.bio = request.form['bio']
        success = success or 'Профиль обновлен'
    
    # Обновление пароля
    if 'new_password' in request.form and request.form['new_password']:
        user.password = generate_password_hash(request.form['new_password'])
        success = success or 'Пароль изменен'
    
    db.session.commit()
    return render_template_string(PROFILE_TEMPLATE, user=user, success=success, error=error, can_change_avatar=True, days_left=0)

@app.route('/chat')
@login_required
def chat():
    user = User.query.get(session['user_id'])
    messages = Message.query.filter_by(room='general').order_by(Message.timestamp).limit(100).all()
    users = User.query.all()
    return render_template_string(CHAT_TEMPLATE, username=user.username, user_id_display=user.user_id_display, messages=messages, users=users)

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
    from flask import send_from_directory
    return send_from_directory('uploads', filename)

# SocketIO события
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
                'username': user.username,
                'user_id_display': user.user_id_display
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
    
    emit('new_message', {
        'id': msg.id,
        'username': user.username,
        'user_id_display': user.user_id_display,
        'text': text,
        'file_url': file_url,
        'file_type': file_type,
        'timestamp': msg.timestamp.strftime('%H:%M'),
        'reply_to': reply_to
    }, room=room, broadcast=True)

@socketio.on('join')
def handle_join(data):
    room = data.get('room', 'general')
    join_room(room)
    emit('system_message', {
        'text': f"{session['username']} присоединился к комнате",
        'timestamp': datetime.now().strftime('%H:%M')
    }, room=room)

# CHAT_TEMPLATE (упрощенный, но полностью рабочий)
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
        .sidebar {
            width: 280px;
            background: white;
            display: flex;
            flex-direction: column;
            overflow-y: auto;
            box-shadow: 2px 0 10px rgba(0,0,0,0.1);
        }
        .user-profile {
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            text-align: center;
            cursor: pointer;
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
            overflow: hidden;
        }
        .avatar img { width: 100%; height: 100%; object-fit: cover; }
        .user-id-badge {
            font-size: 12px;
            opacity: 0.8;
            font-family: monospace;
        }
        .rooms { padding: 20px; border-bottom: 1px solid #e0e0e0; }
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
        .online-users { padding: 20px; flex: 1; }
        .user-item {
            padding: 10px;
            margin: 5px 0;
            border-radius: 10px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .online-dot {
            width: 10px;
            height: 10px;
            background: #4ade80;
            border-radius: 50%;
        }
        .offline-dot {
            width: 10px;
            height: 10px;
            background: #a0a0a0;
            border-radius: 50%;
        }
        .chat-main {
            flex: 1;
            display: flex;
            flex-direction: column;
            background: #f8f9fa;
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
        }
        .message {
            margin-bottom: 15px;
            animation: fadeIn 0.3s ease-out;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .message-header { margin-bottom: 5px; }
        .username { font-weight: bold; color: #667eea; margin-right: 10px; }
        .timestamp { font-size: 11px; color: #999; }
        .message-content {
            background: white;
            padding: 12px;
            border-radius: 12px;
            display: inline-block;
            max-width: 70%;
            box-shadow: 0 1px 2px rgba(0,0,0,0.1);
        }
        .message-image { max-width: 300px; border-radius: 8px; margin-top: 5px; }
        .controls-area {
            padding: 20px;
            background: white;
            border-top: 1px solid #e0e0e0;
        }
        .input-group {
            display: flex;
            gap: 10px;
        }
        #messageInput {
            flex: 1;
            padding: 12px 20px;
            border: 2px solid #e0e0e0;
            border-radius: 25px;
            font-size: 14px;
        }
        #messageInput:focus { outline: none; border-color: #667eea; }
        .typing-indicator {
            font-size: 12px;
            color: #666;
            padding: 5px 20px;
        }
        button {
            padding: 10px 18px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 25px;
            cursor: pointer;
            transition: all 0.3s;
        }
        button:hover { transform: translateY(-1px); box-shadow: 0 5px 15px rgba(102,126,234,0.3); }
        .logout-btn { background: #dc2626; }
        .logout-btn:hover { background: #b91c1c; }
        @media (max-width: 768px) { .sidebar { display: none; } .message-content { max-width: 90%; } }
    </style>
</head>
<body>
    <div class="app">
        <div class="sidebar">
            <div class="user-profile" onclick="window.location.href='/profile'">
                <div class="avatar">👤</div>
                <strong>{{ username }}</strong>
                <div class="user-id-badge">ID: {{ user_id_display }}</div>
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
                        <div class="user-item" data-user-id="{{ user.id }}" data-status="{{ user.status }}">
                            <div class="{% if user.status == 'online' %}online-dot{% else %}offline-dot{% endif %}"></div>
                            <span>{{ user.username }}</span>
                            <small style="margin-left: auto; font-size: 10px; color:#999;">{{ user.user_id_display }}</small>
                        </div>
                    {% endfor %}
                </div>
            </div>
        </div>
        <div class="chat-main">
            <div class="chat-header">
                <h2><i class="fas fa-comments"></i> <span id="currentRoom">Общий чат</span></h2>
                <button class="logout-btn" onclick="window.location.href='/logout'"><i class="fas fa-sign-out-alt"></i> Выйти</button>
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
        let typingTimeout;
        let isTyping = false;

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

        // Socket events
        socket.on('new_message', (msg) => {
            if (currentRoom === 'general') {
                appendMessage(msg);
            }
        });

        socket.on('user_online', (data) => {
            const userDiv = document.querySelector(`.user-item[data-user-id="${data.user_id}"]`);
            if (userDiv) {
                userDiv.querySelector('.online-dot, .offline-dot').className = 'online-dot';
                userDiv.setAttribute('data-status', 'online');
            }
            updateOnlineCount();
        });

        socket.on('user_offline', (data) => {
            const userDiv = document.querySelector(`.user-item[data-user-id="${data.user_id}"]`);
            if (userDiv) {
                userDiv.querySelector('.online-dot, .offline-dot').className = 'offline-dot';
                userDiv.setAttribute('data-status', 'offline');
            }
            updateOnlineCount();
        });

        socket.on('user_typing', (data) => {
            const indicator = document.getElementById('typingIndicator');
            if (data.is_typing) {
                indicator.innerHTML = `<i class="fas fa-ellipsis-h"></i> ${escapeHtml(data.username)} печатает...`;
            }
            setTimeout(() => { if (indicator.innerHTML.includes(data.username)) indicator.innerHTML = ''; }, 2000);
        });

        function updateOnlineCount() {
            const onlineUsers = document.querySelectorAll('.user-item[data-status="online"]').length;
            document.getElementById('onlineCount').innerText = onlineUsers;
        }

        // Send message
        const sendBtn = document.getElementById('sendBtn');
        const messageInput = document.getElementById('messageInput');
        
        sendBtn.onclick = () => {
            const text = messageInput.value.trim();
            if (text) {
                socket.emit('message', { text, room: currentRoom });
                messageInput.value = '';
            }
        };

        messageInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') sendBtn.click();
        });

        // Typing indicator
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

        // Image upload
        const uploadImageBtn = document.getElementById('uploadImageBtn');
        const imageInput = document.getElementById('imageInput');
        
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
            imageInput.value = '';
        };

        // Change room
        document.querySelectorAll('.room-item').forEach(room => {
            room.onclick = () => {
                document.querySelectorAll('.room-item').forEach(r => r.classList.remove('active'));
                room.classList.add('active');
                currentRoom = room.getAttribute('data-room');
                document.getElementById('currentRoom').innerText = room.querySelector('span').innerText;
                socket.emit('join', { room: currentRoom });
                document.getElementById('messages').innerHTML = '';
            };
        });

        updateOnlineCount();
        document.getElementById('messages').scrollTop = document.getElementById('messages').scrollHeight;
    </script>
</body>
</html>
'''

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
