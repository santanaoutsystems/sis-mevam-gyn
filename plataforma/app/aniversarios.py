"""Aniversariantes (v2.8.0): quem faz aniversário, quem deve ser avisado e o registro das mensagens.

Regras (proposta "Aniversariantes", Edição 01, validada pelo Ricardo em 17/10/2026):
- Entram só fichas ativas na membresia, com data de nascimento e sem recusa de homenagem (LGPD).
- Nunca se mostra ano de nascimento nem idade: só dia/mês.
- Aviso de amanhã (e "hoje", no dia): vai para a Coordenação dos setores em que o membro serve ou que marcou
  como interesse. Sem setor, ou setor sem coordenador, vai para a Secretaria e o Adm (na janela).
  Secretaria e Adm sempre recebem todos no sino.
- Quem nasceu em 29/02 faz aniversário em 28/02 nos anos que não são bissextos.
A rotina roda junto dos lembretes de cadastro (/healthz, das 8h às 21h) e também na primeira tela do dia.
"""

from __future__ import annotations

import calendar
import logging
from datetime import date, timedelta
from urllib.parse import quote

from sqlalchemy import and_, insert, or_, select, update
from sqlalchemy.exc import IntegrityError

from . import config, datas, db, envios, ficha

FORA = ("Inativo", "Anonimizado (LGPD)")
SEM_SETOR = "Sem setor"
GESTORES = ("secretaria", "admin")
AMANHA, HOJE = "aniversario_amanha", "aniversario_hoje"
CANAIS = {"whatsapp": "WhatsApp", "email": "E-mail", "copia": "Texto copiado", "email_auto": "E-mail automático do Ministério"}
REMETENTE_AUTO = "Ministério MEVAM GYN"

MODELO_PADRAO = {
    "id": 0, "titulo": "Aniversário · padrão do Ministério", "padrao": True, "ativo": True,
    "texto": ("Paz, {primeiro_nome}! 🎉\n\nHoje celebramos a sua vida! \"O Senhor te abençoe e te guarde; o Senhor faça "
              "resplandecer o seu rosto sobre ti e te conceda graça\" (Nm 6.24-25).\n\nFeliz aniversário!\n"
              "Com carinho, {remetente} · MEVAM GYN"),
}
CAMPOS = ("{primeiro_nome}", "{nome}", "{setor}", "{remetente}")

log = logging.getLogger("mevam")
_garantido = {"dia": None}


# ---------------------------------------------------------------------------
# Quem faz aniversário
# ---------------------------------------------------------------------------
def no_ano(nasc: date, ano: int) -> date:
    """Data do aniversário no ano informado (29/02 vira 28/02 fora dos anos bissextos)."""
    if nasc.month == 2 and nasc.day == 29 and not calendar.isleap(ano):
        return date(ano, 2, 28)
    return date(ano, nasc.month, nasc.day)


def chave_setor(nome: str) -> str:
    """Nome padronizado do setor (os nomes antigos dos departamentos viram o nome da ficha)."""
    return ficha.setor_padrao(nome) or (nome or "").strip()


def primeiro_nome(nome: str) -> str:
    return (nome or "").strip().split(" ")[0]


def nome_curto(nome: str) -> str:
    partes = (nome or "").split()
    return partes[0] + (f" {partes[-1][0]}." if len(partes) > 1 else "")


def membros(c, ids=None) -> list[dict]:
    """Aniversariantes possíveis, com os setores (onde serve e de interesse). Data completa fica só aqui dentro."""
    m = db.membros.c
    q = (select(m.id, m.nome_completo, m.data_nascimento, m.whatsapp, m.email)
         .where(m.data_nascimento.isnot(None), m.status.notin_(FORA), m.homenagem_aniversario.isnot(False)))
    if ids is not None:
        q = q.where(m.id.in_(list(ids)))
    linhas = {r["id"]: dict(r) for r in c.execute(q).mappings()}
    if not linhas:
        return []
    serve: dict[int, list[str]] = {}
    for mid, nome in c.execute(select(db.membro_setores.c.membro_id, db.departamentos.c.nome)
                               .select_from(db.membro_setores.join(db.departamentos,
                                                                  db.DEP_ID == db.membro_setores.c.departamento_id))):
        serve.setdefault(mid, []).append(chave_setor(nome))
    interesse: dict[int, list[str]] = {}
    for mid, setor in c.execute(select(db.membro_interesses.c.membro_id, db.membro_interesses.c.setor)):
        interesse.setdefault(mid, []).append(setor)
    lista = []
    for mid, r in linhas.items():
        nasc = datas.parse_data(r["data_nascimento"])
        if not nasc:
            continue
        setores, vistos = [], set()
        for nome in sorted(serve.get(mid, [])):
            if nome and nome not in vistos:
                vistos.add(nome); setores.append({"nome": nome, "tipo": "serve"})
        for nome in sorted(interesse.get(mid, [])):
            if nome and nome not in vistos:
                vistos.add(nome); setores.append({"nome": nome, "tipo": "interesse"})
        lista.append({"id": mid, "nome": r["nome_completo"], "primeiro": primeiro_nome(r["nome_completo"]),
                      "curto": nome_curto(r["nome_completo"]), "nasc": nasc, "dia": nasc.day, "mes": nasc.month,
                      "whatsapp": r["whatsapp"], "email": r["email"], "setores": setores, "chaves": vistos})
    lista.sort(key=lambda x: (x["mes"], x["dia"], (x["nome"] or "").lower()))
    return lista


def do_dia(lista: list[dict], d: date) -> list[dict]:
    return [m for m in lista if no_ano(m["nasc"], d.year) == d]


def por_dia(lista: list[dict], de: date, ate: date) -> dict[date, list[dict]]:
    """Aniversariantes de cada dia entre `de` e `ate` (inclusive)."""
    saida: dict[date, list[dict]] = {}
    for ano in range(de.year, ate.year + 1):
        for m in lista:
            d = no_ano(m["nasc"], ano)
            if de <= d <= ate:
                saida.setdefault(d, []).append(m)
    return saida


def rotulo_setores(m: dict) -> str:
    if not m["setores"]:
        return SEM_SETOR
    return ", ".join(s["nome"] + (" (interesse)" if s["tipo"] == "interesse" else "") for s in m["setores"])


# ---------------------------------------------------------------------------
# Quem pode ver e quem é avisado
# ---------------------------------------------------------------------------
def escopo(c, usuario: dict) -> set[str] | None:
    """Setores (padronizados) que o usuário vê. None = todos (Secretaria e Adm); vazio = nenhum."""
    if usuario["perfil"] in GESTORES:
        return None
    if usuario["perfil"] != "coordenacao":
        return set()
    from .rotas.agenda import escopo_setores
    return {chave_setor(n) for n in (escopo_setores(c, usuario) or set())}


def visivel(m: dict, esc: set[str] | None) -> bool:
    return esc is None or bool(m["chaves"] & esc)


def coordenadores(c) -> dict[str, set[int]]:
    """Setor padronizado → ids dos usuários ativos da Coordenação daquele setor."""
    u, us = db.usuarios.c, db.usuario_setores.c
    q = (select(u.id, db.departamentos.c.nome)
         .select_from(db.usuario_setores.join(db.usuarios, u.id == us.usuario_id)
                      .join(db.departamentos, db.DEP_ID == us.departamento_id))
         .where(u.ativo.is_(True), u.perfil == "coordenacao"))
    mapa: dict[str, set[int]] = {}
    for uid, nome in c.execute(q):
        mapa.setdefault(chave_setor(nome), set()).add(uid)
    return mapa


def gestores(c) -> list[int]:
    return list(c.execute(select(db.usuarios.c.id).where(db.usuarios.c.ativo.is_(True),
                                                         db.usuarios.c.perfil.in_(GESTORES))).scalars())


def destinatarios(m: dict, coords: dict[str, set[int]], gest: list[int]) -> dict[int, bool]:
    """usuário → aparece na janela? Coordenação dos setores sempre; Secretaria/Adm na janela só sem coordenação."""
    dest = {uid: True for k in m["chaves"] for uid in coords.get(k, ())}
    sem_coordenacao = not dest
    for uid in gest:
        dest.setdefault(uid, sem_coordenacao)
    return dest


def gerar_avisos(c, hoje: date | None = None) -> int:
    """Cria (uma única vez) os avisos de amanhã e de hoje. Devolve quantos foram criados."""
    hoje = hoje or datas.hoje()
    lista = membros(c)
    coords, gest = coordenadores(c), gestores(c)
    a = db.avisos.c
    criados = 0
    for tipo, dia in ((AMANHA, hoje + timedelta(days=1)), (HOJE, hoje)):
        do = do_dia(lista, dia)
        if not do:
            continue
        existentes = set(c.execute(select(a.usuario_id, a.membro_id).where(a.tipo == tipo, a.referencia == dia)).all())
        for m in do:
            for uid, janela in destinatarios(m, coords, gest).items():
                if (uid, m["id"]) in existentes:
                    continue
                try:
                    with c.begin_nested():
                        c.execute(insert(db.avisos).values(usuario_id=uid, tipo=tipo, membro_id=m["id"], referencia=dia,
                                                           janela=janela, criado_em=datas.agora_utc()))
                    criados += 1
                except IntegrityError:
                    pass
    return criados


def garantir(hoje: date | None = None) -> None:
    """Na primeira tela do dia (por processo), garante os avisos mesmo se a rotina ainda não rodou."""
    hoje = hoje or datas.hoje()
    if _garantido["dia"] == hoje:
        return
    try:
        with db.engine().begin() as c:
            gerar_avisos(c, hoje)
        _garantido["dia"] = hoje
    except Exception:  # noqa: BLE001
        log.exception("Falha ao gerar os avisos de aniversário")


def avisos_do_usuario(c, usuario_id: int, hoje: date | None = None) -> list[dict]:
    """Avisos ativos: amanhã, e o de hoje (fica no sino até o dia seguinte ao aniversário)."""
    hoje = hoje or datas.hoje()
    a, m = db.avisos.c, db.membros.c
    q = (select(a.id, a.tipo, a.membro_id, a.referencia, a.janela, a.lido_em, m.nome_completo)
         .join(db.membros, m.id == a.membro_id)
         .where(a.usuario_id == usuario_id, m.status.notin_(FORA), m.homenagem_aniversario.isnot(False),
                or_(and_(a.tipo == AMANHA, a.referencia == hoje + timedelta(days=1)),
                    and_(a.tipo == HOJE, a.referencia >= hoje - timedelta(days=1), a.referencia <= hoje)))
         .order_by(a.referencia, m.nome_completo))
    lista = []
    for r in c.execute(q).mappings():
        r = dict(r)
        r["referencia"] = datas.parse_data(r["referencia"])
        r["hoje"] = r["tipo"] == HOJE and r["referencia"] == hoje
        lista.append(r)
    return lista


def marcar_lidos(c, usuario_id: int) -> None:
    c.execute(update(db.avisos).where(db.avisos.c.usuario_id == usuario_id, db.avisos.c.lido_em.is_(None))
              .values(lido_em=datas.agora_utc()))


# ---------------------------------------------------------------------------
# Mensagens
# ---------------------------------------------------------------------------
def modelos(c, so_ativos: bool = True) -> list[dict]:
    q = select(db.mensagens_modelo).where(db.mensagens_modelo.c.tipo == "aniversario").order_by(
        db.mensagens_modelo.c.padrao.desc(), db.mensagens_modelo.c.titulo)
    if so_ativos:
        q = q.where(db.mensagens_modelo.c.ativo.is_(True))
    lista = [dict(r) for r in c.execute(q).mappings()]
    return lista or [dict(MODELO_PADRAO)]


def modelo_padrao(c) -> dict:
    lista = modelos(c)
    return next((x for x in lista if x["padrao"]), lista[0])


def preencher(texto: str, m: dict, remetente: str, setor: str = "") -> str:
    setor = setor or next((s["nome"] for s in m.get("setores", []) if s["tipo"] == "serve"), "") or "MEVAM GYN"
    return (texto.replace("{primeiro_nome}", m["primeiro"]).replace("{nome}", m["nome"] or "")
            .replace("{setor}", setor).replace("{remetente}", remetente))


def link_whatsapp(numero: str | None, texto: str) -> str:
    n = envios.numero_whatsapp(numero)
    return f"https://wa.me/{n}?text={quote(texto)}" if n else ""


def enviados(c, ids, anos) -> dict[tuple[int, int], list[dict]]:
    """Mensagens já enviadas, por (membro, ano): marca ✔ no calendário para toda a equipe."""
    ids, anos = list(ids), list(anos)
    if not ids or not anos:
        return {}
    e = db.aniversario_envios.c
    saida: dict[tuple[int, int], list[dict]] = {}
    for r in c.execute(select(e.membro_id, e.ano, e.canal, e.usuario_nome, e.enviado_em, e.resultado)
                       .where(e.membro_id.in_(ids), e.ano.in_(anos)).order_by(e.enviado_em)).mappings():
        if (r["resultado"] or "").startswith("falha"):
            continue
        saida.setdefault((r["membro_id"], r["ano"]), []).append(dict(r))
    return saida


def ano_da_homenagem(nasc: date, hoje: date | None = None) -> int:
    """Ano do aniversário a que a mensagem se refere: o deste ano até 7 dias depois; depois, o do ano que vem."""
    hoje = hoje or datas.hoje()
    return hoje.year if no_ano(nasc, hoje.year) >= hoje - timedelta(days=7) else hoje.year + 1


def registrar(c, membro_id: int, ano: int, canal: str, usuario: dict | None, resultado: str = "enviado") -> None:
    c.execute(insert(db.aniversario_envios).values(
        membro_id=membro_id, ano=ano, canal=canal, usuario_id=usuario["id"] if usuario else None,
        usuario_nome=usuario["nome"] if usuario else REMETENTE_AUTO, enviado_em=datas.agora_utc(), resultado=resultado))


# ---------------------------------------------------------------------------
# Rotina diária (e-mail resumo das 8h e e-mail automático do Ministério)
# ---------------------------------------------------------------------------
def _email_resumo(hoje: date) -> int:
    """Um e-mail por usuário com os aniversariantes de amanhã da sua janela (Coordenação: seus setores)."""
    amanha = hoje + timedelta(days=1)
    a, u, m = db.avisos.c, db.usuarios.c, db.membros.c
    with db.engine().connect() as c:
        linhas = c.execute(select(a.id, a.usuario_id, u.nome.label("usuario"), u.email, m.id.label("membro_id"))
                           .join(db.usuarios, u.id == a.usuario_id).join(db.membros, m.id == a.membro_id)
                           .where(a.tipo == AMANHA, a.referencia == amanha, a.janela.is_(True), a.email_em.is_(None),
                                  u.ativo.is_(True), u.email_avisos.isnot(False), m.homenagem_aniversario.isnot(False),
                                  m.status.notin_(FORA))).mappings().all()
        if not linhas:
            return 0
        dados = {x["id"]: x for x in membros(c, {r["membro_id"] for r in linhas})}
    por_usuario: dict[int, list] = {}
    for r in linhas:
        if r["membro_id"] in dados:
            por_usuario.setdefault(r["usuario_id"], []).append(r)
    enviados_n = 0
    for uid, itens in por_usuario.items():
        ids_aviso = [r["id"] for r in itens]
        with db.engine().begin() as c:  # trava antes do envio: rodadas simultâneas não repetem o e-mail
            n = c.execute(update(db.avisos).where(db.avisos.c.id.in_(ids_aviso), db.avisos.c.email_em.is_(None))
                          .values(email_em=datas.agora_utc())).rowcount
        if not n:
            continue
        nomes = "\n".join(f"  • {dados[r['membro_id']]['nome']} · {rotulo_setores(dados[r['membro_id']])}" for r in itens)
        qtd = len(itens)
        assunto = f"🎂 Amanhã ({amanha.strftime('%d/%m')}) é aniversário de {qtd} pessoa{'s' if qtd > 1 else ''}"
        corpo = (f"Paz, {primeiro_nome(itens[0]['usuario'])}!\n\nAmanhã, {datas.dia_semana(amanha).lower()} "
                 f"{amanha.strftime('%d/%m')}, é aniversário de:\n{nomes}\n\n"
                 f"Prepare uma palavra especial. No dia, o botão 💬 Mensagem do calendário já traz o texto pronto:\n"
                 f"{config.URL_BASE}/aniversariantes?dia={amanha.isoformat()}\n\n"
                 "Para não receber este resumo, desligue em Aniversariantes › Resumo por e-mail.\nSIS MEVAM-GYN")
        erro = envios.enviar_email(itens[0]["email"], assunto, corpo)
        from .web import auditar
        auditar(None, "AVISO_ANIVERSARIO_EMAIL" if erro is None else "FALHA_AVISO_ANIVERSARIO_EMAIL",
                f"Usuário #{uid}", f"{qtd} aniversariante(s) de {amanha.strftime('%d/%m')}" + (f": {erro}" if erro else ""))
        enviados_n += erro is None
    return enviados_n


def _email_automatico(hoje: date) -> int:
    """E-mail do Ministério no dia, para cada aniversariante com e-mail (um por ano, trava pela chave)."""
    from .web import auditar
    with db.engine().connect() as c:
        lista = [m for m in do_dia(membros(c), hoje) if m["email"]]
        modelo = modelo_padrao(c) if lista else None
    saiu = 0
    for m in lista:
        chave = f"auto:{m['id']}:{hoje.year}"
        try:
            with db.engine().begin() as c:
                eid = c.execute(insert(db.aniversario_envios).values(
                    membro_id=m["id"], ano=hoje.year, canal="email_auto", usuario_nome=REMETENTE_AUTO,
                    enviado_em=datas.agora_utc(), chave=chave)).inserted_primary_key[0]
        except IntegrityError:
            continue
        texto = preencher(modelo["texto"], m, REMETENTE_AUTO)
        erro = envios.enviar_email(m["email"], f"🎂 Feliz aniversário, {m['primeiro']}!", texto)
        with db.engine().begin() as c:
            c.execute(update(db.aniversario_envios).where(db.aniversario_envios.c.id == eid)
                      .values(resultado="enviado" if erro is None else f"falha: {erro}"[:300]))
            auditar(None, "ANIVERSARIO_EMAIL_AUTO" if erro is None else "FALHA_ANIVERSARIO_EMAIL_AUTO",
                    f"Membro #{m['id']}", erro or "", conexao=c)
        saiu += erro is None
    return saiu


def rodar(hoje: date | None = None) -> dict:
    """Uma rodada: avisos (sempre) e e-mails (se o envio estiver configurado)."""
    hoje = hoje or datas.hoje()
    with db.engine().begin() as c:
        criados = gerar_avisos(c, hoje)
    _garantido["dia"] = hoje
    resumo = automatico = 0
    if envios.email_configurado():
        resumo = _email_resumo(hoje)
        automatico = _email_automatico(hoje)
    return {"avisos": criados, "resumo": resumo, "automatico": automatico}
