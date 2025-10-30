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
    filtered_df['banco_clean'] = filtered_df['banco'].astype(str).str.strip().str.lower() if 'banco' in filtered_df.columns else ""
    filtered_df['idade'] = filtered_df.get('idade', 0)

    blocked_banks = [""]
    blocked_banks = [b.lower() for b in blocked_banks]

    filtered_df = filtered_df[~filtered_df['banco_clean'].isin(blocked_banks)]
    filtered_df = filtered_df[filtered_df['idade'] <= 70]

    if uf_filtro:
        filtered_df = filtered_df[filtered_df['uf'].str.upper() == uf_filtro.upper()]
    if orgao_filtro:
        filtered_df = filtered_df[filtered_df['orgao'].astype(str).str.upper() == orgao_filtro.upper()]

    filtered_df.drop(columns=['banco_clean'], errors='ignore', inplace=True)
    return filtered_df

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
    except (ValueError, TypeError):
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

    # --- Comentar salvamento no Firebase ---
    # existing_docs = db.collection('fluxo_pessoas').stream()
    # existing_ids = set(doc.id for doc in existing_docs)
    # new_df = filtered_df[~filtered_df['doc_id'].isin(existing_ids)]
    # enviados = 0
    # for _, row in new_df.iterrows():
    #     doc_ref = db.collection('fluxo_pessoas').document(row['doc_id'])
    #     doc = {
    #         "cpf": row['cpf'],
    #         "nome": row['nome'],
    #         "dt_nascimento": row.get('dt_nascimento', ''),
    #         "idade": row['idade'],
    #         "banco": row['banco'],
    #         "uf": row['uf'],
    #         "parcela": row.get('parcela_exibir', '0,00'),
    #         "prazo": row['prazo'],
    #         "saldo_devedor": format_brl(row['saldo_devedor_float']),
    #         "orgao": row.get('orgao', ''),
    #         "matricula": row.get('matricula', ''),
    #         "timestamp": datetime.utcnow()
    #     }
    #     doc_ref.set(doc)
    #     enviados += 1
    # print(f"\n🔥 Total de registros enviados ao Firestore: {enviados}")

    paginated_df = filtered_df.iloc[start:start + limit].copy()
    paginated_df["parcela"] = paginated_df["parcela_exibir"]
    paginated_df["saldo_devedor"] = paginated_df["saldo_devedor_float"].apply(format_brl)

    table_data = paginated_df.to_dict(orient="records")

    return render_template(
        'sheets_view.html',
        table_data=table_data,
        start=start,
        username=session.get('username'),
        exibidos=len(paginated_df)
    )

# ============================================================
# 🔁 AJAX ATUALIZAÇÃO
# ============================================================

@app.route('/atualiza_dataframe', methods=['POST'])
def atualiza_dataframe():
    print("\n🔥 ROTA ATUALIZAÇÃO ACIONADA")

    data = request.get_json()
    start = int(data.get('start', 0))
    limit = int(data.get('limit', 10))

    # --- Ler planilha apenas uma vez ---
    df = read_sheet_to_dataframe(SHEET_URL, SHEET_NAME)
    df.columns = df.columns.str.strip().str.replace(" ", "_").str.lower()
    for col in ["parcela", "prazo", "idade"]:
        if col in df.columns:
            df[col] = df[col].apply(parse_brl)

    df["saldo_devedor_float"] = df.apply(calcular_valor_financiado, axis=1)
    df["parcela_exibir"] = (df["parcela"] / 100).apply(format_brl)

    # --- Aplicar filtros passados via JSON ---
    saldo_filtro = data.get('saldo', None)
    uf_filtro = data.get('uf', None)
    orgao_filtro = data.get('orgao', None)

    filtered_df = aplicar_filtros(df, uf_filtro=uf_filtro, orgao_filtro=orgao_filtro, saldo_filtro=saldo_filtro)
    filtered_df['doc_id'] = filtered_df.apply(
        lambda row: f"{row['cpf']}_{row['banco']}_{int(row['prazo'])}_{int(row['parcela'])}_{row['uf']}".replace(" ", "").upper(), axis=1
    )
    filtered_df = filtered_df.drop_duplicates(subset=['doc_id'], keep='first')

    # --- Remove clientes já existentes (opcional) ---
    existing_docs = db.collection('fluxo_pessoas').stream()
    existing_ids = set(doc.id for doc in existing_docs)
    new_df = filtered_df[~filtered_df['doc_id'].isin(existing_ids)]

    # --- Preparar JSON de clientes ---
    paginated_df = filtered_df.iloc[start:start + limit].copy()
    paginated_df["parcela"] = paginated_df["parcela_exibir"]
    paginated_df["saldo_devedor"] = paginated_df["saldo_devedor_float"].apply(format_brl)

    clientes_json = paginated_df.to_dict(orient="records")

# --- Retornar JSON diretamente ---
    next_start = start + limit
    if next_start >= len(filtered_df):
        next_start = 0

    # --- Salvar clientes no Firebase (comentado) ---
    # enviados = 0
    # for _, row in paginated_df.iterrows():
    #     doc_ref = db.collection('fluxo_pessoas').document(row['doc_id'])
    #     doc = {
    #         "cpf": row['cpf'],
    #         "nome": row['nome'],
    #         "dt_nascimento": row.get('dt_nascimento', ''),
    #         "idade": row['idade'],
    #         "banco": row['banco'],
    #         "uf": row['uf'],
    #         "parcela": row.get('parcela_exibir', '0,00'),
    #         "prazo": row['prazo'],
    #         "saldo_devedor": format_brl(row['saldo_devedor_float']),
    #         "orgao": row.get('orgao', ''),
    #         "matricula": row.get('matricula', ''),
    #         "timestamp": datetime.utcnow()
    #     }
    #     doc_ref.set(doc)
    #     enviados += 1

    # --- Preparar HTML para retornar ---
    colunas_base = ["nome", "cpf", "banco", "uf", "saldo_devedor", "parcela", "prazo"]
    colunas_telefone = [c for c in paginated_df.columns if "telefone" in c.lower()]
    colunas = [c for c in (colunas_base + colunas_telefone) if c in paginated_df.columns]

    tbody_html = ""
    for _, row in paginated_df.iterrows():
        tbody_html += "<tr>"
        for c in colunas:
            valor = row.get(c, "")
            tbody_html += f"<td>{valor}</td>"
        tbody_html += "</tr>"

    return jsonify({
    "clientes": clientes_json,
    "next_start": next_start
})

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