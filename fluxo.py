from flask import Blueprint, request, jsonify, render_template, session
from divulgadores import get_divulgadores_list
from config import db
from datetime import datetime

bp = Blueprint('fluxo', __name__)

@bp.route('/buscar_fluxo', methods=['POST'])
def buscar_fluxo():
    data = request.get_json()
    termo = data.get('q', '').strip().lower()
    limit = data.get('limit', 20)
    divulgador_filtro = data.get('divulgador')

    colecao = db.collection('fluxo_pessoas')
    query = colecao.order_by('nome')
    resultados = []

    for doc in query.stream():
        d = doc.to_dict()
        if not d:
            continue
        if divulgador_filtro and d.get('divulgador') != divulgador_filtro:
            continue
        if termo and not any(termo in str(d.get(field, '')).lower()
                             for field in ['nome','cpf','telefone_movel_1','telefone_movel_2','telefone_movel_3','email_1','email_2','email_3','orgao_nome','banco']):
            continue
        d['doc_id'] = doc.id
        d['orgao_nome'] = d.get('orgao_nome','Desconhecido')
        d['uf'] = d.get('uf','-')
        d['telefone'] = d.get('telefone_movel_1') or d.get('telefone_movel_2') or d.get('telefone_movel_3') or '-'
        d['idade'] = d.get('idade','-')
        d['divulgador'] = d.get('divulgador','-')
        resultados.append({
            'doc_id': d.get('doc_id',''),
            'nome': d.get('nome',''),
            'cpf': d.get('cpf',''),
            'idade': d.get('idade',''),
            'orgao_nome': d.get('orgao_nome',''),
            'uf': d.get('uf',''),
            'banco': d.get('banco','-'),
            'telefone_movel_1': d.get('telefone_movel_1','-'),
            'telefone_movel_2': d.get('telefone_movel_2','-'),
            'telefone_movel_3': d.get('telefone_movel_3','-'),
            'divulgador': d.get('divulgador',''),
            'data_divulgacao': d.get('data_divulgacao','-')
        })

    clientes = resultados[:limit]
    mais = len(resultados) > limit
    return jsonify({'clientes': clientes, 'has_more': mais})


@bp.route("/atualizar_fluxo/<doc_id>", methods=["POST"])
def atualizar_fluxo(doc_id):
    try:
        dados = request.get_json()
        db.collection("fluxo_pessoas").document(doc_id).update(dados)
        return jsonify({"status":"ok"})
    except Exception as e:
        return jsonify({"status":"erro","msg":str(e)})


@bp.route('/salvar_cliente', methods=['POST'])
def salvar_cliente():
    try:
        cliente = request.json
        if not cliente or 'doc_id' not in cliente:
            return jsonify({'status':'erro','tipo':'dados','mensagem':'Dados do cliente inválidos.'}), 400

        cliente['divulgador'] = session.get('username','Desconhecido')
        if not cliente.get('data_divulgacao'):
            cliente['data_divulgacao'] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        doc_ref = db.collection('fluxo_pessoas').document(cliente['doc_id'])
        novo_telefone = cliente.get('novo_telefone','').strip()
        doc_ref.set(cliente, merge=True)
        if novo_telefone:
            doc_ref.update({'novo_telefone': novo_telefone})

        return jsonify({'status':'ok'})
    except Exception as e:
        return jsonify({'status':'erro','tipo':'servidor','mensagem':str(e)}),500


@bp.route('/cliente/<id>')
def cliente(id):
    cliente_data = db.collection("clientes").document(id).get().to_dict()
    divulgadores = get_divulgadores_list()
    return render_template('sheets_view.html', cliente=cliente_data, divulgadores=divulgadores)


@bp.route('/get_divulgadores', methods=['GET'])
def get_divulgadores():
    try:
        docs = db.collection('usuarios').stream()
        nomes = []
        for doc in docs:
            data = doc.to_dict()
            nome = data.get('nome') or data.get('username')
            if nome:
                nomes.append(nome)
        nomes = sorted(set(nomes))
        return jsonify(nomes)
    except:
        return jsonify([]),500
