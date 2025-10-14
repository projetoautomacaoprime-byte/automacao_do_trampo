import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.security import check_password_hash
import os
from dotenv import load_dotenv
from datetime import timedelta, datetime
import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

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

# --- Função para ler planilha do Google Sheets ---
def read_sheet_to_dataframe(sheet_url: str, sheet_name: str, creds_path: str = "credenciais.json") -> pd.DataFrame:
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_url(sheet_url)
    worksheet = sheet.worksheet(sheet_name)
    data = worksheet.get_all_records()
    df = pd.DataFrame(data)
    return df

# --- Função segura para converter BRL para float ---
def parse_brl(valor):
    try:
        if isinstance(valor, str):
            valor = valor.replace(".", "").replace(",", ".")
        return float(valor)
    except Exception as e:
        print("Erro ao converter número:", valor, e)
        return 0.0

# --- Função para calcular saldo devedor ---
def calcular_valor_financiado(row):
    try:
        parcela = parse_brl(row.get("parcela", 0))
        prazo = int(parse_brl(row.get("prazo", 0)))
        taxa = 1.5 / 100  # 1,5% ao mês em decimal

        if parcela <= 0 or prazo <= 0 or taxa <= 0:
            return 0.0

        valor_financiado = parcela * (1 - (1 + taxa) ** (-prazo)) / taxa

        # Corrigir multiplicação indevida por 100
        valor_financiado /= 100

        print(f"Cliente: {row.get('nome')}, Parcela: {parcela}, Prazo: {prazo}, Saldo calculado: {valor_financiado:.2f}")
        return round(valor_financiado, 2)
    except Exception as e:
        print("Erro ao calcular saldo:", e)
        return 0.0

# --- Função para exibir valores como na planilha ---
def format_brl(valor):
    try:
        return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return valor

# --- Verificação de sessão ---
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

# --- Página inicial (login) ---
@app.route('/')
def home():
    return render_template('login.html')

# --- Processar login ---
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

# --- Dashboard protegido ---
@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('home'))

    start = int(request.args.get('start', 0))
    limit = 10

    # --- Ler planilha ---
    SHEET_URL = "https://docs.google.com/spreadsheets/d/1hKhKv4h4QGx5PyfNqp5kXQz0CPp_7wE3X1F-QvWxiCI/edit?gid=0#gid=0"
    SHEET_NAME = "Página1"
    df = read_sheet_to_dataframe(SHEET_URL, SHEET_NAME)
    print(f"\n✅ Planilha carregada: {len(df)} linhas")

    # --- Padronizar colunas ---
    df.columns = df.columns.str.strip().str.replace(" ", "_").str.lower()

    # --- Converter colunas numéricas BR ---
    for col in ["parcela", "prazo", "idade"]:
        if col in df.columns:
            df[col] = df[col].apply(parse_brl)

    # --- Calcular saldo devedor (float para lógica) ---
    df["saldo_devedor_float"] = df.apply(calcular_valor_financiado, axis=1)

    # --- Dividir parcela por 100 para exibição ---
    df["parcela_exibir"] = (df["parcela"] / 100).apply(format_brl)

    # --- Filtrar clientes com saldo >= 25.000 usando float ---
    filtered_df = df[df["saldo_devedor_float"] >= 25000]
    print(f"✅ Clientes após filtro de saldo: {len(filtered_df)}")

    # --- Paginação ---
    paginated_df = filtered_df.iloc[start:start + limit]
    print(f"✅ Clientes nesta página: {len(paginated_df)}")

    # --- Preparar dataframe para exibição ---
    display_df = paginated_df.copy()
    display_df["parcela"] = display_df["parcela_exibir"]  # parcela formatada para exibição
    display_df["saldo_devedor"] = display_df["saldo_devedor_float"].apply(format_brl)

    table_html = display_df.to_html(classes='table table-striped', index=False)
    next_start = start + limit if start + limit < len(filtered_df) else None

    # --- Salvar registros no Firebase como string formatada ---
    enviados = 0
    for _, row in paginated_df.iterrows():
        doc_id = f"{row['cpf']}_{int(row['prazo'])}_{row['banco']}_{row['uf']}".replace(" ", "").upper()
        doc = {
            "cpf": row['cpf'],
            "nome": row['nome'],
            "dt_nascimento": row.get('dt_nascimento', ''),
            "idade": row['idade'],
            "banco": row['banco'],
            "uf": row['uf'],
            "parcela": format_brl(row['parcela'] / 100),               # string formatada igual planilha
            "prazo": row['prazo'],
            "saldo_devedor": format_brl(row['saldo_devedor_float']),   # string formatada
            "orgao": row.get('orgao', ''),
            "matricula": row.get('matricula', ''),
            "timestamp": datetime.utcnow()
        }
        db.collection('fluxo_pessoas').document(doc_id).set(doc)
        enviados += 1
        print(f"💾 Salvo: {row['nome']} ({row['cpf']}) - {row['banco']} [{row['uf']}]")

    print(f"\n🔥 Total de registros enviados ao Firestore: {enviados}")

    return render_template(
        'sheets_view.html',
        table=table_html,
        start=start,
        next_start=next_start,
        username=session.get('username')
    )


# --- Logout ---
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# --- Inicializa o servidor ---
if __name__ == '__main__':
    app.run(debug=True)
