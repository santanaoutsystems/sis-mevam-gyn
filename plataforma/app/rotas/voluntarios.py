"""Voluntários: membros que marcaram na ficha os setores em que desejam servir, e convites por e-mail.

Secretaria e Adm veem todos os setores. A Coordenação vê só os setores sob sua coordenação, e apenas
nome e contato dos interessados (LGPD: o mínimo necessário para o convite). O texto do convite é
escrito pela coordenação; {nome} é trocado pelo primeiro nome de cada pessoa. Todo envio vai para a auditoria.
"""

from __future__ import annotations

import threading
from datetime import timedelta

from sqlalchemy import select
from starlette.requests import Request
from starlette.routing import Route

from .. import areas, config, datas, db, envios, ficha, seguranca
from ..web import auditar, flash, ir, render
from .agenda import escopo_setores

FORA = db.STATUS_FORA
LIMITE_CONVITES = 80  # a conta Gmail da Secretaria tem cota diária de envios


def setores_permitidos(c, usuario: dict) -> list[str]:
    escopo = escopo_setores(c, usuario)
    if escopo is None:
        return list(ficha.NOMES_SETORES)
    meus = {ficha.setor_padrao(n) for n in escopo}
    return [n for n in ficha.NOMES_SETORES if n in meus]


def interessados(c, setor: str) -> list[dict]:
    q = (select(db.membros.c.id, db.membros.c.nome_completo, db.membros.c.whatsapp, db.membros.c.email,
                db.membros.c.status, db.membro_interesses.c.criado_em)
         .join(db.membro_interesses, db.membro_interesses.c.membro_id == db.membros.c.id)
         .where(db.membro_interesses.c.setor.in_(areas.equivalentes(setor)), db.membros.c.status.notin_(FORA))
         .order_by(db.membros.c.nome_completo))
    vistos, lista = set(), []
    for r in c.execute(q).mappings():  # quem marcou o nome antigo e o oficial aparece uma vez só
        if r["id"] not in vistos:
            vistos.add(r["id"]); lista.append(dict(r))
    return lista


def _eventos_do_setor(c, setor: str) -> list[dict]:
    hoje = datas.agora()
    de = db.data_evento(hoje.strftime("%Y-%m-%dT00:00:00"))
    ate = db.data_evento((hoje + timedelta(days=180)).strftime("%Y-%m-%dT23:59:59"))
    lista = []
    for e in c.execute(select(db.eventos.c.id, db.eventos.c.titulo, db.eventos.c.data_inicio, db.eventos.c.local,
                              db.eventos.c.departamento)
                       .where(db.eventos.c.data_inicio >= de, db.eventos.c.data_inicio <= ate)
                       .order_by(db.eventos.c.data_inicio)).mappings():
        if ficha.setor_padrao(e["departamento"] or "") == setor:
            e = dict(e)
            e["quando"] = datas.parse_data_hora_local(e["data_inicio"])
            lista.append(e)
    return lista


def texto_padrao(setor: str, evento: dict | None, usuario: dict) -> tuple[str, str]:
    if evento:
        quando = evento["quando"].strftime("%d/%m/%Y às %H:%M") if evento.get("quando") else ""
        local = f", em {evento['local']}" if evento.get("local") else ""
        assunto = f"Convite especial para servir: {evento['titulo']}"
        convite = (f"Estamos preparando o evento {evento['titulo']}, no dia {quando}{local}, "
                   f"e precisamos de voluntários do ministério {setor}.")
    else:
        assunto = f"Convite especial: servir em {setor}"
        convite = f"O ministério {setor} está precisando de voluntários."
    corpo = (f"Paz, {{nome}}!\n\nNo seu cadastro você marcou que deseja servir em {setor}. {convite}\n\n"
             "Podemos contar com você? Responda este e-mail confirmando a sua participação.\n\n"
             f"Deus abençoe!\n{usuario['nome']}\nCoordenação · {setor} · MEVAM GYN")
    return assunto, corpo


@seguranca.exigir("coordenacao", "secretaria", "admin")
async def painel(request: Request):
    u = seguranca.usuario_atual(request)
    with db.engine().connect() as c:
        setores = setores_permitidos(c, u)
        contagem = {s: len(interessados(c, s)) for s in setores}
        setor = request.query_params.get("setor") or (setores[0] if setores else "")
        if setor not in setores:
            setor = setores[0] if setores else ""
        pessoas = interessados(c, setor) if setor else []
        eventos = _eventos_do_setor(c, setor) if setor else []
    evento = next((e for e in eventos if str(e["id"]) == request.query_params.get("evento")), None)
    assunto, corpo = texto_padrao(setor, evento, u) if setor else ("", "")
    auditar(request, "VISUALIZACAO_VOLUNTARIOS", setor or "-", f"{len(pessoas)} interessados")
    return render(request, "voluntarios/painel.html", {
        "setores": setores, "contagem": contagem, "setor": setor, "pessoas": pessoas, "eventos": eventos,
        "evento": evento, "assunto": assunto, "corpo": corpo, "email_ok": envios.email_configurado(),
        "LIMITE": LIMITE_CONVITES, "ver_status": u["perfil"] in ("secretaria", "admin")})


@seguranca.exigir("coordenacao", "secretaria", "admin")
async def convidar(request: Request):
    u = seguranca.usuario_atual(request)
    form = await request.form()
    if not await seguranca.conferir_csrf(request):
        flash(request, "A página expirou. Tente de novo.", "erro")
        return ir("/voluntarios")
    setor = form.get("setor") or ""
    assunto = (form.get("assunto") or "").strip()[:150]
    corpo = (form.get("corpo") or "").strip()[:5000]
    volta = f"/voluntarios?setor={setor}"
    with db.engine().connect() as c:
        if setor not in setores_permitidos(c, u):
            auditar(request, "ACESSO_NEGADO_AREA", "/voluntarios/convidar", f"convite para {setor[:80] or '-'}")
            return render(request, "erro.html", {"titulo": "Acesso restrito",
                          "mensagem": "Este ministério ou área não está sob a sua coordenação."}, 403)
        pessoas = {str(p["id"]): p for p in interessados(c, setor)}
    escolhidos = [pessoas[i] for i in form.getlist("membro") if i in pessoas and pessoas[i].get("email")]
    if not assunto or not corpo:
        flash(request, "Escreva o assunto e a mensagem do convite.", "erro")
        return ir(volta)
    if not escolhidos:
        flash(request, "Marque pelo menos uma pessoa com e-mail.", "erro")
        return ir(volta)
    if len(escolhidos) > LIMITE_CONVITES:
        flash(request, f"Envie no máximo {LIMITE_CONVITES} convites por vez.", "erro")
        return ir(volta)
    if not envios.email_configurado():
        flash(request, "O envio de e-mail não está configurado. Avise o Adm.", "erro")
        return ir(volta)

    def tarefa():
        falhas = []
        for p in escolhidos:
            primeiro = (p["nome_completo"] or "").split(" ")[0]
            erro = envios.enviar_email(p["email"], assunto, corpo.replace("{nome}", primeiro))
            if erro:
                falhas.append(f"#{p['id']}: {erro}")
        auditar(None, "CONVITE_VOLUNTARIOS", setor,
                f"Assunto: {assunto} · {len(escolhidos) - len(falhas)} enviados"
                + (f" · falhas: {'; '.join(falhas)}" if falhas else ""), usuario=u)
    if config.ENVIO_SINCRONO:
        tarefa()
    else:
        threading.Thread(target=tarefa, daemon=True).start()
    flash(request, f"Convite enviado para {len(escolhidos)} pessoa(s). O resultado fica na auditoria.")
    return ir(volta)


rotas = [
    Route("/voluntarios", painel),
    Route("/voluntarios/convidar", convidar, methods=["POST"]),
]
