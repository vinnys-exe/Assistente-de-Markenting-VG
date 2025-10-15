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

/* Estilo para o botão PRO (upgrade na sidebar) */
.pro-button a button {
    background-color: #52b2ff !important;
    color: white !important;
    border: none !important;
    padding: 10px 20px !important;
    border-radius: 8px !important;
    font-size: 16px !important;
    cursor: pointer !important;
    font-weight: bold;
}

</style>
""", unsafe_allow_html=True)


# --- CONFIGURAÇÕES & CHAVES (Puxadas do secrets.toml) ---
GEMINI_KEY = st.secrets.get("GEMINI_API_KEY", "") 
FREE_LIMIT = int(st.secrets.get("DEFAULT_FREE_LIMIT", 3))

# Puxa o e-mail do secrets.toml para dar acesso PRO
DEVELOPER_EMAIL = st.secrets.get("DEVELOPER_EMAIL", "")

# ----------------------------------------------------
#               CONFIGURAÇÃO DO FIREBASE
# ----------------------------------------------------

if 'db' not in st.session_state:
    st.session_state['db'] = None
    
    try:
        firebase_config = st.secrets.get("firebase", None)
        
        if not firebase_config:
            st.session_state["db"] = "SIMULATED"
            
        else:
            private_key_raw = firebase_config.get("private_key", "")
            
            # Limpa quebras de linha (necessário se não for formatado com aspas triplas no toml)
            if "\\n" in private_key_raw:
                private_key = private_key_raw.replace("\\n", "\n")
            else:
                private_key = private_key_raw
            
            service_account_info = {
                k: v for k, v in firebase_config.items() if k not in ["private_key"]
            }
            service_account_info["private_key"] = private_key

            if not firebase_admin._apps: 
                cred = credentials.Certificate(service_account_info)
                initialize_app(cred, name="anuncia_app_instance")
            
            db_client = firestore.client(app=firebase_admin.get_app("anuncia_app_instance"))
            st.session_state["db"] = db_client 
            
    except Exception as e:
        st.info("A contagem de anúncios usará um sistema de contagem SIMULADA.")
        st.session_state["db"] = "SIMULATED" 
        
# ----------------------------------------------------
#       FUNÇÕES DE CONTROLE DE USO (FIREBASE/SIMULADO)
# ----------------------------------------------------

def clean_email_to_doc_id(email: str) -> str:
    """Limpa o e-mail (removendo alias '+' e caracteres especiais) para usar como Document ID."""
    clean_email = email.lower().strip()
    if "+" in clean_email:
        local_part, domain = clean_email.split("@")
        local_part = local_part.split("+")[0]
        clean_email = f"{local_part}@{domain}"
    
    # Mantém apenas letras, números, @, hifens e pontos. Substitui outros por "_"
    user_doc_id = re.sub(r'[^\w@\.\-]', '_', clean_email)
    return user_doc_id

def get_user_data(user_id: str) -> Dict[str, Any]:
    """Busca os dados do usuário no Firestore (ou simula a busca), verificando o acesso dev."""
    
    # 1. VERIFICAÇÃO DE DESENVOLVEDOR (Plano PRO forçado)
    dev_doc_id = clean_email_to_doc_id(DEVELOPER_EMAIL)
    if user_id.lower() == dev_doc_id:
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
        # Modo Firebase (Atualiza o documento)
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
#           FUNÇÕES DE CHAMADA DA API (GEMINI)
# ----------------------------------------------------

def call_gemini_api(user_description: str, product_type: str, tone: str, is_pro_user: bool, needs_video: bool) -> Union[Dict, str]:
    """Chama a API (simulando Gemini/OpenAI) para gerar copy em formato JSON."""
    
    api_key = GEMINI_KEY
    if not api_key:
        return {"error": "Chave de API (GEMINI_API_KEY) não configurada no secrets.toml."}

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
    
    # 3. CHAMADA HTTP (COM BACKOFF)
    for i in range(3):
        try:
            response = requests.post(url, headers={'Content-Type': 'application/json'}, data=json.dumps(payload))
            response.raise_for_status() 
            
            result = response.json()
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
    """Exibe a página de vendas/upgrade quando o limite é atingido."""
    st.markdown("---")
    st.subheader("🚀 Destrave o Poder Total da AnuncIA!")
    st.warning("🚨 **Limite Gratuito Atingido!** Você utilizou 3 de 3 anúncios grátis.")
    
    st.markdown("Chegou a hora de levar sua copy e seus resultados para o próximo nível.")
    
    col1, col2 = st.columns(2)
    
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
                <div style="text-align: center; margin-top: 15px;" class="pro-button">
                    <a href="LINK_PARA_PAGAMENTO" target="_blank" style="text-decoration: none;">
                        <button>
                            ATIVAR AGORA →
                        </button>
                    </a>
                </div>
            </div>
            """, unsafe_allow_html=True
        )
    
    st.markdown(f"---")
    st.info(f"Seu ID de acesso é: **{user_id}**") # Mostra o ID limpo (Document ID)

# FUNÇÃO ATUALIZADA COM ÍCONE
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
#               IMPLEMENTAÇÃO DE LOGIN SIMPLIFICADO
# ----------------------------------------------------

if 'logged_in_user_id' not in st.session_state:
    st.session_state['logged_in_user_id'] = None

st.title("✨ AnuncIA — O Gerador de Anúncios Inteligente")

# Área de Login/Identificação na Sidebar
with st.sidebar:
    st.markdown("## 🔒 Identificação")
    email_input = st.text_input("Seu E-mail (Para controle de uso)", 
                                 placeholder="seu@email.com")
    
    if st.button("Acessar / Simular Login", use_container_width=True):
        if "@" in email_input and "." in email_input:
            user_doc_id = clean_email_to_doc_id(email_input)
            
            st.session_state['logged_in_user_id'] = user_doc_id
            st.success(f"Acesso Liberado!")
        else:
            st.error("Por favor, insira um e-mail válido (ex: 'nome@dominio.com').")

# ----------------------------------------------------
#               INTERFACE PRINCIPAL
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
        if user_id.lower() == clean_email_to_doc_id(DEVELOPER_EMAIL):
             status_text = "⭐ Acesso de Desenvolvedor (PRO Ilimitado)"
        else:
             status_text = "💎 Plano PRO (Uso Ilimitado)"
        st.markdown(f"**Status:** {status_text}")
    else:
        st.markdown(f"**Status:** Você usou **{ads_used}** de **{FREE_LIMIT}** anúncios grátis.")
    st.markdown("---")

    # Botão de Upgrade na Sidebar
    with st.sidebar:
        if not is_pro_user and ads_used > 0:
            st.markdown("---")
            st.markdown("#### Quer Ilimitado? 🚀")
            st.markdown("""
            <div style="text-align: center;" class="pro-button">
                <a href="LINK_PARA_PAGAMENTO" target="_blank">
                    <button>
                        UPGRADE AGORA
                    </button>
                </a>
            </div>
            """, unsafe_allow_html=True)
            st.markdown("---")
        

    if not is_pro_user and ads_used >= FREE_LIMIT:
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

            needs_video = st.checkbox(
                "🚀 Gerar Roteiro de Vídeo (Reels/TikTok) - Exclusivo Plano PRO", 
                value=False,
                disabled=(not is_pro_user)
            )
            
            st.markdown("---")
            # Botão de submissão
            submitted = st.form_submit_button("🔥 Gerar Copy com a IA", use_container_width=True)

        if submitted:
            if not description:
                st.error("Por favor, forneça uma descrição detalhada do produto para a IA.")
            elif needs_video and not is_pro_user:
                st.error("⚠️ **Recurso PRO:** A Geração de Roteiro de Vídeo é exclusiva do Plano PRO. Por favor, desmarque a opção ou faça o upgrade.")
            elif not GEMINI_KEY:
                st.error("⚠️ Erro de Configuração: A chave de API (GEMINI_API_KEY) não está definida no secrets.toml.")
                
                # SIMULAÇÃO DE RESULTADO
                st.warning("Gerando Resultado Simulado para Teste de UI/Contagem. Se a chave estivesse OK, o resultado real apareceria abaixo.")
                
                new_count = increment_ads_count(user_id, user_plan)
                
                st.success(f"✅ Teste de UI/Contagem Sucesso! (Grátis restante: {max(0, FREE_LIMIT - new_count)})")
                
                st.markdown("---")
                st.subheader("Resultado Simulado da Copy")
                
                sim_result = {
                    "titulo_gancho": "NÃO COMPRE ESTE CURSO! (Antes de ver o que ele faz)",
                    "copy_aida": "ATENÇÃO: Cansado de jargões financeiros que só complicam? Você não precisa de milhões para começar. INTERESSE: Este curso desmistifica a bolsa, usando estratégias de baixo risco, ideais para iniciantes. DESEJO: Imagine seu dinheiro trabalhando por você, sem estresse. Em pouco tempo, você terá mais confiança do que 90% dos investidores. AÇÃO: As vagas são limitadas! Clique agora no link para a matrícula e destrave o bônus de iniciante.",
                    "chamada_para_acao": "Clique aqui e comece a investir hoje!",
                    "segmentacao_e_ideias": "1. Pessoas com medo de investir. 2. Aposentados buscando renda extra. 3. Estudantes de economia desiludidos com a teoria."
                }
                
                if is_pro_user and needs_video:
                    sim_result['gancho_video'] = "Pare de perder tempo com vídeos longos!"
                    sim_result['roteiro_basico'] = "Problema (0-5s): Mostra uma tela de gráfico confusa. 'Investir parece complicado, né?'. Solução/Benefício (6-20s): Transição para a tela do curso, mostrando uma interface simples. 'Com nosso método, você aprende o básico em 1 hora e aplica amanhã!'. CTA (21-30s): Link na bio. 'Inscreva-se hoje e ganhe seu primeiro guia de investimentos grátis!'"

                
                display_result_box("🎯", "Título Gancho (Atenção)", sim_result["titulo_gancho"], "title_sim_box")
                display_result_box("📝", "Copy Principal (AIDA)", sim_result["copy_aida"], "copy_sim_box")
                display_result_box("📢", "Chamada para Ação (CTA)", sim_result["chamada_para_acao"], "cta_sim_box")
                display_result_box("💡", "Ideias de Segmentação", sim_result["segmentacao_e_ideias"], "seg_sim_box")
                
                if is_pro_user and needs_video:
                    st.markdown("---")
                    st.subheader("💎 Conteúdo PRO: Roteiro de Vídeo (SIMULADO)")
                    with st.container(border=True): # Destaque visual PRO
                        with st.expander("Clique para ver o Roteiro Completo"):
                            display_result_box("🎬", "Gancho (Hook) de 3 Segundos", sim_result["gancho_video"], "hook_sim_box")
                            display_result_box("🎞️", "Roteiro Completo (30s)", sim_result["roteiro_basico"], "roteiro_sim_box")
                
            else:
                # 1. Chamada REAL à API
                with st.spinner("🧠 A IA está gerando sua estratégia e copy..."):
                    api_result = call_gemini_api(description, product_type, tone, is_pro_user, needs_video)
                    
                    if "error" in api_result:
                        st.error(f"❌ Erro na Geração da Copy: {api_result['error']}")
                        st.info("A contagem de uso **NÃO** foi debitada. Tente novamente.")
                    else:
                        # 2. Incrementa a contagem no Firebase/Simulação
                        new_count = increment_ads_count(user_id, user_plan)
                        
                        # 3. Exibição do resultado
                        st.success(f"✅ Copy Gerada com Sucesso! (Grátis restante: {max(0, FREE_LIMIT - new_count)})")
                        
                        st.markdown("---")
                        st.subheader("Resultado da Copy")
                        
                        # TÍTULO GANCHO
                        display_result_box("🎯", "Título Gancho (Atenção)", api_result.get("titulo_gancho", "N/A"), "title_box")

                        # COPY AIDA
                        display_result_box("📝", "Copy Principal (AIDA)", api_result.get("copy_aida", "N/A"), "copy_box")

                        # CTA
                        display_result_box("📢", "Chamada para Ação (CTA)", api_result.get("chamada_para_acao", "N/A"), "cta_box")
                        
                        # SEGMENTAÇÃO
                        display_result_box("💡", "Ideias de Segmentação", api_result.get("segmentacao_e_ideias", "N/A"), "seg_box")
                        
                        
                        # ROTEIRO DE VÍDEO (EXCLUSIVO PRO)
                        if is_pro_user and needs_video:
                            st.markdown("---")
                            st.subheader("💎 Conteúdo PRO: Roteiro de Vídeo (Reels/TikTok)")
                            with st.container(border=True): # Destaque visual PRO
                                with st.expander("Clique para ver o Roteiro Completo"):
                                    # GANCHO VÍDEO
                                    display_result_box("🎬", "Gancho (Hook) de 3 Segundos", api_result.get("gancho_video", "N/A"), "hook_box")
                                    
                                    # ROTEIRO BÁSICO
                                    display_result_box("🎞️", "Roteiro Completo (30s)", api_result.get("roteiro_basico", "N/A"), "roteiro_box")


# ----------------------------------------------------
#               DEBUG E STATUS FINAL
# ----------------------------------------------------
st.sidebar.markdown("---")
st.sidebar.markdown("##### Status do Sistema")
if st.session_state.get("db") and st.session_state["db"] != "SIMULATED":
    st.sidebar.success("✅ Conexão Firebase OK")
elif st.session_state.get("db") == "SIMULATED":
    st.sidebar.warning("⚠️ Firebase: MODO SIMULADO")

if GEMINI_KEY:
    st.sidebar.success("🔑 Chave de API OK")
else:
    st.sidebar.error("❌ Chave de API AUSENTE")
