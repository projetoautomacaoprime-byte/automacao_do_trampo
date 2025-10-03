import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
import os
from dotenv import load_dotenv
from datetime import timedelta, datetime

# Inicializar Firebase
cred = credentials.Certificate("credenciais.json")
firebase_admin.initialize_app(cred)
db = firestore.client()


print("Usuário criado com sucesso!")

# Carregar variáveis do .env
load_dotenv()

# Cria a aplicação Flask
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

# Define tempo máximo da sessão
SESSION_TIMEOUT_MINUTES = 30

@app.before_request
def verificar_sessao():
    if "logged_in" in session:
        ultimo_acesso = session.get("last_seen")
        agora = datetime.utcnow()

        if ultimo_acesso:
            ultimo_acesso = datetime.strptime(ultimo_acesso, "%Y-%m-%d %H:%M:%S")
            if (agora - ultimo_acesso) > timedelta(minutes=SESSION_TIMEOUT_MINUTES):
                # Expirou -> logout
                session.clear()
                return redirect(url_for("home"))
        
        # Atualiza último acesso
        session["last_seen"] = agora.strftime("%Y-%m-%d %H:%M:%S")

# Página inicial (login)
@app.route('/')
def home():
    return render_template('login.html')

# Processar login
@app.route('/login', methods=['POST'])
def login():
    username = request.form['username']
    password = request.form['password']

    # Busca usuário no Firebase
    usuarios_ref = db.collection('usuarios')
    query = usuarios_ref.where('username', '==', username).limit(1).stream()
    user_doc = next(query, None)

    if user_doc:
        user_data = user_doc.to_dict()
        password_hash = user_data.get('password_hash')

        # Verifica senha com hash
        if check_password_hash(password_hash, password):
            session['logged_in'] = True
            session['username'] = username
            session['last_seen'] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            return redirect(url_for('dashboard'))

    return 'Usuário ou senha incorretos!'

# Dashboard protegido
@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('home'))
    return f'Bem-vindo ao painel seguro, {session.get("username")}!'

if __name__ == '__main__':
    app.run(debug=True)
