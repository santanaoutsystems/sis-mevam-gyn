"""Agenda de eventos, inscrições, financeiro e relatórios (porta do antigo painel Streamlit)."""

from __future__ import annotations

import calendar
from datetime import date

from sqlalchemy import delete, func, insert, select, update
from starlette.requests import Request
from starlette.routing import Route

from .. import datas, db, ficha, notificacoes, seguranca
from ..web import auditar, flash, ir, render

GESTAO = ("secretaria", "admin")
TIPOS_INGRESSO = ["Inteira", "Meia (5-11 anos)", "Cortesia/Isento"]
FORMAS_PAGAMENTO = ["Pix", "Cartão de Crédito", "Cartão de Débito", "Dinheiro", "A Receber"]
STATUS_PAGAMENTO = ["Confirmado", "Pendente"]


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------
def _num(valor, padrao=0.0) -> float:
    """Aceita '1.234,56', '1234,56' ou '1234.56'."""
    if valor in (None, ""):
        return padrao
    texto = str(valor).strip().replace("R$", "").replace(" ", "")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return round(float(texto), 2)
    except ValueError:
        return padrao


def _valor_ingresso(base: float, tipo: str) -> float:
    if tipo.startswith("Meia"):
        return round((base or 0) / 2, 2)
    if tipo.startswith("Cortesia"):
        return 0.0
    return float(base or 0)


def _evento(c, eid: int) -> dict | None:
    r = c.execute(select(db.eventos).where(db.eventos.c.id == eid)).mappings().first()
    if not r:
        return None
    e = dict(r)
    e["quando"] = datas.parse_data_hora_local(e["data_inicio"])
    return e


def _deptos(c) -> list[dict]:
    return [dict(r) for r in c.execute(select(db.departamentos).order_by(db.departamentos.c.nome)).mappings()]


def _carimbo(usuario: dict) -> str:
    return f"{usuario['nome']} em {datas.agora().strftime('%d/%m/%Y às %H:%M')}"


def _resumo_financeiro(inscritos: list[dict], custos: list[dict]) -> dict:
    conf = [i for i in inscritos if i.get("status_pagamento") == "Confirmado"]
    por_forma = {f: sum(i.get("valor_pago") or 0 for i in conf if i.get("forma_pagamento") == f)
                 for f in FORMAS_PAGAMENTO if f != "A Receber"}
    receita = sum(por_forma.values())
    despesa = sum(c.get("valor") or 0 for c in custos)
    a_receber = sum(i.get("valor_pago") or 0 for i in inscritos if i.get("status_pagamento") == "Pendente")
    publico = {t: sum(1 for i in inscritos if (i.get("tipo_ingresso") or "").startswith(t.split(" ")[0]))
               for t in TIPOS_INGRESSO}
    return {"por_forma": por_forma, "receita": receita, "despesa": despesa, "a_receber": a_receber,
            "resultado": receita - despesa, "publico": publico, "total_inscritos": len(inscritos)}


def _ler_form_evento(form) -> tuple[dict, dict]:
    erros = {}
    titulo = (form.get("titulo") or "").strip()
    if len(titulo) < 3:
        erros["titulo"] = "Informe o título do evento."
    d = datas.parse_data(form.get("data"))
    if not d:
        erros["data"] = "Data inválida (use dd/mm/aaaa)."
    h = datas.parse_hora(form.get("hora"))
    if not h:
        erros["hora"] = "Hora inválida (use HH:MM)."
    vagas = int(_num(form.get("limite_vagas"), 0)) if form.get("controle_vagas") == "fixo" else 0
    if form.get("controle_vagas") == "fixo" and vagas < 1:
        erros["limite_vagas"] = "Informe o número de vagas."
    dados = {
        "titulo": titulo,
        "departamento": (form.get("departamento") or "Geral").strip(),
        "valor_inscricao": max(_num(form.get("valor_inscricao")), 0.0),
        "limite_vagas": vagas,
        "descricao": (form.get("descricao") or "").strip() or None,
        "local": (form.get("local") or "").strip() or None,
    }
    if d and h:
        dados["data_inicio"] = datas.iso_evento(d, h)
    return dados, erros


def _conflito(c, data_iso: str, departamento: str, ignorar_id: int | None = None) -> dict | None:
    dia = data_iso[:10]
    q = select(db.eventos.c.id, db.eventos.c.titulo, db.eventos.c.departamento).where(
        db.eventos.c.data_inicio >= f"{dia}T00:00:00", db.eventos.c.data_inicio <= f"{dia}T23:59:59")
    for r in c.execute(q).mappings():
        if r["id"] != ignorar_id and r["departamento"] != departamento:
            return dict(r)
    return None


# ---------------------------------------------------------------------------
# Agenda (todos os perfis)
# ---------------------------------------------------------------------------
@seguranca.exigir()
async def agenda(request: Request):
    hoje = datas.hoje()
    try:
        ano, mes = (int(x) for x in (request.query_params.get("mes") or f"{hoje.year}-{hoje.month}").split("-"))
        date(ano, mes, 1)
    except (ValueError, TypeError):
        ano, mes = hoje.year, hoje.month
    inicio = f"{ano:04d}-{mes:02d}-01T00:00:00"
    fim = f"{ano:04d}-{mes:02d}-{calendar.monthrange(ano, mes)[1]:02d}T23:59:59"
    with db.engine().connect() as c:
        eventos = [dict(r) for r in c.execute(select(db.eventos).where(
            db.eventos.c.data_inicio >= inicio, db.eventos.c.data_inicio <= fim)
            .order_by(db.eventos.c.data_inicio)).mappings()]
        ocupadas = dict(c.execute(select(db.inscricoes.c.evento_id, func.count())
                                  .group_by(db.inscricoes.c.evento_id)).all())
        responsaveis = {d["nome"]: d.get("responsavel") for d in _deptos(c)}
    por_dia: dict[int, list] = {}
    for e in eventos:
        e["quando"] = datas.parse_data_hora_local(e["data_inicio"])
        e["dia_semana"] = datas.dia_semana(e["quando"].date()) if e["quando"] else ""
        e["responsavel"] = responsaveis.get(e.get("departamento"))
        lim = e.get("limite_vagas") or 0
        e["vagas_txt"] = "Livre" if not lim else f"{max(lim - ocupadas.get(e['id'], 0), 0)} de {lim} vagas"
        if e["quando"]:
            por_dia.setdefault(e["quando"].day, []).append(e)
    anterior = date(ano - 1, 12, 1) if mes == 1 else date(ano, mes - 1, 1)
    seguinte = date(ano + 1, 1, 1) if mes == 12 else date(ano, mes + 1, 1)
    return render(request, "eventos/agenda.html", {
        "eventos": eventos, "semanas": calendar.monthcalendar(ano, mes), "por_dia": por_dia,
        "ano": ano, "mes": mes, "nome_mes": datas.MESES[mes - 1], "hoje": hoje,
        "anterior": f"{anterior.year}-{anterior.month}", "seguinte": f"{seguinte.year}-{seguinte.month}",
        "visao": request.query_params.get("visao", "lista")})


@seguranca.exigir()
async def detalhe(request: Request):
    eid = request.path_params["id"]
    u = seguranca.usuario_atual(request)
    with db.engine().connect() as c:
        e = _evento(c, eid)
        if not e:
            return render(request, "erro.html", {"titulo": "Não encontrado", "mensagem": "Evento não encontrado."}, 404)
        inscritos = [dict(r) for r in c.execute(select(db.inscricoes).where(db.inscricoes.c.evento_id == eid)
                                                .order_by(db.inscricoes.c.nome)).mappings()]
        custos = [dict(r) for r in c.execute(select(db.custos_evento).where(db.custos_evento.c.evento_id == eid)
                                             .order_by(db.custos_evento.c.id)).mappings()]
    lim = e.get("limite_vagas") or 0
    e["vagas_txt"] = "Livre acesso" if not lim else f"{max(lim - len(inscritos), 0)} vagas restantes de {lim}"
    ctx = {"e": e, "TIPOS_INGRESSO": TIPOS_INGRESSO, "FORMAS_PAGAMENTO": FORMAS_PAGAMENTO,
           "STATUS_PAGAMENTO": STATUS_PAGAMENTO}
    if u["perfil"] in GESTAO:
        ctx.update(inscritos=inscritos, custos=custos, fin=_resumo_financeiro(inscritos, custos))
    return render(request, "eventos/detalhe.html", ctx)


# ---------------------------------------------------------------------------
# Gestão de eventos (Secretaria / Admin)
# ---------------------------------------------------------------------------
@seguranca.exigir(*GESTAO)
async def novo(request: Request):
    with db.engine().connect() as c:
        deptos = _deptos(c)
    if request.method == "GET":
        return render(request, "eventos/form.html", {"deptos": deptos, "valores": {}, "erros": {}})
    form = await request.form()
    dados, erros = _ler_form_evento(form)
    u = seguranca.usuario_atual(request)
    with db.engine().begin() as c:
        if not erros:
            conflito = _conflito(c, dados["data_inicio"], dados["departamento"])
            if conflito:
                erros["data"] = (f"Conflito de agenda: o departamento {conflito['departamento']} já tem "
                                 f"\"{conflito['titulo']}\" nesta data.")
        if erros:
            return render(request, "eventos/form.html", {"deptos": deptos, "valores": dict(form), "erros": erros}, 400)
        carimbo = _carimbo(u)
        dados.update(criado_por=carimbo, historico_alteracoes=f"[{carimbo}] Criado")
        eid = c.execute(insert(db.eventos).values(**dados)).inserted_primary_key[0]
        auditar(request, "EVENTO_CRIADO", f"Evento #{eid}", dados["titulo"], conexao=c)
    notificacoes.alerta_evento("novo", dados, u["nome"])
    flash(request, "Evento salvo na agenda.")
    return ir(f"/eventos/{eid}")


@seguranca.exigir(*GESTAO)
async def editar(request: Request):
    eid = request.path_params["id"]
    with db.engine().connect() as c:
        e = _evento(c, eid)
        deptos = _deptos(c)
    if not e:
        return ir("/agenda")
    if request.method == "GET":
        valores = {**e, "data": e["quando"].strftime("%d/%m/%Y") if e["quando"] else "",
                   "hora": e["quando"].strftime("%H:%M") if e["quando"] else "",
                   "controle_vagas": "fixo" if (e.get("limite_vagas") or 0) > 0 else "livre",
                   "valor_inscricao": f"{(e.get('valor_inscricao') or 0):.2f}".replace(".", ",")}
        return render(request, "eventos/form.html", {"deptos": deptos, "valores": valores, "erros": {}, "e": e})
    form = await request.form()
    dados, erros = _ler_form_evento(form)
    justificativa = (form.get("justificativa") or "").strip()
    if len(justificativa) < 5:
        erros["justificativa"] = "A justificativa é obrigatória para auditoria."
    u = seguranca.usuario_atual(request)
    with db.engine().begin() as c:
        if not erros:
            conflito = _conflito(c, dados["data_inicio"], dados["departamento"], ignorar_id=eid)
            if conflito:
                erros["data"] = (f"Conflito de agenda: o departamento {conflito['departamento']} já tem "
                                 f"\"{conflito['titulo']}\" nesta data.")
        if erros:
            return render(request, "eventos/form.html",
                          {"deptos": deptos, "valores": dict(form), "erros": erros, "e": e}, 400)
        carimbo = _carimbo(u)
        historico = f"{e.get('historico_alteracoes') or ''}\n[{carimbo}] Atualizado: {justificativa}".strip()
        c.execute(update(db.eventos).where(db.eventos.c.id == eid).values(
            **dados, criado_por=carimbo, historico_alteracoes=historico))
        auditar(request, "EVENTO_ATUALIZADO", f"Evento #{eid}", justificativa, conexao=c)
    notificacoes.alerta_evento("atualizado", dados, u["nome"], justificativa)
    flash(request, "Evento atualizado e registrado na auditoria.")
    return ir(f"/eventos/{eid}")


@seguranca.exigir(*GESTAO)
async def excluir(request: Request):
    eid = request.path_params["id"]
    form = await request.form()
    justificativa = (form.get("justificativa") or "").strip()
    u = seguranca.usuario_atual(request)
    with db.engine().begin() as c:
        e = _evento(c, eid)
        if not e:
            return ir("/agenda")
        if len(justificativa) < 5:
            flash(request, "Informe a justificativa para excluir o evento.", "erro")
            return ir(f"/eventos/{eid}")
        tem_dados = c.execute(select(func.count()).select_from(db.inscricoes)
                              .where(db.inscricoes.c.evento_id == eid)).scalar() or \
            c.execute(select(func.count()).select_from(db.custos_evento)
                      .where(db.custos_evento.c.evento_id == eid)).scalar()
        if tem_dados:
            flash(request, "Este evento tem inscrições ou custos lançados. Para não perder esses dados, "
                           "remova-os antes ou mantenha o evento.", "erro")
            return ir(f"/eventos/{eid}")
        c.execute(delete(db.eventos).where(db.eventos.c.id == eid))
        auditar(request, "EVENTO_EXCLUIDO", f"Evento #{eid}", f"{e['titulo']}. Motivo: {justificativa}", conexao=c)
    notificacoes.alerta_evento("cancelado", e, u["nome"], justificativa)
    flash(request, "Evento excluído e registrado na auditoria.")
    return ir("/agenda")


# ---------------------------------------------------------------------------
# Inscrições
# ---------------------------------------------------------------------------
def _ler_inscricao(form, base: float) -> tuple[dict, dict]:
    erros = {}
    nome = ficha.nome_proprio(form.get("nome") or "")
    if len(nome) < 3:
        erros["nome"] = "Informe o nome do participante."
    tipo = form.get("tipo_ingresso") if form.get("tipo_ingresso") in TIPOS_INGRESSO else TIPOS_INGRESSO[0]
    forma = form.get("forma_pagamento") if form.get("forma_pagamento") in FORMAS_PAGAMENTO else "Pix"
    status = form.get("status_pagamento") if form.get("status_pagamento") in STATUS_PAGAMENTO else "Pendente"
    if forma == "A Receber":
        status = "Pendente"
    membro_id = form.get("membro_id")
    return {"nome": nome, "telefone": ficha.fmt_telefone(form.get("telefone") or ""), "tipo_ingresso": tipo,
            "forma_pagamento": forma, "status_pagamento": status, "valor_pago": _valor_ingresso(base, tipo),
            "membro_id": int(membro_id) if membro_id and str(membro_id).isdigit() else None}, erros


@seguranca.exigir(*GESTAO)
async def inscrever(request: Request):
    eid = request.path_params["id"]
    form = await request.form()
    with db.engine().begin() as c:
        e = _evento(c, eid)
        if not e:
            return ir("/agenda")
        dados, erros = _ler_inscricao(form, e.get("valor_inscricao") or 0)
        if form.get("lgpd") != "sim":
            erros["lgpd"] = "Confirme o consentimento LGPD do participante."
        lim = e.get("limite_vagas") or 0
        if lim:
            ocupadas = c.execute(select(func.count()).select_from(db.inscricoes)
                                 .where(db.inscricoes.c.evento_id == eid)).scalar()
            if ocupadas >= lim:
                erros["vagas"] = "Não há mais vagas neste evento."
        if erros:
            for msg in erros.values():
                flash(request, msg, "erro")
            return ir(f"/eventos/{eid}#inscricoes")
        u = seguranca.usuario_atual(request)
        dados["observacoes"] = f"[{_carimbo(u)}] Inscrição registrada com consentimento LGPD."
        iid = c.execute(insert(db.inscricoes).values(evento_id=eid, **dados)).inserted_primary_key[0]
        auditar(request, "INSCRICAO_CRIADA", f"Inscrição #{iid} / Evento #{eid}", dados["nome"], conexao=c)
    flash(request, f"{dados['nome']} inscrito(a).")
    return ir(f"/eventos/{eid}#inscricoes")


@seguranca.exigir(*GESTAO)
async def editar_inscricao(request: Request):
    iid = request.path_params["iid"]
    form = await request.form()
    justificativa = (form.get("justificativa") or "").strip()
    with db.engine().begin() as c:
        atual = c.execute(select(db.inscricoes).where(db.inscricoes.c.id == iid)).mappings().first()
        if not atual:
            return ir("/agenda")
        eid = atual["evento_id"]
        e = _evento(c, eid)
        if len(justificativa) < 5:
            flash(request, "A justificativa é obrigatória para alterar a inscrição.", "erro")
            return ir(f"/eventos/{eid}#inscricoes")
        dados, erros = _ler_inscricao(form, (e or {}).get("valor_inscricao") or 0)
        if erros:
            for msg in erros.values():
                flash(request, msg, "erro")
            return ir(f"/eventos/{eid}#inscricoes")
        u = seguranca.usuario_atual(request)
        dados.pop("membro_id")
        dados["observacoes"] = f"{atual.get('observacoes') or ''}\n[{_carimbo(u)}] {justificativa}".strip()
        c.execute(update(db.inscricoes).where(db.inscricoes.c.id == iid).values(**dados))
        auditar(request, "INSCRICAO_ATUALIZADA", f"Inscrição #{iid}", justificativa, conexao=c)
    flash(request, "Inscrição atualizada.")
    return ir(f"/eventos/{eid}#inscricoes")


@seguranca.exigir(*GESTAO)
async def excluir_inscricao(request: Request):
    iid = request.path_params["iid"]
    form = await request.form()
    justificativa = (form.get("justificativa") or "").strip()
    with db.engine().begin() as c:
        atual = c.execute(select(db.inscricoes).where(db.inscricoes.c.id == iid)).mappings().first()
        if not atual:
            return ir("/agenda")
        if len(justificativa) < 5:
            flash(request, "A justificativa é obrigatória para excluir a inscrição.", "erro")
            return ir(f"/eventos/{atual['evento_id']}#inscricoes")
        c.execute(delete(db.inscricoes).where(db.inscricoes.c.id == iid))
        auditar(request, "INSCRICAO_EXCLUIDA", f"Inscrição #{iid}", f"{atual['nome']}. Motivo: {justificativa}", conexao=c)
    flash(request, "Inscrição excluída.")
    return ir(f"/eventos/{atual['evento_id']}#inscricoes")


# ---------------------------------------------------------------------------
# Custos
# ---------------------------------------------------------------------------
@seguranca.exigir(*GESTAO)
async def lancar_custo(request: Request):
    eid = request.path_params["id"]
    form = await request.form()
    descricao = (form.get("descricao") or "").strip()
    valor = _num(form.get("valor"))
    if not descricao or valor <= 0:
        flash(request, "Informe descrição e valor da despesa.", "erro")
        return ir(f"/eventos/{eid}#financeiro")
    with db.engine().begin() as c:
        cid = c.execute(insert(db.custos_evento).values(evento_id=eid, descricao=descricao, valor=valor)).inserted_primary_key[0]
        auditar(request, "CUSTO_LANCADO", f"Custo #{cid} / Evento #{eid}", f"{descricao}: {valor:.2f}", conexao=c)
    flash(request, "Despesa lançada.")
    return ir(f"/eventos/{eid}#financeiro")


@seguranca.exigir(*GESTAO)
async def excluir_custo(request: Request):
    cid = request.path_params["cid"]
    with db.engine().begin() as c:
        atual = c.execute(select(db.custos_evento).where(db.custos_evento.c.id == cid)).mappings().first()
        if not atual:
            return ir("/agenda")
        c.execute(delete(db.custos_evento).where(db.custos_evento.c.id == cid))
        auditar(request, "CUSTO_EXCLUIDO", f"Custo #{cid}", f"{atual['descricao']}: {atual['valor']}", conexao=c)
    flash(request, "Despesa removida.")
    return ir(f"/eventos/{atual['evento_id']}#financeiro")


# ---------------------------------------------------------------------------
# Relatórios (página pronta para imprimir / salvar em PDF)
# ---------------------------------------------------------------------------
@seguranca.exigir(*GESTAO)
async def relatorio_evento(request: Request):
    eid = request.path_params["id"]
    tipo = request.query_params.get("tipo", "lista")
    with db.engine().connect() as c:
        e = _evento(c, eid)
        if not e:
            return ir("/agenda")
        inscritos = [dict(r) for r in c.execute(select(db.inscricoes).where(db.inscricoes.c.evento_id == eid)
                                                .order_by(db.inscricoes.c.nome)).mappings()]
        custos = [dict(r) for r in c.execute(select(db.custos_evento).where(db.custos_evento.c.evento_id == eid)).mappings()]
    if tipo == "inadimplentes":
        inscritos = [i for i in inscritos if i.get("status_pagamento") == "Pendente"]
    auditar(request, "RELATORIO_EVENTO", f"Evento #{eid}", tipo)
    return render(request, "eventos/relatorio.html", {"e": e, "tipo": tipo, "inscritos": inscritos, "custos": custos,
                                                       "fin": _resumo_financeiro(inscritos, custos),
                                                       "emitido": datas.agora()})


@seguranca.exigir(*GESTAO)
async def relatorio_periodo(request: Request):
    hoje = datas.hoje()
    de = datas.parse_data(request.query_params.get("de")) or hoje.replace(day=1)
    ate = datas.parse_data(request.query_params.get("ate")) or date(hoje.year, hoje.month, calendar.monthrange(hoje.year, hoje.month)[1])
    with db.engine().connect() as c:
        eventos = [dict(r) for r in c.execute(select(db.eventos).where(
            db.eventos.c.data_inicio >= f"{de.isoformat()}T00:00:00",
            db.eventos.c.data_inicio <= f"{ate.isoformat()}T23:59:59").order_by(db.eventos.c.data_inicio)).mappings()]
    for e in eventos:
        e["quando"] = datas.parse_data_hora_local(e["data_inicio"])
    return render(request, "eventos/relatorio_periodo.html", {"eventos": eventos, "de": de, "ate": ate,
                                                               "emitido": datas.agora()})


rotas = [
    Route("/agenda", agenda),
    Route("/eventos/novo", novo, methods=["GET", "POST"]),
    Route("/eventos/{id:int}", detalhe),
    Route("/eventos/{id:int}/editar", editar, methods=["GET", "POST"]),
    Route("/eventos/{id:int}/excluir", excluir, methods=["POST"]),
    Route("/eventos/{id:int}/inscricoes", inscrever, methods=["POST"]),
    Route("/inscricoes/{iid:int}/editar", editar_inscricao, methods=["POST"]),
    Route("/inscricoes/{iid:int}/excluir", excluir_inscricao, methods=["POST"]),
    Route("/eventos/{id:int}/custos", lancar_custo, methods=["POST"]),
    Route("/custos/{cid:int}/excluir", excluir_custo, methods=["POST"]),
    Route("/eventos/{id:int}/relatorio", relatorio_evento),
    Route("/relatorios/periodo", relatorio_periodo),
]
