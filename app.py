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
# URL SIMULADA DE PAGAMENTO (SUBSTITUA PELO SEU LINK DO PAGSEGURO/STRIPE/CARRINHO.IO)
PAYMENT_URL = "https://checkout.seusite.com.br/planos-anuncia-ia"

# ----------------------------------------------------
#               CONFIGURAÇÃO DO FIREBASE
# ----------------------------------------------------
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
#               FUNÇÕES DE UPGRADE E MONETIZAÇÃO
# ----------------------------------------------------

def display_upgrade_page():
    """Exibe o painel de upgrade quando o limite grátis é atingido."""
    st.markdown("## 🛑 Limite Gratuito Atingido!")
    st.markdown("Parece que você já usou **todos os seus 3 anúncios grátis**.")
    st.warning("Seu sucesso em gerar copies de alta conversão está travado. Não pare agora!")

    st.markdown("---")
    
    st.markdown("### 🚀 Escolha Seu Plano e Libere o Potencial")
    
    # --- Cartões de Planos ---
    col1, col2 = st.columns(2)
    
    # Plano Starter (Foco no preço)
    with col1:
        st.markdown(
            f"""
            <div style='border: 2px solid #2ecc71; padding: 15px; border-radius: 10px; text-align: center; background-color: #f0fff0;'>
                <h3>Plano STARTER</h3>
                <h1>R$ 19,90<sub style='font-size: 50%;'>/mês</sub></h1>
                <p><strong>Perfeito para iniciantes e pequenos negócios.</strong></p>
                <ul>
                    <li>✅ 50 Anúncios/Mês</li>
                    <li>✅ Acesso a Todos os Tons de Voz</li>
                    <li>✅ Suporte por E-mail</li>
                </ul>
                <a href='{PAYMENT_URL}?plan=starter' target='_blank'>
                    <button style='background-color: #2ecc71; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; margin-top: 10px;'>
                        Contratar Starter
                    </button>
                </a>
            </div>
            """, 
            unsafe_allow_html=True
        )

    # Plano Pro (Foco no valor e Ilimitado)
    with col2:
        st.markdown(
            f"""
            <div style='border: 3px solid #3498db; padding: 15px; border-radius: 10px; text-align: center; background-color: #eaf6ff;'>
                <h3>Plano PRO (Recomendado)</h3>
                <h1>R$ 39,90<sub style='font-size: 50%;'>/mês</sub></h1>
                <p><strong>Para agências e empreendedores de alto volume.</strong></p>
                <ul>
                    <li>🌟 ANÚNCIOS ILIMITADOS</li>
                    <li>✅ Criação de Segmentos Avançada</li>
                    <li>✅ Suporte VIP Prioritário</li>
                </ul>
                <a href='{PAYMENT_URL}?plan=pro' target='_blank'>
                    <button style='background-color: #3498db; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; margin-top: 10px;'>
                        Contratar PRO
                    </button>
                </a>
            </div>
            """, 
            unsafe_allow_html=True
        )
    
    st.markdown("---")
    st.info(f"Ao contratar, use o e-mail **{st.session_state['logged_in_user_id']}** para ativar seu plano.")
    st.markdown("Se você já pagou, recarregue a página em 5 minutos.")


# ----------------------------------------------------
#               FUNÇÃO DE CHAMADA À IA OTIMIZADA
# ----------------------------------------------------
# (Mantida inalterada da última iteração, exceto a URL base da API que não deve ter a chave no URL, pois a chave está no cabeçalho)
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
    
    # Passando a chave no header de autorização (Método preferido)
    headers = {
        'Content-Type': 'application/json',
        'x-api-key': GEMINI_API_KEY 
    }
    
    try:
        # A URL não precisa mais do ?key={GEMINI_API_KEY}
        response = requests.post(API_URL, headers=headers, data=json.dumps(payload))
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
    user_plan = user_data.get("plan", "free")

    st.markdown("---")
    # Mostrar status de forma dinâmica
    if user_plan == "free":
        st.markdown(f"**Status:** Você usou **{ads_used}** de **{FREE_LIMIT}** anúncios grátis.")
    else:
        st.markdown(f"**Status:** Seu plano **{user_plan.upper()}** está ativo! Uso Ilimitado.")
    st.markdown("---")


    # MUDANÇA PRINCIPAL: Lógica de Exibição
    # Se o plano for "free" E o uso for maior ou igual ao limite, mostra a página de upgrade
    if user_plan == "free" and ads_used >= FREE_LIMIT:
        display_upgrade_page() # Chama a nova função de vendas
    
    else:
        # --- Formulário de Geração de Anúncios ---
        with st.form("input_form"):
            st.subheader("🛠️ Crie Seu Anúncio Profissional")
            
            col_a, col_b = st.columns(2)
            
            with col_a:
                product_type = st.selectbox("Tipo de produto", 
                                            ["Ambos (Físico e Digital)", "Produto físico", "Produto digital"])
            with col_b:
                tone = st.selectbox("Tom de Voz da Copy", 
                                    ["Persuasivo/Vendedor", "Divertido/Casual", "Formal/Técnico", "Agressivo/Urgente"])

            description = st.text_area("Descrição do produto e o que você quer vender (máx. 800 caracteres):", max_chars=800)
            
            submitted = st.form_submit_button("Gerar Anúncio com IA")

        if submitted:
            if not description:
                st.error("Por favor, insira uma descrição do produto para gerar o anúncio.")
            else:
                with st.spinner("🧠 A IA está gerando sua estratégia e copy..."):
                    
                    ad_content = call_gemini_api(product_type, description, tone)

                    if ad_content:
                        # 1. Incrementa a contagem no Firebase (APENAS se for plano free)
                        if user_plan == "free":
                            new_count = increment_ads_count(user_id)
                        else:
                            new_count = ads_used # Não incrementa se for pago
                        
                        # 2. Exibição do resultado REAL da IA
                        st.success(f"✅ Anúncio Gerado com Sucesso!")
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
