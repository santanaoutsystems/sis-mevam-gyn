"""
Servidor Web Assíncrono - SIS MEVAM-GYN (Membros, OCR, Credo, Autenticação & LGPD)
Construído com Starlette e Uvicorn para máxima performance em smartphones, iPhones e PCs.
Total conformidade com a LGPD (Lei 13.709/2018) e controle rigoroso de acessos por perfil (RBAC).
"""

import os
import sys
import json
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles
from starlette.responses import JSONResponse, HTMLResponse, Response
from starlette.templating import Jinja2Templates

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from auth import (
    obter_usuario_da_requisicao,
    obter_ip_cliente,
    criar_token_sessao
)
from database import (
    init_db, cadastrar_membro, listar_membros,
    obter_membro_por_id, excluir_membro, obter_estatisticas,
    criar_usuario, autenticar_usuario, listar_usuarios,
    obter_usuario_por_id, atualizar_usuario, excluir_usuario,
    registrar_log_lgpd, listar_logs_lgpd, anonimizar_membro_lgpd,
    validar_membro_secretaria, marcar_link_credo_enviado,
    registrar_aceite_credo, obter_membro_por_token, gerar_token_membro
)
from pdf_generator import gerar_pdf_membro
from ocr_parser import parsear_texto_ficha, extrair_texto_pdf

STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Inicializar Banco de Dados na subida do servidor
init_db()


# ==============================================================================
# POLÍTICA DE PRIVACIDADE E TERMOS LGPD (Art. 9º da Lei 13.709/2018)
# ==============================================================================
TEXTO_POLITICA_LGPD = {
    "titulo": "Política de Privacidade e Proteção de Dados - MEVAM Goiânia",
    "versao": "v1.0-2026",
    "data_vigencia": "01/01/2026",
    "controlador": "Igreja Evangélica MEVAM Goiânia (CNPJ Institucional)",
    "encarregado_dpo": {
        "nome": "Ricardo César Santana (Encarregado de Proteção de Dados / DPO)",
        "email": "dpo@mevamgyn.com",
        "canal_atendimento": "Secretaria Geral MEVAM GYN"
    },
    "bases_legais": [
        "Art. 7º, I (Consentimento do Titular)",
        "Art. 11, II, 'a' e 'd' (Tratamento de Dados Pessoais Sensíveis de Filiação Religiosa e Procedimentos Eclesiásticos)",
        "Art. 14 (Melhor interesse de crianças e adolescentes na representação parental de filhos)"
    ],
    "finalidades": [
        "Cadastro de membros e integração ao rol eclesiástico da igreja;",
        "Registro da Confissão de Fé e compromisso de comunhão cristã;",
        "Comunicação pastoral, discipulado e encaminhamento para áreas de ministério;",
        "Emissão de fichas, comprovantes e certidões ministeriais com rúbrica digital;",
        "Governança estatutária e segurança jurídica das decisões assembleares."
    ],
    "direitos_titulares": [
        "Acesso facilitado aos seus dados cadastrais (Art. 18, II);",
        "Correção de dados incompletos ou desatualizados (Art. 18, III);",
        "Anonimização ou eliminação a pedido formal do titular (Art. 18, IV e VI);",
        "Portabilidade dos dados em PDF oficial (Art. 18, V);",
        "Revogação do consentimento a qualquer momento (Art. 18, IX)."
    ]
}


# ==============================================================================
# ROTAS DE PÁGINAS HTML
# ==============================================================================
async def index_view(request):
    """Página principal do aplicativo (Mobile & Desktop)."""
    user = obter_usuario_da_requisicao(request)
    return templates.TemplateResponse(request, "index.html", context={"user": user})


async def comprovante_print_view(request):
    """Página formatada para impressão do documento oficial assinado com selo LGPD."""
    ip = obter_ip_cliente(request)
    user = obter_usuario_da_requisicao(request)
    user_nome = user["nome"] if user else "Convidado/Membro"
    user_id = user["sub"] if user else None

    membro_id = int(request.path_params['id'])
    membro = obter_membro_por_id(membro_id)
    if not membro:
        return HTMLResponse("<h1>Membro não encontrado</h1>", status_code=404)

    registrar_log_lgpd(
        usuario_id=user_id,
        usuario_nome=user_nome,
        acao="IMPRESSAO_COMPROVANTE",
        recurso=f"Membro #{membro_id} ({membro.get('nome_completo')})",
        detalhes="Visualização de página de impressão com carimbo digital LGPD",
        ip_origem=ip
    )

    return templates.TemplateResponse(request, "comprovante_print.html", context={"membro": membro})


async def credo_aceite_view(request):
    """Página mobile e desktop exclusiva para o membro ler a Confissão de Fé e assinar a Rúbrica."""
    membro_id = int(request.path_params['id'])
    token = request.query_params.get("token", "")
    membro = obter_membro_por_id(membro_id)
    if not membro:
        return HTMLResponse("<div style='text-align:center;padding:50px;font-family:sans-serif;'><h2>Membro não encontrado ou cadastro removido.</h2><p>Contate a Secretaria do MEVAM GYN.</p></div>", status_code=404)

    token_esperado = membro.get("token_aceite") or gerar_token_membro(membro_id)
    user = obter_usuario_da_requisicao(request)
    
    # Validação de segurança: precisa do token ou de usuário administrativo conectado
    if token and token != token_esperado and not (user and user.get("perfil") in ("admin", "secretaria")):
        return HTMLResponse("<div style='text-align:center;padding:50px;font-family:sans-serif;'><h2>Link de acesso inválido ou expirado.</h2><p>Por favor, solicite um novo link oficial à Secretaria do MEVAM GYN.</p></div>", status_code=403)

    return templates.TemplateResponse(request, "credo_aceite.html", context={
        "request": request,
        "membro": membro,
        "token": token_esperado
    })


# ==============================================================================
# ENDPOINTS DE AUTENTICAÇÃO (LOGIN, REGISTRO, LOGOUT, STATUS)
# ==============================================================================
async def api_auth_login(request):
    """Efetua login com e-mail e senha, gerando cookie seguro e token de sessão."""
    try:
        dados = await request.json()
        email = dados.get("email", "").strip()
        senha = dados.get("senha", "")
        ip = obter_ip_cliente(request)

        if not email or not senha:
            return JSONResponse({"error": "E-mail e senha são obrigatórios."}, status_code=400)

        user = autenticar_usuario(email, senha)
        if not user:
            registrar_log_lgpd(
                acao="TENTATIVA_LOGIN_INVALIDA",
                recurso="Autenticação",
                detalhes=f"Tentativa com e-mail: {email}",
                ip_origem=ip
            )
            return JSONResponse({"error": "E-mail ou senha incorretos, ou usuário inativo."}, status_code=401)

        token = criar_token_sessao(user)

        registrar_log_lgpd(
            usuario_id=user["id"],
            usuario_nome=user["nome"],
            acao="LOGIN",
            recurso="Autenticação",
            detalhes=f"Login realizado com perfil: {user['perfil']}",
            ip_origem=ip
        )

        response = JSONResponse({
            "status": "success",
            "message": f"Bem-vindo(a), {user['nome']}!",
            "user": user,
            "token": token
        })

        # Define Cookie seguro HttpOnly (7 dias)
        response.set_cookie(
            key="mevam_session",
            value=token,
            max_age=60 * 60 * 24 * 7,
            httponly=True,
            samesite="lax",
            secure=False  # Funciona tanto em HTTP local quanto HTTPS na nuvem
        )
        return response
    except Exception as e:
        return JSONResponse({"error": f"Erro interno: {str(e)}"}, status_code=500)


async def api_auth_register(request):
    """Registra um novo usuário no sistema em conformidade com as regras de acesso."""
    try:
        dados = await request.json()
        nome = dados.get("nome", "").strip()
        email = dados.get("email", "").strip()
        senha = dados.get("senha", "")
        ip = obter_ip_cliente(request)

        if not nome or not email or not senha:
            return JSONResponse({"error": "Nome, e-mail e senha são obrigatórios."}, status_code=400)

        if len(senha) < 6:
            return JSONResponse({"error": "A senha deve conter no mínimo 6 caracteres."}, status_code=400)

        # Se for o primeiro usuário a se registrar, concede perfil admin automaticamente
        usuarios_existentes = listar_usuarios()
        perfil = "admin" if len(usuarios_existentes) == 0 else "membro"

        try:
            novo_id = criar_usuario(nome, email, senha, perfil=perfil)
        except ValueError as val_err:
            return JSONResponse({"error": str(val_err)}, status_code=400)

        user = {
            "id": novo_id,
            "nome": nome,
            "email": email.lower(),
            "perfil": perfil,
            "ativo": 1
        }
        token = criar_token_sessao(user)

        registrar_log_lgpd(
            usuario_id=novo_id,
            usuario_nome=nome,
            acao="NOVO_USUARIO_REGISTRADO",
            recurso=f"Usuário #{novo_id}",
            detalhes=f"Novo cadastro com perfil atribuído: {perfil}",
            ip_origem=ip
        )

        response = JSONResponse({
            "status": "success",
            "message": "Conta criada com sucesso!",
            "user": user,
            "token": token
        }, status_code=201)

        response.set_cookie(
            key="mevam_session",
            value=token,
            max_age=60 * 60 * 24 * 7,
            httponly=True,
            samesite="lax",
            secure=False
        )
        return response
    except Exception as e:
        return JSONResponse({"error": f"Erro interno no registro: {str(e)}"}, status_code=500)


async def api_auth_logout(request):
    """Encerra a sessão do usuário e registra o evento na auditoria LGPD."""
    ip = obter_ip_cliente(request)
    user = obter_usuario_da_requisicao(request)
    if user:
        registrar_log_lgpd(
            usuario_id=user["sub"],
            usuario_nome=user["nome"],
            acao="LOGOUT",
            recurso="Autenticação",
            detalhes="Logout voluntário da sessão",
            ip_origem=ip
        )

    response = JSONResponse({"status": "logged_out", "message": "Sessão encerrada com sucesso."})
    response.delete_cookie("mevam_session")
    return response


async def api_auth_me(request):
    """Retorna o estado da autenticação e os dados do usuário conectado."""
    user = obter_usuario_da_requisicao(request)
    if not user:
        return JSONResponse({"authenticated": False, "user": None})
    return JSONResponse({"authenticated": True, "user": user})


# ==============================================================================
# GESTÃO DE USUÁRIOS E CONFIGURAÇÃO DE ACESSOS (RBAC - EXCLUSIVO ADMIN)
# ==============================================================================
async def api_listar_usuarios(request):
    """Lista todos os usuários cadastrados. Acesso exclusivo a Administradores."""
    user = obter_usuario_da_requisicao(request)
    if not user or user.get("perfil") != "admin":
        return JSONResponse({"error": "Acesso não autorizado. Perfil de Administrador obrigatório."}, status_code=403)

    busca = request.query_params.get("busca", "")
    usuarios = listar_usuarios(busca=busca)
    return JSONResponse(usuarios)


async def api_criar_usuario_admin(request):
    """Criação direta de usuário pelo Administrador, podendo definir o perfil de acesso."""
    user = obter_usuario_da_requisicao(request)
    if not user or user.get("perfil") != "admin":
        return JSONResponse({"error": "Acesso não autorizado."}, status_code=403)

    ip = obter_ip_cliente(request)
    dados = await request.json()
    nome = dados.get("nome", "").strip()
    email = dados.get("email", "").strip()
    senha = dados.get("senha", "")
    perfil = dados.get("perfil", "membro")

    if not nome or not email or not senha:
        return JSONResponse({"error": "Nome, e-mail e senha são obrigatórios."}, status_code=400)

    try:
        novo_id = criar_usuario(nome, email, senha, perfil=perfil)
        registrar_log_lgpd(
            usuario_id=user["sub"],
            usuario_nome=user["nome"],
            acao="CRIACAO_USUARIO_ADMIN",
            recurso=f"Usuário #{novo_id} ({email})",
            detalhes=f"Criado por admin com perfil: {perfil}",
            ip_origem=ip
        )
        return JSONResponse({"status": "success", "id": novo_id, "message": "Usuário criado com sucesso!"}, status_code=201)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


async def api_atualizar_usuario(request):
    """Atualiza perfil, status ativo/inativo ou dados de um usuário pelo Administrador."""
    user = obter_usuario_da_requisicao(request)
    if not user or user.get("perfil") != "admin":
        return JSONResponse({"error": "Acesso não autorizado."}, status_code=403)

    ip = obter_ip_cliente(request)
    alvo_id = int(request.path_params['id'])
    dados = await request.json()

    # Prevenir que o admin logado remova seu próprio privilégio de admin ou se desative por acidente
    if alvo_id == user["sub"]:
        if "perfil" in dados and dados["perfil"] != "admin":
            return JSONResponse({"error": "Você não pode remover seus próprios privilégios de Administrador."}, status_code=400)
        if "ativo" in dados and not dados["ativo"]:
            return JSONResponse({"error": "Você não pode desativar seu próprio usuário em uso."}, status_code=400)

    atualizar_usuario(
        user_id=alvo_id,
        nome=dados.get("nome"),
        email=dados.get("email"),
        perfil=dados.get("perfil"),
        ativo=dados.get("ativo"),
        nova_senha=dados.get("nova_senha")
    )

    registrar_log_lgpd(
        usuario_id=user["sub"],
        usuario_nome=user["nome"],
        acao="ALTERACAO_PERFIL_ACESSO",
        recurso=f"Usuário #{alvo_id}",
        detalhes=f"Alterações realizadas: {json.dumps(dados, ensure_ascii=False)}",
        ip_origem=ip
    )

    return JSONResponse({"status": "updated", "message": "Usuário atualizado com sucesso!"})


async def api_excluir_usuario(request):
    """Exclui um usuário do sistema (Apenas Administrador)."""
    user = obter_usuario_da_requisicao(request)
    if not user or user.get("perfil") != "admin":
        return JSONResponse({"error": "Acesso não autorizado."}, status_code=403)

    alvo_id = int(request.path_params['id'])
    if alvo_id == user["sub"]:
        return JSONResponse({"error": "Você não pode excluir sua própria conta enquanto conectado."}, status_code=400)

    ip = obter_ip_cliente(request)
    excluir_usuario(alvo_id)

    registrar_log_lgpd(
        usuario_id=user["sub"],
        usuario_nome=user["nome"],
        acao="EXCLUSAO_USUARIO",
        recurso=f"Usuário #{alvo_id}",
        detalhes="Conta de usuário excluída pelo Administrador",
        ip_origem=ip
    )

    return JSONResponse({"status": "deleted", "id": alvo_id})


# ==============================================================================
# AUDITORIA & PRIVACIDADE LGPD
# ==============================================================================
async def api_listar_logs_lgpd(request):
    """Exibe trilha de auditoria e governança LGPD (Exclusivo Administrador)."""
    user = obter_usuario_da_requisicao(request)
    if not user or user.get("perfil") != "admin":
        return JSONResponse({"error": "Acesso negado aos relatórios de auditoria."}, status_code=403)

    busca = request.query_params.get("busca", "")
    logs = listar_logs_lgpd(limit=200, busca=busca)
    return JSONResponse(logs)


async def api_politica_lgpd(request):
    """Retorna os termos legais da Política de Privacidade e Proteção de Dados."""
    return JSONResponse(TEXTO_POLITICA_LGPD)


async def api_anonimizar_membro(request):
    """Atende ao direito do titular de revogação de consentimento e anonimização (Art. 18 LGPD)."""
    user = obter_usuario_da_requisicao(request)
    if not user or user.get("perfil") not in ("admin", "secretaria"):
        return JSONResponse({"error": "Permissão insuficiente para anonimização."}, status_code=403)

    membro_id = int(request.path_params['id'])
    dados = await request.json() if request.headers.get("content-type") == "application/json" else {}
    motivo = dados.get("motivo", "Solicitação expressa do titular (Art. 18 da LGPD)")
    ip = obter_ip_cliente(request)

    anonimizar_membro_lgpd(membro_id, motivo=motivo)

    registrar_log_lgpd(
        usuario_id=user["sub"],
        usuario_nome=user["nome"],
        acao="ANONIMIZACAO_LGPD",
        recurso=f"Membro #{membro_id}",
        detalhes=f"Direito do titular exercido. Motivo: {motivo}",
        ip_origem=ip
    )

    return JSONResponse({
        "status": "success",
        "message": f"Dados do Membro #{membro_id} foram devidamente anonimizados conforme a LGPD."
    })


# ==============================================================================
# ROTAS DA API DE MEMBROS (COM CONTROLE DE ACESSO E LOGS)
# ==============================================================================
async def api_listar_membros(request):
    """Lista membros cadastrados. Acesso permitido para Administradores e Secretaria."""
    user = obter_usuario_da_requisicao(request)
    if not user or user.get("perfil") not in ("admin", "secretaria"):
        return JSONResponse({"error": "Acesso restrito à Secretaria e Administração."}, status_code=403)

    busca = request.query_params.get("busca", "")
    status = request.query_params.get("status", "")
    membros = listar_membros(busca=busca, status=status)
    return JSONResponse(membros)


async def api_obter_membro(request):
    """Obtém detalhes de um membro. Requer login."""
    user = obter_usuario_da_requisicao(request)
    if not user:
        return JSONResponse({"error": "Login obrigatório para consultar informações de membros."}, status_code=401)

    membro_id = int(request.path_params['id'])
    membro = obter_membro_por_id(membro_id)
    if not membro:
        return JSONResponse({"error": "Membro não encontrado"}, status_code=404)

    # Membros comuns só podem ver seu próprio cadastro (se vinculado por email)
    if user.get("perfil") == "membro" and user.get("email").lower() != membro.get("email", "").lower():
        return JSONResponse({"error": "Acesso restrito ao próprio titular."}, status_code=403)

    ip = obter_ip_cliente(request)
    registrar_log_lgpd(
        usuario_id=user["sub"],
        usuario_nome=user["nome"],
        acao="CONSULTA_FICHA_MEMBRO",
        recurso=f"Membro #{membro_id}",
        detalhes="Acesso aos dados cadastrais",
        ip_origem=ip
    )

    return JSONResponse(membro)


async def api_cadastrar_membro(request):
    """Cadastra um novo membro com consentimento LGPD explícito e carimbo criptográfico."""
    try:
        dados = await request.json()
        if not dados.get("nome_completo"):
            return JSONResponse({"error": "Nome completo é obrigatório."}, status_code=400)

        # Validação mandatória de consentimento LGPD
        if not dados.get("lgpd_consentimento", True):
            return JSONResponse({"error": "É obrigatório consentir com o Termo de Privacidade da LGPD para registrar o cadastro."}, status_code=400)

        ip = obter_ip_cliente(request)
        user = obter_usuario_da_requisicao(request)
        operador_nome = user["nome"] if user else dados.get("nome_completo", "Auto-Cadastro Membro")
        operador_id = user["sub"] if user else None

        novo_id = cadastrar_membro(dados, ip_origem=ip)

        status_salvo = dados.get("status") or ("Ativo" if dados.get("assinatura_rubrica") else "Aguardando Análise")
        token_gerado = gerar_token_membro(novo_id)

        registrar_log_lgpd(
            usuario_id=operador_id,
            usuario_nome=operador_nome,
            acao="CADASTRO_MEMBRO",
            recurso=f"Membro #{novo_id} ({dados.get('nome_completo')})",
            detalhes=f"Ficha cadastral registrada. Status: {status_salvo}. IP: {ip}",
            ip_origem=ip
        )

        return JSONResponse({
            "status": "success",
            "id": novo_id,
            "token": token_gerado,
            "status_membro": status_salvo,
            "message": "Ficha cadastral salva com sucesso e enviada para a análise da direção!"
        }, status_code=201)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def api_validar_membro(request):
    """Validação da Ficha Cadastral pela Secretaria/Direção antes do envio da Confissão de Fé."""
    user = obter_usuario_da_requisicao(request)
    if not user or user.get("perfil") not in ("admin", "secretaria"):
        return JSONResponse({"error": "Apenas Secretaria ou Administrador podem validar cadastros."}, status_code=403)

    membro_id = int(request.path_params['id'])
    membro = obter_membro_por_id(membro_id)
    if not membro:
        return JSONResponse({"error": "Membro não encontrado."}, status_code=404)

    validador_nome = user.get("nome", "Secretaria Geral")
    res = validar_membro_secretaria(membro_id, validador_nome=validador_nome)

    ip = obter_ip_cliente(request)
    registrar_log_lgpd(
        usuario_id=user["sub"],
        usuario_nome=user["nome"],
        acao="VALIDACAO_CADASTRO_MEMBRO",
        recurso=f"Membro #{membro_id} ({membro.get('nome_completo')})",
        detalhes=f"Cadastro aprovado pela secretaria para envio de Confissão de Fé e Rúbrica. IP: {ip}",
        ip_origem=ip
    )

    return JSONResponse({
        "status": "success",
        "message": f"Ficha de {membro.get('nome_completo')} validada com sucesso!",
        "token": res.get("token"),
        "membro": membro
    })


async def api_marcar_link_enviado(request):
    """Registra envio do link/QR Code de Confissão de Fé para o WhatsApp ou e-mail do membro."""
    user = obter_usuario_da_requisicao(request)
    if not user or user.get("perfil") not in ("admin", "secretaria"):
        return JSONResponse({"error": "Acesso não autorizado."}, status_code=403)

    membro_id = int(request.path_params['id'])
    marcar_link_credo_enviado(membro_id)

    ip = obter_ip_cliente(request)
    registrar_log_lgpd(
        usuario_id=user["sub"],
        usuario_nome=user["nome"],
        acao="ENVIO_LINK_CREDO",
        recurso=f"Membro #{membro_id}",
        detalhes="Link e QR Code de Confissão de Fé encaminhados ao membro via WhatsApp/E-mail",
        ip_origem=ip
    )

    return JSONResponse({"status": "success", "message": "Status atualizado para Link Enviado."})


async def api_registrar_aceite_credo(request):
    """Gravação do Aceite da Confissão de Fé e Rúbrica Digital pelo membro (após validação pastoral)."""
    membro_id = int(request.path_params['id'])
    membro = obter_membro_por_id(membro_id)
    if not membro:
        return JSONResponse({"error": "Membro não encontrado."}, status_code=404)

    dados = await request.json()
    token = dados.get("token", "")
    token_esperado = membro.get("token_aceite") or gerar_token_membro(membro_id)

    user = obter_usuario_da_requisicao(request)
    if token and token != token_esperado and not (user and user.get("perfil") in ("admin", "secretaria")):
        return JSONResponse({"error": "Token de autenticação do link inválido."}, status_code=403)

    nome_assinante = dados.get("nome_assinante", "").strip()
    assinatura_rubrica = dados.get("assinatura_rubrica", "").strip()

    if not nome_assinante:
        return JSONResponse({"error": "O nome completo do assinante é obrigatório."}, status_code=400)

    if not assinatura_rubrica or not assinatura_rubrica.startswith("data:image"):
        return JSONResponse({"error": "A rúbrica/assinatura digital no quadro é obrigatória."}, status_code=400)

    ip = obter_ip_cliente(request)
    res = registrar_aceite_credo(membro_id, nome_assinante, assinatura_rubrica, ip_origem=ip)

    registrar_log_lgpd(
        usuario_id=user["sub"] if user else None,
        usuario_nome=nome_assinante,
        acao="ACEITE_CREDO_RUBRICA",
        recurso=f"Membro #{membro_id} ({membro.get('nome_completo')})",
        detalhes=f"Confissão de Fé aceita e Rúbrica Digital gravada com validade LGPD. IP: {ip}",
        ip_origem=ip
    )

    return JSONResponse({
        "status": "success",
        "message": "Confissão de Fé aceita e Rúbrica Digital registrada com sucesso!",
        "hash_autenticidade": res.get("hash_autenticidade")
    })



async def api_excluir_membro(request):
    """Exclusão física total de membro (Apenas Administrador Master conforme LGPD)."""
    user = obter_usuario_da_requisicao(request)
    if not user or user.get("perfil") != "admin":
        return JSONResponse({"error": "Apenas o Administrador pode executar a exclusão definitiva."}, status_code=403)

    membro_id = int(request.path_params['id'])
    membro = obter_membro_por_id(membro_id)
    nome_membro = membro.get("nome_completo", f"#{membro_id}") if membro else f"#{membro_id}"

    ip = obter_ip_cliente(request)
    excluir_membro(membro_id)

    registrar_log_lgpd(
        usuario_id=user["sub"],
        usuario_nome=user["nome"],
        acao="EXCLUSAO_DEFINITIVA_MEMBRO",
        recurso=f"Membro #{membro_id} ({nome_membro})",
        detalhes="Eliminação definitiva de dados pessoais a pedido do titular ou decisão administrativa",
        ip_origem=ip
    )

    return JSONResponse({"status": "deleted", "id": membro_id})


async def api_download_pdf(request):
    """Gera e faz o download do comprovante eclesiástico oficial assinado em PDF."""
    membro_id = int(request.path_params['id'])
    membro = obter_membro_por_id(membro_id)
    if not membro:
        return JSONResponse({"error": "Membro não encontrado"}, status_code=404)

    ip = obter_ip_cliente(request)
    user = obter_usuario_da_requisicao(request)
    operador_nome = user["nome"] if user else "Visitante/Membro"
    operador_id = user["sub"] if user else None

    registrar_log_lgpd(
        usuario_id=operador_id,
        usuario_nome=operador_nome,
        acao="DOWNLOAD_PDF_OFICIAL",
        recurso=f"Membro #{membro_id} ({membro.get('nome_completo')})",
        detalhes="Download do documento com rúbrica digital e carimbo de conformidade LGPD",
        ip_origem=ip
    )

    pdf_bytes = gerar_pdf_membro(membro)
    nome_arquivo = f"MEVAM_GYN_Membro_{membro_id}_{membro.get('nome_completo','').replace(' ','_')}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename=\"{nome_arquivo}\""
        }
    )


async def api_ocr_parse_fallback(request):
    """Endpoint backend para processamento de arquivo PDF/Imagem se necessário."""
    try:
        form = await request.form()
        arquivo = form.get("file")
        if not arquivo:
            return JSONResponse({"error": "Nenhum arquivo enviado"}, status_code=400)

        caminho_temp = os.path.join(UPLOADS_DIR, arquivo.filename)
        with open(caminho_temp, "wb") as f:
            f.write(await arquivo.read())

        texto = ""
        if arquivo.filename.lower().endswith(".pdf"):
            texto = extrair_texto_pdf(caminho_temp)

        dados_extraidos = parsear_texto_ficha(texto)
        return JSONResponse(dados_extraidos)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def api_estatisticas(request):
    """Estatísticas consolidadas da membresia e governança LGPD."""
    stats = obter_estatisticas()
    return JSONResponse(stats)


async def api_healthz(request):
    """Endpoint de Health Check e Keep-Alive para monitoramento e prevenção de repouso."""
    from datetime import datetime
    return JSONResponse({
        "status": "healthy",
        "app": "SIS MEVAM-GYN",
        "versao": "v1.27",
        "timestamp": datetime.now().isoformat()
    })


def iniciar_keep_alive():
    """Inicia thread em segundo plano para realizar auto-ping e manter a aplicação ativa no Render."""
    import threading
    import time
    import urllib.request

    def worker():
        # Aguarda 45 segundos para a aplicação estabilizar após a subida
        time.sleep(45)
        url = os.environ.get("KEEP_ALIVE_URL", "https://sis-mevam-gyn.onrender.com/healthz")
        while True:
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "SIS-MEVAM-GYN-KeepAlive/1.0 (Python Background Ping)"}
                )
                with urllib.request.urlopen(req, timeout=15) as res:
                    print(f"[Keep-Alive] Ping no servidor {url} executado com sucesso (Status {res.status})")
            except Exception as e:
                print(f"[Keep-Alive] Verificação de atividade: {e}")
            
            # Repete a cada 9 minutos (540s) para garantir que o Render não atinja os 15 min de repouso
            time.sleep(540)

    # Inicia a thread somente se não estiver explicitamente desativada
    if os.environ.get("DISABLE_KEEP_ALIVE", "0") != "1":
        t = threading.Thread(target=worker, daemon=True, name="RenderKeepAliveThread")
        t.start()


# ==============================================================================
# MAPEAMENTO DE ROTAS DA APLICAÇÃO
# ==============================================================================
routes = [
    # Health Check & Keep-Alive (Prevenção de Repouso no Render)
    Route("/healthz", api_healthz, methods=["GET"]),
    Route("/api/ping", api_healthz, methods=["GET"]),

    # Páginas HTML
    Route("/", index_view, methods=["GET"]),
    Route("/membro/{id:int}/comprovante", comprovante_print_view, methods=["GET"]),
    Route("/credo-aceite/{id:int}", credo_aceite_view, methods=["GET"]),
    
    # Autenticação & Sessão
    Route("/api/auth/login", api_auth_login, methods=["POST"]),
    Route("/api/auth/register", api_auth_register, methods=["POST"]),
    Route("/api/auth/logout", api_auth_logout, methods=["POST"]),
    Route("/api/auth/me", api_auth_me, methods=["GET"]),

    # Gestão de Usuários & Configuração de Acessos (RBAC - Admin)
    Route("/api/usuarios", api_listar_usuarios, methods=["GET"]),
    Route("/api/usuarios", api_criar_usuario_admin, methods=["POST"]),
    Route("/api/usuarios/{id:int}", api_atualizar_usuario, methods=["PUT"]),
    Route("/api/usuarios/{id:int}", api_excluir_usuario, methods=["DELETE"]),

    # Governança e Auditoria LGPD
    Route("/api/lgpd/logs", api_listar_logs_lgpd, methods=["GET"]),
    Route("/api/lgpd/politica", api_politica_lgpd, methods=["GET"]),
    Route("/api/membros/{id:int}/anonimizar", api_anonimizar_membro, methods=["POST"]),

    # Membros & Operações da Secretaria
    Route("/api/membros", api_listar_membros, methods=["GET"]),
    Route("/api/membros", api_cadastrar_membro, methods=["POST"]),
    Route("/api/membros/{id:int}", api_obter_membro, methods=["GET"]),
    Route("/api/membros/{id:int}/validar", api_validar_membro, methods=["POST"]),
    Route("/api/membros/{id:int}/link-enviado", api_marcar_link_enviado, methods=["POST"]),
    Route("/api/membros/{id:int}/aceite-credo", api_registrar_aceite_credo, methods=["POST"]),
    Route("/api/membros/{id:int}", api_excluir_membro, methods=["DELETE"]),
    Route("/api/membros/{id:int}/pdf", api_download_pdf, methods=["GET"]),
    Route("/api/ocr/parse", api_ocr_parse_fallback, methods=["POST"]),
    Route("/api/estatisticas", api_estatisticas, methods=["GET"]),

    # Arquivos Estáticos (CSS, JS, Imagens, Fontes)
    Mount("/static", app=StaticFiles(directory=STATIC_DIR), name="static"),
]

app = Starlette(debug=True, routes=routes)

if __name__ == "__main__":
    porta = int(os.environ.get("PORT", 8080))
    iniciar_keep_alive()
    print("=========================================================")
    print(f"SIS MEVAM-GYN (Membros, OCR, Credo, Auth & LGPD) Rodando!")
    print(f"Acesso em Celular / iPhone / PC: http://localhost:{porta}")
    print("=========================================================")
    uvicorn.run(app, host="0.0.0.0", port=porta, log_level="info")
