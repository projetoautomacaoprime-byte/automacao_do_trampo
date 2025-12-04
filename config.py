import os
from datetime import timedelta
import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask
from dotenv import load_dotenv

# --- Carregar variáveis do .env ---
load_dotenv()

# --- Configuração do Flask ---
app = Flask(__name__)

# SECRET KEY obrigatória para CSRF funcionar
app.secret_key = os.getenv("SECRET_KEY")

# CSRF ativado
app.config["WTF_CSRF_ENABLED"] = True

# Tempo de sessão
SESSION_TIMEOUT_MINUTES = 30
app.permanent_session_lifetime = timedelta(minutes=SESSION_TIMEOUT_MINUTES)

# Cookies mais seguros
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# --- Inicializar Firebase ---
firebase_creds_path = os.getenv("FIREBASE_CREDENTIALS")
if not firebase_creds_path:
    raise ValueError("FIREBASE_CREDENTIALS não está definido no .env")

cred = credentials.Certificate(firebase_creds_path)
try:
    firebase_admin.get_app()
except ValueError:
    firebase_admin.initialize_app(cred)

db = firestore.client()
