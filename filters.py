import pandas as pd
from firebase_admin import firestore

db = firestore.client()

# ----------------------------------------------------
# LER ÓRGÃOS DO FIRESTORE
# ----------------------------------------------------
def carregar_orgaos():
    orgaos_ref = db.collection("Orgãos_taxa_cod")
    docs = orgaos_ref.stream()

    lista_orgaos = []

    print("Coleção lida:", orgaos_ref)
    print("Documentos encontrados:")
    for doc in orgaos_ref.stream():
        print(doc.id, doc.to_dict())

    for doc in docs:
        data = doc.to_dict()
        if not data:
            continue

        nome = data.get("nome", "").strip()
        taxa_raw = data.get("taxa", "0")
        codigos_raw = data.get("codigos", [])
        ativo_raw = data.get("ativo", "false")

        # Firestore: codigos é ARRAY (não string)
        if isinstance(codigos_raw, list):
            codigos = [str(c).strip() for c in codigos_raw]
        else:
            codigos = [c.strip() for c in str(codigos_raw).split(",")]

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


# ----------------------------------------------------
# FILTRAR DATAFRAME
# ----------------------------------------------------
def aplicar_filtros(df: pd.DataFrame, uf_filtro=None, orgao_filtro=None, saldo_filtro=None, orgaos_fire=None) -> pd.DataFrame:

    if df is None or df.empty:
        return pd.DataFrame()

    saldo_min = float(saldo_filtro) if saldo_filtro else 25000
    filtered_df = df[df.get("saldo_devedor_float", 0) >= saldo_min].copy()

    # Banco + Idade
    filtered_df['banco_clean'] = (
        filtered_df['banco'].astype(str).str.strip().str.lower()
        if 'banco' in filtered_df.columns else ""
    )
    filtered_df = filtered_df[filtered_df['banco_clean'] != ""]
    filtered_df = filtered_df[filtered_df.get('idade', 0) <= 70]

    # Limpeza do órgão → deixa só números
    if "orgao" in filtered_df.columns:
        filtered_df["orgao_clean"] = (
            filtered_df["orgao"]
                .astype(str)
                .str.replace(r"[^0-9]", "", regex=True)
                .str.strip()
        )

    # ----------------------------------------------------------
    # CRIAR MAPA DE CÓDIGOS → ÓRGÃOS (nome, taxa)
    # ----------------------------------------------------------
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
                codigo_to_orgao[c_normalizado] = {
                    "nome": nome,
                    "taxa": taxa
                }

    # ----------------------------------------------------------
    # FILTRAR APENAS CÓDIGOS EXISTENTES NO FIRESTORE
    # ----------------------------------------------------------
    filtered_df = filtered_df[
        filtered_df["orgao_clean"].isin(codigo_to_orgao.keys())
    ].copy()

    if filtered_df.empty:
        return filtered_df

    # ----------------------------------------------------------
    # ADICIONAR NOME DO ÓRGÃO + TAXa
    # ----------------------------------------------------------
    filtered_df["nome_orgao"] = filtered_df["orgao_clean"].apply(
        lambda x: codigo_to_orgao.get(x, {}).get("nome", "")
    )

    filtered_df["taxa_orgao"] = filtered_df["orgao_clean"].apply(
        lambda x: codigo_to_orgao.get(x, {}).get("taxa", 0)
    )

    # Filtro manual de órgão
    if orgao_filtro:
        orgao_filtro = str(orgao_filtro).lower().strip()
        filtered_df = filtered_df[
            filtered_df["nome_orgao"].str.lower() == orgao_filtro
        ]

    # Filtro UF
    if uf_filtro and "uf" in filtered_df.columns:
        filtered_df = filtered_df[
            filtered_df["uf"].str.upper() == uf_filtro.upper()
        ]

    # Limpeza final
    filtered_df.drop(columns=["banco_clean", "orgao_clean"], errors="ignore", inplace=True)

    return filtered_df
