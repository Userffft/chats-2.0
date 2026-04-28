import os
from flask import Flask, render_template_string, request, redirect, url_for, session
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

# СНАЧАЛА создаём приложение
app = Flask(__name__)

# ПОТОМ настраиваем конфигурацию
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')

# Настройка базы данных
database_url = os.environ.get('DATABASE_URL', 'sqlite:///chat.db')
if database_url and database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Настройка загрузки файлов
app.config['UPLOAD_FOLDER_IMAGES'] = 'uploads/images'
app.config['UPLOAD_FOLDER_AUDIO'] = 'uploads/audio'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

# Создаём папки для загрузок
os.makedirs(app.config['UPLOAD_FOLDER_IMAGES'], exist_ok=True)
os.makedirs(app.config['UPLOAD_FOLDER_AUDIO'], exist_ok=True)

# Инициализируем расширения
db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Модели базы данных
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    avatar = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    room = db.Column(db.String(50), default='general')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    content = db.Column(db.Text)
    file_url = db.Column(db.String(200))
    file_type = db.Column(db.String(20))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        user = User.query.get(self.user_id)
        return {
            'id': self.id,
            'username': user.username if user else 'Unknown',
            'content': self.content,
            'file_url': self.file_url,
            'file_type': self.file_type,
            'timestamp': self.timestamp.strftime('%H:%M')
        }

# Создаём таблицы
with app.app_context():
    db.create_all()

# HTML шаблон для страницы входа (с красивым дизайном)
LOGIN_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Вход в чат</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
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
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
            width: 400px;
            max-width: 90%;
            animation: slideIn 0.5s ease-out;
        }
        @keyframes slideIn {
            from {
                opacity: 0;
                transform: translateY(-50px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px;
            text-align: center;
        }
        .header h1 {
            font-size: 28px;
            margin-bottom: 10px;
        }
        .header p {
            opacity: 0.9;
            font-size: 14px;
        }
        .form-container {
            padding: 40px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            color: #333;
            font-weight: 500;
        }
        input {
            width: 100%;
            padding: 12px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
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
            padding: 12px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s;
        }
        button:hover {
            transform: translateY(-2px);
        }
        button:active {
            transform: translateY(0);
        }
        .footer {
            text-align: center;
            margin-top: 20px;
            color: #666;
        }
        .footer a {
            color: #667eea;
            text-decoration: none;
            font-weight: 600;
        }
        .footer a:hover {
            text-decoration: underline;
        }
        .error {
            background: #fee;
            color: #c33;
            padding: 10px;
            border-radius: 8px;
            margin-bottom: 20px;
            text-align: center;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>💬 Мессенджер</h1>
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

# HTML шаблон для страницы регистрации
REGISTER_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Регистрация в чате</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
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
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
            width: 400px;
            max-width: 90%;
            animation: slideIn 0.5s ease-out;
        }
        @keyframes slideIn {
            from {
                opacity: 0;
                transform: translateY(-50px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 40px;
            text-align: center;
        }
        .header h1 {
            font-size: 28px;
            margin-bottom: 10px;
        }
        .header p {
            opacity: 0.9;
            font-size: 14px;
        }
        .form-container {
            padding: 40px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            color: #333;
            font-weight: 500;
        }
        input {
            width: 100%;
            padding: 12px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
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
            padding: 12px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s;
        }
        button:hover {
            transform: translateY(-2px);
        }
        button:active {
            transform: translateY(0);
        }
        .footer {
            text-align: center;
            margin-top: 20px;
            color: #666;
        }
        .footer a {
            color: #667eea;
            text-decoration: none;
            font-weight: 600;
        }
        .footer a:hover {
            text-decoration: underline;
        }
        .error {
            background: #fee;
            color: #c33;
            padding: 10px;
            border-radius: 8px;
            margin-bottom: 20px;
            text-align: center;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📝 Регистрация</h1>
            <p>Создайте новый аккаунт</p>
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
        
        if User.query.filter_by(username=username).first():
            return render_template_string(REGISTER_TEMPLATE, error='Пользователь уже существует')
        
        hashed_password = generate_password_hash(password)
        user = User(username=username, password=hashed_password)
        db.session.add(user)
        db.session.commit()
        return redirect(url_for('login'))
    
    return render_template_string(REGISTER_TEMPLATE)

@app.route('/chat')
def chat():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    messages = Message.query.filter_by(room='general').order_by(Message.timestamp).limit(100).all()
    return render_template_string(HTML_TEMPLATE, username=session['username'], messages=messages)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'user_id' not in session:
        return {'error': 'unauthorized'}, 401
    if 'file' not in request.files:
        return {'error': 'no file'}, 400
    file = request.files['file']
    if file.filename == '':
        return {'error': 'empty filename'}, 400
    
    file_type = 'image' if file.content_type.startswith('image/') else 'audio'
    subfolder = 'images' if file_type == 'image' else 'audio'
    filename = f"{datetime.utcnow().timestamp()}_{secure_filename(file.filename)}"
    save_path = os.path.join('uploads', subfolder, filename)
    file.save(save_path)
    file_url = f"/{save_path}"
    return {'file_url': file_url, 'file_type': file_type}

# SocketIO события
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
    
    emit('new_message', {
        'username': session['username'],
        'text': text,
        'file_url': file_url,
        'file_type': file_type,
        'timestamp': msg.timestamp.strftime('%H:%M')
    }, room=room, broadcast=True)

# HTML шаблон для самого чата
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Чат - {{ username }}</title>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .chat-container {
            width: 90%;
            max-width: 1000px;
            height: 85vh;
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        .chat-header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .chat-header h2 {
            font-size: 20px;
        }
        .logout-btn {
            background: rgba(255,255,255,0.2);
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.3s;
        }
        .logout-btn:hover {
            background: rgba(255,255,255,0.3);
            transform: translateY(-1px);
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
            from {
                opacity: 0;
                transform: translateY(10px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        .message-header {
            display: flex;
            align-items: baseline;
            margin-bottom: 5px;
        }
        .username {
            font-weight: bold;
            color: #667eea;
            margin-right: 10px;
        }
        .timestamp {
            font-size: 0.7em;
            color: #999;
        }
        .message-content {
            background: white;
            padding: 10px;
            border-radius: 10px;
            display: inline-block;
            max-width: 70%;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }
        .message-text {
            margin: 0;
            word-wrap: break-word;
        }
        .message-image {
            max-width: 300px;
            max-height: 300px;
            border-radius: 10px;
            margin-top: 5px;
        }
        .message-audio {
            margin-top: 5px;
        }
        .controls-area {
            padding: 20px;
            background: white;
            border-top: 1px solid #e0e0e0;
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        #messageInput {
            flex: 1;
            padding: 12px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 14px;
        }
        #messageInput:focus {
            outline: none;
            border-color: #667eea;
        }
        .btn {
            padding: 12px 20px;
            background: #f0f0f0;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.3s;
            font-size: 14px;
        }
        .btn-primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        .btn-primary:hover {
            transform: translateY(-1px);
            box-shadow: 0 5px 15px rgba(102,126,234,0.4);
        }
        .btn:hover {
            transform: translateY(-1px);
        }
        .btn:active {
            transform: translateY(0);
        }
        @media (max-width: 768px) {
            .message-content {
                max-width: 90%;
            }
            .controls-area {
                flex-wrap: wrap;
            }
            .btn {
                padding: 8px 12px;
                font-size: 12px;
            }
        }
    </style>
</head>
<body>
    <div class="chat-container">
        <div class="chat-header">
            <h2>💬 Общий чат</h2>
            <button class="logout-btn" onclick="window.location.href='/logout'">🚪 Выйти</button>
        </div>
        <div class="messages-area" id="messages">
            {% for msg in messages %}
                <div class="message">
                    <div class="message-header">
                        <span class="username">{{ msg.user.username }}:</span>
                        <span class="timestamp">{{ msg.timestamp.strftime('%H:%M') }}</span>
                    </div>
                    <div class="message-content">
                        {% if msg.content %}
                            <p class="message-text">{{ msg.content }}</p>
                        {% endif %}
                        {% if msg.file_type == 'image' %}
                            <img class="message-image" src="{{ msg.file_url }}" alt="image">
                        {% elif msg.file_type == 'audio' %}
                            <audio class="message-audio" controls src="{{ msg.file_url }}"></audio>
                        {% endif %}
                    </div>
                </div>
            {% endfor %}
        </div>
        <div class="controls-area">
            <input type="text" id="messageInput" placeholder="Введите сообщение..." autofocus>
            <button class="btn btn-primary" id="sendBtn">Отправить</button>
            <input type="file" id="imageInput" accept="image/*" style="display: none;">
            <button class="btn" id="uploadImageBtn">📷 Изображение</button>
            <button class="btn" id="recordBtn">🎤 Запись</button>
            <button class="btn" id="stopRecordBtn" disabled>⏹️ Стоп</button>
        </div>
    </div>

    <script>
        const socket = io();
        const messagesDiv = document.getElementById('messages');
        const messageInput = document.getElementById('messageInput');
        const sendBtn = document.getElementById('sendBtn');
        const uploadImageBtn = document.getElementById('uploadImageBtn');
        const imageInput = document.getElementById('imageInput');
        const recordBtn = document.getElementById('recordBtn');
        const stopBtn = document.getElementById('stopRecordBtn');
        let mediaRecorder;
        let audioChunks = [];

        socket.on('new_message', (msg) => {
            const div = document.createElement('div');
            div.className = 'message';
            div.innerHTML = `
                <div class="message-header">
                    <span class="username">${escapeHtml(msg.username)}:</span>
                    <span class="timestamp">${msg.timestamp}</span>
                </div>
                <div class="message-content">
                    ${msg.text ? `<p class="message-text">${escapeHtml(msg.text)}</p>` : ''}
                    ${msg.file_type === 'image' ? `<img class="message-image" src="${msg.file_url}">` : ''}
                    ${msg.file_type === 'audio' ? `<audio class="message-audio" controls src="${msg.file_url}"></audio>` : ''}
                </div>
            `;
            messagesDiv.appendChild(div);
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
        });

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        sendBtn.onclick = () => {
            const text = messageInput.value.trim();
            if (text) {
                socket.emit('message', { text });
                messageInput.value = '';
            }
        };

        uploadImageBtn.onclick = () => imageInput.click();
        imageInput.onchange = async (e) => {
            const file = e.target.files[0];
            if (!file) return;
            const formData = new FormData();
            formData.append('file', file);
            const res = await fetch('/upload', { method: 'POST', body: formData });
            const data = await res.json();
            if (data.file_url) {
                socket.emit('message', { file_url: data.file_url, file_type: 'image' });
            }
            imageInput.value = '';
        };

        recordBtn.onclick = async () => {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorder = new MediaRecorder(stream);
            audioChunks = [];
            mediaRecorder.ondataavailable = event => audioChunks.push(event.data);
            mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
                const formData = new FormData();
                formData.append('file', audioBlob, 'voice.webm');
                const res = await fetch('/upload', { method: 'POST', body: formData });
                const data = await res.json();
                if (data.file_url) {
                    socket.emit('message', { file_url: data.file_url, file_type: 'audio' });
                }
                stream.getTracks().forEach(track => track.stop());
            };
            mediaRecorder.start();
            recordBtn.disabled = true;
            stopBtn.disabled = false;
        };

        stopBtn.onclick = () => {
            mediaRecorder.stop();
            recordBtn.disabled = false;
            stopBtn.disabled = true;
        };

        messageInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') sendBtn.click();
        });

        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    </script>
</body>
</html>
'''

# Это для локального запуска (Render использует Gunicorn, поэтому этот блок не обязателен)
if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
