from config import db
from flask import jsonify
import logging

logger = logging.getLogger(__name__)

def get_divulgadores_list():
    """
    Busca lista simples de nomes na coleção 'divulgadores'.
    Retorna lista de strings.
    """
    try:
        divulgadores_ref = db.collection("divulgadores")
        docs = divulgadores_ref.stream()

        divulgadores = []
        for doc in docs:
            data = doc.to_dict() or {}
            nome = data.get("nome")
            if nome:
                divulgadores.append(nome)

        return divulgadores

    except Exception as e:
        logger.error(f"Erro ao buscar divulgadores (divulgadores): {e}")
        return []


def get_divulgadores_flask():
    """
    Endpoint Flask — retorna JSON com nomes da coleção 'usuarios'.
    """
    try:
        docs = db.collection('usuarios').stream()

        nomes = []
        for doc in docs:
            data = doc.to_dict() or {}
            nome = data.get('nome') or data.get('username')
            if nome:
                nomes.append(nome)

        nomes = sorted(set(nomes))  # remove duplicados

        return jsonify(nomes), 200

    except Exception as e:
        logger.error(f"Erro ao buscar divulgadores (usuarios): {e}")
        return jsonify([]), 500
