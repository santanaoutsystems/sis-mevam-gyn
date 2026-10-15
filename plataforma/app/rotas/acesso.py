"""Login, logout, troca de senha e painel inicial direcionado por perfil."""

from __future__ import annotations

import hmac
from datetime import timedelta

from sqlalchemy import func, select, update
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.routing import Route

from .. import config, datas, db, ficha, seguranca
from ..web import auditar, flash, ir, render


def _destino_seguro(proximo: str | None) -> str:
    if proximo and proximo.startswith("/") and not proximo.startswith("//"):
        return proximo
    return "/inicio"


async def entrar(request: Request):
    if request.method == "GET":
        if seguranca.usuario_atual(request):
            return ir("/inicio")
        ctx = {"proximo": request.query_params.get("proximo", "")}
        if request.query_params.get("expirou"):
            ctx["aviso"] = "Seu acesso foi encerrado por falta de uso, para sua segurança. Entre novamente."
        return render(request, "entrar.html", ctx)

    form = await request.form()
    if not await seguranca.conferir_csrf(request):
        flash(request, "Sessão expirada. Tente novamente.", "erro")
        return ir("/entrar")

    email = (form.get("email") or "").strip().lower()
    senha = form.get("senha") or ""
    proximo = form.get("proximo") or ""
    ip = seguranca.ip_cliente(request)
    erro_generico = "E-mail ou senha incorretos."

    if seguranca.ip_bloqueado(ip):
        return render(request, "entrar.html", {"erro": "Muitas tentativas. Aguarde alguns minutos.",
                                               "email": email, "proximo": proximo}, status_code=429)

    with db.engine().begin() as c:
        u = c.execute(select(db.usuarios).where(func.lower(db.usuarios.c.email) == email)).mappings().first()
        agora = datas.agora_utc()
        if u and u["bloqueado_ate"]:
            bloqueio = u["bloqueado_ate"]
            if bloqueio.tzinfo is None:
                bloqueio = bloqueio.replace(tzinfo=agora.tzinfo)
            if bloqueio > agora:
                auditar(request, "LOGIN_BLOQUEADO", f"Usuário #{u['id']}", usuario=dict(u), conexao=c)
                return render(request, "entrar.html", {
                    "erro": f"Conta bloqueada temporariamente por excesso de tentativas. "
                            f"Tente após {datas.fmt_data_hora(bloqueio)}.",
                    "email": email, "proximo": proximo}, status_code=429)

        # Senha provisória copiada do WhatsApp/celular costuma vir com espaço no fim ou com o hífen
        # trocado por travessão. Só para quem ainda está com a senha provisória, tolera isso.
        if u and u["trocar_senha"] and not seguranca.verificar_senha(senha, u["senha_hash"], u["salt"], u["iteracoes"]):
            senha = senha.strip().replace("\u2013", "-").replace("\u2014", "-").replace("\u2011", "-")
        if not u or not u["ativo"] or not seguranca.verificar_senha(senha, u["senha_hash"], u["salt"], u["iteracoes"]):
            seguranca.registrar_falha_ip(ip)
            if u:
                falhas = (u["tentativas_falhas"] or 0) + 1
                valores = {"tentativas_falhas": falhas}
                if falhas >= config.LOGIN_MAX_TENTATIVAS:
                    valores = {"tentativas_falhas": 0,
                               "bloqueado_ate": agora + timedelta(minutes=config.LOGIN_BLOQUEIO_MINUTOS)}
                c.execute(update(db.usuarios).where(db.usuarios.c.id == u["id"]).values(**valores))
            auditar(request, "LOGIN_FALHOU", email, usuario=None, conexao=c)
            return render(request, "entrar.html", {"erro": erro_generico, "email": email, "proximo": proximo},
                          status_code=401)

        valores = {"tentativas_falhas": 0, "bloqueado_ate": None, "ultimo_login": agora}
        # Atualiza hashes antigos (100 mil iterações) para o padrão atual de forma transparente
        if u["iteracoes"] < seguranca.ITERACOES_PADRAO:
            h, s, it = seguranca.hash_senha(senha)
            valores.update(senha_hash=h, salt=s, iteracoes=it)
        c.execute(update(db.usuarios).where(db.usuarios.c.id == u["id"]).values(**valores))
        u = c.execute(select(db.usuarios).where(db.usuarios.c.id == u["id"])).mappings().first()
        auditar(request, "LOGIN", f"Usuário #{u['id']}", f"Perfil: {u['perfil']}", usuario=dict(u), conexao=c)

    seguranca.iniciar_sessao(request, dict(u))
    if u["trocar_senha"]:
        return ir("/trocar-senha")
    return ir(_destino_seguro(proximo))


@seguranca.exigir()
async def sair(request: Request):
    auditar(request, "LOGOUT")
    request.session.clear()
    return ir("/entrar")


@seguranca.exigir()
async def trocar_senha(request: Request):
    u = seguranca.usuario_atual(request)
    if request.method == "GET":
        return render(request, "trocar_senha.html")
    form = await request.form()
    atual, nova, confirma = form.get("atual") or "", form.get("nova") or "", form.get("confirma") or ""
    erro = None
    if not seguranca.verificar_senha(atual, u["senha_hash"], u["salt"], u["iteracoes"]):
        erro = "A senha atual não confere."
    elif nova != confirma:
        erro = "A confirmação não é igual à nova senha."
    elif nova == atual:
        erro = "A nova senha precisa ser diferente da atual."
    else:
        erro = seguranca.validar_forca_senha(nova)
    if erro:
        return render(request, "trocar_senha.html", {"erro": erro}, status_code=400)
    h, s, it = seguranca.hash_senha(nova)
    with db.engine().begin() as c:
        c.execute(update(db.usuarios).where(db.usuarios.c.id == u["id"])
                  .values(senha_hash=h, salt=s, iteracoes=it, trocar_senha=False))
        auditar(request, "TROCA_SENHA", f"Usuário #{u['id']}", conexao=c)
        novo = c.execute(select(db.usuarios).where(db.usuarios.c.id == u["id"])).mappings().first()
    seguranca.iniciar_sessao(request, dict(novo))
    flash(request, "Senha alterada com sucesso.")
    return ir("/inicio")


def cpf_da_pessoa(c, u: dict) -> str | None:
    """CPF do login ou, se ele ainda não tiver, o da ficha de membro ligada a ele."""
    if u.get("cpf"):
        return u["cpf"]
    if u.get("membro_id"):
        return c.execute(select(db.membros.c.cpf).where(db.membros.c.id == u["membro_id"])).scalar()
    return None


@seguranca.exigir()
async def meu_cpf(request: Request):
    """Membros e equipe já cadastrados informam o próprio CPF (identificação única)."""
    u = seguranca.usuario_atual(request)
    with db.engine().connect() as c:
        atual = cpf_da_pessoa(c, u)
    # Depois de informado, só a Secretaria/Adm corrige (evita troca indevida de identidade)
    pode_alterar = not atual or u["perfil"] in ("secretaria", "admin")
    ctx = {"atual": atual, "pode_alterar": pode_alterar}
    if request.method == "GET":
        return render(request, "meu_cpf.html", ctx)

    form = await request.form()
    cpf = (form.get("cpf") or "").strip()
    erro = None
    if not pode_alterar:
        erro = "Seu CPF já está registrado. Para corrigir, procure a Secretaria."
    elif not ficha.cpf_valido(cpf):
        erro = ficha.ERRO_CPF
    else:
        cpf = ficha.fmt_cpf(cpf)
        with db.engine().connect() as c:
            if ficha.cpf_em_uso(c, cpf, membro_id=u["membro_id"], usuario_id=u["id"]):
                erro = ficha.ERRO_CPF_EM_USO
    if erro:
        return render(request, "meu_cpf.html", {**ctx, "erro": erro, "valor": cpf}, status_code=400)

    with db.engine().begin() as c:
        c.execute(update(db.usuarios).where(db.usuarios.c.id == u["id"]).values(cpf=cpf))
        if u["membro_id"]:
            c.execute(update(db.membros).where(db.membros.c.id == u["membro_id"])
                      .values(cpf=cpf, atualizado_em=datas.agora_utc()))
        auditar(request, "CPF_INFORMADO" if not atual else "CPF_CORRIGIDO", f"Usuário #{u['id']}",
                f"Ficha #{u['membro_id']}" if u["membro_id"] else "", conexao=c)
    flash(request, "CPF registrado. Obrigado por atualizar seus dados!")
    return ir("/inicio")


def _existe_admin() -> bool:
    with db.engine().connect() as c:
        return c.execute(select(db.usuarios.c.id).where(db.usuarios.c.perfil == "admin").limit(1)).first() is not None


async def primeiro_acesso(request: Request):
    """Cria o primeiro Administrador. Só existe enquanto não há nenhum admin e com o código configurado."""
    if not config.CODIGO_PRIMEIRO_ACESSO or _existe_admin():
        raise HTTPException(404)
    if request.method == "GET":
        return render(request, "primeiro_acesso.html")

    form = await request.form()
    ip = seguranca.ip_cliente(request)
    dados = {k: (form.get(k) or "").strip() for k in ("nome", "email")}
    dados["email"] = dados["email"].lower()
    erro = None
    if not await seguranca.conferir_csrf(request):
        erro = "Sessão expirada. Tente novamente."
    elif seguranca.ip_bloqueado(ip):
        erro = "Muitas tentativas. Aguarde alguns minutos."
    elif not hmac.compare_digest((form.get("codigo") or "").strip(), config.CODIGO_PRIMEIRO_ACESSO):
        seguranca.registrar_falha_ip(ip)
        erro = "Código de primeiro acesso incorreto."
    elif not dados["nome"] or "@" not in dados["email"]:
        erro = "Informe nome e e-mail."
    elif (form.get("senha") or "") != (form.get("confirma") or ""):
        erro = "A confirmação não é igual à senha."
    else:
        erro = seguranca.validar_forca_senha(form.get("senha") or "")
    if erro:
        return render(request, "primeiro_acesso.html", {"erro": erro, **dados}, status_code=400)

    from .admin import criar_usuario
    with db.engine().begin() as c:
        uid, _ = criar_usuario(c, dados["nome"], dados["email"], "admin", senha=form.get("senha"))
        c.execute(update(db.usuarios).where(db.usuarios.c.id == uid).values(trocar_senha=False))
        u = c.execute(select(db.usuarios).where(db.usuarios.c.id == uid)).mappings().first()
        auditar(request, "PRIMEIRO_ACESSO", f"Usuário #{uid}", "Primeiro Administrador criado", usuario=dict(u), conexao=c)
    seguranca.iniciar_sessao(request, dict(u))
    flash(request, "Adm criado. Agora apague a variável CODIGO_PRIMEIRO_ACESSO no Render.")
    return ir("/inicio")


async def raiz(request: Request):
    return ir("/inicio" if seguranca.usuario_atual(request) else "/entrar")


@seguranca.exigir()
async def inicio(request: Request):
    """Painel inicial: cada perfil cai no seu conjunto de atalhos e números."""
    u = seguranca.usuario_atual(request)
    hoje_iso = db.data_evento(f"{datas.hoje().isoformat()}T00:00:00")
    with db.engine().connect() as c:
        proximos = c.execute(
            select(db.eventos).where(db.eventos.c.data_inicio >= hoje_iso)
            .order_by(db.eventos.c.data_inicio).limit(5)
        ).mappings().all()
        numeros = {}
        if u["perfil"] in ("secretaria", "admin"):
            numeros["aguardando"] = c.execute(select(func.count()).select_from(db.membros)
                                              .where(db.membros.c.status == "Aguardando Análise")).scalar()
            numeros["membros"] = c.execute(select(func.count()).select_from(db.membros)
                                           .where(db.membros.c.status != "Anonimizado (LGPD)")).scalar()
            numeros["eventos_futuros"] = c.execute(select(func.count()).select_from(db.eventos)
                                                   .where(db.eventos.c.data_inicio >= hoje_iso)).scalar()
        meus_setores = []
        if u["perfil"] == "coordenacao":
            from .agenda import escopo_setores
            meus_setores = sorted(escopo_setores(c, u) or [])
        if u["perfil"] == "admin":
            numeros["usuarios"] = c.execute(select(func.count()).select_from(db.usuarios)).scalar()
        minha_ficha = None
        if u["membro_id"]:
            minha_ficha = c.execute(select(db.membros.c.id, db.membros.c.nome_completo, db.membros.c.status)
                                    .where(db.membros.c.id == u["membro_id"])).mappings().first()
        sem_cpf = not cpf_da_pessoa(c, u)
    eventos_fmt = [{**e, "quando": datas.parse_data_hora_local(e["data_inicio"])} for e in proximos]
    return render(request, "inicio.html", {"proximos": eventos_fmt, "numeros": numeros, "minha_ficha": minha_ficha,
                                           "meus_setores": meus_setores, "sem_cpf": sem_cpf})


@seguranca.exigir()
async def manter_sessao(request: Request):
    """Chamado pelo navegador enquanto a pessoa usa a tela (digitando, rolando): mantém o acesso ativo."""
    from starlette.responses import Response
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


rotas = [
    Route("/sessao/manter", manter_sessao),
    Route("/", raiz),
    Route("/entrar", entrar, methods=["GET", "POST"]),
    Route("/sair", sair, methods=["POST"]),
    Route("/trocar-senha", trocar_senha, methods=["GET", "POST"]),
    Route("/meu-cpf", meu_cpf, methods=["GET", "POST"]),
    Route("/inicio", inicio),
    Route("/primeiro-acesso", primeiro_acesso, methods=["GET", "POST"]),
]
