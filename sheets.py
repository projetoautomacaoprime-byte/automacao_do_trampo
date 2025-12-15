import pandas as pd
import gspread
import logging
import os
import json
import base64
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)


def read_sheet_to_dataframe(sheet_url: str, sheet_name: str) -> pd.DataFrame:
    """
    Lê uma planilha do Google Sheets e retorna como DataFrame.
    Mantém comportamento original: em qualquer erro → DataFrame vazio.
    Usa credenciais do deploy (Base64).
    """
    if not sheet_url or not sheet_name:
        return pd.DataFrame()

    # ---------------------------------------
    # 🔒 Proteção SSRF: validação da URL
    # ---------------------------------------
    allowed_prefix = "https://docs.google.com/spreadsheets/"

    if not sheet_url.startswith(allowed_prefix):
        logger.error(f"URL de planilha bloqueada (SSRF): {sheet_url}")
        return pd.DataFrame()  # mantém comportamento original (falha silenciosa)

    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

        # 🔹 Usa variável Base64 do deploy
        creds_b64 = os.getenv("FIREBASE_CREDENTIALS_BASE64")
        if not creds_b64:
            raise ValueError("Variável de ambiente FIREBASE_CREDENTIALS_BASE64 não encontrada")

        creds_json = base64.b64decode(creds_b64).decode("utf-8")
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)

        sheet = client.open_by_url(sheet_url)
        worksheet = sheet.worksheet(sheet_name)
        data = worksheet.get_all_records()
        return pd.DataFrame(data)

    except Exception as e:
        logger.error(f"Erro ao ler Google Sheets ({sheet_name}): {e}")
        return pd.DataFrame()


def parse_brl(valor):
    """
    Converte valores no formato BR para float.
    Comportamento original mantido: erro → retorna 0.0
    """
    try:
        if isinstance(valor, str):
            valor = valor.replace(".", "").replace(",", ".")
        return float(valor)
    except Exception as e:
        logger.warning(f"Erro ao converter número BRL ({valor}): {e}")
        return 0.0


def calcular_valor_financiado(row):
    """
    Calcula valor financiado usando parcela, prazo e taxa fixa.
    Mantém exatamente a fórmula e retornos originais.
    """
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
        logger.error(f"Erro ao calcular saldo: {e}")
        return 0.0


def format_brl(valor):
    """
    Formata número float para padrão BRL.
    Mantém comportamento original: erro → retorna valor original.
    """
    try:
        return (
            f"{valor:,.2f}"
            .replace(",", "X")
            .replace(".", ",")
            .replace("X", ".")
        )
    except Exception as e:
        logger.warning(f"Erro ao formatar BRL ({valor}): {e}")
        return valor
