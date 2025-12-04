from config import app as flask_app
from flask import g
from flask_wtf.csrf import CSRFProtect
from security import init_security_headers
import secrets

csrf = CSRFProtect()


def create_app():
    app = flask_app  # usa o app do config.py

    # === Segurança global (carregada apenas 1 vez) ===
    csrf.init_app(app)
    init_security_headers(app)

    # === Importar e registrar blueprints ===
    from auth import auth_bp
    from dashboard import dashboard_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)

    return app


app = create_app()

# === (2) Gerar NONCE ANTES de cada requisição ===
@app.before_request
def add_csp_nonce():
    g.csp_nonce = secrets.token_urlsafe(16)


# === (3) Adicionar CSP DINÂMICO APÓS a resposta ===
@app.after_request
def apply_csp(response):
    nonce = g.get("csp_nonce", "")
    csp = (
        "default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}'; "
        "style-src 'self' 'unsafe-inline'; "
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

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)
