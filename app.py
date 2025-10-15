import streamlit as st
import os
import time
import requests
import json
import firebase_admin
from firebase_admin import credentials, initialize_app, firestore
from google.cloud.firestore import Client
from typing import Dict, Any, Union
import re 
import base64

# --- CONFIGURAÇÕES DO APLICATIVO E CSS CUSTOMIZADO ---
st.set_page_config(page_title="✨ AnuncIA - Gerador de Anúncios", layout="centered")

# Injeção de CSS para layout e estética
st.markdown("""
<style>
/* Remove padding top e laterais do Streamlit */
.block-container {
    padding-top: 2rem;
    padding-left: 1rem;
    padding-right: 1rem;
    padding-bottom: 2rem;
}

/* Customiza cor de botões e widgets principais */
div.stButton > button:first-child, .stMultiSelect, .stSelectbox {
    border-radius: 10px;
    border: 1px solid #52b2ff; 
}

/* Cor de fundo para o sidebar */
[data-testid="stSidebar"] {
    background-color: #f7f7f7;
    border-right: 1px solid #eee;
}

/* Destaque para as caixas de resultado (Shadow) */
.stCode, .stTextarea > div, [data-testid="stExpander"] {
    border-radius: 12px;
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.05);
    background-color: #ffffff;
    padding: 15px;
}
.stCode:hover, .stTextarea:hover {
    box-shadow: 0 6px 12px rgba(0, 0, 0, 0.1);
    transition: all 0.3s ease-in-out;
}
</style>
""", unsafe_allow_html=True)


# --- CONFIGURAÇÕES & CHAVES (Puxadas do secrets.toml) ---
OPENAI_KEY = st.secrets.get("OPENAI_API_KEY", "")
FREE_LIMIT = int(st.secrets.get("DEFAULT_FREE_LIMIT", 3))
DEVELOPER_EMAIL = st.secrets.get("DEVELOPER_EMAIL", "")

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
            private_key = firebase_config.get("private_key", "").replace("\\n", "\n")
            
            service_account_info = {
                k: v for k, v in firebase_config.items() if k not in ["private_key"]
            }
            service_account_info["private_key"] = private_key

            # 2. Inicializar o Firebase Admin SDK (só se não estiver inicializado)
            if not firebase_admin._apps: 
                cred = credentials.Certificate(service_account_info)
                initialize_app(cred, name="anuncia_app")
            
            # 3. Conectar ao Firestore
            db_client = firestore.client(app=firebase_admin.get_app("anuncia_app"))
            st.session_state["db"] = db_client 
            # st.success("✅ Conexão Firebase/Firestore estabelecida.") # Removido para limpar a tela
            
    except Exception as e:
        # st.error(f"❌ Erro ao inicializar Firebase: {e}") # Comentei para evitar poluir o app
        st.info("A contagem de anúncios usará um sistema de contagem SIMULADA.")
        st.session_state["db"] = "SIMULATED" 
        
# ----------------------------------------------------
#       FUNÇÕES DE CONTROLE DE USO (FIREBASE/SIMULADO)
# ----------------------------------------------------

def get_user_data(user_id: str) -> Dict[str, Any]:
    """Busca os dados do usuário no Firestore (ou simula a busca), verificando o acesso dev."""
    
    # 1. VERIFICAÇÃO DE DESENVOLVEDOR (WHITELIST)
    dev_email_clean = DEVELOPER_EMAIL.lower()
    
    # O user_id é o e-mail limpo e formatado como document ID
    if user_id.lower() == re.sub(r'[^\w\-@\.]', '_', dev_email_clean):
        # Retorna o plano 'pro' imediatamente, ignorando o Firebase
        return {"ads_generated": 0, "plan": "pro"} 
    
    # 2. MODO FIREBASE
    if st.session_state.get("db") and st.session_state["db"] != "SIMULATED":
        user_ref = st.session_state["db"].collection("users").document(user_id)
        doc = user_ref.get()
        if doc.exists:
            return doc.to_dict()
    
    # 3. MODO SIMULADO (Fallback)
    return st.session_state.get(f"user_{user_id}", {"ads_generated": 0, "plan": "free"})

def increment_ads_count(user_id: str, current_plan: str) -> int:
    """Incrementa a contagem de anúncios SOMENTE se o plano for 'free'."""
    if current_plan != "free":
        return 0 
        
    user_data = get_user_data(user_id)
    new_count = user_data.get("ads_generated", 0) + 1
    
    if st.session_state.get("db") and st.session_state["db"] != "SIMULATED":
        # Modo Firebase
        user_ref = st.session_state["db"].collection("users").document(user_id)
        user_ref.set({
            "ads_generated": new_count,
            "last_used": firestore.SERVER_TIMESTAMP,
            "plan": user_data.get("plan", "free")
        }, merge=True)
    else:
        # Modo Simulado
        user_data["ads_generated"] = new_count
        st.session_state[f"user_{user_id}"] = user_data
        
    return new_count

# ----------------------------------------------------
#             FUNÇÕES DE CHAMADA DA API (GEMINI/OPENAI)
# ----------------------------------------------------

def call_gemini_api(user_description: str, product_type: str, tone: str, is_pro_user: bool, needs_video: bool) -> Union[Dict, str]:
    """Chama a API (simulando Gemini/OpenAI) para gerar copy em formato JSON."""
    
    api_key = OPENAI_KEY
    if not api_key:
        return {"error": "Chave de API (OPENAI_API_KEY) não configurada."}

    # 1. CONSTRUÇÃO DO PROMPT E SCHEMA (Dinâmico para o Plano PRO)
    
    # Instrução base (AIDA + Tom)
    system_instruction = f"""
    Você é um Copywriter de elite, especializado em Marketing Digital e Vendas Diretas. 
    Sua missão é gerar um anúncio altamente persuasivo e focado em conversão.
    
    Instruções de Tom: O tom de voz deve ser {tone}.
    Instruções de Estrutura: Use o Framework AIDA (Atenção, Interesse, Desejo, Ação). 
    A copy deve ser concisa, focar no benefício do cliente e incluir gatilhos de escassez/urgência/prova social.
    
    O produto é um {product_type}.
    """
    
    # Instruções e Schema para Saída (JSON)
    output_schema = {
        "type": "OBJECT",
        "properties": {
            "titulo_gancho": {"type": "STRING", "description": "Um título chocante e que gere Atenção imediata, com no máximo 10 palavras."},
            "copy_aida": {"type": "STRING", "description": "O texto principal (body copy) persuasivo, seguindo a estrutura AIDA (Atenção, Interesse, Desejo e Ação)."},
            "chamada_para_acao": {"type": "STRING", "description": "Uma Chamada para Ação (CTA) clara e urgente."},
            "segmentacao_e_ideias": {"type": "STRING", "description": "Sugestões de 3 personas ou grupos de interesse para segmentação do anúncio."}
        },
        "propertyOrdering": ["titulo_gancho", "copy_aida", "chamada_para_acao", "segmentacao_e_ideias"]
    }

    # ADICIONA RECURSOS PRO (Roteiro de Vídeo)
    if is_pro_user and needs_video:
        system_instruction += "\n\n⚠️ INSTRUÇÃO PRO: Além da copy, você DEVE gerar um roteiro de vídeo de 30 segundos e um gancho inicial (hook) de 3 segundos para Reels/TikTok, com foco em parar o feed."
        output_schema['properties']['gancho_video'] = {"type": "STRING", "description": "Um HOOK (gancho) de 3 segundos que interrompe a rolagem do feed (ex: 'Não use isso para perder peso!')."}
        output_schema['properties']['roteiro_basico'] = {"type": "STRING", "description": "Um roteiro conciso de 30 segundos em 3 etapas (Problema, Solução/Benefício, CTA)."}
        output_schema['propertyOrdering'].extend(['gancho_video', 'roteiro_basico'])


    # 2. CONSTRUÇÃO DO PAYLOAD
    payload = {
        "contents": [{"parts": [{"text": user_description}]}],
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "config": {
            "responseMimeType": "application/json",
            "responseSchema": output_schema,
            "temperature": 0.7 
        }
    }

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent?key={api_key}"
    
    # 3. CHAMADA HTTP (COM BACKOFF PARA RESILIÊNCIA)
    for i in range(3): # Tenta até 3 vezes
        try:
            response = requests.post(url, headers={'Content-Type': 'application/json'}, data=json.dumps(payload))
            response.raise_for_status() # Lança exceção para status 4xx/5xx
            
            result = response.json()
            
            # Tenta parsear o JSON de saída do modelo
            json_text = result.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '{}')
            
            return json.loads(json_text)
        
        except requests.exceptions.RequestException as e:
            if i < 2:
                time.sleep(2 ** i) # Espera exponencial
                continue
            return {"error": f"Erro de conexão com a API: {e}"}
        except json.JSONDecodeError:
            # Se a IA não retornar JSON válido, pede para tentar de novo ou retorna erro
            return {"error": "A IA não conseguiu retornar um JSON válido. Por favor, tente novamente."}
        except Exception as e:
            return {"error": f"Erro inesperado na chamada da API: {e}"}
            
    return {"error": "Não foi possível conectar após várias tentativas."}

# ----------------------------------------------------
#              FUNÇÕES DE EXIBIÇÃO DA UI
# ----------------------------------------------------

def display_upgrade_page(user_id: str):
    """Exibe a página de vendas/upgrade quando o limite é atingido."""
    st.markdown("---")
    st.subheader("🚀 Destrave o Poder Total da AnuncIA!")
    st.warning("🚨 **Limite Gratuito Atingido!** Você utilizou 3 de 3 anúncios grátis.")
    
    st.markdown("Chegou a hora de levar sua copy e seus resultados para o próximo nível.")
    
    col1, col2 = st.columns(2)
    
    # Plano Grátis (Comparação)
    with col1:
        st.markdown(
            f"""
            <div style="background-color: #f0f0f0; padding: 20px; border-radius: 12px; height: 100%; border: 1px solid #ddd;">
                <h4 style="color: #666;">Plano Gratuito</h4>
                <p><strong>R$ 0,00</strong></p>
                <ul style="list-style-type: '❌ '; padding-left: 20px;">
                    <li>Apenas {FREE_LIMIT} Anúncios/Sessão</li>
                    <li>Sem Roteiros de Vídeo (Reels/TikTok)</li>
                    <li>Uso Básico</li>
                </ul>
            </div>
            """, unsafe_allow_html=True
        )
    
    # Plano PRO (A Venda)
    with col2:
        st.markdown(
            f"""
            <div style="background-color: #e0f2ff; padding: 20px; border-radius: 12px; height: 100%; border: 2px solid #52b2ff;">
                <h4 style="color: #52b2ff;">Plano PRO 💎</h4>
                <p><strong>R$ 19,90/mês</strong></p>
                <ul style="list-style-type: '✅ '; padding-left: 20px;">
                    <li>Anúncios Ilimitados (Sem Restrições)</li>
                    <li>Geração de **Roteiros de Vídeo** (PRO Feature)</li>
                    <li>Todos os Tons de Voz</li>
                    <li>Suporte Prioritário</li>
                </ul>
                <div style="text-align: center; margin-top: 15px;">
                    <a href="LINK_PARA_PAGAMENTO" target="_blank" style="text-decoration: none;">
                        <button style="background-color: #52b2ff; color: white; border: none; padding: 10px 20px; border-radius: 8px; font-size: 16px; cursor: pointer;">
                            ATIVAR AGORA →
                        </button>
                    </a>
                </div>
            </div>
            """, unsafe_allow_html=True
        )
    
    st.markdown(f"---")
    st.info(f"Seu e-mail de acesso é: **{user_id}**")


def display_result_box(title: str, content: str, key: str):
    """Exibe o conteúdo em um text_area com botão de cópia nativo."""
    st.markdown(f"**{title}**")
    st.text_area(
        label=title,
        value=content,
        height=None,
        key=key,
        label_visibility="collapsed"
    )

# ----------------------------------------------------
#               IMPLEMENTAÇÃO DE LOGIN SIMPLIFICADO
# ----------------------------------------------------

if 'logged_in_user_id' not in st.session_state:
    st.session_state['logged_in_user_id'] = None

st.title("✨ AnuncIA — O Gerador de Anúncios Inteligente")

# Área de Login/Identificação na Sidebar
with st.sidebar:
    st.markdown("## 🔒 Login/Acesso")
    email_input = st.text_input("Seu E-mail (Para controle de uso)", 
                                placeholder="seu@email.com")
    
    if st.button("Acessar / Simular Login", use_container_width=True):
        if "@" in email_input:
            # 1. Aplica a lógica anti-abuso de e-mail alias (ignora '+alias')
            clean_email = email_input
            if "+" in email_input:
                local_part, domain = email_input.split("@")
                local_part = local_part.split("+")[0]
                clean_email = f"{local_part}@{domain}"
            
            # 2. Cria um ID limpo para usar como Document ID no Firestore
            user_doc_id = re.sub(r'[^\w\-@\.]', '_', clean_email)
            
            st.session_state['logged_in_user_id'] = user_doc_id
            st.success(f"Acesso Liberado: {clean_email}")
        else:
            st.error("Por favor, insira um e-mail válido.")

# ----------------------------------------------------
#                  INTERFACE PRINCIPAL
# ----------------------------------------------------

if not st.session_state['logged_in_user_id']:
    st.info("Insira seu e-mail na barra lateral para começar seu teste grátis.")
else:
    # --- Verificação de Limite e Exibição de Status ---
    user_id = st.session_state['logged_in_user_id']
    user_data = get_user_data(user_id)
    ads_used = user_data.get("ads_generated", 0)
    user_plan = user_data.get("plan", "free")
    
    is_pro_user = (user_plan == "pro")

    st.markdown("---")
    if is_pro_user:
        status_text = "⭐ Acesso de Desenvolvedor (PRO Ilimitado)" if user_id.lower() == re.sub(r'[^\w\-@\.]', '_', DEVELOPER_EMAIL.lower()) else "💎 Plano PRO (Uso Ilimitado)"
        st.markdown(f"**Status:** {status_text}")
    else:
        st.markdown(f"**Status:** Você usou **{ads_used}** de **{FREE_LIMIT}** anúncios grátis.")
    st.markdown("---")


    if not is_pro_user and ads_used >= FREE_LIMIT:
        # Usuário Grátis atingiu o limite
        display_upgrade_page(user_id)
        
    else:
        # --- Formulário de Geração de Anúncios ---
        with st.form("input_form"):
            st.subheader("🛠️ Crie Seu Anúncio Profissional")
            
            col_tone, col_type = st.columns(2)
            
            with col_type:
                product_type = st.selectbox(
                    "Qual é o tipo de produto?", 
                    ["Ambos (Físico e Digital)", "Produto físico", "Produto digital"]
                )
            
            with col_tone:
                 tone = st.selectbox(
                    "Qual Tom de Voz usar?", 
                    ["Vendedor e Agressivo", "Divertido e Informal", "Profissional e Formal", "Inspirador e Motivacional"]
                )
            
            description = st.text_area(
                "Descreva seu produto (máximo 800 caracteres):", 
                placeholder="Ex: 'Um curso online para iniciantes que ensina a investir na bolsa com pouco dinheiro, usando estratégias de baixo risco e zero jargão técnico.'", 
                max_chars=800
            )
            
            needs_video = st.checkbox(
                "🚀 Gerar Roteiro de Vídeo (Reels/TikTok) - Exclusivo Plano PRO", 
                value=False,
                disabled=(not is_pro_user)
            )
            
            # Botão de submissão
            submitted = st.form_submit_button("🔥 Gerar Copy com a IA")

        if submitted:
            if not description:
                st.error("Por favor, forneça uma descrição detalhada do produto para a IA.")
            elif needs_video and not is_pro_user:
                st.error("⚠️ **Recurso PRO:** A Geração de Roteiro de Vídeo é exclusiva do Plano PRO. Por favor, desmarque a opção ou faça o upgrade.")
            elif not OPENAI_KEY:
                st.error("⚠️ Erro de Configuração: A chave de API (OPENAI_API_KEY) não está definida no secrets.toml.")
            else:
                with st.spinner("🧠 A IA está gerando sua estratégia e copy..."):
                    
                    # 1. Chamada REAL à API
                    api_result = call_gemini_api(description, product_type, tone, is_pro_user, needs_video)
                    
                    if "error" in api_result:
                        st.error(f"❌ Erro na Geração da Copy: {api_result['error']}")
                        st.info("A contagem de uso NÃO foi debitada. Tente novamente.")
                    else:
                        # 2. Incrementa a contagem no Firebase/Simulação
                        new_count = increment_ads_count(user_id, user_plan)
                        
                        # 3. Exibição do resultado
                        st.success(f"✅ Copy Gerada com Sucesso! (Grátis restante: {max(0, FREE_LIMIT - new_count)})")
                        
                        st.markdown("---")
                        st.subheader("Resultado da Copy")
                        
                        # TÍTULO GANCHO
                        col_t, col_b = st.columns([0.8, 0.2])
                        with col_t:
                            st.markdown("#### 🎯 Título Gancho (Atenção)")
                        display_result_box("Título", api_result.get("titulo_gancho", "N/A"), "title_box")

                        # COPY AIDA
                        st.markdown("#### 📝 Copy Principal (Interesse, Desejo, Ação)")
                        display_result_box("Copy AIDA", api_result.get("copy_aida", "N/A"), "copy_box")

                        # CTA
                        st.markdown("#### 📢 Chamada para Ação (CTA)")
                        display_result_box("CTA", api_result.get("chamada_para_acao", "N/A"), "cta_box")
                        
                        # SEGMENTAÇÃO
                        st.markdown("#### 💡 Ideias de Segmentação")
                        display_result_box("Segmentação", api_result.get("segmentacao_e_ideias", "N/A"), "seg_box")
                        
                        
                        # ROTEIRO DE VÍDEO (EXCLUSIVO PRO)
                        if is_pro_user and needs_video:
                            st.markdown("---")
                            st.subheader("🎥 Roteiro PRO de Vídeo (Reels/TikTok)")
                            with st.expander("Clique para ver o Roteiro Completo"):
                                # GANCHO VÍDEO
                                st.markdown("##### Gancho (Hook) de 3 Segundos")
                                display_result_box("Gancho Video", api_result.get("gancho_video", "N/A"), "hook_box")
                                
                                # ROTEIRO BÁSICO
                                st.markdown("##### Roteiro Completo (30s)")
                                display_result_box("Roteiro", api_result.get("roteiro_basico", "N/A"), "roteiro_box")


# ----------------------------------------------------
#               DEBUG E STATUS FINAL
# ----------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.markdown("##### Status do Sistema")
if st.session_state.get("db") and st.session_state["db"] != "SIMULATED":
    st.sidebar.success("✅ Conexão Firebase OK")
elif st.session_state.get("db") == "SIMULATED":
    st.sidebar.warning("⚠️ Firebase: MODO SIMULADO")

if OPENAI_KEY:
    st.sidebar.success("✅ Chave de API OK")
else:
    st.sidebar.error("❌ Chave de API AUSENTE")
