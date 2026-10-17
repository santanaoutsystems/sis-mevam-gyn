"""
Utilidades de interface: templates, mensagens (flash) e trilha de auditoria.
"""

from __future__ import annotations

import os

from sqlalchemy import insert
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.templating import Jinja2Templates

from . import config, datas, db, ficha, seguranca

BASE = os.path.dirname(__file__)
templates = Jinja2Templates(directory=os.path.join(BASE, "templates"))

templates.env.filters["data_br"] = datas.fmt_data
templates.env.filters["cpf"] = lambda v: ficha.fmt_cpf(v) if v else ""
templates.env.filters["data_hora_br"] = datas.fmt_data_hora
templates.env.filters["moeda"] = lambda v: ("R$ {:,.2f}".format(float(v or 0))
                                             .replace(",", "X").replace(".", ",").replace("X", "."))
templates.env.globals["PERFIS_ROTULO"] = db.PERFIS_ROTULO
templates.env.globals["MESES"] = datas.MESES
templates.env.globals["VERSAO_APP"] = config.VERSAO_APP
templates.env.globals["aniv"] = {}  # telas fora do render() comum: sem avisos


def flash(request: Request, mensagem: str, tipo: str = "sucesso") -> None:
    request.session.setdefault("flash", []).append({"tipo": tipo, "texto": mensagem})


def voltar_para(caminho: str) -> str | None:
    """Tela "anterior" lógica, usada pelo botão ← Voltar quando não há histórico de navegação."""
    partes = [p for p in caminho.strip("/").split("/") if p]
    if not partes or caminho in ("/inicio", "/entrar", "/"):
        return None
    if partes[0] == "eventos":
        if len(partes) >= 3:
            return f"/eventos/{partes[1]}"
        return "/agenda"
    if partes[0] == "regularizacao" and len(partes) >= 2:
        return f"/regularizacao/membro/{partes[2]}" if len(partes) >= 4 else "/regularizacao"
    if partes[0] == "aniversariantes" and len(partes) >= 2:
        return "/aniversariantes"
    if partes[0] == "membros" and len(partes) >= 2:
        return f"/membros/{partes[1]}" if len(partes) >= 3 else "/membros"
    return "/inicio"


def _aniversarios(request: Request, usuario: dict | None) -> dict:
    """Sino (avisos), janela de aniversariantes (1x por dia) e felicitação ao próprio membro no dia."""
    if not usuario or usuario.get("trocar_senha"):
        return {}
    from . import aniversarios as an
    saida: dict = {}
    hoje = datas.hoje()
    dia = hoje.isoformat()
    try:
        if usuario["perfil"] in db.PERFIS_AGENDA:
            an.garantir(hoje)
            with db.engine().connect() as c:
                lista = an.avisos_do_usuario(c, usuario["id"], hoje)
                saida["avisos_n"] = sum(1 for a in lista if not a["lido_em"])
                janela = [a for a in lista if a["janela"] and not a["lido_em"]]
                if (janela and request.session.get("aniv_janela") != dia
                        and request.url.path not in ("/aniversariantes", "/avisos")):
                    request.session["aniv_janela"] = dia
                    dados = {m["id"]: m for m in an.membros(c, {a["membro_id"] for a in janela})}
                    saida["janela"] = [{**a, "m": dados[a["membro_id"]]} for a in janela if a["membro_id"] in dados]
        if usuario.get("membro_id") and request.session.get("aniv_felicitacao") != dia:
            request.session["aniv_felicitacao"] = dia
            with db.engine().connect() as c:
                proprio = an.membros(c, [usuario["membro_id"]])
            if proprio and an.no_ano(proprio[0]["nasc"], hoje.year) == hoje:
                saida["felicitacao"] = proprio[0]["primeiro"]
    except Exception:  # noqa: BLE001  (o aviso nunca pode derrubar a tela)
        import logging
        logging.getLogger("mevam").exception("Falha nos avisos de aniversário")
    return saida


def render(request: Request, nome: str, contexto: dict | None = None, status_code: int = 200):
    usuario = seguranca.usuario_atual(request)
    ctx = {
        "usuario": usuario,
        "csrf": seguranca.csrf_token(request),
        "mensagens": request.session.pop("flash", []),
        "caminho": request.url.path,
        "pode": lambda *p: seguranca.pode(usuario, *p),
        "inatividade": seguranca.limite_inatividade(usuario),
        "versao": config.VERSAO,
        "voltar_para": voltar_para(request.url.path),
        "aniv": _aniversarios(request, usuario),
    }
    ctx.update(contexto or {})
    return templates.TemplateResponse(request, nome, ctx, status_code=status_code)


def ir(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def auditar(request: Request | None, acao: str, recurso: str = "", detalhes: str = "",
            usuario: dict | None = None, conexao=None) -> None:
    """Registra quem fez o quê, quando e de onde (LGPD art. 37)."""
    if usuario is None and request is not None:
        usuario = seguranca.usuario_atual(request)
    valores = {
        "usuario_id": usuario["id"] if usuario else None,
        "usuario_nome": usuario["nome"] if usuario else "Visitante",
        "acao": acao,
        "recurso": recurso,
        "detalhes": detalhes[:2000] if detalhes else "",
        "ip": seguranca.ip_cliente(request) if request is not None else "",
        "criado_em": datas.agora_utc(),
    }
    if conexao is not None:
        conexao.execute(insert(db.auditoria).values(**valores))
    else:
        with db.engine().begin() as c:
            c.execute(insert(db.auditoria).values(**valores))
