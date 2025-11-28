import pandas as pd

def aplicar_filtros(df: pd.DataFrame, uf_filtro=None, orgao_filtro=None, saldo_filtro=None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    saldo_min = float(saldo_filtro) if saldo_filtro else 25000
    filtered_df = df[df.get("saldo_devedor_float", 0) >= saldo_min].copy()

    filtered_df['banco_clean'] = filtered_df['banco'].astype(str).str.strip().str.lower() if 'banco' in df.columns else ""
    filtered_df['idade'] = filtered_df.get('idade', 0)

    blocked_banks = [b.lower() for b in [""]]
    filtered_df = filtered_df[~filtered_df['banco_clean'].isin(blocked_banks)]
    filtered_df = filtered_df[filtered_df['idade'] <= 70]

    allowed_orgaos = ["40803"]
    orgaos_info = {"40803": {"nome": "Vinigay", "taxa": 1.50}}

    if "orgao" in filtered_df.columns:
        filtered_df["orgao_clean"] = filtered_df["orgao"].astype(str).str.strip().str.upper()
        filtered_df = filtered_df[filtered_df["orgao_clean"].isin([o.upper() for o in allowed_orgaos])]
        filtered_df["orgao_nome"] = filtered_df["orgao_clean"].map({k.upper(): v["nome"] for k,v in orgaos_info.items()}).fillna("Desconhecido")
        filtered_df["taxa_orgao"] = filtered_df["orgao_clean"].map({k.upper(): v["taxa"] for k,v in orgaos_info.items()}).fillna(0)
    else:
        filtered_df["orgao_nome"] = "Desconhecido"
        filtered_df["taxa_orgao"] = 0

    filtered_df.drop(columns=['banco_clean', 'orgao_clean'], errors='ignore', inplace=True)

    if uf_filtro and 'uf' in filtered_df.columns:
        filtered_df = filtered_df[filtered_df['uf'].str.upper() == uf_filtro.upper()]
    if orgao_filtro and 'orgao' in filtered_df.columns:
        filtered_df = filtered_df[filtered_df['orgao'].astype(str).str.upper() == orgao_filtro.upper()]

    return filtered_df
