"""Coordenação (v2.9.0): Secretaria ou Adm designam, editam e encerram coordenadores por setor.

Quem pode ser designado: Membro, Secretaria ou Adm (com login ativo), ou uma ficha validada com e-mail
que ainda não tem login (o acesso é criado na hora). Regras em app/coordenacao.py.
"""

from __future__ import annotations

import threading

from sqlalchemy import func, insert, select, update
from starlette.requests import Request
from starlette.routing import Route

from .. import config, coordenacao as coord, datas, db, envios, ficha, seguranca
from ..web import auditar, flash, ir, render
from .admin import _mostrar_senha_uma_vez, criar_usuario

SEC_ADM = ("secretaria", "admin")
FICHA_APTA = ("Ativo", "Validado pela Secretaria")


def _numero(v) -> int:
    v = str(v or "").strip()
    return int(v) if v.isdigit() else 0


def _ficha_de(c, usuario: dict) -> dict | None:
    if not usuario.get("membro_id"):
        return None
    return c.execute(select(db.membros.c.id, db.membros.c.status, db.membros.c.nome_completo)
                     .where(db.membros.c.id == usuario["membro_id"])).mappings().first()


def _fichas_sem_login(c) -> list[dict]:
    m = db.membros.c
    com_login = select(db.usuarios.c.membro_id).where(db.usuarios.c.membro_id.isnot(None))
    emails = {e.lower() for e in c.execute(select(db.usuarios.c.email)).scalars() if e}
    linhas = [dict(r) for r in c.execute(
        select(m.id, m.nome_completo, m.email).where(m.status.in_(FICHA_APTA), m.email.isnot(None),
                                                     m.id.notin_(com_login)).order_by(m.nome_completo)).mappings()]
    return [l for l in linhas if l["email"] and l["email"].strip().lower() not in emails]


def _eventos_futuros(c) -> list[dict]:
    hoje_iso = db.data_evento(f"{datas.hoje().isoformat()}T00:00:00")
    linhas = []
    for r in c.execute(select(db.eventos.c.id, db.eventos.c.titulo, db.eventos.c.data_inicio, db.eventos.c.departamento)
                       .where(db.eventos.c.data_inicio >= hoje_iso).order_by(db.eventos.c.data_inicio).limit(200)).mappings():
        e = dict(r)
        e["quando"] = datas.parse_data_hora_local(e["data_inicio"])
        linhas.append(e)
    return linhas


@seguranca.exigir(*SEC_ADM)
async def tela(request: Request):
    coord.encerrar_vencidas()
    hoje = datas.hoje()
    us = db.usuario_setores.c
    with db.engine().connect() as c:
        deptos = [dict(r) for r in c.execute(select(db.departamentos).order_by(db.departamentos.c.nome)).mappings()]
        nome_setor = {str(d["id"]): d["nome"] for d in deptos}
        eventos = _eventos_futuros(c)
        titulo_evento = {str(e["id"]): e for e in eventos}
        linhas = [dict(r) for r in c.execute(
            select(db.usuario_setores, db.usuarios.c.nome, db.usuarios.c.email, db.usuarios.c.perfil,
                   db.usuarios.c.ativo.label("login_ativo"))
            .join(db.usuarios, db.usuarios.c.id == us.usuario_id)
            .order_by(db.usuarios.c.nome)).mappings()]
        # Perfil Coordenação sem nenhuma designação (ex.: definido antes da v2.9.0 ou em Usuários)
        sem_setor = [dict(r) for r in c.execute(
            select(db.usuarios.c.id, db.usuarios.c.nome, db.usuarios.c.email, db.usuarios.c.ativo)
            .where(db.usuarios.c.perfil == "coordenacao", db.usuarios.c.id.notin_(select(us.usuario_id)))
            .order_by(db.usuarios.c.nome)).mappings()]
        usuarios = [dict(r) for r in c.execute(
            select(db.usuarios.c.id, db.usuarios.c.nome, db.usuarios.c.email, db.usuarios.c.perfil)
            .where(db.usuarios.c.ativo.is_(True)).order_by(db.usuarios.c.nome)).mappings()]
        fichas = _fichas_sem_login(c)
        historico = [dict(r) for r in c.execute(
            select(db.coordenacoes_historico).order_by(db.coordenacoes_historico.c.encerrado_em.desc()).limit(40)).mappings()]
    pessoas: dict[int, dict] = {}
    for l in linhas:
        l["setor"] = nome_setor.get(str(l["departamento_id"]), "Ministério removido")
        l["situacao"], l["classe"] = coord.situacao(l, hoje)
        l["evento"] = titulo_evento.get(str(l["evento_id"])) if l.get("evento_id") else None
        p = pessoas.setdefault(l["usuario_id"], {"id": l["usuario_id"], "nome": l["nome"], "email": l["email"],
                                                 "perfil": l["perfil"], "ativo": l["login_ativo"], "designacoes": []})
        p["designacoes"].append(l)
    return render(request, "admin/coordenacao.html", {
        "deptos": deptos, "pessoas": list(pessoas.values()), "sem_setor": sem_setor, "usuarios": usuarios,
        "fichas": fichas, "eventos": eventos, "historico": historico, "TIPOS": coord.TIPOS,
        "CRITERIOS": coord.CRITERIOS, "DIRETRIZES": coord.DIRETRIZES, "hoje": hoje,
        "senha_provisoria": request.session.pop("senha_provisoria", None)})


def _avisar(destino: dict, setor: str, tipo: str, inicio, fim, evento: dict | None, por: str) -> None:
    if not destino.get("email") or not envios.email_configurado():
        return
    primeiro = (destino.get("nome") or "").split(" ")[0]
    if tipo == "evento" and evento:
        prazo = f"para o evento \"{evento['titulo']}\" ({evento['quando'].strftime('%d/%m/%Y')})"
    elif tipo == "periodo":
        prazo = f"de {inicio.strftime('%d/%m/%Y')} a {fim.strftime('%d/%m/%Y')}"
    else:
        prazo = f"a partir de {inicio.strftime('%d/%m/%Y')}, até nova decisão"
    corpo = (f"Paz, {primeiro}!\n\nVocê foi designado(a) para a Coordenação do ministério {setor}, {prazo}.\n\n"
             "Diretrizes da função:\n" + "\n".join(f"• {d}" for d in coord.DIRETRIZES) +
             f"\n\nEntre no sistema: {config.URL_BASE}/entrar\n"
             f"O Manual da Coordenação explica cada passo.\n\nDesignado por {por}.\nMinistério MEVAM GYN")

    def tarefa():
        erro = envios.enviar_email(destino["email"], f"Coordenação do ministério {setor} · MEVAM GYN", corpo)
        auditar(None, "EMAIL_COORDENACAO", f"Usuário #{destino['id']}", erro or "enviado",
                usuario={"id": None, "nome": "Sistema"})
    if config.ENVIO_SINCRONO:
        tarefa()
    else:
        threading.Thread(target=tarefa, daemon=True).start()


def _ler_prazo(c, form, setor_nome: str):
    tipo = form.get("tipo") or "permanente"
    inicio = datas.parse_data(form.get("inicio")) if (form.get("inicio") or "").strip() else None
    fim = datas.parse_data(form.get("fim")) if (form.get("fim") or "").strip() else None
    if (form.get("inicio") or "").strip() and not inicio:
        return None, None, None, None, "Data de início inválida. Use dd/mm/aaaa."
    if (form.get("fim") or "").strip() and not fim:
        return None, None, None, None, "Data de término inválida. Use dd/mm/aaaa."
    evento = coord._evento(c, form.get("evento_id")) if tipo == "evento" else None
    if evento and evento.get("departamento") != setor_nome:
        return None, None, None, None, f"O evento escolhido não é do ministério {setor_nome}."
    inicio, fim, erro = coord.validar_prazo(tipo, inicio, fim, evento)
    return tipo, inicio, fim, evento, erro


@seguranca.exigir(*SEC_ADM)
async def designar(request: Request):
    form = await request.form()
    eu = seguranca.usuario_atual(request)
    pessoa = (form.get("pessoa") or "").strip()
    dep = (form.get("departamento_id") or "").strip()
    observacao = (form.get("observacao") or "").strip()[:500]
    if form.get("disponibilidade") != "sim":
        flash(request, "Confirme que a pessoa se disponibilizou a servir no ministério. É um dos critérios da Coordenação.", "erro")
        return ir("/coordenacao#designar")
    senha_nova = None
    with db.engine().begin() as c:
        setor = c.execute(select(db.departamentos.c.nome).where(db.DEP_ID == dep)).scalar() if dep else None
        if not setor:
            flash(request, "Escolha o ministério.", "erro")
            return ir("/coordenacao#designar")
        tipo, inicio, fim, evento, erro = _ler_prazo(c, form, setor)
        if erro:
            flash(request, erro, "erro")
            return ir("/coordenacao#designar")
        if pessoa.startswith("m:"):
            # Ficha validada sem login: cria o acesso de Membro e designa
            mid = _numero(pessoa[2:])
            m = c.execute(select(db.membros).where(db.membros.c.id == mid)).mappings().first()
            if not m or m["status"] not in FICHA_APTA or not m["email"]:
                flash(request, "A ficha precisa estar validada e ter e-mail.", "erro")
                return ir("/coordenacao#designar")
            existe = c.execute(select(db.usuarios.c.id).where(func.lower(db.usuarios.c.email) == m["email"].strip().lower())).scalar()
            if existe:
                uid = existe
            else:
                uid, senha_nova = criar_usuario(c, m["nome_completo"], m["email"], "membro", membro_id=mid)
                auditar(request, "USUARIO_CRIADO", f"Usuário #{uid}", f"Acesso criado para Coordenação (ficha #{mid})", conexao=c)
        else:
            uid = _numero(pessoa[2:] if pessoa.startswith("u:") else pessoa)
        alvo = c.execute(select(db.usuarios).where(db.usuarios.c.id == uid)).mappings().first()
        if not alvo:
            flash(request, "Escolha a pessoa.", "erro")
            return ir("/coordenacao#designar")
        if not alvo["ativo"]:
            flash(request, f"O login de {alvo['nome']} está desativado. Reative o acesso antes de designar.", "erro")
            return ir("/coordenacao#designar")
        f = _ficha_de(c, dict(alvo))
        if f and f["status"] not in FICHA_APTA:
            flash(request, f"A ficha de {alvo['nome']} está como \"{f['status']}\". Só ficha validada pode receber Coordenação.", "erro")
            return ir("/coordenacao#designar")
        us = db.usuario_setores.c
        if c.execute(select(us.id).where(us.usuario_id == uid, us.departamento_id == dep)).first():
            flash(request, f"{alvo['nome']} já tem uma designação no ministério {setor}. Use ✏️ Editar nela.", "erro")
            return ir(f"/coordenacao#u{uid}")
        c.execute(insert(db.usuario_setores).values(
            usuario_id=uid, departamento_id=dep, tipo=tipo, inicio=inicio, fim=fim,
            evento_id=str(evento["id"]) if evento else None, observacao=observacao or None,
            disponibilidade=True, criado_por=eu["nome"], criado_em=datas.agora_utc()))
        if alvo["perfil"] == "membro":
            c.execute(update(db.usuarios).where(db.usuarios.c.id == uid).values(perfil="coordenacao"))
        # Disponibilidade: a pessoa passa a constar no setor (ficha) como Coordenação
        if alvo["membro_id"]:
            ms = db.membro_setores.c
            atual = c.execute(select(ms.id).where(ms.membro_id == alvo["membro_id"], ms.departamento_id == dep)).first()
            if atual:
                c.execute(update(db.membro_setores).where(ms.id == atual[0]).values(funcao="Coordenação"))
            else:
                c.execute(insert(db.membro_setores).values(membro_id=alvo["membro_id"], departamento_id=dep, funcao="Coordenação"))
        prazo = coord.TIPOS[tipo] + (f" · {inicio.strftime('%d/%m/%Y')}" if inicio else "") + (f" a {fim.strftime('%d/%m/%Y')}" if fim else "")
        auditar(request, "COORDENACAO_DESIGNADA", f"Usuário #{uid}",
                f"Ministério {setor} · {prazo}" + (f" · evento {evento['titulo']}" if evento else "")
                + (f" · {observacao}" if observacao else ""), conexao=c)
    if senha_nova:
        _mostrar_senha_uma_vez(request, alvo["nome"], alvo["email"], senha_nova)
    if form.get("avisar") == "sim":
        _avisar(dict(alvo), setor, tipo, inicio, fim, evento, eu["nome"])
    flash(request, f"{alvo['nome']} agora coordena {setor} ({coord.TIPOS[tipo].lower()}).")
    return ir(f"/coordenacao#u{uid}")


@seguranca.exigir(*SEC_ADM)
async def editar(request: Request):
    did = request.path_params["id"]
    form = await request.form()
    observacao = (form.get("observacao") or "").strip()[:500]
    with db.engine().begin() as c:
        linha = c.execute(select(db.usuario_setores).where(db.usuario_setores.c.id == did)).mappings().first()
        if not linha:
            flash(request, "Designação não encontrada (pode ter vencido).", "erro")
            return ir("/coordenacao")
        setor = c.execute(select(db.departamentos.c.nome).where(db.DEP_ID == str(linha["departamento_id"]))).scalar()
        tipo, inicio, fim, evento, erro = _ler_prazo(c, form, setor)
        if erro:
            flash(request, erro, "erro")
            return ir(f"/coordenacao#u{linha['usuario_id']}")
        antes = f"{coord.TIPOS.get(linha['tipo'], linha['tipo'])} {datas.fmt_data(linha['inicio'])}–{datas.fmt_data(linha['fim'])}"
        c.execute(update(db.usuario_setores).where(db.usuario_setores.c.id == did).values(
            tipo=tipo, inicio=inicio, fim=fim, evento_id=str(evento["id"]) if evento else None, observacao=observacao or None))
        depois = f"{coord.TIPOS[tipo]} {datas.fmt_data(inicio)}–{datas.fmt_data(fim)}"
        auditar(request, "COORDENACAO_ALTERADA", f"Usuário #{linha['usuario_id']}",
                f"Ministério {setor} · {antes} → {depois}" + (f" · {observacao}" if observacao else ""), conexao=c)
    flash(request, f"Coordenação de {setor} atualizada.")
    return ir(f"/coordenacao#u{linha['usuario_id']}")


def _motivo(form) -> str:
    return (form.get("motivo") or "").strip()[:1000]


@seguranca.exigir(*SEC_ADM)
async def encerrar(request: Request):
    did = request.path_params["id"]
    form = await request.form()
    motivo = _motivo(form)
    eu = seguranca.usuario_atual(request)
    with db.engine().begin() as c:
        linha = c.execute(select(db.usuario_setores).where(db.usuario_setores.c.id == did)).mappings().first()
        if not linha:
            return ir("/coordenacao")
        if len(motivo) < coord.MOTIVO_MINIMO:
            flash(request, f"Escreva a justificativa do encerramento (mínimo {coord.MOTIVO_MINIMO} caracteres).", "erro")
            return ir(f"/coordenacao#u{linha['usuario_id']}")
        setor = c.execute(select(db.departamentos.c.nome).where(db.DEP_ID == str(linha["departamento_id"]))).scalar()
        coord.encerrar(c, dict(linha), eu["nome"], motivo)
        auditar(request, "COORDENACAO_ENCERRADA", f"Usuário #{linha['usuario_id']}", f"Ministério {setor} · {motivo}", conexao=c)
        perfil = c.execute(select(db.usuarios.c.perfil, db.usuarios.c.nome).where(db.usuarios.c.id == linha["usuario_id"])).first()
    flash(request, f"Coordenação de {setor} encerrada." + (f" {perfil[1]} voltou a ser Membro." if perfil and perfil[0] == "membro" else ""))
    return ir("/coordenacao")


@seguranca.exigir(*SEC_ADM)
async def remover(request: Request):
    """Encerra todas as designações da pessoa (Tirar da Coordenação)."""
    uid = request.path_params["id"]
    form = await request.form()
    motivo = _motivo(form)
    eu = seguranca.usuario_atual(request)
    with db.engine().begin() as c:
        alvo = c.execute(select(db.usuarios).where(db.usuarios.c.id == uid)).mappings().first()
        if not alvo:
            return ir("/coordenacao")
        if len(motivo) < coord.MOTIVO_MINIMO:
            flash(request, f"Escreva a justificativa (mínimo {coord.MOTIVO_MINIMO} caracteres).", "erro")
            return ir(f"/coordenacao#u{uid}")
        n = coord.encerrar_todas(c, uid, eu["nome"], motivo)
        if alvo["perfil"] == "coordenacao":
            c.execute(update(db.usuarios).where(db.usuarios.c.id == uid).values(perfil="membro"))
        auditar(request, "COORDENACAO_REMOVIDA", f"Usuário #{uid}", f"{n} designação(ões) encerrada(s) · {motivo}", conexao=c)
    flash(request, f"{alvo['nome']} saiu da Coordenação." + (" Voltou a ser Membro." if alvo["perfil"] in ("membro", "coordenacao") else ""))
    return ir("/coordenacao")


rotas = [
    Route("/coordenacao", tela),
    Route("/coordenacao/designar", designar, methods=["POST"]),
    Route("/coordenacao/designacao/{id:int}/editar", editar, methods=["POST"]),
    Route("/coordenacao/designacao/{id:int}/encerrar", encerrar, methods=["POST"]),
    Route("/coordenacao/{id:int}/remover", remover, methods=["POST"]),
]
