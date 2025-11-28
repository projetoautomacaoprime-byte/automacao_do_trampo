import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

def read_sheet_to_dataframe(sheet_url: str, sheet_name: str, creds_path: str = "credenciais.json") -> pd.DataFrame:
    if not sheet_url or not sheet_name:
        return pd.DataFrame()
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
