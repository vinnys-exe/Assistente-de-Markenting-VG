import streamlit as st
import os
import time
import re
import requests 
import json     
import firebase_admin 
from firebase_admin import credentials, initialize_app, firestore 
from google.cloud.firestore import Client
from typing import Dict, Any, Optional

# --- Configurações & Chaves (Puxadas do secrets.toml) ---
GEMINI_API_KEY = st.secrets.get("OPENAI_API_KEY", None) 
FREE_LIMIT = int(st.secrets.get("DEFAULT_FREE_LIMIT", 3))

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
MODEL_NAME = "gemini-2.5-flash" 

# ----------------------------------------------------
#               CONFIGURAÇÃO DO FIREBASE
# ----------------------------------------------------
# (O bloco de inicialização do Firebase é mantido inalterado)
if 'db' not in st.session_state:
    st.session_state['db'] = None
    
    try:
        firebase_config = st.secrets.get("firebase", None)
        
        if not firebase_config:
            st.warning("⚠️ Configuração [firebase] não encontrada. O app funcionará no MODO OFFLINE/SIMULAÇÃO.")
        else:
            private_key = firebase_config.get("private_key", "").replace("\\n", "\n")
            
            service_account_info = {
                k: v for k, v in firebase_config.items() if k not in ["private_key"]
            }
            service_account_info["private_key"] = private_key

            if not firebase_admin._apps: 
                cred = credentials.Certificate(service_account_info)
                initialize_app(cred, name="anuncia_app")
            
            db_client = firestore.client(app=firebase_admin.get_app("anuncia_app"))
            st.session_state["db"] = db_client 
            st.success("✅ Conexão Firebase/Firestore estabelecida.")

    except Exception as e:
        st.error(f"❌ Erro ao inicializar Firebase: {e}")
        st.info("A contagem de anúncios usará um sistema de contagem SIMULADA.")
        st.session_state["db"] = "SIMULATED"


# ----------------------------------------------------
#               FUNÇÃO DE CHAMADA À IA OTIMIZADA
# ----------------------------------------------------

def call_gemini_api(product_type: str, description: str, tone: str) -> Optional[Dict[str, str]]:
    """
    Chama a API do Gemini com um prompt estruturado para gerar o anúncio.
    Adiciona o parâmetro 'tone' para adaptar a voz do copywriter.
    """
    if not GEMINI_API_KEY:
        st.error("Chave da API não configurada. Verifique o secrets.toml.")
        return None
    
    # SYSTEM PROMPT: Otimizado para conversão e gatilhos mentais
    system_prompt = (
        "Você é o Copywriter-Chefe da agência 'AnuncIA'. Sua missão é gerar um anúncio que converte como fogo. "
        "A copy deve ser estruturada seguindo o framework AIDA (Atenção, Interesse, Desejo, Ação), "
        "com uso de gatilhos mentais de Escassez e Prova Social. "
        "O idioma de saída DEVE ser Português Brasileiro (PT-BR), com emojis e linguagem persuasiva. "
        "Sua resposta DEVE ser um objeto JSON válido, contendo obrigatoriamente 4 chaves: "
        "'titulo_gancho', 'copy_aida', 'call_to_action', e 'segmentacao_e_ideias'. "
        "Não inclua qualquer outro texto antes ou depois do JSON."
    )
    
    # Prompt do Usuário: INJETANDO O TOM DE VOZ
    user_prompt = (
        f"Gere um anúncio persuasivo de alta conversão. "
        f"Tipo de Produto: {product_type}. "
        f"Descrição Detalhada e Foco: '{description}'. "
        f"O TOM DE VOZ OBRIGATÓRIO deve ser: {tone}. "
        f"A copy_aida deve ter no máximo 1500 caracteres, ser focada nos benefícios (não nas características) e incluir um elemento de urgência ou escassez."
    )

    # Configuração de Geração (Schema de saída JSON)
    generation_config = {
        "responseMimeType": "application/json",
        "responseSchema": {
            "type": "OBJECT",
            "properties": {
                "titulo_gancho": {"type": "STRING", "description": "Um título curto e agressivo (gancho) para capturar a atenção (max 80 caracteres)."},
                "copy_aida": {"type": "STRING", "description": "O corpo do texto principal do anúncio, seguindo AIDA (Atenção, Interesse, Desejo, Ação)."},
                "call_to_action": {"type": "STRING", "description": "Uma chamada para ação direta, com senso de urgência (ex: 'Últimas 24h! Garanta sua vaga')."},
                "segmentacao_e_ideias": {"type": "STRING", "description": "Sugestões de público-alvo (Facebook Ads) e uma breve ideia de imagem/vídeo para o anúncio."}
            },
            "required": ["titulo_gancho", "copy_aida", "call_to_action", "segmentacao_e_ideias"]
        }
    }

    payload = {
        "contents": [{"parts": [{"text": user_prompt}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "config": generation_config
    }

    headers = {'Content-Type': 'application/json'}
    
    try:
        response = requests.post(f"{API_URL}?key={GEMINI_API_KEY}", headers=headers, data=json.dumps(payload))
        response.raise_for_status() 
        
        result = response.json()
        
        json_string = result['candidates'][0]['content']['parts'][0]['text']
        
        return json.loads(json_string)
        
    except requests.exceptions.HTTPError as e:
        st.error(f"Erro HTTP: Verifique se sua chave da API é válida e se o modelo está acessível.")
        st.info(f"Detalhes da Resposta: {response.text[:200]}...")
    except (KeyError, json.JSONDecodeError) as e:
        st.error(f"Erro ao processar a resposta da IA. O formato JSON esperado pode ter sido violado.")
        st.code(f"Resposta bruta: {json_string}", language='json')
    except Exception as e:
        st.error(f"Erro inesperado na chamada da API: {e}")
        
    return None


# ----------------------------------------------------
# FUNÇÕES DE CONTROLE DE USO (FIREBASE/SIMULADO)
# ----------------------------------------------------
# (Mantidas inalteradas)
def get_user_data(user_id: str) -> Dict[str, Any]:
    """Busca os dados do usuário no Firestore (ou simula a busca)."""
    if st.session_state.get("db") and st.session_state["db"] != "SIMULATED":
        user_ref = st.session_state["db"].collection("users").document(user_id)
        doc = user_ref.get()
        if doc.exists:
            return doc.to_dict()
    return st.session_state.get(f"user_{user_id}", {"ads_generated": 0, "plan": "free"})

def increment_ads_count(user_id: str):
    """Incrementa a contagem de anúncios (Firebase ou Simulado)."""
    user_data = get_user_data(user_id)
    new_count = user_data.get("ads_generated", 0) + 1
    
    if st.session_state.get("db") and st.session_state["db"] != "SIMULATED":
        user_ref = st.session_state["db"].collection("users").document(user_id)
        user_ref.set({
            "ads_generated": new_count,
            "last_used": firestore.SERVER_TIMESTAMP,
            "plan": user_data.get("plan", "free")
        }, merge=True)
    else:
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

with st.sidebar:
    st.title("🔒 Login/Acesso")
    email_input = st.text_input("Seu E-mail (Para controle de uso)", 
                                placeholder="seu@email.com")
    
    if st.button("Acessar / Simular Login"):
        if "@" in email_input:
            clean_email = email_input
            if "+" in email_input:
                local_part, domain = email_input.split("@")
                local_part = local_part.split("+")[0]
                clean_email = f"{local_part}@{domain}"
            
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
        # Link de pagamento agora vai para a nova seção de monetização
        st.markdown(f"**[🚀 Clique aqui para ver nossos planos e fazer upgrade!](LINK_PARA_PAGAMENTO)**")
    
    else:
        # --- Formulário de Geração de Anúncios ---
        with st.form("input_form"):
            st.subheader("🛠️ Crie Seu Anúncio Profissional")
            
            col_a, col_b = st.columns(2)
            
            with col_a:
                product_type = st.selectbox("Tipo de produto", 
                                            ["Ambos (Físico e Digital)", "Produto físico", "Produto digital"])
            with col_b:
                # NOVO CAMPO: Tom de Voz
                tone = st.selectbox("Tom de Voz da Copy", 
                                    ["Persuasivo/Vendedor", "Divertido/Casual", "Formal/Técnico", "Agressivo/Urgente"])

            description = st.text_area("Descrição do produto e o que você quer vender (máx. 800 caracteres):", max_chars=800)
            
            submitted = st.form_submit_button("Gerar Anúncio com IA")

        if submitted:
            if not description:
                st.error("Por favor, insira uma descrição do produto para gerar o anúncio.")
            else:
                with st.spinner("🧠 A IA está gerando sua estratégia e copy..."):
                    
                    # Chama a função real da API, passando o tom
                    ad_content = call_gemini_api(product_type, description, tone)

                    if ad_content:
                        # 1. Incrementa a contagem no Firebase
                        new_count = increment_ads_count(user_id)
                        
                        # 2. Exibição do resultado REAL da IA
                        st.success(f"✅ Anúncio Gerado com Sucesso! (Grátis restante: {max(0, FREE_LIMIT - new_count)})")
                        st.markdown("---")
                        
                        # Exibição Otimizada (UI/UX)
                        
                        st.markdown(f"## 💥 {ad_content.get('titulo_gancho', 'Título Gerado')}")
                        st.caption(f"Tom de voz aplicado: **{tone}**")
                        st.markdown("---")

                        # Displaying the main copy
                        st.markdown("### ✍️ Corpo do Anúncio (AIDA)")
                        st.code(ad_content.get('copy_aida', 'Erro na copy'), language='markdown')

                        # Displaying CTA and Segmentation side-by-side
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            st.markdown("### 📢 Chamada para Ação (CTA)")
                            st.code(ad_content.get('call_to_action', 'Erro no CTA'), language='markdown')
                        
                        with col2:
                            st.markdown("### 🧠 Estratégia e Segmentação")
                            st.info(ad_content.get('segmentacao_e_ideias', 'Erro na segmentação'))
                        
                        st.markdown("---")
                        
                    else:
                        st.error("Falha ao gerar o anúncio. Tente novamente ou verifique as chaves da API.")

    # Botão de debug
    if st.session_state["db"] != "SIMULATED":
        if st.button("Ver Meus Dados no Firestore (Debug)"):
            st.json(user_data)
            
if st.session_state.get("db") and st.session_state["db"] != "SIMULATED":
    st.success("✅ Firebase está funcionando e autenticado corretamente.")
else:
    st.warning("⚠️ Firebase em modo simulado (sem conexão ativa).")
