import os
from datetime import timedelta
import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask
from dotenv import load_dotenv
import logging

# --- Configurar logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Carregar variáveis do .env ---
load_dotenv()

# --- Configuração do Flask ---
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")
app.config["WTF_CSRF_ENABLED"] = True
SESSION_TIMEOUT_MINUTES = 30
app.permanent_session_lifetime = timedelta(minutes=SESSION_TIMEOUT_MINUTES)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# --- Inicializar Firebase ---
firebase_creds_path = os.getenv("FIREBASE_CREDENTIALS")
if not firebase_creds_path:
    raise ValueError("FIREBASE_CREDENTIALS não está definido no .env")
if not os.path.isfile(firebase_creds_path):
    raise FileNotFoundError(f"Arquivo de credenciais não encontrado: {firebase_creds_path}")

cred = credentials.Certificate(firebase_creds_path)

try:
    firebase_admin.get_app()
    logger.info("Firebase já estava inicializado")
except ValueError:
    try:
        firebase_admin.initialize_app(cred)
        logger.info("Firebase inicializado com sucesso")
    except Exception as e:
        logger.exception("Falha ao inicializar o Firebase: %s", e)
        raise

db = firestore.client()
