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

/* Estilo para o botão PRO (upgrade na sidebar e na tela de planos) */
.pro-button a button {
    background-color: #52b2ff !important;
    color: white !important;
    border: none !important;
    padding: 10px 20px !important;
    border-radius: 8px !important;
    font-size: 16px !important;
    cursor: pointer !important;
    font-weight: bold;
    box-shadow: 0 4px 8px rgba(0, 0, 0, 0.15); /* Adiciona sombra para destaque */
    transition: all 0.2s;
}
.pro-button a button:hover {
    background-color: #007bff !important;
    transform: translateY(-2px);
}

/* Estilo para o cartão de plano (Tiered Pricing) */
.plan-card {
    padding: 15px;
    border-radius: 12px;
    height: 100%;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
}
.plan-highlight {
    border: 3px solid #ff4b4b; /* Vermelho/laranja de destaque */
    background-color: #fff0f0;
    box-shadow: 0 6px 12px rgba(255, 75, 75, 0.2);
    transform: scale(1.02);
}
.price-tag {
    font-size: 2.5em;
    font-weight: bold;
    margin: 5px 0;
}
.strike-through {
    text-decoration: line-through;
    color: #888;
    font-size: 0.9em;
}
</style>
""", unsafe_allow_html=True)


# --- CONFIGURAÇÕES & CHAVES (Puxadas do secrets.toml) ---
GEMINI_KEY = st.secrets.get("gemini", {}).get("GEMINI_API_KEY", "") 
FREE_LIMIT = int(st.secrets.get("app", {}).get("DEFAULT_FREE_LIMIT", 3))
DEVELOPER_EMAIL = st.secrets.get("app", {}).get("DEVELOPER_EMAIL", "") 


# ----------------------------------------------------
#               CONFIGURAÇÃO DO FIREBASE (CORRIGIDO)
# ----------------------------------------------------

# Inicialização dos estados de sessão de autenticação
if 'db' not in st.session_state:
    st.session_state['db'] = None
    st.session_state['auth'] = None
    st.session_state['firebase_app'] = None
    st.session_state['logged_in_user_id'] = None
    st.session_state['logged_in_user_email'] = None


def initialize_firebase():
    """Tenta inicializar o Firebase Admin SDK ou obtém a instância existente."""
    
    # Nome de instância para garantir unicidade
    APP_NAME = "anuncia_app_instance"
    
    try:
        # 1. Tenta obter a instância, se já existir (Resolve o erro inicial)
        app = firebase_admin.get_app(APP_NAME)
        
    except ValueError:
        # 2. Se a instância não existir, inicializa
        try:
            firebase_config = st.secrets.get("firebase", None) 
            
            if not firebase_config or not firebase_config.get("private_key"):
                st.info("A contagem de anúncios usará um sistema **SIMULADO**: Credenciais Firebase não encontradas.")
                return "SIMULATED", "SIMULATED", None
            
            # --- Lógica de Tratamento Crítico da Chave Privada ---
            private_key_raw = firebase_config.get("private_key", "")
            if "\\n" in private_key_raw:
                private_key = private_key_raw.replace("\\n", "\n")
            else:
                private_key = private_key_raw
            
            # Constrói o dicionário de credenciais a partir do secrets.toml
            service_account_info = {
                k: v for k, v in firebase_config.items() if k not in ["private_key"]
            }
            service_account_info["private_key"] = private_key

            # Inicializa o app com o nome definido
            cred = credentials.Certificate(service_account_info)
            app = initialize_app(cred, name=APP_NAME)
            
        except Exception as e:
            # Trata erros durante a inicialização (e.g., chave mal formatada)
            st.error(f"❌ Erro Crítico na Inicialização Firebase. Contagem SIMULADA: {e}")
            return "SIMULATED", "SIMULATED", None

    # 3. Retorna os objetos de conexão
    db_client = firestore.client(app=app)
    return db_client, auth, app

# Chamada principal para inicialização (Executa apenas uma vez)
if st.session_state['db'] is None:
    st.session_state['db'], st.session_state['auth'], st.session_state['firebase_app'] = initialize_firebase()


# ----------------------------------------------------
#       FUNÇÕES DE CONTROLE DE USO (FIREBASE/SIMULADO)
# ----------------------------------------------------

def clean_email_to_doc_id(email: str) -> str:
    """Limpa o e-mail para usar como Document ID e comparações."""
    clean_email = email.lower().strip()
    if "+" in clean_email:
        local_part, domain = clean_email.split("@")
        local_part = local_part.split("+")[0]
        clean_email = f"{local_part}@{domain}"
    
    user_doc_id = re.sub(r'[^\w@\.\-]', '_', clean_email)
    return user_doc_id

def get_user_data(user_id: str) -> Dict[str, Any]:
    """Busca os dados do usuário no Firestore (ou simula a busca), verificando o acesso dev."""
    
    # 1. VERIFICAÇÃO DE DESENVOLVEDOR (Plano PREMIUM forçado)
    if st.session_state.get('logged_in_user_email') and clean_email_to_doc_id(st.session_state['logged_in_user_email']) == clean_email_to_doc_id(DEVELOPER_EMAIL):
        return {"ads_generated": 0, "plan_tier": "premium"} 
    
    # 2. MODO FIREBASE
    if st.session_state.get("db") and st.session_state["db"] != "SIMULATED":
        user_ref = st.session_state["db"].collection("users").document(user_id) 
        doc = user_ref.get()
        if doc.exists:
            data = doc.to_dict()
            data['plan_tier'] = data.get('plan_tier', 'free') # Default para 'free'
            return data
    
    # 3. MODO SIMULADO (Fallback)
    data = st.session_state.get(f"user_{user_id}", {"ads_generated": 0, "plan_tier": "free"})
    return data

def increment_ads_count(user_id: str, current_plan_tier: str) -> int:
    """Incrementa a contagem de anúncios SOMENTE se o plano for 'free'."""
    if current_plan_tier != "free":
        return 0 
        
    user_data = get_user_data(user_id)
    new_count = user_data.get("ads_generated", 0) + 1
    
    if st.session_state.get("db") and st.session_state["db"] != "SIMULATED":
        # Modo Firebase (Atualiza o documento)
        user_ref = st.session_state["db"].collection("users").document(user_id)
        user_ref.set({
            "ads_generated": new_count,
            "last_used": firestore.SERVER_TIMESTAMP,
            "plan_tier": user_data.get("plan_tier", "free")
        }, merge=True)
    else:
        # Modo Simulado
        user_data["ads_generated"] = new_count
        st.session_state[f"user_{user_id}"] = user_data
        
    return new_count

# ----------------------------------------------------
#           FUNÇÕES DE AUTENTICAÇÃO (CORRIGIDO)
# ----------------------------------------------------

def handle_login(email: str, password: str):
    """Tenta autenticar um usuário com e-mail e senha, referenciando o app nomeado."""
    try:
        if st.session_state['auth'] == "SIMULATED":
            st.error("Serviço de autenticação desativado. Login simulado não suportado neste modo.")
            return

        # --- CORREÇÃO: Pega a instância do app nomeado ---
        app_instance = st.session_state['firebase_app']
        if app_instance is None or app_instance == "SIMULATED":
            st.error("Erro Crítico: Referência do aplicativo Firebase não encontrada ou está em modo SIMULADO.")
            return

        # Tenta obter o usuário, usando explicitamente a instância nomeada (app=app_instance)
        user = st.session_state['auth'].get_user_by_email(email, app=app_instance) 
        
        st.warning("Aviso: Login efetuado (usuário encontrado). Em uma aplicação real, a verificação de senha é feita com o Firebase Client SDK.")
        
        st.session_state['logged_in_user_email'] = email
        st.session_state['logged_in_user_id'] = user.uid
        st.success(f"Bem-vindo(a), {email}!")
        st.experimental_rerun()
        
    except firebase_admin._auth_utils.UserNotFoundError:
        st.error("Erro: Usuário não encontrado. Verifique seu e-mail e senha.")
    except Exception as e:
        st.error(f"Erro no login: {e}") # Exibe o erro

def handle_register(email: str, password: str, username: str, phone: str):
    """Cria um novo usuário, referenciando o app nomeado e salva dados adicionais no Firestore."""
    try:
        if st.session_state['auth'] == "SIMULATED":
            st.error("Serviço de autenticação desativado. Registro simulado não suportado neste modo.")
            return
            
        # --- CORREÇÃO: Pega a instância do app nomeado ---
        app_instance = st.session_state['firebase_app']
        if app_instance is None or app_instance == "SIMULATED":
            st.error("Erro Crítico: Referência do aplicativo Firebase não encontrada ou está em modo SIMULADO.")
            return

        # 1. Cria o usuário no Firebase Auth, usando explicitamente a instância nomeada (app=app_instance)
        user = st.session_state['auth'].create_user(
            email=email,
            password=password,
            display_name=username,
            app=app_instance 
        )

        # 2. Salva os dados adicionais no Firestore
        if st.session_state["db"] != "SIMULATED":
            st.session_state["db"].collection("users").document(user.uid).set({
                "email": email,
                "username": username,
                "phone": phone if phone else None,
                "created_at": firestore.SERVER_TIMESTAMP,
                "plan_tier": "free", 
                "ads_generated": 0
            })
        
        # 3. Loga o usuário
        st.session_state['logged_in_user_email'] = email
        st.session_state['logged_in_user_id'] = user.uid
        st.success(f"Conta criada com sucesso! Bem-vindo(a), {username}.")
        st.experimental_rerun()

    except firebase_admin._auth_utils.EmailAlreadyExistsError:
        st.error("Erro: Este e-mail já está em uso. Tente fazer o login.")
    except Exception as e:
        st.error(f"Erro no registro: {e}")

def handle_logout():
    """Desloga o usuário."""
    st.session_state['logged_in_user_email'] = None
    st.session_state['logged_in_user_id'] = None
    st.experimental_rerun()

# ----------------------------------------------------
#           FUNÇÕES DE CHAMADA DA API (GEMINI)
# ----------------------------------------------------

def call_gemini_api(user_description: str, product_type: str, tone: str, user_plan_tier: str, needs_video: bool) -> Union[Dict, str]:
    """Chama a API do Gemini para gerar copy em formato JSON."""
    
    api_key = GEMINI_KEY
    if not api_key:
        return {"error": "Chave de API (GEMINI_API_KEY) não configurada no secrets.toml."}

    # Verifica os tiers do plano
    is_premium = (user_plan_tier == "premium")

    # 1. CONSTRUÇÃO DO PROMPT E SCHEMA
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

    # ADICIONA RECURSOS PREMIUM (Roteiro e Campanhas)
    if is_premium and needs_video:
        system_instruction += "\n\n⚠️ INSTRUÇÃO PREMIUM: Gere um roteiro de vídeo de 30 segundos e um gancho inicial (hook) de 3 segundos para Reels/TikTok, com foco em parar o feed. Gere também uma sugestão de 3 títulos de campanhas para teste A/B no Meta Ads."
        
        # Adiciona novos campos ao esquema de saída
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
    
    # 3. CHAMADA HTTP (COM BACKOFF)
    for i in range(3):
        try:
            response = requests.post(url, headers={'Content-Type': 'application/json'}, data=json.dumps(payload))
            response.raise_for_status() 
            
            result = response.json()
            # Tenta extrair o texto JSON gerado pelo modelo
            json_text = result.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '{}')
            
            return json.loads(json_text)
        
        except requests.exceptions.RequestException as e:
            if i < 2:
                time.sleep(2 ** i)
                continue
            return {"error": f"Erro de conexão com a API: {e}"}
        except json.JSONDecodeError:
            return {"error": "A IA não conseguiu retornar um JSON válido. Por favor, tente novamente."}
        except Exception as e:
            return {"error": f"Erro inesperado na chamada da API: {e}"}
            
    return {"error": "Não foi possível conectar após várias tentativas."}

# ----------------------------------------------------
#           FUNÇÕES DE EXIBIÇÃO DA UI
# ----------------------------------------------------

def display_upgrade_page(user_id: str):
    """Exibe a página de vendas/upgrade com 3 planos."""
    st.markdown("---")
    st.subheader("🚀 Escolha seu Plano e Venda Mais!")
    st.warning("🚨 **Limite Gratuito Atingido!** Para continuar, selecione um plano.")
    
    st.markdown("Invista em copy de alta conversão para dominar o mercado.")
    
    # Layout de 3 colunas para os planos (Melhoria de UI)
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
    
    # Plano 2: Essencial (Ancora de preço / Gateway)
    with col2:
        st.markdown(
            f"""
            <div class="plan-card" style="background-color: #e0f2ff; border: 2px solid #52b2ff;">
                <h4 style="color: #52b2ff; text-align: center;">Plano Essencial</h4>
                 <div style="text-align: center;">
                    <p class="price-tag" style="color: #52b2ff;">R$ 19,90</p>
                    <p>por mês</p>
                </div>
                <ul style="list-style-type: '✅ '; padding-left: 20px; font-size: 0.95em;">
                    <li>Anúncios Ilimitados (Sem Restrições)</li>
                    <li>Uso Completo (AIDA e Segmentação)</li>
                    <li><span style="color: #999;">Roteiros de Vídeo (Reels/TikTok)</span></li>
                    <li><span style="color: #999;">Sugestões de Campanhas A/B</span></li>
                </ul>
                <div style="text-align: center; margin-top: 15px;" class="pro-button">
                    <a href="LINK_PARA_PAGAMENTO_ESSENCIAL" target="_blank" style="text-decoration: none;">
                        <button>
                            ASSINAR AGORA →
                        </button>
                    </a>
                </div>
            </div>
            """, unsafe_allow_html=True
        )

    # Plano 3: Premium (Melhor Oferta e Destaque)
    with col3:
        st.markdown(
            f"""
            <div class="plan-card plan-highlight">
                <h4 style="color: #ff4b4b; text-align: center;">🏆 Plano Premium</h4>
                 <div style="text-align: center;">
                    <p class="strike-through">De R$ 49,90</p>
                    <p class="price-tag" style="color: #ff4b4b;">R$ 34,90</p>
                    <p>por mês **(Mais Vantajoso)**</p>
                </div>
                <ul style="list-style-type: '✅ '; padding-left: 20px; font-size: 0.95em;">
                    <li>Anúncios Ilimitados (Sem Restrições)</li>
                    <li>Uso Completo (AIDA e Segmentação)</li>
                    <li>Geração de **Roteiros de Vídeo**</li>
                    <li>Sugestões de **Campanhas A/B** (Exclusivo!)</li>
                </ul>
                <div style="text-align: center; margin-top: 15px;" class="pro-button">
                    <a href="LINK_PARA_PAGAMENTO_PREMIUM" target="_blank" style="text-decoration: none;">
                        <button style="background-color: #ff4b4b !important;">
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
    st.markdown(f"**{icon} {title}**")
    st.text_area(
        label=title,
        value=content,
        height=None,
        key=key,
        label_visibility="collapsed"
    )

# ----------------------------------------------------
#               INTERFACE PRINCIPAL
# ----------------------------------------------------

st.title("🤖 AnuncIA — Gerador de Copy de Alta Conversão") # Título melhorado

# --- PAINEL DE LOGIN/REGISTRO NA SIDEBAR ---
with st.sidebar:
    st.markdown("---")
    if st.session_state['logged_in_user_id']:
        # Se logado, mostra informações do usuário e botão de logout
        st.success(f"Logado como: {st.session_state['logged_in_user_email']}")
        st.button("Sair (Logout)", on_click=handle_logout, use_container_width=True)
    else:
        # Se deslogado, mostra as opções de Login/Registro
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

# --- CONTEÚDO PRINCIPAL ---

if not st.session_state['logged_in_user_id']:
    st.info("Por favor, faça **Login** ou **Crie sua Conta** na barra lateral para começar seu teste grátis.")
else:
    # --- Verificação de Limite e Exibição de Status (Melhorado) ---
    user_id = st.session_state['logged_in_user_id']
    user_data = get_user_data(user_id)
    ads_used = user_data.get("ads_generated", 0)
    user_plan_tier = user_data.get("plan_tier", "free") 
    
    is_premium = (user_plan_tier == "premium")
    
    st.markdown("---")
    
    # Exibição do Status (Melhorado com UX)
    tier_info_map = {
        "free": {"icon": "🆓", "color": "blue", "text": "Plano Grátis"},
        "essential": {"icon": "⚡", "color": "orange", "text": "Plano Essencial"},
        "premium": {"icon": "👑", "color": "green", "text": "Plano Premium"}
    }
    current_tier_info = tier_info_map.get(user_plan_tier, tier_info_map["free"])
        
    # Layout de status
    col_status, col_upgrade_link = st.columns([2, 1])

    with col_status:
        if st.session_state['logged_in_user_email'] and clean_email_to_doc_id(st.session_state['logged_in_user_email']) == clean_email_to_doc_id(DEVELOPER_EMAIL):
            st.markdown(f"**Status:** ⭐ Acesso de Desenvolvedor (PREMIUM Ilimitado)")
        else:
            st.markdown(f"**Status:** {current_tier_info['icon']} **{current_tier_info['text']}**")
            if user_plan_tier == "free":
                st.markdown(f"**Uso:** **{ads_used}** de **{FREE_LIMIT}** anúncios grátis.")
            else:
                st.markdown("Uso Ilimitado! 🎉")

    with col_upgrade_link:
        if user_plan_tier == "free":
            # Botão de Upgrade Flutuante
            st.markdown(f"""
                <div style="text-align: right; margin-top: 10px;" class="pro-button">
                    <a href="LINK_PARA_PAGAMENTO_PREMIUM" target="_blank" style="text-decoration: none;">
                        <button style="background-color: #52b2ff !important; font-size: 14px !important; padding: 8px 15px !important;">
                            FAÇA UPGRADE AGORA
                        </button>
                    </a>
                </div>
                """, unsafe_allow_html=True)
            
    st.markdown("---")

    # Botão de Upgrade na Sidebar
    with st.sidebar:
        if user_plan_tier == "free" or user_plan_tier == "essential":
            st.markdown("---")
            st.markdown("#### 🚀 Quer o Plano Premium?")
            st.markdown("""
            <div style="text-align: center;" class="pro-button">
                <a href="LINK_PARA_PAGAMENTO_PREMIUM" target="_blank">
                    <button style="background-color: #ff4b4b !important;">
                        UPGRADE (Economize!)
                    </button>
                </a>
            </div>
            """, unsafe_allow_html=True)
            st.markdown("---")
        
    if user_plan_tier == "free" and ads_used >= FREE_LIMIT:
        display_upgrade_page(user_id)
        
    else:
        # --- Formulário de Geração de Anúncios ---
        with st.form("input_form"):
            st.subheader("🛠️ Crie Seu Anúncio Profissional")
            
            # PLACEHOLDER MELHORADO
            description = st.text_area(
                "Descreva seu produto (máximo 800 caracteres):", 
                placeholder="""Ex: 'Um curso online para iniciantes que ensina a investir na bolsa com pouco dinheiro, usando estratégias de baixo risco e zero jargão técnico.'\n\nInclua: Nome do Produto, Público-alvo, Benefício principal e Oferta (preço/promoção).""", 
                max_chars=800
            )
            
            # CONFIGURAÇÕES MOVIDAS PARA EXPANDER (Melhoria de UI)
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

            # Recurso exclusivo do PREMIUM
            needs_video = st.checkbox(
                "🎬 Gerar Roteiro de Vídeo (Reels/TikTok) e Sugestão de Campanhas - Exclusivo Plano Premium", 
                value=False,
                disabled=(not is_premium)
            )
            
            st.markdown("---")
            # Botão de submissão
            submitted = st.form_submit_button("🔥 Gerar Copy com a IA", use_container_width=True)

        if submitted:
            if not description:
                st.error("Por favor, forneça uma descrição detalhada do produto para a IA.")
            elif needs_video and not is_premium:
                st.error("⚠️ **Recurso Premium:** A Geração de Roteiro de Vídeo e Campanhas é exclusiva do Plano Premium.")
            elif not GEMINI_KEY:
                st.error("⚠️ Erro de Configuração: A chave de API (GEMINI_API_KEY) não está definida no secrets.toml.")
                
                # --- SIMULAÇÃO DE RESULTADO (SE A CHAVE DA API ESTIVER AUSENTE) ---
                st.warning("Gerando Resultado Simulado para Teste de UI/Contagem. Se a chave estivesse OK, o resultado real apareceria abaixo.")
                
                new_count = increment_ads_count(user_id, user_plan_tier)
                
                st.success(f"✅ Teste de UI/Contagem Sucesso! (Grátis restante: {max(0, FREE_LIMIT - new_count)})")
                
                st.markdown("---")
                st.subheader("Resultado Simulado da Copy")
                
                sim_result = {
                    "titulo_gancho": "NÃO COMPRE ESTE CURSO! (Antes de ver o que ele faz)",
                    "copy_aida": "ATENÇÃO: Cansado de jargões financeiros que só complicam? Você não precisa de milhões para começar. INTERESSE: Este curso desmistifica a bolsa, usando estratégias de baixo risco, ideais para iniciantes. DESEJO: Imagine seu dinheiro trabalhando por você, sem estresse. Em pouco tempo, você terá mais confiança do que 90% dos investidores. AÇÃO: As vagas são limitadas! Clique agora no link para a matrícula e destrave o bônus de iniciante.",
                    "chamada_para_acao": "Clique aqui e comece a investir hoje!",
                    "segmentacao_e_ideias": "1. Pessoas com medo de investir. 2. Aposentados buscando renda extra. 3. Estudantes de economia desiludidos com a teoria."
                }
                
                if is_premium and needs_video:
                    sim_result['gancho_video'] = "Pare de perder tempo com vídeos longos!"
                    sim_result['roteiro_basico'] = "Problema (0-5s): Mostra uma tela de gráfico confusa. 'Investir parece complicado, né?'. Solução/Benefício (6-20s): Transição para a tela do curso, mostrando uma interface simples. 'Com nosso método, você aprende o básico em 1 hora e aplica amanhã!'. CTA (21-30s): Link na bio. 'Inscreva-se hoje e ganhe seu primeiro guia de investimentos grátis!'."
                    sim_result['sugestao_campanhas'] = "Campanha 1: 'Pare de Perder Dinheiro na Poupança (Método Secreto)'. Campanha 2: 'O Fim da Confusão de Investimentos'. Campanha 3: 'Aprenda a Investir Sem Ser Um Gênio da Matemática'."

                
                display_result_box("🎯", "Título Gancho (Atenção)", sim_result["titulo_gancho"], "title_sim_box")
                display_result_box("📝", "Copy Principal (AIDA)", sim_result["copy_aida"], "copy_sim_box")
                display_result_box("📢", "Chamada para Ação (CTA)", sim_result["chamada_para_acao"], "cta_sim_box")
                display_result_box("💡", "Ideias de Segmentação", sim_result["segmentacao_e_ideias"], "seg_sim_box")
                
                if is_premium and needs_video:
                    st.markdown("---")
                    st.subheader("💎 Conteúdo Premium: Estratégia de Vídeo e Campanhas (SIMULADO)")
                    with st.container(border=True): # Destaque visual PREMIUM
                        # ROTEIRO DE VÍDEO
                        with st.expander("🎬 Roteiro de Vídeo (Reels/TikTok)"):
                            display_result_box("🎬", "Gancho (Hook) de 3 Segundos", sim_result["gancho_video"], "hook_sim_box")
                            display_result_box("🎞️", "Roteiro Completo (30s)", sim_result["roteiro_basico"], "roteiro_sim_box")
                        
                        # SUGESTÃO DE CAMPANHAS
                        with st.expander("📈 Sugestões de Campanhas A/B (Meta Ads)"):
                             display_result_box("📈", "Títulos de Campanhas", sim_result["sugestao_campanhas"], "camp_sim_box")
                
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
                        # Mensagem de sucesso (e aviso de limite para o Free)
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

                        # --- SEÇÃO DE FEEDBACK (Nova) ---
                        st.markdown("---")
                        st.subheader("Avalie a Qualidade da Copy:")

                        col_rate, col_feedback = st.columns([1, 4])
                        with col_rate:
                            rating = st.select_slider(
                                'Gostou do Resultado?',
                                options=['Ruim 😭', 'Mais ou Menos 🤔', 'Bom 👍', 'Ótimo! 🚀'],
                                key="rating_slider"
                            )
                        
                        # Formulário/Caixa de Feedback
                        with col_feedback:
                            feedback_text = ""
                            if rating == 'Ruim 😭':
                                feedback_text = st.text_input("Diga-nos o que podemos melhorar (opcional):", key="feedback_text_input") 
                            
                            disable_send = st.session_state.get("db") == "SIMULATED" or rating == "Mais ou Menos 🤔"

                            # Botão e lógica de envio
                            if st.button("Enviar Feedback", key="send_feedback_btn", use_container_width=True, disabled=disable_send):
                                if st.session_state["db"] != "SIMULATED":
                                    feedback_data = {
                                        "user_id": user_id,
                                        "rating": rating,
                                        "text": feedback_text,
                                        "timestamp": firestore.SERVER_TIMESTAMP,
                                        "input_desc": description[:100], 
                                        "result": api_result.get("copy_aida", "N/A")[:100] 
                                    }
                                    st.session_state["db"].collection("feedback").add(feedback_data)
                                    st.success("Feedback enviado! Isso nos ajuda a melhorar a IA.")
                                else:
                                    st.error("Funcionalidade de Feedback desativada em modo SIMULADO.")
