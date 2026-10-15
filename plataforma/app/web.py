"""
Utilidades de interface: templates, mensagens (flash) e trilha de auditoria.
"""

from __future__ import annotations

import os

from sqlalchemy import insert
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.templating import Jinja2Templates

from . import config, datas, db, seguranca

BASE = os.path.dirname(__file__)
templates = Jinja2Templates(directory=os.path.join(BASE, "templates"))

templates.env.filters["data_br"] = datas.fmt_data
templates.env.filters["data_hora_br"] = datas.fmt_data_hora
templates.env.filters["moeda"] = lambda v: ("R$ {:,.2f}".format(float(v or 0))
                                             .replace(",", "X").replace(".", ",").replace("X", "."))
templates.env.globals["PERFIS_ROTULO"] = db.PERFIS_ROTULO
templates.env.globals["VERSAO_APP"] = config.VERSAO_APP


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
    if partes[0] == "membros" and len(partes) >= 2:
        return f"/membros/{partes[1]}" if len(partes) >= 3 else "/membros"
    return "/inicio"


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
