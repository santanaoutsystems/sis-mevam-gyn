"""INTEGRA (v2.12.0): turmas e código de conclusão, confirmação pelo QR Code, quadro da ficha e campanha.

Regras em app/integra.py. Secretaria e Adm cadastram turmas e registram conclusões/dispensas; o bloqueio
administrativo é só do Adm. As telas públicas (/integra/c/<código> e /integra/atualizar/<id>) não mostram
dados pessoais: pedem o CPF ou usam link assinado.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, insert, or_, select, update
from starlette.requests import Request
from starlette.routing import Route

from .. import datas, db, ficha, integra, seguranca
from ..web import auditar, flash, ir, render
from .membros import _carregar

ADMIN_SECRETARIA = ("secretaria", "admin")
JUSTIFICATIVA_MINIMA = 10


def _turma(c, tid) -> dict | None:
    t = c.execute(select(db.integra_turmas).where(db.integra_turmas.c.id == tid)).mappings().first()
    return dict(t) if t else None


def _concluintes(c, tid) -> list[dict]:
    q = (select(db.membros.c.id, db.membros.c.nome_completo, db.membros.c.status, db.membros.c.integra_situacao,
                db.membros.c.integra_registrado_por, db.membros.c.integra_registrado_em)
         .where(db.membros.c.integra_turma_id == tid, db.membros.c.status != db.EXCLUIDO)
         .order_by(db.membros.c.nome_completo))
    return [dict(r) for r in c.execute(q).mappings()]


def _contagem(c) -> dict:
    linhas = c.execute(select(db.membros.c.integra_situacao, func.count())
                       .where(db.membros.c.status.notin_((db.ANONIMIZADO, db.EXCLUIDO)))
                       .group_by(db.membros.c.integra_situacao)).all()
    return {s: n for s, n in linhas}


# ---------------------------------------------------------------------------
# Painel (Secretaria e Adm)
# ---------------------------------------------------------------------------
@seguranca.exigir(*ADMIN_SECRETARIA)
async def painel(request: Request):
    with db.engine().connect() as c:
        turmas = [dict(r) for r in c.execute(select(
            db.integra_turmas, func.count(db.membros.c.id).label("concluintes"))
            .select_from(db.integra_turmas.outerjoin(db.membros, db.membros.c.integra_turma_id == db.integra_turmas.c.id))
            .group_by(db.integra_turmas.c.id).order_by(db.integra_turmas.c.data_conclusao.desc())).mappings()]
        contagem = _contagem(c)
        candidatos = len(integra.candidatos_campanha(c))
        aguardando = [dict(r) for r in c.execute(select(
            db.membros.c.id, db.membros.c.nome_completo, db.membros.c.integra_data, db.membros.c.integra_turma_id)
            .where(db.membros.c.integra_situacao == "aguardando", db.membros.c.status != db.EXCLUIDO)
            .order_by(db.membros.c.nome_completo)).mappings()]
        em_prazo = c.execute(select(func.count()).select_from(db.membros).where(
            db.membros.c.integra_situacao.is_(None), db.membros.c.integra_prazo.isnot(None),
            db.membros.c.status.notin_(db.STATUS_FORA + (db.NC_INTEGRA,)))).scalar()
    agora = datas.agora_utc()
    for t in turmas:
        t["vigente"] = integra.codigo_vigente(t, agora)
    return render(request, "integra/painel.html", {
        "turmas": turmas, "contagem": contagem, "candidatos": candidatos, "aguardando": aguardando,
        "em_prazo": em_prazo, "SITUACOES": integra.SITUACOES, "hoje": datas.fmt_data(datas.hoje()),
        "LIMITE": integra.LIMITE_DIARIO, "PRAZO": integra.PRAZO_DIAS})


@seguranca.exigir(*ADMIN_SECRETARIA)
async def nova_turma(request: Request):
    form = await request.form()
    nome = (form.get("nome") or "").strip()[:120]
    data_c = datas.parse_data(form.get("data_conclusao"))
    if not nome or not data_c:
        flash(request, "Informe o nome da turma e a data do encerramento (dd/mm/aaaa).", "erro")
        return ir("/integra")
    u = seguranca.usuario_atual(request)
    with db.engine().begin() as c:
        codigo = integra.gerar_codigo(c)
        tid = c.execute(insert(db.integra_turmas).values(
            nome=nome, data_conclusao=data_c, local=(form.get("local") or "").strip()[:120] or None,
            codigo=codigo, codigo_valido_ate=integra.fim_do_dia(data_c), criado_por=u["nome"],
            criado_em=datas.agora_utc())).inserted_primary_key[0]
        auditar(request, "INTEGRA_TURMA_CRIADA", f"Turma INTEGRA #{tid}", f"{nome} · {datas.fmt_data(data_c)}", conexao=c)
    flash(request, f"Turma criada. Código {codigo}, válido até o fim do dia {datas.fmt_data(data_c)}.")
    return ir(f"/integra/turmas/{tid}")


@seguranca.exigir(*ADMIN_SECRETARIA)
async def turma(request: Request):
    tid = request.path_params["id"]
    busca = (request.query_params.get("q") or "").strip()
    with db.engine().connect() as c:
        t = _turma(c, tid)
        if not t:
            return ir("/integra")
        concluintes = _concluintes(c, tid)
        achados = []
        if len(busca) >= 3:
            dig = ficha.so_digitos(busca)
            cond = func.lower(db.membros.c.nome_completo).like(f"%{busca.lower()}%")
            if len(dig) == 11:
                cond = or_(cond, db.membros.c.cpf == dig)
            achados = [dict(r) for r in c.execute(select(
                db.membros.c.id, db.membros.c.nome_completo, db.membros.c.status, db.membros.c.integra_situacao)
                .where(cond, db.membros.c.status.notin_((db.ANONIMIZADO, db.EXCLUIDO)))
                .order_by(db.membros.c.nome_completo).limit(15)).mappings()]
    t["vigente"] = integra.codigo_vigente(t)
    return render(request, "integra/turma.html", {
        "t": t, "concluintes": concluintes, "achados": achados, "busca": busca, "link": integra.link_turma(t),
        "SITUACOES": integra.SITUACOES})


@seguranca.exigir(*ADMIN_SECRETARIA)
async def projetar(request: Request):
    with db.engine().connect() as c:
        t = _turma(c, request.path_params["id"])
    if not t:
        return ir("/integra")
    return render(request, "integra/projetar.html", {"t": t, "link": integra.link_turma(t),
                                                     "vigente": integra.codigo_vigente(t)})


@seguranca.exigir(*ADMIN_SECRETARIA)
async def prorrogar(request: Request):
    tid = request.path_params["id"]
    form = await request.form()
    try:
        dias = max(1, min(30, int(form.get("dias") or 1)))
    except ValueError:
        dias = 1
    novo = integra.fim_do_dia(datas.hoje() + timedelta(days=dias - 1))
    with db.engine().begin() as c:
        if not _turma(c, tid):
            return ir("/integra")
        c.execute(update(db.integra_turmas).where(db.integra_turmas.c.id == tid).values(codigo_valido_ate=novo))
        auditar(request, "INTEGRA_CODIGO_PRORROGADO", f"Turma INTEGRA #{tid}", f"Válido até {datas.fmt_data_hora(novo)}", conexao=c)
    flash(request, f"Código válido até {datas.fmt_data_hora(novo)}.")
    return ir(f"/integra/turmas/{tid}")


@seguranca.exigir(*ADMIN_SECRETARIA)
async def incluir(request: Request):
    """Inclui à mão um concluinte na turma (ex.: não leu o QR Code)."""
    tid = request.path_params["id"]
    form = await request.form()
    u = seguranca.usuario_atual(request)
    with db.engine().begin() as c:
        t = _turma(c, tid)
        m = _carregar(c, form.get("membro_id"))
        if not t or not m or m["status"] in (db.ANONIMIZADO, db.EXCLUIDO):
            flash(request, "Ficha não encontrada.", "erro")
            return ir(f"/integra/turmas/{tid}")
        if m.get("integra_situacao") == "bloqueado":
            flash(request, "Esta ficha tem bloqueio administrativo do INTEGRA. Só o Adm pode desbloquear.", "erro")
            return ir(f"/integra/turmas/{tid}")
        integra.liberar(c, m, "concluido", u["nome"], data_integra=t["data_conclusao"], turma_id=t["id"])
        auditar(request, "INTEGRA_CONCLUSAO", f"Membro #{m['id']}", f"Incluído na turma {t['nome']}", conexao=c)
    flash(request, f"{m['nome_completo']} incluído(a) na turma.")
    return ir(f"/integra/turmas/{tid}")


@seguranca.exigir(*ADMIN_SECRETARIA)
async def campanha(request: Request):
    r = integra.enviar_pedidos()
    auditar(request, "INTEGRA_CAMPANHA", "Membros já cadastrados",
            f"{r['marcados']} pedidos; {r['enviados']} e-mails; {r['sem_email']} sem e-mail; prazo {datas.fmt_data(r['prazo'])}")
    if not r["marcados"]:
        flash(request, "Não há fichas aguardando o pedido de atualização do INTEGRA.")
    else:
        flash(request, f"Pedido registrado para {r['marcados']} ficha(s), prazo {datas.fmt_data(r['prazo'])}. "
                       f"E-mails enviados: {r['enviados']}. Sem e-mail (avise pelo WhatsApp): {r['sem_email']}.")
    return ir("/integra")


# ---------------------------------------------------------------------------
# Quadro INTEGRA na ficha do membro
# ---------------------------------------------------------------------------
@seguranca.exigir(*ADMIN_SECRETARIA)
async def acao_ficha(request: Request):
    mid = request.path_params["id"]
    form = await request.form()
    acao = form.get("acao")
    u = seguranca.usuario_atual(request)
    justificativa = (form.get("motivo") or "").strip()[:1000]
    with db.engine().begin() as c:
        m = _carregar(c, mid)
        if not m or m["status"] in (db.ANONIMIZADO, db.EXCLUIDO):
            return ir("/membros")
        bloqueado = m.get("integra_situacao") == "bloqueado"
        if acao in ("bloquear", "desbloquear") and u["perfil"] != "admin":
            flash(request, "O bloqueio administrativo do INTEGRA é feito só pelo Adm.", "erro")
            return ir(f"/membros/{mid}")
        if bloqueado and acao in ("registrar", "dispensar"):
            flash(request, "Esta ficha tem bloqueio administrativo do INTEGRA. Só o Adm pode desbloquear.", "erro")
            return ir(f"/membros/{mid}")
        if acao in ("dispensar", "bloquear", "desbloquear") and len(justificativa) < JUSTIFICATIVA_MINIMA:
            flash(request, "Escreva a justificativa (pelo menos 10 caracteres).", "erro")
            return ir(f"/membros/{mid}")
        if acao == "registrar":
            t = _turma(c, form.get("turma_id")) if form.get("turma_id") else None
            data_i = t["data_conclusao"] if t else datas.parse_data(form.get("data"))
            if not data_i or data_i > datas.hoje():
                flash(request, "Escolha a turma ou informe a data de conclusão (dd/mm/aaaa).", "erro")
                return ir(f"/membros/{mid}")
            status = integra.liberar(c, m, "concluido", u["nome"], data_integra=data_i, turma_id=t["id"] if t else None)
            auditar(request, "INTEGRA_CONCLUSAO", f"Membro #{mid}",
                    f"{t['nome'] if t else 'Sem turma'} · {datas.fmt_data(data_i)} · status {status}", conexao=c)
            flash(request, "Conclusão do INTEGRA registrada." + (" A ficha seguiu para a análise." if status == "Aguardando Análise" else ""))
        elif acao == "dispensar":
            status = integra.liberar(c, m, "dispensado", u["nome"], justificativa=justificativa)
            auditar(request, "INTEGRA_DISPENSA", f"Membro #{mid}", justificativa, conexao=c)
            flash(request, "Dispensa do INTEGRA registrada.")
        elif acao == "bloquear":
            integra.segurar(c, m, "bloqueado", u["nome"], justificativa)
            auditar(request, "INTEGRA_BLOQUEIO", f"Membro #{mid}", justificativa, conexao=c)
            flash(request, "Bloqueio administrativo aplicado: ficha N/C INTEGRA e acesso suspenso.")
        elif acao == "desbloquear" and bloqueado:
            situacao = "concluido" if m.get("integra_data") else "dispensado"
            integra.liberar(c, m, situacao, u["nome"], justificativa=justificativa)
            auditar(request, "INTEGRA_DESBLOQUEIO", f"Membro #{mid}", justificativa, conexao=c)
            flash(request, "Bloqueio retirado.")
    return ir(f"/membros/{mid}")


# ---------------------------------------------------------------------------
# Telas públicas
# ---------------------------------------------------------------------------
async def confirmar_codigo(request: Request):
    """Aberta pelo QR Code no encerramento: o participante informa o CPF."""
    codigo = integra.normalizar_codigo(request.path_params["codigo"])
    with db.engine().connect() as c:
        t, erro = integra.turma_do_codigo(c, codigo)
    ctx = {"t": t, "erro_codigo": erro, "codigo": codigo}
    if request.method == "GET" or erro:
        return render(request, "integra/confirmar.html", ctx, status_code=200 if not erro else 410 if t else 404)
    if not await seguranca.conferir_csrf(request):
        flash(request, "A página expirou. Tente de novo.", "erro")
        return ir(f"/integra/c/{codigo}")
    ip = seguranca.ip_cliente(request)
    if seguranca.ip_bloqueado(ip):
        return render(request, "integra/confirmar.html", {**ctx, "erro": "Muitas tentativas. Tente mais tarde."}, 429)
    form = await request.form()
    cpf = ficha.so_digitos(form.get("cpf") or "")
    if not ficha.cpf_valido(cpf):
        seguranca.registrar_falha_ip(ip)
        return render(request, "integra/confirmar.html", {**ctx, "erro": ficha.ERRO_CPF, "cpf": form.get("cpf")}, 400)
    with db.engine().begin() as c:
        m = c.execute(select(db.membros).where(db.membros.c.cpf == cpf, db.membros.c.status.notin_(
            (db.ANONIMIZADO, db.EXCLUIDO)))).mappings().first()
        if not m:
            return ir(f"/ficha?integra={codigo}")
        m = dict(m)
        if m.get("integra_situacao") == "bloqueado":
            return render(request, "integra/confirmar.html", {**ctx, "erro": "Procure a Secretaria para concluir o seu cadastro."}, 403)
        status = integra.liberar(c, m, "concluido", "Código da turma", data_integra=t["data_conclusao"], turma_id=t["id"])
        auditar(request, "INTEGRA_CONCLUSAO", f"Membro #{m['id']}", f"Pelo código da turma {t['nome']}",
                usuario={"id": None, "nome": "Participante (QR Code)"}, conexao=c)
    primeiro = (m["nome_completo"] or "").split(" ")[0]
    return render(request, "integra/confirmar.html", {**ctx, "ok": True, "primeiro": primeiro, "status": status})


async def atualizar(request: Request):
    """Link da campanha para quem já tinha cadastro."""
    mid = request.path_params["id"]
    token = request.query_params.get("t") or ""
    if request.method == "POST":
        form = await request.form()
        token = form.get("t") or token
    if not seguranca.conferir_token_link("integra", mid, token):
        return render(request, "erro.html", {"titulo": "Link inválido",
                      "mensagem": "Este link não é válido. Peça um novo à Secretaria."}, 403)
    with db.engine().connect() as c:
        m = _carregar(c, mid)
    if not m or m["status"] in (db.ANONIMIZADO, db.EXCLUIDO):
        return render(request, "erro.html", {"titulo": "Indisponível", "mensagem": "Ficha indisponível."}, 404)
    ctx = {"m": m, "token": token, "valores": {}, "erros": {}, "SIM_NAO": ("Sim", "Não"),
           "primeiro": (m["nome_completo"] or "").split(" ")[0], "rotulo": integra.rotulo(m.get("integra_situacao"))}
    if request.method == "GET" or m.get("integra_situacao") in integra.LIBERADO + ("bloqueado",):
        return render(request, "integra/atualizar.html", ctx)
    if not await seguranca.conferir_csrf(request):
        flash(request, "A página expirou. Responda de novo.", "erro")
        return ir(f"/integra/atualizar/{mid}?t={token}")
    with db.engine().begin() as c:
        valores, erros = integra.resposta_do_form(c, form)
        if erros:
            return render(request, "integra/atualizar.html", {**ctx, "valores": dict(form), "erros": erros}, 400)
        por = "Membro (atualização)"
        if valores["integra_situacao"] == "concluido":
            integra.liberar(c, m, "concluido", "Código da turma", data_integra=valores["integra_data"],
                            turma_id=valores["integra_turma_id"])
        elif valores["integra_situacao"] == "aguardando":
            # Disse que fez, sem código: a Secretaria confirma; quem já tinha acesso continua com ele
            c.execute(update(db.membros).where(db.membros.c.id == mid).values(
                integra_situacao="aguardando", integra_data=valores["integra_data"],
                integra_turma_id=valores["integra_turma_id"], integra_registrado_por=por,
                integra_registrado_em=datas.agora_utc(), integra_prazo=None))
        else:
            integra.segurar(c, m, "nao_concluido", por)
            c.execute(update(db.membros).where(db.membros.c.id == mid).values(integra_prazo=None))
        auditar(request, "INTEGRA_RESPOSTA", f"Membro #{mid}", integra.rotulo(valores["integra_situacao"]),
                usuario={"id": None, "nome": "Membro (link)"}, conexao=c)
    return render(request, "integra/atualizar.html", {**ctx, "respondido": valores["integra_situacao"],
                                                      "rotulo": integra.rotulo(valores["integra_situacao"])})


rotas = [
    Route("/integra", painel),
    Route("/integra/turmas", nova_turma, methods=["POST"]),
    Route("/integra/turmas/{id:int}", turma),
    Route("/integra/turmas/{id:int}/projetar", projetar),
    Route("/integra/turmas/{id:int}/prorrogar", prorrogar, methods=["POST"]),
    Route("/integra/turmas/{id:int}/incluir", incluir, methods=["POST"]),
    Route("/integra/campanha", campanha, methods=["POST"]),
    Route("/membros/{id:int}/integra", acao_ficha, methods=["POST"]),
    Route("/integra/c/{codigo}", confirmar_codigo, methods=["GET", "POST"]),
    Route("/integra/atualizar/{id:int}", atualizar, methods=["GET", "POST"]),
]
