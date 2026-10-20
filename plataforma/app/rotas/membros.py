"""Ficha de membro, painel da Secretaria, Credo com rúbrica digital e direitos LGPD."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from html import escape
from urllib.parse import quote

from sqlalchemy import delete, func, insert, or_, select, update
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from .. import config, datas, db, envios, ficha, lembretes, profissional, seguranca
from ..pdf import gerar_pdf_membro
from ..web import auditar, flash, ir, render

ADMIN_SECRETARIA = ("secretaria", "admin")

with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "credo.json"), encoding="utf-8") as _f:
    CREDO = json.load(_f)


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------
def _carregar(c, membro_id: int) -> dict | None:
    row = c.execute(select(db.membros).where(db.membros.c.id == membro_id)).mappings().first()
    return dict(row) if row else None


def interesses_de(c, membro_id) -> list[str]:
    q = select(db.membro_interesses.c.setor).where(db.membro_interesses.c.membro_id == membro_id)
    marcados = {r[0] for r in c.execute(q)}
    return [n for n in ficha.NOMES_SETORES if n in marcados]


def salvar_interesses(c, membro_id, setores: list[str]) -> bool:
    """Grava os setores em que o membro deseja servir. Devolve True se mudou algo."""
    atuais = set(interesses_de(c, membro_id))
    novos = set(setores)
    if atuais == novos:
        return False
    if atuais - novos:
        c.execute(delete(db.membro_interesses).where(db.membro_interesses.c.membro_id == membro_id,
                                                     db.membro_interesses.c.setor.in_(list(atuais - novos))))
    for setor in sorted(novos - atuais):
        c.execute(insert(db.membro_interesses).values(membro_id=membro_id, setor=setor, criado_em=datas.agora_utc()))
    return True


def _setores_do_membro(c, membro_id: int) -> list[dict]:
    q = (select(db.membro_setores.c.departamento_id, db.membro_setores.c.funcao, db.departamentos.c.nome)
         .join(db.departamentos, db.DEP_ID == db.membro_setores.c.departamento_id)
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
    # O gerador usa valores padrão quando a chave não existe; None/"" cairiam em erro
    return {k: v for k, v in saida.items() if v not in (None, "")}


def _pode_ver(usuario: dict, membro_id: int) -> bool:
    return usuario["perfil"] in ADMIN_SECRETARIA or usuario.get("membro_id") == membro_id


def _login_da_ficha(c, membro_id) -> bool:
    return membro_id is not None and c.execute(
        select(db.usuarios.c.id).where(db.usuarios.c.membro_id == membro_id)).first() is not None


def _onde_esta_cpf(c, cpf: str | None, membro_id=None, usuario_id=None) -> dict | None:
    """Onde o CPF já está em uso por outra pessoa (ficha ou login), ou None se está livre.

    Ficha sem login e login sem ficha com o mesmo CPF são a mesma pessoa (ex.: a Secretaria informou o CPF
    em "Meu CPF" e depois cadastrou a própria ficha): não é conflito; `_ligar_pelo_cpf` faz a ligação.
    """
    if not cpf:
        return None
    sem_ficha = usuario_id is not None and membro_id is None  # login sem ficha informando o próprio CPF
    q = select(db.membros.c.id, db.membros.c.nome_completo).where(db.membros.c.cpf == cpf)
    if membro_id is not None:
        q = q.where(db.membros.c.id != membro_id)
    for outra, nome in c.execute(q).all():
        if not (sem_ficha and not _login_da_ficha(c, outra)):
            return {"tipo": "ficha", "id": outra, "nome": nome}
    q = select(db.usuarios.c.id, db.usuarios.c.membro_id, db.usuarios.c.nome, db.usuarios.c.email).where(db.usuarios.c.cpf == cpf)
    if usuario_id is not None:
        q = q.where(db.usuarios.c.id != usuario_id)
    ficha_tem_login = _login_da_ficha(c, membro_id)
    for uid, uid_membro, nome, email in c.execute(q).all():
        if membro_id is not None and uid_membro == membro_id:
            continue  # o login desta mesma ficha
        if uid_membro is None and not sem_ficha and not ficha_tem_login:
            continue  # login sem ficha da mesma pessoa: será ligado a esta ficha
        return {"tipo": "login", "id": uid, "nome": nome, "email": email, "membro_id": uid_membro}
    return None


def _cpf_em_uso(c, cpf: str | None, membro_id=None, usuario_id=None) -> bool:
    return _onde_esta_cpf(c, cpf, membro_id, usuario_id) is not None


def _conflito_para_equipe(onde: dict) -> str:
    """Mensagem para Secretaria/Adm dizendo exatamente onde o CPF está, para poderem resolver."""
    if onde["tipo"] == "ficha":
        return (f"Este CPF já está na ficha #{onde['id']} ({onde['nome']}). Abra essa ficha em Membros: "
                "se for cadastro repetido, corrija o CPF lá (ou o Adm exclui a ficha repetida).")
    ligado = f", ligado à ficha #{onde['membro_id']}" if onde["membro_id"] else ", sem ficha ligada"
    return (f"Este CPF está no login de {onde['nome']} ({onde['email']}{ligado}). Se for a mesma pessoa, "
            "o Adm liga esse login a esta ficha em Usuários › Alterar; se não for, apague o CPF desse login lá.")


def _ligar_pelo_cpf(c, cpf: str | None, membro_id=None, usuario_id=None) -> None:
    """Liga ficha e login da mesma pessoa (mesmo CPF) quando um dos dois ainda está solto."""
    if not cpf:
        return
    if membro_id is not None and not _login_da_ficha(c, membro_id):
        c.execute(update(db.usuarios).where(db.usuarios.c.cpf == cpf, db.usuarios.c.membro_id.is_(None))
                  .values(membro_id=membro_id))
    elif usuario_id is not None and membro_id is None:
        for (mid,) in c.execute(select(db.membros.c.id).where(db.membros.c.cpf == cpf)).all():
            if not _login_da_ficha(c, mid):
                c.execute(update(db.usuarios).where(db.usuarios.c.id == usuario_id).values(membro_id=mid))
                break


ERRO_CPF_REPETIDO = "Este CPF já está em outro cadastro. Se for o seu, fale com a Secretaria."


def _contexto_form(extra: dict | None = None) -> dict:
    ctx = {"ESTADOS_CIVIS": ficha.ESTADOS_CIVIS, "ESCOLARIDADES": ficha.ESCOLARIDADES,
           "SEXOS": ficha.SEXOS, "SIM_NAO": ficha.SIM_NAO, "SETORES_INTERESSE": ficha.SETORES_INTERESSE,
           "DIZIMO_OPCOES": ficha.DIZIMO_OPCOES, "DIAS_PROFISSAO": [[k, d, n] for k, d, n in profissional.DIAS],
           "valores": {}, "erros": {}, "interesses": []}
    ctx.update(extra or {})
    return ctx


def _valores_de(m: dict) -> dict:
    v = dict(m)
    v["data_nascimento"] = datas.fmt_data(m.get("data_nascimento"))
    v["data_batismo"] = datas.fmt_data(m.get("data_batismo"))
    v["cpf"] = ficha.fmt_cpf(m.get("cpf"))
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

    dados, erros = ficha.validar(form, exigir_foto=False)
    interesses = ficha.interesses_do_form(form)
    if not erros.get("cpf"):
        with db.engine().connect() as c:
            if _cpf_em_uso(c, dados["cpf"]):
                erros["cpf"] = ERRO_CPF_REPETIDO
    if erros:
        valores = dict(form)
        return render(request, "membros/ficha.html", _contexto_form(
            {"modo": "publico", "valores": valores, "erros": erros, "interesses": interesses}), status_code=400)

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
        # Liga a ficha ao login só quando é a própria pessoa (mesmo e-mail); a Secretaria pode cadastrar várias fichas seguidas
        if usuario and not usuario["membro_id"] and (dados.get("email") or "").lower() == (usuario.get("email") or "").lower():
            c.execute(update(db.usuarios).where(db.usuarios.c.id == usuario["id"]).values(membro_id=novo_id, cpf=dados["cpf"]))
        _ligar_pelo_cpf(c, dados["cpf"], membro_id=novo_id)
        salvar_interesses(c, novo_id, interesses)
        sem_foto = not dados["foto_3x4"]
        if sem_foto:
            lembretes.iniciar(c, novo_id)  # link de 30 dias para enviar a foto
        auditar(request, "CADASTRO_MEMBRO", f"Membro #{novo_id}",
                "Pré-cadastro enviado para análise" + (" (sem foto: prazo de 30 dias)" if sem_foto else ""), conexao=c)
    if dados.get("email") and envios.email_configurado():
        lembretes.boas_vindas(novo_id, sem_foto)

    request.session["protocolo"] = novo_id
    request.session["protocolo_sem_foto"] = sem_foto
    return ir("/ficha/recebida")


async def ficha_recebida(request: Request):
    protocolo = request.session.get("protocolo")
    if not protocolo:
        return ir("/ficha")
    return render(request, "membros/recebida.html", {"protocolo": protocolo,
                                                     "sem_foto": request.session.get("protocolo_sem_foto")})


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


@seguranca.exigir()
async def meu_cpf(request: Request):
    """Quem já tem cadastro (membro ou equipe) informa o próprio CPF. Correções depois: só pela Secretaria."""
    u = seguranca.usuario_atual(request)
    with db.engine().connect() as c:
        m = _carregar(c, u["membro_id"]) if u["membro_id"] else None
    atual = u.get("cpf") or (m or {}).get("cpf")
    if request.method == "GET" or atual:
        return render(request, "membros/meu_cpf.html", {"atual": atual, "valores": {}, "erros": {}})
    form = await request.form()
    cpf = ficha.so_digitos(form.get("cpf") or "")
    erro = None if ficha.cpf_valido(cpf) else ficha.ERRO_CPF
    with db.engine().begin() as c:
        if not erro and _cpf_em_uso(c, cpf, membro_id=u["membro_id"], usuario_id=u["id"]):
            erro = ERRO_CPF_REPETIDO
        if erro:
            return render(request, "membros/meu_cpf.html",
                          {"atual": None, "valores": {"cpf": form.get("cpf") or ""}, "erros": {"cpf": erro}}, 400)
        c.execute(update(db.usuarios).where(db.usuarios.c.id == u["id"]).values(cpf=cpf))
        if not m:
            _ligar_pelo_cpf(c, cpf, usuario_id=u["id"])
        if m and not m.get("cpf"):
            c.execute(update(db.membros).where(db.membros.c.id == m["id"]).values(cpf=cpf, atualizado_em=datas.agora_utc()))
        auditar(request, "CPF_INFORMADO", f"Usuário #{u['id']}" + (f" / Membro #{m['id']}" if m else ""), conexao=c)
    flash(request, "CPF registrado. Obrigado!")
    return ir("/inicio")


# ---------------------------------------------------------------------------
# Secretaria / Administração
# ---------------------------------------------------------------------------
@seguranca.exigir(*ADMIN_SECRETARIA)
async def lista(request: Request):
    """Lista de membros com filtro e ordenação pelos cabeçalhos (v2.7.0). A busca continua no topo."""
    from .. import tabelas
    from .relatorios import _membros, colunas_membros
    u = seguranca.usuario_atual(request)
    busca = (request.query_params.get("q") or "").strip()
    with db.engine().connect() as c:
        linhas = _membros(c, com_setores=True)
    contagem = {}
    for l in linhas:
        contagem[l["status"]] = contagem.get(l["status"], 0) + 1
    if busca:
        termo, dig = busca.lower(), ficha.so_digitos(busca)
        linhas = [l for l in linhas if termo in (l["nome_completo"] or "").lower() or termo in (l["email"] or "").lower()
                  or termo in (l["bairro"] or "").lower()
                  or (dig and (dig in ficha.so_digitos(l["whatsapp"] or "") or dig in (l["cpf"] or "")))]
    linhas.sort(key=lambda l: tabelas._norm(l["nome_completo"]))
    colunas = colunas_membros(u["perfil"], ("id", "nome_completo", "whatsapp", "bairro", "data_nascimento", "status"))
    estado = tabelas.ler_estado(request.query_params, colunas)
    formato = request.query_params.get("formato")
    t = tabelas.montar("/membros", linhas, colunas, estado, tudo=bool(request.query_params.get("tudo")) or formato == "csv")
    if formato == "csv":
        auditar(request, "EXPORTACAO_CSV", "Membros (lista filtrada)",
                f"{t['total']} registros · " + (" · ".join(t["filtros_texto"]) or "sem filtros"))
        nome = f"membros_mevam_{datas.hoje().strftime('%d-%m-%Y')}.csv"
        return Response(tabelas.csv_de(t), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{nome}"', "Cache-Control": "no-store"})
    status_ativo = (estado["filtros"].get("status") or {}).get("em", [])
    return render(request, "membros/lista.html", {
        "t": t, "busca": busca, "contagem": contagem, "STATUS": db.STATUS_MEMBRO,
        "status_ativo": status_ativo[0] if len(status_ativo) == 1 else "", "emitido": datas.agora()})


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
    if not m or m["status"] in (db.ANONIMIZADO, db.EXCLUIDO):
        return render(request, "erro.html", {"titulo": "Indisponível", "mensagem": "Ficha não pode ser editada."}, 404)
    if request.method == "GET":
        with db.engine().connect() as c:
            interesses = interesses_de(c, mid)
        return render(request, "membros/ficha.html", _contexto_form(
            {"modo": "editar", "m": m, "valores": _valores_de(m), "interesses": interesses}))

    form = await request.form()
    dados, erros = ficha.validar(form, exigir_foto=False, exigir_lgpd=False, exigir_cpf=False)
    interesses = ficha.interesses_do_form(form)
    if not erros.get("cpf"):
        with db.engine().connect() as c:
            onde = _onde_esta_cpf(c, dados["cpf"], membro_id=mid)
            if onde:
                erros["cpf"] = _conflito_para_equipe(onde)
    if not dados["foto_3x4"]:
        dados.pop("foto_3x4")  # sem nova foto: mantém a atual
    if erros:
        return render(request, "membros/ficha.html",
                      _contexto_form({"modo": "editar", "m": m, "valores": dict(form), "erros": erros,
                                      "interesses": interesses}), 400)
    alterados = [k for k, v in dados.items() if m.get(k) != v and k != "foto_3x4"]
    with db.engine().begin() as c:
        c.execute(update(db.membros).where(db.membros.c.id == mid).values(**dados, atualizado_em=datas.agora_utc()))
        if salvar_interesses(c, mid, interesses):
            alterados.append("ministérios de interesse")
        if "cpf" in alterados:  # o login da mesma pessoa acompanha o CPF da ficha
            c.execute(update(db.usuarios).where(db.usuarios.c.membro_id == mid).values(cpf=dados["cpf"]))
        _ligar_pelo_cpf(c, dados["cpf"], membro_id=mid)
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
    """Etapas do fluxo (Aguardando, Validado, Ativo). Inativar e excluir têm botões próprios, com justificativa."""
    mid = request.path_params["id"]
    form = await request.form()
    novo = form.get("status")
    if novo not in ("Ativo", "Aguardando Análise", "Validado pela Secretaria"):
        flash(request, "Status inválido. Para inativar, use o botão Inativar membro (com justificativa).", "erro")
        return ir(f"/membros/{mid}")
    with db.engine().begin() as c:
        m = _carregar(c, mid)
        if not m:
            return ir("/membros")
        if m["status"] in db.STATUS_FORA:
            flash(request, "Esta ficha está inativa, na lixeira ou anonimizada. Use Reativar ou Restaurar.", "erro")
            return ir(f"/membros/{mid}")
        c.execute(update(db.membros).where(db.membros.c.id == mid).values(status=novo, atualizado_em=datas.agora_utc()))
        auditar(request, "ALTERACAO_STATUS", f"Membro #{mid}", f"Novo status: {novo}", conexao=c)
    flash(request, f"Status alterado para {novo}.")
    return ir(f"/membros/{mid}")


# ---------------------------------------------------------------------------
# Inativar, reativar, excluir (lixeira), restaurar e excluir definitivamente (v2.9.0)
# Sempre com justificativa; tudo fica na auditoria. Exclusivo de Secretaria e Adm.
# ---------------------------------------------------------------------------
JUSTIFICATIVA_MINIMA = 10
PERFIS_SUSPENSOS = ("membro", "coordenacao")  # login da equipe (Secretaria/Adm) não é desligado pela ficha


def _justificativa(form) -> str | None:
    texto = (form.get("motivo") or "").strip()
    return texto[:1000] if len(texto) >= JUSTIFICATIVA_MINIMA else None


def _suspender_login(c, mid: int, por: str, motivo: str) -> int:
    """Desliga o login de Membro/Coordenação ligado à ficha e encerra as coordenações dele."""
    from .. import coordenacao
    n = 0
    for uid, perfil in c.execute(select(db.usuarios.c.id, db.usuarios.c.perfil).where(
            db.usuarios.c.membro_id == mid, db.usuarios.c.ativo.is_(True), db.usuarios.c.perfil.in_(PERFIS_SUSPENSOS))).all():
        coordenacao.encerrar_todas(c, uid, por, motivo)
        c.execute(update(db.usuarios).where(db.usuarios.c.id == uid).values(ativo=False))
        n += 1
    if n:
        c.execute(update(db.membros).where(db.membros.c.id == mid).values(login_suspenso=True))
    return n


def _religar_login(c, m: dict) -> int:
    if not m.get("login_suspenso"):
        return 0
    r = c.execute(update(db.usuarios).where(db.usuarios.c.membro_id == m["id"], db.usuarios.c.perfil.in_(PERFIS_SUSPENSOS))
                  .values(ativo=True, tentativas_falhas=0, bloqueado_ate=None))
    c.execute(update(db.membros).where(db.membros.c.id == m["id"]).values(login_suspenso=False))
    return r.rowcount or 0


def _status_de_volta(m: dict) -> str:
    anterior = m.get("status_anterior")
    if anterior in ("Ativo", "Validado pela Secretaria", "Aguardando Análise"):
        return anterior
    return "Ativo" if m.get("credo_aceito") else "Validado pela Secretaria"


@seguranca.exigir(*ADMIN_SECRETARIA)
async def inativar(request: Request):
    mid = request.path_params["id"]
    form = await request.form()
    motivo = _justificativa(form)
    u = seguranca.usuario_atual(request)
    if not motivo:
        flash(request, f"Escreva a justificativa da inativação (mínimo {JUSTIFICATIVA_MINIMA} caracteres).", "erro")
        return ir(f"/membros/{mid}#inativar")
    with db.engine().begin() as c:
        m = _carregar(c, mid)
        if not m or m["status"] in db.STATUS_FORA:
            flash(request, "Esta ficha já está fora da lista de ativos.", "erro")
            return ir(f"/membros/{mid}")
        c.execute(update(db.membros).where(db.membros.c.id == mid).values(
            status="Inativo", status_anterior=m["status"], inativado_em=datas.agora_utc(), inativado_por=u["nome"],
            motivo_inativacao=motivo, atualizado_em=datas.agora_utc()))
        n = _suspender_login(c, mid, u["nome"], "Membro inativado: " + motivo)
        auditar(request, "MEMBRO_INATIVADO", f"Membro #{mid}",
                f"{m['nome_completo']} · {motivo}" + (" · login desligado" if n else ""), conexao=c)
    flash(request, f"{m['nome_completo']} foi inativado(a)." + (" O acesso ao sistema foi desligado." if n else ""))
    return ir(f"/membros/{mid}")


@seguranca.exigir(*ADMIN_SECRETARIA)
async def reativar(request: Request):
    mid = request.path_params["id"]
    form = await request.form()
    motivo = _justificativa(form)
    if not motivo:
        flash(request, f"Escreva a justificativa da reativação (mínimo {JUSTIFICATIVA_MINIMA} caracteres).", "erro")
        return ir(f"/membros/{mid}")
    with db.engine().begin() as c:
        m = _carregar(c, mid)
        if not m or m["status"] != "Inativo":
            return ir(f"/membros/{mid}")
        volta = _status_de_volta(m)
        c.execute(update(db.membros).where(db.membros.c.id == mid).values(
            status=volta, status_anterior=None, inativado_em=None, inativado_por=None, motivo_inativacao=None,
            atualizado_em=datas.agora_utc()))
        n = _religar_login(c, m)
        auditar(request, "MEMBRO_REATIVADO", f"Membro #{mid}",
                f"{m['nome_completo']} · status {volta} · {motivo}" + (" · login religado" if n else ""), conexao=c)
    flash(request, f"{m['nome_completo']} foi reativado(a) ({volta})." + (" O acesso ao sistema voltou." if n else ""))
    return ir(f"/membros/{mid}")


@seguranca.exigir(*ADMIN_SECRETARIA)
async def excluir(request: Request):
    """Excluir = mandar para a lixeira: some das listas, relatórios e avisos, mas pode ser restaurada."""
    mid = request.path_params["id"]
    form = await request.form()
    motivo = _justificativa(form)
    u = seguranca.usuario_atual(request)
    if not motivo:
        flash(request, f"Escreva a justificativa da exclusão (mínimo {JUSTIFICATIVA_MINIMA} caracteres).", "erro")
        return ir(f"/membros/{mid}#excluir")
    if (form.get("confirmacao") or "").strip() != str(mid):
        flash(request, "Para excluir, digite o número do protocolo.", "erro")
        return ir(f"/membros/{mid}#excluir")
    with db.engine().begin() as c:
        m = _carregar(c, mid)
        if not m or m["status"] in (db.EXCLUIDO, db.ANONIMIZADO):
            return ir("/membros")
        c.execute(update(db.membros).where(db.membros.c.id == mid).values(
            status=db.EXCLUIDO, status_anterior=m["status_anterior"] if m["status"] == "Inativo" else m["status"],
            excluido_em=datas.agora_utc(), excluido_por=u["nome"], motivo_exclusao=motivo, atualizado_em=datas.agora_utc()))
        n = _suspender_login(c, mid, u["nome"], "Ficha excluída: " + motivo)
        c.execute(update(db.regularizacoes).where(db.regularizacoes.c.membro_id == mid).values(revogado=True))
        auditar(request, "MEMBRO_EXCLUIDO", f"Membro #{mid}",
                f"{m['nome_completo']} · enviado para a lixeira · {motivo}" + (" · login desligado" if n else ""), conexao=c)
    flash(request, f"Ficha #{mid} ({m['nome_completo']}) foi para a lixeira. Ela pode ser restaurada em Membros › 🗑️ Lixeira.")
    return ir("/membros")


@seguranca.exigir(*ADMIN_SECRETARIA)
async def restaurar(request: Request):
    mid = request.path_params["id"]
    form = await request.form()
    motivo = _justificativa(form)
    if not motivo:
        flash(request, f"Escreva a justificativa da restauração (mínimo {JUSTIFICATIVA_MINIMA} caracteres).", "erro")
        return ir("/membros/lixeira")
    with db.engine().begin() as c:
        m = _carregar(c, mid)
        if not m or m["status"] != db.EXCLUIDO:
            return ir("/membros/lixeira")
        # Se estava inativa antes da exclusão, volta inativa
        volta = "Inativo" if m.get("inativado_em") else _status_de_volta(m)
        c.execute(update(db.membros).where(db.membros.c.id == mid).values(
            status=volta, excluido_em=None, excluido_por=None, motivo_exclusao=None, atualizado_em=datas.agora_utc(),
            **({} if volta == "Inativo" else {"status_anterior": None})))
        n = 0 if volta == "Inativo" else _religar_login(c, m)
        auditar(request, "MEMBRO_RESTAURADO", f"Membro #{mid}", f"{m['nome_completo']} · status {volta} · {motivo}", conexao=c)
    flash(request, f"Ficha #{mid} restaurada ({volta})." + (" O acesso ao sistema voltou." if n else ""))
    return ir(f"/membros/{mid}")


@seguranca.exigir(*ADMIN_SECRETARIA)
async def lixeira(request: Request):
    m = db.membros.c
    with db.engine().connect() as c:
        linhas = [dict(r) for r in c.execute(
            select(m.id, m.nome_completo, m.excluido_em, m.excluido_por, m.motivo_exclusao)
            .where(m.status == db.EXCLUIDO).order_by(m.excluido_em.desc())).mappings()]
    hoje = datas.hoje()
    for l in linhas:
        quando = l["excluido_em"]
        l["dias"] = (hoje - quando.date()).days if quando else None
    return render(request, "membros/lixeira.html", {"linhas": linhas})


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
    ids = [str(x) for x in form.getlist("departamento_id") if x]
    with db.engine().begin() as c:
        validos = {str(r[0]) for r in c.execute(select(db.departamentos.c.id))}
        c.execute(delete(db.membro_setores).where(db.membro_setores.c.membro_id == mid))
        for did in ids:
            if did in validos:
                funcao = form.get(f"funcao_{did}") or "Voluntário"
                c.execute(insert(db.membro_setores).values(membro_id=mid, departamento_id=did, funcao=funcao[:40]))
        auditar(request, "SETORES_MEMBRO", f"Membro #{mid}", f"Ministérios: {ids}", conexao=c)
    flash(request, "Ministérios atualizados.")
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
                                "nome_assinante", "observacoes", "cpf", "ficha_escaneada")}
    with db.engine().begin() as c:
        c.execute(update(db.membros).where(db.membros.c.id == mid).values(
            **vazios, nome_completo=f"Titular Anonimizado #{mid}", filhos=[],
            status="Anonimizado (LGPD)", status_lgpd="Anonimizado", atualizado_em=datas.agora_utc()))
        c.execute(delete(db.membro_setores).where(db.membro_setores.c.membro_id == mid))
        c.execute(delete(db.membro_interesses).where(db.membro_interesses.c.membro_id == mid))
        c.execute(update(db.regularizacoes).where(db.regularizacoes.c.membro_id == mid).values(revogado=True))
        c.execute(update(db.usuarios).where(db.usuarios.c.membro_id == mid).values(membro_id=None, cpf=None))
        auditar(request, "ANONIMIZACAO_LGPD", f"Membro #{mid}", motivo, conexao=c)
    flash(request, "Dados pessoais anonimizados conforme a LGPD.")
    return ir("/membros")


@seguranca.exigir("admin")
async def excluir_definitivo(request: Request):
    """Só o Adm e só a partir da lixeira: apaga a ficha de vez (fica na auditoria o nome e a justificativa)."""
    mid = request.path_params["id"]
    form = await request.form()
    motivo = _justificativa(form)
    if not motivo:
        flash(request, f"Escreva a justificativa da exclusão definitiva (mínimo {JUSTIFICATIVA_MINIMA} caracteres).", "erro")
        return ir("/membros/lixeira")
    with db.engine().begin() as c:
        m = _carregar(c, mid)
        if not m:
            return ir("/membros/lixeira")
        if m["status"] != db.EXCLUIDO:
            flash(request, "Só uma ficha que está na lixeira pode ser excluída definitivamente.", "erro")
            return ir(f"/membros/{mid}")
        if (form.get("confirmacao") or "").strip() != str(mid):
            flash(request, "Para excluir definitivamente, digite o número do protocolo.", "erro")
            return ir("/membros/lixeira")
        c.execute(update(db.usuarios).where(db.usuarios.c.membro_id == mid).values(membro_id=None))
        for t in (db.membro_setores, db.regularizacoes, db.membro_interesses, db.lembretes_cadastro,
                  db.pesquisa_satisfacao, db.avisos, db.aniversario_envios):
            c.execute(delete(t).where(t.c.membro_id == mid))
        c.execute(update(db.inscricoes).where(db.inscricoes.c.membro_id == mid).values(membro_id=None))
        c.execute(delete(db.membros).where(db.membros.c.id == mid))
        auditar(request, "EXCLUSAO_DEFINITIVA_MEMBRO", f"Membro #{mid}",
                f"Nome: {m['nome_completo']} · excluída por {m.get('excluido_por') or '-'} ({m.get('motivo_exclusao') or '-'}) · {motivo}",
                conexao=c)
    flash(request, f"Ficha #{mid} excluída definitivamente.")
    return ir("/membros/lixeira")


@seguranca.exigir("admin")
async def exportar_csv(request: Request):
    campos = ["id", "nome_completo", "data_nascimento", "sexo", "estado_civil", "whatsapp", "email",
              "bairro", "cidade", "batizado", "data_batismo", "status", "data_registro"]
    with db.engine().connect() as c:
        linhas = c.execute(select(*[db.membros.c[k] for k in campos])
                           .where(db.membros.c.status.notin_((db.ANONIMIZADO, db.EXCLUIDO))).order_by(db.membros.c.nome_completo)).all()
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
    if not m or m["status"] in ("Aguardando Análise",) + db.STATUS_FORA:
        return render(request, "erro.html", {"titulo": "Ainda não disponível",
                      "mensagem": "Sua ficha ainda está em análise pela Secretaria."}, 403)

    if request.method == "GET":
        return render(request, "publico/credo.html", {"m": m, "token": token, "credo": CREDO})

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
    if not m or not m["credo_aceito"] or m["status"] in (db.ANONIMIZADO, db.EXCLUIDO):
        return render(request, "erro.html", {"titulo": "Indisponível", "mensagem": "Ficha indisponível."}, 404)
    auditar(request, "DOWNLOAD_PDF_TITULAR", f"Membro #{mid}", usuario=None)
    return Response(gerar_pdf_membro(_para_pdf(m)), media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="Ficha_MEVAM_GYN_{mid}.pdf"', "Cache-Control": "no-store"})


def whatsapp_credo(m: dict) -> str:
    numero = ficha.so_digitos(m.get("whatsapp") or "")
    if numero and not numero.startswith("55"):
        numero = "55" + numero
    primeiro = (m.get("nome_completo") or "").split(" ")[0]
    texto = (f"Paz, {primeiro}! Sua ficha foi analisada e validada pela Secretaria do MEVAM GYN. "
             f"Acesse o link para ler a Confissão de Fé e fazer sua rúbrica digital: {_link_credo(m['id'])}")
    return f"https://wa.me/{numero}?text={quote(texto)}"


from ..web import templates  # noqa: E402

templates.env.globals["whatsapp_credo"] = whatsapp_credo

rotas = [
    Route("/ficha", ficha_publica, methods=["GET", "POST"]),
    Route("/ficha/recebida", ficha_recebida),
    Route("/minha-ficha", minha_ficha),
    Route("/meu-cpf", meu_cpf, methods=["GET", "POST"]),
    Route("/membros", lista),
    Route("/membros/exportar.csv", exportar_csv),
    Route("/membros/lixeira", lixeira),
    Route("/membros/{id:int}", detalhe),
    Route("/membros/{id:int}/editar", editar, methods=["GET", "POST"]),
    Route("/membros/{id:int}/validar", validar, methods=["POST"]),
    Route("/membros/{id:int}/status", alterar_status, methods=["POST"]),
    Route("/membros/{id:int}/link-enviado", link_enviado, methods=["POST"]),
    Route("/membros/{id:int}/setores", setores, methods=["POST"]),
    Route("/membros/{id:int}/pdf", pdf),
    Route("/membros/{id:int}/anonimizar", anonimizar, methods=["POST"]),
    Route("/membros/{id:int}/inativar", inativar, methods=["POST"]),
    Route("/membros/{id:int}/reativar", reativar, methods=["POST"]),
    Route("/membros/{id:int}/excluir", excluir, methods=["POST"]),
    Route("/membros/{id:int}/restaurar", restaurar, methods=["POST"]),
    Route("/membros/{id:int}/excluir-definitivo", excluir_definitivo, methods=["POST"]),
    Route("/credo/{id:int}", credo, methods=["GET", "POST"]),
    Route("/credo/{id:int}/pdf", credo_pdf),
]
