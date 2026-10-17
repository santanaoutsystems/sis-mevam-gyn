"""Pesquisa de satisfação do e-mail de boas-vindas e download do Manual do Membro.

O e-mail traz um link por resposta, assinado com a SECRET_KEY: um clique registra (ou troca) a
resposta do membro, sem login. O resultado fica em Auditoria › Satisfação (Secretaria e Adm).
"""

from __future__ import annotations

import os

from sqlalchemy import func, insert, select, update
from starlette.requests import Request
from starlette.responses import FileResponse
from starlette.routing import Route

from .. import config, datas, db, seguranca
from ..web import auditar, render

OPCOES = [("bom", "Bom"), ("regular", "Regular"), ("ruim", "Ruim"), ("nao_opinar", "Prefiro não opinar agora")]
ROTULOS = dict(OPCOES)
MANUAL_MEMBRO = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "manuais", "manual-do-membro.pdf")


def link(membro_id, resposta: str) -> str:
    return f"{config.URL_BASE}/pesquisa/{membro_id}?r={resposta}&t={seguranca.token_link('pesquisa', membro_id)}"


async def responder(request: Request):
    mid = request.path_params["id"]
    resposta = request.query_params.get("r") or ""
    if resposta not in ROTULOS or not seguranca.conferir_token_link("pesquisa", mid, request.query_params.get("t")):
        return render(request, "erro.html", {"titulo": "Pesquisa", "mensagem": "Este link não é válido."}, 403)
    with db.engine().begin() as c:
        m = c.execute(select(db.membros.c.id, db.membros.c.nome_completo, db.membros.c.status)
                      .where(db.membros.c.id == mid)).mappings().first()
        if not m or m["status"] == "Anonimizado (LGPD)":
            return render(request, "erro.html", {"titulo": "Pesquisa", "mensagem": "Cadastro indisponível."}, 404)
        anterior = c.execute(select(db.pesquisa_satisfacao.c.resposta)
                             .where(db.pesquisa_satisfacao.c.membro_id == mid)).scalar()
        if anterior is None:
            c.execute(insert(db.pesquisa_satisfacao).values(membro_id=mid, resposta=resposta,
                                                            respondido_em=datas.agora_utc()))
        elif anterior != resposta:
            c.execute(update(db.pesquisa_satisfacao).where(db.pesquisa_satisfacao.c.membro_id == mid)
                      .values(resposta=resposta, respondido_em=datas.agora_utc()))
        if anterior != resposta:
            auditar(request, "PESQUISA_SATISFACAO", f"Membro #{mid}", ROTULOS[resposta], usuario=None, conexao=c)
    return render(request, "publico/pesquisa.html", {
        "nome": (m["nome_completo"] or "").split(" ")[0], "resposta": ROTULOS[resposta],
        "outras": [(k, r, link(mid, k)) for k, r in OPCOES if k != resposta]})


async def manual_membro(request: Request):
    if not os.path.exists(MANUAL_MEMBRO):
        return render(request, "erro.html", {"titulo": "Manual", "mensagem": "Manual indisponível no momento."}, 404)
    return FileResponse(MANUAL_MEMBRO, media_type="application/pdf", filename="Manual do Membro - SIS MEVAM-GYN.pdf",
                        content_disposition_type="inline")


@seguranca.exigir("secretaria", "admin")
async def resultado(request: Request):
    with db.engine().connect() as c:
        contagem = dict(c.execute(select(db.pesquisa_satisfacao.c.resposta, func.count())
                                  .group_by(db.pesquisa_satisfacao.c.resposta)).all())
    total = sum(contagem.values())
    linhas = [{"rotulo": r, "n": contagem.get(k, 0), "pct": round(contagem.get(k, 0) * 100 / total) if total else 0}
              for k, r in OPCOES]
    return render(request, "admin/satisfacao.html", {"linhas": linhas, "total": total})


rotas = [
    Route("/pesquisa/{id:int}", responder),
    Route("/manual/membro", manual_membro),
    Route("/admin/satisfacao", resultado),
]
