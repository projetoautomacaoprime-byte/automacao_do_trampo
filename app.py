import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash
import os
from dotenv import load_dotenv
from datetime import timedelta, datetime
import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

# Cria a aplicação Flask
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

# Inicializar Firebase
cred = credentials.Certificate("credenciais.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# Carregar variáveis do .env
load_dotenv()

# Define tempo máximo da sessão
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

# --- Dashboard protegido com filtros e paginação ---
@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('home'))

    # --- Parâmetros de paginação ---
    start = int(request.args.get('start', 0))
    limit = 10

    # --- Receber filtros do request ---
    cpf = request.args.get('cpf', '').strip()
    parcela_min = request.args.get('parcela_min', '').strip()
    prazo_min = request.args.get('prazo_min', '').strip()
    banco = request.args.get('banco', '').strip()
    idade_max = request.args.get('idade_max', '').strip()

    # --- Ler planilha ---
    SHEET_URL = "https://docs.google.com/spreadsheets/d/1hKhKv4h4QGx5PyfNqp5kXQz0CPp_7wE3X1F-QvWxiCI/edit?gid=0#gid=0"
    SHEET_NAME = "Página1"
    df = read_sheet_to_dataframe(SHEET_URL, SHEET_NAME)

    # --- Aplicar filtros ---
    filtered_df = df.copy()
    if parcela_min:
        filtered_df = filtered_df[filtered_df["Parcela"] >= int(parcela_min)]
    if prazo_min:
        filtered_df = filtered_df[filtered_df["Prazo"] >= int(prazo_min)]
    if banco:
        filtered_df = filtered_df[filtered_df["Banco"].str.contains(banco, case=False)]
    if idade_max:
        filtered_df = filtered_df[filtered_df["Idade"] <= int(idade_max)]

    # --- Paginação ---
    paginated_df = filtered_df.iloc[start:start+limit]
    table_html = paginated_df.to_html(classes='table table-striped', index=False)
    next_start = start + limit if start + limit < len(filtered_df) else None

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
