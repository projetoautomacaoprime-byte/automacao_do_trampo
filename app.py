import os
import secrets
import logging
from flask import g
from flask_wtf.csrf import CSRFProtect, CSRFError
from config import app as flask_app
from security import init_security_headers
from consulta import consulta_bp  # corrigido

# === Configurar logging ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.info("Inicializando aplicação Flask...")

# === CSRF global ===
csrf = CSRFProtect()

def create_app():
    app = flask_app  # usa o app criado no config.py

    # === Segurança global ===
    csrf.init_app(app)
    init_security_headers(app)

    # === Registrar blueprints ===
    from auth import auth_bp
    from dashboard import dashboard_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(consulta_bp)  # registrado corretamente
    return app


app = create_app()

# === Gerar NONCE antes de cada requisição para CSP ===
@app.before_request
def add_csp_nonce():
    g.csp_nonce = secrets.token_urlsafe(16)

# === Handler global de CSRFError ===
@app.errorhandler(CSRFError)
def handle_csrf(e):
    logger.warning("CSRF token inválido: %s", e)
    return "Requisição inválida (CSRF token inválido)", 400

# === Inserir CSP dinâmico na resposta ===
@app.after_request
def apply_csp(response):
    nonce = g.get("csp_nonce", "")
    csp = (
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}'; "
        "style-src 'self'; "
        "img-src 'self' data: https:; "
        "font-src 'self' data: https:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none';"
    )
    response.headers['Content-Security-Policy'] = csp
    return response

# === Executar aplicação ===
if __name__ == '__main__':
   debug_mode = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    #logger.info("Aplicação rodando em modo debug: %s", debug_mode)
   # app.run(host="0.0.0.0", port=5000, debug=debug_mode)
