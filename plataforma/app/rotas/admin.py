"""Administração: usuários e perfis, setores (departamentos) e trilha de auditoria."""

from __future__ import annotations

from sqlalchemy import delete, func, insert, or_, select, update
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request
from starlette.routing import Route

from .. import datas, db, ficha, seguranca
from ..web import auditar, flash, ir, render


def _admins_ativos(c, exceto: int | None = None) -> int:
    q = select(func.count()).select_from(db.usuarios).where(db.usuarios.c.perfil == "admin",
                                                            db.usuarios.c.ativo.is_(True))
    if exceto:
        q = q.where(db.usuarios.c.id != exceto)
    return c.execute(q).scalar() or 0


def _mostrar_senha_uma_vez(request: Request, nome: str, email: str, senha: str) -> None:
    request.session["senha_provisoria"] = {"nome": nome, "email": email, "senha": senha}


def criar_usuario(c, nome: str, email: str, perfil: str, membro_id: int | None = None,
                  senha: str | None = None, origem: str = "novo") -> tuple[int, str]:
    senha = senha or seguranca.senha_temporaria()
    h, s, it = seguranca.hash_senha(senha)
    uid = c.execute(insert(db.usuarios).values(
        nome=ficha.nome_proprio(nome), email=email.strip().lower(), senha_hash=h, salt=s, iteracoes=it,
        perfil=perfil, ativo=True, trocar_senha=True, membro_id=membro_id, origem=origem,
        tentativas_falhas=0, criado_em=datas.agora_utc())).inserted_primary_key[0]
    return uid, senha


# ---------------------------------------------------------------------------
# Usuários
# ---------------------------------------------------------------------------
@seguranca.exigir("admin")
async def usuarios(request: Request):
    busca = (request.query_params.get("q") or "").strip().lower()
    q = (select(db.usuarios.c.id, db.usuarios.c.nome, db.usuarios.c.email, db.usuarios.c.perfil,
                db.usuarios.c.ativo, db.usuarios.c.ultimo_login, db.usuarios.c.trocar_senha,
                db.usuarios.c.membro_id, db.membros.c.nome_completo.label("membro_nome"))
         .select_from(db.usuarios.outerjoin(db.membros, db.membros.c.id == db.usuarios.c.membro_id))
         .order_by(db.usuarios.c.nome))
    if busca:
        q = q.where(or_(func.lower(db.usuarios.c.nome).like(f"%{busca}%"),
                        func.lower(db.usuarios.c.email).like(f"%{busca}%")))
    with db.engine().connect() as c:
        linhas = [dict(r) for r in c.execute(q).mappings()]
    return render(request, "admin/usuarios.html", {"linhas": linhas, "busca": busca, "PERFIS": db.PERFIS,
                                                   "senha_provisoria": request.session.pop("senha_provisoria", None)})


@seguranca.exigir("admin")
async def novo_usuario(request: Request):
    form = await request.form()
    nome = (form.get("nome") or "").strip()
    email = (form.get("email") or "").strip().lower()
    perfil = form.get("perfil") if form.get("perfil") in db.PERFIS else "membro"
    if len(nome.split()) < 2 or "@" not in email:
        flash(request, "Informe nome completo e um e-mail válido.", "erro")
        return ir("/admin/usuarios")
    try:
        with db.engine().begin() as c:
            membro = c.execute(select(db.membros.c.id).where(func.lower(db.membros.c.email) == email)).first()
            uid, senha = criar_usuario(c, nome, email, perfil, membro_id=membro[0] if membro else None)
            auditar(request, "USUARIO_CRIADO", f"Usuário #{uid}", f"{email} / perfil {perfil}", conexao=c)
    except IntegrityError:
        flash(request, "Já existe um usuário com este e-mail.", "erro")
        return ir("/admin/usuarios")
    _mostrar_senha_uma_vez(request, nome, email, senha)
    return ir("/admin/usuarios")


@seguranca.exigir("admin")
async def alterar_usuario(request: Request):
    uid = request.path_params["id"]
    form = await request.form()
    eu = seguranca.usuario_atual(request)
    perfil = form.get("perfil")
    ativo = form.get("ativo") == "sim"
    with db.engine().begin() as c:
        alvo = c.execute(select(db.usuarios).where(db.usuarios.c.id == uid)).mappings().first()
        if not alvo or perfil not in db.PERFIS:
            flash(request, "Dados inválidos.", "erro")
            return ir("/admin/usuarios")
        perde_admin = alvo["perfil"] == "admin" and (perfil != "admin" or not ativo)
        if perde_admin and _admins_ativos(c, exceto=uid) == 0:
            flash(request, "O sistema precisa de pelo menos um Adm ativo.", "erro")
            return ir("/admin/usuarios")
        if uid == eu["id"] and perde_admin:
            flash(request, "Você não pode remover o seu próprio acesso de Adm.", "erro")
            return ir("/admin/usuarios")
        c.execute(update(db.usuarios).where(db.usuarios.c.id == uid).values(perfil=perfil, ativo=ativo))
        if perfil != "coordenacao":
            c.execute(delete(db.usuario_setores).where(db.usuario_setores.c.usuario_id == uid))
        auditar(request, "USUARIO_ALTERADO", f"Usuário #{uid}",
                f"Perfil {alvo['perfil']} → {perfil}; ativo {alvo['ativo']} → {ativo}", conexao=c)
    flash(request, "Usuário atualizado.")
    return ir("/admin/usuarios")


@seguranca.exigir("admin")
async def redefinir_senha(request: Request):
    uid = request.path_params["id"]
    senha = seguranca.senha_temporaria()
    h, s, it = seguranca.hash_senha(senha)
    with db.engine().begin() as c:
        alvo = c.execute(select(db.usuarios).where(db.usuarios.c.id == uid)).mappings().first()
        if not alvo:
            return ir("/admin/usuarios")
        c.execute(update(db.usuarios).where(db.usuarios.c.id == uid).values(
            senha_hash=h, salt=s, iteracoes=it, trocar_senha=True, tentativas_falhas=0, bloqueado_ate=None))
        auditar(request, "SENHA_REDEFINIDA", f"Usuário #{uid}", conexao=c)
    _mostrar_senha_uma_vez(request, alvo["nome"], alvo["email"], senha)
    return ir("/admin/usuarios")


@seguranca.exigir("secretaria", "admin")
async def criar_acesso_membro(request: Request):
    """A Secretaria cria o login (perfil Membro) a partir da ficha validada."""
    mid = request.path_params["id"]
    with db.engine().begin() as c:
        m = c.execute(select(db.membros).where(db.membros.c.id == mid)).mappings().first()
        if not m or not m["email"]:
            flash(request, "A ficha precisa ter e-mail para criar o acesso.", "erro")
            return ir(f"/membros/{mid}")
        if m["status"] == "Aguardando Análise":
            flash(request, "Valide a ficha antes de criar o acesso.", "erro")
            return ir(f"/membros/{mid}")
        existe = c.execute(select(db.usuarios.c.id).where(func.lower(db.usuarios.c.email) == m["email"].lower())).first()
        if existe:
            c.execute(update(db.usuarios).where(db.usuarios.c.id == existe[0]).values(membro_id=mid))
            flash(request, "Já existia um login com este e-mail. Ele foi vinculado a esta ficha.")
            return ir(f"/membros/{mid}")
        uid, senha = criar_usuario(c, m["nome_completo"], m["email"], "membro", membro_id=mid)
        auditar(request, "USUARIO_CRIADO", f"Usuário #{uid}", f"Acesso de membro para ficha #{mid}", conexao=c)
    request.session["senha_provisoria"] = {"nome": m["nome_completo"], "email": m["email"], "senha": senha}
    return ir(f"/membros/{mid}")


# ---------------------------------------------------------------------------
# Coordenação: Secretaria ou Adm definem quem coordena e quais setores
# ---------------------------------------------------------------------------
def _usuario(c, uid: int):
    return c.execute(select(db.usuarios).where(db.usuarios.c.id == uid)).mappings().first()


@seguranca.exigir("secretaria", "admin")
async def coordenacao(request: Request):
    with db.engine().connect() as c:
        deptos = [dict(r) for r in c.execute(select(db.departamentos).order_by(db.departamentos.c.nome)).mappings()]
        coords = [dict(r) for r in c.execute(
            select(db.usuarios.c.id, db.usuarios.c.nome, db.usuarios.c.email, db.usuarios.c.ativo)
            .where(db.usuarios.c.perfil == "coordenacao").order_by(db.usuarios.c.nome)).mappings()]
        vinculos = c.execute(select(db.usuario_setores.c.usuario_id, db.usuario_setores.c.departamento_id)).all()
        candidatos = [dict(r) for r in c.execute(
            select(db.usuarios.c.id, db.usuarios.c.nome, db.usuarios.c.email)
            .where(db.usuarios.c.perfil == "membro", db.usuarios.c.ativo.is_(True))
            .order_by(db.usuarios.c.nome)).mappings()]
    for u in coords:
        u["setores"] = {d for uid, d in vinculos if uid == u["id"]}
    return render(request, "admin/coordenacao.html", {"deptos": deptos, "coords": coords, "candidatos": candidatos})


@seguranca.exigir("secretaria", "admin")
async def adicionar_coordenador(request: Request):
    form = await request.form()
    uid = int(form.get("usuario_id") or 0) if str(form.get("usuario_id") or "").isdigit() else 0
    with db.engine().begin() as c:
        alvo = _usuario(c, uid)
        if not alvo or alvo["perfil"] != "membro":
            flash(request, "Escolha um usuário com perfil Membro.", "erro")
            return ir("/coordenacao")
        c.execute(update(db.usuarios).where(db.usuarios.c.id == uid).values(perfil="coordenacao"))
        auditar(request, "USUARIO_ALTERADO", f"Usuário #{uid}", "Perfil membro → coordenacao", conexao=c)
    flash(request, f"{alvo['nome']} agora é Coordenação. Marque abaixo os setores que vai gerenciar.")
    return ir(f"/coordenacao#u{uid}")


@seguranca.exigir("secretaria", "admin")
async def salvar_setores_coordenador(request: Request):
    uid = request.path_params["id"]
    form = await request.form()
    escolhidos = {int(x) for x in form.getlist("setores") if str(x).isdigit()}
    with db.engine().begin() as c:
        alvo = _usuario(c, uid)
        if not alvo or alvo["perfil"] != "coordenacao":
            flash(request, "Este usuário não é da Coordenação.", "erro")
            return ir("/coordenacao")
        validos = set(c.execute(select(db.departamentos.c.id)).scalars())
        escolhidos &= validos
        c.execute(delete(db.usuario_setores).where(db.usuario_setores.c.usuario_id == uid))
        for d in sorted(escolhidos):
            c.execute(insert(db.usuario_setores).values(usuario_id=uid, departamento_id=d))
        nomes = c.execute(select(db.departamentos.c.nome).where(db.departamentos.c.id.in_(escolhidos))
                          .order_by(db.departamentos.c.nome)).scalars().all() if escolhidos else []
        auditar(request, "COORDENACAO_SETORES", f"Usuário #{uid}", ", ".join(nomes) or "nenhum setor", conexao=c)
    flash(request, f"Setores de {alvo['nome']} atualizados.")
    return ir(f"/coordenacao#u{uid}")


@seguranca.exigir("secretaria", "admin")
async def remover_coordenador(request: Request):
    uid = request.path_params["id"]
    with db.engine().begin() as c:
        alvo = _usuario(c, uid)
        if not alvo or alvo["perfil"] != "coordenacao":
            return ir("/coordenacao")
        c.execute(delete(db.usuario_setores).where(db.usuario_setores.c.usuario_id == uid))
        c.execute(update(db.usuarios).where(db.usuarios.c.id == uid).values(perfil="membro"))
        auditar(request, "USUARIO_ALTERADO", f"Usuário #{uid}", "Perfil coordenacao → membro", conexao=c)
    flash(request, f"{alvo['nome']} voltou a ser Membro.")
    return ir("/coordenacao")


# ---------------------------------------------------------------------------
# Setores (tabela 'departamentos' da Agenda)
# ---------------------------------------------------------------------------
@seguranca.exigir("admin")
async def setores(request: Request):
    with db.engine().connect() as c:
        linhas = [dict(r) for r in c.execute(
            select(db.departamentos, func.count(db.membro_setores.c.id).label("qtd"))
            .select_from(db.departamentos.outerjoin(db.membro_setores,
                                                    db.membro_setores.c.departamento_id == db.departamentos.c.id))
            .group_by(*db.departamentos.c).order_by(db.departamentos.c.nome)).mappings()]
    return render(request, "admin/setores.html", {"linhas": linhas})


@seguranca.exigir("admin")
async def salvar_setor(request: Request):
    form = await request.form()
    nome = (form.get("nome") or "").strip()
    responsavel = (form.get("responsavel") or "").strip()
    sid = form.get("id")
    if len(nome) < 2:
        flash(request, "Informe o nome do setor.", "erro")
        return ir("/admin/setores")
    with db.engine().begin() as c:
        if sid and sid.isdigit():
            antigo = c.execute(select(db.departamentos.c.nome).where(db.departamentos.c.id == int(sid))).scalar()
            c.execute(update(db.departamentos).where(db.departamentos.c.id == int(sid))
                      .values(nome=nome, responsavel=responsavel))
            if antigo and antigo != nome:
                # Os eventos guardam o nome do departamento: renomeia junto para não perder o vínculo
                c.execute(update(db.eventos).where(db.eventos.c.departamento == antigo).values(departamento=nome))
            auditar(request, "SETOR_ALTERADO", f"Setor #{sid}", f"{antigo} → {nome}", conexao=c)
        else:
            novo = c.execute(insert(db.departamentos).values(nome=nome, responsavel=responsavel)).inserted_primary_key[0]
            auditar(request, "SETOR_CRIADO", f"Setor #{novo}", nome, conexao=c)
    flash(request, "Setor salvo.")
    return ir("/admin/setores")


@seguranca.exigir("admin")
async def excluir_setor(request: Request):
    sid = request.path_params["id"]
    with db.engine().begin() as c:
        nome = c.execute(select(db.departamentos.c.nome).where(db.departamentos.c.id == sid)).scalar()
        usados = c.execute(select(func.count()).select_from(db.eventos).where(db.eventos.c.departamento == nome)).scalar()
        if usados:
            flash(request, f"O setor {nome} tem {usados} evento(s) na agenda e não pode ser excluído.", "erro")
            return ir("/admin/setores")
        c.execute(delete(db.membro_setores).where(db.membro_setores.c.departamento_id == sid))
        c.execute(delete(db.usuario_setores).where(db.usuario_setores.c.departamento_id == sid))
        c.execute(delete(db.departamentos).where(db.departamentos.c.id == sid))
        auditar(request, "SETOR_EXCLUIDO", f"Setor #{sid}", nome or "", conexao=c)
    flash(request, "Setor excluído.")
    return ir("/admin/setores")


# ---------------------------------------------------------------------------
# Auditoria
# ---------------------------------------------------------------------------
@seguranca.exigir("admin")
async def auditoria(request: Request):
    busca = (request.query_params.get("q") or "").strip().lower()
    q = select(db.auditoria).order_by(db.auditoria.c.id.desc()).limit(300)
    if busca:
        termo = f"%{busca}%"
        q = q.where(or_(func.lower(db.auditoria.c.acao).like(termo), func.lower(db.auditoria.c.usuario_nome).like(termo),
                        func.lower(db.auditoria.c.recurso).like(termo), func.lower(db.auditoria.c.detalhes).like(termo)))
    with db.engine().connect() as c:
        linhas = [dict(r) for r in c.execute(q).mappings()]
    return render(request, "admin/auditoria.html", {"linhas": linhas, "busca": busca})


rotas = [
    Route("/admin/usuarios", usuarios),
    Route("/admin/usuarios/novo", novo_usuario, methods=["POST"]),
    Route("/admin/usuarios/{id:int}", alterar_usuario, methods=["POST"]),
    Route("/admin/usuarios/{id:int}/senha", redefinir_senha, methods=["POST"]),
    Route("/membros/{id:int}/criar-acesso", criar_acesso_membro, methods=["POST"]),
    Route("/coordenacao", coordenacao),
    Route("/coordenacao/adicionar", adicionar_coordenador, methods=["POST"]),
    Route("/coordenacao/{id:int}", salvar_setores_coordenador, methods=["POST"]),
    Route("/coordenacao/{id:int}/remover", remover_coordenador, methods=["POST"]),
    Route("/admin/setores", setores),
    Route("/admin/setores/salvar", salvar_setor, methods=["POST"]),
    Route("/admin/setores/{id:int}/excluir", excluir_setor, methods=["POST"]),
    Route("/admin/auditoria", auditoria),
]
