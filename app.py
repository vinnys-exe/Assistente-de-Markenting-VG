import streamlit as st
import os
import time
import re
# CORREÇÃO 1: Importar o módulo principal 'firebase_admin' para usar '_apps'
import firebase_admin 
from firebase_admin import credentials, initialize_app, firestore
from google.cloud.firestore import Client
from typing import Dict, Any


# --- Configurações & Chaves (Puxadas do secrets.toml) ---
# A chave OpenAI é apenas um placeholder de demonstração.
OPENAI_KEY = st.secrets.get("OPENAI_API_KEY", None) 
FREE_LIMIT = int(st.secrets.get("DEFAULT_FREE_LIMIT", 3)) # Garante que o limite é um inteiro

# ----------------------------------------------------
#               CONFIGURAÇÃO DO FIREBASE
# ----------------------------------------------------

# Verifica se o Firebase já foi inicializado na sessão
if 'db' not in st.session_state:
    st.session_state['db'] = None
    
    try:
        # 1. Obter as credenciais do secrets.toml
        firebase_config = st.secrets.get("firebase", None)
        
        if not firebase_config:
            st.warning("⚠️ Configuração [firebase] não encontrada. O app funcionará no MODO OFFLINE/SIMULAÇÃO.")
        else:
            # Corrige a private_key (substitui \\n por \n)
            private_key = firebase_config.get("private_key", "").replace("\\n", "\n")
            
            # Cria o objeto de credenciais de serviço
            service_account_info = {
                k: v for k, v in firebase_config.items() if k not in ["private_key"]
            }
            service_account_info["private_key"] = private_key

            # 2. Inicializar o Firebase Admin SDK (só se não estiver inicializado)
            # CORREÇÃO 2: Usa 'firebase_admin._apps' em vez de 'firestore._apps'
            if not firebase_admin._apps:
                cred = credentials.Certificate(service_account_info)
                # Inicializa o app com um nome para evitar o erro de re-inicialização
                initialize_app(cred, name="anuncia_app")
            
            # 3. Conectar ao Firestore
            # Tenta usar o client associado ao app inicializado
            db_client = firestore.client(app=firebase_admin.get_app("anuncia_app"))
            st.session_state["db"] = db_client # Armazena o cliente no estado da sessão
            st.success("✅ Conexão Firebase/Firestore estabelecida.")

    except Exception as e:
        # Nota: Deixa este erro genérico, pois pode ser problema de Private Key ou Regra de Segurança.
        st.error(f"❌ Erro ao inicializar Firebase: {e}")
        st.info("A contagem de anúncios usará um sistema de contagem SIMULADA.")
        st.session_state["db"] = "SIMULATED" # Sinaliza que está em modo de simulação


# ----------------------------------------------------
#           FUNÇÕES DE CONTROLE DE USO (FIREBASE/SIMULADO)
# ----------------------------------------------------

def get_user_data(user_id: str) -> Dict[str, Any]:
    """Busca os dados do usuário no Firestore (ou simula a busca)."""
    if st.session_state.get("db") and st.session_state["db"] != "SIMULATED":
        # Modo Firebase
        user_ref = st.session_state["db"].collection("users").document(user_id)
        doc = user_ref.get()
        if doc.exists:
            return doc.to_dict()
    # Modo Simulado (Fallback)
    return st.session_state.get(f"user_{user_id}", {"ads_generated": 0, "plan": "free"})

def increment_ads_count(user_id: str):
    """Incrementa a contagem de anúncios (Firebase ou Simulado)."""
    user_data = get_user_data(user_id)
    new_count = user_data.get("ads_generated", 0) + 1
    
    if st.session_state.get("db") and st.session_state["db"] != "SIMULATED":
        # Modo Firebase
        user_ref = st.session_state["db"].collection("users").document(user_id)
        # Atualiza o Firestore
        user_ref.set({
            "ads_generated": new_count,
            "last_used": firestore.SERVER_TIMESTAMP,
            "plan": user_data.get("plan", "free")
        }, merge=True)
    else:
        # Modo Simulado (apenas para a sessão Streamlit atual)
        user_data["ads_generated"] = new_count
        st.session_state[f"user_{user_id}"] = user_data 

    return new_count

# ----------------------------------------------------
#           IMPLEMENTAÇÃO DE LOGIN SIMPLIFICADO
# ----------------------------------------------------

if 'logged_in_user_id' not in st.session_state:
    st.session_state['logged_in_user_id'] = None

st.set_page_config(page_title="AnuncIA - Gerador de Anúncios", layout="centered")
st.title("✨ AnuncIA — O Gerador de Anúncios Inteligente")

# Área de Login/Identificação na Sidebar
with st.sidebar:
    st.title("🔒 Login/Acesso")
    email_input = st.text_input("Seu E-mail (Para controle de uso)", 
                                placeholder="seu@email.com")
    
    if st.button("Acessar / Simular Login"):
        if "@" in email_input:
            # 1. Aplica a lógica anti-abuso de e-mail alias (ignora '+alias')
            clean_email = email_input
            if "+" in email_input:
                local_part, domain = email_input.split("@")
                local_part = local_part.split("+")[0]
                clean_email = f"{local_part}@{domain}"
            
            # 2. Cria um ID limpo para usar como Document ID no Firestore
            # Subistitui caracteres que podem dar problema no Firebase ID
            user_doc_id = re.sub(r'[^\w\-@\.]', '_', clean_email)
            
            st.session_state['logged_in_user_id'] = user_doc_id
            st.success(f"Logado como: {clean_email}")
        else:
            st.error("Por favor, insira um e-mail válido.")

# ----------------------------------------------------
#                   INTERFACE PRINCIPAL
# ----------------------------------------------------

if not st.session_state['logged_in_user_id']:
    st.info("Insira seu e-mail na barra lateral para começar seu teste grátis.")
else:
    # --- Verificação de Limite e Exibição de Status ---
    user_id = st.session_state['logged_in_user_id']
    user_data = get_user_data(user_id)
    ads_used = user_data.get("ads_generated", 0)

    st.markdown("---")
    st.markdown(f"**Status:** Você usou **{ads_used}** de **{FREE_LIMIT}** anúncios grátis.")
    st.markdown("---")


    if ads_used >= FREE_LIMIT:
        st.warning("🚫 **Limite gratuito atingido!** Faça upgrade para liberar o uso ilimitado.")
        st.markdown(f"**[🚀 Clique aqui para ver nossos planos (R${19.90}/mês)](LINK_PARA_PAGAMENTO)**")
    
    else:
        # --- Formulário de Geração de Anúncios ---
        with st.form("input_form"):
            st.subheader("🛠️ Crie Seu Anúncio Profissional")
            
            # Campos do formulário...
            product_type = st.selectbox("Tipo de produto", ["Ambos (Físico e Digital)", "Produto físico", "Produto digital"])
            description = st.text_area("Descrição do produto e o que você quer vender:", max_chars=800)
            
            # Botão de submissão
            submitted = st.form_submit_button("Gerar Anúncio com IA")

        if submitted:
            # Lógica de processamento e chamada de API (simulação)
            with st.spinner("🧠 A IA está gerando sua estratégia e copy..."):
                time.sleep(2) # Simula o tempo de API
                
                # SIMULAÇÃO DE GERAÇÃO
                simulated_title = f"✨ Venda {product_type}: {description[:40]}..."
                
                # 1. Incrementa a contagem no Firebase/Simulação
                new_count = increment_ads_count(user_id)
                
                # 2. Exibição do resultado (simulação)
                st.success(f"✅ Anúncio Gerado com Sucesso! (Grátis restante: {max(0, FREE_LIMIT - new_count)})")
                
                st.markdown(f"### 🎯 Título Sugerido: {simulated_title}")
                st.markdown(f"**Texto:** Sua descrição foi transformada em um texto persuasivo para {product_type}. Use CTAs fortes e gatilhos mentais!")
                st.markdown(f"**Grupos Recomendados:** Marketing Digital BR, Vendas {product_type}, Ofertas Online.")
                st.markdown("---")

    # Botão de debug (útil para ver se o Firebase está funcionando)
    if st.session_state["db"] != "SIMULATED":
        if st.button("Ver Meus Dados no Firestore (Debug)"):
            st.json(user_data)
            
if st.session_state.get("db") and st.session_state["db"] != "SIMULATED":
    st.success("✅ Firebase está funcionando e autenticado corretamente.")
else:
    st.warning("⚠️ Firebase em modo simulado (sem conexão ativa).")
