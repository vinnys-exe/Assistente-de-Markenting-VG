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

# --- CONFIGURAÇÕES DO APLICATIVO E CSS CUSTOMIZADO (V5.0 - PLANOS E RERUN CORRIGIDOS) ---
st.set_page_config(page_title="✨ AnuncIA - Gerador de Anúncios", layout="centered")

# --- CSS PROFISSIONAL V5.0 ---
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
# Garante que o e-mail do desenvolvedor seja limpo para a verificação
DEVELOPER_EMAIL_CLEAN = re.sub(r'[^\w@\.\-]', '_', DEVELOPER_EMAIL.lower().strip().split('+')[0])

# ----------------------------------------------------
#                CONFIGURAÇÃO DO FIREBASE (IMUTÁVEL)
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
#       FUNÇÕES DE CONTROLE DE USO E PLANO
# ----------------------------------------------------

def clean_email_to_doc_id(email: str) -> str:
    """Limpa o e-mail para usar como Document ID e comparações."""
    clean_email = email.lower().strip()
    if "+" in clean_email:
        local_part, domain = clean_email.split("@")
        local_part = local_part.split("+")[0]
        clean_email = f"{local_part}@{domain}"
    
    # Substitui caracteres especiais restantes por '_' (para Document ID)
    user_doc_id = re.sub(r'[^\w@\.\-]', '_', clean_email)
    return clean_email

def get_user_data(user_id: str) -> Dict[str, Any]:
    """Busca os dados do usuário no Firestore, verificando o acesso dev."""
    
    # 1. VERIFICAÇÃO DE DESENVOLVEDOR (Plano PREMIUM forçado)
    if st.session_state.get('logged_in_user_email'):
        logged_email_clean = clean_email_to_doc_id(st.session_state['logged_in_user_email'])
        
        if logged_email_clean == clean_email_to_doc_id(DEVELOPER_EMAIL):
            # Se o e-mail for o Admin, força o plano PREMIUM (ilimitado)
            return {"ads_generated": 0, "plan_tier": "premium"}
    
    # 2. MODO FIREBASE
    if st.session_state.get("db") and st.session_state["db"] != "SIMULATED":
        user_ref = st.session_state["db"].collection("users").document(user_id)
        doc = user_ref.get()
        if doc.exists:
            data = doc.to_dict()
            # Lê o plan_tier do Firestore (que seria atualizado pelo Webhook de pagamento)
            data['plan_tier'] = data.get('plan_tier', 'free')
            return data
    
    # 3. MODO SIMULADO (Fallback)
    data = st.session_state.get(f"user_{user_id}", {"ads_generated": 0, "plan_tier": "free"})
    return data

def increment_ads_count(user_id: str, current_plan_tier: str) -> int:
    """Incrementa a contagem de anúncios SOMENTE se o plano for 'free'."""
    # ESSENCIAL E PREMIUM SÃO ILIMITADOS
    if current_plan_tier != "free":
        return 0
        
    user_data = get_user_data(user_id)
    new_count = user_data.get("ads_generated", 0) + 1
    
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
    
    # 1. MODO FIREBASE
    if st.session_state.get("db") and st.session_state["db"] != "SIMULATED":
        feedback_ref = st.session_state["db"].collection("feedback").document() # Gera um ID automático
        
        # Converte o rating de texto para um valor numérico para facilitar análises
        rating_map = {'Ruim 😭': 1, 'Mais ou Menos 🤔': 2, 'Bom 👍': 3, 'Ótimo! 🚀': 4}
        rating_score = rating_map.get(rating, 0)
        
        try:
            feedback_ref.set({
                "user_id": user_id,
                "rating_text": rating,
                "rating_score": rating_score,
                "input_prompt": input_prompt,
                "ai_response_json": ai_response, # Salva o JSON completo (útil para debug)
                "timestamp": firestore.SERVER_TIMESTAMP,
            })
            return True
        except Exception as e:
            st.error(f"Erro ao salvar feedback no Firestore: {e}")
            return False
            
    # 2. MODO SIMULADO (Apenas loga a ação)
    else:
        return True

def update_user_plan(target_email: str, new_plan: str) -> bool:
    """
    Função administrativa/Webhook Simulada para alterar o plano de um usuário.
    Garante que 'free' reset a contagem, e outros planos usem 0.
    """
    # 1. Limpar e-mail
    clean_email = clean_email_to_doc_id(target_email)

    # 2. MODO FIREBASE
    if st.session_state.get("db") and st.session_state["db"] != "SIMULATED":
        # Primeiro, precisamos do UID do usuário para achar o documento.
        # No cenário real, o Webhook teria o UID. Aqui, faremos uma busca por e-mail (mais lento, mas funciona).
        try:
            # Assumimos que o Firebase Auth está funcionando
            user_record = st.session_state['auth'].get_user_by_email(target_email, app=st.session_state['firebase_app'])
            user_id = user_record.uid
            
            user_ref = st.session_state["db"].collection("users").document(user_id)
            
            # Resetar a contagem de anúncios para 0 ao mudar para um plano pago,
            # ou iniciar um novo ciclo se for free.
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
            
    # 3. MODO SIMULADO (Atualiza a session_state)
    else:
        # No modo simulado, o user_id é o e-mail limpo.
        user_data_key = f"user_{clean_email}"
        # A API de autenticação não está ativa, então usamos o e-mail como ID
        if st.session_state.get('logged_in_user_email') and clean_email_to_doc_id(st.session_state['logged_in_user_email']) == clean_email:
             user_data_key = f"user_{st.session_state['logged_in_user_id']}"
        else: # Se não for o logado, tentamos com o e-mail limpo (fallback)
             user_data_key = f"user_{clean_email}"
             
        if user_data_key in st.session_state:
            st.session_state[user_data_key]["plan_tier"] = new_plan
            st.session_state[user_data_key]["ads_generated"] = 0 # Reset de contagem
            return True
        else:
            # No modo dev simulado, se não encontrar na sessão, ele assume o e-mail logado
            st.error(f"❌ Erro SIMULADO: Não foi possível aplicar o plano. Tente logar e usar seu e-mail de dev.")
            return False


# ----------------------------------------------------
#            FUNÇÕES DE AUTENTICAÇÃO (st.rerun CORRIGIDO)
# ----------------------------------------------------

def handle_login(email: str, password: str):
    """Tenta autenticar um usuário."""
    try:
        if st.session_state['auth'] == "SIMULATED":
            st.error("Serviço de autenticação desativado. Login simulado não suportado neste modo.")
            return

        app_instance = st.session_state['firebase_app']
        user = st.session_state['auth'].get_user_by_email(email, app=app_instance)
        
        st.warning("Aviso: Login efetuado (usuário encontrado). Em uma aplicação real, a verificação de senha é feita com o Firebase Client SDK.")
        
        st.session_state['logged_in_user_email'] = email
        st.session_state['logged_in_user_id'] = user.uid
        st.success(f"Bem-vindo(a), {email}!")
        st.rerun() # <-- CORREÇÃO
        
    except firebase_admin._auth_utils.UserNotFoundError:
        st.error("Erro: Usuário não encontrado. Verifique seu e-mail e senha.")
    except Exception as e:
        st.error(f"Erro no login: {e}")

def handle_register(email: str, password: str, username: str, phone: str):
    """Cria um novo usuário."""
    try:
        if st.session_state['auth'] == "SIMULATED":
            st.error("Serviço de autenticação desativado. Registro simulado não suportado neste modo.")
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
        st.rerun() # <-- CORREÇÃO

    except firebase_admin._auth_utils.EmailAlreadyExistsError:
        st.error("Erro: Este e-mail já está em uso. Tente fazer o login.")
    except Exception as e:
        st.error(f"Erro no registro: {e}")

def handle_logout():
    """Desloga o usuário."""
    st.session_state['logged_in_user_email'] = None
    st.session_state['logged_in_user_id'] = None
    st.rerun() # <-- CORREÇÃO

# ----------------------------------------------------
#            FUNÇÕES DE CHAMADA DA API (IMUTÁVEL)
# ----------------------------------------------------

def call_gemini_api(user_description: str, product_type: str, tone: str, user_plan_tier: str, needs_video: bool) -> Union[Dict, str]:
    """Chama a API do Gemini para gerar copy em formato JSON."""
    
    api_key = GEMINI_KEY
    if not api_key:
        return {"error": "Chave de API (GEMINI_API_KEY) não configurada no secrets.toml."}

    # Recurso de vídeo/A/B é EXCLUSIVO do plano premium
    is_premium_feature = (user_plan_tier == "premium" and needs_video)
    
    system_instruction = f"""
    Você é um Copywriter de elite, especializado em Marketing Digital e Vendas Diretas.
    Sua missão é gerar um anúncio altamente persuasivo e focado em conversão.
    
    Instruções de Tom: O tom de voz deve ser {tone}.
    Instruções de Estrutura: Use o Framework AIDA (Atenção, Interesse, Desejo, Ação).
    A copy deve ser concisa, focar no benefício do cliente e incluir gatilhos de escassez/urgência/prova social.
    
    O produto é um {product_type}.
    """
    
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

    if is_premium_feature:
        system_instruction += "\n\n⚠️ INSTRUÇÃO PREMIUM: Gere um roteiro de vídeo de 30 segundos e um gancho inicial (hook) de 3 segundos para Reels/TikTok, com foco em parar o feed. Gere também uma sugestão de 3 títulos de campanhas para teste A/B no Meta Ads."
        
        output_schema['properties']['gancho_video'] = {"type": "STRING", "description": "Um HOOK (gancho) de 3 segundos que interrompe a rolagem do feed."}
        output_schema['properties']['roteiro_basico'] = {"type": "STRING", "description": "Um roteiro conciso de 30 segundos em 3 etapas (Problema, Solução/Benefício, CTA)."}
        output_schema['properties']['sugestao_campanhas'] = {"type": "STRING", "description": "3 títulos de campanhas agressivas para teste A/B."}
        
        output_schema['propertyOrdering'].extend(['gancho_video', 'roteiro_basico', 'sugestao_campanhas'])


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
    
    # 3. CHAMADA HTTP (omiti a lógica de retry para brevidade, mas ela estava correta)
    try:
        response = requests.post(url, headers={'Content-Type': 'application/json'}, data=json.dumps(payload))
        response.raise_for_status()
        
        result = response.json()
        json_text = result.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '{}')
        
        # Retorna o dicionário para a UI
        return json.loads(json_text)
    
    except requests.exceptions.RequestException as e:
        return {"error": f"Erro de conexão com a API: {e}"}
    except json.JSONDecodeError:
        raw_response_text = response.text if 'response' in locals() else "N/A"
        return {"error": f"A IA não conseguiu retornar um JSON válido. Resposta da API: {raw_response_text}"}
    except Exception as e:
        return {"error": f"Erro inesperado na chamada da API: {e}"}

# ----------------------------------------------------
#            FUNÇÕES DE EXIBIÇÃO DA UI
# ----------------------------------------------------

def display_upgrade_page(user_id: str):
    """Exibe a página de vendas/upgrade."""
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

st.title("🤖 AnuncIA — Gerador de Copy de Alta Conversão")

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

    # Bloco de Upgrade para o Premium (aparece para Free e Essencial logado)
    if st.session_state.get('logged_in_user_id') and not is_premium and not is_dev:
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
    if st.session_state.get('logged_in_user_email') and clean_email_to_doc_id(st.session_state['logged_in_user_email']) == clean_email_to_doc_id(DEVELOPER_EMAIL):
        st.markdown("---")
        with st.expander("🛠️ ADMIN: Controle de Planos (Webhook Simulado)"):
            st.info("Painel DEV: Simule a compra de um plano para o usuário logado.")
            
            # Puxa o e-mail logado para facilitar o teste
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
                        # Garante que o usuário logado veja a mudança imediatamente
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
    # --- Verificação de Limite e Exibição de Status ---
    user_id = st.session_state['logged_in_user_id']
    user_data = get_user_data(user_id)
    ads_used = user_data.get("ads_generated", 0)
    user_plan_tier = user_data.get("plan_tier", "free")
    
    # Aplicação dos benefícios
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
            st.markdown(f"**Status:** ⭐ Acesso de Desenvolvedor (PREMIUM Ilimitado)")
        else:
            st.markdown(f"**Status:** {current_tier_info['icon']} **{current_tier_info['text']}**")
            if user_plan_tier == "free":
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
        
    if user_plan_tier == "free" and ads_used >= FREE_LIMIT and not is_dev:
        display_upgrade_page(user_id)
        
    else:
        # --- Formulário de Geração de Anúncios ---
        with st.form("input_form"):
            st.subheader("🛠️ Crie Seu Anúncio Profissional")
            
            description = st.text_area(
                "Descreva seu produto (máximo 800 caracteres):",
                placeholder="""Ex: 'Um curso online para iniciantes que ensina a investir na bolsa com pouco dinheiro, usando estratégias de baixo risco e zero jargão técnico.'\n\nInclua: Nome do Produto, Público-alvo, Benefício principal e Oferta (preço/promoção).""",
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
                "🎬 Gerar Roteiro de Vídeo (Reels/TikTok) e Sugestão de Campanhas - Exclusivo Plano Premium",
                value=False,
                disabled=(not is_premium) # Desabilitado se não for Premium
            )
            
            st.markdown("---")
            submitted = st.form_submit_button("🔥 Gerar Copy com a IA", use_container_width=True)

        if submitted:
            if not description:
                st.error("Por favor, forneça uma descrição detalhada do produto para a IA.")
            elif needs_video and not is_premium:
                st.error("⚠️ **Recurso Premium:** A Geração de Roteiro de Vídeo e Campanhas é exclusiva do Plano Premium.")
            elif not GEMINI_KEY:
                st.error("⚠️ Erro de Configuração: A chave de API (GEMINI_API_KEY) não está definida no secrets.toml. Por favor, corrija o arquivo.")
                
                # SIMULAÇÃO DE RESULTADO (Fallback)
                new_count = increment_ads_count(user_id, user_plan_tier)
                
                st.success(f"✅ Teste de UI/Contagem Sucesso! (Grátis restante: {max(0, FREE_LIMIT - new_count)})")
                
                api_result = { # Usamos 'api_result' para poder alimentar o formulário de feedback (se for o caso)
                    "titulo_gancho": "SIMULADO: Seu Título de Sucesso Aqui!",
                    "copy_aida": "SIMULADO: A Copy AIDA apareceria aqui se a chave do Gemini estivesse ativa.",
                    "chamada_para_acao": "Clique no Botão de Compra!",
                    "segmentacao_e_ideias": "SIMULADO: Segmentação: 1. Clientes potenciais. 2. Clientes atuais. 3. Clientes frios.",
                    "gancho_video": "SIMULADO: HOOK de 3s (Exclusivo Premium)",
                    "roteiro_basico": "SIMULADO: Roteiro (Exclusivo Premium)",
                    "sugestao_campanhas": "SIMULADO: Campanhas (Exclusivo Premium)"
                }

                display_result_box("🎯", "Título Gancho (Atenção)", api_result["titulo_gancho"], "title_sim_box")
                display_result_box("📝", "Copy Principal (AIDA)", api_result["copy_aida"], "copy_sim_box")
                display_result_box("📢", "Chamada para Ação (CTA)", api_result["chamada_para_acao"], "cta_sim_box")
                display_result_box("💡", "Ideias de Segmentação", api_result["segmentacao_e_ideias"], "seg_sim_box")
                
            else:
                # 1. Chamada REAL à API
                with st.spinner("🧠 A IA está gerando sua estratégia e copy..."):
                    api_result = call_gemini_api(description, product_type, tone, user_plan_tier, needs_video)
                    
                    if "error" in api_result:
                        st.error(f"❌ Erro na Geração da Copy: {api_result['error']}")
                        st.info("A contagem de uso **NÃO** foi debitada. Tente novamente.")
                    else:
                        # 2. Incrementa a contagem no Firebase/Simulação
                        new_count = increment_ads_count(user_id, user_plan_tier)
                        
                        # 3. Exibição do resultado
                        
                        if user_plan_tier == "free":
                            st.success(f"✅ Copy Gerada! Você tem mais **{max(0, FREE_LIMIT - new_count)}** anúncios grátis nesta sessão.")
                        else:
                            st.success("✅ Copy Ilimitada Gerada com Sucesso!")
                        
                        st.markdown("---")
                        st.subheader("Resultado Gerado Pela IA:")

                        # Resultados Padrão (Todos os Planos)
                        display_result_box("🎯", "Título Gancho (Atenção)", api_result.get("titulo_gancho", "N/A"), "title_box")
                        display_result_box("📝", "Copy Principal (AIDA)", api_result.get("copy_aida", "N/A"), "copy_box")
                        display_result_box("📢", "Chamada para Ação (CTA)", api_result.get("chamada_para_acao", "N/A"), "cta_box")
                        display_result_box("💡", "Ideias de Segmentação", api_result.get("segmentacao_e_ideias", "N/A"), "seg_box")

                        # Resultados Premium (Se solicitado e no plano correto)
                        if is_premium and needs_video:
                            st.markdown("---")
                            st.subheader("💎 Conteúdo Premium: Estratégia de Vídeo e Campanhas")
                            with st.container(border=True):
                                # ROTEIRO DE VÍDEO
                                with st.expander("🎬 Roteiro de Vídeo (Reels/TikTok)"):
                                    display_result_box("🎬", "Gancho (Hook) de 3 Segundos", api_result.get("gancho_video", "N/A"), "hook_box")
                                    display_result_box("🎞️", "Roteiro Completo (30s)", api_result.get("roteiro_basico", "N/A"), "roteiro_box")
                                
                                # SUGESTÃO DE CAMPANHAS
                                with st.expander("📈 Sugestões de Campanhas A/B (Meta Ads)"):
                                    display_result_box("📈", "Títulos de Campanhas", api_result.get("sugestao_campanhas", "N/A"), "camp_box")

                        # --- SEÇÃO DE FEEDBACK (BLOCO COMPLETO) ---
                        st.markdown("---")
                        
                        # Adiciona um novo form para o feedback, pois ele precisa de submissão separada.
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
                                st.write("") # Espaçamento
                                feedback_submitted = st.form_submit_button("Enviar Feedback", use_container_width=True)

                            if feedback_submitted:
                                # Salva o feedback usando a nova função
                                # Converte o dicionário de resultado da API para string JSON para salvar.
                                json_response_str = json.dumps(api_result, ensure_ascii=False, indent=2)
                                success = save_user_feedback(user_id, rating, description, json_response_str)

                                if success:
                                    st.toast('Feedback enviado! Obrigado por nos ajudar a melhorar. 🚀')
