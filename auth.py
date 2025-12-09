from flask import Blueprint, session, redirect, url_for, request, render_template
from werkzeug.security import check_password_hash, generate_password_hash
from config import db, app
from datetime import datetime, timezone
from security import get_identifier, check_block, register_attempt  # Funções brute force
import logging

# === Configurar logging ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)

# ------------------------------
# Funções auxiliares
# ------------------------------
def parse_datetime_safe(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S%z")
    except ValueError:
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
            return dt.replace(tzinfo=timezone.utc)
        except Exception as e:
            logger.warning("Falha ao parsear datetime: %s", e)
            return None


# ------------------------------
# Middleware de sessão
# ------------------------------
@app.before_request
def verificar_sessao():
    # Liberar arquivos estáticos e favicon
    if request.path.startswith("/static/") or request.path == "/favicon.ico":
        return None

    # Rotas públicas do auth
    if request.endpoint in ("auth.home", "auth.login", "auth.alterar_senha", "auth.logout"):
        return None

    if not session.get("logged_in"):
        return redirect(url_for("auth.home"))

    now = datetime.now(timezone.utc)
    last_seen = session.get("last_seen")
    if last_seen:
        ultimo_acesso = parse_datetime_safe(last_seen)
        if not ultimo_acesso or (now - ultimo_acesso) > app.permanent_session_lifetime:
            session.clear()
            return redirect(url_for("auth.home"))

    # Checar se senha foi alterada
    username = session.get("username")
    if username:
        try:
            doc = db.collection("usuarios").document(username).get()
            if doc.exists:
                u = doc.to_dict()
                pwd_changed = u.get("password_changed_at")
                if pwd_changed:
                    pwd_changed_dt = datetime.fromisoformat(pwd_changed)
                    session_created = parse_datetime_safe(session.get("last_seen"))
                    if session_created and pwd_changed_dt > session_created:
                        session.clear()
                        return redirect(url_for("auth.home"))
        except Exception as e:
            logger.warning("Falha ao validar senha alterada para usuário %s: %s", username, e)

    session["last_seen"] = now.strftime("%Y-%m-%d %H:%M:%S%z")
    return None


# ------------------------------
# Rotas
# ------------------------------
@auth_bp.route("/")
def home():
    return render_template("login.html")


@auth_bp.route("/login", methods=["POST"])
def login():
    # **CSRF será validado automaticamente pelo Flask-WTF antes de entrar aqui**
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    ip = request.remote_addr

    # Validação mínima de tamanho
    if len(username) > 50 or len(password) > 1000:
        return "Entrada inválida", 400

    # Proteção Brute Force
    identifier = get_identifier(email=username, ip=ip)
    blocked, seconds_left = check_block(identifier)
    if blocked:
        return f"Conta bloqueada. Tente novamente em {seconds_left//60} minutos.", 403

    # Verificação de credenciais
    query = db.collection("usuarios").where("username", "==", username).limit(1).stream()
    user_doc = next(query, None)

    if user_doc:
        user_data = user_doc.to_dict()
        if check_password_hash(user_data.get("password_hash", ""), password):
            # Login correto -> reset de tentativas
            register_attempt(identifier, success=True)

            # Limpa sessão apenas após login bem-sucedido
            session.clear()
            session.permanent = True
            session["logged_in"] = True
            session["username"] = username
            session["role"] = user_data.get("role", "user")
            session["last_seen"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S%z")
            return redirect(url_for("dashboard.dashboard"))

    # Login incorreto -> registra tentativa falha
    register_attempt(identifier, success=False)
    return "Usuário ou senha incorretos!", 401


@auth_bp.route("/alterar_senha", methods=["POST"])
def alterar_senha():
    if not session.get("logged_in"):
        return redirect(url_for("auth.home"))

    username = session.get("username")
    nova = request.form.get("nova_senha", "").strip()

    # Validação mínima
    if not nova or len(nova) > 1000:
        return "Senha inválida", 400

    try:
        password_hash = generate_password_hash(nova)
        now = datetime.now(timezone.utc).isoformat()
        db.collection("usuarios").document(username).update(
            {"password_hash": password_hash, "password_changed_at": now}
        )
    except Exception as e:
        logger.error("Falha ao alterar senha do usuário %s: %s", username, e)
        return "Erro ao alterar senha", 500

    session.clear()
    return redirect(url_for("auth.home"))


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.home"))
