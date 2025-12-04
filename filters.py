import pandas as pd
from firebase_admin import firestore

db = firestore.client()

# ----------------------------------------------------
# LER ÓRGÃOS DO FIRESTORE
# ----------------------------------------------------
def carregar_orgaos():
    orgaos_ref = db.collection("orgaos")
    docs = orgaos_ref.stream()

    lista_orgaos = []

    for doc in docs:
        data = doc.to_dict()
        if not data:
            continue

        nome = data.get("nome", "").strip()
        taxa_raw = data.get("taxa", "0")
        codigos_raw = data.get("codigos", "")
        ativo_raw = data.get("ativo", "false")

        # "22202, 1997" → ["22202", "1997"]
        codigos = [c.strip() for c in codigos_raw.split(",")]

        # "1,36%" → 0.0136
        taxa_str = str(taxa_raw).replace("%", "").replace(",", ".").strip()
        taxa_float = float(taxa_str) / 100 if taxa_str else 0

        ativo_bool = str(ativo_raw).lower() == "true"

        lista_orgaos.append({
            "nome": nome,
            "codigos": codigos,
            "taxa": taxa_float,
            "ativo": ativo_bool
        })

    return lista_orgaos


def aplicar_filtros(df: pd.DataFrame, uf_filtro=None, orgao_filtro=None, saldo_filtro=None, orgaos_fire=None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    # -------------------------------
    # 1) FILTRO DE SALDO
    # -------------------------------
    saldo_min = float(saldo_filtro) if saldo_filtro else 25000
    filtered_df = df[df.get("saldo_devedor_float", 0) >= saldo_min].copy()

    # -------------------------------
    # 2) BANCO E IDADE
    # -------------------------------
    filtered_df['banco_clean'] = (
        filtered_df['banco'].astype(str).str.strip().str.lower()
        if 'banco' in filtered_df.columns else ""
    )
    filtered_df['idade'] = filtered_df.get('idade', 0)
    blocked_banks = [""]  # lista de bancos bloqueados
    filtered_df = filtered_df[~filtered_df['banco_clean'].isin(blocked_banks)]
    filtered_df = filtered_df[filtered_df['idade'] <= 70]

    # -------------------------------
    # 3) LIMPEZA DO CÓDIGO DO ÓRGÃO
    # -------------------------------
    if "orgao" in filtered_df.columns:
        filtered_df["orgao_clean"] = (
            filtered_df["orgao"].astype(str).str.replace(".0", "", regex=False).str.strip()
        )

    # -------------------------------
    # 4) FILTRO DE ÓRGÃOS (FIRESTORE + MANUAL)
    # -------------------------------
    codigos_validos = set()  # inicializa sempre, evita erro
    if orgaos_fire and "orgao_clean" in filtered_df.columns:
        for org in orgaos_fire:
            if org.get("ativo", False):
                for c in org.get("codigos", []):
                    codigos_validos.add(str(c).strip())

        # aplica filtro manual se passado
        if orgao_filtro:
            orgao_filtro = str(orgao_filtro).strip()
            codigos_filtro_manual = set()
            for org in orgaos_fire:
                if orgao_filtro.lower() == org.get("nome", "").lower() or orgao_filtro in org.get("codigos", []):
                    for c in org.get("codigos", []):
                        codigos_filtro_manual.add(str(c).strip())
            if codigos_filtro_manual:
                codigos_validos &= codigos_filtro_manual
            else:
                codigos_validos = {orgao_filtro}  # tenta direto se não achar correspondência

        filtered_df = filtered_df[filtered_df["orgao_clean"].isin(codigos_validos)]

    # -------------------------------
    # 5) FILTRO DE UF
    # -------------------------------
    if uf_filtro and 'uf' in filtered_df.columns:
        filtered_df = filtered_df[filtered_df['uf'].str.upper() == uf_filtro.upper()]

    # -------------------------------
    # 6) REMOVE COLUNAS TEMPORÁRIAS
    # -------------------------------
    filtered_df.drop(columns=['banco_clean', 'orgao_clean'], errors='ignore', inplace=True)

    # -------------------------------
    # 7) RETORNO FINAL
    # -------------------------------
    return filtered_df
