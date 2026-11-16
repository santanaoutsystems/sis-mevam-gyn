"""Coordenação (v2.9.0): designações por setor, permanentes, por período ou para um evento.

Cada linha de `usuario_setores` é uma designação. Quem tem perfil Membro e recebe a primeira designação
passa ao perfil Coordenação; quando a última termina (prazo ou decisão da Secretaria/Adm), volta a Membro.
Secretaria e Adm também podem ser designados: o perfil deles não muda (já gerenciam toda a agenda),
mas passam a constar como coordenadores do setor.

Nada se perde: toda designação encerrada vai para `coordenacoes_historico` com quem encerrou e o motivo.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from sqlalchemy import and_, delete, insert, or_, select, update

from . import datas, db

log = logging.getLogger("mevam")

TIPOS = {
    "permanente": "Permanente (até nova decisão)",
    "periodo": "Por período",
    "evento": "Para um evento",
}
PERIODO_MAXIMO_DIAS = 366  # coordenação por período: no máximo 1 ano (renovável)
MOTIVO_MINIMO = 10  # caracteres da justificativa ao encerrar

# Critérios conferidos pelo sistema na hora de designar (aparecem na tela e no manual)
CRITERIOS = [
    "Ter login ativo no sistema. Se a pessoa ainda não tem, o sistema cria o acesso a partir da ficha validada (com e-mail).",
    "Se a pessoa tem ficha, ela precisa estar validada (Ativo ou Validado pela Secretaria). Ficha inativa, "
    "na lixeira ou aguardando análise não pode receber Coordenação.",
    "Ter se disponibilizado a servir no ministério: a Secretaria/Adm confirma isso ao designar, e a pessoa passa a "
    "constar no ministério como Coordenação.",
    "Uma designação por pessoa em cada ministério. Para mudar o prazo ou o tipo, edite a designação que já existe.",
    "Por período: de 1 dia até 1 ano, renovável. Para um evento: vale até o dia do evento e só para ele.",
]

# Diretrizes da função (proposta para a liderança validar; aparecem na tela e no manual)
DIRETRIZES = [
    "Servir no ministério que coordena, participando da escala e das reuniões do ministério.",
    "Cadastrar e manter só os eventos dos seus ministérios, respeitando o intervalo de 2 horas entre eventos. "
    "Liberar conflito de horário é decisão da Secretaria ou do Adm.",
    "Toda edição ou exclusão de evento exige justificativa e fica registrada no histórico.",
    "Registrar inscrições e despesas do evento no sistema e conferir o resumo financeiro ao final.",
    "Usar os dados das inscrições só para o evento (LGPD): não copiar listas para fora do sistema.",
    "A Coordenação não vê fichas de membros nem usuários; dúvidas de cadastro vão para a Secretaria.",
    "Coordenação temporária termina sozinha no fim do prazo. Ao deixar a função antes, avise a Secretaria.",
]


def ativa(linha: dict, hoje: date | None = None) -> bool:
    hoje = hoje or datas.hoje()
    return (linha.get("inicio") is None or linha["inicio"] <= hoje) and (linha.get("fim") is None or linha["fim"] >= hoje)


def situacao(linha: dict, hoje: date | None = None) -> tuple[str, str]:
    """(texto, classe do selo) da designação: Ativa, Começa em…, Vence em…"""
    hoje = hoje or datas.hoje()
    if linha.get("inicio") and linha["inicio"] > hoje:
        return f"Começa em {linha['inicio'].strftime('%d/%m/%Y')}", "aguardando"
    if linha.get("fim"):
        dias = (linha["fim"] - hoje).days
        if dias < 0:
            return "Prazo encerrado", "inativo"
        if dias <= 7:
            return ("Termina hoje" if dias == 0 else f"Termina em {dias} dia(s)"), "aguardando"
    return "Ativa", "ativo"


def filtro_ativo(hoje: date | None = None):
    """Condição SQL: designação dentro do prazo."""
    hoje = hoje or datas.hoje()
    us = db.usuario_setores.c
    return and_(or_(us.inicio.is_(None), us.inicio <= hoje), or_(us.fim.is_(None), us.fim >= hoje))


def designacoes_ativas(c, usuario_id: int) -> list[dict]:
    us = db.usuario_setores.c
    return [dict(r) for r in c.execute(
        select(db.usuario_setores, db.departamentos.c.nome.label("setor"))
        .select_from(db.usuario_setores.join(db.departamentos, db.DEP_ID == us.departamento_id))
        .where(us.usuario_id == usuario_id, filtro_ativo())).mappings()]


def _evento(c, evento_id) -> dict | None:
    if not evento_id:
        return None
    r = c.execute(select(db.eventos.c.id, db.eventos.c.titulo, db.eventos.c.data_inicio, db.eventos.c.departamento)
                  .where(db.texto(db.eventos.c.id) == str(evento_id))).mappings().first()
    if not r:
        return None
    e = dict(r)
    e["quando"] = datas.parse_data_hora_local(e["data_inicio"])
    return e


def encerrar(c, linha: dict, por: str, motivo: str) -> None:
    """Tira a designação de `usuario_setores`, guarda no histórico e, se era a última de um Membro, volta a Membro."""
    alvo = c.execute(select(db.usuarios.c.id, db.usuarios.c.nome, db.usuarios.c.perfil)
                     .where(db.usuarios.c.id == linha["usuario_id"])).mappings().first()
    setor = c.execute(select(db.departamentos.c.nome).where(db.DEP_ID == str(linha["departamento_id"]))).scalar()
    ev = _evento(c, linha.get("evento_id"))
    c.execute(insert(db.coordenacoes_historico).values(
        usuario_id=linha["usuario_id"], usuario_nome=alvo["nome"] if alvo else None,
        departamento_id=str(linha["departamento_id"]), setor_nome=setor, tipo=linha.get("tipo") or "permanente",
        inicio=linha.get("inicio"), fim=linha.get("fim"), evento_id=linha.get("evento_id"),
        evento_titulo=ev["titulo"] if ev else None, observacao=linha.get("observacao"),
        criado_por=linha.get("criado_por"), criado_em=linha.get("criado_em"),
        encerrado_em=datas.agora_utc(), encerrado_por=por, motivo_encerramento=motivo))
    c.execute(delete(db.usuario_setores).where(db.usuario_setores.c.id == linha["id"]))
    rebaixar_se_vazio(c, linha["usuario_id"])


def rebaixar_se_vazio(c, usuario_id: int) -> bool:
    """Perfil Coordenação sem nenhuma designação (ativa ou futura) volta a Membro."""
    perfil = c.execute(select(db.usuarios.c.perfil).where(db.usuarios.c.id == usuario_id)).scalar()
    if perfil != "coordenacao":
        return False
    hoje = datas.hoje()
    us = db.usuario_setores.c
    resta = c.execute(select(us.id).where(us.usuario_id == usuario_id,
                                          or_(us.fim.is_(None), us.fim >= hoje)).limit(1)).first()
    if resta:
        return False
    c.execute(update(db.usuarios).where(db.usuarios.c.id == usuario_id).values(perfil="membro"))
    return True


def encerrar_todas(c, usuario_id: int, por: str, motivo: str) -> int:
    linhas = [dict(r) for r in c.execute(select(db.usuario_setores)
                                         .where(db.usuario_setores.c.usuario_id == usuario_id)).mappings()]
    for l in linhas:
        encerrar(c, l, por, motivo)
    return len(linhas)


def encerrar_vencidas() -> int:
    """Rotina diária (chamada pelo /healthz e ao abrir a tela): designações com prazo vencido vão para o histórico."""
    from .web import auditar
    hoje = datas.hoje()
    n = 0
    with db.engine().begin() as c:
        vencidas = [dict(r) for r in c.execute(select(db.usuario_setores)
                                               .where(db.usuario_setores.c.fim < hoje)).mappings()]
        for l in vencidas:
            encerrar(c, l, "Sistema", "Prazo encerrado")
            auditar(None, "COORDENACAO_ENCERRADA", f"Usuário #{l['usuario_id']}",
                    f"Prazo encerrado em {l['fim'].strftime('%d/%m/%Y')} · ministério {l['departamento_id']}",
                    usuario={"id": None, "nome": "Sistema"}, conexao=c)
            n += 1
    if n:
        log.info("Coordenações encerradas pelo prazo: %s", n)
    return n


def validar_prazo(tipo: str, inicio: date | None, fim: date | None, evento: dict | None) -> tuple[date | None, date | None, str | None]:
    """Confere e completa as datas conforme o tipo. Devolve (inicio, fim, erro)."""
    hoje = datas.hoje()
    inicio = inicio or hoje
    if tipo == "permanente":
        return inicio, None, None
    if tipo == "evento":
        if not evento or not evento.get("quando"):
            return inicio, None, "Escolha o evento desta coordenação."
        dia = evento["quando"].date()
        if dia < hoje:
            return inicio, None, "Este evento já aconteceu. Escolha um evento de hoje em diante."
        return min(inicio, dia), dia, None
    if tipo == "periodo":
        if not fim:
            return inicio, None, "Informe a data de término do período (dd/mm/aaaa)."
        if fim < inicio:
            return inicio, fim, "A data de término é anterior à data de início."
        if fim < hoje:
            return inicio, fim, "A data de término já passou."
        if (fim - inicio) > timedelta(days=PERIODO_MAXIMO_DIAS):
            return inicio, fim, "O período pode ter no máximo 1 ano. Depois é só renovar."
        return inicio, fim, None
    return inicio, fim, "Tipo de coordenação inválido."
