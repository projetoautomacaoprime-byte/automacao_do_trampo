import os
from datetime import timedelta, datetime

import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from werkzeug.security import check_password_hash
import gspread
import pandas as pd
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

# --- Carregar variáveis do .env ---
load_dotenv()

# --- Configuração do Flask ---
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

# --- Inicializar Firebase ---
cred = credentials.Certificate("credenciais.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# --- Tempo máximo da sessão ---
SESSION_TIMEOUT_MINUTES = 30

# ============================================================
# 🧩 FUNÇÕES AUXILIARES
# ============================================================

def read_sheet_to_dataframe(sheet_url: str, sheet_name: str, creds_path: str = "credenciais.json") -> pd.DataFrame:
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_url(sheet_url)
    worksheet = sheet.worksheet(sheet_name)
    data = worksheet.get_all_records()
    return pd.DataFrame(data)

def parse_brl(valor):
    try:
        if isinstance(valor, str):
            valor = valor.replace(".", "").replace(",", ".")
        return float(valor)
    except Exception as e:
        print("Erro ao converter número:", valor, e)
        return 0.0

def calcular_valor_financiado(row):
    try:
        parcela = parse_brl(row.get("parcela", 0))
        prazo = int(parse_brl(row.get("prazo", 0)))
        taxa = 1.5 / 100
        if parcela <= 0 or prazo <= 0 or taxa <= 0:
            return 0.0
        valor_financiado = parcela * (1 - (1 + taxa) ** (-prazo)) / taxa
        valor_financiado /= 100
        return round(valor_financiado, 2)
    except Exception as e:
        print("Erro ao calcular saldo:", e)
        return 0.0

def format_brl(valor):
    try:
        return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return valor

# ============================================================
# 🔐 SESSÃO
# ============================================================

@app.before_request
def verificar_sessao():
    if "logged_in" in session:
        ultimo_acesso = session.get("last_seen")
        agora = datetime.utcnow()
        if ultimo_acesso:
            ultimo_acesso = datetime.strptime(ultimo_acesso, "%Y-%m-%d %H:%M:%S")
            if (agora - ultimo_acesso) > timedelta(minutes=SESSION_TIMEOUT_MINUTES):
                session.clear()
                return redirect(url_for("home"))
        session["last_seen"] = agora.strftime("%Y-%m-%d %H:%M:%S")

# ============================================================
# 🔑 AUTENTICAÇÃO
# ============================================================

@app.route('/')
def home():
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    username = request.form['username']
    password = request.form['password']

    usuarios_ref = db.collection('usuarios')
    query = usuarios_ref.where('username', '==', username).limit(1).stream()
    user_doc = next(query, None)

    if user_doc:
        user_data = user_doc.to_dict()
        password_hash = user_data.get('password_hash')
        if check_password_hash(password_hash, password):
            session['logged_in'] = True
            session['username'] = username
            session['last_seen'] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            return redirect(url_for('dashboard'))

    return 'Usuário ou senha incorretos!'

# ============================================================
# 🧩 FILTROS CENTRALIZADOS
# ============================================================

def aplicar_filtros(df: pd.DataFrame, uf_filtro=None, orgao_filtro=None, saldo_filtro=None) -> pd.DataFrame:
    saldo_min = float(saldo_filtro) if saldo_filtro else 25000
    filtered_df = df[df["saldo_devedor_float"] >= saldo_min].copy()
    filtered_df['banco_clean'] = filtered_df['banco'].astype(str).str.strip().str.lower() if 'banco' in df.columns else ""
    filtered_df['idade'] = filtered_df.get('idade', 0)

    # =======================
    # FILTRO DE BANCOS
    # =======================
    blocked_banks = [""]
    blocked_banks = [b.lower() for b in blocked_banks]
    filtered_df = filtered_df[~filtered_df['banco_clean'].isin(blocked_banks)]
    filtered_df = filtered_df[filtered_df['idade'] <= 70]

def aplicar_filtros(df: pd.DataFrame, uf_filtro=None, orgao_filtro=None, saldo_filtro=None) -> pd.DataFrame:
    saldo_min = float(saldo_filtro) if saldo_filtro else 25000
    filtered_df = df[df["saldo_devedor_float"] >= saldo_min].copy()
    filtered_df['banco_clean'] = filtered_df['banco'].astype(str).str.strip().str.lower() if 'banco' in df.columns else ""
    filtered_df['idade'] = filtered_df.get('idade', 0)

    # =======================
    # FILTRO DE BANCOS
    # =======================
    blocked_banks = [""]
    blocked_banks = [b.lower() for b in blocked_banks]
    filtered_df = filtered_df[~filtered_df['banco_clean'].isin(blocked_banks)]
    filtered_df = filtered_df[filtered_df['idade'] <= 70]

       # =======================
    # NOVO FILTRO DE ÓRGÃOS (MOSTRAR APENAS OS PERMITIDOS)
    # =======================
    allowed_orgaos = ["40803"]  # Códigos que devem aparecer

    # Mapeamento código → nome e taxa
    orgaos_info = {
        "40803": {"nome": "Vinigay", "taxa": 1.50},
        # exemplo:
        # "50100": {"nome": "INSS", "taxa": 1.35},
        # "30200": {"nome": "PREFEITURA", "taxa": 1.25},
    }

    if "orgao" in filtered_df.columns:
        filtered_df["orgao_clean"] = filtered_df["orgao"].astype(str).str.strip().str.upper()

        # Filtra apenas os órgãos permitidos
        filtered_df = filtered_df[filtered_df["orgao_clean"].isin([o.upper() for o in allowed_orgaos])]

        # Mapeia nome e taxa
        filtered_df["orgao_nome"] = filtered_df["orgao_clean"].map(
            {k.upper(): v["nome"] for k, v in orgaos_info.items()}
        ).fillna("Desconhecido")

        filtered_df["taxa_orgao"] = filtered_df["orgao_clean"].map(
            {k.upper(): v["taxa"] for k, v in orgaos_info.items()}
        ).fillna(0)
    else:
        filtered_df["orgao_nome"] = "Desconhecido"
        filtered_df["taxa_orgao"] = 0
        filtered_df.drop(columns=['banco_clean', 'orgao_clean'], errors='ignore', inplace=True)

    filtered_df.drop(columns=['banco_clean', 'orgao_clean'], errors='ignore', inplace=True)

    # =======================
    # FILTROS EXISTENTES
    # =======================
    if uf_filtro:
        filtered_df = filtered_df[filtered_df['uf'].str.upper() == uf_filtro.upper()]
    if orgao_filtro:
        filtered_df = filtered_df[filtered_df['orgao'].astype(str).str.upper() == orgao_filtro.upper()]

    return filtered_df



def get_divulgadores():
    """
    Retorna uma lista com os nomes das pessoas da empresa
    cadastradas na coleção 'divulgadores' do Firestore.
    """
    divulgadores_ref = db.collection("divulgadores")
    docs = divulgadores_ref.stream()

    divulgadores = []
    for doc in docs:
        data = doc.to_dict()
        nome = data.get("nome")
        if nome:
            divulgadores.append(nome)

    return divulgadores


# ============================================================
# 📊 DASHBOARD PRINCIPAL
# ============================================================

SHEET_URL = "https://docs.google.com/spreadsheets/d/1hKhKv4h4QGx5PyfNqp5kXQz0CPp_7wE3X1F-QvWxiCI/edit?gid=0#gid=0"
SHEET_NAME = "Página1"

@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('home'))

    # 🔥 Ajuste NECESSÁRIO da Task 2 — pegar planilha por usuário
    username = session.get("username")
    config = get_user_sheet_config(username)

    if config:
        SHEET_URL_USER = config.get('sheet_url')
        SHEET_NAME_USER = config.get('sheet_name')
    else:
        SHEET_URL_USER = None
        SHEET_NAME_USER = None

    start = request.args.get('start', 0)
    try:
        start = int(start)
    except:
        start = 0
    limit = 10

    # 🔥 Aqui troca SOMENTE o necessário
    df = read_sheet_to_dataframe(SHEET_URL_USER, SHEET_NAME_USER)

    df.columns = df.columns.str.strip().str.replace(" ", "_").str.lower()
    for col in ["parcela", "prazo", "idade"]:
        if col in df.columns:
            df[col] = df[col].apply(parse_brl)

    df["saldo_devedor_float"] = df.apply(calcular_valor_financiado, axis=1)
    df["parcela_exibir"] = (df["parcela"] / 100).apply(format_brl)

    saldo_filtro = request.args.get('saldo', None)
    uf_filtro = request.args.get('uf', None)
    orgao_filtro = request.args.get('orgao', None)

    filtered_df = aplicar_filtros(
        df,
        uf_filtro=uf_filtro,
        orgao_filtro=orgao_filtro,
        saldo_filtro=saldo_filtro
    )

    filtered_df['doc_id'] = filtered_df.apply(
        lambda row: f"{row['cpf']}_{row['banco']}_{int(row['prazo'])}_{int(row['parcela'])}_{row['uf']}".replace(" ", "").upper(),
        axis=1
    )
    filtered_df = filtered_df.drop_duplicates(subset=['doc_id'], keep='first')

    paginated_df = filtered_df.iloc[start:start + limit].copy()
    paginated_df["parcela"] = paginated_df["parcela_exibir"]
    paginated_df["saldo_devedor"] = paginated_df["saldo_devedor_float"].apply(format_brl)

    table_data = paginated_df.to_dict(orient="records")

    return render_template(
    'sheets_view.html',
    table_data=table_data,
    start=start,
    username=session.get('username'),
    exibidos=len(table_data)
)




# ============================================================
# 🔁 AJAX ATUALIZAÇÃO (carregar mais 10)
# ============================================================

@app.route('/atualiza_dataframe', methods=['POST'])
def atualiza_dataframe():
    if not session.get('logged_in'):
        return jsonify({"success": False, "error": "Usuário não autenticado"}), 401

    try:
        data = request.get_json()
        start = int(data.get('start', 0))
        limit = int(data.get('limit', 10))

        # 🔥 Buscar planilha por usuário
        username = session.get("username")
        config = get_user_sheet_config(username)

        if config:
            SHEET_URL_USER = config.get("sheet_url")
            SHEET_NAME_USER = config.get("sheet_name")
        else:
            return jsonify({"success": False, "error": "Planilha do usuário não configurada"}), 400

        # 🔥 Ler planilha do usuário
        df = read_sheet_to_dataframe(SHEET_URL_USER, SHEET_NAME_USER)

        df.columns = df.columns.str.strip().str.replace(" ", "_").str.lower()

        # Aplicar conversões
        for col in ["parcela", "prazo", "idade"]:
            if col in df.columns:
                df[col] = df[col].apply(parse_brl)

        df["saldo_devedor_float"] = df.apply(calcular_valor_financiado, axis=1)
        df["parcela_exibir"] = (df["parcela"] / 100).apply(format_brl)

        # --- FILTROS (mantidos do original)
        saldo_filtro = data.get('saldo', None)
        uf_filtro = data.get('uf', None)
        orgao_filtro = data.get('orgao', None)

        filtered_df = aplicar_filtros(
            df,
            uf_filtro=uf_filtro,
            orgao_filtro=orgao_filtro,
            saldo_filtro=saldo_filtro
        )

        # --- CRIAR DOC_ID COMO ANTES
        filtered_df['doc_id'] = filtered_df.apply(
            lambda row: f"{row['cpf']}_{row['banco']}_{int(row['prazo'])}_{int(row['parcela'])}_{row['uf']}".replace(" ", "").upper(),
            axis=1
        )

        filtered_df = filtered_df.drop_duplicates(subset=['doc_id'], keep='first')

        # --- PAGINAÇÃO
        paginated_df = filtered_df.iloc[start:start + limit].copy()
        paginated_df["parcela"] = paginated_df["parcela_exibir"]
        paginated_df["saldo_devedor"] = paginated_df["saldo_devedor_float"].apply(format_brl)

        clientes_json = paginated_df.to_dict(orient="records")

        # --- Buscar divulgador salvo no Firestore (mantido igual)
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

        # --- Calcular next_start
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

# Rota da tela de consulta
@app.route('/consulta', methods=['GET'])
def consulta():
    # exige login (mesma lógica que usa no /dashboard)
    if not session.get('logged_in'):
        return redirect(url_for('home'))

    # podemos passar dados iniciais (ex: username) para o template
    return render_template('consulta.html', username=session.get('username'))


# Rota para buscar registros salvos no Firestore (fluxo_pessoas)
@app.route('/buscar_fluxo', methods=['POST'])
def buscar_fluxo():
    data = request.get_json()
    termo = data.get('q', '').strip().lower()
    limit = data.get('limit', 20)
    divulgador_filtro = data.get('divulgador')  # 🆕 veio do front-end (filtro opcional)

    colecao = db.collection('fluxo_pessoas')
    query = colecao.order_by('nome')

    resultados = []

    docs = query.stream()
    for doc in docs:
        d = doc.to_dict()
        if not d:
            continue

        # 🧩 se tiver filtro de divulgador, pula quem não for o mesmo
        if divulgador_filtro and d.get('divulgador') != divulgador_filtro:
            continue

        # 🔎 filtro de texto geral (nome, cpf, telefone, etc.)
        if termo and not any(
            termo in str(d.get(field, '')).lower()
            for field in ['nome', 'cpf', 'telefone_movel_1', 'telefone_movel_2', 'telefone_movel_3',
                          'email_1', 'email_2', 'email_3', 'orgao_nome', 'banco']
        ):
            continue

        d['doc_id'] = doc.id

        # 🔧 garante campos padrão
        d['orgao_nome'] = d.get('orgao_nome', 'Desconhecido')
        d['uf'] = d.get('uf', '-')
        d['telefone'] = d.get('telefone_movel_1') or d.get('telefone_movel_2') or d.get('telefone_movel_3') or '-'
        d['idade'] = d.get('idade', '-')
        d['divulgador'] = d.get('divulgador', '-')

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
    'data_divulgacao': d.get('data_divulgacao', '-')  # <-- adiciona aqui
}


        resultados.append(resultado_limpo)

    clientes = resultados[:limit]
    mais = len(resultados) > limit

    return jsonify({'clientes': clientes, 'has_more': mais})



@app.route('/cliente/<id>')
def cliente(id):
    cliente_data = db.collection("clientes").document(id).get().to_dict()
    divulgadores = get_divulgadores()
    return render_template('sheets_view.html', cliente=cliente_data, divulgadores=divulgadores)


@app.route('/get_divulgadores', methods=['GET'])
def get_divulgadores():
    try:
        docs = db.collection('usuarios').stream()
        nomes = []
        for doc in docs:
            data = doc.to_dict()
            nome = data.get('nome') or data.get('username')  # usa 'nome' ou 'username'
            if nome:
                nomes.append(nome)

        nomes = sorted(set(nomes))  # remove duplicados e ordena
        return jsonify(nomes)

    except Exception as e:
        print("Erro ao buscar divulgadores:", e)
        return jsonify([]), 500


@app.route("/atualizar_fluxo/<doc_id>", methods=["POST"])
def atualizar_fluxo(doc_id):
    try:
        dados = request.get_json()
        db = firestore.client()

        db.collection("fluxo_pessoas").document(doc_id).update(dados)

        return jsonify({"status": "ok"})
    except Exception as e:
        print("Erro ao atualizar:", str(e))
        return jsonify({"status": "erro", "msg": str(e)})


def get_user_sheet_config(username):
    """
    Busca a configuração da planilha do usuário no Firestore.
    Retorna { sheet_url, sheet_name }
    """
    if not username:
        return None

    ref = db.collection("planilhas_usuarios").document(username).get()

    if not ref.exists:
        return None

    cfg = ref.to_dict()

    # Garantir que os campos essenciais estão presentes
    if "sheet_url" not in cfg or "sheet_name" not in cfg:
        return None

    return {
        "sheet_url": cfg["sheet_url"],
        "sheet_name": cfg["sheet_name"]
    }
@app.route("/test_sheet")
def test_sheet():
    user = session.get("username")
    return get_user_sheet_config(user) or {"erro": "nenhuma config encontrada"}

# ============================================================
# 📝 SALVAR CLIENTE (botão)
# ============================================================

@app.route('/salvar_cliente', methods=['POST'])
def salvar_cliente():
    try:
        cliente = request.json
        if not cliente or 'doc_id' not in cliente:
            return jsonify({'status': 'erro', 'tipo': 'dados', 'mensagem': 'Dados do cliente inválidos.'}), 400

        # Injeta o divulgador logado
        cliente['divulgador'] = session.get('username', 'Desconhecido')

        # injeta data da divulgação se não existir
        if not cliente.get('data_divulgacao'):
            cliente['data_divulgacao'] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        # define a referência DO DOCUMENTO (precisa vir ANTES DE USAR)
        doc_ref = db.collection('fluxo_pessoas').document(cliente['doc_id'])

        # pega o novo telefone
        novo_telefone = cliente.get('novo_telefone', '').strip()

        # salva o cliente inteiro
        doc_ref.set(cliente, merge=True)

        # se veio novo telefone, salva separado também
        if novo_telefone:
            doc_ref.update({'novo_telefone': novo_telefone})

        return jsonify({'status': 'ok'})

    except Exception as e:
        print("Erro geral do servidor:", e)
        return jsonify({'status': 'erro', 'tipo': 'servidor', 'mensagem': str(e)}), 500



# ============================================================
# 🚪 LOGOUT
# ============================================================

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# ============================================================
# 🚀 EXECUÇÃO
# ============================================================

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True)
