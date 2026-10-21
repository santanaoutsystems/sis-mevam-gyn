"""Mutirão de fichas históricas (v2.13.0).

A Secretaria/Adm cria um lote (ex.: "Fichas históricas · INTEGRA aprovado pelo pastor fundador") e recebe um
link com código. As voluntárias abrem o link no celular, sem login, e lançam os dados de cada ficha em papel
(as digitalizações ficam no Drive da Secretaria, não no banco: com MUTIRAO_DRIVE_PASTA, a foto tirada na própria
tela vai para a pasta do mutirão pelo Apps Script da Secretaria; sem ela, a voluntária usa o app do Drive). Cada ficha entra como Validado pela Secretaria,
com o INTEGRA concluído (registro histórico) e a justificativa do lote, pronta para o Credo. A Secretaria envia o
link do Credo em lote (e-mail, até o limite diário) e pelo WhatsApp para quem não tem e-mail. Na assinatura, o
membro também dá o consentimento LGPD que a ficha de papel não tinha.

Ficha sem CPF entra como Aguardando Análise e segue o padrão da Regularização: link para o membro completar
os dados no prazo padrão (REGULARIZACAO_PRAZO_DIAS); depois a Secretaria valida e o Credo segue normalmente.

A tela pública só grava fichas: não mostra nem devolve dados de ninguém.
"""

from __future__ import annotations

import re
import secrets
import threading
from datetime import timedelta

from sqlalchemy import func, insert, select, update
from starlette.requests import Request
from starlette.routing import Route

from .. import config, datas, db, envios, ficha, integra, seguranca
from ..web import auditar, flash, ir, render
from . import regularizacao
from .membros import ERRO_CPF_REPETIDO, _cpf_em_uso, _ligar_pelo_cpf, _link_credo, whatsapp_credo

ADMIN_SECRETARIA = ("secretaria", "admin")
JUSTIFICATIVA_PADRAO = "INTEGRA concluído antes do sistema, aprovado verbalmente pelo pastor fundador."
VALIDADE_PADRAO = 30  # dias
LIMITE_DIARIO = integra.LIMITE_DIARIO  # mesma cota do Gmail da Secretaria
PENDENTE_LGPD = "Pendente (ficha impressa)"


def origem_do_lote(lote_id: int) -> str:
    return f"mutirao:{lote_id}:{secrets.token_hex(5)}"  # membros.origem é único


def _prefixo(lote_id: int) -> str:
    return f"mutirao:{lote_id}:"


def _lote(c, lid) -> dict | None:
    r = c.execute(select(db.mutirao_lotes).where(db.mutirao_lotes.c.id == lid)).mappings().first()
    return dict(r) if r else None


def _gerar_codigo(c) -> str:
    while True:
        codigo = "".join(secrets.choice(integra.ALFABETO) for _ in range(6))
        if not c.execute(select(db.mutirao_lotes.c.id).where(db.mutirao_lotes.c.codigo == codigo)).first():
            return codigo


def _vigente(lote: dict, agora=None) -> bool:
    return integra._utc(lote["valido_ate"]) >= (agora or datas.agora_utc())


_RE_DRIVE = re.compile(r"https://drive\.google\.com/file/d/[\w-]+/view")


def link_lote(lote: dict) -> str:
    return f"{config.URL_BASE}/mutirao/{lote['codigo']}"


def _fichas(c, lote_id: int) -> list[dict]:
    q = (select(db.membros.c.id, db.membros.c.nome_completo, db.membros.c.data_nascimento, db.membros.c.email,
                db.membros.c.whatsapp, db.membros.c.cpf, db.membros.c.status, db.membros.c.credo_aceito,
                db.membros.c.credo_email_em, db.membros.c.link_credo_enviado, db.membros.c.integra_registrado_por,
                db.membros.c.criado_em, db.membros.c.integra_situacao, db.membros.c.observacoes)
         .where(db.membros.c.origem.like(_prefixo(lote_id) + "%"), db.membros.c.status != db.EXCLUIDO)
         .order_by(db.membros.c.criado_em.desc()))
    fichas = [dict(r) for r in c.execute(q).mappings()]
    for m in fichas:
        m["drive"] = _RE_DRIVE.findall(m.pop("observacoes") or "")
    return fichas


def enviados_hoje(c) -> int:
    inicio = integra.fim_do_dia(datas.hoje() - timedelta(days=1))
    return c.execute(select(func.count()).select_from(db.membros)
                     .where(db.membros.c.credo_email_em > inicio)).scalar() or 0


def texto_credo(m: dict) -> tuple[str, str]:
    primeiro = (m.get("nome_completo") or "").split(" ")[0]
    return ("Assine a sua Confissão de Fé · MEVAM GYN",
            f"Paz, {primeiro}!\n\n"
            "A sua ficha de membro do MEVAM GYN foi registrada no novo sistema da igreja (SIS MEVAM-GYN), "
            "com o INTEGRA reconhecido pela liderança.\n\n"
            "Para concluir, leia a Confissão de Fé e faça a sua rubrica digital pelo link abaixo. Ao assinar, "
            "você também confirma o uso dos seus dados pela Secretaria, conforme a LGPD:\n"
            f"{_link_credo(m['id'])}\n\n"
            "Depois da assinatura você recebe por e-mail a cópia do documento assinado.\n\n"
            "Secretaria MEVAM GYN")


def _enviar_emails(lista: list[dict]) -> None:
    for m in lista:
        envios.enviar_email(m["email"], *texto_credo(m))


# ---------------------------------------------------------------------------
# Secretaria e Adm
# ---------------------------------------------------------------------------
@seguranca.exigir(*ADMIN_SECRETARIA)
async def painel(request: Request):
    with db.engine().connect() as c:
        lotes = [dict(r) for r in c.execute(select(db.mutirao_lotes).order_by(db.mutirao_lotes.c.id.desc())).mappings()]
        for lote in lotes:
            fichas = _fichas(c, lote["id"])
            lote["total"] = len(fichas)
            lote["assinadas"] = sum(1 for m in fichas if m["credo_aceito"])
            lote["vigente"] = _vigente(lote)
    return render(request, "mutirao/painel.html", {"lotes": lotes, "JUSTIFICATIVA": JUSTIFICATIVA_PADRAO,
                                                   "VALIDADE": VALIDADE_PADRAO})


@seguranca.exigir(*ADMIN_SECRETARIA)
async def novo_lote(request: Request):
    form = await request.form()
    nome = (form.get("nome") or "").strip()[:120]
    justificativa = (form.get("justificativa") or "").strip()[:1000] or JUSTIFICATIVA_PADRAO
    try:
        dias = max(1, min(90, int(form.get("dias") or VALIDADE_PADRAO)))
    except ValueError:
        dias = VALIDADE_PADRAO
    if not nome or len(justificativa) < 10:
        flash(request, "Informe o nome do lote e a justificativa do INTEGRA (pelo menos 10 caracteres).", "erro")
        return ir("/mutirao")
    u = seguranca.usuario_atual(request)
    with db.engine().begin() as c:
        codigo = _gerar_codigo(c)
        lid = c.execute(insert(db.mutirao_lotes).values(
            nome=nome, justificativa=justificativa, codigo=codigo,
            valido_ate=integra.fim_do_dia(datas.hoje() + timedelta(days=dias - 1)),
            criado_por=u["nome"], criado_em=datas.agora_utc())).inserted_primary_key[0]
        auditar(request, "MUTIRAO_LOTE_CRIADO", f"Lote do mutirão #{lid}", f"{nome} · {justificativa}", conexao=c)
    flash(request, f"Lote criado. Envie o link às voluntárias: código {codigo}, válido por {dias} dia(s).")
    return ir(f"/mutirao/lotes/{lid}")


@seguranca.exigir(*ADMIN_SECRETARIA)
async def lote(request: Request):
    lid = request.path_params["id"]
    with db.engine().connect() as c:
        lt = _lote(c, lid)
        if not lt:
            return ir("/mutirao")
        fichas = _fichas(c, lt["id"])
        hoje_enviados = enviados_hoje(c)
    lt["vigente"] = _vigente(lt)
    pend_email = [m for m in fichas if not m["credo_aceito"] and m["email"] and not m["credo_email_em"]
                  and m["status"] == "Validado pela Secretaria"]
    so_whats = [m for m in fichas if not m["credo_aceito"] and not m["email"] and m["whatsapp"]
                and m["status"] == "Validado pela Secretaria"]
    for m in so_whats:
        m["wa"] = whatsapp_credo(m)
    sem_cpf = [m for m in fichas if not m["cpf"] and m["status"] == "Aguardando Análise"]
    with db.engine().connect() as c:
        links = regularizacao._ultimos_links(c, [m["id"] for m in sem_cpf]) if sem_cpf else {}
    for m in sem_cpf:
        reg = links.get(m["id"])
        m["situacao_link"] = regularizacao.situacao(reg)
        m["reg"] = reg
        m["wa_link"] = regularizacao.link_whatsapp(m, reg) if reg and m["situacao_link"] in ("ativo", "enviado") \
            and m["whatsapp"] else None
    por_voluntaria: dict[str, int] = {}
    for m in fichas:
        quem = (m["integra_registrado_por"] or "").replace("Mutirão · ", "") or "-"
        por_voluntaria[quem] = por_voluntaria.get(quem, 0) + 1
    numeros = {"total": len(fichas), "assinadas": sum(1 for m in fichas if m["credo_aceito"]),
               "email_enviado": sum(1 for m in fichas if m["credo_email_em"]),
               "sem_contato": sum(1 for m in fichas if not m["email"] and not m["whatsapp"]),
               "sem_cpf": len(sem_cpf)}
    return render(request, "mutirao/lote.html", {
        "lt": lt, "fichas": fichas, "link": link_lote(lt), "pend_email": pend_email, "so_whats": so_whats,
        "numeros": numeros, "sem_cpf": sem_cpf, "PRAZO_REG": config.REGULARIZACAO_PRAZO_DIAS,
        "sem_link": sum(1 for m in sem_cpf if m["situacao_link"] in ("sem_link", "vencido", "revogado")),
        "por_voluntaria": sorted(por_voluntaria.items(), key=lambda x: -x[1]),
        "restam_hoje": max(0, LIMITE_DIARIO - hoje_enviados), "LIMITE": LIMITE_DIARIO,
        "email_ok": envios.email_configurado()})


@seguranca.exigir(*ADMIN_SECRETARIA)
async def validade(request: Request):
    lid = request.path_params["id"]
    form = await request.form()
    with db.engine().begin() as c:
        lt = _lote(c, lid)
        if not lt:
            return ir("/mutirao")
        if form.get("acao") == "encerrar":
            novo = datas.agora_utc() - timedelta(seconds=1)
            msg = "Link encerrado: as voluntárias não conseguem mais lançar fichas neste lote."
        else:
            try:
                dias = max(1, min(90, int(form.get("dias") or 7)))
            except ValueError:
                dias = 7
            novo = integra.fim_do_dia(datas.hoje() + timedelta(days=dias - 1))
            msg = f"Link válido até {datas.fmt_data_hora(novo)}."
        c.execute(update(db.mutirao_lotes).where(db.mutirao_lotes.c.id == lt["id"]).values(valido_ate=novo))
        auditar(request, "MUTIRAO_VALIDADE", f"Lote do mutirão #{lt['id']}", msg, conexao=c)
    flash(request, msg)
    return ir(f"/mutirao/lotes/{lid}")


@seguranca.exigir(*ADMIN_SECRETARIA)
async def enviar_credo(request: Request):
    """Envia o link do Credo por e-mail para as fichas do lote, respeitando o limite diário."""
    lid = request.path_params["id"]
    with db.engine().begin() as c:
        lt = _lote(c, lid)
        if not lt:
            return ir("/mutirao")
        if not envios.email_configurado():
            flash(request, "O envio de e-mail não está configurado. Use a lista do WhatsApp.", "erro")
            return ir(f"/mutirao/lotes/{lid}")
        restam = max(0, LIMITE_DIARIO - enviados_hoje(c))
        lista = [m for m in _fichas(c, lt["id"]) if not m["credo_aceito"] and m["email"] and not m["credo_email_em"]
                 and m["status"] == "Validado pela Secretaria"]
        lista.sort(key=lambda m: m["id"])
        lista = lista[:restam]
        agora = datas.agora_utc()
        for m in lista:
            c.execute(update(db.membros).where(db.membros.c.id == m["id"]).values(
                credo_email_em=agora, link_credo_enviado=True))
        auditar(request, "MUTIRAO_CREDO_EMAIL", f"Lote do mutirão #{lt['id']}",
                f"{len(lista)} e-mail(s) com o link do Credo", conexao=c)
    if not lista:
        flash(request, "Nenhum e-mail enviado: ou não há pendentes com e-mail, ou o limite de hoje já foi usado.")
        return ir(f"/mutirao/lotes/{lid}")
    if config.ENVIO_SINCRONO:
        _enviar_emails(lista)
    else:
        threading.Thread(target=_enviar_emails, args=(lista,), daemon=True).start()
    flash(request, f"Link do Credo enviado por e-mail para {len(lista)} pessoa(s). Volte amanhã para o próximo grupo.")
    return ir(f"/mutirao/lotes/{lid}")


@seguranca.exigir(*ADMIN_SECRETARIA)
async def complemento(request: Request):
    """Fichas sem CPF: gera o link da Regularização (prazo padrão) e envia por e-mail/WhatsApp automático."""
    lid = request.path_params["id"]
    u = seguranca.usuario_atual(request)
    dias = config.REGULARIZACAO_PRAZO_DIAS
    with db.engine().begin() as c:
        lt = _lote(c, lid)
        if not lt:
            return ir("/mutirao")
        alvo = [m for m in _fichas(c, lt["id"]) if not m["cpf"] and m["status"] == "Aguardando Análise"]
        links = regularizacao._ultimos_links(c, [m["id"] for m in alvo]) if alvo else {}
        rids = [regularizacao._criar_link(c, m["id"], dias, u["nome"])["id"] for m in alvo
                if regularizacao.situacao(links.get(m["id"])) in ("sem_link", "vencido", "revogado")]
        auditar(request, "MUTIRAO_COMPLEMENTO", f"Lote do mutirão #{lt['id']}",
                f"{len(rids)} link(s) de complemento (sem CPF), prazo {dias} dias", conexao=c)
    if not rids:
        flash(request, "Todas as fichas sem CPF já têm link de complemento válido.")
    elif envios.email_configurado() or envios.whatsapp_configurado():
        regularizacao.disparar(rids, u)
        flash(request, f"{len(rids)} link(s) de complemento gerado(s), válidos por {dias} dias. Envio automático iniciado; "
                       "para quem não tem e-mail, use o botão de WhatsApp da lista.")
    else:
        flash(request, f"{len(rids)} link(s) gerado(s), válidos por {dias} dias. Envie pelo botão de WhatsApp da lista.", "aviso")
    return ir(f"/mutirao/lotes/{lid}#sem-cpf")


@seguranca.exigir(*ADMIN_SECRETARIA)
async def whatsapp_enviado(request: Request):
    lid, mid = request.path_params["id"], request.path_params["mid"]
    with db.engine().begin() as c:
        m = c.execute(select(db.membros.c.id, db.membros.c.origem).where(db.membros.c.id == mid)).first()
        if m and (m.origem or "").startswith(_prefixo(lid)):
            c.execute(update(db.membros).where(db.membros.c.id == mid).values(link_credo_enviado=True))
            auditar(request, "LINK_CREDO_ENVIADO", f"Membro #{mid}", "WhatsApp (mutirão)", conexao=c)
    return ir(f"/mutirao/lotes/{lid}#whatsapp")


# ---------------------------------------------------------------------------
# Tela pública das voluntárias
# ---------------------------------------------------------------------------
CAMPOS = ("nome_completo", "data_nascimento", "cpf", "whatsapp", "email", "arquivo")


def _validar_ficha(c, valores: dict) -> tuple[dict, dict]:
    erros: dict = {}
    nome = ficha.nome_proprio(valores["nome_completo"])
    if len(nome.split()) < 2:
        erros["nome_completo"] = "Informe nome e sobrenome, como está na ficha."
    nasc = datas.parse_data(valores["data_nascimento"])
    if not nasc or nasc > datas.hoje() or nasc.year < 1900:
        erros["data_nascimento"] = "Data de nascimento inválida (dd/mm/aaaa)."
    elif (integra.idade(nasc) or 0) < integra.IDADE_MINIMA:
        erros["data_nascimento"] = "Menor de 18 anos: não lance. Separe esta ficha para a Secretaria."
    cpf = ficha.so_digitos(valores["cpf"])
    if cpf and not ficha.cpf_valido(cpf):
        erros["cpf"] = ficha.ERRO_CPF + " Se a ficha não tiver CPF, deixe em branco."
    whats = valores["whatsapp"]
    if whats and not ficha.telefone_valido(whats):
        erros["whatsapp"] = ficha.ERRO_TELEFONE
    email = valores["email"].lower()
    if email and not ficha._RE_EMAIL.match(email):
        erros["email"] = "E-mail inválido."
    if not whats and not email:
        erros["whatsapp"] = "Informe o WhatsApp ou o e-mail: é por eles que o membro recebe o link do Credo."
    if not erros:
        if cpf and _cpf_em_uso(c, cpf):
            erros["cpf"] = ERRO_CPF_REPETIDO
        else:
            existe = c.execute(select(db.membros.c.id).where(
                func.lower(db.membros.c.nome_completo) == nome.lower(), db.membros.c.data_nascimento == nasc,
                db.membros.c.status.notin_((db.ANONIMIZADO, db.EXCLUIDO)))).first()
            if existe:
                erros["nome_completo"] = "Esta pessoa já está no sistema (mesmo nome e data de nascimento). Não lance de novo."
    dados = {"nome_completo": nome, "data_nascimento": nasc, "cpf": cpf or None, "email": email or None,
             "whatsapp": ficha.fmt_telefone(whats) if whats else None,
             "ocr_documento_nome": valores["arquivo"][:200] or None}
    return dados, erros


MAX_FOTOS = 3
MAX_BYTES_FOTO = 8 * 1024 * 1024
TIPOS_FOTO = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "application/pdf": ".pdf"}


async def _ler_fotos(form) -> tuple[list[tuple[str, bytes]], str | None]:
    """Fotos da ficha (frente, verso) enviadas pela voluntária, para gravar no Drive da Secretaria."""
    fotos = []
    for arq in form.getlist("foto_ficha")[:MAX_FOTOS]:
        if not getattr(arq, "filename", None):
            continue
        mime = (arq.content_type or "").split(";")[0].strip().lower()
        if mime not in TIPOS_FOTO:
            return [], "Envie a foto (JPG ou PNG) ou o PDF da ficha."
        dados = await arq.read()
        if len(dados) > MAX_BYTES_FOTO:
            return [], "Arquivo grande demais (máximo 8 MB). Tire a foto de novo."
        if dados:
            fotos.append((mime, dados))
    return fotos, None


def link_drive(arquivo_id: str) -> str:
    return f"https://drive.google.com/file/d/{arquivo_id}/view"


def _guardar_no_drive(mid: int, nome: str, fotos: list[tuple[str, bytes]]) -> int:
    """Grava as fotos na pasta do mutirão e anota os links na ficha. Devolve quantas foram gravadas."""
    ids, falhas = [], []
    for i, (mime, dados) in enumerate(fotos, 1):
        sufixo = f" ({i})" if len(fotos) > 1 else ""
        arq_id, erro = envios.salvar_no_drive(f"{nome} - ficha {mid}{sufixo}{TIPOS_FOTO[mime]}", mime, dados)
        if arq_id:
            ids.append(arq_id)
        else:
            falhas.append(erro or "falha")
    nota = (" Ficha no Drive: " + " ".join(link_drive(x) for x in ids)) if ids else ""
    if falhas:
        nota += " Foto não enviada ao Drive (" + "; ".join(falhas)[:150] + ")."
    with db.engine().begin() as c:
        m = c.execute(select(db.membros.c.observacoes).where(db.membros.c.id == mid)).first()
        valores = {"observacoes": ((m.observacoes or "") + nota)[:2000]}
        if ids:
            valores["ocr_documento_nome"] = f"Drive: {nome} - ficha {mid}"[:200]
        c.execute(update(db.membros).where(db.membros.c.id == mid).values(**valores))
    return len(ids)


async def voluntaria(request: Request):
    codigo = integra.normalizar_codigo(request.path_params["codigo"])
    with db.engine().connect() as c:
        lt = c.execute(select(db.mutirao_lotes).where(db.mutirao_lotes.c.codigo == codigo)).mappings().first()
    lt = dict(lt) if lt else None
    if not lt or not _vigente(lt):
        return render(request, "mutirao/voluntaria.html", {"erro_link": (
            "Este link do mutirão foi encerrado. Fale com a Secretaria." if lt else
            "Link do mutirão não encontrado. Confira o endereço com a Secretaria.")}, 410 if lt else 404)
    chave = f"mutirao_{lt['id']}"
    sessao = request.session.get(chave) or {}
    ctx = {"lt": lt, "codigo": codigo, "voluntaria": sessao.get("nome"), "lancadas": sessao.get("n", 0),
           "valores": {}, "erros": {}, "drive": envios.drive_configurado()}
    if request.method == "GET":
        return render(request, "mutirao/voluntaria.html", ctx)

    if not await seguranca.conferir_csrf(request):
        flash(request, "A página expirou. Tente de novo.", "erro")
        return ir(f"/mutirao/{codigo}")
    ip = seguranca.ip_cliente(request)
    if seguranca.ip_bloqueado(ip):
        return render(request, "mutirao/voluntaria.html", {**ctx, "erro_link": "Muitas tentativas. Tente mais tarde."}, 429)
    form = await request.form()
    if form.get("acao") == "identificar":
        nome = ficha.nome_proprio(form.get("voluntaria") or "")[:80]
        if len(nome.split()) < 2:
            return render(request, "mutirao/voluntaria.html", {**ctx, "erro_nome": "Informe o seu nome e sobrenome."}, 400)
        request.session[chave] = {"nome": nome, "n": 0}
        return ir(f"/mutirao/{codigo}")
    if not sessao.get("nome"):
        return ir(f"/mutirao/{codigo}")

    valores = {k: (form.get(k) or "").strip() for k in CAMPOS}
    fotos, erro_foto = await _ler_fotos(form)
    if erro_foto:
        return render(request, "mutirao/voluntaria.html", {**ctx, "valores": valores, "erros": {"foto_ficha": erro_foto}}, 400)
    if form.get("conferido") != "sim":
        erros = {"conferido": "Confira os dados com a ficha em papel e marque a caixa."}
        return render(request, "mutirao/voluntaria.html", {**ctx, "valores": valores, "erros": erros}, 400)
    with db.engine().begin() as c:
        dados, erros = _validar_ficha(c, valores)
        if erros:
            if "cpf" in erros and erros["cpf"] == ERRO_CPF_REPETIDO:
                seguranca.registrar_falha_ip(ip)
            return render(request, "mutirao/voluntaria.html", {**ctx, "valores": valores, "erros": erros}, 400)
        agora = datas.agora_utc()
        por = f"Mutirão · {sessao['nome']}"
        # Sem CPF: fica em análise e segue a Regularização (complemento de dados no prazo padrão)
        validada = bool(dados["cpf"])
        mid = c.execute(insert(db.membros).values(
            **dados, data_registro=datas.hoje(), status="Validado pela Secretaria" if validada else "Aguardando Análise",
            validado_por=por if validada else None, data_validacao=agora if validada else None, origem=origem_do_lote(lt["id"]),
            credo_aceito=False, lgpd_consentimento=False, status_lgpd=PENDENTE_LGPD, filhos=[],
            integra_situacao="concluido", integra_justificativa=lt["justificativa"],
            integra_registrado_por=por, integra_registrado_em=agora,
            observacoes=f"Ficha histórica lançada no mutirão \"{lt['nome']}\" por {sessao['nome']}.",
            criado_em=agora, atualizado_em=agora)).inserted_primary_key[0]
        _ligar_pelo_cpf(c, dados["cpf"], membro_id=mid)
        auditar(request, "MUTIRAO_FICHA", f"Membro #{mid}", f"Lote #{lt['id']} · {lt['nome']}",
                usuario={"id": None, "nome": por}, conexao=c)
    request.session[chave] = {"nome": sessao["nome"], "n": sessao.get("n", 0) + 1}
    request.session["mutirao_ultima"] = dados["nome_completo"].split(" ")[0]
    primeiro = dados["nome_completo"].split(" ")[0]
    if fotos and envios.drive_configurado():
        enviadas = _guardar_no_drive(mid, dados["nome_completo"], fotos)
        if enviadas == len(fotos):
            flash(request, f"Ficha de {primeiro} salva e a foto foi para o Drive da Secretaria. Pode lançar a próxima.")
        else:
            flash(request, f"Ficha de {primeiro} salva, mas a foto não chegou ao Drive. Separe esta ficha para a Secretaria.", "aviso")
        return ir(f"/mutirao/{codigo}")
    flash(request, f"Ficha de {primeiro} salva. Pode lançar a próxima.")
    return ir(f"/mutirao/{codigo}")


rotas = [
    Route("/mutirao", painel),
    Route("/mutirao/lotes", novo_lote, methods=["POST"]),
    Route("/mutirao/lotes/{id:int}", lote),
    Route("/mutirao/lotes/{id:int}/validade", validade, methods=["POST"]),
    Route("/mutirao/lotes/{id:int}/credo", enviar_credo, methods=["POST"]),
    Route("/mutirao/lotes/{id:int}/complemento", complemento, methods=["POST"]),
    Route("/mutirao/lotes/{id:int}/whatsapp/{mid:int}", whatsapp_enviado, methods=["POST"]),
    Route("/mutirao/{codigo}", voluntaria, methods=["GET", "POST"]),
]
