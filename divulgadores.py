from config import db
from flask import jsonify

def get_divulgadores_list():
    divulgadores_ref = db.collection("divulgadores")
    docs = divulgadores_ref.stream()
    divulgadores = [doc.to_dict().get("nome") for doc in docs if doc.to_dict().get("nome")]
    return divulgadores

def get_divulgadores_flask():
    try:
        docs = db.collection('usuarios').stream()
        nomes = sorted(set([doc.to_dict().get('nome') or doc.to_dict().get('username') for doc in docs if doc.to_dict().get('nome') or doc.to_dict().get('username')]))
        return jsonify(nomes)
    except Exception as e:
        print("Erro ao buscar divulgadores:", e)
        return jsonify([]), 500
