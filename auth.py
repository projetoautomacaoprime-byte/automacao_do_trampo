from flask import Blueprint, session, redirect, url_for, request, render_template
from werkzeug.security import check_password_hash, generate_password_hash
from config import db, app
from datetime import datetime, timezone

auth_bp = Blueprint("auth", __name__)

# ------------------------------
# Middleware de sessão
# ------------------------------
@app.before_request
def verificar_sessao():
    # ------------------------------
    # 1️⃣ Liberar arquivos estáticos e favicon
    # ------------------------------
    if request.path.startswith("/static/") or request.path == "/favicon.ico":
        return None

    # Rotas públicas do auth
    if request.endpoint in (
    "auth.home",
    "auth.login",
    "auth.alterar_senha",
    "auth.logout",
):
        return None


    if not session.get("logged_in"):
        return redirect(url_for("auth.home"))

    last_seen = session.get("last_seen")
    now = datetime.now(timezone.utc)

    if last_seen:
        try:
            ultimo_acesso = datetime.strptime(last_seen, "%Y-%m-%d %H:%M:%S%z")
        except:
            try:
                ultimo_acesso = datetime.strptime(last_seen, "%Y-%m-%d %H:%M:%S")
                ultimo_acesso = ultimo_acesso.replace(tzinfo=timezone.utc)
            except:
                session.clear()
                return redirect(url_for("auth.home"))

        if (now - ultimo_acesso) > app.permanent_session_lifetime:
            session.clear()
            return redirect(url_for("auth.home"))

    username = session.get("username")
    if username:
        doc = db.collection("usuarios").document(username).get()
        if doc.exists:
            u = doc.to_dict()
            pwd_changed = u.get("password_changed_at")
            if pwd_changed:
                try:
                    pwd_changed_dt = datetime.fromisoformat(pwd_changed)
                    session_created = datetime.strptime(
                        session.get("last_seen"), "%Y-%m-%d %H:%M:%S%z"
                    )
                    if pwd_changed_dt > session_created:
                        session.clear()
                        return redirect(url_for("auth.home"))
                except:
                    pass

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
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    query = (
        db.collection("usuarios")
        .where("username", "==", username)
        .limit(1)
        .stream()
    )
    user_doc = next(query, None)

    if user_doc:
        user_data = user_doc.to_dict()
        if check_password_hash(user_data.get("password_hash", ""), password):
            session.clear()
            session.permanent = True
            session["logged_in"] = True
            session["username"] = username
            session["role"] = user_data.get("role", "user")
            session["last_seen"] = datetime.now(timezone.utc).strftime(
                "%Y-%m-%d %H:%M:%S%z"
            )
            return redirect(url_for("dashboard.dashboard"))

    return "Usuário ou senha incorretos!", 401


@auth_bp.route("/alterar_senha", methods=["POST"])
def alterar_senha():
    if not session.get("logged_in"):
        return redirect(url_for("auth.home"))

    username = session.get("username")
    nova = request.form.get("nova_senha", "").strip()
    if not nova:
        return "Senha inválida", 400

    password_hash = generate_password_hash(nova)
    now = datetime.now(timezone.utc).isoformat()

    db.collection("usuarios").document(username).update(
        {
            "password_hash": password_hash,
            "password_changed_at": now,
        }
    )

    session.clear()
    return redirect(url_for("auth.home"))


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.home"))
