import streamlit as st
from supabase import create_client, Client
from datetime import datetime, date
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import pandas as pd
import calendar

# ==========================================
# 1. Configuração Principal e Interface Web
# ==========================================
st.set_page_config(page_title="SIS MEVAM-GYN", page_icon="📅", layout="wide")

esconder_elementos = """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    [data-testid="stToolbar"] {visibility: hidden !important;}
    [data-testid="stDecoration"] {visibility: hidden !important;}
    [data-testid="stStatusWidget"] {visibility: hidden !important;}
    
    /* BLOQUEIO TOTAL E AGRESSIVO DOS ELEMENTOS FLUTUANTES DO STREAMLIT CLOUD (FOTO E COROA) */
    div[data-testid="stStatusWidget"], 
    .viewerBadge_container__1QSob, 
    .styles_viewerBadge__1yG5_, 
    #viewerBadge, 
    iframe[title="streamlitAppBadge"], 
    div.eczcs4p0,
    div[class*="viewerBadge"],
    a[href*="streamlit.cloud"],
    .stApp > div:has(> iframe) {
        display: none !important;
        visibility: hidden !important;
        opacity: 0 !important;
        pointer-events: none !important;
        height: 0 !important;
        width: 0 !important;
        z-index: -999999 !important;
        position: absolute !important;
    }
    
    div[style*="fixed"], div[style*="position: fixed"] {
        z-index: 1 !important;
    }
    
    /* Tabelas com Alta Legibilidade e Cores Intercaladas (Zebrada) */
    .dataframe {
        font-size: 16px !important;
    }
    .dataframe tbody tr:nth-child(even) { background-color: #f2f4f7 !important; }
    .dataframe tbody tr:nth-child(odd) { background-color: #ffffff !important; }
    .dataframe th { background-color: #0d6efd !important; color: white !important; font-size: 16px !important; padding: 10px !important; }
    .dataframe td { padding: 12px 10px !important; }
    
    /* Estilização do Calendário Visual */
    .calendar-table { width: 100%; border-collapse: collapse; text-align: center; font-family: sans-serif; margin-bottom: 15px; }
    .calendar-table th { background-color: #0d6efd; color: white; padding: 10px; font-size: 15px; }
    .calendar-table td { border: 1px solid #dee2e6; padding: 12px; font-size: 15px; width: 14%; vertical-align: top; height: 55px; }
    .day-normal { background-color: #ffffff; color: #333333; }
    .day-ocupado { background-color: #d1e7dd; color: #0f5132; font-weight: bold; border: 2px solid #198754; }
    .day-empty { background-color: #f8f9fa; }

    /* Ocultar elementos na hora de imprimir / Salvar em PDF */
    @media print {
        .stButton, form, .stSelectbox, .stRadio, .stDateInput { display: none !important; }
        .printable-area { display: block !important; width: 100%; font-size: 16px; line-height: 1.6; }
        body { background-color: white; }
    }
    </style>
    """
st.markdown(esconder_elementos, unsafe_allow_html=True)

col_logo, col_titulo = st.columns([2, 8])
with col_logo:
    try:
        st.image("Mevamgyn_logo.jpg", use_column_width=True)
    except:
        st.write("*(Logótipo)*")
with col_titulo:
    st.markdown("### Gestão e Financeiro\n**SIS MEVAM-GYN** 📅 *(Ambiente Seguro LGPD)*")

# ==========================================
# Dicionário de Tradução dos Dias da Semana
# ==========================================
dias_traduzidos = {
    "Monday": "Segunda-feira",
    "Tuesday": "Terça-feira",
    "Wednesday": "Quarta-feira",
    "Thursday": "Quinta-feira",
    "Friday": "Sexta-feira",
    "Saturday": "Sábado",
    "Sunday": "Domingo"
}

# ==========================================
# 2. Funções de E-mail e Registos (Seguras)
# ==========================================
def enviar_alerta_evento(tipo_alerta, titulo_evento, data_hora, departamento, emails_destino):
    if not emails_destino:
        return 
    
    email_remetente = "naifesan@gmail.com"
    senha_app = "ofweerbmpbvnzexs" 

    if tipo_alerta == "novo":
        assunto = f"🚨 SIS MEVAM-GYN: Novo Evento Agendado - {titulo_evento}"
        texto_intro = "Um novo evento foi adicionado ao calendário oficial."
    elif tipo_alerta == "atualizado":
        assunto = f"🔄 SIS MEVAM-GYN: Evento Atualizado - {titulo_evento}"
        texto_intro = "ATENÇÃO: Um evento existente sofreu alterações!"
    elif tipo_alerta == "cancelado":
        assunto = f"❌ SIS MEVAM-GYN: Evento CANCELADO - {titulo_evento}"
        texto_intro = "ATENÇÃO: O evento abaixo foi CANCELADO."

    corpo = f"A Paz! {texto_intro}\n\n📌 Evento: {titulo_evento}\n📅 Data/Hora: {data_hora}\n🏢 Departamento: {departamento}\n\nAceda ao painel para mais detalhes."

    try:
        servidor = smtplib.SMTP('smtp.gmail.com', 587)
        servidor.starttls()
        servidor.login(email_remetente, senha_app)
        for destinatario in emails_destino:
            msg = MIMEMultipart()
            msg['From'] = email_remetente
            msg['To'] = destinatario
            msg['Subject'] = assunto
            msg.attach(MIMEText(corpo, 'plain', 'utf-8'))
            servidor.sendmail(email_remetente, destinatario, msg.as_string())
        servidor.quit()
    except Exception:
        pass

# ==========================================
# 3. Base de Dados (Supabase)
# ==========================================
URL_SUPABASE = "https://sbitcxnqmjvnfwxccxwq.supabase.co"
CHAVE_SUPABASE = "sb_publishable_sZmAEEZihVmm3ts51XogJg_ECUc4rmg"

@st.cache_resource
def iniciar_supabase():
    return create_client(URL_SUPABASE, CHAVE_SUPABASE)
supabase = iniciar_supabase()

def registrar_log(acao):
    usuario = st.session_state.get("usuario_logado", "Desconhecido")
    try:
        supabase.table("logs_auditoria").insert({"usuario": usuario, "acao": acao}).execute()
    except Exception:
        pass

# ==========================================
# 4. Ecrã de Login Obrigatório (Autenticação Segura)
# ==========================================
if "usuario_logado" not in st.session_state:
    st.session_state["usuario_logado"] = None

if st.session_state["usuario_logado"] is None:
    st.markdown("---")
    st.subheader("🔐 Acesso Restrito da Liderança")
    st.info("🔒 Sistema protegido em conformidade com as diretrizes de segurança de dados e LGPD.")
    
    try:
        res_admins_login = supabase.table("administradores").select("id, nome, senha").execute()
        admins_cadastrados = res_admins_login.data if res_admins_login.data else []
    except Exception:
        admins_cadastrados = []
        
    lista_nomes = ["Ricardo César Santana", "Admin Geral"] + [a['nome'] for a in admins_cadastrados if a['nome'] not in ["Ricardo César Santana", "Admin Geral"]]
        
    with st.form("login_form"):
        usuario_selecionado = st.selectbox("Quem está a aceder?", lista_nomes)
        senha_digitada = st.text_input("Palavra-passe de Acesso", type="password")
        if st.form_submit_button("Entrar no Sistema", use_container_width=True):
            if (usuario_selecionado in ["Ricardo César Santana", "Admin Geral"]) and senha_digitada == "mevam314107":
                st.session_state["usuario_logado"] = usuario_selecionado
                registrar_log(f"Login efetuado ({usuario_selecionado} - Master)")
                st.rerun()
            else:
                admin_obj = next((a for a in admins_cadastrados if a['nome'] == usuario_selecionado), None)
                if admin_obj and admin_obj.get('senha') == senha_digitada:
                    st.session_state["usuario_logado"] = usuario_selecionado
                    registrar_log(f"Login efetuado ({usuario_selecionado})")
                    st.rerun()
                else:
                    st.error("❌ Credenciais inválidas. Acesso negado.")
    st.stop()

# ==========================================
# 5. MENU PRINCIPAL MOBILE-FIRST (Com Acesso Restrito de Auditoria)
# ==========================================
st.markdown("---")
col_user, col_logout = st.columns([7, 3])
with col_user:
    st.info(f"👤 **{st.session_state['usuario_logado']}** | 🔒 Sessão Autenticada")
with col_logout:
    if st.button("Sair", use_container_width=True):
        registrar_log("Terminou sessão")
        st.session_state["usuario_logado"] = None
        st.rerun()

# Lista base de módulos visíveis para todos
lista_modulos = [
    "📋 Agenda de Eventos", 
    "➕ Criar Novo Evento", 
    "✏️ Editar / Excluir Evento", 
    "👥 Inscrições e Auditoria", 
    "📜 Cadastro de Membros & Credo (OCR)",
    "📊 Dashboard Financeiro", 
    "🖨️ Relatórios e PDF",
    "⚙️ Cadastros (Equipa/Deptos)"
]

if st.session_state["usuario_logado"] in ["Ricardo César Santana", "Admin Geral"]:
    lista_modulos.append("🔍 Auditoria do Sistema (Restrito)")

menu = st.selectbox("📌 SELECIONE O MÓDULO:", lista_modulos)
st.markdown("---")

try:
    res_deptos = supabase.table("departamentos").select("*").execute()
    lista_deptos_obj = res_deptos.data if res_deptos.data else []
    lista_deptos_nomes = [d['nome'] for d in lista_deptos_obj] if lista_deptos_obj else ["Geral"]
    mapa_responsaveis = {d['nome']: d.get('responsavel', 'Geral') for d in lista_deptos_obj}
except Exception:
    lista_deptos_nomes = ["Geral"]
    mapa_responsaveis = {"Geral": "Geral"}

try:
    res_eventos = supabase.table("eventos").select("*").order("data_inicio", desc=False).execute()
    eventos = res_eventos.data if res_eventos.data else []
except Exception:
    eventos = []

# ==========================================
# MÓDULOS DO SISTEMA
# ==========================================

if menu == "📋 Agenda de Eventos":
    st.subheader("Eventos Agendados e Calendário")
    
    modo_agenda = st.radio("Formato de Visualização:", ["Lista Detalhada", "Visão Calendário (Mensal / Anual)"], horizontal=True)
    
    if modo_agenda == "Visão Calendário (Mensal / Anual)":
        col_cal1, col_cal2 = st.columns(2)
        with col_cal1: ano_sel = st.selectbox("Ano:", [2026, 2027, 2028], index=0)
        with col_cal2: mes_sel = st.selectbox("Mês:", ["Todos (Visão Anual)", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"], index=datetime.now().month)
        
        mes_num = None if mes_sel == "Todos (Visão Anual)" else ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"].index(mes_sel) + 1
        
        eventos_calendario = []
        for ev in eventos:
            d_obj = datetime.strptime(ev['data_inicio'][:10], "%Y-%m-%d")
            if d_obj.year == ano_sel and (mes_num is None or d_obj.month == mes_num):
                resp = mapa_responsaveis.get(ev.get('departamento', 'Geral'), 'Equipa')
                dia_ingles = d_obj.strftime("%A")
                dia_pt = dias_traduzidos.get(dia_ingles, dia_ingles)
                
                eventos_calendario.append({
                    "Data": d_obj.strftime("%d/%m/%Y"),
                    "Dia": dia_pt,
                    "Horário": ev['data_inicio'][11:16],
                    "Evento": ev['titulo'],
                    "Departamento / Responsável": f"{ev.get('departamento', 'Geral')} / {resp}",
                    "Criado ou alterado por": ev.get('criado_por', st.session_state['usuario_logado'])
                })
        
        if eventos_calendario:
            df_cal = pd.DataFrame(eventos_calendario)
            st.dataframe(df_cal, use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum evento agendado para o período selecionado.")
    else:
        if eventos:
            for ev in eventos:
                data_br = datetime.strptime(ev['data_inicio'][:10], "%Y-%m-%d").strftime("%d/%m/%Y")
                hora_str = ev['data_inicio'][11:16]
                res_vagas = supabase.table("inscricoes").select("id").eq("evento_id", ev['id']).execute()
                ocupadas = len(res_vagas.data) if res_vagas.data else 0
                
                resp_depto = mapa_responsaveis.get(ev.get('departamento', 'Geral'), 'Líder')
                vagas_val = ev.get('limite_vagas')
                vagas_txt = "Ilimitado (Livre Acesso)" if (vagas_val is None or int(vagas_val) == 0) else f"{int(vagas_val) - ocupadas} vagas restantes"
                
                with st.expander(f"📌 {ev['titulo']} - ({data_br})"):
                    st.write(f"🏢 **Departamento / Responsável:** {ev.get('departamento', 'Geral')} / {resp_depto}")
                    st.write(f"📅 **Data e Hora:** {data_br} às {hora_str}")
                    st.write(f"✍️ **Criado ou alterado por:** {ev.get('criado_por', st.session_state['usuario_logado'])}")
                    st.write(f"💰 **Valor Base (Inteira):** R$ {ev['valor_inscricao']}")
                    st.write(f"👥 **Vagas:** {vagas_txt}")
                    if ev.get('historico_alteracoes'):
                        st.info(f"📜 **Histórico de Auditoria:**\n{ev.get('historico_alteracoes')}")
        else:
            st.info("Nenhum evento marcado no momento.")

elif menu == "➕ Criar Novo Evento":
    st.subheader("Agendar Novo Evento e Calendário de Ocupação")
    
    st.markdown("---")
    st.markdown("#### 🗓️ Calendário Visual de Ocupação de Datas")
    col_vc1, col_vc2 = st.columns(2)
    with col_vc1:
        ano_c_vis = st.selectbox("Ano de Referência:", [2026, 2027, 2028], index=0, key="ano_c_vis")
    with col_vc2:
        meses_lista_vis = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
        mes_c_nome = st.selectbox("Mês de Referência:", meses_lista_vis, index=datetime.now().month - 1, key="mes_c_nome")
        mes_c_num = meses_lista_vis.index(mes_c_nome) + 1

    dias_ocupados_set = set()
    for ev in eventos:
        try:
            d_ev_obj = datetime.strptime(ev['data_inicio'][:10], "%Y-%m-%d")
            if d_ev_obj.year == ano_c_vis and d_ev_obj.month == mes_c_num:
                dias_ocupados_set.add(d_ev_obj.day)
        except:
            pass

    matriz_mes = calendar.monthcalendar(ano_c_vis, mes_c_num)
    tabela_html = """
    <table class="calendar-table">
        <thead>
            <tr>
                <th>Seg</th><th>Ter</th><th>Qua</th><th>Qui</th><th>Sex</th><th>Sáb</th><th>Dom</th>
            </tr>
        </thead>
        <tbody>
    """
    for semana in matriz_mes:
        tabela_html += "<tr>"
        for dia in semana:
            if dia == 0:
                tabela_html += "<td class='day-empty'></td>"
            else:
                if dia in dias_ocupados_set:
                    tabela_html += f"<td class='day-ocupado'>📅 {dia}<br><small style='font-size:10px;'>Ocupado</small></td>"
                else:
                    tabela_html += f"<td class='day-normal'>{dia}</td>"
        tabela_html += "</tr>"
    tabela_html += "</tbody></table>"
    st.markdown(tabela_html, unsafe_allow_html=True)
    st.caption("🟢 **Dias destacados em verde** já possuem eventos agendados neste mês. Consulte antes de preencher o formulário abaixo.")
    st.markdown("---")

    with st.form("form_evento_novo", clear_on_submit=True):
        st.markdown("#### 📝 Preencha os dados do novo evento:")
        titulo = st.text_input("Título do Evento")
        departamento = st.selectbox("Departamento Responsável", lista_deptos_nomes)
        data_inicio = st.date_input("Data", format="DD/MM/YYYY")
        hora_inicio = st.time_input("Hora")
        valor = st.number_input("Valor de Inscrição Base (R$)", min_value=0.0, format="%.2f")
        
        tipo_vagas_opcao = st.radio("Controlo de Vagas:", ["Livre Acesso (Sem Limite de Vagas)", "Definir Número Fixo de Vagas"], horizontal=True)
        if tipo_vagas_opcao == "Definir Número Fixo de Vagas":
            vagas = int(st.number_input("Qual o limite de vagas?", min_value=1, value=50, step=1))
        else:
            vagas = 0
        
        if st.form_submit_button("Salvar na Agenda", use_container_width=True):
            data_busca = str(data_inicio)
            busca_conflito = supabase.table("eventos").select("titulo, departamento").gte("data_inicio", f"{data_busca}T00:00:00").lte("data_inicio", f"{data_busca}T23:59:59").execute()
            
            conflito_encontrado = False
            nome_conflito = ""
            if busca_conflito.data:
                for ev_existente in busca_conflito.data:
                    if ev_existente['departamento'] != departamento:
                        conflito_encontrado = True
                        nome_conflito = ev_existente['titulo']
                        break
            
            if conflito_encontrado:
                st.error(f"❌ Conflito de Agenda: O departamento '{ev_existente['departamento']}' já possui o evento '{nome_conflito}' agendado nesta data.")
            else:
                usuario_atual = st.session_state['usuario_logado']
                agora_str = datetime.now().strftime('%d/%m/%Y às %H:%M')
                
                novo_evento = {
                    "titulo": str(titulo), 
                    "data_inicio": f"{data_inicio}T{hora_inicio}", 
                    "departamento": str(departamento), 
                    "valor_inscricao": float(valor), 
                    "limite_vagas": int(vagas),
                    "criado_por": f"{usuario_atual} em {agora_str}",
                    "historico_alteracoes": f"[{agora_str}] Criado por {usuario_atual}"
                }
                
                try:
                    supabase.table("eventos").insert(novo_evento).execute()
                    registrar_log(f"Criou o evento: '{titulo}' para o depto '{departamento}'")
                    
                    res_admins = supabase.table("administradores").select("email").execute()
                    lista_emails = [a['email'] for a in res_admins.data if a.get('email')]
                    enviar_alerta_evento("novo", titulo, f"{data_inicio.strftime('%d/%m/%Y')} às {hora_inicio}", departamento, lista_emails)
                    st.success("✅ Evento gravado com sucesso e formulário limpo!")
                except Exception as e:
                    st.error(f"❌ Erro ao gravar na base de dados: {e}")

elif menu == "✏️ Editar / Excluir Evento":
    st.subheader("Corrigir ou Cancelar (Com Auditoria Obrigatória)")
    if eventos:
        opcoes = {f"{e['titulo']} ({datetime.strptime(e['data_inicio'][:10], '%Y-%m-%d').strftime('%d/%m/%Y')})": e for e in eventos}
        evento_selecionado = st.selectbox("Escolha o evento:", list(opcoes.keys()))
        dados_ev = opcoes[evento_selecionado]
        
        with st.form("form_editar_excluir", clear_on_submit=True):
            st.warning("⚠️ Qualquer alteração ou exclusão exige justificativa para fins de auditoria.")
            novo_titulo = st.text_input("Alterar Título", value=dados_ev['titulo'])
            nova_data = st.date_input("Alterar Data", value=datetime.strptime(dados_ev['data_inicio'][:10], "%Y-%m-%d").date(), format="DD/MM/YYYY")
            justificativa_ev = st.text_area("Justificativa da Alteração/Exclusão (Obrigatório)", placeholder="Ex: Mudança de horário aprovada pela liderança")
            
            btn_atualizar = st.form_submit_button("Atualizar Evento", use_container_width=True)
            btn_excluir = st.form_submit_button("❌ Excluir Evento", use_container_width=True)
            
            if btn_atualizar:
                if not justificativa_ev.strip():
                    st.error("❌ Preencha a justificativa obrigatória para atualizar o evento.")
                else:
                    usuario_atual = st.session_state['usuario_logado']
                    agora_str = datetime.now().strftime('%d/%m/%Y às %H:%M')
                    hora_atual = dados_ev['data_inicio'][11:19]
                    historico_atual = dados_ev.get('historico_alteracoes', '')
                    novo_historico = f"{historico_atual}\n[{agora_str}] Atualizado por {usuario_atual}: {justificativa_ev}".strip()
                    
                    supabase.table("eventos").update({
                        "titulo": str(novo_titulo), 
                        "data_inicio": f"{nova_data}T{hora_atual}",
                        "criado_por": f"{usuario_atual} em {agora_str}",
                        "historico_alteracoes": str(novo_historico)
                    }).eq("id", dados_ev['id']).execute()
                    
                    registrar_log(f"Atualizou evento para '{novo_titulo}'. Motivo: {justificativa_ev}")
                    st.success("✅ Evento atualizado e auditado com sucesso!")
                
            if btn_excluir:
                if not justificativa_ev.strip():
                    st.error("❌ Preencha a justificativa obrigatória para excluir o evento.")
                else:
                    supabase.table("eventos").delete().eq("id", dados_ev['id']).execute()
                    registrar_log(f"Cancelou evento '{dados_ev['titulo']}'. Motivo: {justificativa_ev}")
                    st.warning("🗑️ Evento excluído e registado na auditoria!")
    else:
        st.info("Nenhum evento agendado.")

elif menu == "👥 Inscrições e Auditoria":
    st.subheader("Gestão de Inscrições e Consentimento LGPD")
    if eventos:
        opcoes_ev_insc = {f"{e['titulo']} ({e['data_inicio'][:10]})": e for e in eventos}
        ev_selecionado_insc = st.selectbox("Selecione o Evento:", list(opcoes_ev_insc.keys()))
        dados_ev = opcoes_ev_insc[ev_selecionado_insc]
        valor_base = dados_ev['valor_inscricao']
        
        sub_nova, sub_editar = st.tabs(["➕ Nova Inscrição", "✏️ Editar/Excluir"])
        
        with sub_nova:
            with st.form("form_nova_inscricao_limpa", clear_on_submit=True):
                nome_insc = st.text_input("Nome Completo")
                tel_insc = st.text_input("Telefone")
                tipo_ing = st.selectbox("Tipo de Ingresso", ["Inteira", "Meia (5-11 anos)", "Cortesia/Isento"])
                forma_pag = st.selectbox("Forma de Pagamento", ["Pix", "Cartão de Crédito", "Cartão de Débito", "Dinheiro", "A Receber"])
                status_pag = st.radio("Status", ["Confirmado", "Pendente"])
                
                st.caption("🔒 **Conformidade LGPD:** Ao cadastrar, confirma-se o consentimento do titular para o tratamento dos dados estritamente para fins de organização e controlo financeiro deste evento.")
                concordou_lgpd = st.checkbox("Declaro que o participante está ciente e concorda com o tratamento dos seus dados para esta finalidade.")

                if st.form_submit_button("Confirmar Inscrição", use_container_width=True):
                    if not concordou_lgpd:
                        st.error("❌ É obrigatório obter o consentimento (LGPD) do participante para prosseguir com a inscrição.")
                    else:
                        valor_final = valor_base if "Inteira" in tipo_ing else (valor_base / 2 if "Meia" in tipo_ing else 0.0)
                        nova_insc = {
                            "evento_id": dados_ev['id'], "nome": str(nome_insc), "telefone": str(tel_insc),
                            "forma_pagamento": str(forma_pag), "status_pagamento": str(status_pag),
                            "tipo_ingresso": str(tipo_ing), "valor_pago": float(valor_final),
                            "observacoes": "Consentimento LGPD coletado."
                        }
                        supabase.table("inscricoes").insert(nova_insc).execute()
                        registrar_log(f"Inscreveu {nome_insc} no evento {dados_ev['titulo']}")
                        st.success("✅ Inscrição Registada em conformidade com a LGPD!")
                    
        with sub_editar:
            res_inscritos = supabase.table("inscricoes").select("*").eq("evento_id", dados_ev['id']).execute()
            inscritos = res_inscritos.data if res_inscritos.data else []
            
            if inscritos:
                opc_inscritos = {f"{i['nome']} - {i['status_pagamento']}": i for i in inscritos}
                participante_sel = st.selectbox("Selecione o Participante:", list(opc_inscritos.keys()))
                dados_participante = opc_inscritos[participante_sel]
                
                with st.form("form_editar_inscricao_limpa", clear_on_submit=True):
                    st.warning("⚠️ Alterações exigem justificativa.")
                    novo_nome = st.text_input("Nome", value=dados_participante['nome'])
                    novo_tel = st.text_input("Telefone", value=dados_participante.get('telefone', ''))
                    
                    lista_tipos = ["Inteira", "Meia (5-11 anos)", "Cortesia/Isento"]
                    idx_tipo = lista_tipos.index(dados_participante.get('tipo_ingresso', 'Inteira')) if dados_participante.get('tipo_ingresso') in lista_tipos else 0
                    novo_tipo = st.selectbox("Tipo", lista_tipos, index=idx_tipo)
                    
                    lista_formas = ["Pix", "Cartão de Crédito", "Cartão de Débito", "Dinheiro", "A Receber"]
                    idx_forma = lista_formas.index(dados_participante.get('forma_pagamento', 'Pix')) if dados_participante.get('forma_pagamento') in lista_formas else 0
                    nova_forma = st.selectbox("Pagamento", lista_formas, index=idx_forma)
                    
                    idx_status = 0 if dados_participante.get('status_pagamento') == 'Confirmado' else 1
                    novo_status = st.radio("Status", ["Confirmado", "Pendente"], index=idx_status)
                    
                    justificativa = st.text_area("Justificativa da Alteração/Exclusão (Obrigatório)")
                    
                    btn_atualizar_insc = st.form_submit_button("Atualizar Cadastro", use_container_width=True)
                    btn_excluir_insc = st.form_submit_button("❌ Excluir Inscrição", use_container_width=True)
                    
                    if btn_atualizar_insc:
                        if not justificativa.strip():
                            st.error("❌ Preencha a justificativa.")
                        else:
                            valor_final_edit = valor_base if "Inteira" in novo_tipo else (valor_base / 2 if "Meia" in novo_tipo else 0.0)
                            historico_obs = f"{dados_participante.get('observacoes', '')}\n[{datetime.now().strftime('%d/%m %H:%M')}] {st.session_state['usuario_logado']}: {justificativa}".strip()
                            
                            supabase.table("inscricoes").update({
                                "nome": str(novo_nome), "telefone": str(novo_tel), "tipo_ingresso": str(novo_tipo),
                                "forma_pagamento": str(nova_forma), "status_pagamento": str(novo_status),
                                "valor_pago": float(valor_final_edit), "observacoes": str(historico_obs)
                            }).eq("id", dados_participante['id']).execute()
                            registrar_log(f"Atualizou a inscrição de {novo_nome}. Motivo: {justificativa}")
                            st.success("✅ Atualizado com sucesso!")
                            
                    if btn_excluir_insc:
                        if not justificativa.strip():
                            st.error("❌ Preencha a justificativa.")
                        else:
                            supabase.table("inscricoes").delete().eq("id", dados_participante['id']).execute()
                            registrar_log(f"Excluiu {dados_participante['nome']}. Motivo: {justificativa}")
                            st.warning("🗑️ Inscrição excluída com sucesso!")
            else:
                st.info("Nenhum participante inscrito ainda.")
    else:
        st.info("Crie um evento primeiro.")

elif menu == "📊 Dashboard Financeiro":
    st.subheader("Dashboard Financeiro")
    if eventos:
        ev_fin = st.selectbox("Analisar Evento:", list({f"{e['titulo']}": e for e in eventos}.keys()))
        evento_selecionado = next(e for e in eventos if e['titulo'] == ev_fin)
        ev_id = evento_selecionado['id']
        
        res_insc = supabase.table("inscricoes").select("*").eq("evento_id", ev_id).execute()
        res_custos = supabase.table("custos_evento").select("*").eq("evento_id", ev_id).execute()
        inscricoes = res_insc.data if res_insc.data else []
        custos = res_custos.data if res_custos.data else []
        
        total_pix = sum(i['valor_pago'] for i in inscricoes if i['forma_pagamento'] == 'Pix' and i['status_pagamento'] == 'Confirmado')
        total_cc = sum(i['valor_pago'] for i in inscricoes if i['forma_pagamento'] == 'Cartão de Crédito' and i['status_pagamento'] == 'Confirmado')
        total_cd = sum(i['valor_pago'] for i in inscricoes if i['forma_pagamento'] == 'Cartão de Débito' and i['status_pagamento'] == 'Confirmado')
        total_dinheiro = sum(i['valor_pago'] for i in inscricoes if i['forma_pagamento'] == 'Dinheiro' and i['status_pagamento'] == 'Confirmado')
        a_receber = sum(i['valor_pago'] for i in inscricoes if i['status_pagamento'] == 'Pendente')
        
        receita_total = total_pix + total_cc + total_cd + total_dinheiro
        despesa_total = sum(c['valor'] for c in custos)
        resultado_final = receita_total - despesa_total
        
        qtd_inteira = len([i for i in inscricoes if "Inteira" in i['tipo_ingresso']])
        qtd_meia = len([i for i in inscricoes if "Meia" in i['tipo_ingresso']])
        qtd_cortesia = len([i for i in inscricoes if "Cortesia" in i['tipo_ingresso']])
        
        st.markdown(f"#### Resultado Final:\n### R$ {resultado_final:,.2f}")
        st.success(f"💰 Receita: R$ {receita_total:,.2f}")
        st.error(f"📉 Despesa: R$ {despesa_total:,.2f}")
        st.warning(f"⏳ A Receber: R$ {a_receber:,.2f}")
        
        with st.expander("➕ Lançar Nova Despesa"):
            with st.form("form_despesa_limpa", clear_on_submit=True):
                desc_custo = st.text_input("Descrição da Despesa")
                valor_custo = st.number_input("Valor (R$)", min_value=0.0)
                if st.form_submit_button("Registar Custo", use_container_width=True):
                    supabase.table("custos_evento").insert({"evento_id": ev_id, "descricao": str(desc_custo), "valor": float(valor_custo)}).execute()
                    st.success("Despesa registada e campos limpos!")
                    
        st.write("**Receitas por Meio de Pagamento**")
        dados_grafico = pd.DataFrame({
            "Forma": ["Pix", "Cartão", "Dinheiro", "A Receber"],
            "Valor": [total_pix, (total_cc + total_cd), total_dinheiro, a_receber]
        })
        st.bar_chart(dados_grafico.set_index("Forma"))
        st.caption(f"**Público:** {qtd_inteira} Inteiras | {qtd_meia} Meias | {qtd_cortesia} Cortesias")
    else:
        st.info("Nenhum evento cadastrado.")

elif menu == "🖨️ Relatórios e PDF":
    st.subheader("Central de Relatórios e PDF Profissional")
    tipo_relatorio_geral = st.radio("Selecione o tipo de relatório:", ["Relatório de Inscritos por Evento", "Relatório de Eventos por Período"])
    
    if tipo_relatorio_geral == "Relatório de Inscritos por Evento":
        if eventos:
            ev_rel = st.selectbox("Selecione o Evento:", list({f"{e['titulo']}": e for e in eventos}.keys()))
            tipo_sub = st.radio("Filtro:", ["Lista Completa de Participantes", "Inadimplentes (A Receber)", "Extrato Financeiro e Resumo"])
            
            if st.button("Gerar Visualização para Impressão/PDF", use_container_width=True):
                ev_id_rel = next(e['id'] for e in eventos if e['titulo'] == ev_rel)
                
                st.markdown("<div class='printable-area'>", unsafe_allow_html=True)
                
                col_p1, col_p2 = st.columns([2, 8])
                with col_p1:
                    try:
                        st.image("Mevamgyn_logo.jpg", width=110)
                    except:
                        st.write("*(MEVAM GYN)*")
                with col_p2:
                    st.markdown(f"### MINISTÉRIO MEVAM GYN\n**Evento:** {ev_rel}\n**Relatório:** {tipo_sub}")
                st.markdown(f"*Emitido em:* {datetime.now().strftime('%d/%m/%Y às %H:%M')} por **{st.session_state['usuario_logado']}**")
                st.markdown("---")
                
                if tipo_sub in ["Lista Completa de Participantes", "Inadimplentes (A Receber)"]:
                    res_insc_rel = supabase.table("inscricoes").select("*").eq("evento_id", ev_id_rel).execute()
                    dados = res_insc_rel.data if res_insc_rel.data else []
                    
                    if tipo_sub == "Inadimplentes (A Receber)":
                        dados = [d for d in dados if d['status_pagamento'] == 'Pendente']
                        
                    if dados:
                        df = pd.DataFrame(dados)[['nome', 'telefone', 'tipo_ingresso', 'forma_pagamento', 'status_pagamento', 'valor_pago']]
                        df.columns = ['Nome', 'Telefone', 'Tipo', 'Meio', 'Status', 'Valor (R$)']
                        st.dataframe(df, use_container_width=True, hide_index=True)
                    else:
                        st.warning("Nenhum registo encontrado.")
                        
                elif tipo_sub == "Extrato Financeiro e Resumo":
                    res_insc = supabase.table("inscricoes").select("*").eq("evento_id", ev_id_rel).execute()
                    res_custos = supabase.table("custos_evento").select("*").eq("evento_id", ev_id_rel).execute()
                    inscricoes = res_insc.data if res_insc.data else []
                    custos = res_custos.data if res_custos.data else []
                    
                    tot_rec = sum(i['valor_pago'] for i in inscricoes if i['status_pagamento'] == 'Confirmado')
                    tot_esp = sum(c['valor'] for c in custos)
                    tot_pend = sum(i['valor_pago'] for i in inscricoes if i['status_pagamento'] == 'Pendente')
                    
                    st.markdown(f"#### 💰 Resumo Financeiro Consolidado")
                    st.write(f"- **Receita Confirmada:** R$ {tot_rec:,.2f}")
                    st.write(f"- **Total de Custos/Despesas:** R$ {tot_esp:,.2f}")
                    st.write(f"- **Resultado Líquido:** R$ {tot_rec - tot_esp:,.2f}")
                    st.write(f"- **Valores Pendentes (A Receber):** R$ {tot_pend:,.2f}")
                    
                    if custos:
                        st.markdown("#### 📉 Lançamento de Custos")
                        df_c = pd.DataFrame(custos)[['descricao', 'valor']]
                        df_c.columns = ['Descrição da Despesa', 'Valor (R$)']
                        st.dataframe(df_c, use_container_width=True, hide_index=True)

                st.markdown("---")
                st.caption("📄 **Como salvar em PDF:** Pressione **Ctrl + P** (ou partilhe/imprima no telemóvel) e selecione **'Guardar como PDF'**.")
                st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.info("Nenhum evento registado.")
            
    else:
        st.subheader("Relatório de Eventos por Período (Com Auditoria e Responsáveis)")
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            data_ini_filtro = st.date_input("Data Inicial", value=date.today(), format="DD/MM/YYYY")
        with col_d2:
            data_fim_filtro = st.date_input("Data Final", value=date.today(), format="DD/MM/YYYY")
        
        if st.button("Gerar Relatório de Eventos", use_container_width=True):
            eventos_filtrados = []
            for ev in eventos:
                d_ev_str = ev['data_inicio'][:10]
                d_ev_obj = datetime.strptime(d_ev_str, "%Y-%m-%d").date()
                if data_ini_filtro <= d_ev_obj <= data_fim_filtro:
                    depto_nome = ev.get('departamento', 'Geral')
                    resp = mapa_responsaveis.get(depto_nome, 'Líder')
                    criador = ev.get('criado_por', f"{st.session_state['usuario_logado']} em {datetime.now().strftime('%d/%m/%Y às %H:%M')}")
                    vagas_val = ev.get('limite_vagas')
                    eventos_filtrados.append({
                        "Título do Evento": ev['titulo'],
                        "Data / Horário": f"{d_ev_obj.strftime('%d/%m/%Y')} às {ev['data_inicio'][11:16]}",
                        "Departamento / Responsável": f"{depto_nome} / {resp}",
                        "Criado ou alterado por": criador,
                        "Valor Base": f"R$ {ev['valor_inscricao']:.2f}",
                        "Vagas": "Livre" if (vagas_val is None or int(vagas_val) == 0) else vagas_val
                    })
            
            st.markdown("<div class='printable-area'>", unsafe_allow_html=True)
            col_p1, col_p2 = st.columns([2, 8])
            with col_p1:
                try:
                    st.image("Mevamgyn_logo.jpg", width=110)
                except:
                    st.write("*(MEVAM GYN)*")
            with col_p2:
                st.markdown(f"### MINISTÉRIO MEVAM GYN\n**Relatório de Eventos por Período e Auditoria**\n*Período:* {data_ini_filtro.strftime('%d/%m/%Y')} a {data_fim_filtro.strftime('%d/%m/%Y')}")
            st.markdown(f"*Emitido por:* **{st.session_state['usuario_logado']}** em {datetime.now().strftime('%d/%m/%Y às %H:%M')}")
            st.markdown("---")
            
            if eventos_filtrados:
                df_evs = pd.DataFrame(eventos_filtrados)
                st.dataframe(df_evs, use_container_width=True, hide_index=True)
            else:
                st.warning("Nenhum evento encontrado no período selecionado.")
                
            st.markdown("---")
            st.caption("📄 **Como salvar em PDF:** Pressione **Ctrl + P** (ou partilhe/imprima no telemóvel) e selecione **'Guardar como PDF'**.")
            st.markdown("</div>", unsafe_allow_html=True)

elif menu == "⚙️ Cadastros (Equipa/Deptos)":
    st.subheader("Cadastros do Sistema")
    sub_cad_novo, sub_cad_edit = st.tabs(["➕ Novos", "✏️ Editar/Excluir"])
    
    with sub_cad_novo:
        st.write("**👨‍💼 Novo Administrador**")
        with st.form("form_admin_novo_limpo", clear_on_submit=True):
            nome_admin = st.text_input("Nome Completo")
            telefone_admin = st.text_input("Telefone")
            email_admin = st.text_input("E-mail")
            senha_admin = st.text_input("Palavra-passe de Acesso", type="password")
            if st.form_submit_button("Gravar Administrador", use_container_width=True):
                if len(senha_admin) >= 4:
                    supabase.table("administradores").insert({"nome": str(nome_admin), "telefone": str(telefone_admin), "email": str(email_admin), "senha": str(senha_admin)}).execute()
                    registrar_log(f"Cadastrou administrador: '{nome_admin}'")
                    st.success("✅ Administrador salvo e campos limpos!")
                else:
                    st.error("A palavra-passe deve ter no mínimo 4 dígitos!")
                    
        st.write("**🏢 Novo Departamento**")
        with st.form("form_depto_novo_limpo", clear_on_submit=True):
            nome_depto = st.text_input("Nome do Departamento")
            resp_depto = st.text_input("Líder / Responsável")
            if st.form_submit_button("Gravar Departamento", use_container_width=True):
                supabase.table("departamentos").insert({"nome": str(nome_depto), "responsavel": str(resp_depto)}).execute()
                registrar_log(f"Cadastrou departamento: '{nome_depto}'")
                st.success("✅ Departamento salvo e campos limpos!")

    with sub_cad_edit:
        st.write("**👨‍💼 Editar Administrador**")
        try:
            res_admins = supabase.table("administradores").select("*").execute()
            admins = res_admins.data if res_admins.data else []
            if admins:
                opcoes_admins = {a['nome']: a for a in admins}
                admin_sel = st.selectbox("Selecione o Admin:", list(opcoes_admins.keys()))
                d_admin = opcoes_admins[admin_sel]
                
                with st.form("form_edit_admin", clear_on_submit=True):
                    n_nome = st.text_input("Nome", value=d_admin['nome'])
                    n_email = st.text_input("E-mail", value=d_admin.get('email', ''))
                    n_senha = st.text_input("Nova Palavra-passe (vazio para manter)", type="password")
                    
                    btn_atualizar_adm = st.form_submit_button("Atualizar", use_container_width=True)
                    btn_excluir_adm = st.form_submit_button("❌ Excluir", use_container_width=True)
                    
                    if btn_atualizar_adm:
                        upd_data = {"nome": str(n_nome), "email": str(n_email)}
                        if n_senha: upd_data["senha"] = str(n_senha)
                        supabase.table("administradores").update(upd_data).eq("id", d_admin['id']).execute()
                        st.success("Atualizado com sucesso!")
                    if btn_excluir_adm:
                        supabase.table("administradores").delete().eq("id", d_admin['id']).execute()
                        st.warning("Excluído com sucesso!")
        except Exception:
            pass
            
        st.write("**🏢 Editar Departamento**")
        try:
            if lista_deptos_nomes and lista_deptos_nomes != ["Geral"]:
                opcoes_deptos = {d['nome']: d for d in lista_deptos_obj}
                depto_sel = st.selectbox("Selecione o Depto:", list(opcoes_deptos.keys()))
                d_depto = opcoes_deptos[depto_sel]
                
                with st.form("form_edit_depto", clear_on_submit=True):
                    n_nome_d = st.text_input("Nome", value=d_depto['nome'])
                    n_resp = st.text_input("Responsável", value=d_depto.get('responsavel', ''))
                    
                    btn_atualizar_dep = st.form_submit_button("Atualizar", use_container_width=True)
                    btn_excluir_dep = st.form_submit_button("❌ Excluir", use_container_width=True)
                    
                    if btn_atualizar_dep:
                        supabase.table("departamentos").update({"nome": str(n_nome_d), "responsavel": str(n_resp)}).eq("id", d_depto['id']).execute()
                        st.success("Atualizado com sucesso!")
                    if btn_excluir_dep:
                        supabase.table("departamentos").delete().eq("id", d_depto['id']).execute()
                        st.warning("Excluído!")
        except Exception:
            pass

elif menu == "🔍 Auditoria do Sistema (Restrito)":
    st.subheader("🔍 Central de Auditoria Geral (Acesso Exclusivo - Master)")
    st.write("Registo completo de todas as ações, acessos e movimentações efetuadas por qualquer administrador no sistema.")
    
    try:
        res_logs = supabase.table("logs_auditoria").select("*").order("id", desc=True).limit(100).execute()
        logs_dados = res_logs.data if res_logs.data else []
        
        if logs_dados:
            df_logs = pd.DataFrame(logs_dados)
            if 'created_at' in df_logs.columns:
                df_logs = df_logs[['created_at', 'usuario', 'acao']]
                df_logs.columns = ['Data/Hora', 'Administrador', 'Ação Registrada']
            else:
                df_logs = df_logs[['usuario', 'acao']]
                df_logs.columns = ['Administrador', 'Ação Registrada']
            
            st.markdown("<div class='printable-area'>", unsafe_allow_html=True)
            col_p1, col_p2 = st.columns([2, 8])
            with col_p1:
                try:
                    st.image("Mevamgyn_logo.jpg", width=110)
                except:
                    st.write("*(MEVAM GYN)*")
            with col_p2:
                st.markdown(f"### MINISTÉRIO MEVAM GYN\n**Relatório de Auditoria e Segurança de Acessos**")
            st.markdown(f"*Emitido por:* **{st.session_state['usuario_logado']}** em {datetime.now().strftime('%d/%m/%Y às %H:%M')}")
            st.markdown("---")
            
            st.dataframe(df_logs, use_container_width=True, hide_index=True)
            
            st.markdown("---")
            st.caption("📄 **Como salvar em PDF:** Pressione **Ctrl + P** (ou partilhe/imprima no telemóvel) e selecione **'Guardar como PDF'**.")
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.info("Nenhum registo de auditoria encontrado na base de dados.")
    except Exception as e:
        st.error("Erro ao carregar os registos de auditoria.")

# ==========================================
# MÓDULO: CADASTRO DE MEMBROS, OCR & CONFISSÃO DE FÉ
# ==========================================
elif menu == "📜 Cadastro de Membros & Credo (OCR)":
    import sys
    import os
    app_membros_path = os.path.join(os.path.dirname(__file__), "membros_app")
    if app_membros_path not in sys.path:
        sys.path.append(app_membros_path)
    
    try:
        from database import listar_membros, obter_membro_por_id, obter_estatisticas, excluir_membro
        from pdf_generator import gerar_pdf_membro
        db_disponivel = True
    except Exception as err:
        db_disponivel = False
        st.error(f"Erro ao carregar módulo de membros: {err}")

    st.subheader("📜 Gestão de Membros, OCR & Confissão de Fé")
    st.write("Sistema integrado de filiação, reconhecimento de documentos e assinatura digital tipo rúbrica.")

    # Banner com link do Web App para Smartphones/iPhones
    st.markdown("""
        <div style="background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 100%); color: white; padding: 18px 24px; border-radius: 12px; margin-bottom: 20px;">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
                <div>
                    <h4 style="margin: 0; color: #fbbf24; font-size: 1.2rem;">📱 Aplicativo Web Responsivo Ativo!</h4>
                    <p style="margin: 4px 0 0; font-size: 0.9rem; color: #e2e8f0;">
                        Otimizado para <strong>iPhone, Android e Totem</strong> com reconhecimento OCR pela câmera e assinatura digital por toque na tela.
                    </p>
                </div>
                <div>
                    <a href="http://localhost:8080" target="_blank" style="background: #f59e0b; color: #0f172a; padding: 10px 18px; border-radius: 8px; font-weight: bold; text-decoration: none; display: inline-block;">
                        🚀 Abrir App Web do Membro
                    </a>
                </div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    if db_disponivel:
        # Métricas
        stats = obter_estatisticas()
        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        with col_m1:
            st.metric("👥 Total de Membros", stats.get("total_membros", 0))
        with col_m2:
            st.metric("💧 Batizados", stats.get("batizados", 0))
        with col_m3:
            st.metric("✍️ Com Rúbrica Registrada", stats.get("com_assinatura", 0))
        with col_m4:
            st.metric("🎯 Interesse em Batismo", stats.get("interesse_batismo", 0))

        aba_gestao, aba_credo = st.tabs(["👥 Membros Cadastrados", "📜 Credo & Confissão de Fé"])

        with aba_gestao:
            col_busca, col_filtro = st.columns([7, 3])
            with col_busca:
                termo_busca = st.text_input("🔍 Buscar membro por nome, telefone, whatsapp ou bairro:", "")
            with col_filtro:
                status_filtro = st.selectbox("Filtrar por Status:", ["Todos", "Ativo", "Pendente"])

            membros_lista = listar_membros(busca=termo_busca, status=status_filtro)

            if membros_lista:
                # Criar DataFrame para exibição
                dados_tabela = []
                for m in membros_lista:
                    dados_tabela.append({
                        "ID": m.get("id"),
                        "Data Reg.": m.get("data_registro"),
                        "Nome Completo": m.get("nome_completo"),
                        "WhatsApp": m.get("whatsapp"),
                        "Cidade/Bairro": f"{m.get('cidade','Goiânia')} / {m.get('bairro','')}",
                        "Batizado": m.get("batizado"),
                        "Rúbrica": "✓ Sim" if m.get("assinatura_rubrica") else "Não"
                    })
                
                st.dataframe(pd.DataFrame(dados_tabela), use_container_width=True, hide_index=True)

                st.markdown("---")
                st.subheader("🔍 Detalhes do Membro e Emissão de Documento")
                opcoes_membros = {f"#{m['id']} - {m['nome_completo']}": m['id'] for m in membros_lista}
                membro_selecionado_label = st.selectbox("Selecione um membro para visualizar a ficha e assinatura:", list(opcoes_membros.keys()))
                
                if membro_selecionado_label:
                    mid = opcoes_membros[membro_selecionado_label]
                    m_detalhe = obter_membro_por_id(mid)
                    
                    if m_detalhe:
                        col_d1, col_d2 = st.columns(2)
                        with col_d1:
                            st.markdown(f"**Nome:** {m_detalhe.get('nome_completo')}")
                            st.markdown(f"**Nascimento:** {m_detalhe.get('data_nascimento', '-')} | **Sexo:** {m_detalhe.get('sexo', '-')}")
                            st.markdown(f"**Estado Civil:** {m_detalhe.get('estado_civil', '-')} | **Cônjuge:** {m_detalhe.get('conjuge', '-')}")
                            st.markdown(f"**Endereço:** {m_detalhe.get('endereco', '-')} - {m_detalhe.get('bairro', '-')} (CEP: {m_detalhe.get('cep', '-')})")
                            st.markdown(f"**WhatsApp:** {m_detalhe.get('whatsapp', '-')} | **E-mail:** {m_detalhe.get('email', '-')}")
                        with col_d2:
                            st.markdown(f"**Profissão:** {m_detalhe.get('profissao', '-')} ({m_detalhe.get('empresa', '-')})")
                            st.markdown(f"**Escolaridade:** {m_detalhe.get('escolaridade', '-')}")
                            st.markdown(f"**Batizado nas Águas:** {m_detalhe.get('batizado', '-')} (Data: {m_detalhe.get('data_batismo', '-')})")
                            st.markdown(f"**Congregava antes:** {m_detalhe.get('congregava_antes', '-')} ({m_detalhe.get('onde_congregava', '-')})")
                            st.markdown(f"**Área Ministerial:** {m_detalhe.get('area_ministerial', '-')}")

                        # Exibição da Rúbrica
                        st.markdown("#### ✍️ Rúbrica e Termo de Aceite:")
                        rubrica_b64 = m_detalhe.get("assinatura_rubrica")
                        if rubrica_b64 and "data:image" in rubrica_b64:
                            st.image(rubrica_b64, caption=f"Rúbrica Digital registrada por {m_detalhe.get('nome_assinante')} em {m_detalhe.get('data_assinatura')}", width=300)
                            st.caption(f"🔒 Hash de Autenticidade LGPD: `{m_detalhe.get('hash_autenticidade', 'VALIDO')}`")
                        else:
                            st.warning("Assinatura digital não registrada para este membro.")

                        # Gerar PDF para Download Imediato
                        try:
                            pdf_bytes = gerar_pdf_membro(m_detalhe)
                            st.download_button(
                                label="📄 Baixar Ficha Oficial & Confissão de Fé Assinada (PDF)",
                                data=pdf_bytes,
                                file_name=f"Ficha_MEVAM_{m_detalhe.get('id')}_{m_detalhe.get('nome_completo').replace(' ','_')}.pdf",
                                mime="application/pdf",
                                use_container_width=True
                            )
                        except Exception as e_pdf:
                            st.error(f"Erro ao gerar PDF: {e_pdf}")
            else:
                st.info("Nenhum membro cadastrado até o momento. Utilize o botão acima para abrir o app e realizar o primeiro cadastro!")

        with aba_credo:
            st.markdown("""
                ### CREDO MEVAM GYN / CONFISSÃO DE FÉ
                *Creio em Deus Pai Todo-Poderoso, Criador dos céus e da terra; E em Jesus Cristo, seu único Filho, nosso Senhor; O qual foi concebido por obra do Espírito Santo; Nasceu da virgem, Maria; Padeceu sob o poder de Pôncio Pilatos; Foi crucificado, morto e sepultado; E ao terceiro dia, ressurgiu dos mortos; Subiu ao céu e está assentado à destra de Deus Pai, Todo-Poderoso, de onde há de vir para julgar os vivos e os mortos; Creio no Espírito Santo, Na Santa Igreja de Cristo, Na comunhão dos santos, Na remissão dos pecados, Na ressurreição do corpo E na vida eterna. Amém!*
            """)
            st.markdown("---")
            with st.expander("1 - A Natureza de Deus e de Seu Cristo"):
                st.write("Cremos no único Deus eterno, Criador e Senhor do Mundo, Deus Trino: Pai, Filho e Espírito Santo, que governa todas as coisas segundo a sua vontade...")
            with st.expander("2 - O Ministério do Espírito Santo"):
                st.write("Cremos que o Espírito Santo é uma pessoa da Trindade e mais do que apenas um carisma ou poder sobrenatural...")
            with st.expander("3 - A Autoridade e o Poder da Bíblia"):
                st.write("Afirmamos a inspiração divina, a veracidade e autoridade das Escrituras tanto do Antigo como do Novo Testamento...")
            with st.expander("4 - A Natureza de Evangelismo e Missões"):
                st.write("Evangelizar é difundir a mensagem de que Jesus Cristo morreu por nossos pecados e ressuscitou...")
            with st.expander("5 - A Igreja: Instrumento do Reino e Socialmente Responsável"):
                st.write("Nós acreditamos na Igreja única, santa, universal... O evangelho Todo, Para o Homem Todo, Para Todos os Homens.")
            with st.expander("6 - O Retorno de Cristo"):
                st.write("Cremos que Jesus Cristo voltará pessoal e visivelmente, em poder e glória, para consumar a salvação e o juízo...")
            with st.expander("7 - Guerra Espiritual"):
                st.write("Cremos que estamos num permanente conflito espiritual com os principados e potestades do mal...")
            with st.expander("8 - O Valor da Vida Humana"):
                st.write("Acreditamos que todos seres humanos são criados por Deus à Sua imagem e semelhança. Nos posicionamos contra o aborto e o denominamos como homicídio.")
            with st.expander("9 - A Sexualidade e a Imutabilidade do Casamento"):
                st.write("Acreditamos que Deus criou os seres humanos, intencionalmente e imutavelmente nos gêneros masculino e feminino somente. O casamento é uma aliança sagrada entre um homem e uma mulher até que a morte os separe.")
            with st.expander("10 - Exortação, Disciplina e Exclusão"):
                st.write("Cremos que há uma dinâmica de exortação, disciplina e exclusão nas escrituras (Mateus 18:15-17)...")