# app.py - AnuncIA (versão inicial)
import streamlit as st
import pyrebase4 as pyrebase
import firebase_admin
from firebase_admin import credentials, firestore
import openai

# -----------------------------
# Configurações iniciais
# -----------------------------
# Lê as chaves do Streamlit Secrets
FIREBASE_CONFIG = st.secrets["FIREBASE_CONFIG"]
ADMIN_CRED_JSON = st.secrets["FIREBASE_ADMIN_CREDENTIAL_JSON"]
OPENAI_KEY = st.secrets.get("OPENAI_API_KEY")

# Inicializa Firebase
firebase = pyrebase.initialize_app(eval(FIREBASE_CONFIG))
auth = firebase.auth()

# Inicializa Firebase Admin
cred = credentials.Certificate(eval(ADMIN_CRED_JSON))
try:
    firebase_admin.initialize_app(cred)
except ValueError:
    pass  # já inicializado
db = firestore.client()

# Inicializa OpenAI
if OPENAI_KEY:
    openai.api_key = OPENAI_KEY

# -----------------------------
# Funções principais
# -----------------------------

def registrar_usuario(email, senha):
    try:
        auth.create_user_with_email_and_password(email, senha)
        st.success("Usuário registrado! Verifique seu e-mail.")
    except Exception as e:
        st.error(f"Erro ao registrar: {e}")

def login_usuario(email, senha):
    try:
        user = auth.sign_in_with_email_and_password(email, senha)
        st.session_state['user'] = user
        st.success("Login realizado!")
        return True
    except Exception as e:
        st.error(f"Erro ao logar: {e}")
        return False

def gerar_anuncio(descricao_produto):
    prompt = f"Gere um anúncio profissional para: {descricao_produto}"
    if OPENAI_KEY:
        response = openai.Completion.create(
            engine="text-davinci-003",
            prompt=prompt,
            max_tokens=200
        )
        return response.choices[0].text.strip()
    else:
        return f"[IA desligada] Seu anúncio: {descricao_produto}"

def verificar_limite(user_email):
    doc_ref = db.collection("usuarios").document(user_email)
    doc = doc_ref.get()
    if doc.exists:
        dados = doc.to_dict()
        return dados.get("anuncios_usados", 0)
    else:
        doc_ref.set({"anuncios_usados": 0})
        return 0

def incrementar_anuncio(user_email):
    doc_ref = db.collection("usuarios").document(user_email)
    doc_ref.update({"anuncios_usados": firestore.Increment(1)})

# -----------------------------
# Interface Streamlit
# -----------------------------

st.title("🧠 AnuncIA — Gerador de Anúncios Profissionais")

if 'user' not in st.session_state:
    st.subheader("Login / Registro")
    email = st.text_input("E-mail")
    senha = st.text_input("Senha", type="password")
    if st.button("Registrar"):
        registrar_usuario(email, senha)
    if st.button("Login"):
        if login_usuario(email, senha):
            st.experimental_rerun()
else:
    user_email = st.session_state['user']['email']
    limite_usado = verificar_limite(user_email)
    FREE_LIMIT = int(st.secrets.get("DEFAULT_FREE_LIMIT", 3))

    st.subheader(f"Bem-vindo(a), {user_email}!")
    st.write(f"Anúncios usados: {limite_usado}/{FREE_LIMIT}")

    if limite_usado >= FREE_LIMIT:
        st.warning("Você atingiu o limite de anúncios grátis. Faça upgrade para continuar.")
    else:
        descricao = st.text_area("Descrição do produto")
        if st.button("Gerar Anúncio"):
            anuncio = gerar_anuncio(descricao)
            st.success("Anúncio gerado com sucesso!")
            st.write(anuncio)
            incrementar_anuncio(user_email)

    if st.button("Logout"):
        del st.session_state['user']
        st.experimental_rerun()

