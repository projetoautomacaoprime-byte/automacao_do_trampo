# security.py
import secrets
from flask import request, g
from datetime import datetime, timedelta, timezone
from firebase_admin import firestore
from google.cloud.firestore_v1 import SERVER_TIMESTAMP

# ----------------- CSP EXISTENTE -----------------
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
        g.csp_nonce = generate_nonce()

    @app.after_request
    def add_headers(response):
        nonce = getattr(g, "csp_nonce", "")
        csp = CSP_TEMPLATE.replace("{nonce}", nonce)
        response.headers["Content-Security-Policy"] = csp
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response


# ----------------- BRUTE FORCE HARDENED -----------------
MAX_ATTEMPTS = 5
BLOCK_TIME_MINUTES = 2
ATTEMPT_WINDOW_MINUTES = 30

db = firestore.client()


def _ensure_dt_with_tz(dt):
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    try:
        return dt.to_datetime().replace(tzinfo=timezone.utc)
    except:
        return None


def get_identifier(email=None, ip=None):
    return email if email else ip


# -------- REGISTRO DE BLOQUEIO (NOVO) --------
def log_block_event(identifier, blocked_until):
    try:
        db.collection("login_blocks").add({
            "identifier": identifier,
            "blocked_until": blocked_until,
            "timestamp": datetime.now(timezone.utc)
        })
    except Exception as e:
        print("Erro ao registrar bloqueio:", e)


def check_block(identifier):
    if not identifier:
        return False, 0

    doc = db.collection("login_attempts").document(identifier).get()
    if not doc.exists:
        return False, 0

    data = doc.to_dict()
    blocked_until = _ensure_dt_with_tz(data.get("blocked_until"))
    now = datetime.now(timezone.utc)

    if blocked_until and now < blocked_until:
        return True, int((blocked_until - now).total_seconds())

    return False, 0


def register_attempt(identifier, success=False):
    if not identifier:
        return

    now = datetime.now(timezone.utc)
    doc_ref = db.collection("login_attempts").document(identifier)

    try:
        snap = doc_ref.get()
        data = snap.to_dict() if snap.exists else None

        # ---- CASO NÃO EXISTE DOC ----
        if data is None:
            if success:
                doc_ref.set({
                    "attempts": 0,
                    "last_attempt": now,
                    "blocked_until": None
                })
            else:
                doc_ref.set({
                    "attempts": 1,
                    "last_attempt": now,
                    "blocked_until": None
                })
            return

        # ---- DOC EXISTE ----
        attempts = int(data.get("attempts", 0))
        last_attempt = _ensure_dt_with_tz(data.get("last_attempt"))
        blocked_until = _ensure_dt_with_tz(data.get("blocked_until"))

        # Se já está bloqueado → mantém bloqueio
        if blocked_until and now < blocked_until:
            doc_ref.update({"last_attempt": now})
            return

        # Login bem-sucedido → reseta
        if success:
            doc_ref.update({
                "attempts": 0,
                "last_attempt": now,
                "blocked_until": None
            })
            return

        # Reset janela
        if last_attempt and (now - last_attempt) > timedelta(minutes=ATTEMPT_WINDOW_MINUTES):
            attempts = 0

        attempts += 1

        # Atingiu limite → BLOQUEIA
        if attempts >= MAX_ATTEMPTS:
            new_block = now + timedelta(minutes=BLOCK_TIME_MINUTES)

            doc_ref.update({
                "attempts": 0,
                "last_attempt": now,
                "blocked_until": new_block
            })

            # Log do bloqueio
            log_block_event(identifier, new_block)
            return

        # Atualização normal
        doc_ref.update({
            "attempts": attempts,
            "last_attempt": now,
            "blocked_until": None
        })

    except Exception as e:
        print("Erro register_attempt:", e)
