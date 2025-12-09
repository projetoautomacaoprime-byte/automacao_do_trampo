import pandas as pd
from flask import Blueprint, session, redirect, url_for, request, render_template, jsonify
from config import db, app
from sheets import read_sheet_to_dataframe, parse_brl, calcular_valor_financiado, format_brl
from filters import aplicar_filtros, carregar_orgaos
from divulgadores import get_divulgadores_list
from flask_wtf.csrf import CSRFProtect
import bleach

dashboard_bp = Blueprint("dashboard", __name__)

# -------------------------------
# Ativa CSRF globalmente
# -------------------------------
csrf = CSRFProtect()
csrf.init_app(app)

# -------------------------------
# Função para pegar config do usuário
# -------------------------------
def get_user_sheet_config(username):
    if not username:
        return None
    ref = db.collection("planilhas_usuarios").document(username).get()
    if not ref.exists:
        return None
    cfg = ref.to_dict()
    if "sheet_url" not in cfg or "sheet_name" not in cfg:
        return None
    return {"sheet_url": cfg["sheet_url"], "sheet_name": cfg["sheet_name"]}

# -------------------------------
# Função para adicionar nome e taxa do órgão
# -------------------------------
def adiciona_nome_taxa_orgao(table_data):
    orgaos_docs = db.collection("Orgãos_taxa_cod").stream()
    orgaos_lista = [doc.to_dict() for doc in orgaos_docs]

    for cliente in table_data:
        codigo_orgao = str(cliente.get("orgao", "")).strip()
        cliente["orgao_nome"] = "Não informado"
        cliente["orgao_taxa_formatada"] = "—"

        for orgao in orgaos_lista:
            codigos = orgao.get("codigos", [])
            if codigo_orgao in codigos:
                cliente["orgao_nome"] = orgao.get("nome", "Não informado").upper()
                taxa = orgao.get("taxa", None)
                if taxa:
                    try:
                        taxa_clean = str(taxa).replace(",", ".").replace("%", "").strip()
                        cliente["orgao_taxa_formatada"] = f"{float(taxa_clean):.2f}%"
                    except:
                        cliente["orgao_taxa_formatada"] = "—"
                break
    return table_data

# -------------------------------
# Dashboard principal
# -------------------------------
@dashboard_bp.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('auth.home'))

    username = session.get("username")
    config = get_user_sheet_config(username)
    SHEET_URL_USER = config.get('sheet_url') if config else None
    SHEET_NAME_USER = config.get('sheet_name') if config else None

    start = request.args.get('start', 0)
    try:
        start = int(start)
    except:
        start = 0
    limit = 10

    df = read_sheet_to_dataframe(SHEET_URL_USER, SHEET_NAME_USER)
    if not df.empty:
        df.columns = df.columns.str.strip().str.replace(" ", "_").str.lower()
        for col in ["parcela", "prazo", "idade"]:
            if col in df.columns:
                df[col] = df[col].apply(parse_brl)
        df["saldo_devedor_float"] = df.apply(calcular_valor_financiado, axis=1)
        df["parcela_exibir"] = (df["parcela"] / 100).apply(format_brl)
    else:
        df = pd.DataFrame()

    # filtros
    saldo_filtro = request.args.get('saldo', None)
    uf_filtro = request.args.get('uf', None)
    orgao_filtro = request.args.get('orgao', None)

    orgaos_fire = carregar_orgaos()

    filtered_df = aplicar_filtros(
        df,
        uf_filtro=uf_filtro,
        orgao_filtro=orgao_filtro,
        saldo_filtro=saldo_filtro,
        orgaos_fire=orgaos_fire
    )

    if not filtered_df.empty:
        filtered_df['doc_id'] = filtered_df.apply(
            lambda row: f"{row.get('cpf','')}_{row.get('banco','')}_{int(row.get('prazo',0))}_{int(row.get('parcela',0))}_{row.get('uf','')}".replace(" ", "").upper(),
            axis=1
        )
        filtered_df = filtered_df.drop_duplicates(subset=['doc_id'], keep='first')
        paginated_df = filtered_df.iloc[start:start + limit].copy()
        paginated_df["parcela"] = paginated_df["parcela_exibir"]
        paginated_df["saldo_devedor"] = paginated_df["saldo_devedor_float"].apply(format_brl)

        table_data = paginated_df.to_dict(orient="records")
        table_data = adiciona_nome_taxa_orgao(table_data)
    else:
        table_data = []

    return render_template(
        'dashboard.html',
        table_data=table_data,
        start=start,
        username=session.get('username'),
        exibidos=len(table_data),
    )

# -------------------------------
# Rotas de órgãos e divulgadores
# -------------------------------
@dashboard_bp.route("/get_orgaos")
def get_orgaos_route():
    orgaos = carregar_orgaos()
    lista = [
        {"nome": o["nome"], "codigos": o["codigos"], "ativo": o["ativo"]}
        for o in orgaos
    ]
    return jsonify(lista), 200

@dashboard_bp.route("/get_divulgadores")
def get_divulgadores_route():
    divulgadores = get_divulgadores_list()
    return jsonify(divulgadores), 200

# -------------------------------
# Atualiza dataframe via AJAX
# -------------------------------
@dashboard_bp.route('/atualiza_dataframe', methods=['POST'])
@csrf.exempt
def atualiza_dataframe():
    if not session.get('logged_in'):
        return jsonify({"success": False, "error": "Usuário não autenticado"}), 401
    try:
        data = request.get_json()
        start = int(data.get('start', 0))
        limit = int(data.get('limit', 10))
        username = session.get("username")
        config = get_user_sheet_config(username)
        if not config:
            return jsonify({"success": False, "error": "Planilha do usuário não configurada"}), 400

        df = read_sheet_to_dataframe(config.get("sheet_url"), config.get("sheet_name"))
        if not df.empty:
            df.columns = df.columns.str.strip().str.replace(" ", "_").str.lower()
            for col in ["parcela", "prazo", "idade"]:
                if col in df.columns:
                    df[col] = df[col].apply(parse_brl)
            df["saldo_devedor_float"] = df.apply(calcular_valor_financiado, axis=1)
            df["parcela_exibir"] = (df["parcela"] / 100).apply(format_brl)

        orgaos_fire = carregar_orgaos()

        uf_filtro = bleach.clean(data.get('uf') or "")
        orgao_filtro = bleach.clean(data.get('orgao') or "")
        saldo_filtro = bleach.clean(str(data.get('saldo') or ""))

        filtered_df = aplicar_filtros(
            df,
            uf_filtro=uf_filtro,
            orgao_filtro=orgao_filtro,
            saldo_filtro=saldo_filtro,
            orgaos_fire=orgaos_fire
        )

        if filtered_df.empty:
            return jsonify({"clientes": [], "total_count": 0, "next_start": 0})

        filtered_df['doc_id'] = filtered_df.apply(
            lambda row: f"{row.get('cpf','')}_{row.get('banco','')}_{int(row.get('prazo',0))}_{int(row.get('parcela',0))}_{row.get('uf','')}".replace(" ", "").upper(),
            axis=1
        )

        filtered_df = filtered_df.drop_duplicates(subset=['doc_id'], keep='first')
        paginated_df = filtered_df.iloc[start:start + limit].copy()

        paginated_df["parcela"] = paginated_df["parcela_exibir"]
        paginated_df["saldo_devedor"] = paginated_df["saldo_devedor_float"].apply(format_brl)

        clientes_json = paginated_df.to_dict(orient="records")
        clientes_json = adiciona_nome_taxa_orgao(clientes_json)

        next_start = start + limit
        if next_start >= len(filtered_df):
            next_start = 0

        return jsonify({
            "clientes": clientes_json,
            "total_count": len(filtered_df),
            "next_start": next_start
        })

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
