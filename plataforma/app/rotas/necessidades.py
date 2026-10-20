"""Pesquisa mensal de necessidades (v2.11.0).

Uma vez por mês cada pessoa com login conta em que áreas precisa de apoio. As respostas são anônimas:
a tabela de respostas não guarda quem respondeu (só o mês e a faixa etária), e a tabela de controle guarda
só "fulano já respondeu em tal mês", sem ligação com a resposta. Quem marca "Quero que alguém me procure"
abre mão do anonimato nessa resposta, e o nome vai para a Secretaria.

Painel: a liderança (Coordenação, Secretaria, Adm) vê os números; comentários e pedidos de contato são
só da Secretaria e do Adm. Faixas etárias com menos de 5 respostas não aparecem, para ninguém ser identificado.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, insert, select
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request
from starlette.routing import Route

from .. import datas, db, seguranca
from ..web import flash, ir, render

CATEGORIAS = [
    ("saude", "🩺", "Saúde"),
    ("aconselhamento", "🤝", "Aconselhamento"),
    ("casamento", "💍", "Casamento"),
    ("familia", "👨‍👩‍👧", "Família e filhos"),
    ("financas", "💰", "Finanças"),
    ("emprego", "💼", "Emprego e trabalho"),
    ("luto", "🕊️", "Luto"),
    ("espiritual", "📖", "Vida espiritual"),
    ("outro", "✳️", "Outro"),
]
ROTULO = {k: r for k, _, r in CATEGORIAS}
INTENSIDADES = [(1, "Pouca"), (2, "Média"), (3, "Muita")]
MINIMO_GRUPO = 5  # grupos menores não aparecem no painel
GESTAO = ("coordenacao", "secretaria", "admin")
SEC_ADM = ("secretaria", "admin")
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
         "novembro", "dezembro"]


def mes_atual(d: date | None = None) -> str:
    d = d or datas.hoje()
    return f"{d.year:04d}-{d.month:02d}"


def nome_mes(mes: str) -> str:
    a, m = mes.split("-")
    return f"{MESES[int(m) - 1]} de {a}"


def ja_respondeu(c, usuario_id: int, mes: str | None = None) -> bool:
    n = db.necessidades_controle.c
    return c.execute(select(func.count()).select_from(db.necessidades_controle)
                     .where(n.mes == (mes or mes_atual()), n.usuario_id == usuario_id)).scalar() > 0


def faixa(nasc) -> str:
    i = datas.idade(nasc) if nasc else None
    if i is None:
        return "Não informada"
    for lim, nome in ((17, "Até 17 anos"), (29, "18 a 29 anos"), (44, "30 a 44 anos"), (59, "45 a 59 anos")):
        if i <= lim:
            return nome
    return "60 anos ou mais"


@seguranca.exigir()
async def pesquisa(request: Request):
    u = seguranca.usuario_atual(request)
    mes = mes_atual()
    with db.engine().connect() as c:
        respondida = ja_respondeu(c, u["id"], mes)
    if request.method == "GET" or respondida:
        return render(request, "necessidades/pesquisa.html", {"CATEGORIAS": CATEGORIAS, "INTENSIDADES": INTENSIDADES,
                                                              "respondida": respondida, "mes": nome_mes(mes), "erro": None})
    form = await request.form()
    escolhas = []
    for k, _, _ in CATEGORIAS:
        if form.get(f"cat_{k}"):
            try:
                inten = int(form.get(f"int_{k}") or 2)
            except ValueError:
                inten = 2
            escolhas.append((k, min(3, max(1, inten))))
    comentario = (form.get("comentario") or "").strip()[:1000] or None
    nenhuma = form.get("nenhuma") == "sim"
    if not escolhas and not nenhuma:
        return render(request, "necessidades/pesquisa.html", {
            "CATEGORIAS": CATEGORIAS, "INTENSIDADES": INTENSIDADES, "respondida": False, "mes": nome_mes(mes),
            "erro": "Marque ao menos uma área ou \"Neste mês estou bem\"."}, status_code=400)
    contato = form.get("quer_contato") == "sim"
    try:
        with db.engine().begin() as c:
            c.execute(insert(db.necessidades_controle).values(mes=mes, usuario_id=u["id"]))
            nasc = None
            if u.get("membro_id"):
                nasc = c.execute(select(db.membros.c.data_nascimento).where(db.membros.c.id == u["membro_id"])).scalar()
            rid = c.execute(insert(db.necessidades_respostas).values(
                mes=mes, faixa=faixa(nasc), comentario=comentario, nenhuma=nenhuma and not escolhas,
                contato_usuario_id=u["id"] if contato else None)).inserted_primary_key[0]
            for k, inten in escolhas:
                c.execute(insert(db.necessidades_itens).values(resposta_id=rid, categoria=k, intensidade=inten))
    except IntegrityError:
        pass  # já respondeu (clique duplo): fica a primeira resposta
    flash(request, "Obrigado! Sua resposta ajuda a liderança a cuidar melhor da igreja.")
    return ir("/inicio")


def _resumo(c, mes: str) -> dict:
    r, i = db.necessidades_respostas.c, db.necessidades_itens.c
    total = c.execute(select(func.count()).select_from(db.necessidades_respostas).where(r.mes == mes)).scalar() or 0
    bem = c.execute(select(func.count()).select_from(db.necessidades_respostas)
                    .where(r.mes == mes, r.nenhuma.is_(True))).scalar() or 0
    linhas = c.execute(select(i.categoria, func.count(), func.avg(i.intensidade))
                       .select_from(db.necessidades_itens.join(db.necessidades_respostas, r.id == i.resposta_id))
                       .where(r.mes == mes).group_by(i.categoria)).all()
    ranking = sorted(({"chave": k, "rotulo": ROTULO.get(k, k), "n": n, "pct": round(n * 100 / total) if total else 0,
                       "media": round(float(m or 0), 1)} for k, n, m in linhas), key=lambda x: (-x["n"], -x["media"]))
    return {"total": total, "bem": bem, "ranking": ranking}


@seguranca.exigir(*GESTAO)
async def painel(request: Request):
    u = seguranca.usuario_atual(request)
    r, i = db.necessidades_respostas.c, db.necessidades_itens.c
    with db.engine().connect() as c:
        meses = [m for (m,) in c.execute(select(r.mes).distinct().order_by(r.mes.desc()))]
        atual = mes_atual()
        if atual not in meses:
            meses.insert(0, atual)
        mes = request.query_params.get("mes") or meses[0]
        if mes not in meses:
            mes = meses[0]
        resumo = _resumo(c, mes)
        # Evolução: últimos 6 meses com resposta, % de quem marcou cada área
        ultimos = sorted(meses[:6])
        evolucao = {}
        for m in ultimos:
            res = _resumo(c, m)
            evolucao[m] = {x["chave"]: x["pct"] for x in res["ranking"]} | {"_total": res["total"]}
        # Por faixa etária (só faixas com respostas suficientes)
        por_faixa = []
        totais_faixa = dict(c.execute(select(r.faixa, func.count()).where(r.mes == mes).group_by(r.faixa)).all())
        for nome_faixa, n in sorted(totais_faixa.items()):
            if n < MINIMO_GRUPO:
                continue
            top = c.execute(select(i.categoria, func.count())
                            .select_from(db.necessidades_itens.join(db.necessidades_respostas, r.id == i.resposta_id))
                            .where(r.mes == mes, r.faixa == nome_faixa).group_by(i.categoria)
                            .order_by(func.count().desc()).limit(3)).all()
            por_faixa.append({"faixa": nome_faixa, "n": n, "top": [(ROTULO.get(k, k), round(q * 100 / n)) for k, q in top]})
        ocultas = sum(1 for n in totais_faixa.values() if n < MINIMO_GRUPO)
        comentarios, contatos = [], []
        if u["perfil"] in SEC_ADM:
            comentarios = [x for (x,) in c.execute(select(r.comentario).where(r.mes == mes, r.comentario.isnot(None))
                                                    .order_by(r.id))]
            uu = db.usuarios.c
            for rid, nome, email in c.execute(select(r.id, uu.nome, uu.email)
                                              .join(db.usuarios, uu.id == r.contato_usuario_id)
                                              .where(r.mes == mes).order_by(uu.nome)):
                areas = [ROTULO.get(k, k) for (k,) in c.execute(select(i.categoria).where(i.resposta_id == rid))]
                contatos.append({"nome": nome, "email": email, "areas": areas})
    return render(request, "necessidades/painel.html", {
        "mes": mes, "nome_mes": nome_mes(mes), "meses": [(m, nome_mes(m)) for m in meses], "resumo": resumo,
        "evolucao": evolucao, "ultimos": ultimos, "CATEGORIAS": CATEGORIAS, "por_faixa": por_faixa, "ocultas": ocultas,
        "comentarios": comentarios, "contatos": contatos, "ve_detalhes": u["perfil"] in SEC_ADM,
        "MINIMO_GRUPO": MINIMO_GRUPO, "nome_mes_curto": lambda m: nome_mes(m)[:3] + "/" + m[2:4]})


rotas = [
    Route("/necessidades", pesquisa, methods=["GET", "POST"]),
    Route("/necessidades/painel", painel),
]
