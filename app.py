import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore, auth
import openai
import json

# -----------------------------
# Configurações Iniciais
# -----------------------------
st.title("🧠 AnuncIA — Gerador de Anúncios Profissionais")

# Lê os dados do arquivo secrets.toml
try:
    FIREBASE_CONFIG = st.secrets["FIREBASE_ADMIN_CREDENTIAL_JSON"]
    OPENAI_KEY = st.secrets.get("OPENAI_API_KEY")
except Exception as e:
    st.error(f"Erro ao ler secrets: {e}")
    st.stop()

# Inicializa Firebase
if not firebase_admin._apps:
    try:
        cred = credentials.Certificate(dict(FIREBASE_CONFIG))
        firebase_admin.initialize_app(cred)
        st.write("✅ Firebase inicializado com sucesso.")
    except Exception as e:
        st.error(f"Erro ao inicializar Firebase: {e}")

# Conecta ao Firestore
try:
    db = firestore.client()
except Exception as e:
    st.error(f"Erro ao conectar ao Firestore: {e}")
    st.stop()

# Inicializa OpenAI
if OPENAI_KEY:
    openai.api_key = OPENAI_KEY

# -----------------------------
# Funções principais
# -----------------------------
def registrar_usuario(email, senha):
    try:
        user = auth.create_user(email=email, password=senha)
        db.collection("usuarios").document(email).set({
            "anuncios_usados": 0
        })
        st.success("Usuário registrado com sucesso!")
    except Exception as e:
        st.error(f"Erro ao registrar: {e}")

def login_usuario(email, senha):
    doc = db.collection("usuarios").document(email).get()
    if doc.exists:
        st.session_state['user_email'] = email
        return True
    else:
        st.error("Usuário não encontrado. Registre-se primeiro.")
        return False

def gerar_anuncio(descricao_produto):
    prompt = f"Gere um anúncio profissional e persuasivo para o seguinte produto: {descricao_produto}"
    if OPENAI_KEY:
        try:
            response = openai.Completion.create(
                engine="text-davinci-003",
                prompt=prompt,
                max_tokens=200
            )
            return response.choices[0].text.strip()
        except Exception as e:
            return f"Erro ao gerar anúncio: {e}"
    else:
        return f"[IA desligada] Seu anúncio: {descricao_produto}"

def verificar_limite(email):
    doc = db.collection("usuarios").document(email).get()
    if doc.exists:
        return doc.to_dict().get("anuncios_usados", 0)
    else:
        db.collection("usuarios").document(email).set({"anuncios_usados": 0})
        return 0

def incrementar_anuncio(email):
    db.collection("usuarios").document(email).update({
        "anuncios_usados": firestore.Increment(1)
    })

# -----------------------------
# Interface Streamlit
# -----------------------------
if 'user_email' not in st.session_state:
    st.subheader("Login / Registro")
    email = st.text_input("E-mail")
    senha = st.text_input("Senha", type="password")

    if st.button("Registrar"):
        registrar_usuario(email, senha)

    if st.button("Login"):
        if login_usuario(email, senha):
            st.experimental_rerun()
else:
    email = st.session_state['user_email']
    limite_usado = verificar_limite(email)
    FREE_LIMIT = int(st.secrets.get("DEFAULT_FREE_LIMIT", 3))

    st.subheader(f"Bem-vindo(a), {email}!")
    st.write(f"Anúncios usados: {limite_usado}/{FREE_LIMIT}")

    if limite_usado >= FREE_LIMIT:
        st.warning("Você atingiu o limite de anúncios grátis. Faça upgrade para continuar.")
    else:
        descricao = st.text_area("Descreva seu produto ou serviço:")
        if st.button("Gerar Anúncio"):
            anuncio = gerar_anuncio(descricao)
            st.success("Anúncio gerado com sucesso!")
            st.write(anuncio)
            incrementar_anuncio(email)

    if st.button("Logout"):
        del st.session_state['user_email']
        st.experimental_rerun()
