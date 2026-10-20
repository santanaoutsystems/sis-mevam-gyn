"""Aniversariantes (v2.8.0): calendário, avisos do sino, mensagem especial no dia e modelos de mensagem.

Coordenação: só os membros dos seus setores (onde servem ou de interesse). Secretaria e Adm: todos.
Nunca mostra ano de nascimento nem idade (LGPD).
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from sqlalchemy import func, insert, select, update
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .. import aniversarios as an
from .. import datas, db, envios, ficha, profissional, seguranca
from ..web import auditar, flash, ir, render

GESTAO = db.PERFIS_AGENDA
SEC_ADM = ("secretaria", "admin")
VISOES = ("mes", "semana", "lista")


def _data(valor) -> date | None:
    try:
        return date.fromisoformat(valor) if valor else None
    except ValueError:
        return None


def _membro_visivel(c, u, mid) -> dict | None:
    lista = an.membros(c, [mid])
    if not lista or not an.visivel(lista[0], an.escopo(c, u)):
        return None
    return lista[0]


def _negado(request: Request):
    return render(request, "erro.html", {"titulo": "Indisponível",
                  "mensagem": "Este aniversariante não está nos seus ministérios, recusou a homenagem ou não está mais ativo."}, 404)


@seguranca.exigir(*GESTAO)
async def calendario(request: Request):
    u = seguranca.usuario_atual(request)
    p = request.query_params
    hoje = datas.hoje()
    visao = p.get("visao") if p.get("visao") in VISOES else "mes"
    ref = _data(p.get("dia"))
    if not ref:
        try:
            ref = date(int(p.get("ano")), int(p.get("mes")), 1)
        except (TypeError, ValueError):
            ref = hoje
    setor = (p.get("setor") or "").strip()

    if visao == "semana":
        inicio = ref - timedelta(days=(ref.weekday() + 1) % 7)  # semana de domingo a sábado
        semanas = [[inicio + timedelta(days=i) for i in range(7)]]
        de, ate = inicio, inicio + timedelta(days=6)
        titulo = f"Semana de {de.strftime('%d/%m')} a {ate.strftime('%d/%m/%Y')}"
        anterior, proxima = (inicio - timedelta(days=7)).isoformat(), (inicio + timedelta(days=7)).isoformat()
    else:
        semanas = calendar.Calendar(firstweekday=6).monthdatescalendar(ref.year, ref.month)
        de, ate = date(ref.year, ref.month, 1), date(ref.year, ref.month, calendar.monthrange(ref.year, ref.month)[1])
        titulo = f"{datas.MESES[ref.month - 1]} {ref.year}"
        anterior = (de - timedelta(days=1)).replace(day=1).isoformat()
        proxima = (ate + timedelta(days=1)).isoformat()
    grade_de, grade_ate = semanas[0][0], semanas[-1][-1]

    with db.engine().begin() as c:
        esc = an.escopo(c, u)
        todos = [m for m in an.membros(c) if an.visivel(m, esc)]
        if esc is None:
            opcoes = sorted({k for m in todos for k in m["chaves"]} | set(ficha.NOMES_SETORES), key=str.lower) + [an.SEM_SETOR]
        else:
            opcoes = sorted(esc, key=str.lower)
        if setor == an.SEM_SETOR:
            lista = [m for m in todos if not m["chaves"]]
        elif setor:
            lista = [m for m in todos if setor in m["chaves"]]
        else:
            lista = todos
        dias = an.por_dia(lista, min(grade_de, de), max(grade_ate, ate))
        proximos = sorted(an.por_dia(lista, hoje, hoje + timedelta(days=6)).items())
        ids = {m["id"] for d in dias.values() for m in d} | {m["id"] for _, d in proximos for m in d}
        env = an.enviados(c, ids, {grade_de.year, grade_ate.year, hoje.year, (hoje + timedelta(days=6)).year})
        sem_data = None
        if esc is None:
            sem_data = c.execute(select(func.count()).select_from(db.membros).where(
                db.membros.c.data_nascimento.is_(None), db.membros.c.status.notin_(an.FORA))).scalar()
        an.marcar_lidos(c, u["id"])  # abriu o calendário: os avisos do sino contam como vistos
        email_avisos = c.execute(select(db.usuarios.c.email_avisos).where(db.usuarios.c.id == u["id"])).scalar()

    lista_mes = [(d, dias[d]) for d in sorted(dias) if de <= d <= ate]
    return render(request, "aniversarios/calendario.html", {
        "visao": visao, "ref": ref, "semanas": semanas, "dias": dias, "de": de, "ate": ate, "hoje": hoje,
        "titulo": titulo, "anterior": anterior, "proxima": proxima, "setor": setor, "opcoes": opcoes,
        "proximos": proximos, "env": env, "sem_data": sem_data, "lista_mes": lista_mes, "email_avisos": email_avisos,
        "total": sum(len(v) for _, v in lista_mes), "escopo": esc,
        "DIAS_CURTOS": ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"], "CANAIS": an.CANAIS,
        "filtros_texto": f"{titulo} · Ministério: {setor or 'todos'}",
    })


@seguranca.exigir(*GESTAO)
async def avisos(request: Request):
    u = seguranca.usuario_atual(request)
    hoje = datas.hoje()
    an.garantir(hoje)
    with db.engine().begin() as c:
        lista = an.avisos_do_usuario(c, u["id"], hoje)
        dados = {m["id"]: m for m in an.membros(c, {a["membro_id"] for a in lista}, so_aniversario=False)}
        an.marcar_lidos(c, u["id"])
    itens = [{**a, "m": dados[a["membro_id"]]} for a in lista if a["membro_id"] in dados]
    for i in itens:  # Dia do Profissional: mensagem pronta para o WhatsApp
        if i["tipo"] == an.PROFISSIONAL:
            nome_data = profissional.nome_da_data(i["m"]["dia_profissional"], i["m"]["profissao"] or "")
            i["nome_data"] = nome_data
            i["zap"] = an.link_whatsapp(i["m"]["whatsapp"], profissional.mensagem(i["m"]["primeiro"], nome_data, _remetente(u)))
    return render(request, "aniversarios/avisos.html", {"itens": itens, "hoje": hoje})


def _remetente(u: dict) -> str:
    return an.primeiro_nome(u["nome"])


def _setor_do_remetente(u: dict, m: dict, esc) -> str:
    if esc:  # Coordenação: o setor dela que liga ao aniversariante
        comuns = sorted(m["chaves"] & esc)
        if comuns:
            return comuns[0]
    if u["perfil"] == "secretaria":
        return "Secretaria"
    return ""


@seguranca.exigir(*GESTAO)
async def mensagem(request: Request):
    u = seguranca.usuario_atual(request)
    mid = request.path_params["id"]
    hoje = datas.hoje()
    with db.engine().connect() as c:
        m = _membro_visivel(c, u, mid)
        if not m:
            return _negado(request)
        esc = an.escopo(c, u)
        mods = an.modelos(c)
        escolhido = request.query_params.get("modelo")
        mod = next((x for x in mods if str(x["id"]) == escolhido), None) or an.modelo_padrao(c)
        ano = an.ano_da_homenagem(m["nasc"], hoje)
        ja = an.enviados(c, [mid], [ano]).get((mid, ano), [])
    quando = an.no_ano(m["nasc"], ano)
    faltam = (quando - hoje).days
    texto = an.preencher(mod["texto"], m, _remetente(u), _setor_do_remetente(u, m, esc))
    return render(request, "aniversarios/mensagem.html", {
        "m": m, "mods": mods, "mod": mod, "texto": texto, "quando": quando, "faltam": faltam, "ja": ja,
        "tem_whatsapp": bool(envios.numero_whatsapp(m["whatsapp"])), "tem_email": bool(m["email"]),
        "email_ok": envios.email_configurado(), "link_wa": an.link_whatsapp(m["whatsapp"], texto),
        "numero_wa": envios.numero_whatsapp(m["whatsapp"]), "CANAIS": an.CANAIS,
        "setores": an.rotulo_setores(m)})


@seguranca.exigir(*GESTAO)
async def registrar(request: Request):
    """Chamado pelo navegador ao tocar em WhatsApp ou Copiar: marca ✔ e grava na Auditoria."""
    u = seguranca.usuario_atual(request)
    mid = request.path_params["id"]
    form = await request.form()
    canal = form.get("canal")
    if canal not in ("whatsapp", "copia"):
        return JSONResponse({"ok": False}, status_code=400)
    with db.engine().begin() as c:
        m = _membro_visivel(c, u, mid)
        if not m:
            return JSONResponse({"ok": False}, status_code=404)
        an.registrar(c, mid, an.ano_da_homenagem(m["nasc"]), canal, u)
        auditar(request, "ANIVERSARIO_MENSAGEM", f"Membro #{mid}", f"Canal: {an.CANAIS[canal]}", conexao=c)
    return JSONResponse({"ok": True})


@seguranca.exigir(*GESTAO)
async def enviar_email(request: Request):
    u = seguranca.usuario_atual(request)
    mid = request.path_params["id"]
    form = await request.form()
    texto = (form.get("texto") or "").strip()[:2000]
    with db.engine().connect() as c:
        m = _membro_visivel(c, u, mid)
    if not m:
        return _negado(request)
    if not texto or not m["email"] or not envios.email_configurado():
        flash(request, "Não foi possível enviar: falta o texto, o e-mail do membro ou o envio de e-mail do sistema.", "erro")
        return ir(f"/aniversariantes/{mid}/mensagem")
    erro = envios.enviar_email(m["email"], f"🎂 Feliz aniversário, {m['primeiro']}!", texto)
    with db.engine().begin() as c:
        an.registrar(c, mid, an.ano_da_homenagem(m["nasc"]), "email", u,
                     "enviado" if erro is None else f"falha: {erro}"[:300])
        auditar(request, "ANIVERSARIO_MENSAGEM" if erro is None else "FALHA_ANIVERSARIO_MENSAGEM", f"Membro #{mid}",
                "Canal: E-mail" + (f": {erro}" if erro else ""), conexao=c)
    if erro:
        flash(request, f"O e-mail não saiu: {erro}", "erro")
        return ir(f"/aniversariantes/{mid}/mensagem")
    flash(request, f"Mensagem enviada por e-mail para {m['primeiro']}. 🎉")
    return ir(f"/aniversariantes?dia={an.no_ano(m['nasc'], an.ano_da_homenagem(m['nasc'])).isoformat()}")


@seguranca.exigir(*GESTAO)
async def resumo_email(request: Request):
    u = seguranca.usuario_atual(request)
    form = await request.form()
    ligar = form.get("ligar") == "1"
    with db.engine().begin() as c:
        c.execute(update(db.usuarios).where(db.usuarios.c.id == u["id"]).values(email_avisos=ligar))
        auditar(request, "PREFERENCIA_AVISOS", f"Usuário #{u['id']}",
                "Resumo de aniversariantes por e-mail " + ("ligado" if ligar else "desligado"), conexao=c)
    flash(request, "Você vai receber o resumo das 8h por e-mail." if ligar else "Resumo por e-mail desligado. Os avisos continuam no sino.")
    return ir("/aniversariantes")


@seguranca.exigir(*SEC_ADM)
async def modelos(request: Request):
    with db.engine().connect() as c:
        lista = an.modelos(c, so_ativos=False)
    editar = next((x for x in lista if str(x["id"]) == request.query_params.get("editar")), None)
    return render(request, "aniversarios/modelos.html", {"lista": lista, "editar": editar, "CAMPOS": an.CAMPOS,
                                                         "padrao_embutido": lista and lista[0]["id"] == 0})


@seguranca.exigir(*SEC_ADM)
async def salvar_modelo(request: Request):
    u = seguranca.usuario_atual(request)
    form = await request.form()
    titulo = (form.get("titulo") or "").strip()[:80]
    texto = (form.get("texto") or "").strip()[:1500]
    if not titulo or not texto:
        flash(request, "Informe o nome e o texto do modelo.", "erro")
        return ir("/aniversariantes/modelos")
    ativo, padrao = form.get("ativo") == "1", form.get("padrao") == "1"
    try:
        mid = int(form.get("id") or 0)
    except ValueError:
        mid = 0
    valores = {"titulo": titulo, "texto": texto, "ativo": ativo or padrao, "padrao": padrao,
               "criado_por": u["nome"], "atualizado_em": datas.agora_utc()}
    with db.engine().begin() as c:
        t = db.mensagens_modelo
        if mid and c.execute(select(t.c.id).where(t.c.id == mid)).first():
            c.execute(update(t).where(t.c.id == mid).values(**valores))
        else:
            mid = c.execute(insert(t).values(tipo="aniversario", **valores)).inserted_primary_key[0]
        if padrao:  # só um modelo padrão (o do e-mail automático do Ministério)
            c.execute(update(t).where(t.c.id != mid, t.c.padrao.is_(True)).values(padrao=False))
        elif not c.execute(select(t.c.id).where(t.c.padrao.is_(True), t.c.ativo.is_(True))).first():
            c.execute(update(t).where(t.c.id == mid).values(padrao=True, ativo=True))
        auditar(request, "MODELO_ANIVERSARIO_SALVO", f"Modelo #{mid}", titulo, conexao=c)
    flash(request, "Modelo salvo.")
    return ir("/aniversariantes/modelos")


@seguranca.exigir()
async def minha_homenagem(request: Request):
    """O próprio membro liga ou desliga a homenagem de aniversário (LGPD)."""
    u = seguranca.usuario_atual(request)
    if not u["membro_id"]:
        return ir("/minha-ficha")
    form = await request.form()
    quer = form.get("homenagem") == "sim"
    with db.engine().begin() as c:
        c.execute(update(db.membros).where(db.membros.c.id == u["membro_id"]).values(
            homenagem_aniversario=quer, atualizado_em=datas.agora_utc()))
        auditar(request, "LGPD_HOMENAGEM_ANIVERSARIO", f"Membro #{u['membro_id']}",
                "Aceitou a homenagem de aniversário" if quer else "Recusou a homenagem de aniversário", conexao=c)
    flash(request, "Pronto! A equipe vai lembrar do seu aniversário. 🎂" if quer else
          "Pronto! Seu aniversário não vai mais aparecer para a equipe.")
    return ir("/minha-ficha")


rotas = [
    Route("/aniversariantes", calendario),
    Route("/aniversariantes/modelos", modelos),
    Route("/aniversariantes/modelos/salvar", salvar_modelo, methods=["POST"]),
    Route("/aniversariantes/resumo-email", resumo_email, methods=["POST"]),
    Route("/aniversariantes/{id:int}/mensagem", mensagem),
    Route("/aniversariantes/{id:int}/registrar", registrar, methods=["POST"]),
    Route("/aniversariantes/{id:int}/email", enviar_email, methods=["POST"]),
    Route("/avisos", avisos),
    Route("/minha-ficha/homenagem", minha_homenagem, methods=["POST"]),
]
