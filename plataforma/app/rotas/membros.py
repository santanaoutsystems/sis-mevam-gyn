"""Ficha de membro, painel da Secretaria, Credo com rúbrica digital e direitos LGPD."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from html import escape
from urllib.parse import quote

from sqlalchemy import delete, func, insert, or_, select, update
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from .. import config, datas, db, ficha, seguranca
from ..pdf import gerar_pdf_membro
from ..web import auditar, flash, ir, render

ADMIN_SECRETARIA = ("secretaria", "admin")


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------
def _carregar(c, membro_id: int) -> dict | None:
    row = c.execute(select(db.membros).where(db.membros.c.id == membro_id)).mappings().first()
    return dict(row) if row else None


def _setores_do_membro(c, membro_id: int) -> list[dict]:
    q = (select(db.membro_setores.c.departamento_id, db.membro_setores.c.funcao, db.departamentos.c.nome)
         .join(db.departamentos, db.departamentos.c.id == db.membro_setores.c.departamento_id)
         .where(db.membro_setores.c.membro_id == membro_id).order_by(db.departamentos.c.nome))
    return [dict(r) for r in c.execute(q).mappings()]


def _link_credo(membro_id: int) -> str:
    return f"{config.URL_BASE}/credo/{membro_id}?t={seguranca.token_link('credo', membro_id)}"


def _hash_rubrica(membro: dict, assinatura: str, quando, ip: str) -> str:
    conteudo = f"{membro['id']}|{membro['nome_assinante']}|{quando.isoformat()}|" \
               f"{hashlib.sha256(assinatura.encode()).hexdigest()}|{ip}"
    return hashlib.sha256(conteudo.encode()).hexdigest()


def _para_pdf(m: dict) -> dict:
    """Adapta o registro ao gerador de PDF (textos escapados e datas em dd/mm/aaaa)."""
    saida = {}
    for k, v in m.items():
        if k in ("foto_3x4", "assinatura_rubrica"):
            saida[k] = v or ""
        elif isinstance(v, str):
            saida[k] = escape(v)
        else:
            saida[k] = v
    for k in ("data_nascimento", "data_batismo", "data_registro"):
        saida[k] = datas.fmt_data(m.get(k))
    saida["data_assinatura"] = datas.fmt_data_hora(m.get("data_assinatura"))
    saida["filhos"] = [{"nome": escape(f.get("nome", "")), "nascimento": f.get("data_nascimento", ""),
                        "idade": datas.idade(f.get("data_nascimento")) if f.get("data_nascimento") else "-"}
                       for f in (m.get("filhos") or [])]
    if m.get("batizado") == "Não":
        saida["data_batismo"] = "Não batizado"
    return saida


def _pode_ver(usuario: dict, membro_id: int) -> bool:
    return usuario["perfil"] in ADMIN_SECRETARIA or usuario.get("membro_id") == membro_id


def _contexto_form(extra: dict | None = None) -> dict:
    ctx = {"ESTADOS_CIVIS": ficha.ESTADOS_CIVIS, "ESCOLARIDADES": ficha.ESCOLARIDADES,
           "SEXOS": ficha.SEXOS, "SIM_NAO": ficha.SIM_NAO, "valores": {}, "erros": {}}
    ctx.update(extra or {})
    return ctx


def _valores_de(m: dict) -> dict:
    v = dict(m)
    v["data_nascimento"] = datas.fmt_data(m.get("data_nascimento"))
    v["data_batismo"] = datas.fmt_data(m.get("data_batismo"))
    v["filhos_json"] = json.dumps(m.get("filhos") or [], ensure_ascii=False)
    return v


# ---------------------------------------------------------------------------
# Ficha pública (pré-cadastro)
# ---------------------------------------------------------------------------
async def ficha_publica(request: Request):
    if request.method == "GET":
        return render(request, "membros/ficha.html", _contexto_form({"modo": "publico"}))

    form = await request.form()
    if not await seguranca.conferir_csrf(request):
        flash(request, "A página expirou. Seus dados não foram enviados; preencha novamente.", "erro")
        return ir("/ficha")

    dados, erros = ficha.validar(form)
    if erros:
        valores = dict(form)
        return render(request, "membros/ficha.html",
                      _contexto_form({"modo": "publico", "valores": valores, "erros": erros}), status_code=400)

    agora = datas.agora_utc()
    usuario = seguranca.usuario_atual(request)
    with db.engine().begin() as c:
        novo_id = c.execute(insert(db.membros).values(
            **dados,
            data_registro=datas.hoje(),
            lgpd_consentimento=True,
            lgpd_versao_termo=config.VERSAO_TERMO_LGPD,
            lgpd_data_consentimento=agora,
            lgpd_ip_origem=seguranca.ip_cliente(request),
            status_lgpd="Consentimento Ativo",
            status="Aguardando Análise",
            credo_aceito=False,
            origem="novo",
            criado_em=agora, atualizado_em=agora,
        )).inserted_primary_key[0]
        if usuario and not usuario["membro_id"]:
            c.execute(update(db.usuarios).where(db.usuarios.c.id == usuario["id"]).values(membro_id=novo_id))
        auditar(request, "CADASTRO_MEMBRO", f"Membro #{novo_id}", "Pré-cadastro enviado para análise", conexao=c)

    request.session["protocolo"] = novo_id
    return ir("/ficha/recebida")


async def ficha_recebida(request: Request):
    protocolo = request.session.get("protocolo")
    if not protocolo:
        return ir("/ficha")
    return render(request, "membros/recebida.html", {"protocolo": protocolo})


# ---------------------------------------------------------------------------
# Área do membro
# ---------------------------------------------------------------------------
@seguranca.exigir()
async def minha_ficha(request: Request):
    u = seguranca.usuario_atual(request)
    if not u["membro_id"]:
        return render(request, "membros/sem_ficha.html")
    with db.engine().connect() as c:
        m = _carregar(c, u["membro_id"])
        setores = _setores_do_membro(c, u["membro_id"]) if m else []
    if not m:
        return render(request, "membros/sem_ficha.html")
    auditar(request, "VISUALIZACAO_PROPRIA_FICHA", f"Membro #{m['id']}")
    return render(request, "membros/detalhe.html", {"m": m, "setores": setores, "propria": True})


# ---------------------------------------------------------------------------
# Secretaria / Administração
# ---------------------------------------------------------------------------
@seguranca.exigir(*ADMIN_SECRETARIA)
async def lista(request: Request):
    busca = (request.query_params.get("q") or "").strip()
    status = request.query_params.get("status") or ""
    setor = request.query_params.get("setor") or ""
    q = select(db.membros.c.id, db.membros.c.nome_completo, db.membros.c.whatsapp, db.membros.c.bairro,
               db.membros.c.status, db.membros.c.data_registro, db.membros.c.credo_aceito,
               db.membros.c.data_nascimento)
    if busca:
        termo = f"%{busca.lower()}%"
        q = q.where(or_(func.lower(db.membros.c.nome_completo).like(termo),
                        func.lower(db.membros.c.email).like(termo),
                        db.membros.c.whatsapp.like(f"%{ficha.so_digitos(busca) or busca}%"),
                        func.lower(db.membros.c.bairro).like(termo)))
    if status:
        q = q.where(db.membros.c.status == status)
    if setor.isdigit():
        q = q.where(db.membros.c.id.in_(select(db.membro_setores.c.membro_id)
                                        .where(db.membro_setores.c.departamento_id == int(setor))))
    q = q.order_by(db.membros.c.nome_completo).limit(500)
    with db.engine().connect() as c:
        linhas = [dict(r) for r in c.execute(q).mappings()]
        contagem = dict(c.execute(select(db.membros.c.status, func.count()).group_by(db.membros.c.status)).all())
        deptos = [dict(r) for r in c.execute(select(db.departamentos).order_by(db.departamentos.c.nome)).mappings()]
    return render(request, "membros/lista.html", {
        "linhas": linhas, "busca": busca, "status": status, "setor": setor, "contagem": contagem,
        "STATUS": db.STATUS_MEMBRO, "deptos": deptos})


@seguranca.exigir(*ADMIN_SECRETARIA)
async def detalhe(request: Request):
    mid = request.path_params["id"]
    with db.engine().connect() as c:
        m = _carregar(c, mid)
        if not m:
            return render(request, "erro.html", {"titulo": "Não encontrado", "mensagem": "Ficha não encontrada."}, 404)
        setores = _setores_do_membro(c, mid)
        deptos = [dict(r) for r in c.execute(select(db.departamentos).order_by(db.departamentos.c.nome)).mappings()]
        login = c.execute(select(db.usuarios.c.id, db.usuarios.c.email, db.usuarios.c.perfil)
                          .where(db.usuarios.c.membro_id == mid)).mappings().first()
    auditar(request, "VISUALIZACAO_FICHA", f"Membro #{mid}")
    return render(request, "membros/detalhe.html", {
        "m": m, "setores": setores, "deptos": deptos, "login": login,
        "link_credo": _link_credo(mid), "STATUS": db.STATUS_MEMBRO,
        "senha_provisoria": request.session.pop("senha_provisoria", None)})


@seguranca.exigir(*ADMIN_SECRETARIA)
async def editar(request: Request):
    mid = request.path_params["id"]
    with db.engine().connect() as c:
        m = _carregar(c, mid)
    if not m or m["status"] == "Anonimizado (LGPD)":
        return render(request, "erro.html", {"titulo": "Indisponível", "mensagem": "Ficha não pode ser editada."}, 404)
    if request.method == "GET":
        return render(request, "membros/ficha.html", _contexto_form({"modo": "editar", "m": m, "valores": _valores_de(m)}))

    form = await request.form()
    dados, erros = ficha.validar(form, exigir_foto=False, exigir_lgpd=False)
    if not dados["foto_3x4"]:
        dados.pop("foto_3x4")  # sem nova foto: mantém a atual
    if erros:
        return render(request, "membros/ficha.html",
                      _contexto_form({"modo": "editar", "m": m, "valores": dict(form), "erros": erros}), 400)
    alterados = [k for k, v in dados.items() if m.get(k) != v and k != "foto_3x4"]
    with db.engine().begin() as c:
        c.execute(update(db.membros).where(db.membros.c.id == mid).values(**dados, atualizado_em=datas.agora_utc()))
        auditar(request, "EDICAO_FICHA", f"Membro #{mid}", "Campos: " + ", ".join(alterados), conexao=c)
    flash(request, "Ficha atualizada.")
    return ir(f"/membros/{mid}")


@seguranca.exigir(*ADMIN_SECRETARIA)
async def validar(request: Request):
    mid = request.path_params["id"]
    u = seguranca.usuario_atual(request)
    with db.engine().begin() as c:
        m = _carregar(c, mid)
        if not m:
            return ir("/membros")
        novo_status = "Ativo" if m["credo_aceito"] else "Validado pela Secretaria"
        c.execute(update(db.membros).where(db.membros.c.id == mid).values(
            status=novo_status, validado_por=u["nome"], data_validacao=datas.agora_utc()))
        auditar(request, "VALIDACAO_SECRETARIA", f"Membro #{mid}", f"Novo status: {novo_status}", conexao=c)
    flash(request, "Ficha validada. Envie agora o link do Credo ao membro." if novo_status != "Ativo"
          else "Ficha validada e membro ativo.")
    return ir(f"/membros/{mid}")


@seguranca.exigir(*ADMIN_SECRETARIA)
async def alterar_status(request: Request):
    mid = request.path_params["id"]
    form = await request.form()
    novo = form.get("status")
    if novo not in ("Ativo", "Inativo", "Aguardando Análise", "Validado pela Secretaria"):
        flash(request, "Status inválido.", "erro")
        return ir(f"/membros/{mid}")
    with db.engine().begin() as c:
        c.execute(update(db.membros).where(db.membros.c.id == mid).values(status=novo, atualizado_em=datas.agora_utc()))
        auditar(request, "ALTERACAO_STATUS", f"Membro #{mid}", f"Novo status: {novo}", conexao=c)
    flash(request, f"Status alterado para {novo}.")
    return ir(f"/membros/{mid}")


@seguranca.exigir(*ADMIN_SECRETARIA)
async def link_enviado(request: Request):
    mid = request.path_params["id"]
    with db.engine().begin() as c:
        c.execute(update(db.membros).where(db.membros.c.id == mid).values(link_credo_enviado=True))
        auditar(request, "LINK_CREDO_ENVIADO", f"Membro #{mid}", conexao=c)
    flash(request, "Envio do link registrado.")
    return ir(f"/membros/{mid}")


@seguranca.exigir(*ADMIN_SECRETARIA)
async def setores(request: Request):
    mid = request.path_params["id"]
    form = await request.form()
    ids = [int(x) for x in form.getlist("departamento_id") if str(x).isdigit()]
    with db.engine().begin() as c:
        validos = {r[0] for r in c.execute(select(db.departamentos.c.id))}
        c.execute(delete(db.membro_setores).where(db.membro_setores.c.membro_id == mid))
        for did in ids:
            if did in validos:
                funcao = form.get(f"funcao_{did}") or "Voluntário"
                c.execute(insert(db.membro_setores).values(membro_id=mid, departamento_id=did, funcao=funcao[:40]))
        auditar(request, "SETORES_MEMBRO", f"Membro #{mid}", f"Setores: {ids}", conexao=c)
    flash(request, "Setores atualizados.")
    return ir(f"/membros/{mid}")


@seguranca.exigir()
async def pdf(request: Request):
    mid = request.path_params["id"]
    u = seguranca.usuario_atual(request)
    if not _pode_ver(u, mid):
        return render(request, "erro.html", {"titulo": "Acesso restrito", "mensagem": "Você só pode baixar a sua própria ficha."}, 403)
    with db.engine().connect() as c:
        m = _carregar(c, mid)
    if not m or m["status"] == "Anonimizado (LGPD)":
        return render(request, "erro.html", {"titulo": "Indisponível", "mensagem": "Ficha indisponível."}, 404)
    auditar(request, "DOWNLOAD_PDF", f"Membro #{mid}")
    conteudo = gerar_pdf_membro(_para_pdf(m))
    return Response(conteudo, media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="Ficha_MEVAM_GYN_{mid}.pdf"',
        "Cache-Control": "no-store"})


@seguranca.exigir(*ADMIN_SECRETARIA)
async def anonimizar(request: Request):
    """LGPD art. 18: remove dados pessoais mantendo apenas o registro estatístico."""
    mid = request.path_params["id"]
    form = await request.form()
    motivo = (form.get("motivo") or "").strip()
    if len(motivo) < 10:
        flash(request, "Descreva o motivo da anonimização (mínimo 10 caracteres).", "erro")
        return ir(f"/membros/{mid}")
    vazios = {k: None for k in ("endereco", "bairro", "cep", "data_nascimento", "naturalidade", "conjuge",
                                "email", "telefone", "whatsapp", "formacao_academica", "profissao", "empresa",
                                "data_batismo", "onde_congregava", "interesse_batismo_familia",
                                "assinatura_rubrica", "foto_3x4", "ocr_documento_nome", "lgpd_ip_origem",
                                "nome_assinante", "observacoes")}
    with db.engine().begin() as c:
        c.execute(update(db.membros).where(db.membros.c.id == mid).values(
            **vazios, nome_completo=f"Titular Anonimizado #{mid}", filhos=[],
            status="Anonimizado (LGPD)", status_lgpd="Anonimizado", atualizado_em=datas.agora_utc()))
        c.execute(delete(db.membro_setores).where(db.membro_setores.c.membro_id == mid))
        c.execute(update(db.usuarios).where(db.usuarios.c.membro_id == mid).values(membro_id=None))
        auditar(request, "ANONIMIZACAO_LGPD", f"Membro #{mid}", motivo, conexao=c)
    flash(request, "Dados pessoais anonimizados conforme a LGPD.")
    return ir("/membros")


@seguranca.exigir("admin")
async def excluir(request: Request):
    mid = request.path_params["id"]
    form = await request.form()
    with db.engine().begin() as c:
        m = _carregar(c, mid)
        if not m:
            return ir("/membros")
        if (form.get("confirmacao") or "").strip() != str(mid):
            flash(request, "Para excluir, digite o número do protocolo.", "erro")
            return ir(f"/membros/{mid}")
        c.execute(update(db.usuarios).where(db.usuarios.c.membro_id == mid).values(membro_id=None))
        c.execute(delete(db.membro_setores).where(db.membro_setores.c.membro_id == mid))
        c.execute(delete(db.membros).where(db.membros.c.id == mid))
        auditar(request, "EXCLUSAO_MEMBRO", f"Membro #{mid}", f"Nome: {m['nome_completo']}", conexao=c)
    flash(request, f"Ficha #{mid} excluída.")
    return ir("/membros")


@seguranca.exigir("admin")
async def exportar_csv(request: Request):
    campos = ["id", "nome_completo", "data_nascimento", "sexo", "estado_civil", "whatsapp", "email",
              "bairro", "cidade", "batizado", "data_batismo", "status", "data_registro"]
    with db.engine().connect() as c:
        linhas = c.execute(select(*[db.membros.c[k] for k in campos])
                           .where(db.membros.c.status != "Anonimizado (LGPD)").order_by(db.membros.c.nome_completo)).all()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(campos)
    for r in linhas:
        w.writerow([datas.fmt_data(v) if k.startswith("data_") else (v if v is not None else "")
                    for k, v in zip(campos, r)])
    auditar(request, "EXPORTACAO_CSV", "Membros", f"{len(linhas)} registros")
    nome = f"membros_mevam_{datas.hoje().strftime('%d-%m-%Y')}.csv"
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nome}"', "Cache-Control": "no-store"})


# ---------------------------------------------------------------------------
# Credo e rúbrica digital (link enviado pela Secretaria)
# ---------------------------------------------------------------------------
async def credo(request: Request):
    mid = request.path_params["id"]
    if request.method == "POST":
        token = (await request.form()).get("t") or ""
    else:
        token = request.query_params.get("t") or ""
    u = seguranca.usuario_atual(request)
    autorizado = seguranca.conferir_token_link("credo", mid, token) or (u and _pode_ver(u, mid))
    if not autorizado:
        return render(request, "erro.html", {"titulo": "Link inválido",
                      "mensagem": "Este link não é válido. Peça um novo link à Secretaria."}, 403)
    with db.engine().connect() as c:
        m = _carregar(c, mid)
    if not m or m["status"] in ("Aguardando Análise", "Anonimizado (LGPD)", "Inativo"):
        return render(request, "erro.html", {"titulo": "Ainda não disponível",
                      "mensagem": "Sua ficha ainda está em análise pela Secretaria."}, 403)

    if request.method == "GET":
        return render(request, "publico/credo.html", {"m": m, "token": token})

    if not await seguranca.conferir_csrf(request):
        flash(request, "A página expirou. Assine novamente.", "erro")
        return ir(f"/credo/{mid}?t={token}")
    if m["credo_aceito"]:
        return ir(f"/credo/{mid}?t={token}")
    form = await request.form()
    assinatura = form.get("assinatura") or ""
    nome = ficha.nome_proprio(form.get("nome_assinante") or "")
    if form.get("aceite") != "sim" or not assinatura.startswith("data:image/png;base64,") or len(assinatura) > 600_000 \
            or len(nome.split()) < 2:
        flash(request, "Leia o Credo, marque o aceite, informe seu nome completo e assine no quadro.", "erro")
        return ir(f"/credo/{mid}?t={token}")
    quando = datas.agora_utc()
    ip = seguranca.ip_cliente(request)
    m["nome_assinante"] = nome
    with db.engine().begin() as c:
        c.execute(update(db.membros).where(db.membros.c.id == mid).values(
            credo_aceito=True, nome_assinante=nome, assinatura_rubrica=assinatura, data_assinatura=quando,
            hash_autenticidade=_hash_rubrica(m, assinatura, quando, ip), status="Ativo",
            atualizado_em=quando))
        auditar(request, "ACEITE_CREDO", f"Membro #{mid}", f"Assinado por {nome}", conexao=c)
    flash(request, "Assinatura registrada. Bem-vindo(a) à família MEVAM GYN!")
    return ir(f"/credo/{mid}?t={token}")


async def credo_pdf(request: Request):
    """PDF da própria ficha a partir do link seguro do Credo (o membro pode não ter login)."""
    mid = request.path_params["id"]
    if not seguranca.conferir_token_link("credo", mid, request.query_params.get("t")):
        return render(request, "erro.html", {"titulo": "Link inválido", "mensagem": "Link inválido."}, 403)
    with db.engine().connect() as c:
        m = _carregar(c, mid)
    if not m or not m["credo_aceito"] or m["status"] == "Anonimizado (LGPD)":
        return render(request, "erro.html", {"titulo": "Indisponível", "mensagem": "Ficha indisponível."}, 404)
    auditar(request, "DOWNLOAD_PDF_TITULAR", f"Membro #{mid}", usuario=None)
    return Response(gerar_pdf_membro(_para_pdf(m)), media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="Ficha_MEVAM_GYN_{mid}.pdf"', "Cache-Control": "no-store"})


def whatsapp_credo(m: dict) -> str:
    numero = ficha.so_digitos(m.get("whatsapp") or "")
    if numero and not numero.startswith("55"):
        numero = "55" + numero
    primeiro = (m.get("nome_completo") or "").split(" ")[0]
    texto = (f"Graça e Paz, {primeiro}! Sua ficha foi analisada e validada pela Secretaria do MEVAM GYN. "
             f"Acesse o link para ler a Confissão de Fé e fazer sua rúbrica digital: {_link_credo(m['id'])}")
    return f"https://wa.me/{numero}?text={quote(texto)}"


from ..web import templates  # noqa: E402

templates.env.globals["whatsapp_credo"] = whatsapp_credo

rotas = [
    Route("/ficha", ficha_publica, methods=["GET", "POST"]),
    Route("/ficha/recebida", ficha_recebida),
    Route("/minha-ficha", minha_ficha),
    Route("/membros", lista),
    Route("/membros/exportar.csv", exportar_csv),
    Route("/membros/{id:int}", detalhe),
    Route("/membros/{id:int}/editar", editar, methods=["GET", "POST"]),
    Route("/membros/{id:int}/validar", validar, methods=["POST"]),
    Route("/membros/{id:int}/status", alterar_status, methods=["POST"]),
    Route("/membros/{id:int}/link-enviado", link_enviado, methods=["POST"]),
    Route("/membros/{id:int}/setores", setores, methods=["POST"]),
    Route("/membros/{id:int}/pdf", pdf),
    Route("/membros/{id:int}/anonimizar", anonimizar, methods=["POST"]),
    Route("/membros/{id:int}/excluir", excluir, methods=["POST"]),
    Route("/credo/{id:int}", credo, methods=["GET", "POST"]),
    Route("/credo/{id:int}/pdf", credo_pdf),
]
