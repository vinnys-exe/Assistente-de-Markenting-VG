import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore, auth
import openai
import json

# -----------------------------
# Configurações Iniciais
# -----------------------------
FIREBASE_CONFIG = dict(st.secrets["FIREBASE_ADMIN_CREDENTIAL_JSON"])
OPENAI_KEY = st.secrets.get("OPENAI_API_KEY")

# Inicializa Firebase
if not firebase_admin._apps:
    try:
        cred = credentials.Certificate(FIREBASE_CONFIG)
        firebase_admin.initialize_app(cred)
        st.success("✅ Firebase inicializado com sucesso!")
    except Exception as e:
        st.error(f"Erro ao inicializar Firebase: {e}")

# Conecta ao Firestore
try:
    db = firestore.client()
except Exception as e:
    st.error(f"Erro ao conectar ao Firestore: {e}")
    db = None

# Inicializa OpenAI
if OPENAI_KEY:
    openai.api_key = OPENAI_KEY
