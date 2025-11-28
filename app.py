import os
from datetime import timedelta, datetime, timezone
from flask import Flask, session, redirect, url_for
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

# --- Carregar variáveis do .env ---
load_dotenv()

# --- Configuração Flask ---
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")
SESSION_TIMEOUT_MINUTES = 30
app.permanent_session_lifetime = timedelta(minutes=SESSION_TIMEOUT_MINUTES)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# --- Inicializar Firebase ---
firebase_creds_path = os.getenv("FIREBASE_CREDENTIALS")
if not firebase_creds_path:
    raise ValueError("FIREBASE_CREDENTIALS não está definido no .env")

cred = credentials.Certificate(firebase_creds_path)
firebase_admin.initialize_app(cred)
db = firestore.client()

# --- Importar blueprints ---
from routes.auth import bp as auth_bp
from routes.dashboard import bp as dashboard_bp
from routes.fluxo import bp as fluxo_bp
from routes.consulta import bp as consulta_bp

# --- Registrar blueprints ---
app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(fluxo_bp)
app.register_blueprint(consulta_bp)

# --- Controle de sessão ---
@app.before_request
def verificar_sessao():
    if not session.get("logged_in"):
        return None
    last_seen = session.get("last_seen")
    now = datetime.now(timezone.utc)
    if last_seen:
        try:
            ultimo_acesso = datetime.strptime(last_seen, "%Y-%m-%d %H:%M:%S%z")
        except Exception:
            session.clear()
            return redirect(url_for("auth.home"))
        if (now - ultimo_acesso) > app.permanent_session_lifetime:
            session.clear()
            return redirect(url_for("auth.home"))
    session['last_seen'] = now.strftime("%Y-%m-%d %H:%M:%S%z")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
