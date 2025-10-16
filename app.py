import os
from datetime import timedelta, datetime

import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, render_template_string
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
    """Lê planilha do Google Sheets e retorna como DataFrame"""
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_url(sheet_url)
    worksheet = sheet.worksheet(sheet_name)
    data = worksheet.get_all_records()
    return pd.DataFrame(data)


def parse_brl(valor):
    """Converte valor BRL para float"""
    try:
        if isinstance(valor, str):
            valor = valor.replace(".", "").replace(",", ".")
        return float(valor)
    except Exception as e:
        print("Erro ao converter número:", valor, e)
        return 0.0


def calcular_valor_financiado(row):
    """Calcula o valor financiado (saldo devedor)"""
    try:
        parcela = parse_brl(row.get("parcela", 0))
        prazo = int(parse_brl(row.get("prazo", 0)))
        taxa = 1.5 / 100  # 1,5% ao mês

        if parcela <= 0 or prazo <= 0 or taxa <= 0:
            return 0.0

        valor_financiado = parcela * (1 - (1 + taxa) ** (-prazo)) / taxa
        valor_financiado /= 100  # Corrigir multiplicação indevida por 100

        return round(valor_financiado, 2)
    except Exception as e:
        print("Erro ao calcular saldo:", e)
        return 0.0


def format_brl(valor):
    """Formata float para BRL"""
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
# 📊 DASHBOARD PRINCIPAL
# ============================================================

@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('home'))

    # --- pegar o start corretamente ---
    start = request.args.get('start', 0)
    try:
        start = int(start)
    except (ValueError, TypeError):
        start = 0

    limit = 10


    # --- Ler planilha ---
    SHEET_URL = "https://docs.google.com/spreadsheets/d/1hKhKv4h4QGx5PyfNqp5kXQz0CPp_7wE3X1F-QvWxiCI/edit?gid=0#gid=0"
    SHEET_NAME = "Página1"
    df = read_sheet_to_dataframe(SHEET_URL, SHEET_NAME)
    print(f"\n✅ Planilha carregada: {len(df)} linhas")

    df.columns = df.columns.str.strip().str.replace(" ", "_").str.lower()

    for col in ["parcela", "prazo", "idade"]:
        if col in df.columns:
            df[col] = df[col].apply(parse_brl)

    df["saldo_devedor_float"] = df.apply(calcular_valor_financiado, axis=1)
    df["parcela_exibir"] = (df["parcela"] / 100).apply(format_brl)
    filtered_df = df[df["saldo_devedor_float"] >= 25000]

    def gerar_doc_id(row):
        return f"{row['cpf']}_{row['banco']}_{int(row['prazo'])}_{int(row['parcela'])}_{row['uf']}".replace(" ", "").upper()

    filtered_df['doc_id'] = filtered_df.apply(gerar_doc_id, axis=1)
    filtered_df = filtered_df.drop_duplicates(subset=['doc_id'], keep='first')

    existing_docs = db.collection('fluxo_pessoas').stream()
    existing_ids = set(doc.id for doc in existing_docs)
    new_df = filtered_df[~filtered_df['doc_id'].isin(existing_ids)]

    total_planilha = len(df)
    apos_filtro_saldo = len(df[df["saldo_devedor_float"] >= 25000])
    apos_remover_locais = len(filtered_df)
    apos_remover_firebase = len(new_df)

    paginated_df = new_df.iloc[start:start + limit]

    display_df = paginated_df.copy()
    display_df["parcela"] = display_df["parcela_exibir"]
    display_df["saldo_devedor"] = display_df["saldo_devedor_float"].apply(format_brl)

    next_start = start + limit if start + limit < len(new_df) else None

    # --- Enviar novos registros ao Firebase ---
    enviados = 0
    for _, row in paginated_df.iterrows():
        doc_ref = db.collection('fluxo_pessoas').document(row['doc_id'])
        doc = {
            "cpf": row['cpf'],
            "nome": row['nome'],
            "dt_nascimento": row.get('dt_nascimento', ''),
            "idade": row['idade'],
            "banco": row['banco'],
            "uf": row['uf'],
            "parcela": format_brl(row['parcela'] / 100),
            "prazo": row['prazo'],
            "saldo_devedor": format_brl(row['saldo_devedor_float']),
            "orgao": row.get('orgao', ''),
            "matricula": row.get('matricula', ''),
            "timestamp": datetime.utcnow()
        }
        doc_ref.set(doc)
        enviados += 1

    print(f"\n🔥 Total de registros enviados ao Firestore: {enviados}")

    table_data = display_df[["nome", "cpf", "banco", "uf", "saldo_devedor", "parcela"]].to_dict(orient="records")

    return render_template(
        'sheets_view.html',
        table_data=table_data,
        start=start,
        next_start=next_start,
        username=session.get('username'),
        total_planilha=total_planilha,
        apos_filtro_saldo=apos_filtro_saldo,
        apos_remover_locais=apos_remover_locais,
        apos_remover_firebase=apos_remover_firebase,
        exibidos=len(paginated_df)
    )


# ============================================================
# 🔁 ROTA PARA ATUALIZAR DATAFRAME (via AJAX)
# ============================================================

@app.route('/atualiza_dataframe', methods=['POST'])
def atualiza_dataframe():
    print("\n🔥 ROTA ATUALIZAÇÃO ACIONADA")

    data = request.get_json()
    start = int(data.get('start', 0))
    limit = int(data.get('limit', 10))

    # --- Lê e processa planilha ---
    SHEET_URL = "https://docs.google.com/spreadsheets/d/1hKhKv4h4QGx5PyfNqp5kXQz0CPp_7wE3X1F-QvWxiCI/edit?gid=0#gid=0"
    SHEET_NAME = "Página1"
    df = read_sheet_to_dataframe(SHEET_URL, SHEET_NAME)
    df.columns = df.columns.str.strip().str.replace(" ", "_").str.lower()

    for col in ["parcela", "prazo", "idade"]:
        if col in df.columns:
            df[col] = df[col].apply(parse_brl)

    df["saldo_devedor_float"] = df.apply(calcular_valor_financiado, axis=1)
    df["parcela_exibir"] = (df["parcela"] / 100).apply(format_brl)
    filtered_df = df[df["saldo_devedor_float"] >= 25000]

    def gerar_doc_id(row):
        return f"{row['cpf']}_{row['banco']}_{int(row['prazo'])}_{int(row['parcela'])}_{row['uf']}".replace(" ", "").upper()

    filtered_df['doc_id'] = filtered_df.apply(gerar_doc_id, axis=1)
    filtered_df = filtered_df.drop_duplicates(subset=['doc_id'], keep='first')

    existing_docs = db.collection('fluxo_pessoas').stream()
    existing_ids = set(doc.id for doc in existing_docs)
    new_df = filtered_df[~filtered_df['doc_id'].isin(existing_ids)]

    # --- Paginação ---
    next_start = start + limit
    if next_start >= len(new_df):
        next_start = 0

    print(f"Start recebido: {start}, Próximo start: {next_start}, Total registros novos: {len(new_df)}")

    paginated_df = new_df.iloc[start:start + limit].copy()
    paginated_df["parcela"] = paginated_df["parcela_exibir"]
    paginated_df["saldo_devedor"] = paginated_df["saldo_devedor_float"].apply(format_brl)

    # --- Montar HTML da tabela ---
    tbody_html = ""
    for _, row in paginated_df.iterrows():
        tbody_html += f"""
        <tr>
          <td>{row['nome']}</td>
          <td>{row['cpf']}</td>
          <td>{row['banco']}</td>
          <td>{row['uf']}</td>
          <td>{row['saldo_devedor']}</td>
          <td>{row['parcela']}</td>
        </tr>
        """

    print(f"🔹 Enviando {len(paginated_df)} registros para o frontend.")

    return jsonify({
        "tbody": tbody_html,
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
    app.run(debug=True)
