from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import gspread
from google.oauth2.service_account import Credentials

# --- 0) Conexão com Firebase ---
import firebase_admin
from firebase_admin import credentials, firestore

cred = credentials.Certificate("serviceAccountKey.json")  # sua chave JSON do Firebase
firebase_admin.initialize_app(cred)
db = firestore.client()
print("Conexão com Firebase feita!")

# --- 1) Conectar com o Google Sheets ---
scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

creds = Credentials.from_service_account_file("credenciais.json", scopes=scopes)
client = gspread.authorize(creds)

spreadsheet = client.open("PlanilhaTeste")
sheet = spreadsheet.sheet1

usuario_da_planilha = sheet.cell(1, 1).value
senha_da_planilha = sheet.cell(1, 2).value

# --- 2) Selenium ---
driver = webdriver.Chrome()

try:
    driver.get("http://quotes.toscrape.com/login")
    wait = WebDriverWait(driver, 10)

    usuario_input = wait.until(EC.presence_of_element_located((By.ID, "username")))
    senha_input = driver.find_element(By.ID, "password")
    botao_login = driver.find_element(By.CSS_SELECTOR, 'input[type="submit"]')

    # Envia dados da planilha
    usuario_input.send_keys(usuario_da_planilha)
    senha_input.send_keys(senha_da_planilha)
    botao_login.click()

    # Espera e extrai dados após login
    painel = wait.until(EC.presence_of_element_located((By.CLASS_NAME, "quote")))
    time.sleep(1)

    quote = driver.find_element(By.CLASS_NAME, "text").text
    author = driver.find_element(By.CLASS_NAME, "author").text

    print("Primeira citação encontrada:")
    print(f"{quote} — {author}")

    # --- 3) Salvar no Firebase ---
    db.collection("quotes").add({
        "usuario": usuario_da_planilha,
        "quote": quote,
        "author": author
    })
    print("Dados salvos no Firebase com sucesso!")

finally:
    time.sleep(2)
    driver.quit()
