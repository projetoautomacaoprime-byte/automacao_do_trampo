# security.py
import secrets
from flask import request, g

CSP_TEMPLATE = (
    "default-src 'self'; "
    "script-src 'self' 'nonce-{nonce}'; "
    "style-src 'self' 'nonce-{nonce}'; "
    "img-src 'self' data: https:; "
    "font-src 'self' data: https:; "
    "connect-src 'self' https://sheets.googleapis.com https://docs.google.com; "
    "frame-ancestors 'self'; "
    "base-uri 'self'; "
    "object-src 'none'; "
    "media-src 'self'; "
    "manifest-src 'self'; "
    "worker-src 'self';"
)

def generate_nonce():
    return secrets.token_urlsafe(16)

def init_security_headers(app):
    @app.before_request
    def inject_nonce():
        # nonce fica disponível nos templates
        g.csp_nonce = generate_nonce()

    @app.after_request
    def add_headers(response):
        nonce = getattr(g, "csp_nonce", "")
        csp = CSP_TEMPLATE.replace("{nonce}", nonce)

        # CSP final
        response.headers["Content-Security-Policy"] = csp

        # Impede mime sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Impede clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # Política de referrer segura
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # XSS Filter legado
        response.headers["X-XSS-Protection"] = "1; mode=block"

        # HSTS se HTTPS
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        return response
