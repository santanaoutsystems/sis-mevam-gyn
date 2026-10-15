"""Regularização de fichas impressas antigas (Secretaria e Adm) e portal de atualização do membro.

Fluxo: a Secretaria cadastra ou importa a ficha antiga e anexa o escaneamento; o sistema gera um link
exclusivo com prazo para cada membro sem CPF, foto ou campos obrigatórios; o membro completa os dados
pelo link e o próprio registro é atualizado (sem duplicar). Quem não atualiza no prazo aparece no
relatório de vencidos para análise ou inativação.
"""

from __future__ import annotations

import base64
import csv
import io
import secrets
import threading
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from sqlalchemy import func, insert, select, update
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from .. import config, datas, db, envios, ficha, seguranca
from ..web import auditar, flash, ir, render
from .membros import ERRO_CPF_REPETIDO, _carregar, _contexto_form, _cpf_em_uso, _ligar_pelo_cpf, _valores_de

ADMIN_SECRETARIA = ("secretaria", "admin")
ORIGEM_IMPRESSA = "ficha_impressa"  # membros.origem é único (exceto 'novo'): cada ficha leva um sufixo
FORA_DA_REGULARIZACAO = ("Anonimizado (LGPD)", "Inativo")
TIPOS_ESCANEAMENTO = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
LIMITE_ESCANEAMENTO = 6 * 1024 * 1024


# ---------------------------------------------------------------------------
# Regras
# ---------------------------------------------------------------------------
def origem_impressa() -> str:
    return f"{ORIGEM_IMPRESSA}:{secrets.token_hex(6)}"


def pendencias(m: dict) -> list[str]:
    """O que falta na ficha: CPF, foto e os campos obrigatórios da ficha atual."""
    faltas = []
    if not m.get("cpf"):
        faltas.append("CPF")
    if not (m.get("foto_3x4") or m.get("tem_foto")):
        faltas.append("Foto 3x4")
    for campo, rotulo in ficha.OBRIGATORIOS.items():
        if campo not in ("nome_completo",) and not m.get(campo):
            faltas.append(rotulo)
    return faltas


def _utc(v) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, str):
        v = datetime.fromisoformat(v)
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


def _token(reg: dict) -> str:
    return seguranca.token_link("regularizacao", f"{reg['id']}.{reg['segredo']}")


def link_de(reg: dict) -> str:
    return f"{config.URL_BASE}/atualizar/{reg['id']}?t={_token(reg)}"


def situacao(reg: dict | None) -> str:
    """sem_link | ativo | enviado | vencido | concluido | revogado"""
    if not reg:
        return "sem_link"
    if reg["concluido_em"]:
        return "concluido"
    if reg["revogado"]:
        return "revogado"
    if _utc(reg["expira_em"]) < datas.agora_utc():
        return "vencido"
    return "enviado" if reg["enviado_em"] else "ativo"


def mensagem(m: dict, reg: dict) -> str:
    primeiro = (m.get("nome_completo") or "").split(" ")[0]
    prazo = datas.fmt_data_hora(_utc(reg["expira_em"]))[:10]
    return (f"Paz, {primeiro}! O MEVAM GYN está atualizando o cadastro dos membros. "
            f"Complete seus dados (CPF, foto e o que faltar) neste link exclusivo, válido até {prazo}: "
            f"{link_de(reg)}")


def link_whatsapp(m: dict, reg: dict) -> str:
    return f"https://wa.me/{envios.numero_whatsapp(m.get('whatsapp'))}?text={quote(mensagem(m, reg))}"


def _ultimos_links(c, membro_ids=None) -> dict:
    q = select(db.regularizacoes).order_by(db.regularizacoes.c.id)
    if membro_ids is not None:
        q = q.where(db.regularizacoes.c.membro_id.in_(list(membro_ids)))
    ultimos = {}
    for r in c.execute(q).mappings():
        ultimos[r["membro_id"]] = dict(r)
    return ultimos


def _criar_link(c, membro_id, dias: int, autor: str) -> dict:
    """Novo link exclusivo; os links anteriores ainda abertos deixam de valer."""
    c.execute(update(db.regularizacoes).where(
        db.regularizacoes.c.membro_id == membro_id, db.regularizacoes.c.concluido_em.is_(None),
        db.regularizacoes.c.revogado.is_(False)).values(revogado=True))
    valores = {"membro_id": membro_id, "segredo": secrets.token_urlsafe(24), "criado_por": autor,
               "criado_em": datas.agora_utc(), "expira_em": datas.agora_utc() + timedelta(days=dias)}
    rid = c.execute(insert(db.regularizacoes).values(**valores)).inserted_primary_key[0]
    return {**valores, "id": rid, "enviado_em": None, "concluido_em": None, "revogado": False, "canais": None}


def _marcar_envio(c, rid, canal: str) -> None:
    atual = c.execute(select(db.regularizacoes.c.canais).where(db.regularizacoes.c.id == rid)).scalar() or ""
    canais = ", ".join(sorted({x for x in (atual.split(", ") if atual else []) + [canal] if x}))
    c.execute(update(db.regularizacoes).where(db.regularizacoes.c.id == rid).values(
        enviado_em=datas.agora_utc(), canais=canais))


def disparar(rids: list, usuario: dict | None) -> None:
    """Envia o link por e-mail e WhatsApp automático (quando configurados). Falhas vão para a auditoria."""
    def tarefa():
        for rid in rids:
            with db.engine().connect() as c:
                reg = c.execute(select(db.regularizacoes).where(db.regularizacoes.c.id == rid)).mappings().first()
                if not reg:
                    continue
                reg = dict(reg)
                m = c.execute(select(db.membros.c.id, db.membros.c.nome_completo, db.membros.c.email,
                                     db.membros.c.whatsapp).where(db.membros.c.id == reg["membro_id"])).mappings().first()
            if not m:
                continue
            m = dict(m)
            texto = mensagem(m, reg)
            resultados = []
            if envios.email_configurado() and m.get("email"):
                erro = envios.enviar_email(m["email"], "MEVAM GYN: atualize seu cadastro", texto + "\n")
                resultados.append(("email", erro))
            if envios.whatsapp_configurado() and m.get("whatsapp"):
                resultados.append(("whatsapp", envios.enviar_whatsapp(m["whatsapp"], texto)))
            with db.engine().begin() as c:
                for canal, erro in resultados:
                    if erro is None:
                        _marcar_envio(c, rid, canal)
                    auditar(None, "REGULARIZACAO_ENVIO" if erro is None else "FALHA_ENVIO_REGULARIZACAO",
                            f"Membro #{m['id']}", f"{canal}" + (f": {erro}" if erro else ""), usuario=usuario, conexao=c)
    if config.ENVIO_SINCRONO:
        tarefa()
    else:
        threading.Thread(target=tarefa, daemon=True).start()


def _ler_escaneamento(arquivo) -> tuple[str | None, str | None]:
    """Devolve (data URL, erro). Imagens grandes são reduzidas para no máximo 2000 px (JPEG)."""
    tipo = (getattr(arquivo, "content_type", "") or "").lower()
    if tipo not in TIPOS_ESCANEAMENTO:
        return None, "Envie uma foto (JPG, PNG) ou um PDF da ficha."
    return tipo, None


async def _escaneamento_do_form(form) -> tuple[str | None, str | None]:
    arquivo = form.get("escaneada")
    if not arquivo or not getattr(arquivo, "filename", ""):
        return None, None
    tipo, erro = _ler_escaneamento(arquivo)
    if erro:
        return None, erro
    dados = await arquivo.read()
    if len(dados) > LIMITE_ESCANEAMENTO:
        return None, "Arquivo muito grande (máximo 6 MB)."
    if tipo.startswith("image/"):
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(dados))
            img = img.convert("RGB")
            img.thumbnail((2000, 2000))
            saida = io.BytesIO()
            img.save(saida, "JPEG", quality=80, optimize=True)
            dados, tipo = saida.getvalue(), "image/jpeg"
        except Exception:  # noqa: BLE001
            return None, "Não foi possível ler a imagem. Tente outra foto ou um PDF."
    return f"data:{tipo};base64,{base64.b64encode(dados).decode()}", None


# ---------------------------------------------------------------------------
# Painel da Secretaria
# ---------------------------------------------------------------------------
COLUNAS_PAINEL = ("id", "nome_completo", "whatsapp", "email", "status", "origem", "cpf", "data_nascimento",
                  *[k for k in ficha.OBRIGATORIOS if k not in ("nome_completo", "data_nascimento")])


@seguranca.exigir(*ADMIN_SECRETARIA)
async def painel(request: Request):
    aba = request.query_params.get("aba") or "pendentes"
    with db.engine().connect() as c:
        tem_foto = (func.coalesce(func.length(db.membros.c.foto_3x4), 0) > 0).label("tem_foto")
        tem_scan = (func.coalesce(func.length(db.membros.c.ficha_escaneada), 0) > 0).label("tem_escaneada")
        linhas = [dict(r) for r in c.execute(
            select(*[db.membros.c[k] for k in COLUNAS_PAINEL], tem_foto, tem_scan)
            .where(db.membros.c.status.notin_(("Anonimizado (LGPD)",)))
            .order_by(db.membros.c.nome_completo)).mappings()]
        ultimos = _ultimos_links(c)
    pend, venc, concl = [], [], []
    for m in linhas:
        reg = ultimos.get(m["id"])
        m["faltas"] = pendencias(m)
        m["reg"] = reg
        m["situacao"] = situacao(reg)
        if m["situacao"] == "concluido":
            concl.append(m)
        if m["status"] in FORA_DA_REGULARIZACAO or not m["faltas"]:
            continue
        (venc if m["situacao"] == "vencido" else pend).append(m)
    numeros = {"pendentes": len(pend), "vencidos": len(venc), "concluidos": len(concl),
               "com_link": sum(1 for m in pend if m["situacao"] in ("ativo", "enviado"))}
    lista = {"pendentes": pend, "vencidos": venc, "concluidos": concl}.get(aba, pend)
    return render(request, "regularizacao/painel.html", {
        "aba": aba, "lista": lista, "numeros": numeros, "prazo_padrao": config.REGULARIZACAO_PRAZO_DIAS,
        "email_ok": envios.email_configurado(), "whatsapp_ok": envios.whatsapp_configurado()})


@seguranca.exigir(*ADMIN_SECRETARIA)
async def nova(request: Request):
    """Cadastro de uma ficha impressa antiga (dados mínimos + escaneamento)."""
    if request.method == "GET":
        return render(request, "regularizacao/nova.html", {"valores": {}, "erros": {}})
    form = await request.form()
    valores = {k: (form.get(k) or "").strip() for k in ("nome_completo", "data_nascimento", "whatsapp", "email", "cpf")}
    erros = {}
    nome = ficha.nome_proprio(valores["nome_completo"])
    if len(nome.split()) < 2:
        erros["nome_completo"] = "Informe nome e sobrenome."
    nasc = None
    if valores["data_nascimento"]:
        nasc = datas.parse_data(valores["data_nascimento"])
        if not nasc or nasc > datas.hoje():
            erros["data_nascimento"] = "Data inválida (use dd/mm/aaaa)."
    if valores["whatsapp"] and not ficha.telefone_valido(valores["whatsapp"]):
        erros["whatsapp"] = ficha.ERRO_TELEFONE
    email = valores["email"].lower()
    if email and "@" not in email:
        erros["email"] = "E-mail inválido."
    cpf = ficha.so_digitos(valores["cpf"])
    if cpf and not ficha.cpf_valido(cpf):
        erros["cpf"] = ficha.ERRO_CPF
    escaneada, erro_scan = await _escaneamento_do_form(form)
    if erro_scan:
        erros["escaneada"] = erro_scan
    with db.engine().begin() as c:
        if cpf and not erros.get("cpf") and _cpf_em_uso(c, cpf):
            erros["cpf"] = ERRO_CPF_REPETIDO
        if erros:
            return render(request, "regularizacao/nova.html", {"valores": valores, "erros": erros}, 400)
        u = seguranca.usuario_atual(request)
        agora = datas.agora_utc()
        mid = c.execute(insert(db.membros).values(
            nome_completo=nome, data_nascimento=nasc, whatsapp=ficha.fmt_telefone(valores["whatsapp"]) or None,
            email=email or None, cpf=cpf or None, data_registro=datas.hoje(), status="Ativo",
            origem=origem_impressa(), credo_aceito=False, lgpd_consentimento=False,
            status_lgpd="Pendente (ficha impressa)", filhos=[],
            ficha_escaneada=escaneada, ficha_escaneada_em=agora if escaneada else None,
            ficha_escaneada_por=u["nome"] if escaneada else None, criado_em=agora, atualizado_em=agora,
        )).inserted_primary_key[0]
        _ligar_pelo_cpf(c, cpf or None, membro_id=mid)
        auditar(request, "CADASTRO_FICHA_IMPRESSA", f"Membro #{mid}",
                "Com ficha escaneada" if escaneada else "Sem escaneamento", conexao=c)
    flash(request, f"Ficha antiga de {nome} cadastrada (protocolo #{mid}).")
    if form.get("proxima") == "sim":
        return ir("/regularizacao/nova")
    return ir(f"/regularizacao/membro/{mid}")


CAMPOS_IMPORTACAO = {"nome": "nome_completo", "nome_completo": "nome_completo", "whatsapp": "whatsapp",
                     "telefone": "whatsapp", "celular": "whatsapp", "email": "email", "e-mail": "email",
                     "nascimento": "data_nascimento", "data_nascimento": "data_nascimento", "cpf": "cpf"}


@seguranca.exigir(*ADMIN_SECRETARIA)
async def importar(request: Request):
    """Planilha CSV com as fichas antigas: nome; whatsapp; email; nascimento; cpf. Não duplica quem já existe."""
    form = await request.form()
    arquivo = form.get("arquivo")
    if not arquivo or not getattr(arquivo, "filename", ""):
        flash(request, "Escolha o arquivo CSV da planilha.", "erro")
        return ir("/regularizacao")
    bruto = await arquivo.read()
    try:
        texto = bruto.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = bruto.decode("latin-1")
    separador = ";" if texto.split("\n", 1)[0].count(";") >= texto.split("\n", 1)[0].count(",") else ","
    leitor = csv.DictReader(io.StringIO(texto), delimiter=separador)
    mapa = {col: CAMPOS_IMPORTACAO.get((col or "").strip().lower()) for col in (leitor.fieldnames or [])}
    if "nome_completo" not in mapa.values():
        flash(request, "A planilha precisa de uma coluna 'nome'. Colunas aceitas: nome, whatsapp, email, nascimento, cpf.", "erro")
        return ir("/regularizacao")
    criados, repetidos, problemas = 0, 0, []
    u = seguranca.usuario_atual(request)
    with db.engine().begin() as c:
        existentes = {(ficha.nome_proprio(r[0] or "").lower(), r[1]) for r in
                      c.execute(select(db.membros.c.nome_completo, db.membros.c.data_nascimento))}
        for n, linha in enumerate(leitor, start=2):
            v = {mapa[k]: (val or "").strip() for k, val in linha.items() if mapa.get(k)}
            nome = ficha.nome_proprio(v.get("nome_completo", ""))
            if not nome:
                continue
            nasc = datas.parse_data(v.get("data_nascimento")) if v.get("data_nascimento") else None
            cpf = ficha.so_digitos(v.get("cpf", ""))
            if cpf and not ficha.cpf_valido(cpf):
                problemas.append(f"linha {n}: CPF inválido ({nome})")
                cpf = ""
            if (cpf and _cpf_em_uso(c, cpf)) or (nome.lower(), nasc) in existentes:
                repetidos += 1
                continue
            whats = v.get("whatsapp", "")
            agora = datas.agora_utc()
            c.execute(insert(db.membros).values(
                nome_completo=nome, data_nascimento=nasc, cpf=cpf or None,
                whatsapp=ficha.fmt_telefone(whats) if whats and ficha.telefone_valido(whats) else (whats or None),
                email=(v.get("email") or "").lower() or None, data_registro=datas.hoje(), status="Ativo",
                origem=origem_impressa(), credo_aceito=False, lgpd_consentimento=False,
                status_lgpd="Pendente (ficha impressa)", filhos=[], criado_em=agora, atualizado_em=agora))
            existentes.add((nome.lower(), nasc))
            criados += 1
        auditar(request, "IMPORTACAO_FICHAS_IMPRESSAS", "Membros",
                f"{criados} criadas, {repetidos} já existiam, {len(problemas)} avisos", usuario=u, conexao=c)
    flash(request, f"Importação concluída: {criados} fichas criadas, {repetidos} já existiam.")
    if problemas:
        flash(request, "Avisos: " + "; ".join(problemas[:10]) + (" ..." if len(problemas) > 10 else ""), "aviso")
    return ir("/regularizacao")


@seguranca.exigir(*ADMIN_SECRETARIA)
async def membro(request: Request):
    mid = request.path_params["id"]
    with db.engine().connect() as c:
        m = _carregar(c, mid)
        if not m:
            return render(request, "erro.html", {"titulo": "Não encontrado", "mensagem": "Ficha não encontrada."}, 404)
        links = [dict(r) for r in c.execute(select(db.regularizacoes).where(db.regularizacoes.c.membro_id == mid)
                                            .order_by(db.regularizacoes.c.id.desc())).mappings()]
    for r in links:
        r["situacao"] = situacao(r)
        r["link"] = link_de(r)
        r["whatsapp"] = link_whatsapp(m, r) if m.get("whatsapp") else None
    atual = links[0] if links and links[0]["situacao"] in ("ativo", "enviado") else None
    return render(request, "regularizacao/membro.html", {
        "m": m, "faltas": pendencias(m), "links": links, "atual": atual,
        "prazo_padrao": config.REGULARIZACAO_PRAZO_DIAS,
        "email_ok": envios.email_configurado(), "whatsapp_ok": envios.whatsapp_configurado()})


@seguranca.exigir(*ADMIN_SECRETARIA)
async def anexar_escaneada(request: Request):
    mid = request.path_params["id"]
    form = await request.form()
    escaneada, erro = await _escaneamento_do_form(form)
    if erro or not escaneada:
        flash(request, erro or "Escolha a foto ou o PDF da ficha impressa.", "erro")
        return ir(f"/regularizacao/membro/{mid}")
    u = seguranca.usuario_atual(request)
    with db.engine().begin() as c:
        c.execute(update(db.membros).where(db.membros.c.id == mid).values(
            ficha_escaneada=escaneada, ficha_escaneada_em=datas.agora_utc(), ficha_escaneada_por=u["nome"]))
        auditar(request, "FICHA_ESCANEADA_ANEXADA", f"Membro #{mid}", conexao=c)
    flash(request, "Ficha escaneada anexada.")
    return ir(f"/regularizacao/membro/{mid}")


@seguranca.exigir(*ADMIN_SECRETARIA)
async def ver_escaneada(request: Request):
    mid = request.path_params["id"]
    with db.engine().connect() as c:
        dado = c.execute(select(db.membros.c.ficha_escaneada).where(db.membros.c.id == mid)).scalar()
    if not dado or not dado.startswith("data:"):
        return render(request, "erro.html", {"titulo": "Sem escaneamento", "mensagem": "Esta ficha não tem escaneamento."}, 404)
    cabecalho, conteudo = dado.split(",", 1)
    tipo = cabecalho[5:].split(";")[0]
    auditar(request, "VISUALIZACAO_FICHA_ESCANEADA", f"Membro #{mid}")
    extensao = "pdf" if tipo == "application/pdf" else "jpg"
    return Response(base64.b64decode(conteudo), media_type=tipo, headers={
        "Content-Disposition": f'inline; filename="ficha_impressa_{mid}.{extensao}"', "Cache-Control": "no-store"})


@seguranca.exigir(*ADMIN_SECRETARIA)
async def gerar(request: Request):
    """Gera links (um ou vários membros) e, se pedido, envia por e-mail e WhatsApp automático."""
    form = await request.form()
    ids = [x for x in form.getlist("membro_id") if x]
    voltar = form.get("voltar") or "/regularizacao"
    if not voltar.startswith("/regularizacao"):
        voltar = "/regularizacao"
    try:
        dias = max(1, min(180, int(form.get("prazo") or config.REGULARIZACAO_PRAZO_DIAS)))
    except ValueError:
        dias = config.REGULARIZACAO_PRAZO_DIAS
    if not ids:
        flash(request, "Selecione ao menos um membro.", "erro")
        return ir(voltar)
    u = seguranca.usuario_atual(request)
    rids = []
    with db.engine().begin() as c:
        validos = {str(r[0]) for r in c.execute(select(db.membros.c.id).where(
            db.membros.c.id.in_([int(i) for i in ids if str(i).isdigit()]),
            db.membros.c.status != "Anonimizado (LGPD)"))}
        for mid in ids:
            if str(mid) in validos:
                rids.append(_criar_link(c, int(mid), dias, u["nome"])["id"])
        auditar(request, "REGULARIZACAO_LINKS_GERADOS", "Membros", f"{len(rids)} links, prazo {dias} dias", conexao=c)
    enviar = form.get("enviar") == "sim"
    if enviar and (envios.email_configurado() or envios.whatsapp_configurado()):
        disparar(rids, u)
        flash(request, f"{len(rids)} link(s) gerado(s), válidos por {dias} dias. Envio automático iniciado; "
                       "o resultado aparece na coluna Link em instantes.")
    elif enviar:
        flash(request, f"{len(rids)} link(s) gerado(s). O envio automático não está configurado: "
                       "use o botão de WhatsApp de cada membro.", "aviso")
    else:
        flash(request, f"{len(rids)} link(s) gerado(s), válidos por {dias} dias.")
    return ir(voltar)


async def _registro_link(c, rid):
    reg = c.execute(select(db.regularizacoes).where(db.regularizacoes.c.id == rid)).mappings().first()
    return dict(reg) if reg else None


@seguranca.exigir(*ADMIN_SECRETARIA)
async def whatsapp_manual(request: Request):
    """Registra o envio manual e abre o WhatsApp com a mensagem pronta."""
    rid = request.path_params["rid"]
    with db.engine().begin() as c:
        reg = await _registro_link(c, rid)
        if not reg or situacao(reg) not in ("ativo", "enviado"):
            flash(request, "Este link não está mais válido. Gere um novo.", "erro")
            return ir("/regularizacao")
        m = _carregar(c, reg["membro_id"])
        _marcar_envio(c, rid, "whatsapp")
        auditar(request, "REGULARIZACAO_ENVIO", f"Membro #{m['id']}", "whatsapp (manual)", conexao=c)
    return ir(link_whatsapp(m, reg))


@seguranca.exigir(*ADMIN_SECRETARIA)
async def revogar(request: Request):
    rid = request.path_params["rid"]
    with db.engine().begin() as c:
        reg = await _registro_link(c, rid)
        if not reg:
            return ir("/regularizacao")
        c.execute(update(db.regularizacoes).where(db.regularizacoes.c.id == rid).values(revogado=True))
        auditar(request, "REGULARIZACAO_LINK_REVOGADO", f"Membro #{reg['membro_id']}", conexao=c)
    flash(request, "Link cancelado. Ele não abre mais.")
    return ir(f"/regularizacao/membro/{reg['membro_id']}")


@seguranca.exigir(*ADMIN_SECRETARIA)
async def desfecho(request: Request):
    """Quem não atualizou no prazo: marcar para análise, inativar o vínculo ou reenviar com novo prazo."""
    form = await request.form()
    ids = [int(x) for x in form.getlist("membro_id") if str(x).isdigit()]
    acao = form.get("acao")
    motivo = (form.get("motivo") or "").strip()
    if not ids or acao not in ("em_analise", "inativar"):
        flash(request, "Selecione os membros e a ação.", "erro")
        return ir("/regularizacao?aba=vencidos")
    if acao == "inativar" and len(motivo) < 5:
        flash(request, "Para inativar, descreva o motivo.", "erro")
        return ir("/regularizacao?aba=vencidos")
    with db.engine().begin() as c:
        ultimos = _ultimos_links(c, ids)
        for mid in ids:
            reg = ultimos.get(mid)
            if not reg or situacao(reg) != "vencido":
                continue
            c.execute(update(db.regularizacoes).where(db.regularizacoes.c.id == reg["id"]).values(
                desfecho="inativado" if acao == "inativar" else "em_analise"))
            if acao == "inativar":
                c.execute(update(db.membros).where(db.membros.c.id == mid).values(
                    status="Inativo", atualizado_em=datas.agora_utc()))
            auditar(request, "REGULARIZACAO_INATIVACAO" if acao == "inativar" else "REGULARIZACAO_EM_ANALISE",
                    f"Membro #{mid}", motivo, conexao=c)
    flash(request, f"{len(ids)} membro(s) " + ("inativado(s)." if acao == "inativar" else "marcado(s) para análise."))
    return ir("/regularizacao?aba=vencidos")


# ---------------------------------------------------------------------------
# Portal do membro (link exclusivo)
# ---------------------------------------------------------------------------
def _validar_link(request: Request, rid) -> tuple[dict | None, str | None]:
    token = request.query_params.get("t") or ""
    with db.engine().connect() as c:
        reg = c.execute(select(db.regularizacoes).where(db.regularizacoes.c.id == rid)).mappings().first()
    if not reg or not seguranca.conferir_token_link("regularizacao", f"{reg['id']}.{reg['segredo']}", token):
        return None, "Este link não é válido. Peça um novo link à Secretaria."
    reg = dict(reg)
    s = situacao(reg)
    if s == "concluido":
        return reg, "Seus dados já foram atualizados. Obrigado!"
    if s == "revogado":
        return None, "Este link foi substituído por um mais novo. Use o último link recebido ou procure a Secretaria."
    if s == "vencido":
        return None, "O prazo deste link terminou. Procure a Secretaria para receber um novo."
    return reg, None


async def atualizar(request: Request):
    rid = request.path_params["rid"]
    reg, aviso = _validar_link(request, rid)
    if aviso:
        return render(request, "erro.html", {"titulo": "Atualização cadastral", "mensagem": aviso},
                      200 if reg else 403)
    with db.engine().connect() as c:
        m = _carregar(c, reg["membro_id"])
    if not m or m["status"] == "Anonimizado (LGPD)":
        return render(request, "erro.html", {"titulo": "Indisponível", "mensagem": "Cadastro indisponível."}, 404)
    faltas = pendencias(m)
    if request.method == "GET":
        return render(request, "membros/ficha.html", _contexto_form(
            {"modo": "regularizar", "m": m, "valores": _valores_de(m), "faltas": faltas}))

    if not await seguranca.conferir_csrf(request):
        flash(request, "A página expirou. Seus dados não foram salvos; preencha novamente.", "erro")
        return ir(f"/atualizar/{rid}?t={request.query_params.get('t')}")
    form = await request.form()
    dados, erros = ficha.validar(form)
    if not erros.get("cpf"):
        with db.engine().connect() as c:
            if _cpf_em_uso(c, dados["cpf"], membro_id=m["id"]):
                erros["cpf"] = ERRO_CPF_REPETIDO
    if erros:
        return render(request, "membros/ficha.html", _contexto_form(
            {"modo": "regularizar", "m": m, "valores": dict(form), "erros": erros, "faltas": faltas}), 400)
    agora = datas.agora_utc()
    alterados = [k for k, v in dados.items() if m.get(k) != v and k != "foto_3x4"]
    with db.engine().begin() as c:
        c.execute(update(db.membros).where(db.membros.c.id == m["id"]).values(
            **dados, lgpd_consentimento=True, lgpd_versao_termo=config.VERSAO_TERMO_LGPD,
            lgpd_data_consentimento=agora, lgpd_ip_origem=seguranca.ip_cliente(request),
            status_lgpd="Consentimento Ativo", atualizado_em=agora))
        c.execute(update(db.usuarios).where(db.usuarios.c.membro_id == m["id"], db.usuarios.c.cpf.is_(None))
                  .values(cpf=dados["cpf"]))
        _ligar_pelo_cpf(c, dados["cpf"], membro_id=m["id"])
        c.execute(update(db.regularizacoes).where(db.regularizacoes.c.id == reg["id"]).values(concluido_em=agora))
        c.execute(update(db.regularizacoes).where(
            db.regularizacoes.c.membro_id == m["id"], db.regularizacoes.c.id != reg["id"],
            db.regularizacoes.c.concluido_em.is_(None)).values(revogado=True))
        auditar(request, "REGULARIZACAO_CONCLUIDA", f"Membro #{m['id']}",
                "Campos: " + ", ".join(alterados), usuario=None, conexao=c)
    request.session["regularizado"] = (m["nome_completo"] or "").split(" ")[0]
    return ir("/atualizar/concluido")


async def concluido(request: Request):
    nome = request.session.pop("regularizado", None)
    if not nome:
        return ir("/")
    return render(request, "regularizacao/concluido.html", {"nome": nome})


rotas = [
    Route("/regularizacao", painel),
    Route("/regularizacao/nova", nova, methods=["GET", "POST"]),
    Route("/regularizacao/importar", importar, methods=["POST"]),
    Route("/regularizacao/gerar", gerar, methods=["POST"]),
    Route("/regularizacao/desfecho", desfecho, methods=["POST"]),
    Route("/regularizacao/membro/{id:int}", membro),
    Route("/regularizacao/membro/{id:int}/escaneada", ver_escaneada),
    Route("/regularizacao/membro/{id:int}/escaneada/anexar", anexar_escaneada, methods=["POST"]),
    Route("/regularizacao/link/{rid:int}/whatsapp", whatsapp_manual, methods=["POST"]),
    Route("/regularizacao/link/{rid:int}/revogar", revogar, methods=["POST"]),
    Route("/atualizar/concluido", concluido),
    Route("/atualizar/{rid:int}", atualizar, methods=["GET", "POST"]),
]
