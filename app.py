import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore, auth
import openai
import json

# -----------------------------
# CONFIGURAÇÕES INICIAIS
# -----------------------------

# 🔹 Pega as chaves do Streamlit Secrets
FIREBASE_CONFIG = st.secrets["FIREBASE_ADMIN_CREDENTIAL_JSON"]
OPENAI_KEY = st.secrets.get("OPENAI_API_KEY")
DEFAULT_FREE_LIMIT = int(st.secrets.get("DEFAULT_FREE_LIMIT", 3))

# 🔹 Inicializa o Firebase apenas uma vez
if not firebase_admin._apps:
    try:
        # Converte a seção TOML em um dicionário JSON
        cred = credentials.Certificate(json.loads(json.dumps(FIREBASE_CONFIG)))
        firebase_admin.initialize_app(cred)
        st.success("Firebase inicializado com sucesso!")
    except Exception as e:
        st.error(f"Erro ao inicializar Firebase: {e}")

# 🔹 Conecta ao Firestore
try:
    db = firestore.client()
except Exception as e:
    st.error(f"Erro ao conectar ao Firestore: {e}")

# 🔹 Inicializa a API da OpenAI
if OPENAI_KEY:
    openai.api_key = OPENAI_KEY


# -----------------------------
# FUNÇÕES
# -----------------------------

def registrar_usuario(email, senha):
    """Cria um novo usuário no Firebase Auth e registra no Firestore."""
    try:
        user = auth.create_user(email=email, password=senha)
        db.collection("usuarios").document(email).set({
            "anuncios_usados": 0
        })
        st.success("✅ Usuário registrado com sucesso!")
    except Exception as e:
        st.error(f"Erro ao registrar: {e}")


def login_usuario(email, senha):
    """Simula login: apenas verifica se o usuário existe no Firestore."""
    doc = db.collection("usuarios").document(email).get()
    if doc.exists:
        st.session_state['user_email'] = email
        return True
    else:
        st.error("Usuário não encontrado. Registre-se primeiro.")
        return False


def gerar_anuncio(descricao_produto):
    """Gera texto de anúncio com IA."""
    prompt = f"Gere um anúncio profissional e persuasivo para o seguinte produto: {descricao_produto}"
    try:
        if OPENAI_KEY:
            response = openai.Completion.create(
                engine="text-davinci-003",
                prompt=prompt,
                max_tokens=200
            )
            return response.choices[0].text.strip()
        else:
            return f"[IA desligada] Seu anúncio: {descricao_produto}"
    except Exception as e:
        return f"Erro ao gerar anúncio: {e}"


def verificar_limite(email):
    """Verifica o número de anúncios já usados."""
    doc = db.collection("usuarios").document(email).get()
    if doc.exists:
        return doc.to_dict().get("anuncios_usados", 0)
    else:
        db.collection("usuarios").document(email).set({"anuncios_usados": 0})
        return 0


def incrementar_anuncio(email):
    """Incrementa o contador de anúncios usados."""
    try:
        db.collection("usuarios").document(email).update({
            "anuncios_usados": firestore.Increment(1)
        })
    except Exception as e:
        st.error(f"Erro ao atualizar limite: {e}")


# -----------------------------
# INTERFACE STREAMLIT
# -----------------------------
st.title("🧠 AnuncIA — Gerador de Anúncios Profissionais")

if 'user_email' not in st.session_state:
    st.subheader("🔐 Login / Registro")
    email = st.text_input("E-mail")
    senha = st.text_input("Senha", type="password")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Registrar"):
            registrar_usuario(email, senha)
    with col2:
        if st.button("Login"):
            if login_usuario(email, senha):
                st.experimental_rerun()

else:
    email = st.session_state['user_email']
    limite_usado = verificar_limite(email)

    st.subheader(f"👋 Bem-vindo(a), {email}")
    st.write(f"Anúncios usados: **{limite_usado}/{DEFAULT_FREE_LIMIT}**")

    if limite_usado >= DEFAULT_FREE_LIMIT:
        st.warning("⚠️ Você atingiu o limite de anúncios grátis. Faça upgrade para continuar.")
    else:
        descricao = st.text_area("📝 Descreva seu produto ou serviço:")
        if st.button("🚀 Gerar Anúncio"):
            anuncio = gerar_anuncio(descricao)
            st.success("✅ Anúncio gerado com sucesso!")
            st.write(anuncio)
            incrementar_anuncio(email)

    if st.button("🚪 Logout"):
        del st.session_state['user_email']
        st.experimental_rerun()
