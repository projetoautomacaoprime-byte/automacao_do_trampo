import pandas as pd
from firebase_admin import firestore
import logging
import unicodedata
import re

db = firestore.client()
logger = logging.getLogger(__name__)

# ----------------------------------------------------
# MAPEAMENTO DE BANCOS (keywords para detectar mesmo com sufixos)
# ----------------------------------------------------
BANK_KEYWORDS = {
    "bradesco": ["bradesco"],
    "itau": ["itau"],
    "santander": ["santander"],
    "banco do brasil": ["banco do brasil"],
    "nubank": ["nubank"],
    "sicredi": ["sicredi"],
    "daycoval": ["daycoval"],
    "bmg": ["bmg"],
    "inter": ["inter"],
    "safra": ["safra"],
    "alfa": ["alfa"],
    "c6": ["c6"],    # pega "c6 bank", "c6bank" etc
    "brb": ["brb"],
    "inbursa": ["inbursa"],
    "banrisul": ["banrisul"],
}

# set com os bancos aceitos no sistema
BANCOS_VALIDOS = set(BANK_KEYWORDS.keys())


# ----------------------------------------------------
# UTIL: normalizar texto
# ----------------------------------------------------
def normalize_text(s: str) -> str:
    if s is None:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


# ----------------------------------------------------
# MAPEAR BANCO A PARTIR DA STRING DA PLANILHA
# ----------------------------------------------------
def mapear_banco(banco_raw: str) -> str | None:
    norm = normalize_text(banco_raw)

    for banco, keywords in BANK_KEYWORDS.items():
        for kw in keywords:
            kw_norm = normalize_text(kw)
            if kw_norm in norm:
                return banco

    return None


# ----------------------------------------------------
# LER ÓRGÃOS DO FIRESTORE
# ----------------------------------------------------
def carregar_orgaos():
    try:
        orgaos_ref = db.collection("Orgãos_taxa_cod")
        docs = orgaos_ref.stream()

        lista_orgaos = []

        logger.info(f"Coleção lida: {orgaos_ref}")
        logger.info("Documentos encontrados:")
        for doc in orgaos_ref.stream():
            logger.info(f"{doc.id}: {doc.to_dict()}")

        for doc in docs:
            data = doc.to_dict() or {}
            if not data:
                continue

            nome = data.get("nome", "").strip()
            taxa_raw = data.get("taxa", "0")
            codigos_raw = data.get("codigos", [])
            ativo_raw = data.get("ativo", "false")

            # codigos é array no Firestore
            if isinstance(codigos_raw, list):
                codigos = [str(c).strip() for c in codigos_raw]
            else:
                codigos = [c.strip() for c in str(codigos_raw).split(",")]

            # converter taxa "1,36%" → 0.0136
            taxa_float = 0
            try:
                taxa_str = str(taxa_raw).replace("%", "").replace(",", ".").strip()
                taxa_float = float(taxa_str) / 100 if taxa_str else 0
            except ValueError:
                logger.warning(f"Taxa inválida no documento {doc.id}: {taxa_raw}")

            ativo_bool = str(ativo_raw).lower() == "true"

            lista_orgaos.append({
                "nome": nome,
                "codigos": codigos,
                "taxa": taxa_float,
                "ativo": ativo_bool
            })

        return lista_orgaos

    except Exception as e:
        logger.error(f"Erro ao carregar órgãos: {e}")
        return []


# ----------------------------------------------------
# FILTRAR DATAFRAME
# ----------------------------------------------------
def aplicar_filtros(df: pd.DataFrame, uf_filtro=None, orgao_filtro=None,
                    saldo_filtro=None, orgaos_fire=None) -> pd.DataFrame:

    if df is None or df.empty:
        return pd.DataFrame()

    # Saldo mínimo
    saldo_min = 25000
    if saldo_filtro:
        try:
            saldo_min = float(saldo_filtro)
        except ValueError:
            logger.warning(f"Saldo inválido recebido: {saldo_filtro}, usando 25000 como padrão")

    filtered_df = df[df.get("saldo_devedor_float", 0) >= saldo_min].copy()

    # Banco + Idade
    if 'banco' in filtered_df.columns:

        filtered_df['banco_clean'] = filtered_df['banco'].astype(str).str.strip()

        # Primeiro: mapear
        filtered_df['banco_mapeado'] = filtered_df['banco_clean'].apply(mapear_banco)

        # Debug
        try:
            logger.info(f"Mapeados: {filtered_df['banco_mapeado'].dropna().unique()[:20]}")
        except Exception:
            pass

        # Mostrar unmapped ANTES do filtro
        unmapped = filtered_df[filtered_df['banco_mapeado'].isna()]['banco_clean'].unique()
        if len(unmapped) > 0:
            logger.warning(f"❗ Bancos não mapeados (primeiros 20): {unmapped[:20]}")

        # Agora sim filtra bancos válidos
        filtered_df = filtered_df[
            filtered_df['banco_mapeado'].notna() &
            filtered_df['banco_mapeado'].isin(BANCOS_VALIDOS)
        ]

    else:
        return pd.DataFrame()

    # Idade
    if 'idade' in filtered_df.columns:
        filtered_df = filtered_df[filtered_df['idade'] <= 70]

    # Limpeza do órgão
    if "orgao" in filtered_df.columns:
        filtered_df["orgao_clean"] = (
            filtered_df["orgao"]
                .astype(str)
                .str.replace(r"[^0-9]", "", regex=True)
                .str.strip()
        )

    # Criar mapa código → órgão
    codigo_to_orgao = {}
    if orgaos_fire:
        for org in orgaos_fire:
            if not org.get("ativo", False):
                continue
            nome = org.get("nome", "")
            taxa = org.get("taxa", 0)
            codigos = org.get("codigos", [])

            for c in codigos:
                c_normalizado = "".join(filter(str.isdigit, str(c)))
                codigo_to_orgao[c_normalizado] = {"nome": nome, "taxa": taxa}

    # Filtrar códigos existentes
    filtered_df = filtered_df[filtered_df["orgao_clean"].isin(codigo_to_orgao.keys())].copy()
    if filtered_df.empty:
        return filtered_df

    # Adicionar nome e taxa
    filtered_df["nome_orgao"] = filtered_df["orgao_clean"].apply(
        lambda x: codigo_to_orgao.get(x, {}).get("nome", "")
    )
    filtered_df["taxa_orgao"] = filtered_df["orgao_clean"].apply(
        lambda x: codigo_to_orgao.get(x, {}).get("taxa", 0)
    )

    # Filtro simples de órgão (manual input): filtra direto pelo código da planilha
    if orgao_filtro:
        orgao_filtro = str(orgao_filtro).strip()
        filtered_df = filtered_df[filtered_df["orgao_clean"] == orgao_filtro]


    # Filtro UF
    if uf_filtro and "uf" in filtered_df.columns:
        filtered_df = filtered_df[filtered_df["uf"].str.upper() == uf_filtro.upper()]

    # Limpeza final
    filtered_df.drop(columns=["banco_clean", "orgao_clean"], errors="ignore", inplace=True)

    return filtered_df
