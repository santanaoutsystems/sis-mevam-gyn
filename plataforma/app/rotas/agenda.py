"""Agenda de eventos, inscrições, financeiro e relatórios (porta do antigo painel Streamlit)."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

from sqlalchemy import delete, func, insert, select, update
from starlette.requests import Request
from starlette.routing import Route

from .. import datas, db, ficha, notificacoes, seguranca
from ..web import auditar, flash, ir, render

GESTAO = db.PERFIS_AGENDA
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


def _evento(c, eid) -> dict | None:
    r = c.execute(select(db.eventos).where(db.texto(db.eventos.c.id) == str(eid))).mappings().first()
    if not r:
        return None
    e = dict(r)
    e["quando"] = datas.parse_data_hora_local(e["data_inicio"])
    return e


def _deptos(c) -> list[dict]:
    return [dict(r) for r in c.execute(select(db.departamentos).order_by(db.departamentos.c.nome)).mappings()]


def escopo_setores(c, usuario: dict) -> set[str] | None:
    """Setores (nomes) que o usuário pode gerenciar. None = todos (Secretaria e Adm)."""
    if usuario["perfil"] != "coordenacao":
        return None
    return set(c.execute(select(db.departamentos.c.nome).select_from(
        db.usuario_setores.join(db.departamentos, db.DEP_ID == db.usuario_setores.c.departamento_id))
        .where(db.usuario_setores.c.usuario_id == usuario["id"])).scalars())


def _pode_gerir(escopo: set[str] | None, evento: dict | None) -> bool:
    return bool(evento) and (escopo is None or evento.get("departamento") in escopo)


def _fora_do_setor(request: Request):
    return render(request, "erro.html", {"titulo": "Acesso restrito",
                  "mensagem": "Este evento é de um setor que não está sob a sua coordenação."}, 403)


def _deptos_permitidos(c, escopo: set[str] | None) -> list[dict]:
    return [d for d in _deptos(c) if escopo is None or d["nome"] in escopo]


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


INTERVALO_MINIMO = timedelta(hours=2)
PODE_LIBERAR_CONFLITO = ("secretaria", "admin")


def _conflitos(c, data_iso: str, ignorar_id: int | None = None) -> list[dict]:
    """Eventos (de qualquer setor ou local) a menos de 2 horas do horário pedido.

    Evita interferência acústica e de logística. Vários eventos no mesmo dia são
    permitidos desde que respeitem o intervalo.
    """
    alvo = datetime.fromisoformat(data_iso)
    de, ate = (alvo - timedelta(days=1)).date().isoformat(), (alvo + timedelta(days=2)).date().isoformat()
    if db._DATA_EVENTO["modo"] == "texto":
        # Compara só a data (texto) para pegar também registros legados com espaço no lugar do 'T'
        filtro = (db.eventos.c.data_inicio >= de, db.eventos.c.data_inicio < ate)
    else:
        filtro = (db.eventos.c.data_inicio >= db.data_evento(f"{de}T00:00:00"),
                  db.eventos.c.data_inicio < db.data_evento(f"{ate}T00:00:00"))
    q = select(db.eventos.c.id, db.eventos.c.titulo, db.eventos.c.departamento, db.eventos.c.local,
               db.eventos.c.data_inicio).where(*filtro)
    achados = []
    for r in c.execute(q).mappings():
        quando = datas.parse_data_hora_local(r["data_inicio"])
        if str(r["id"]) != str(ignorar_id) and quando and abs(quando - alvo) < INTERVALO_MINIMO:
            achados.append({**r, "quando": quando})
    return sorted(achados, key=lambda e: e["quando"])


def _verificar_conflito(c, form, dados: dict, usuario: dict, erros: dict, ignorar_id: int | None = None) -> dict | None:
    """Aplica a regra das 2 horas. Secretaria e Adm podem liberar com motivo; devolve a liberação, se houver."""
    conflitos = _conflitos(c, dados["data_inicio"], ignorar_id)
    if not conflitos:
        return None
    lista = "; ".join(f"\"{e['titulo']}\" às {e['quando'].strftime('%H:%M')} de {e['quando'].strftime('%d/%m')}"
                      f" ({e.get('departamento') or 'Geral'}{', ' + e['local'] if e.get('local') else ''})"
                      for e in conflitos)
    pode_liberar = usuario["perfil"] in PODE_LIBERAR_CONFLITO
    motivo = (form.get("motivo_liberacao") or "").strip()
    if pode_liberar and form.get("liberar_conflito") == "sim":
        if len(motivo) >= 5:
            return {"conflitos": lista, "motivo": motivo}
        erros["motivo_liberacao"] = "Informe o motivo da liberação."
    erros["data"] = (f"Conflito de agenda: é preciso um intervalo mínimo de 2 horas entre eventos. "
                     f"Já existe {lista}.")
    if not pode_liberar:
        erros["data"] += " Escolha outro horário ou peça a liberação à Secretaria ou ao Adm."
    erros["_conflito"] = True
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
            db.eventos.c.data_inicio >= db.data_evento(inicio), db.eventos.c.data_inicio <= db.data_evento(fim))
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
        inscritos = [dict(r) for r in c.execute(select(db.inscricoes).where(db.texto(db.inscricoes.c.evento_id) == str(eid))
                                                .order_by(db.inscricoes.c.nome)).mappings()]
        custos = [dict(r) for r in c.execute(select(db.custos_evento).where(db.texto(db.custos_evento.c.evento_id) == str(eid))
                                             .order_by(db.custos_evento.c.id)).mappings()]
    lim = e.get("limite_vagas") or 0
    e["vagas_txt"] = "Livre acesso" if not lim else f"{max(lim - len(inscritos), 0)} vagas restantes de {lim}"
    ctx = {"e": e, "TIPOS_INGRESSO": TIPOS_INGRESSO, "FORMAS_PAGAMENTO": FORMAS_PAGAMENTO,
           "STATUS_PAGAMENTO": STATUS_PAGAMENTO}
    with db.engine().connect() as c:
        ctx["pode_gerir"] = u["perfil"] in GESTAO and _pode_gerir(escopo_setores(c, u), e)
    if ctx["pode_gerir"]:
        ctx.update(inscritos=inscritos, custos=custos, fin=_resumo_financeiro(inscritos, custos))
    return render(request, "eventos/detalhe.html", ctx)


# ---------------------------------------------------------------------------
# Gestão de eventos (Secretaria / Admin)
# ---------------------------------------------------------------------------
@seguranca.exigir(*GESTAO)
async def novo(request: Request):
    u = seguranca.usuario_atual(request)
    with db.engine().connect() as c:
        escopo = escopo_setores(c, u)
        deptos = _deptos_permitidos(c, escopo)
    if escopo is not None and not deptos:
        return render(request, "erro.html", {"titulo": "Nenhum setor atribuído",
                      "mensagem": "Peça à Secretaria ou ao Adm para definir os setores que você coordena."}, 403)
    if request.method == "GET":
        return render(request, "eventos/form.html", {"deptos": deptos, "valores": {}, "erros": {}})
    form = await request.form()
    dados, erros = _ler_form_evento(form)
    if escopo is not None and dados["departamento"] not in escopo:
        erros["departamento"] = "Escolha um dos setores que você coordena."
    with db.engine().begin() as c:
        liberacao = None if erros else _verificar_conflito(c, form, dados, u, erros)
        if erros:
            return render(request, "eventos/form.html", {"deptos": deptos, "valores": dict(form), "erros": erros}, 400)
        carimbo = _carimbo(u)
        historico = f"[{carimbo}] Criado"
        if liberacao:
            historico += f"\n[{carimbo}] Conflito de horário liberado ({liberacao['conflitos']}). Motivo: {liberacao['motivo']}"
        dados.update(criado_por=carimbo, historico_alteracoes=historico)
        eid = c.execute(insert(db.eventos).values(**{**dados, "data_inicio": db.data_evento(dados["data_inicio"])})).inserted_primary_key[0]
        auditar(request, "EVENTO_CRIADO", f"Evento #{eid}", dados["titulo"], conexao=c)
        if liberacao:
            auditar(request, "CONFLITO_LIBERADO", f"Evento #{eid}",
                    f"{liberacao['conflitos']}. Motivo: {liberacao['motivo']}", conexao=c)
    notificacoes.alerta_evento("novo", dados, u["nome"])
    flash(request, "Evento salvo na agenda.")
    return ir(f"/eventos/{eid}")


@seguranca.exigir(*GESTAO)
async def editar(request: Request):
    eid = request.path_params["id"]
    u = seguranca.usuario_atual(request)
    with db.engine().connect() as c:
        e = _evento(c, eid)
        escopo = escopo_setores(c, u)
        deptos = _deptos_permitidos(c, escopo)
    if not e:
        return ir("/agenda")
    if not _pode_gerir(escopo, e):
        return _fora_do_setor(request)
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
    if escopo is not None and dados["departamento"] not in escopo:
        erros["departamento"] = "Escolha um dos setores que você coordena."
    with db.engine().begin() as c:
        liberacao = None if erros else _verificar_conflito(c, form, dados, u, erros, ignorar_id=eid)
        if erros:
            return render(request, "eventos/form.html",
                          {"deptos": deptos, "valores": dict(form), "erros": erros, "e": e}, 400)
        carimbo = _carimbo(u)
        historico = f"{e.get('historico_alteracoes') or ''}\n[{carimbo}] Atualizado: {justificativa}".strip()
        if liberacao:
            historico += f"\n[{carimbo}] Conflito de horário liberado ({liberacao['conflitos']}). Motivo: {liberacao['motivo']}"
            auditar(request, "CONFLITO_LIBERADO", f"Evento #{eid}",
                    f"{liberacao['conflitos']}. Motivo: {liberacao['motivo']}", conexao=c)
        c.execute(update(db.eventos).where(db.texto(db.eventos.c.id) == str(eid)).values(
            **{**dados, "data_inicio": db.data_evento(dados["data_inicio"])},
            criado_por=carimbo, historico_alteracoes=historico))
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
        if not _pode_gerir(escopo_setores(c, u), e):
            return _fora_do_setor(request)
        if len(justificativa) < 5:
            flash(request, "Informe a justificativa para excluir o evento.", "erro")
            return ir(f"/eventos/{eid}")
        tem_dados = c.execute(select(func.count()).select_from(db.inscricoes)
                              .where(db.texto(db.inscricoes.c.evento_id) == str(eid))).scalar() or \
            c.execute(select(func.count()).select_from(db.custos_evento)
                      .where(db.texto(db.custos_evento.c.evento_id) == str(eid))).scalar()
        if tem_dados:
            flash(request, "Este evento tem inscrições ou custos lançados. Para não perder esses dados, "
                           "remova-os antes ou mantenha o evento.", "erro")
            return ir(f"/eventos/{eid}")
        c.execute(delete(db.eventos).where(db.texto(db.eventos.c.id) == str(eid)))
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
    if (form.get("telefone") or "").strip() and not ficha.telefone_valido(form.get("telefone")):
        erros["telefone"] = ficha.ERRO_TELEFONE
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
        if not _pode_gerir(escopo_setores(c, seguranca.usuario_atual(request)), e):
            return _fora_do_setor(request)
        dados, erros = _ler_inscricao(form, e.get("valor_inscricao") or 0)
        if form.get("lgpd") != "sim":
            erros["lgpd"] = "Confirme o consentimento LGPD do participante."
        lim = e.get("limite_vagas") or 0
        if lim:
            ocupadas = c.execute(select(func.count()).select_from(db.inscricoes)
                                 .where(db.texto(db.inscricoes.c.evento_id) == str(eid))).scalar()
            if ocupadas >= lim:
                erros["vagas"] = "Não há mais vagas neste evento."
        if erros:
            for msg in erros.values():
                flash(request, msg, "erro")
            return ir(f"/eventos/{eid}#inscricoes")
        u = seguranca.usuario_atual(request)
        dados["observacoes"] = f"[{_carimbo(u)}] Inscrição registrada com consentimento LGPD."
        iid = c.execute(insert(db.inscricoes).values(evento_id=e["id"], **dados)).inserted_primary_key[0]
        auditar(request, "INSCRICAO_CRIADA", f"Inscrição #{iid} / Evento #{eid}", dados["nome"], conexao=c)
    flash(request, f"{dados['nome']} inscrito(a).")
    return ir(f"/eventos/{eid}#inscricoes")


@seguranca.exigir(*GESTAO)
async def editar_inscricao(request: Request):
    iid = request.path_params["iid"]
    form = await request.form()
    justificativa = (form.get("justificativa") or "").strip()
    with db.engine().begin() as c:
        atual = c.execute(select(db.inscricoes).where(db.texto(db.inscricoes.c.id) == str(iid))).mappings().first()
        if not atual:
            return ir("/agenda")
        eid = atual["evento_id"]
        e = _evento(c, eid)
        if not _pode_gerir(escopo_setores(c, seguranca.usuario_atual(request)), e):
            return _fora_do_setor(request)
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
        c.execute(update(db.inscricoes).where(db.texto(db.inscricoes.c.id) == str(iid)).values(**dados))
        auditar(request, "INSCRICAO_ATUALIZADA", f"Inscrição #{iid}", justificativa, conexao=c)
    flash(request, "Inscrição atualizada.")
    return ir(f"/eventos/{eid}#inscricoes")


@seguranca.exigir(*GESTAO)
async def excluir_inscricao(request: Request):
    iid = request.path_params["iid"]
    form = await request.form()
    justificativa = (form.get("justificativa") or "").strip()
    with db.engine().begin() as c:
        atual = c.execute(select(db.inscricoes).where(db.texto(db.inscricoes.c.id) == str(iid))).mappings().first()
        if not atual:
            return ir("/agenda")
        if not _pode_gerir(escopo_setores(c, seguranca.usuario_atual(request)), _evento(c, atual["evento_id"])):
            return _fora_do_setor(request)
        if len(justificativa) < 5:
            flash(request, "A justificativa é obrigatória para excluir a inscrição.", "erro")
            return ir(f"/eventos/{atual['evento_id']}#inscricoes")
        c.execute(delete(db.inscricoes).where(db.texto(db.inscricoes.c.id) == str(iid)))
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
        e = _evento(c, eid)
        if not e:
            return ir("/agenda")
        if not _pode_gerir(escopo_setores(c, seguranca.usuario_atual(request)), e):
            return _fora_do_setor(request)
        cid = c.execute(insert(db.custos_evento).values(evento_id=e["id"], descricao=descricao, valor=valor)).inserted_primary_key[0]
        auditar(request, "CUSTO_LANCADO", f"Custo #{cid} / Evento #{eid}", f"{descricao}: {valor:.2f}", conexao=c)
    flash(request, "Despesa lançada.")
    return ir(f"/eventos/{eid}#financeiro")


@seguranca.exigir(*GESTAO)
async def excluir_custo(request: Request):
    cid = request.path_params["cid"]
    with db.engine().begin() as c:
        atual = c.execute(select(db.custos_evento).where(db.texto(db.custos_evento.c.id) == str(cid))).mappings().first()
        if not atual:
            return ir("/agenda")
        if not _pode_gerir(escopo_setores(c, seguranca.usuario_atual(request)), _evento(c, atual["evento_id"])):
            return _fora_do_setor(request)
        c.execute(delete(db.custos_evento).where(db.texto(db.custos_evento.c.id) == str(cid)))
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
        if not _pode_gerir(escopo_setores(c, seguranca.usuario_atual(request)), e):
            return _fora_do_setor(request)
        inscritos = [dict(r) for r in c.execute(select(db.inscricoes).where(db.texto(db.inscricoes.c.evento_id) == str(eid))
                                                .order_by(db.inscricoes.c.nome)).mappings()]
        custos = [dict(r) for r in c.execute(select(db.custos_evento).where(db.texto(db.custos_evento.c.evento_id) == str(eid))).mappings()]
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
            db.eventos.c.data_inicio >= db.data_evento(f"{de.isoformat()}T00:00:00"),
            db.eventos.c.data_inicio <= db.data_evento(f"{ate.isoformat()}T23:59:59")).order_by(db.eventos.c.data_inicio)).mappings()]
        escopo = escopo_setores(c, seguranca.usuario_atual(request))
    eventos = [e for e in eventos if _pode_gerir(escopo, e)]
    for e in eventos:
        e["quando"] = datas.parse_data_hora_local(e["data_inicio"])
    return render(request, "eventos/relatorio_periodo.html", {"eventos": eventos, "de": de, "ate": ate,
                                                               "emitido": datas.agora()})


rotas = [
    Route("/agenda", agenda),
    Route("/eventos/novo", novo, methods=["GET", "POST"]),
    Route("/eventos/{id}", detalhe),
    Route("/eventos/{id}/editar", editar, methods=["GET", "POST"]),
    Route("/eventos/{id}/excluir", excluir, methods=["POST"]),
    Route("/eventos/{id}/inscricoes", inscrever, methods=["POST"]),
    Route("/inscricoes/{iid}/editar", editar_inscricao, methods=["POST"]),
    Route("/inscricoes/{iid}/excluir", excluir_inscricao, methods=["POST"]),
    Route("/eventos/{id}/custos", lancar_custo, methods=["POST"]),
    Route("/custos/{cid}/excluir", excluir_custo, methods=["POST"]),
    Route("/eventos/{id}/relatorio", relatorio_evento),
    Route("/relatorios/periodo", relatorio_periodo),
]
