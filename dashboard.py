from flask import Blueprint, render_template, request, session, jsonify
from utils.sheets import read_sheet_to_dataframe, parse_brl, calcular_valor_financiado, format_brl
from utils.filtros import aplicar_filtros
from config import db

bp = Blueprint('dashboard', __name__)

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

@bp.route('/dashboard')
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

    saldo_filtro = request.args.get('saldo', None)
    uf_filtro = request.args.get('uf', None)
    orgao_filtro = request.args.get('orgao', None)

    filtered_df = aplicar_filtros(df, uf_filtro=uf_filtro, orgao_filtro=orgao_filtro, saldo_filtro=saldo_filtro)

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
    else:
        table_data = []

    return render_template('sheets_view.html', table_data=table_data, start=start, username=username, exibidos=len(table_data))


@bp.route('/atualiza_dataframe', methods=['POST'])
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

        filtered_df = aplicar_filtros(df, uf_filtro=data.get('uf'), orgao_filtro=data.get('orgao'), saldo_filtro=data.get('saldo'))

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

        for cliente in clientes_json:
            doc_id = cliente.get('doc_id')
            if doc_id:
                doc = db.collection('fluxo_pessoas').document(doc_id).get()
                if doc.exists:
                    data_fire = doc.to_dict()
                    if 'divulgador' in data_fire:
                        cliente['divulgador'] = data_fire['divulgador']
                    if 'novo_telefone' in data_fire:
                        cliente['novo_telefone'] = data_fire['novo_telefone']

        next_start = start + limit
        if next_start >= len(filtered_df):
            next_start = 0

        return jsonify({"clientes": clientes_json, "total_count": len(filtered_df), "next_start": next_start})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@bp.route("/test_sheet")
def test_sheet():
    user = session.get("username")
    return get_user_sheet_config(user) or {"erro": "nenhuma config encontrada"}
