from flask import Blueprint, render_template, request, redirect, url_for, session
from werkzeug.security import check_password_hash, generate_password_hash
from config import db
from datetime import datetime, timezone

bp = Blueprint('auth', __name__)

@bp.route('/')
def home():
    return render_template('login.html')

@bp.route('/login', methods=['POST'])
def login():
    username = request.form.get('username','').strip()
    password = request.form.get('password','')
    usuarios_ref = db.collection('usuarios')
    query = usuarios_ref.where('username','==',username).limit(1).stream()
    user_doc = next(query, None)

    if user_doc:
        user_data = user_doc.to_dict()
        password_hash = user_data.get('password_hash')
        if password_hash and check_password_hash(password_hash,password):
            session.clear()
            session.permanent = True
            session['logged_in'] = True
            session['username'] = username
            session['role'] = user_data.get('role','user')
            session['last_seen'] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S%z")
            return redirect(url_for('dashboard.dashboard'))
    return 'Usuário ou senha incorretos!', 401

@bp.route('/alterar_senha', methods=['POST'])
def alterar_senha():
    if not session.get('logged_in'):
        return redirect(url_for('auth.home'))
    username = session.get('username')
    nova = request.form.get('nova_senha','').strip()
    if not nova:
        return "Senha inválida",400
    password_hash = generate_password_hash(nova)
    now = datetime.now(timezone.utc).isoformat()
    db.collection("usuarios").document(username).update({
        "password_hash": password_hash,
        "password_changed_at": now
    })
    session.clear()
    return redirect(url_for('auth.home'))

@bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.home'))
