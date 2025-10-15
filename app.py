import streamlit as st
import os
import time
import requests
import json
import firebase_admin
from firebase_admin import credentials, initialize_app, firestore
from firebase_admin import auth
from google.cloud.firestore import Client
from typing import Dict, Any, Union
import re
import base64

# --- CONFIGURAÇÕES DO APLICATIVO E CSS CUSTOMIZADO ---
st.set_page_config(page_title="✨ AnuncIA - Gerador de Estratégia de Marketing", layout="wide")

# --- CSS PROFISSIONAL V5.0 (MANTIDO) ---
st.markdown("""
<style>
/* 1. CONFIGURAÇÃO BASE GERAL */
body {
    font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    color: #333;
}
.block-container {
    padding-top: 2rem;
    padding-left: 1.5rem;
    padding-right: 1.5rem;
    padding-bottom: 2rem;
}

/* 2. SIDEBAR */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #ffffff, #e0f7fa);
    border-right: 1px solid #ddd;
    box-shadow: 2px 0 5px rgba(0, 0, 0, 0.05);
}

/* 3. TÍTULO PRINCIPAL (Branding) */
h1 {
    color: #007bbd;
    text-shadow: 1px 1px 3px rgba(0, 0, 0, 0.05);
    font-weight: 700;
}
h2, h3, h4 {
    color: #333;
    border-bottom: 1px solid #eee;
    padding-bottom: 5px;
}

/* 4. ESTILO DE CARTÃO E BORDAS */
[data-testid="stExpander"], [data-testid="stForm"], .stTextArea > div {
    border-radius: 12px;
    border: 1px solid #e0e0e0;
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.04);
    background-color: #ffffff;
    padding: 15px;
    transition: box-shadow 0.3s ease;
}

/* 5. WIDGETS E BOTÕES */
div.stButton > button:first-child {
    background-color: #00bcd4;
    color: white;
    border: none;
    border-radius: 8px;
    padding: 10px 20px;
    font-weight: bold;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
    transition: background-color 0.2s;
}
div.stButton > button:first-child:hover {
    background-color: #0097a7;
}

/* 6. BOTÕES DE UPGRADE (PRO) */
.pro-button a button {
    background-color: #ff5722 !important;
    color: white !important;
    border: none !important;
    padding: 10px 20px !important;
    border-radius: 8px !important;
    font-size: 16px !important;
    cursor: pointer !important;
    font-weight: bold;
    box-shadow: 0 4px 8px rgba(255, 87, 34, 0.3);
    transition: all 0.2s;
}
.pro-button a button:hover {
    background-color: #e64a19 !important;
    transform: translateY(-2px);
}
.plan-highlight {
    border: 3px solid #ff5722;
    background-color: #fff3e0;
    box-shadow: 0 6px 12px rgba(255, 87, 34, 0.2);
    transform: scale(1.02);
}
</style>
""", unsafe_allow_html=True)


# --- CONFIGURAÇÕES & CHAVES (Puxadas do secrets.toml) ---
GEMINI_KEY = st.secrets.get("gemini", {}).get("GEMINI_API_KEY", "")
FREE_LIMIT = int(st.secrets.get("app", {}).get("DEFAULT_FREE_LIMIT", 3))
DEVELOPER_EMAIL = st.secrets.get("app", {}).get("DEVELOPER_EMAIL", "seu-email-de-login-admin@exemplo.com")
DEVELOPER_EMAIL_CLEAN = re.sub(r'[^\w@\.\-]', '_', DEVELOPER_EMAIL.lower().strip().split('+')[0])

# ----------------------------------------------------
#               FUNÇÕES DE UTILIADE MULTIMODAL (NOVO)
# ----------------------------------------------------

def file_to_base64(uploaded_file):
    """Converte um objeto FileUploader do Streamlit para Base64."""
    if uploaded_file is not None:
        # A API Gemini aceita base64 para imagens in-line
        return base64.b64encode(uploaded_file.getvalue()).decode("utf-8")
    return None

def get_mime_type(uploaded_file):
    """Obtém o tipo MIME de um arquivo Streamlit uploaded_file."""
    if uploaded_file is not None:
        return uploaded_file.type
    return "text/plain" # Default/Fallback


# ----------------------------------------------------
#                CONFIGURAÇÃO DO FIREBASE (MANTIDO)
# ----------------------------------------------------

if 'db' not in st.session_state:
    st.session_state['db'] = None
    st.session_state['auth'] = None
    st.session_state['firebase_app'] = None
    st.session_state['logged_in_user_id'] = None
    st.session_state['logged_in_user_email'] = None


def initialize_firebase():
    """Tenta inicializar o Firebase Admin SDK ou obtém a instância existente."""
    APP_NAME = "anuncia_app_instance"
    
    try:
        app = firebase_admin.get_app(APP_NAME)
    except ValueError:
        try:
            firebase_config = st.secrets.get("firebase", None)
            
            if not firebase_config or not firebase_config.get("private_key"):
                st.info("A contagem de anúncios usará um sistema **SIMULADO**: Credenciais Firebase não encontradas.")
                return "SIMULATED", "SIMULATED", None
            
            private_key_raw = firebase_config.get("private_key", "")
            if "\\n" in private_key_raw:
                private_key = private_key_raw.replace("\\n", "\n")
            else:
                private_key = private_key_raw
            
            service_account_info = {
                k: v for k, v in firebase_config.items() if k not in ["private_key"]
            }
            service_account_info["private_key"] = private_key
            service_account_info["type"] = service_account_info.get("type", "service_account")

            cred = credentials.Certificate(service_account_info)
            app = initialize_app(cred, name=APP_NAME)
            
        except Exception as e:
            st.error(f"❌ Erro Crítico na Inicialização Firebase. Contagem SIMULADA: {e}")
            return "SIMULATED", "SIMULATED", None

    db_client = firestore.client(app=app)
    return db_client, auth, app

if st.session_state['db'] is None:
    st.session_state['db'], st.session_state['auth'], st.session_state['firebase_app'] = initialize_firebase()


# ----------------------------------------------------
#       FUNÇÕES DE CONTROLE DE USO E PLANO (MANTIDAS)
# ----------------------------------------------------

def clean_email_to_doc_id(email: str) -> str:
    """Limpa o e-mail para usar como Document ID e comparações."""
    clean_email = email.lower().strip()
    if "+" in clean_email:
        local_part, domain = clean_email.split("@")
        local_part = local_part.split("+")[0]
        clean_email = f"{local_part}@{domain}"
    
    user_doc_id = re.sub(r'[^\w@\.\-]', '_', clean_email)
    return clean_email

def get_user_data(user_id: str) -> Dict[str, Any]:
    """Busca os dados do usuário no Firestore, verificando o acesso dev."""
    
    # 1. VERIFICAÇÃO DE DESENVOLVEDOR (Plano PREMIUM forçado)
    if st.session_state.get('logged_in_user_email'):
        logged_email_clean = clean_email_to_doc_id(st.session_state['logged_in_user_email'])
        
        if logged_email_clean == clean_email_to_doc_id(DEVELOPER_EMAIL):
            # Se o e-mail for o Admin, força o plano PREMIUM (ilimitado/vitalício)
            return {"ads_generated": 0, "plan_tier": "premium"}
    
    # 2. MODO FIREBASE
    if st.session_state.get("db") and st.session_state["db"] != "SIMULATED":
        user_ref = st.session_state["db"].collection("users").document(user_id)
        doc = user_ref.get()
        if doc.exists:
            data = doc.to_dict()
            data['plan_tier'] = data.get('plan_tier', 'free')
            return data
    
    # 3. MODO SIMULADO (Fallback)
    data = st.session_state.get(f"user_{user_id}", {"ads_generated": 0, "plan_tier": "free"})
    return data

def increment_ads_count(user_id: str, current_plan_tier: str) -> int:
    """Incrementa a contagem de anúncios SOMENTE se o plano for 'free' e o limite não foi atingido."""
    
    if current_plan_tier != "free":
        return 0
        
    user_data = get_user_data(user_id)
    current_count = user_data.get("ads_generated", 0)
    
    if current_count >= FREE_LIMIT:
        return current_count
        
    new_count = current_count + 1
    
    if st.session_state.get("db") and st.session_state["db"] != "SIMULATED":
        user_ref = st.session_state["db"].collection("users").document(user_id)
        user_ref.set({
            "ads_generated": new_count,
            "last_used": firestore.SERVER_TIMESTAMP,
            "plan_tier": user_data.get("plan_tier", "free")
        }, merge=True)
    else:
        user_data["ads_generated"] = new_count
        st.session_state[f"user_{user_id}"] = user_data
        
    return new_count

def save_user_feedback(user_id: str, rating: str, input_prompt: str, ai_response: str):
    """Salva o feedback do usuário no Firestore para melhoria da IA."""
    
    if st.session_state.get("db") and st.session_state["db"] != "SIMULATED":
        feedback_ref = st.session_state["db"].collection("feedback").document()
        
        rating_map = {'Ruim 😭': 1, 'Mais ou Menos 🤔': 2, 'Bom 👍': 3, 'Ótimo! 🚀': 4}
        rating_score = rating_map.get(rating, 0)
        
        try:
            feedback_ref.set({
                "user_id": user_id,
                "rating_text": rating,
                "rating_score": rating_score,
                "input_prompt": input_prompt,
                "ai_response_json": ai_response, 
                "timestamp": firestore.SERVER_TIMESTAMP,
            })
            return True
        except Exception as e:
            st.error(f"Erro ao salvar feedback no Firestore: {e}")
            return False
            
    else:
        return True

def update_user_plan(target_email: str, new_plan: str) -> bool:
    """Função administrativa/Webhook Simulada para alterar o plano de um usuário."""
    clean_email = clean_email_to_doc_id(target_email)

    if st.session_state.get("db") and st.session_state["db"] != "SIMULATED":
        try:
            user_record = st.session_state['auth'].get_user_by_email(target_email, app=st.session_state['firebase_app'])
            user_id = user_record.uid
            
            user_ref = st.session_state["db"].collection("users").document(user_id)
            new_ads_count = 0 
            
            user_ref.set({
                "plan_tier": new_plan,
                "ads_generated": new_ads_count,
                "updated_at": firestore.SERVER_TIMESTAMP,
            }, merge=True)
            return True
            
        except firebase_admin._auth_utils.UserNotFoundError:
            st.error(f"❌ Erro: Usuário com e-mail '{target_email}' não encontrado no Firebase Auth.")
            return False
        except Exception as e:
            st.error(f"❌ Erro ao atualizar o plano no Firestore: {e}")
            return False
            
    else:
        st.info("Função de upgrade não executada. Firebase em modo SIMULADO.")
        return False

# --- FUNÇÕES DE AUTENTICAÇÃO (MANTIDAS) ---
def handle_login(email: str, password: str):
    # ... (implementação da função login - MANTIDA)
    try:
        if st.session_state['auth'] == "SIMULATED":
            st.error("Serviço de autenticação desativado.")
            return

        app_instance = st.session_state['firebase_app']
        user = st.session_state['auth'].get_user_by_email(email, app=app_instance)
        
        st.warning("Aviso: Login efetuado. Verificação de senha simulada (Admin SDK).")
        
        st.session_state['logged_in_user_email'] = email
        st.session_state['logged_in_user_id'] = user.uid
        st.success(f"Bem-vindo(a), {email}!")
        st.rerun()
        
    except firebase_admin._auth_utils.UserNotFoundError:
        st.error("Erro: Usuário não encontrado. Verifique seu e-mail e senha.")
    except Exception as e:
        st.error(f"Erro no login: {e}")

def handle_register(email: str, password: str, username: str, phone: str):
    # ... (implementação da função register - MANTIDA)
    try:
        if st.session_state['auth'] == "SIMULATED":
            st.error("Serviço de autenticação desativado.")
            return
            
        app_instance = st.session_state['firebase_app']

        user = st.session_state['auth'].create_user(
            email=email,
            password=password,
            display_name=username,
            app=app_instance
        )

        if st.session_state["db"] != "SIMULATED":
            st.session_state["db"].collection("users").document(user.uid).set({
                "email": email,
                "username": username,
                "phone": phone if phone else None,
                "created_at": firestore.SERVER_TIMESTAMP,
                "plan_tier": "free",
                "ads_generated": 0
            })
            
        st.session_state['logged_in_user_email'] = email
        st.session_state['logged_in_user_id'] = user.uid
        st.success(f"Conta criada com sucesso! Bem-vindo(a), {username}.")
        st.rerun()

    except firebase_admin._auth_utils.EmailAlreadyExistsError:
        st.error("Erro: Este e-mail já está em uso. Tente fazer o login.")
    except Exception as e:
        st.error(f"Erro no registro: {e}")

def handle_logout():
    """Desloga o usuário."""
    st.session_state['logged_in_user_email'] = None
    st.session_state['logged_in_user_id'] = None
    st.rerun()


# ----------------------------------------------------
#            FUNÇÕES DE CHAMADA DA API (ATUALIZADAS)
# ----------------------------------------------------

def call_gemini_api(user_description: str, product_type: str, tone: str, user_plan_tier: str, needs_video: bool, image_b64: str, mime_type: str) -> Union[Dict, str]:
    """Chama a API do Gemini para gerar copy multimodal em formato JSON."""
    
    api_key = GEMINI_KEY
    if not api_key:
        return {"error": "Chave de API (GEMINI_API_KEY) não configurada no secrets.toml."}

    is_premium_feature = (user_plan_tier == "premium" and needs_video)
    
    system_instruction = f"""
    Você é um Copywriter de elite, especializado em Marketing Digital e Vendas Diretas.
    Sua missão é gerar um anúncio altamente persuasivo, focado em conversão e otimizado para o esboço de texto/título fornecido pelo usuário.
    
    Instruções de Tom: O tom de voz deve ser {tone}.
    Instruções de Estrutura: Use o Framework AIDA (Atenção, Interesse, Desejo, Ação).
    A copy deve ser concisa, focar no benefício do cliente e incluir gatilhos de escassez/urgência/prova social.
    O produto é um {product_type}.
    
    Se uma imagem foi fornecida, analise-a para garantir que a copy seja contextualizada e maximize a conversão visual.
    """
    
    output_schema = {
        "type": "OBJECT",
        "properties": {
            "titulo_gancho": {"type": "STRING", "description": "Um título chocante e que gere Atenção imediata, com no máximo 10 palavras. Otimize o rascunho de título fornecido."},
            "copy_aida": {"type": "STRING", "description": "O texto principal (body copy) persuasivo, seguindo a estrutura AIDA. Corrige e melhora o esboço de texto fornecido pelo usuário, focando na imagem (se houver)."},
            "chamada_para_acao": {"type": "STRING", "description": "Uma Chamada para Ação (CTA) clara e urgente."},
            "segmentacao_e_ideias": {"type": "STRING", "description": "Sugestões de 3 personas ou grupos de interesse para segmentação do anúncio."}
        },
        "propertyOrdering": ["titulo_gancho", "copy_aida", "chamada_para_acao", "segmentacao_e_ideias"]
    }

    if is_premium_feature:
        system_instruction += "\n\n⚠️ INSTRUÇÃO PREMIUM: Gere um roteiro de vídeo de 30 segundos e um gancho inicial (hook) de 3 segundos para Reels/TikTok, com foco em parar o feed. Gere também uma sugestão de 3 títulos de campanhas para teste A/B no Meta Ads."
        output_schema['properties']['gancho_video'] = {"type": "STRING", "description": "Um HOOK (gancho) de 3 segundos que interrompe a rolagem do feed."}
        output_schema['properties']['roteiro_basico'] = {"type": "STRING", "description": "Um roteiro conciso de 30 segundos em 3 etapas (Problema, Solução/Benefício, CTA)."}
        output_schema['properties']['sugestao_campanhas'] = {"type": "STRING", "description": "3 títulos de campanhas agressivas para teste A/B."}
        output_schema['propertyOrdering'].extend(['gancho_video', 'roteiro_basico', 'sugestao_campanhas'])

    # CONSTRUÇÃO DO PAYLOAD (Multimodal)
    contents = []
    
    if image_b64 and mime_type.startswith("image/"):
        contents.append({
            "inlineData": {
                "data": image_b64,
                "mimeType": mime_type
            }
        })
    elif image_b64 and not mime_type.startswith("image/"):
         user_description += "\n\nAVISO: O arquivo fornecido não é uma imagem (MIME Type: " + mime_type + "). Analise apenas o texto."

    contents.append({"text": user_description})

    payload = {
        "contents": contents,
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "config": {
            "responseMimeType": "application/json",
            "responseSchema": output_schema,
            "temperature": 0.7
        }
    }

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent?key={api_key}"
    
    try:
        response = requests.post(url, headers={'Content-Type': 'application/json'}, data=json.dumps(payload))
        response.raise_for_status()
        
        result = response.json()
        json_text = result.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '{}')
        
        return json.loads(json_text)
    
    except Exception as e:
        return {"error": f"Erro na chamada da API de Copy: {e}"}


def call_gemini_strategy(ad_copy_json: Dict, user_objective: str, user_description: str, user_plan_tier: str) -> Union[Dict, str]:
    """Chama a API do Gemini para gerar a Estratégia de Canais e Público (NOVO)."""
    
    api_key = GEMINI_KEY
    if not api_key:
        return {"error": "Chave de API (GEMINI_API_KEY) não configurada."}

    copy_text = f"Título: {ad_copy_json.get('titulo_gancho', '')}\nCopy: {ad_copy_json.get('copy_aida', '')}\nCTA: {ad_copy_json.get('chamada_para_acao', '')}"
    
    system_instruction = f"""
    Você é um Estrategista de Mídia Digital e Growth. Sua função é analisar a copy gerada e o objetivo do cliente para criar um plano de divulgação completo.
    
    Objetivo do Cliente: **{user_objective}**.
    Tipo de Produto/Descrição: {user_description}
    A Copy de Anúncio é: "{copy_text}"
    
    Analise as principais plataformas (Meta Ads/Instagram, TikTok e Google Ads) e forneça a melhor estratégia.
    """

    output_schema = {
        "type": "OBJECT",
        "properties": {
            "plataforma_principal": {"type": "STRING", "description": "A plataforma principal mais indicada (Ex: TikTok, Instagram, Google Search) para o objetivo e porquê."},
            "publico_alvo_detalhado": {"type": "STRING", "description": "Uma descrição detalhada do público-alvo, incluindo interesses, dor principal e faixa etária."},
            "estrategia_de_horarios": {"type": "STRING", "description": "Sugestão dos 3 melhores horários de postagem ou veiculação de anúncios na plataforma principal, com breve justificativa."},
            "sugestoes_de_hashtags": {"type": "STRING", "description": "5-7 hashtags estratégicas e segmentadas para a divulgação."},
            "ideia_de_criativo": {"type": "STRING", "description": "Sugestão de uma ideia de imagem ou um esboço de texto complementar que maximize a conversão na plataforma principal."},
        },
        "propertyOrdering": ["plataforma_principal", "publico_alvo_detalhado", "estrategia_de_horarios", "sugestoes_de_hashtags", "ideia_de_criativo"]
    }

    if user_plan_tier == "premium":
        output_schema['properties']['roteiro_video_estrategico'] = {"type": "STRING", "description": "Um esboço de roteiro de vídeo estratégico (30 segundos) para a plataforma principal com foco em viralização/conversão."}
        output_schema['propertyOrdering'].append('roteiro_video_estrategico')
        
    payload = {
        "contents": [{"parts": [{"text": system_instruction}]}],
        "config": {
            "responseMimeType": "application/json",
            "responseSchema": output_schema,
            "temperature": 0.5
        }
    }

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent?key={api_key}"
    
    try:
        response = requests.post(url, headers={'Content-Type': 'application/json'}, data=json.dumps(payload))
        response.raise_for_status()
        
        result = response.json()
        json_text = result.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '{}')
        
        return json.loads(json_text)
    
    except Exception as e:
        return {"error": f"Erro na chamada da API de Estratégia: {e}"}

# ----------------------------------------------------
#            FUNÇÕES DE EXIBIÇÃO DA UI (MANTIDAS)
# ----------------------------------------------------

def display_upgrade_page(user_id: str):
    """Exibe a página de vendas/upgrade."""
    # ... (Mantenha a implementação da display_upgrade_page - MANTIDA)
    st.markdown("---")
    st.subheader("🚀 Escolha seu Plano e Venda Mais!")
    st.warning("🚨 **Limite Gratuito Atingido!** Para continuar, selecione um plano.")
    
    st.markdown("Invista em copy de alta conversão para dominar o mercado.")
    
    col1, col2, col3 = st.columns(3)
    
    # Plano 1: Gratuito (Referência)
    with col1:
        st.markdown(
            f"""
            <div class="plan-card" style="background-color: #f7f7f7; border: 1px solid #ddd;">
                <h4 style="color: #666; text-align: center;">Plano Grátis</h4>
                <div style="text-align: center;">
                    <p class="price-tag" style="color: #666;">R$ 0,00</p>
                    <p>por mês</p>
                </div>
                <ul style="list-style-type: '❌ '; padding-left: 20px; font-size: 0.95em;">
                    <li>Apenas {FREE_LIMIT} Anúncios/Sessão</li>
                    <li>Uso Básico (AIDA)</li>
                    <li><span style="color: #999;">Roteiros de Vídeo (Reels/TikTok)</span></li>
                    <li><span style="color: #999;">Sugestões de Campanhas A/B</span></li>
                </ul>
                <div style="text-align: center; margin-top: 15px;">
                    <button style="background-color: #ccc; color: white; border: none; padding: 10px 20px; border-radius: 8px; font-weight: bold;" disabled>
                        SELECIONADO
                    </button>
                </div>
            </div>
            """, unsafe_allow_html=True
        )
    
    # Plano 2: Essencial (Anúncios Ilimitados + AIDA/Segmentação)
    with col2:
        st.markdown(
            f"""
            <div class="plan-card" style="background-color: #e0f2ff; border: 2px solid #00bcd4;">
                <h4 style="color: #00bcd4; text-align: center;">Plano Essencial</h4>
                   <div style="text-align: center;">
                    <p class="price-tag" style="color: #00bcd4;">R$ 19,90</p>
                    <p>por mês</p>
                </div>
                <ul style="list-style-type: '✅ '; padding-left: 20px; font-size: 0.95em;">
                    <li>**Anúncios Ilimitados** (Sem Restrições)</li>
                    <li>Uso Completo (AIDA e Segmentação)</li>
                    <li><span style="color: #999;">❌ Roteiros de Vídeo (Exclusivo Premium)</span></li>
                    <li><span style="color: #999;">❌ Sugestões de Campanhas A/B (Exclusivo Premium)</span></li>
                </ul>
                <div style="text-align: center; margin-top: 15px;" class="pro-button">
                    <a href="LINK_PARA_PAGAMENTO_ESSENCIAL" target="_blank" style="text-decoration: none;">
                        <button style="background-color: #00bcd4 !important; box-shadow: 0 4px 8px rgba(0, 188, 212, 0.3);">
                            ASSINAR AGORA →
                        </button>
                    </a>
                </div>
            </div>
            """, unsafe_allow_html=True
        )

    # Plano 3: Premium (Tudo Ilimitado + Vídeo/A/B)
    with col3:
        st.markdown(
            f"""
            <div class="plan-card plan-highlight">
                <h4 style="color: #ff5722; text-align: center;">🏆 Plano Premium</h4>
                   <div style="text-align: center;">
                    <p class="strike-through">De R$ 49,90</p>
                    <p class="price-tag" style="color: #ff5722;">R$ 34,90</p>
                    <p>por mês **(Mais Vantajoso)**</p>
                </div>
                <ul style="list-style-type: '✅ '; padding-left: 20px; font-size: 0.95em;">
                    <li>**Anúncios Ilimitados** (Sem Restrições)</li>
                    <li>Uso Completo (AIDA e Segmentação)</li>
                    <li>Geração de **Roteiros de Vídeo**</li>
                    <li>Sugestões de **Campanhas A/B** (Exclusivo!)</li>
                </ul>
                <div style="text-align: center; margin-top: 15px;" class="pro-button">
                    <a href="LINK_PARA_PAGAMENTO_PREMIUM" target="_blank" style="text-decoration: none;">
                        <button>
                            EU QUERO O PREMIUM!
                        </button>
                    </a>
                </div>
            </div>
            """, unsafe_allow_html=True
        )
    
    st.markdown(f"---")
    st.info(f"Seu ID de acesso (UID) é: **{user_id}**")

def display_result_box(icon: str, title: str, content: str, key: str):
    """Exibe o conteúdo em um text_area com botão de cópia nativo e ícone."""
    with st.container(border=True):
        st.markdown(f"**{icon} {title}**")
        st.text_area(
            label=title,
            value=content,
            height=None,
            key=key,
            label_visibility="collapsed"
        )


# ----------------------------------------------------
#                INTERFACE PRINCIPAL
# ----------------------------------------------------

st.title("🤖 AnuncIA — Gerador de Copy de Alta Conversão & Estratégia")

# --- PAINEL DE LOGIN/REGISTRO NA SIDEBAR ---
with st.sidebar:
    st.markdown("---")
    if st.session_state['logged_in_user_id']:
        st.success(f"Logado como: {st.session_state['logged_in_user_email']}")
        st.button("Sair (Logout)", on_click=handle_logout, use_container_width=True)
    else:
        st.markdown("## 🔑 Acesso ao Sistema")
        login_mode = st.radio("Escolha a Ação:", ["Entrar", "Criar Conta"])

        if login_mode == "Entrar":
            with st.form("login_form"):
                st.subheader("Login")
                login_email = st.text_input("E-mail", key="l_email", placeholder="seu@email.com")
                login_password = st.text_input("Senha", type="password", key="l_password")
                
                if st.form_submit_button("Entrar no AnuncIA", use_container_width=True):
                    if login_email and login_password:
                        handle_login(login_email, login_password)
                    else:
                        st.error("Preencha e-mail e senha.")

        else: # Criar Conta
            with st.form("register_form"):
                st.subheader("Registro")
                reg_email = st.text_input("E-mail", key="r_email", placeholder="seu@email.com")
                reg_password = st.text_input("Senha", type="password", key="r_password", help="Mínimo 6 caracteres.")
                reg_username = st.text_input("Nome de Usuário", key="r_username", placeholder="Seu nome/nick")
                reg_phone = st.text_input("Telefone (Opcional)", key="r_phone", placeholder="(99) 99999-9999")
                
                if st.form_submit_button("Criar Minha Conta Grátis", use_container_width=True):
                    if reg_email and reg_password and reg_username:
                        if len(reg_password) >= 6:
                            handle_register(reg_email, reg_password, reg_username, reg_phone)
                        else:
                            st.error("A senha deve ter no mínimo 6 caracteres.")
                    else:
                        st.error("Preencha E-mail, Senha e Nome de Usuário.")

    # --- Variáveis de estado para checagem de plano ---
    user_id = st.session_state.get('logged_in_user_id')
    user_data = get_user_data(user_id) if user_id else {}
    user_plan_tier = user_data.get("plan_tier", "free")
    is_premium = (user_plan_tier == "premium")
    is_dev = st.session_state.get('logged_in_user_email') and clean_email_to_doc_id(st.session_state['logged_in_user_email']) == clean_email_to_doc_id(DEVELOPER_EMAIL)
    
    # Bloco de Upgrade para o Premium (aparece para Free e Essencial logado)
    if user_id and not is_premium and not is_dev:
        st.markdown("---")
        st.markdown("#### 🚀 Quer o Plano Premium?")
        st.markdown("""
        <div style="text-align: center;" class="pro-button">
            <a href="LINK_PARA_PAGAMENTO_PREMIUM" target="_blank">
                <button>
                    UPGRADE (Acesso Total)
                </button>
            </a>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("---")

    # NOVO: PAINEL DE CONTROLE DE PLANOS (Apenas para Desenvolvedor)
    if is_dev:
        st.markdown("---")
        with st.expander("🛠️ ADMIN: Controle de Planos (Webhook Simulado)"):
            st.info("Painel DEV: Simule a compra de um plano para o usuário logado.")
            
            target_email_admin = st.text_input("E-mail para Upgrade (Logado):", value=st.session_state['logged_in_user_email'])
            
            new_plan_admin = st.selectbox(
                "Novo Plano:",
                options=['free', 'essential', 'premium'],
                index=2 # Padrão para premium
            )
            
            if st.button(f"Aplicar Plano '{new_plan_admin.upper()}'", use_container_width=True):
                if target_email_admin:
                    success = update_user_plan(target_email_admin, new_plan_admin)
                    if success:
                        st.success(f"✅ Sucesso! Plano de {target_email_admin} alterado para {new_plan_admin.upper()}.")
                        if clean_email_to_doc_id(target_email_admin) == clean_email_to_doc_id(st.session_state['logged_in_user_email']):
                            st.rerun()
                    else:
                        st.error("Falha ao aplicar o plano. Verifique o console.")
                else:
                    st.error("E-mail do usuário não pode ser vazio.")


# --- CONTEÚDO PRINCIPAL ---

if not st.session_state['logged_in_user_id']:
    st.info("Por favor, faça **Login** ou **Crie sua Conta** na barra lateral para começar seu teste grátis.")
else:
    user_id = st.session_state['logged_in_user_id']
    user_data = get_user_data(user_id)
    ads_used = user_data.get("ads_generated", 0)
    user_plan_tier = user_data.get("plan_tier", "free")
    
    is_essential_or_premium = (user_plan_tier in ["essential", "premium"])
    is_premium = (user_plan_tier == "premium")
    is_dev = st.session_state.get('logged_in_user_email') and clean_email_to_doc_id(st.session_state['logged_in_user_email']) == clean_email_to_doc_id(DEVELOPER_EMAIL)
    
    st.markdown("---")
    
    tier_info_map = {
        "free": {"icon": "🆓", "color": "blue", "text": "Plano Grátis"},
        "essential": {"icon": "⚡", "color": "orange", "text": "Plano Essencial"},
        "premium": {"icon": "👑", "color": "green", "text": "Plano Premium"}
    }
    current_tier_info = tier_info_map.get(user_plan_tier, tier_info_map["free"])
        
    col_status, col_upgrade_link = st.columns([2, 1])

    with col_status:
        if is_dev:
            st.markdown(f"**Status:** ⭐ **Acesso de Desenvolvedor (PREMIUM Ilimitado)**")
        else:
            st.markdown(f"**Status:** {current_tier_info['icon']} **{current_tier_info['text']}**")
            
            if user_plan_tier == "free" and FREE_LIMIT < 1000:
                st.markdown(f"**Uso:** **{ads_used}** de **{FREE_LIMIT}** anúncios grátis.")
            else:
                st.markdown("Uso Ilimitado! 🎉")

    with col_upgrade_link:
        if user_plan_tier == "free" and not is_dev:
            st.markdown(f"""
                <div style="text-align: right; margin-top: 10px;" class="pro-button">
                    <a href="LINK_PARA_PAGAMENTO_PREMIUM" target="_blank" style="text-decoration: none;">
                        <button style="background-color: #ff5722 !important; font-size: 14px !important; padding: 8px 15px !important;">
                            FAÇA UPGRADE AGORA
                        </button>
                    </a>
                </div>
                """, unsafe_allow_html=True)
            
    st.markdown("---")
        
    if user_plan_tier == "free" and ads_used >= FREE_LIMIT and FREE_LIMIT < 1000 and not is_dev:
        display_upgrade_page(user_id)
        
    else:
        # --- Formulário de Geração de Anúncios (ATUALIZADO) ---
        with st.form("input_form"):
            st.subheader("🛠️ Crie Seu Anúncio Profissional")
            
            col_obj, col_file = st.columns([1, 1])

            with col_obj:
                user_objective = st.selectbox(
                    "🎯 Objetivo Principal da Campanha:",
                    ["Vendas / Conversão", "Geração de Leads (Cadastros)", "Tráfego para o Site", "Reconhecimento de Marca / Divulgação"]
                )

            with col_file:
                uploaded_file = st.file_uploader(
                    "🖼️ Faça o upload da Imagem Principal do Anúncio (Opcional):",
                    type=["png", "jpg", "jpeg", "webp"],
                    help="A IA irá analisar a imagem para criar uma copy mais contextualizada."
                )

            description = st.text_area(
                "Esboço de Títulos e Textos:",
                placeholder="""Forneça seus rascunhos de títulos, textos e/ou a descrição detalhada do produto (máximo 800 caracteres).
A IA irá CORRIGIR, REESCREVER e OTIMIZAR seu esboço para alta conversão.""",
                max_chars=800
            )
            
            with st.expander("⚙️ Configurações de Copy (Tom e Tipo de Produto)"):
                col_type, col_tone = st.columns(2)
                
                with col_type:
                    product_type = st.selectbox(
                        "Tipo de Produto:",
                        ["Ambos (Físico e Digital)", "Produto físico", "Produto digital"]
                    )
                
                with col_tone:
                      tone = st.selectbox(
                            "Tom de Voz:",
                            ["Vendedor e Agressivo", "Divertido e Informal", "Profissional e Formal", "Inspirador e Motivacional"]
                      )

            needs_video = st.checkbox(
                "🎬 Gerar Roteiro de Vídeo (Reels/TikTok) e Sugestão de Campanhas A/B - Exclusivo Plano Premium",
                value=is_premium and not is_dev,
                disabled=(not is_premium and not is_dev)
            )
            
            st.markdown("---")
            submitted = st.form_submit_button("🔥 Gerar Copy e Estratégia Completa", use_container_width=True)

        if submitted:
            if not description:
                st.error("Por favor, forneça um esboço de texto ou descrição detalhada do produto para a IA.")
            elif needs_video and not is_premium and not is_dev:
                st.error("⚠️ **Recurso Premium:** A Geração de Roteiro de Vídeo e Campanhas A/B é exclusiva do Plano Premium.")
            elif not GEMINI_KEY:
                st.error("⚠️ Erro de Configuração: A chave de API (GEMINI_API_KEY) não está definida.")
                
            else:
                image_b64 = file_to_base64(uploaded_file)
                mime_type = get_mime_type(uploaded_file)

                # --- 1. CHAMADA DA COPY (Multimodal) ---
                with st.spinner("🧠 A IA está analisando sua imagem/texto e gerando a Copy Otimizada..."):
                    api_copy_result = call_gemini_api(description, product_type, tone, user_plan_tier, needs_video, image_b64, mime_type)
                    
                if "error" in api_copy_result:
                    st.error(f"❌ Erro na Geração da Copy: {api_copy_result['error']}")
                    st.info("A contagem de uso **NÃO** foi debitada. Tente novamente.")
                    return

                # --- 2. CHAMADA DA ESTRATÉGIA ---
                with st.spinner("📈 Gerando a Estratégia de Canais e Público-Alvo..."):
                    api_strategy_result = call_gemini_strategy(api_copy_result, user_objective, description, user_plan_tier)

                if "error" in api_strategy_result:
                    st.warning(f"⚠️ Aviso: Falha parcial na Geração da Estratégia. O erro foi: {api_strategy_result['error']}. Exibindo resultados da Copy.")
                
                # 3. Incrementa a contagem
                new_count = increment_ads_count(user_id, user_plan_tier)
                
                # 4. Exibição do Resultado
                
                st.success("✅ Estratégia e Copy Ilimitadas Geradas com Sucesso!")
                if user_plan_tier == "free" and FREE_LIMIT < 1000:
                    st.info(f"Você tem mais **{max(0, FREE_LIMIT - new_count)}** usos grátis.")

                st.markdown("---")
                
                # --- EXIBIÇÃO DA COPY OTIMIZADA ---
                st.header("1. 📝 Copy Otimizada e Corrigida")
                
                if uploaded_file is not None:
                    st.image(uploaded_file, caption=f"Imagem analisada: {uploaded_file.name}", use_column_width=False, width=200)

                display_result_box("🎯", "Título Gancho (Atenção)", api_copy_result.get("titulo_gancho", "N/A"), "title_box")
                display_result_box("📝", "Copy Principal (AIDA) Otimizada", api_copy_result.get("copy_aida", "N/A"), "copy_box")
                display_result_box("📢", "Chamada para Ação (CTA)", api_copy_result.get("chamada_para_acao", "N/A"), "cta_box")


                # --- EXIBIÇÃO DA ESTRATÉGIA DE MARKETING ---
                st.header("2. 📈 Estratégia de Canais e Públicos")
                
                if "error" in api_strategy_result:
                     st.error("❌ A Estratégia de Marketing não pôde ser gerada devido a um erro. Exibindo apenas a segmentação de base.")
                     display_result_box("👤", "Ideias de Segmentação (Pessoas)", api_copy_result.get("segmentacao_e_ideias", "N/A"), "seg_box")
                else:
                    display_result_box("🌍", "Plataforma Principal Sugerida", api_strategy_result.get("plataforma_principal", "N/A"), "plataforma_box")
                    display_result_box("👥", "Público-Alvo Detalhado", api_strategy_result.get("publico_alvo_detalhado", "N/A"), "publico_box")
                    display_result_box("⏱️", "Estratégia de Horários de Postagem", api_strategy_result.get("estrategia_de_horarios", "N/A"), "horario_box")
                    display_result_box("🏷️", "Sugestões de Hashtags", api_strategy_result.get("sugestoes_de_hashtags", "N/A"), "hashtag_box")
                    display_result_box("💡", "Ideia de Criativo Complementar", api_strategy_result.get("ideia_de_criativo", "N/A"), "criativo_box")
                    display_result_box("👤", "Ideias de Segmentação (Pessoas)", api_copy_result.get("segmentacao_e_ideias", "N/A"), "seg_box")


                # --- EXIBIÇÃO DE RECURSOS PREMIUM ---
                if (is_premium and needs_video) or is_dev:
                    st.markdown("---")
                    st.header("💎 Conteúdo Premium")
                    
                    col_premium_a, col_premium_b = st.columns(2)
                    
                    with col_premium_a:
                        with st.expander("🎬 Roteiro de Vídeo Estratégico"):
                            # Puxa o roteiro estratégico da API de estratégia, se existir
                            if "roteiro_video_estrategico" in api_strategy_result:
                                display_result_box("🎞️", "Roteiro Estratégico (30s)", api_strategy_result.get("roteiro_video_estrategico", "N/A"), "roteiro_est_box")
                            # Puxa o roteiro básico da API de copy (fallback)
                            elif "roteiro_basico" in api_copy_result:
                                display_result_box("🎞️", "Roteiro Básico (30s)", api_copy_result.get("roteiro_basico", "N/A"), "roteiro_box_premium")
                            
                            display_result_box("🎬", "Gancho (Hook) de 3 Segundos", api_copy_result.get("gancho_video", "N/A"), "hook_box_premium")
                        
                    with col_premium_b:
                        with st.expander("📈 Sugestões de Campanhas A/B"):
                             display_result_box("📈", "Títulos de Campanhas para Teste A/B", api_copy_result.get("sugestao_campanhas", "N/A"), "camp_box")

                # --- SEÇÃO DE FEEDBACK ---
                st.markdown("---")
                        
                with st.form("feedback_form", clear_on_submit=True):
                    st.subheader("Avalie a Qualidade da Copy e Ajude a Melhorar a IA:")

                    col_rate, col_submit = st.columns([1, 4])
                    
                    with col_rate:
                        rating = st.select_slider(
                            'Gostou do Resultado?',
                            options=['Ruim 😭', 'Mais ou Menos 🤔', 'Bom 👍', 'Ótimo! 🚀'],
                            key="rating_slider_final"
                            )
                        
                    with col_submit:
                        st.write("")
                        feedback_submitted = st.form_submit_button("Enviar Feedback", use_container_width=True)

                    if feedback_submitted:
                        json_response_str = json.dumps({
                            "copy": api_copy_result, 
                            "strategy": api_strategy_result
                        }, ensure_ascii=False, indent=2)
                        success = save_user_feedback(user_id, rating, description, json_response_str)

                        if success:
                            st.toast('Feedback enviado! Obrigado por nos ajudar a melhorar. 🚀')
