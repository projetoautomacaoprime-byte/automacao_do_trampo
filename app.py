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

# --- Configuração do Flask ---
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")

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

# --- Inicializar Firebase ---
cred = credentials.Certificate("credenciais.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# --- Carregar variáveis do .env ---
load_dotenv()

# --- Tempo máximo da sessão ---
SESSION_TIMEOUT_MINUTES = 30

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

# --- Dashboard protegido com filtros automáticos, paginação e salvamento no Firebase ---
@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('home'))

    # --- Paginação ---
    start = int(request.args.get('start', 0))
    limit = 10

    # --- Ler planilha ---
    SHEET_URL = "https://docs.google.com/spreadsheets/d/1hKhKv4h4QGx5PyfNqp5kXQz0CPp_7wE3X1F-QvWxiCI/edit?gid=0#gid=0"
    SHEET_NAME = "Página1"
    df = read_sheet_to_dataframe(SHEET_URL, SHEET_NAME)

    # --- Padronizar colunas ---
    df.columns = df.columns.str.strip()
    df.columns = df.columns.str.replace(" ", "_")
    df.columns = df.columns.str.lower()

    # --- Converter taxa de juros ---
    if "taxa_juros_mensal" in df.columns:
        df["taxa_juros_mensal"] = df["taxa_juros_mensal"].astype(str).str.replace(",", ".").astype(float) / 100
    else:
        df["taxa_juros_mensal"] = 0.015

    # --- Calcular saldo devedor ---
    df["saldo_devedor"] = df.apply(
        lambda row: row["parcela"] * (1 - (1 + row["taxa_juros_mensal"]) ** -row["prazo"]) / row["taxa_juros_mensal"]
        if row["taxa_juros_mensal"] > 0 else row["parcela"] * row["prazo"],
        axis=1
    )

    # --- Filtros automáticos ---
    parcela_min = 365.55
    prazo_min = 55
    idade_max = 70
    banco = ""

    filtered_df = df.copy()
    filtered_df = filtered_df[filtered_df["parcela"] >= parcela_min]
    filtered_df = filtered_df[filtered_df["prazo"] >= prazo_min]
    filtered_df = filtered_df[filtered_df["idade"] <= idade_max]
    if banco:
        filtered_df = filtered_df[filtered_df["banco"].str.contains(banco, case=False, na=False)]

    # --- Filtro por saldo mínimo ---
    i = 0.015
    saldo_min = parcela_min * (1 - (1 + i) ** -prazo_min) / i
    filtered_df = filtered_df[filtered_df["saldo_devedor"] >= saldo_min]

    # --- Paginação para exibição ---
    paginated_df = filtered_df.iloc[start:start + limit]
    table_html = paginated_df.to_html(classes='table table-striped', index=False)
    next_start = start + limit if start + limit < len(filtered_df) else None

    # --- Salvar somente os 10 registros visíveis no Firebase ---
    for _, row in paginated_df.iterrows():
        doc_id = f"{row['cpf']}_{row['banco']}_{row['uf']}".replace(" ", "").upper()
        doc = {
            "cpf": row['cpf'],
            "nome": row['nome'],
            "dt_nascimento": row.get('dt_nascimento', ''),
            "idade": row['idade'],
            "banco": row['banco'],
            "uf": row['uf'],
            "parcela": row['parcela'],
            "prazo": row['prazo'],
            "saldo_devedor": row['saldo_devedor'],
            "orgao": row.get('orgao', ''),
            "matricula": row.get('matricula', ''),
            "timestamp": datetime.utcnow()
        }
        db.collection('fluxo_pessoas').document(doc_id).set(doc)

    # --- Renderizar template ---
    return render_template(
        'sheets_view.html',
        table=table_html,
        start=start,
        next_start=next_start,
        parcela_min=parcela_min,
        prazo_min=prazo_min,
        banco=banco,
        idade_max=idade_max,
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
