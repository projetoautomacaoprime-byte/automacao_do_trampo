from config import db

def get_divulgadores_list():
    divulgadores_ref = db.collection("divulgadores")
    docs = divulgadores_ref.stream()
    divulgadores = []
    for doc in docs:
        data = doc.to_dict()
        nome = data.get("nome")
        if nome:
            divulgadores.append(nome)
    return divulgadores
