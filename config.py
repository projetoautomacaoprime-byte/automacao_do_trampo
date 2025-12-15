import os
import json
import logging
from datetime import timedelta
from flask import Flask
import firebase_admin
from firebase_admin import credentials, firestore

# --- Configurar logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuração do Flask ---
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "uma_chave_padrao_se_nao_definida")
app.config["WTF_CSRF_ENABLED"] = True
SESSION_TIMEOUT_MINUTES = 30
app.permanent_session_lifetime = timedelta(minutes=SESSION_TIMEOUT_MINUTES)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# --- Inicializar Firebase diretamente da variável de ambiente ---
firebase_creds_json = os.getenv("FIREBASE_CREDENTIALS")
if not firebase_creds_json:
    raise ValueError("FIREBASE_CREDENTIALS não está definido no ambiente")

try:
    firebase_creds_dict = json.loads(firebase_creds_json)
except json.JSONDecodeError as e:
    raise ValueError("FIREBASE_CREDENTIALS não é um JSON válido") from e

cred = credentials.Certificate(firebase_creds_dict)

try:
    firebase_admin.get_app()
    logger.info("Firebase já estava inicializado")
except ValueError:
    firebase_admin.initialize_app(cred)
    logger.info("Firebase inicializado com sucesso")

db = firestore.client()
