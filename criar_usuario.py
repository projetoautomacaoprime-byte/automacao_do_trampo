import firebase_admin
from firebase_admin import credentials, firestore
from werkzeug.security import generate_password_hash

# Inicializar Firebase (mesmo do app)
cred = credentials.Certificate("credenciais.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# Criar usuário
username = "manelzao"
senha = "123456789"
password_hash = generate_password_hash(senha)

db.collection("usuarios").add({
    "username": username,
    "password_hash": password_hash
})

print("Usuário criado com sucesso!")
