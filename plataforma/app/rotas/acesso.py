"""Login, logout, troca de senha e painel inicial direcionado por perfil."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select, update
from starlette.requests import Request
from starlette.routing import Route

from .. import config, datas, db, seguranca
from ..web import auditar, flash, ir, render


def _destino_seguro(proximo: str | None) -> str:
    if proximo and proximo.startswith("/") and not proximo.startswith("//"):
        return proximo
    return "/inicio"


async def entrar(request: Request):
    if request.method == "GET":
        if seguranca.usuario_atual(request):
            return ir("/inicio")
        return render(request, "entrar.html", {"proximo": request.query_params.get("proximo", "")})

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


async def raiz(request: Request):
    return ir("/inicio" if seguranca.usuario_atual(request) else "/entrar")


@seguranca.exigir()
async def inicio(request: Request):
    """Painel inicial: cada perfil cai no seu conjunto de atalhos e números."""
    u = seguranca.usuario_atual(request)
    hoje_iso = datas.hoje().isoformat()
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
        if u["perfil"] == "admin":
            numeros["usuarios"] = c.execute(select(func.count()).select_from(db.usuarios)).scalar()
        minha_ficha = None
        if u["membro_id"]:
            minha_ficha = c.execute(select(db.membros.c.id, db.membros.c.nome_completo, db.membros.c.status)
                                    .where(db.membros.c.id == u["membro_id"])).mappings().first()
    eventos_fmt = [{**e, "quando": datas.parse_data_hora_local(e["data_inicio"])} for e in proximos]
    return render(request, "inicio.html", {"proximos": eventos_fmt, "numeros": numeros, "minha_ficha": minha_ficha})


rotas = [
    Route("/", raiz),
    Route("/entrar", entrar, methods=["GET", "POST"]),
    Route("/sair", sair, methods=["POST"]),
    Route("/trocar-senha", trocar_senha, methods=["GET", "POST"]),
    Route("/inicio", inicio),
]
