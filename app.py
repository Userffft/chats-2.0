import os
from flask import Flask, render_template, request, redirect, url_for, session
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from db import db, User, Message
from datetime import datetime

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chat.db'
app.config['UPLOAD_FOLDER_IMAGES'] = 'uploads/images'
app.config['UPLOAD_FOLDER_AUDIO'] = 'uploads/audio'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

os.makedirs(app.config['UPLOAD_FOLDER_IMAGES'], exist_ok=True)
os.makedirs(app.config['UPLOAD_FOLDER_AUDIO'], exist_ok=True)

db.init_app(app)
with app.app_context():
    db.create_all()

socketio = SocketIO(app, cors_allowed_origins="*")

# ---------- Маршруты ----------
@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('chat'))

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
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])
        if User.query.filter_by(username=username).first():
            return "User exists"
        new_user = User(username=username, password=password)
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/chat')
def chat():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    # загрузим последние 100 сообщений из общей комнаты
    messages = Message.query.filter_by(room='general').order_by(Message.timestamp).limit(100).all()
    return render_template('chat.html', username=session['username'], messages=messages)

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

    # определяем тип файла
    file_type = 'image' if file.content_type.startswith('image/') else 'audio'
    subfolder = 'images' if file_type == 'image' else 'audio'
    filename = f"{datetime.utcnow().timestamp()}_{secure_filename(file.filename)}"
    save_path = os.path.join('uploads', subfolder, filename)
    file.save(save_path)
    file_url = f"/{save_path}"
    return {'file_url': file_url, 'file_type': file_type}

# ---------- SocketIO обработчики ----------
@socketio.on('join')
def handle_join(data):
    room = data.get('room', 'general')
    join_room(room)
    emit('system', f"{session['username']} вошёл в комнату {room}", room=room)

@socketio.on('leave')
def handle_leave(data):
    room = data.get('room', 'general')
    leave_room(room)

@socketio.on('message')
def handle_message(data):
    user_id = session['user_id']
    room = data.get('room', 'general')
    text = data.get('text', '').strip()
    file_url = data.get('file_url')
    file_type = data.get('file_type')

    new_msg = Message(
        room=room,
        user_id=user_id,
        content=text if text else None,
        file_url=file_url,
        file_type=file_type
    )
    db.session.add(new_msg)
    db.session.commit()

    emit('new_message', {
        'username': session['username'],
        'text': text,
        'file_url': file_url,
        'file_type': file_type,
        'timestamp': new_msg.timestamp.strftime('%H:%M')
    }, room=room, include_self=True)

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)