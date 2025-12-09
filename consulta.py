# consulta.py
from flask import Blueprint, session, redirect, url_for, request, render_template, jsonify
from config import db
from datetime import datetime
from flask_wtf.csrf import validate_csrf
import bleach

consulta_bp = Blueprint("consulta", __name__)

# -------------------------------
# Consulta página
# -------------------------------
@consulta_bp.route('/consulta', methods=['GET'])
def consulta():
    if not session.get('logged_in'):
        return redirect(url_for('auth.home'))
    return render_template('consulta.html', username=session.get('username'))

# -------------------------------
# Buscar fluxo
# -------------------------------
@consulta_bp.route('/buscar_fluxo', methods=['POST'])
def buscar_fluxo():
    data = request.get_json()
    termo = data.get('q', '').strip().lower()
    limit = data.get('limit', 20)
    divulgador_filtro = data.get('divulgador')

    colecao = db.collection('fluxo_pessoas')
    query = colecao.order_by('nome')

    resultados = []
    docs = query.stream()
    for doc in docs:
        d = doc.to_dict()
        if not d:
            continue
        if divulgador_filtro and d.get('divulgador') != divulgador_filtro:
            continue
        if termo and not any(termo in str(d.get(field, '')).lower()
                             for field in ['nome', 'cpf', 'telefone_movel_1', 'telefone_movel_2', 'telefone_movel_3',
                                           'email_1', 'email_2', 'email_3', 'orgao_nome', 'banco']):
            continue

        d['doc_id'] = doc.id
        d['orgao_nome'] = d.get('orgao_nome', 'Desconhecido')
        d['uf'] = d.get('uf', '-')
        d['idade'] = d.get('idade', '-')

        resultado_limpo = {
            'doc_id': d.get('doc_id', ''),
            'nome': d.get('nome', ''),
            'cpf': d.get('cpf', ''),
            'idade': d.get('idade', ''),
            'orgao_nome': d.get('orgao_nome', ''),
            'uf': d.get('uf', ''),
            'banco': d.get('banco', '-'),
            'telefone_movel_1': d.get('telefone_movel_1', '-'),
            'telefone_movel_2': d.get('telefone_movel_2', '-'),
            'telefone_movel_3': d.get('telefone_movel_3', '-'),
            'divulgador': d.get('divulgador', ''),
            'data_divulgacao': d.get('data_divulgacao', '-')
        }
        resultados.append(resultado_limpo)

    clientes = resultados[:limit]
    mais = len(resultados) > limit
    return jsonify({'clientes': clientes, 'has_more': mais})

# -------------------------------
# Atualizar fluxo
# -------------------------------
@consulta_bp.route("/atualizar_fluxo/<doc_id>", methods=["POST"])
def atualizar_fluxo(doc_id):
    if not session.get('logged_in'):
        return jsonify({"status": "erro", "msg": "Usuário não autenticado"}), 401
    try:
        dados_raw = request.get_json()
        allowed_fields = [
        'nome', 'cpf', 'idade', 'orgao_nome', 'uf', 'banco',
        'telefone_movel_1', 'telefone_movel_2', 'telefone_movel_3']

        dados = {k: bleach.clean(str(v)) if isinstance(v, str) else v
                 for k, v in dados_raw.items() if k in allowed_fields}
        db.collection("fluxo_pessoas").document(doc_id).update(dados)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "erro", "msg": str(e)})

# -------------------------------
# Salvar cliente
# -------------------------------
@consulta_bp.route('/salvar_cliente', methods=['POST'])
def salvar_cliente():
    if not session.get('logged_in'):
        return jsonify({"status": "erro", "tipo": "auth", "mensagem": "Usuário não autenticado"}), 401

    try:
        # valida CSRF
        token = request.headers.get("X-CSRFToken")
        if not token:
            return jsonify({"status": "erro", "mensagem": "Token CSRF ausente"}), 400

        try:
            validate_csrf(token)
        except Exception:
            return jsonify({"status": "erro", "mensagem": "CSRF inválido"}), 400

        cliente_raw = request.get_json(silent=True)
        if not cliente_raw:
            return jsonify({
                'status': 'erro',
                'tipo': 'dados',
                'mensagem': 'Nenhum dado recebido ou JSON inválido.'
            }), 400

        # Sanitiza strings
        cliente = {
            k: bleach.clean(str(v)) if isinstance(v, str) else v
            for k, v in cliente_raw.items()
        }

        # valida doc_id
        doc_id = cliente.get("doc_id")
        if not doc_id:
            return jsonify({"status": "erro", "mensagem": "doc_id obrigatório"}), 400

        # Pega documento existente para preservar campos importantes
        doc_ref = db.collection('fluxo_pessoas').document(doc_id)
        existing = doc_ref.get()
        if existing.exists:
            existing_data = existing.to_dict()
        else:
            existing_data = {}

        # Campos que nunca devem ser sobrescritos se já existem
        preserved_fields = ['divulgador', 'data_divulgacao']

        for field in preserved_fields:
            if field not in cliente or not cliente[field]:
                cliente[field] = existing_data.get(field)

        # Se for um cliente novo, adiciona divulgador e data
        if not cliente.get('divulgador'):
            cliente['divulgador'] = session.get('username', 'Desconhecido')
        if not cliente.get('data_divulgacao'):
            cliente['data_divulgacao'] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        # Atualiza apenas os campos recebidos
        update_fields = {k: v for k, v in cliente.items() if k != 'doc_id'}
        doc_ref.update(update_fields)

        return jsonify({'status': 'ok'}), 200

    except Exception as e:
        return jsonify({
            'status': 'erro',
            'tipo': 'servidor',
            'mensagem': str(e)
        }), 500
