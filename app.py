import os
from datetime import timedelta, datetime, timezone
import firebase_admin
from firebase_admin import credentials, firestore
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from werkzeug.security import check_password_hash, generate_password_hash
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
firebase_creds_path = os.getenv("FIREBASE_CREDENTIALS")
if not firebase_creds_path:
    raise ValueError("FIREBASE_CREDENTIALS não está definido no .env")

cred = credentials.Certificate(firebase_creds_path)
firebase_admin.initialize_app(cred)
db = firestore.client()

# --- Tempo máximo da sessão ---
SESSION_TIMEOUT_MINUTES = 30
app.permanent_session_lifetime = timedelta(minutes=SESSION_TIMEOUT_MINUTES)

# Hardening das cookies de sessão
# Em produção mantenha SESSION_COOKIE_SECURE = True (requer HTTPS)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'


# ============================================================
# 🧩 FUNÇÕES AUXILIARES
# ============================================================
def read_sheet_to_dataframe(sheet_url: str, sheet_name: str, creds_path: str = "credenciais.json") -> pd.DataFrame:
    """
    Lê uma planilha Google. Se sheet_url for None/empty retorna DataFrame vazio.
    """
    if not sheet_url or not sheet_name:
        return pd.DataFrame()  # evita erro quando usuário não tem planilha configurada

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
# 🔐 SESSÃO (verificação centralizada)
# ============================================================
@app.before_request
def verificar_sessao():
    # exige login para rotas que requerem sessão, mas permite outras (ex: rota /)
    if not session.get("logged_in"):
        return None

    last_seen = session.get("last_seen")
    now = datetime.now(timezone.utc)

    # verifica formato e converte para timezone-aware
    if last_seen:
        try:
            ultimo_acesso = datetime.strptime(last_seen, "%Y-%m-%d %H:%M:%S%z")
        except Exception:
            try:
                ultimo_acesso = datetime.strptime(last_seen, "%Y-%m-%d %H:%M:%S")
                ultimo_acesso = ultimo_acesso.replace(tzinfo=timezone.utc)
            except Exception:
                session.clear()
                return redirect(url_for("home"))

        # expiração por inatividade
        if (now - ultimo_acesso) > app.permanent_session_lifetime:
            session.clear()
            return redirect(url_for("home"))

    # Checar se a senha foi alterada depois que a sessão foi criada
    username = session.get("username")
    if username:
        doc = db.collection("usuarios").document(username).get()
        if doc.exists:
            u = doc.to_dict()
            pwd_changed = u.get("password_changed_at")  # ISO string
            if pwd_changed:
                try:
                    pwd_changed_dt = datetime.fromisoformat(pwd_changed)
                    session_created = datetime.strptime(session.get("last_seen"), "%Y-%m-%d %H:%M:%S%z")
                    if pwd_changed_dt > session_created:
                        session.clear()
                        return redirect(url_for("home"))
                except Exception:
                    # se parsing falhar, seguir adiante (não bloquear)
                    pass

    # atualiza last_seen
    session['last_seen'] = now.strftime("%Y-%m-%d %H:%M:%S%z")
    return None


# ============================================================
# 🔑 AUTENTICAÇÃO
# ============================================================
@app.route('/')
def home():
    return render_template('login.html')


@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')

    usuarios_ref = db.collection('usuarios')
    query = usuarios_ref.where('username', '==', username).limit(1).stream()
    user_doc = next(query, None)

    if user_doc:
        user_data = user_doc.to_dict()
        password_hash = user_data.get('password_hash')
        if password_hash and check_password_hash(password_hash, password):
            # Rotaciona sessão (evita session fixation)
            session.clear()
            session.permanent = True
            session['logged_in'] = True
            session['username'] = username
            session['role'] = user_data.get('role', 'user')
            session['last_seen'] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S%z")
            return redirect(url_for('dashboard'))

    # resposta genérica para não vazar informação
    return 'Usuário ou senha incorretos!', 401


@app.route('/alterar_senha', methods=['POST'])
def alterar_senha():
    if not session.get('logged_in'):
        return redirect(url_for('home'))

    username = session.get('username')
    nova = request.form.get('nova_senha', '').strip()
    if not nova:
        return "Senha inválida", 400

    password_hash = generate_password_hash(nova)
    now = datetime.now(timezone.utc).isoformat()

    # Atualiza no Firestore
    db.collection("usuarios").document(username).update({
        "password_hash": password_hash,
        "password_changed_at": now
    })

    # Invalida sessão atual (força novo login)
    session.clear()
    return redirect(url_for('home'))


# ============================================================
# 🧩 FILTROS (função única, limpa)
# ============================================================
def aplicar_filtros(df: pd.DataFrame, uf_filtro=None, orgao_filtro=None, saldo_filtro=None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    saldo_min = float(saldo_filtro) if saldo_filtro else 25000
    filtered_df = df[df.get("saldo_devedor_float", 0) >= saldo_min].copy()

    filtered_df['banco_clean'] = filtered_df['banco'].astype(str).str.strip().str.lower() if 'banco' in df.columns else ""
    filtered_df['idade'] = filtered_df.get('idade', 0)

    # FILTRO DE BANCOS (exemplo: lista bloqueada vazia por enquanto)
    blocked_banks = [b.lower() for b in [""]]
    filtered_df = filtered_df[~filtered_df['banco_clean'].isin(blocked_banks)]
    filtered_df = filtered_df[filtered_df['idade'] <= 70]

    # NOVO FILTRO DE ÓRGÃOS (MOSTRAR APENAS OS PERMITIDOS)
    allowed_orgaos = ["40803"]
    orgaos_info = {
        "40803": {"nome": "Vinigay", "taxa": 1.50},
    }

    if "orgao" in filtered_df.columns:
        filtered_df["orgao_clean"] = filtered_df["orgao"].astype(str).str.strip().str.upper()
        filtered_df = filtered_df[filtered_df["orgao_clean"].isin([o.upper() for o in allowed_orgaos])]
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

    if uf_filtro and 'uf' in filtered_df.columns:
        filtered_df = filtered_df[filtered_df['uf'].str.upper() == uf_filtro.upper()]
    if orgao_filtro and 'orgao' in filtered_df.columns:
        filtered_df = filtered_df[filtered_df['orgao'].astype(str).str.upper() == orgao_filtro.upper()]

    return filtered_df


# ============================================================
# helpers divulgadores
# ============================================================
def get_divulgadores_list():
    """
    Retorna lista de nomes da coleção 'divulgadores'.
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
# 📊 DASHBOARD E ROTAS (mantive sua lógica)
# ============================================================
SHEET_URL = "https://docs.google.com/spreadsheets/d/1hKhKv4h4QGx5PyfNqp5kXQz0CPp_7wE3X1F-QvWxiCI/edit?gid=0#gid=0"
SHEET_NAME = "Página1"

@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('home'))

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

    return render_template('sheets_view.html', table_data=table_data, start=start, username=session.get('username'), exibidos=len(table_data))


@app.route('/atualiza_dataframe', methods=['POST'])
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


@app.route('/consulta', methods=['GET'])
def consulta():
    if not session.get('logged_in'):
        return redirect(url_for('home'))
    return render_template('consulta.html', username=session.get('username'))


@app.route('/buscar_fluxo', methods=['POST'])
def buscar_fluxo():
    data = request.get_json()
    termo = data.get('q', '').strip().lower()
    limit = data.get('limit', 20)
    divulgador_filtro = data.get('divulgador')

    colecao = db.collection('fluxo_pessoas')
    query = colecao.order_by('nome')

    resultados = []
    docs = query.stream()
    for doc in docs:
        d = doc.to_dict()
        if not d:
            continue
        if divulgador_filtro and d.get('divulgador') != divulgador_filtro:
            continue
        if termo and not any(termo in str(d.get(field, '')).lower()
                             for field in ['nome', 'cpf', 'telefone_movel_1', 'telefone_movel_2', 'telefone_movel_3',
                                           'email_1', 'email_2', 'email_3', 'orgao_nome', 'banco']):
            continue

        d['doc_id'] = doc.id
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
            'data_divulgacao': d.get('data_divulgacao', '-')
        }
        resultados.append(resultado_limpo)

    clientes = resultados[:limit]
    mais = len(resultados) > limit
    return jsonify({'clientes': clientes, 'has_more': mais})


@app.route('/cliente/<id>')
def cliente(id):
    cliente_data = db.collection("clientes").document(id).get().to_dict()
    divulgadores = get_divulgadores_list()
    return render_template('sheets_view.html', cliente=cliente_data, divulgadores=divulgadores)


@app.route('/get_divulgadores', methods=['GET'])
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
    except Exception as e:
        print("Erro ao buscar divulgadores:", e)
        return jsonify([]), 500


@app.route("/atualizar_fluxo/<doc_id>", methods=["POST"])
def atualizar_fluxo(doc_id):
    try:
        dados = request.get_json()
        db.collection("fluxo_pessoas").document(doc_id).update(dados)
        return jsonify({"status": "ok"})
    except Exception as e:
        print("Erro ao atualizar:", str(e))
        return jsonify({"status": "erro", "msg": str(e)})


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


@app.route("/test_sheet")
def test_sheet():
    user = session.get("username")
    return get_user_sheet_config(user) or {"erro": "nenhuma config encontrada"}


@app.route('/salvar_cliente', methods=['POST'])
def salvar_cliente():
    try:
        cliente = request.json
        if not cliente or 'doc_id' not in cliente:
            return jsonify({'status': 'erro', 'tipo': 'dados', 'mensagem': 'Dados do cliente inválidos.'}), 400

        cliente['divulgador'] = session.get('username', 'Desconhecido')
        if not cliente.get('data_divulgacao'):
            cliente['data_divulgacao'] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        doc_ref = db.collection('fluxo_pessoas').document(cliente['doc_id'])
        novo_telefone = cliente.get('novo_telefone', '').strip()

        doc_ref.set(cliente, merge=True)
        if novo_telefone:
            doc_ref.update({'novo_telefone': novo_telefone})

        return jsonify({'status': 'ok'})
    except Exception as e:
        print("Erro geral do servidor:", e)
        return jsonify({'status': 'erro', 'tipo': 'servidor', 'mensagem': str(e)}), 500


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))


if __name__ == '__main__':
    # nunca rode com debug=True em produção
    app.run(host="0.0.0.0", port=5000, debug=True)
