import pandas as pd
from flask import Blueprint, session, redirect, url_for, request, render_template, jsonify
from config import db
from sheets import read_sheet_to_dataframe, parse_brl, calcular_valor_financiado, format_brl
from filters import aplicar_filtros, carregar_orgaos
from divulgadores import get_divulgadores_list
import bleach
from security import sanitize_doc_id, sanitize_query_param, sanitize_username
import re
from datetime import datetime

dashboard_bp = Blueprint("dashboard", __name__)

# -------------------------------------
# Utils
# -------------------------------------
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


def adiciona_nome_taxa_orgao(table_data):
    orgaos_docs = db.collection("Orgãos_taxa_cod").stream()
    orgaos_lista = [doc.to_dict() for doc in orgaos_docs]
    for cliente in table_data:
        codigo_orgao = str(cliente.get("orgao", "")).strip()
        cliente["orgao_nome"] = "Não informado"
        cliente["orgao_taxa_formatada"] = "—"
        for orgao in orgaos_lista:
            if codigo_orgao in orgao.get("codigos", []):
                cliente["orgao_nome"] = orgao.get("nome", "Não informado").upper()
                taxa = orgao.get("taxa")
                if taxa:
                    try:
                        taxa_clean = str(taxa).replace(",", ".").replace("%", "").strip()
                        cliente["orgao_taxa_formatada"] = f"{float(taxa_clean):.2f}%"
                    except:
                        cliente["orgao_taxa_formatada"] = "—"
                break
    return table_data


def preparar_dataframe(df):
    if df.empty:
        return df
    df.columns = df.columns.str.strip().str.replace(" ", "_").str.lower()
    for col in ["parcela", "prazo", "idade"]:
        if col in df.columns:
            df[col] = df[col].apply(parse_brl)
    df["saldo_devedor_float"] = df.apply(calcular_valor_financiado, axis=1)
    df["parcela_exibir"] = (df["parcela"] / 100).apply(format_brl)
    return df


def gerar_doc_id_from_fields(cpf, banco, prazo, parcela, uf):
    cpf_clean = str(cpf or "").replace(".", "").replace("-", "").strip()
    banco_clean = re.sub(r'[^A-Za-z0-9]', '', str(banco or ""))
    prazo_clean = str(prazo or "").strip()
    parcela_clean = str(parcela or "0").replace(".", "").replace(",", "")
    uf_clean = re.sub(r'[^A-Za-z0-9]', '', str(uf or ""))
    return f"{cpf_clean}_{banco_clean}_{prazo_clean}_{parcela_clean}_{uf_clean}".upper()


def gerar_doc_id(row):
    return gerar_doc_id_from_fields(
        row.get("cpf"),
        row.get("banco"),
        row.get("prazo"),
        row.get("parcela"),
        row.get("uf")
    )


# -------------------------------------
# ROTAS
# -------------------------------------
@dashboard_bp.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        try:
            db.collection("logs_criticos").document().set({
                "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "event_type": "erro_acesso",
                "username": session.get("username"),
                "rota": "/dashboard",
                "acao": "tentativa_sem_login",
                "ip": request.remote_addr,
                "user_agent": request.headers.get("User-Agent")
            })
        except Exception as e:
            print(f"Erro ao registrar log: {e}")
        return redirect(url_for('auth.home'))

    username = session.get("username")
    config = get_user_sheet_config(username)
    sheet_url = config.get("sheet_url") if config else None
    sheet_name = config.get("sheet_name") if config else None

    try:
        start_raw = request.args.get('start', 0)
        start = int(bleach.clean(str(start_raw)))
    except:
        start = 0

    limit = 10

    df = read_sheet_to_dataframe(sheet_url, sheet_name)
    df = preparar_dataframe(df)

    saldo_filtro = sanitize_query_param(request.args.get('saldo') or "")
    uf_filtro = sanitize_query_param(request.args.get('uf') or "")
    orgao_filtro = sanitize_query_param(request.args.get('orgao') or "")

    orgaos_fire = carregar_orgaos()

    filtered_df = aplicar_filtros(
        df,
        uf_filtro=uf_filtro,
        orgao_filtro=orgao_filtro,
        saldo_filtro=saldo_filtro,
        orgaos_fire=orgaos_fire
    )

    if not filtered_df.empty:
        filtered_df["doc_id"] = filtered_df.apply(gerar_doc_id, axis=1)
        filtered_df = filtered_df.drop_duplicates(subset=["doc_id"])
        paginated = filtered_df.iloc[start:start + limit].copy()
        paginated["parcela"] = paginated["parcela_exibir"]
        paginated["saldo_devedor"] = paginated["saldo_devedor_float"].apply(format_brl)
        table_data = adiciona_nome_taxa_orgao(paginated.to_dict(orient="records"))
    else:
        table_data = []

    return render_template(
        "dashboard.html",
        table_data=table_data,
        start=start,
        username=username,
        exibidos=len(table_data)
    )


@dashboard_bp.route("/get_orgaos")
def get_orgaos_route():
    orgaos = carregar_orgaos()
    return jsonify([{"nome": o["nome"], "codigos": o["codigos"], "ativo": o["ativo"]} for o in orgaos]), 200


@dashboard_bp.route("/get_divulgadores")
def get_divulgadores_route():
    return jsonify(get_divulgadores_list()), 200


# -------------------------------------
# AJAX: Atualizar DataFrame
# -------------------------------------
@dashboard_bp.route('/atualiza_dataframe', methods=['POST'])
def atualiza_dataframe():
    if not session.get('logged_in'):
        try:
            db.collection("logs_criticos").document().set({
                "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "event_type": "erro_acesso",
                "username": session.get("username"),
                "rota": "/atualiza_dataframe",
                "acao": "tentativa_sem_login",
                "ip": request.remote_addr,
                "user_agent": request.headers.get("User-Agent")
            })
        except Exception as e:
            print(f"Erro ao registrar log: {e}")
        return jsonify({"success": False, "error": "Usuário não autenticado"}), 401

    try:
        data = request.get_json()
        start = int(bleach.clean(str(data.get("start", 0))))
        limit = int(bleach.clean(str(data.get("limit", 10))))

        username = session.get("username")
        config = get_user_sheet_config(username)
        if not config:
            return jsonify({"success": False, "error": "Planilha do usuário não configurada"}), 400

        df = read_sheet_to_dataframe(config["sheet_url"], config["sheet_name"])
        df = preparar_dataframe(df)
        orgaos_fire = carregar_orgaos()

        uf_filtro = sanitize_query_param(data.get("uf") or "")
        orgao_filtro = sanitize_query_param(data.get("orgao") or "")
        saldo_filtro = sanitize_query_param(str(data.get("saldo") or ""))

        filtered_df = aplicar_filtros(
            df,
            uf_filtro=uf_filtro,
            orgao_filtro=orgao_filtro,
            saldo_filtro=saldo_filtro,
            orgaos_fire=orgaos_fire
        )

        if filtered_df.empty:
            return jsonify({"clientes": [], "total_count": 0, "next_start": 0})

        filtered_df["doc_id"] = filtered_df.apply(gerar_doc_id, axis=1)
        filtered_df = filtered_df.drop_duplicates(subset=["doc_id"])
        paginated = filtered_df.iloc[start:start + limit].copy()
        paginated["parcela"] = paginated["parcela_exibir"]
        paginated["saldo_devedor"] = paginated["saldo_devedor_float"].apply(format_brl)
        clientes_json = adiciona_nome_taxa_orgao(paginated.to_dict(orient="records"))

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


# -------------------------------------
# Salvar/Divulgar cliente (criação via Dashboard)
# -------------------------------------
@dashboard_bp.route("/salvar_cliente_dashboard", methods=["POST"])
def salvar_cliente_dashboard():
    if not session.get('logged_in'):
        try:
            db.collection("logs_criticos").document().set({
                "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "event_type": "erro_acesso",
                "username": session.get("username"),
                "rota": "/salvar_cliente_dashboard",
                "acao": "tentativa_sem_login",
                "ip": request.remote_addr,
                "user_agent": request.headers.get("User-Agent")
            })
        except Exception as e:
            print(f"Erro ao registrar log: {e}")
        return jsonify({"status": "erro", "mensagem": "Usuário não autenticado"}), 401

    try:
        raw = request.get_json() or {}

        def safe_clean(value):
            if value is None:
                return ""
            return bleach.clean(str(value)).strip()

        cpf = safe_clean(raw.get("cpf")).replace(".", "").replace("-", "")
        banco = safe_clean(raw.get("banco"))
        prazo = safe_clean(raw.get("prazo"))
        parcela = safe_clean(raw.get("parcela"))
        uf = safe_clean(raw.get("uf"))
        novo_tel = safe_clean(raw.get("novo_telefone"))

        doc_id = gerar_doc_id_from_fields(cpf, banco, prazo, parcela, uf)
        doc_id = sanitize_doc_id(doc_id)
        doc_ref = db.collection("fluxo_pessoas").document(doc_id)

        payload = {key: safe_clean(value) for key, value in raw.items()}
        if novo_tel:
            payload["novo_telefone"] = novo_tel

        # 🔹 Atrelando automaticamente o divulgador (usuário logado)
        payload["divulgador"] = session.get("username") or "desconhecido"

        # 🔹 Adicionando data de divulgação automática se não existir
        if "data_divulgacao" not in payload or not payload["data_divulgacao"]:
            payload["data_divulgacao"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        doc_ref.set(payload, merge=True)

        try:
            log_ref = db.collection("logs_criticos").document()
            log_ref.set({
                "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "event_type": "alteracao_lead",
                "username": session.get("username"),
                "doc_id": doc_id,
                "acao": "criado/atualizado",
                "ip": request.remote_addr,
                "user_agent": request.headers.get("User-Agent")
            })
        except Exception as e:
            print(f"Erro ao registrar log: {e}")

        return jsonify({"status": "ok", "doc_id": doc_id}), 200

    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500
