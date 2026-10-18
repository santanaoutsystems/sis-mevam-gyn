"""Central de Relatórios: catálogo por perfil, filtros, visualização, impressão A4 e planilha.

Regras (proposta "Central de Relatórios", Edição 02, aprovada em 17/10/2026):
- Cada perfil só vê no catálogo o que pode emitir. O limite é aplicado aqui no servidor, antes dos filtros:
  a Coordenação recebe só eventos dos setores atribuídos e nunca dados de ficha; o Membro, só os próprios dados.
- Filtros comuns (período, setor, evento, mês) ficam no topo; os demais, nos cabeçalhos das colunas (app/tabelas.py).
- LGPD: mínimo de colunas por padrão, CPF nunca sai, estatísticas sem nomes com grupos < 3 suprimidos,
  anonimizados nunca aparecem, toda emissão/impressão/planilha vai para a Auditoria, páginas sem cache (no-store).
- Planilha (CSV) só para Secretaria e Adm. Telefone dos inscritos para a Coordenação só em "A receber".
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Callable
from urllib.parse import urlencode

from sqlalchemy import delete, insert, select
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .. import datas, db, ficha, seguranca, tabelas
from ..tabelas import Coluna
from ..web import auditar, flash, ir, render
from .agenda import FORMAS_PAGAMENTO, GESTAO, _deptos_permitidos, _resumo_financeiro, escopo_setores
from .voluntarios import interessados, setores_permitidos

TODOS = db.PERFIS
SEC_ADM = ("secretaria", "admin")
EXPORTAM = SEC_ADM
FORA = db.STATUS_FORA
ANONIMIZADO = "Anonimizado (LGPD)"
MINIMO_GRUPO = 3  # estatísticas: grupos menores aparecem como "menos de 3"


@dataclass
class Relatorio:
    chave: str
    titulo: str
    icone: str
    grupo: str
    perfis: tuple
    fn: Callable
    filtros: tuple = ()           # periodo | setor | evento | mes
    periodo_padrao: bool = True   # sem datas no endereço, usa o mês atual (False = todo o histórico)
    descricao: str = ""
    assinatura: bool = False
    dados_pessoais: bool = True


@dataclass
class Ctx:
    c: object
    u: dict
    escopo: set | None
    params: object
    de: date | None = None
    ate: date | None = None
    setor: str = ""
    evento: str = ""
    mes: int = 0
    resumo: list = field(default_factory=list)
    aviso: str = ""


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------
def _fim_mes(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def _atalhos(caminho: str, params) -> list[tuple[str, str]]:
    hoje = datas.hoje()
    ini = hoje.replace(day=1)
    passado_fim = ini - timedelta(days=1)
    base = [(k, v) for k, v in params.multi_items() if k not in ("de", "ate", "evento")]
    def url(de, ate):
        return caminho + "?" + urlencode(base + [("de", datas.fmt_data(de)), ("ate", datas.fmt_data(ate))])
    return [("Este mês", url(ini, _fim_mes(hoje))), ("Mês passado", url(passado_fim.replace(day=1), passado_fim)),
            ("Próximos 30 dias", url(hoje, hoje + timedelta(days=30))),
            ("Este ano", url(date(hoje.year, 1, 1), date(hoje.year, 12, 31)))]


def _limites_utc(de: date | None, ate: date | None):
    """Período local (Goiânia) → instantes UTC para colunas de sistema (timestamptz)."""
    ini = datetime.combine(de, time(0, 0), tzinfo=datas.TZ) if de else None
    fim = datetime.combine(ate, time(23, 59, 59), tzinfo=datas.TZ) if ate else None
    return ini, fim


def _no_periodo(coluna, ctx: Ctx):
    ini, fim = _limites_utc(ctx.de, ctx.ate)
    conds = []
    if ini:
        conds.append(coluna >= ini)
    if fim:
        conds.append(coluna <= fim)
    return conds


def _eventos(ctx: Ctx, so_escopo: bool = True) -> list[dict]:
    q = select(db.eventos).order_by(db.eventos.c.data_inicio)
    if ctx.de:
        q = q.where(db.eventos.c.data_inicio >= db.data_evento(f"{ctx.de.isoformat()}T00:00:00"))
    if ctx.ate:
        q = q.where(db.eventos.c.data_inicio <= db.data_evento(f"{ctx.ate.isoformat()}T23:59:59"))
    lista = []
    for r in ctx.c.execute(q).mappings():
        e = dict(r)
        setor = e.get("departamento") or "Geral"
        if so_escopo and ctx.escopo is not None and e.get("departamento") not in ctx.escopo:
            continue
        if ctx.setor and setor != ctx.setor:
            continue
        if ctx.evento and str(e["id"]) != ctx.evento:
            continue
        e["quando"] = datas.parse_data_hora_local(e["data_inicio"])
        e["setor"] = setor
        lista.append(e)
    return lista


def _inscricoes(ctx: Ctx, eventos: list[dict]) -> list[dict]:
    ids = [str(e["id"]) for e in eventos]
    if not ids:
        return []
    por_id = {str(e["id"]): e for e in eventos}
    linhas = []
    for r in ctx.c.execute(select(db.inscricoes).where(db.texto(db.inscricoes.c.evento_id).in_(ids))).mappings():
        i = dict(r)
        i["ev"] = por_id[str(i["evento_id"])]
        linhas.append(i)
    return linhas


def _link_evento(l):
    return f"/eventos/{l['evento_id']}" if l.get("evento_id") is not None else None


def _membros(c, com_setores: bool = False) -> list[dict]:
    m = db.membros.c
    q = select(m.id, m.nome_completo, m.whatsapp, m.email, m.bairro, m.cidade, m.data_nascimento, m.sexo,
               m.estado_civil, m.status, m.data_registro, m.credo_aceito, m.batizado, m.data_batismo,
               m.interesse_batismo_familia, m.cpf, m.origem, m.validado_por, m.data_validacao,
               m.foto_3x4.isnot(None).label("tem_foto")).where(m.status != db.EXCLUIDO)  # lixeira fica de fora
    linhas = [dict(r) for r in c.execute(q).mappings()]
    if com_setores:
        setores: dict[int, list[str]] = {}
        for mid, nome in c.execute(select(db.membro_setores.c.membro_id, db.departamentos.c.nome).select_from(
                db.membro_setores.join(db.departamentos, db.DEP_ID == db.membro_setores.c.departamento_id))):
            setores.setdefault(mid, []).append(nome)
        for l in linhas:
            l["setores"] = sorted(setores.get(l["id"], []))
    for l in linhas:
        l["foto"] = bool(l.pop("tem_foto"))
        l["data_validacao"] = tabelas.local(l.get("data_validacao"))
    return linhas


def colunas_membros(perfil: str, padrao: tuple) -> list[Coluna]:
    """Colunas da ficha que podem aparecer em listas de membros (nunca CPF, endereço ou assinatura)."""
    link = lambda l: f"/membros/{l['id']}"
    cols = [
        Coluna("id", "#", "numero"),
        Coluna("nome_completo", "Nome", "texto", link=link, destaque=True),
        Coluna("whatsapp", "WhatsApp", "texto", sensivel=True),
        Coluna("email", "E-mail", "texto", sensivel=True),
        Coluna("bairro", "Bairro", "lista"),
        Coluna("cidade", "Cidade", "lista"),
        Coluna("data_nascimento", "Nascimento", "aniversario", sensivel=True),
        Coluna("sexo", "Sexo", "lista"),
        Coluna("estado_civil", "Estado civil", "lista"),
        Coluna("status", "Situação", "lista"),
        Coluna("data_registro", "Cadastro", "data"),
        Coluna("credo_aceito", "Credo assinado", "simnao"),
        Coluna("batizado", "Batizado", "lista"),
        Coluna("foto", "Foto enviada", "simnao"),
        Coluna("setores", "Setor em que serve", "lista"),
    ]
    if perfil == "admin":
        cols += [Coluna("origem", "Origem do cadastro", "lista"), Coluna("validado_por", "Validado por", "lista"),
                 Coluna("data_validacao", "Validado em", "data")]
    for c in cols:
        c.padrao = c.chave in padrao
    return cols


def _contagem(linhas, chave) -> dict:
    cont: dict = {}
    for l in linhas:
        cont[l.get(chave)] = cont.get(l.get(chave), 0) + 1
    return cont


# ---------------------------------------------------------------------------
# Relatórios: Meus dados
# ---------------------------------------------------------------------------
def r_agenda(ctx: Ctx):
    eventos = _eventos(ctx, so_escopo=False)
    ocupadas = {}
    if eventos:
        for i in _inscricoes(ctx, eventos):
            ocupadas[str(i["evento_id"])] = ocupadas.get(str(i["evento_id"]), 0) + 1
    linhas = []
    for e in eventos:
        lim = e.get("limite_vagas") or 0
        linhas.append({"evento_id": e["id"], "quando": e["quando"], "dia": datas.dia_semana(e["quando"].date()) if e["quando"] else "",
                       "titulo": e["titulo"], "setor": e["setor"], "local": e.get("local"),
                       "valor": e.get("valor_inscricao") or 0,
                       "vagas": "Livre" if not lim else f"{max(lim - ocupadas.get(str(e['id']), 0), 0)} de {lim}"})
    ctx.resumo = [(len(linhas), "eventos"), (len({l["setor"] for l in linhas}), "setores")]
    cols = [Coluna("quando", "Data e hora", "data"), Coluna("dia", "Dia", "lista"),
            Coluna("titulo", "Evento", "texto", link=_link_evento, destaque=True), Coluna("setor", "Setor", "lista"),
            Coluna("local", "Local", "lista"), Coluna("valor", "Valor", "moeda"), Coluna("vagas", "Vagas", "texto", ordenavel=False)]
    return cols, linhas


def _minhas(ctx: Ctx):
    mid = ctx.u.get("membro_id")
    if not mid:
        ctx.aviso = "Seu login ainda não está ligado a uma ficha de membro. Peça à Secretaria para fazer a ligação."
        return []
    q = select(db.inscricoes).where(db.inscricoes.c.membro_id == mid)
    linhas = []
    eventos = {str(e["id"]): e for e in _eventos(Ctx(ctx.c, ctx.u, None, ctx.params, ctx.de, ctx.ate), so_escopo=False)}
    for r in ctx.c.execute(q).mappings():
        e = eventos.get(str(r["evento_id"]))
        if not e:
            continue  # fora do período
        linhas.append({"evento_id": r["evento_id"], "quando": e["quando"], "titulo": e["titulo"], "setor": e["setor"],
                       "ingresso": r["tipo_ingresso"], "forma": r["forma_pagamento"],
                       "situacao": r["status_pagamento"], "valor": r["valor_pago"] or 0})
    linhas.sort(key=lambda l: l["quando"] or datetime.min)
    return linhas


def r_minhas_inscricoes(ctx: Ctx):
    linhas = _minhas(ctx)
    ctx.resumo = [(len(linhas), "inscrições"), (sum(1 for l in linhas if l["situacao"] == "Pendente"), "pendentes")]
    return [Coluna("quando", "Data e hora", "data"), Coluna("titulo", "Evento", "texto", link=_link_evento, destaque=True),
            Coluna("setor", "Setor", "lista"), Coluna("ingresso", "Ingresso", "lista"),
            Coluna("situacao", "Pagamento", "lista"), Coluna("valor", "Valor", "moeda")], linhas


def r_extrato(ctx: Ctx):
    linhas = _minhas(ctx)
    pago = sum(l["valor"] for l in linhas if l["situacao"] == "Confirmado")
    pend = sum(l["valor"] for l in linhas if l["situacao"] == "Pendente")
    ctx.resumo = [(tabelas.exibir(Coluna("x", "", "moeda"), pago), "pago no período"),
                  (tabelas.exibir(Coluna("x", "", "moeda"), pend), "pendente")]
    return [Coluna("quando", "Data", "data"), Coluna("titulo", "Evento", "texto", destaque=True),
            Coluna("forma", "Forma de pagamento", "lista"), Coluna("situacao", "Situação", "lista"),
            Coluna("valor", "Valor", "moeda")], linhas


# ---------------------------------------------------------------------------
# Relatórios: Eventos (Coordenação nos seus setores, Secretaria e Adm em todos)
# ---------------------------------------------------------------------------
def _cols_inscricao(com_telefone: bool):
    cols = [Coluna("nome", "Nome", "texto", destaque=True)]
    if com_telefone:
        cols.append(Coluna("telefone", "Telefone", "texto", sensivel=True))
    cols += [Coluna("titulo", "Evento", "lista"), Coluna("quando", "Data", "data"),
             Coluna("ingresso", "Ingresso", "lista"), Coluna("forma", "Forma de pagamento", "lista"),
             Coluna("situacao", "Situação", "lista"), Coluna("valor", "Valor", "moeda")]
    return cols


def _linhas_inscricao(insc):
    return [{"evento_id": i["evento_id"], "nome": i["nome"], "telefone": ficha.fmt_telefone(i.get("telefone") or ""),
             "titulo": i["ev"]["titulo"], "quando": i["ev"]["quando"], "ingresso": i.get("tipo_ingresso"),
             "forma": i.get("forma_pagamento"), "situacao": i.get("status_pagamento"), "valor": i.get("valor_pago") or 0}
            for i in insc]


def r_participantes(ctx: Ctx):
    linhas = sorted(_linhas_inscricao(_inscricoes(ctx, _eventos(ctx))), key=lambda l: tabelas._norm(l["nome"]))
    conf = sum(1 for l in linhas if l["situacao"] == "Confirmado")
    ctx.resumo = [(len(linhas), "inscritos"), (conf, "pagos"), (len(linhas) - conf, "a receber")]
    return _cols_inscricao(False), linhas


def r_a_receber(ctx: Ctx):
    linhas = [l for l in _linhas_inscricao(_inscricoes(ctx, _eventos(ctx))) if l["situacao"] == "Pendente"]
    linhas.sort(key=lambda l: tabelas._norm(l["nome"]))
    total = sum(l["valor"] for l in linhas)
    ctx.resumo = [(len(linhas), "inscrições pendentes"), (tabelas.exibir(Coluna("x", "", "moeda"), total), "a receber")]
    cols = _cols_inscricao(True)
    return [c for c in cols if c.chave != "situacao"], linhas


def r_financeiro(ctx: Ctx):
    eventos = _eventos(ctx)
    insc = _inscricoes(ctx, eventos)
    ids = [str(e["id"]) for e in eventos]
    custos = [dict(r) for r in ctx.c.execute(select(db.custos_evento).where(
        db.texto(db.custos_evento.c.evento_id).in_(ids))).mappings()] if ids else []
    linhas, total = [], {"receita": 0, "despesa": 0, "a_receber": 0}
    por_forma = {f: 0 for f in FORMAS_PAGAMENTO if f != "A Receber"}
    for e in eventos:
        fin = _resumo_financeiro([i for i in insc if str(i["evento_id"]) == str(e["id"])],
                                 [c for c in custos if str(c["evento_id"]) == str(e["id"])])
        for k in total:
            total[k] += fin[k]
        for f, v in fin["por_forma"].items():
            por_forma[f] += v
        linhas.append({"evento_id": e["id"], "titulo": e["titulo"], "quando": e["quando"], "setor": e["setor"],
                       "inscritos": fin["total_inscritos"], "receita": fin["receita"], "despesa": fin["despesa"],
                       "resultado": fin["resultado"], "a_receber": fin["a_receber"]})
    moeda = Coluna("x", "", "moeda")
    ctx.resumo = [(tabelas.exibir(moeda, total["receita"]), "receita"), (tabelas.exibir(moeda, total["despesa"]), "despesas"),
                  (tabelas.exibir(moeda, total["receita"] - total["despesa"]), "resultado"),
                  (tabelas.exibir(moeda, total["a_receber"]), "a receber")]
    ctx.resumo += [(tabelas.exibir(moeda, v), f"receita · {f}") for f, v in por_forma.items() if v]
    return [Coluna("quando", "Data", "data"), Coluna("titulo", "Evento", "texto", link=_link_evento, destaque=True),
            Coluna("setor", "Setor", "lista"), Coluna("inscritos", "Inscritos", "numero"),
            Coluna("receita", "Receita", "moeda"), Coluna("despesa", "Despesas", "moeda"),
            Coluna("resultado", "Resultado", "moeda"), Coluna("a_receber", "A receber", "moeda")], linhas


def r_ocupacao(ctx: Ctx):
    eventos = _eventos(ctx)
    cont: dict = {}
    for i in _inscricoes(ctx, eventos):
        cont[str(i["evento_id"])] = cont.get(str(i["evento_id"]), 0) + 1
    linhas = []
    for e in eventos:
        lim = e.get("limite_vagas") or 0
        n = cont.get(str(e["id"]), 0)
        linhas.append({"evento_id": e["id"], "quando": e["quando"], "titulo": e["titulo"], "setor": e["setor"],
                       "inscritos": n, "limite": lim or None, "ocupacao": round(n * 100 / lim, 1) if lim else None,
                       "controle": "Vagas limitadas" if lim else "Livre"})
    com_lim = [l for l in linhas if l["limite"]]
    media = round(sum(l["ocupacao"] for l in com_lim) / len(com_lim)) if com_lim else 0
    ctx.resumo = [(len(linhas), "eventos"), (sum(l["inscritos"] for l in linhas), "inscritos"),
                  (f"{media}%", "ocupação média (com limite)")]
    pct = lambda v: "-" if v is None else f"{str(v).replace('.', ',').removesuffix(',0')}%"
    return [Coluna("quando", "Data", "data"), Coluna("titulo", "Evento", "texto", link=_link_evento, destaque=True),
            Coluna("setor", "Setor", "lista"), Coluna("controle", "Controle", "lista"),
            Coluna("inscritos", "Inscritos", "numero"), Coluna("limite", "Limite", "numero"),
            Coluna("ocupacao", "Ocupação", "numero", fmt=pct)], linhas


def r_voluntarios(ctx: Ctx):
    setores = setores_permitidos(ctx.c, ctx.u)
    ver_status = ctx.u["perfil"] in SEC_ADM
    linhas = []
    for s in setores:
        for p in interessados(ctx.c, s):
            linhas.append({"setor": s, "nome": p["nome_completo"], "whatsapp": ficha.fmt_telefone(p.get("whatsapp") or ""),
                           "email": p.get("email"), "desde": tabelas.local(p.get("criado_em")), "status": p.get("status")})
    linhas.sort(key=lambda l: (tabelas._norm(l["setor"]), tabelas._norm(l["nome"])))
    if not setores:
        ctx.aviso = "Nenhum setor sob a sua coordenação. Peça à Secretaria ou ao Adm para definir seus setores."
    ctx.resumo = [(len({l['nome'] for l in linhas}), "pessoas"), (len({l['setor'] for l in linhas}), "setores com interessados")]
    cols = [Coluna("setor", "Setor de interesse", "lista"), Coluna("nome", "Nome", "texto", destaque=True),
            Coluna("whatsapp", "WhatsApp", "texto", sensivel=True), Coluna("email", "E-mail", "texto", sensivel=True),
            Coluna("desde", "Marcado em", "data", padrao=False)]
    if ver_status:
        cols.append(Coluna("status", "Situação", "lista"))
    return cols, linhas


# ---------------------------------------------------------------------------
# Relatórios: Pessoas (Secretaria e Adm)
# ---------------------------------------------------------------------------
def r_membros(ctx: Ctx):
    linhas = [l for l in _membros(ctx.c, com_setores=True) if l["status"] != ANONIMIZADO]
    linhas.sort(key=lambda l: tabelas._norm(l["nome_completo"]))
    cont = _contagem(linhas, "status")
    ctx.resumo = [(len(linhas), "membros")] + [(cont.get(s, 0), s) for s in db.STATUS_MEMBRO if s != ANONIMIZADO]
    return colunas_membros(ctx.u["perfil"], ("nome_completo", "bairro", "status", "data_registro")), linhas


def r_pendencias(ctx: Ctx):
    agora = datas.agora_utc()
    vencidas = set()
    for mid, expira in ctx.c.execute(select(db.regularizacoes.c.membro_id, db.regularizacoes.c.expira_em).where(
            db.regularizacoes.c.concluido_em.is_(None), db.regularizacoes.c.revogado.is_(False))):
        if expira and (expira if expira.tzinfo else expira.replace(tzinfo=agora.tzinfo)) < agora:
            vencidas.add(mid)
    linhas = []
    for m in _membros(ctx.c):
        if m["status"] in FORA:
            continue
        pend = []
        if not m.get("cpf"):
            pend.append("Sem CPF")
        if not m["foto"]:
            pend.append("Sem foto")
        if not m["credo_aceito"]:
            pend.append("Credo não assinado")
        if m["status"] == "Aguardando Análise":
            pend.append("Aguardando análise")
        if m["id"] in vencidas:
            pend.append("Regularização vencida")
        for p in pend:
            linhas.append({"id": m["id"], "nome": m["nome_completo"], "pendencia": p, "whatsapp": m["whatsapp"],
                           "email": m["email"], "status": m["status"], "cadastro": m["data_registro"]})
    linhas.sort(key=lambda l: (tabelas._norm(l["nome"]), l["pendencia"]))
    cont = _contagem(linhas, "pendencia")
    ctx.resumo = [(len({l['id'] for l in linhas}), "membros com pendência")] + sorted(
        [(n, p) for p, n in cont.items()], key=lambda x: -x[0])
    link = lambda l: f"/membros/{l['id']}"
    return [Coluna("nome", "Nome", "texto", link=link, destaque=True), Coluna("pendencia", "Pendência", "lista"),
            Coluna("whatsapp", "WhatsApp", "texto", sensivel=True), Coluna("email", "E-mail", "texto", sensivel=True, padrao=False),
            Coluna("status", "Situação", "lista"), Coluna("cadastro", "Cadastro", "data")], linhas


def r_aniversariantes(ctx: Ctx):
    """Coordenação: só os membros dos seus setores (onde serve ou de interesse). Quem recusou a homenagem não entra."""
    from .. import aniversarios as an
    esc = an.escopo(ctx.c, ctx.u)
    linhas = []
    for m in an.membros(ctx.c):
        if not an.visivel(m, esc) or (ctx.mes and m["mes"] != ctx.mes):
            continue
        linhas.append({"id": m["id"], "aniversario": m["nasc"], "nome": m["nome"],
                       "setores": [s["nome"] + (" (interesse)" if s["tipo"] == "interesse" else "") for s in m["setores"]]
                       or [an.SEM_SETOR], "whatsapp": m["whatsapp"]})
    ctx.resumo = [(len(linhas), f"aniversariantes em {datas.MESES[ctx.mes - 1]}" if ctx.mes else "aniversariantes")]
    dia_mes = lambda v: v.strftime("%d/%m") if v else "-"  # LGPD: sem ano de nascimento nem idade
    cols = [Coluna("aniversario", "Aniversário", "aniversario", fmt=dia_mes),
            Coluna("nome", "Nome", "texto", destaque=True, link=lambda l: f"/aniversariantes/{l['id']}/mensagem"),
            Coluna("setores", "Setores", "lista")]
    if esc is None:  # telefone só para Secretaria e Adm; a Coordenação usa o botão de mensagem
        cols.append(Coluna("whatsapp", "WhatsApp", "texto", sensivel=True, padrao=False))
    return cols, linhas


def r_membros_setor(ctx: Ctx):
    m, ms = db.membros.c, db.membro_setores.c
    q = (select(db.departamentos.c.nome.label("setor"), ms.funcao, m.id, m.nome_completo, m.whatsapp, m.status)
         .select_from(db.membro_setores.join(db.departamentos, db.DEP_ID == ms.departamento_id)
                      .join(db.membros, db.membros.c.id == ms.membro_id))
         .where(m.status != ANONIMIZADO))
    linhas = [dict(r) for r in ctx.c.execute(q).mappings()]
    if ctx.setor:
        linhas = [l for l in linhas if l["setor"] == ctx.setor]
    linhas.sort(key=lambda l: (tabelas._norm(l["setor"]), l["funcao"] != "Líder", tabelas._norm(l["nome_completo"])))
    ctx.resumo = [(len({l['id'] for l in linhas}), "pessoas servindo"), (len({l['setor'] for l in linhas}), "setores"),
                  (sum(1 for l in linhas if l["funcao"] == "Líder"), "líderes")]
    return [Coluna("setor", "Setor", "lista"), Coluna("funcao", "Função", "lista"),
            Coluna("nome_completo", "Nome", "texto", link=lambda l: f"/membros/{l['id']}", destaque=True),
            Coluna("whatsapp", "WhatsApp", "texto", sensivel=True, padrao=False), Coluna("status", "Situação", "lista")], linhas


def r_interesses(ctx: Ctx):
    m, mi = db.membros.c, db.membro_interesses.c
    q = (select(mi.setor, mi.criado_em, m.id, m.nome_completo, m.whatsapp, m.email, m.status)
         .join(db.membros, m.id == mi.membro_id).where(m.status != ANONIMIZADO))
    linhas = []
    for r in ctx.c.execute(q).mappings():
        l = dict(r)
        l["criado_em"] = tabelas.local(l["criado_em"])
        linhas.append(l)
    linhas.sort(key=lambda l: (tabelas._norm(l["setor"]), tabelas._norm(l["nome_completo"])))
    cont = _contagem(linhas, "setor")
    ctx.resumo = [(len({l['id'] for l in linhas}), "pessoas")] + sorted([(n, s) for s, n in cont.items()], key=lambda x: -x[0])[:6]
    return [Coluna("setor", "Setor de interesse", "lista"),
            Coluna("nome_completo", "Nome", "texto", link=lambda l: f"/membros/{l['id']}", destaque=True),
            Coluna("status", "Situação", "lista"), Coluna("whatsapp", "WhatsApp", "texto", sensivel=True),
            Coluna("email", "E-mail", "texto", sensivel=True, padrao=False), Coluna("criado_em", "Marcado em", "data", padrao=False)], linhas


def r_batismo(ctx: Ctx):
    linhas = [l for l in _membros(ctx.c) if l["status"] not in FORA]
    linhas.sort(key=lambda l: tabelas._norm(l["nome_completo"]))
    ctx.resumo = [(sum(1 for l in linhas if (l.get("batizado") or "").lower() == "sim"), "batizados"),
                  (sum(1 for l in linhas if (l.get("batizado") or "").lower() != "sim"), "não batizados ou sem informação"),
                  (sum(1 for l in linhas if (l.get("interesse_batismo_familia") or "").lower() == "sim"), "com interesse da família")]
    cols = colunas_membros(ctx.u["perfil"], ())
    usar = {"nome_completo": True, "batizado": True, "whatsapp": False, "status": True}
    sel = [c for c in cols if c.chave in usar]
    for c in sel:
        c.padrao = usar[c.chave]
    return sel + [Coluna("data_batismo", "Data do batismo", "data"),
                  Coluna("interesse_batismo_familia", "Interesse da família", "lista")], linhas


def r_regularizacao(ctx: Ctx):
    r, m = db.regularizacoes.c, db.membros.c
    q = (select(r.id, r.criado_em, r.enviado_em, r.canais, r.concluido_em, r.revogado, r.expira_em, r.desfecho,
                m.id.label("membro_id"), m.nome_completo)
         .join(db.membros, m.id == r.membro_id).where(m.status != ANONIMIZADO, *_no_periodo(r.criado_em, ctx)))
    agora = datas.agora_utc()
    linhas = []
    for x in ctx.c.execute(q).mappings():
        x = dict(x)
        exp = x["expira_em"]
        if exp is not None and exp.tzinfo is None:
            exp = exp.replace(tzinfo=agora.tzinfo)
        sit = ("Concluído" if x["concluido_em"] else "Revogado" if x["revogado"] else
               "Vencido" if exp and exp < agora else "Enviado" if x["enviado_em"] else "Gerado, não enviado")
        linhas.append({"membro_id": x["membro_id"], "nome": x["nome_completo"], "situacao": sit,
                       "gerado": tabelas.local(x["criado_em"]), "enviado": tabelas.local(x["enviado_em"]),
                       "canais": [c.strip() for c in (x["canais"] or "").split(",") if c.strip()],
                       "expira": tabelas.local(x["expira_em"]), "concluido": tabelas.local(x["concluido_em"]),
                       "desfecho": {"em_analise": "Voltou para análise", "inativado": "Inativado"}.get(x["desfecho"], x["desfecho"])})
    linhas.sort(key=lambda l: tabelas._norm(l["nome"]))
    cont = _contagem(linhas, "situacao")
    ctx.resumo = [(len(linhas), "links")] + [(n, s) for s, n in sorted(cont.items())]
    return [Coluna("nome", "Nome", "texto", link=lambda l: f"/regularizacao/membro/{l['membro_id']}", destaque=True),
            Coluna("situacao", "Situação do link", "lista"), Coluna("gerado", "Gerado em", "data"),
            Coluna("enviado", "Enviado em", "data"), Coluna("canais", "Canais", "lista"),
            Coluna("expira", "Vence em", "data"), Coluna("concluido", "Concluído em", "data", padrao=False),
            Coluna("desfecho", "Desfecho", "lista", padrao=False)], linhas


def _faixa(n) -> str:
    i = datas.idade(n)
    if i is None:
        return "(sem data de nascimento)"
    for lim, nome in ((11, "0 a 11 anos"), (17, "12 a 17 anos"), (29, "18 a 29 anos"), (44, "30 a 44 anos"), (59, "45 a 59 anos")):
        if i <= lim:
            return nome
    return "60 anos ou mais"


def r_estatisticas(ctx: Ctx):
    base = [l for l in _membros(ctx.c, com_setores=True) if l["status"] != ANONIMIZADO]
    if ctx.de or ctx.ate:
        base = [l for l in base if l["data_registro"] and (not ctx.de or l["data_registro"] >= ctx.de)
                and (not ctx.ate or l["data_registro"] <= ctx.ate)]
    grupos = [("Situação", lambda l: [l["status"]]), ("Faixa etária", lambda l: [_faixa(l["data_nascimento"])]),
              ("Sexo", lambda l: [l["sexo"] or "(não informado)"]), ("Estado civil", lambda l: [l["estado_civil"] or "(não informado)"]),
              ("Bairro", lambda l: [l["bairro"] or "(não informado)"]), ("Batizado", lambda l: [l["batizado"] or "(não informado)"]),
              ("Setor em que serve", lambda l: l["setores"] or ["(nenhum)"])]
    linhas = []
    for g, fn in grupos:
        cont: dict = {}
        for l in base:
            for v in fn(l):
                cont[v] = cont.get(v, 0) + 1
        for v, n in sorted(cont.items(), key=lambda kv: -kv[1]):
            # LGPD: grupo pequeno identificaria pessoas; aparece só como "menos de 3"
            linhas.append({"grupo": g, "valor": v, "total": n if n >= MINIMO_GRUPO else None,
                           "pct": round(n * 100 / len(base), 1) if n >= MINIMO_GRUPO and base else None})
    ctx.resumo = [(len(base), "membros (sem anonimizados)")]
    pct = lambda v: "-" if v is None else f"{str(v).replace('.', ',').removesuffix(',0')}%"
    return [Coluna("grupo", "Grupo", "lista"), Coluna("valor", "Valor", "texto"),
            Coluna("total", "Total", "numero", fmt=lambda v: "menos de 3" if v is None else str(v)),
            Coluna("pct", "Percentual", "numero", fmt=pct)], linhas


def r_satisfacao(ctx: Ctx):
    nomes = {"bom": "Bom", "regular": "Regular", "ruim": "Ruim", "nao_opinar": "Prefere não opinar"}
    q = select(db.pesquisa_satisfacao.c.resposta).where(*_no_periodo(db.pesquisa_satisfacao.c.respondido_em, ctx))
    respostas = list(ctx.c.execute(q).scalars())
    total = len(respostas)
    linhas = [{"resposta": nomes[k], "total": respostas.count(k),
               "pct": round(respostas.count(k) * 100 / total, 1) if total else 0} for k in nomes]
    ctx.resumo = [(total, "respostas")]
    pct = lambda v: f"{str(v).replace('.', ',').removesuffix(',0')}%"
    return [Coluna("resposta", "Resposta", "lista"), Coluna("total", "Total", "numero"),
            Coluna("pct", "Percentual", "numero", fmt=pct)], linhas


# ---------------------------------------------------------------------------
# Relatórios: Administração (Adm)
# ---------------------------------------------------------------------------
def r_usuarios(ctx: Ctx):
    agora = datas.agora_utc()
    limite = agora - timedelta(days=90)
    linhas = []
    for u in ctx.c.execute(select(db.usuarios)).mappings():
        def utc(v):
            return v if v is None or v.tzinfo else v.replace(tzinfo=agora.tzinfo)
        ult, bloq = utc(u["ultimo_login"]), utc(u["bloqueado_ate"])
        linhas.append({"nome": u["nome"], "email": u["email"], "perfil": db.PERFIS_ROTULO.get(u["perfil"], u["perfil"]),
                       "ativo": bool(u["ativo"]), "bloqueado": bool(bloq and bloq > agora),
                       "ultimo": tabelas.local(ult), "sem_uso": not ult or ult < limite,
                       "ficha": bool(u["membro_id"]), "origem": (u["origem"] or "").split(":")[0] or None,
                       "criado": tabelas.local(u["criado_em"])})
    linhas.sort(key=lambda l: tabelas._norm(l["nome"]))
    cont = _contagem(linhas, "perfil")
    ctx.resumo = [(len(linhas), "logins")] + [(cont.get(p, 0), p) for p in db.PERFIS_ROTULO.values()] + [
        (sum(1 for l in linhas if l["sem_uso"]), "sem acesso há 90 dias")]
    return [Coluna("nome", "Nome", "texto", destaque=True), Coluna("email", "E-mail", "texto"),
            Coluna("perfil", "Perfil", "lista"), Coluna("ativo", "Ativo", "simnao"), Coluna("bloqueado", "Bloqueado", "simnao"),
            Coluna("ultimo", "Último acesso", "data"), Coluna("sem_uso", "Sem uso há 90 dias", "simnao"),
            Coluna("ficha", "Ligado a ficha", "simnao", padrao=False), Coluna("origem", "Origem", "lista", padrao=False),
            Coluna("criado", "Criado em", "data", padrao=False)], linhas


def r_coordenadores(ctx: Ctx):
    nomes: dict[str, list[str]] = {}
    for dep, nome in ctx.c.execute(select(db.usuario_setores.c.departamento_id, db.usuarios.c.nome)
                                   .join(db.usuarios, db.usuarios.c.id == db.usuario_setores.c.usuario_id)
                                   .where(db.usuarios.c.ativo.is_(True))):
        nomes.setdefault(str(dep), []).append(nome)
    linhas = [{"setor": d["nome"], "responsavel": d.get("responsavel"), "coordenadores": sorted(nomes.get(str(d["id"]), [])),
               "qtd": len(nomes.get(str(d["id"]), []))}
              for d in ctx.c.execute(select(db.departamentos).order_by(db.departamentos.c.nome)).mappings()]
    ctx.resumo = [(len(linhas), "setores"), (sum(1 for l in linhas if not l["qtd"]), "sem coordenador")]
    return [Coluna("setor", "Setor", "lista"), Coluna("responsavel", "Responsável", "texto"),
            Coluna("coordenadores", "Coordenadores no sistema", "lista"), Coluna("qtd", "Quantidade", "numero")], linhas


def _auditoria(ctx: Ctx, acoes: tuple | None = None, limite: int = 5000) -> list[dict]:
    a = db.auditoria.c
    q = select(db.auditoria).where(*_no_periodo(a.criado_em, ctx)).order_by(a.criado_em.desc()).limit(limite)
    if acoes:
        q = q.where(a.acao.in_(acoes))
    return [{**dict(r), "quando": tabelas.local(r["criado_em"])} for r in ctx.c.execute(q).mappings()]


def r_auditoria(ctx: Ctx):
    linhas = _auditoria(ctx)
    if len(linhas) >= 5000:
        ctx.aviso = "Mostrando os 5.000 registros mais recentes do período. Diminua o período para ver o restante."
    ctx.resumo = [(len(linhas), "registros"), (len({l['usuario_nome'] for l in linhas}), "usuários")]
    return [Coluna("quando", "Data e hora", "data"), Coluna("usuario_nome", "Usuário", "lista"),
            Coluna("acao", "Ação", "lista"), Coluna("recurso", "Recurso", "texto"),
            Coluna("detalhes", "Detalhes", "texto"), Coluna("ip", "IP", "texto", padrao=False)], linhas


ACOES_EMAIL = {"EMAIL_BOAS_VINDAS": "Boas-vindas", "CONVITE_VOLUNTARIOS": "Convite de voluntários",
               "FALHA_EMAIL": "Falha de envio", "EMAIL_TESTE": "E-mail de teste", "LEMBRETE_FOTO": "Lembrete de foto",
               "REGULARIZACAO_ENVIO": "Link de regularização", "LINK_CREDO_ENVIADO": "Link do Credo"}


def r_emails(ctx: Ctx):
    linhas = [{"quando": l["quando"], "tipo": ACOES_EMAIL[l["acao"]], "destino": l["recurso"], "resultado": l["detalhes"],
               "por": l["usuario_nome"]} for l in _auditoria(ctx, tuple(ACOES_EMAIL))]
    lc, m = db.lembretes_cadastro.c, db.membros.c
    q = (select(lc.etapa, lc.enviado_em, lc.resultado, m.nome_completo).join(db.membros, m.id == lc.membro_id)
         .where(*_no_periodo(lc.enviado_em, ctx)))
    for r in ctx.c.execute(q).mappings():
        linhas.append({"quando": tabelas.local(r["enviado_em"]), "tipo": f"Lembrete de foto ({r['etapa']})",
                       "destino": r["nome_completo"], "resultado": r["resultado"], "por": "Sistema"})
    linhas.sort(key=lambda l: l["quando"] or datetime.min, reverse=True)
    ctx.resumo = [(len(linhas), "envios"), (sum(1 for l in linhas if l["tipo"] == "Falha de envio"
                                                  or "falha" in (l["resultado"] or "").lower()), "falhas")]
    return [Coluna("quando", "Data e hora", "data"), Coluna("tipo", "Tipo", "lista"), Coluna("destino", "Destinatário", "texto"),
            Coluna("resultado", "Resultado", "texto"), Coluna("por", "Enviado por", "lista")], linhas


ACOES_LGPD = {"ANONIMIZACAO_LGPD": "Anonimização", "EXCLUSAO_MEMBRO": "Exclusão de ficha",
              "DOWNLOAD_PDF_TITULAR": "Titular baixou a própria ficha", "VISUALIZACAO_PROPRIA_FICHA": "Titular viu a própria ficha",
              "EXPORTACAO_CSV": "Exportação de planilha", "RELATORIO_PLANILHA": "Exportação de planilha (relatório)",
              "RELATORIO_IMPRESSO": "Impressão de relatório"}


def r_lgpd(ctx: Ctx):
    linhas = [{"quando": l["quando"], "tipo": ACOES_LGPD[l["acao"]], "titular": l["recurso"], "detalhes": l["detalhes"],
               "por": l["usuario_nome"]} for l in _auditoria(ctx, tuple(ACOES_LGPD))]
    m = db.membros.c
    q = select(m.nome_completo, m.lgpd_data_consentimento, m.lgpd_versao_termo).where(
        m.lgpd_consentimento.is_(True), m.status != ANONIMIZADO, *_no_periodo(m.lgpd_data_consentimento, ctx))
    for r in ctx.c.execute(q).mappings():
        linhas.append({"quando": tabelas.local(r["lgpd_data_consentimento"]), "tipo": "Consentimento",
                       "titular": r["nome_completo"], "detalhes": f"Termo {r['lgpd_versao_termo'] or ''}".strip(), "por": "Titular"})
    linhas.sort(key=lambda l: l["quando"] or datetime.min, reverse=True)
    cont = _contagem(linhas, "tipo")
    ctx.resumo = [(len(linhas), "registros")] + [(n, t) for t, n in sorted(cont.items(), key=lambda kv: -kv[1])][:5]
    return [Coluna("quando", "Data e hora", "data"), Coluna("tipo", "Tipo", "lista"), Coluna("titular", "Titular / recurso", "texto"),
            Coluna("detalhes", "Detalhes", "texto"), Coluna("por", "Por", "lista")], linhas


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------
G_MEUS, G_EVENTOS, G_PESSOAS, G_ADM = "Meus dados e agenda", "Eventos", "Pessoas", "Administração"
CATALOGO = [
    Relatorio("agenda", "Agenda do período", "📅", G_MEUS, TODOS, r_agenda, ("periodo", "setor"), dados_pessoais=False,
              descricao="Eventos com data, local, setor e vagas. Bom para imprimir e fixar no mural."),
    Relatorio("minhas-inscricoes", "Minhas inscrições", "🎟️", G_MEUS, TODOS, r_minhas_inscricoes, ("periodo",),
              descricao="Eventos em que você se inscreveu, com ingresso e situação do pagamento."),
    Relatorio("extrato", "Extrato dos meus pagamentos", "🧾", G_MEUS, TODOS, r_extrato, ("periodo",),
              descricao="Valores pagos e pendentes no período."),
    Relatorio("participantes", "Participantes / lista de presença", "📝", G_EVENTOS, GESTAO, r_participantes,
              ("periodo", "setor", "evento"), assinatura=True,
              descricao="Nome, ingresso e situação de cada inscrito, com coluna de assinatura para a chamada."),
    Relatorio("a-receber", "A receber", "💰", G_EVENTOS, GESTAO, r_a_receber, ("periodo", "setor", "evento"),
              descricao="Inscrições com pagamento pendente, com telefone para contato."),
    Relatorio("financeiro", "Financeiro consolidado", "📊", G_EVENTOS, GESTAO, r_financeiro, ("periodo", "setor", "evento"),
              dados_pessoais=False, descricao="Receita, despesas e resultado de cada evento e do período."),
    Relatorio("ocupacao", "Ocupação de vagas", "🎫", G_EVENTOS, GESTAO, r_ocupacao, ("periodo", "setor"), dados_pessoais=False,
              descricao="Inscritos x limite de vagas de cada evento."),
    Relatorio("voluntarios", "Voluntários interessados", "🙋", G_EVENTOS, GESTAO, r_voluntarios, (), periodo_padrao=False,
              descricao="Quem marcou na ficha que deseja servir nos seus setores."),
    Relatorio("membros", "Membros por situação", "👥", G_PESSOAS, SEC_ADM, r_membros, (), periodo_padrao=False,
              descricao="Lista de membros com as colunas que você escolher e total por situação."),
    Relatorio("pendencias", "Pendências de cadastro", "⚠️", G_PESSOAS, SEC_ADM, r_pendencias, (), periodo_padrao=False,
              descricao="Quem precisa de contato e qual é a pendência."),
    Relatorio("aniversariantes", "Aniversariantes", "🎂", G_PESSOAS, db.PERFIS_AGENDA, r_aniversariantes, ("mes",),
              periodo_padrao=False, descricao="Nome e dia/mês do aniversário, sem ano nem idade. A Coordenação vê só os seus "
                                               "setores. Calendário completo em 🎂 Aniversariantes."),
    Relatorio("membros-setor", "Membros por setor de serviço", "🛠️", G_PESSOAS, SEC_ADM, r_membros_setor, ("setor",),
              periodo_padrao=False, descricao="Quem serve em cada setor e em qual função."),
    Relatorio("interesses", "Setores de interesse", "💡", G_PESSOAS, SEC_ADM, r_interesses, (), periodo_padrao=False,
              descricao="Total e lista de interessados em servir, por setor."),
    Relatorio("batismo", "Batismo", "💧", G_PESSOAS, SEC_ADM, r_batismo, (), periodo_padrao=False,
              descricao="Batizados, data do batismo e interesse da família."),
    Relatorio("regularizacao", "Regularização", "📋", G_PESSOAS, SEC_ADM, r_regularizacao, ("periodo",), periodo_padrao=False,
              descricao="Andamento dos links de atualização das fichas antigas."),
    Relatorio("estatisticas", "Estatísticas da igreja", "📈", G_PESSOAS, SEC_ADM, r_estatisticas, ("periodo",),
              periodo_padrao=False, dados_pessoais=False,
              descricao="Só números: situação, faixa etária, sexo, bairro, estado civil. O período filtra pela data de cadastro."),
    Relatorio("satisfacao", "Pesquisa de satisfação", "😊", G_PESSOAS, SEC_ADM, r_satisfacao, ("periodo",), periodo_padrao=False,
              dados_pessoais=False, descricao="Respostas da pesquisa enviada no e-mail de boas-vindas."),
    Relatorio("usuarios", "Usuários e perfis", "🔐", G_ADM, ("admin",), r_usuarios, (), periodo_padrao=False,
              descricao="Logins, perfil, último acesso e contas sem uso."),
    Relatorio("coordenadores", "Coordenadores por setor", "🧭", G_ADM, ("admin",), r_coordenadores, (), periodo_padrao=False,
              descricao="Quem coordena cada setor e setores sem coordenador."),
    Relatorio("auditoria", "Auditoria", "🔍", G_ADM, ("admin",), r_auditoria, ("periodo",),
              descricao="Quem fez o quê e quando, inclusive emissões de relatórios e exportações."),
    Relatorio("emails", "E-mails e lembretes", "✉️", G_ADM, ("admin",), r_emails, ("periodo",),
              descricao="Envios feitos pelo sistema e falhas."),
    Relatorio("lgpd", "LGPD", "🛡️", G_ADM, ("admin",), r_lgpd, ("periodo",),
              descricao="Consentimentos, anonimizações, exclusões, exportações e impressões."),
]
POR_CHAVE = {r.chave: r for r in CATALOGO}


def catalogo_de(usuario: dict) -> list[tuple[str, list[Relatorio]]]:
    grupos: dict[str, list] = {}
    for r in CATALOGO:
        if usuario["perfil"] in r.perfis:
            grupos.setdefault(r.grupo, []).append(r)
    return list(grupos.items())


def _salvos(c, usuario: dict) -> list[dict]:
    t = db.relatorios_salvos.c
    return [dict(r) for r in c.execute(select(db.relatorios_salvos).where(t.usuario_id == usuario["id"])
                                       .order_by(t.nome)).mappings() if r["relatorio"] in POR_CHAVE]


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------
@seguranca.exigir()
async def central(request: Request):
    u = seguranca.usuario_atual(request)
    chave = request.path_params.get("chave") or "agenda"
    rel = POR_CHAVE.get(chave)
    if not rel or u["perfil"] not in rel.perfis:
        return render(request, "erro.html", {"titulo": "Acesso restrito",
                      "mensagem": "Este relatório não está disponível para o seu perfil."}, 403)
    p = request.query_params
    formato = p.get("formato")
    if formato == "csv" and u["perfil"] not in EXPORTAM:
        return render(request, "erro.html", {"titulo": "Acesso restrito",
                      "mensagem": "A planilha é exclusiva da Secretaria e do Adm."}, 403)
    caminho = f"/relatorios/{rel.chave}"
    with db.engine().connect() as c:
        ctx = Ctx(c, u, escopo_setores(c, u), p)
        hoje = datas.hoje()
        if "periodo" in rel.filtros:
            ctx.de, ctx.ate = datas.parse_data(p.get("de")), datas.parse_data(p.get("ate"))
            if not ctx.de and not ctx.ate and rel.periodo_padrao and "de" not in p:
                ctx.de, ctx.ate = hoje.replace(day=1), _fim_mes(hoje)
            if ctx.de and ctx.ate and ctx.de > ctx.ate:
                ctx.de, ctx.ate = ctx.ate, ctx.de
        setores = []
        if "setor" in rel.filtros:
            setores = [d["nome"] for d in _deptos_permitidos(c, ctx.escopo if rel.grupo != G_MEUS else None)]
            ctx.setor = p.get("setor") if p.get("setor") in setores else ""
        eventos_opcoes = []
        if "evento" in rel.filtros:
            ctx_ev = Ctx(c, u, ctx.escopo, p, ctx.de, ctx.ate, ctx.setor)
            eventos_opcoes = _eventos(ctx_ev)
            ctx.evento = p.get("evento") if p.get("evento") in {str(e["id"]) for e in eventos_opcoes} else ""
        if "mes" in rel.filtros:
            m = p.get("mes", "")
            ctx.mes = int(m) if m.isdigit() and 1 <= int(m) <= 12 else (0 if "mes" in p else hoje.month)
        colunas, linhas = rel.fn(ctx)
        estado = tabelas.ler_estado(p, colunas)
        t = tabelas.montar(caminho, linhas, colunas, estado, tudo=bool(p.get("tudo")) or formato == "csv")
        salvos = _salvos(c, u)

    filtros_texto = []
    if ctx.de or ctx.ate:
        filtros_texto.append("Período: " + (f"{datas.fmt_data(ctx.de)} a {datas.fmt_data(ctx.ate)}" if ctx.de and ctx.ate
                                            else f"desde {datas.fmt_data(ctx.de)}" if ctx.de else f"até {datas.fmt_data(ctx.ate)}"))
    elif "periodo" in rel.filtros:
        filtros_texto.append("Período: todo o histórico")
    if ctx.setor:
        filtros_texto.append(f"Setor: {ctx.setor}")
    elif ctx.escopo is not None and rel.grupo == G_EVENTOS:
        filtros_texto.append("Setores: " + (", ".join(sorted(ctx.escopo)) or "nenhum atribuído"))
    if ctx.evento:
        ev = next((e for e in eventos_opcoes if str(e["id"]) == ctx.evento), None)
        if ev:
            filtros_texto.append(f"Evento: {ev['titulo']}")
    if "mes" in rel.filtros:
        filtros_texto.append(f"Mês: {datas.MESES[ctx.mes - 1]}" if ctx.mes else "Mês: todos")
    filtros_texto += t["filtros_texto"]
    resumo_filtros = " · ".join(filtros_texto) or "Nenhum"

    if formato == "csv":
        auditar(request, "RELATORIO_PLANILHA", rel.titulo, f"{t['total']} linhas · {resumo_filtros}")
        nome = f"{rel.chave}_{hoje.strftime('%d-%m-%Y')}.csv"
        return Response(tabelas.csv_de(t), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{nome}"', "Cache-Control": "no-store"})
    auditar(request, "RELATORIO_EMITIDO", rel.titulo, f"{t['total']} linhas · {resumo_filtros}")
    return render(request, "relatorios/central.html", {
        "rel": rel, "catalogo": catalogo_de(u), "t": t, "ctx": ctx, "setores": setores, "eventos_opcoes": eventos_opcoes,
        "atalhos": _atalhos(caminho, p) if "periodo" in rel.filtros else [], "resumo": ctx.resumo, "aviso": ctx.aviso,
        "filtros_texto": resumo_filtros, "emitido": datas.agora(), "salvos": salvos,
        "query_atual": urlencode([(k, v) for k, v in p.multi_items() if k not in ("tudo", "imprimir", "formato")]),
        "pode_csv": u["perfil"] in EXPORTAM, "MESES": datas.MESES})


@seguranca.exigir()
async def impressao(request: Request):
    """Registro da impressão (chamado pelo navegador no momento de imprimir)."""
    if not await seguranca.conferir_csrf(request):
        return JSONResponse({"ok": False}, status_code=403)
    form = await request.form()
    rel = POR_CHAVE.get(form.get("relatorio") or "")
    u = seguranca.usuario_atual(request)
    if not rel or u["perfil"] not in rel.perfis:
        return JSONResponse({"ok": False}, status_code=403)
    auditar(request, "RELATORIO_IMPRESSO", rel.titulo, f"{form.get('linhas', '0')} linhas · {(form.get('filtros') or '')[:1500]}")
    return JSONResponse({"ok": True})


@seguranca.exigir()
async def salvar(request: Request):
    u = seguranca.usuario_atual(request)
    if not await seguranca.conferir_csrf(request):
        flash(request, "A página expirou. Tente de novo.", "erro")
        return ir("/relatorios")
    form = await request.form()
    rel = POR_CHAVE.get(form.get("relatorio") or "")
    if not rel or u["perfil"] not in rel.perfis:
        return ir("/relatorios")
    nome = (form.get("nome") or "").strip()[:80] or rel.titulo
    consulta = (form.get("consulta") or "")[:1800]
    with db.engine().begin() as c:
        if len(_salvos(c, u)) >= 30:
            flash(request, "Limite de 30 filtros salvos. Exclua algum para salvar outro.", "erro")
            return ir(f"/relatorios/{rel.chave}?{consulta}")
        c.execute(insert(db.relatorios_salvos).values(usuario_id=u["id"], nome=nome, relatorio=rel.chave,
                                                      consulta=consulta, criado_em=datas.agora_utc()))
    flash(request, f"Filtro \"{nome}\" salvo em ⭐ Meus filtros.")
    return ir(f"/relatorios/{rel.chave}?{consulta}")


@seguranca.exigir()
async def excluir_salvo(request: Request):
    u = seguranca.usuario_atual(request)
    if not await seguranca.conferir_csrf(request):
        flash(request, "A página expirou. Tente de novo.", "erro")
        return ir("/relatorios")
    with db.engine().begin() as c:
        c.execute(delete(db.relatorios_salvos).where(db.relatorios_salvos.c.id == request.path_params["id"],
                                                     db.relatorios_salvos.c.usuario_id == u["id"]))
    flash(request, "Filtro excluído.")
    return ir(request.headers.get("referer") or "/relatorios")


@seguranca.exigir(*GESTAO)
async def periodo_antigo(request: Request):
    """Endereço da versão anterior: leva para a Agenda do período com as mesmas datas."""
    q = urlencode([(k, v) for k, v in request.query_params.multi_items() if k in ("de", "ate")])
    return ir("/relatorios/agenda" + (f"?{q}" if q else ""))


rotas = [
    Route("/relatorios", central),
    Route("/relatorios/periodo", periodo_antigo),
    Route("/relatorios/impressao", impressao, methods=["POST"]),
    Route("/relatorios/salvar", salvar, methods=["POST"]),
    Route("/relatorios/salvos/{id:int}/excluir", excluir_salvo, methods=["POST"]),
    Route("/relatorios/{chave}", central),
]
