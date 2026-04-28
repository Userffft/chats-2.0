import os
from flask import Flask, render_template, request, redirect, url_for, session
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-here')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///chat.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Создаём папки для загрузок
os.makedirs('uploads/images', exist_ok=True)
os.makedirs('uploads/audio', exist_ok=True)

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Модели базы данных
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
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
        return 'Invalid credentials', 401
    return '''
        <form method="post">
            <input type="text" name="username" placeholder="Username">
            <input type="password" name="password" placeholder="Password">
            <button type="submit">Login</button>
        </form>
        <a href="/register">Register</a>
    '''

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])
        if User.query.filter_by(username=username).first():
            return 'User exists', 400
        user = User(username=username, password=password)
        db.session.add(user)
        db.session.commit()
        return redirect(url_for('login'))
    return '''
        <form method="post">
            <input type="text" name="username" placeholder="Username">
            <input type="password" name="password" placeholder="Password">
            <button type="submit">Register</button>
        </form>
    '''

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

# HTML шаблон
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Chat with Media</title>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <style>
        body { font-family: Arial; max-width: 800px; margin: auto; padding: 20px; }
        #messages { border: 1px solid #ccc; height: 400px; overflow-y: auto; padding: 10px; margin-bottom: 10px; }
        .message { margin: 5px 0; }
        .username { font-weight: bold; color: #2c3e50; }
        .timestamp { font-size: 0.7em; color: gray; margin-left: 10px; }
        img { max-width: 200px; max-height: 200px; margin-top: 5px; }
        audio { margin-top: 5px; }
        #controls button { margin: 5px; }
    </style>
</head>
<body>
    <h2>Chat: {{ username }}</h2>
    <button onclick="window.location.href='/logout'">Logout</button>
    <div id="messages">
        {% for msg in messages %}
            <div class="message">
                <span class="username">{{ msg.username }}:</span>
                {% if msg.content %}<span>{{ msg.content }}</span>{% endif %}
                {% if msg.file_type == 'image' %}
                    <br><img src="{{ msg.file_url }}">
                {% elif msg.file_type == 'audio' %}
                    <br><audio controls src="{{ msg.file_url }}"></audio>
                {% endif %}
                <span class="timestamp">{{ msg.timestamp }}</span>
            </div>
        {% endfor %}
    </div>
    <div id="controls">
        <input type="text" id="messageInput" placeholder="Type message..." style="width: 60%;">
        <button id="sendBtn">Send</button>
        <input type="file" id="imageInput" accept="image/*" style="display: none;">
        <button id="uploadImageBtn">📷 Image</button>
        <button id="recordBtn">🎤 Record</button>
        <button id="stopRecordBtn" disabled>Stop</button>
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
            div.innerHTML = `<span class="username">${msg.username}:</span>
                             ${msg.text ? `<span>${msg.text}</span>` : ''}
                             ${msg.file_type === 'image' ? `<br><img src="${msg.file_url}">` : ''}
                             ${msg.file_type === 'audio' ? `<br><audio controls src="${msg.file_url}"></audio>` : ''}
                             <span class="timestamp">${msg.timestamp}</span>`;
            messagesDiv.appendChild(div);
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
        });

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
    </script>
</body>
</html>
'''

# Это ОЧЕНЬ ВАЖНО для Render - переменная app должна существовать
if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
