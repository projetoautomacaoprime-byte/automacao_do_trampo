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

    start = request.args.get('start', 0)
    try:
        start = int(start)
    except:
        start = 0
    limit = 10

    df = read_sheet_to_dataframe(SHEET_URL, SHEET_NAME)
    df.columns = df.columns.str.strip().str.replace(" ", "_").str.lower()
    for col in ["parcela", "prazo", "idade"]:
        if col in df.columns:
            df[col] = df[col].apply(parse_brl)

    df["saldo_devedor_float"] = df.apply(calcular_valor_financiado, axis=1)
    df["parcela_exibir"] = (df["parcela"] / 100).apply(format_brl)

    saldo_filtro = request.args.get('saldo', None)
    uf_filtro = request.args.get('uf', None)
    orgao_filtro = request.args.get('orgao', None)

    filtered_df = aplicar_filtros(df, uf_filtro=uf_filtro, orgao_filtro=orgao_filtro, saldo_filtro=saldo_filtro)
    filtered_df['doc_id'] = filtered_df.apply(lambda row: f"{row['cpf']}_{row['banco']}_{int(row['prazo'])}_{int(row['parcela'])}_{row['uf']}".replace(" ", "").upper(), axis=1)
    filtered_df = filtered_df.drop_duplicates(subset=['doc_id'], keep='first')

    paginated_df = filtered_df.iloc[start:start + limit].copy()
    paginated_df["parcela"] = paginated_df["parcela_exibir"]
    paginated_df["saldo_devedor"] = paginated_df["saldo_devedor_float"].apply(format_brl)

    table_data = paginated_df.to_dict(orient="records")

    return render_template(
        'sheets_view.html',
        table_data=[],  # começa vazio
        start=0,
        username=session.get('username'),
        exibidos=0
    )


# ============================================================
# 🔁 AJAX ATUALIZAÇÃO (carregar mais 10)
# ============================================================

@app.route('/atualiza_dataframe', methods=['POST'])
def atualiza_dataframe():
    data = request.get_json()
    start = int(data.get('start', 0))
    limit = int(data.get('limit', 10))

    df = read_sheet_to_dataframe(SHEET_URL, SHEET_NAME)
    df.columns = df.columns.str.strip().str.replace(" ", "_").str.lower()
    for col in ["parcela", "prazo", "idade"]:
        if col in df.columns:
            df[col] = df[col].apply(parse_brl)

    df["saldo_devedor_float"] = df.apply(calcular_valor_financiado, axis=1)
    df["parcela_exibir"] = (df["parcela"] / 100).apply(format_brl)

    saldo_filtro = data.get('saldo', None)
    uf_filtro = data.get('uf', None)
    orgao_filtro = data.get('orgao', None)

    filtered_df = aplicar_filtros(df, uf_filtro=uf_filtro, orgao_filtro=orgao_filtro, saldo_filtro=saldo_filtro)
    filtered_df['doc_id'] = filtered_df.apply(
        lambda row: f"{row['cpf']}_{row['banco']}_{int(row['prazo'])}_{int(row['parcela'])}_{row['uf']}".replace(" ", "").upper(),
        axis=1
    )
    filtered_df = filtered_df.drop_duplicates(subset=['doc_id'], keep='first')

    paginated_df = filtered_df.iloc[start:start + limit].copy()
    paginated_df["parcela"] = paginated_df["parcela_exibir"]
    paginated_df["saldo_devedor"] = paginated_df["saldo_devedor_float"].apply(format_brl)

    clientes_json = paginated_df.to_dict(orient="records")

    # 🟩 ADICIONE ESSE TRECHO AQUI:
    # Busca o divulgador salvo no Firestore (caso exista)
    for cliente in clientes_json:
        doc_id = cliente.get('doc_id')
        if doc_id:
            doc = db.collection('fluxo_pessoas').document(doc_id).get()
            if doc.exists:
                data = doc.to_dict()
                if 'divulgador' in data:
                    cliente['divulgador'] = data['divulgador']
    # 🟩 FIM DO TRECHO

    next_start = start + limit
    if next_start >= len(filtered_df):
        next_start = 0

    return jsonify({
        "clientes": clientes_json,
        "next_start": next_start
    })

# Rota da tela de consulta
@app.route('/consulta', methods=['GET'])
def consulta():
    # exige login (mesma lógica que usa no /dashboard)
    if not session.get('logged_in'):
        return redirect(url_for('home'))

    # podemos passar dados iniciais (ex: username) para o template
    return render_template('consulta.html', username=session.get('username'))



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



# ============================================================
# 📝 SALVAR CLIENTE (botão)
# ============================================================

@app.route('/salvar_cliente', methods=['POST'])
def salvar_cliente():
    try:
        cliente = request.json
        if not cliente or 'doc_id' not in cliente:
            return jsonify({'status': 'erro', 'tipo': 'dados', 'mensagem': 'Dados do cliente inválidos.'}), 400

        # 🟩 Validação do novo telefone
        novo_telefone = cliente.get('novo_telefone', '').strip()
        if novo_telefone:
            if not novo_telefone.isdigit() or len(novo_telefone) not in [10, 11]:
                return jsonify({'status': 'erro', 'tipo': 'telefone', 'mensagem': 'Número de telefone inválido.'}), 400

        # 🟩 Salvar no Firestore (inclui o novo_telefone se existir)
        try:
            doc_ref = db.collection('fluxo_pessoas').document(cliente['doc_id'])
            doc_ref.set(cliente, merge=True)

            # Se o novo_telefone foi enviado, adiciona também como campo isolado
            if novo_telefone:
                doc_ref.update({'novo_telefone': novo_telefone})

            return jsonify({'status': 'ok'})

        except firebase_admin.exceptions.FirebaseError as e:
            print("Erro Firebase:", e)
            return jsonify({'status': 'erro', 'tipo': 'firebase', 'mensagem': 'Erro na API do Firebase.'}), 500
        except Exception as e:
            print("Erro desconhecido ao salvar no Firebase:", e)
            return jsonify({'status': 'erro', 'tipo': 'desconhecido', 'mensagem': 'Erro inesperado ao salvar cliente.'}), 500

    except Exception as e:
        print("Erro geral do servidor:", e)
        return jsonify({'status': 'erro', 'tipo': 'servidor', 'mensagem': 'Erro inesperado no servidor.'}), 500


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
