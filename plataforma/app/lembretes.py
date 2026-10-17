"""Lembretes por e-mail para quem fez o pré-cadastro sem a foto 3x4.

Regra (v2.6.0): a foto é opcional no envio da ficha, mas precisa ser anexada em até 30 dias.
O membro recebe um link exclusivo (o mesmo portal /atualizar da regularização) e e-mails:
  d0  no envio da ficha
  d1  1 dia depois          d10  10 dias depois
  d25 faltam 5 dias         d29  falta 1 dia
  d30 dia do vencimento: chamado especial, com link novo; depois s1, s2... um por semana até a foto chegar.
O Render free não tem agendador: a rodada é disparada pelo /healthz (UptimeRobot, a cada 5 min),
no máximo a cada 30 minutos e só das 8h às 21h de Goiânia. A trava única (membro, etapa) no banco
impede e-mail repetido mesmo com duas rodadas ao mesmo tempo.
"""

from __future__ import annotations

import logging
import threading
import time

from sqlalchemy import exists, insert, select, update
from sqlalchemy.exc import IntegrityError

from . import config, datas, db, envios
from .web import auditar

PRAZO_DIAS = 30
ETAPAS_ANTES = (1, 10, 25, 29)
FORA = ("Inativo", "Anonimizado (LGPD)")
AUTOR = "Sistema (cadastro sem foto)"
INTERVALO_SEGUNDOS = 30 * 60

_ultima_rodada = {"t": 0.0}
_trava = threading.Lock()
log = logging.getLogger("mevam")


def etapa_do_dia(dias: int) -> str | None:
    """Etapa devida após `dias` dias do cadastro (a mais recente; as perdidas não se acumulam)."""
    if dias >= PRAZO_DIAS:
        semanas = (dias - PRAZO_DIAS) // 7
        return "d30" if semanas == 0 else f"s{semanas}"
    devidas = [d for d in ETAPAS_ANTES if dias >= d]
    return f"d{devidas[-1]}" if devidas else None


def texto_email(etapa: str, m: dict, link: str, prazo: str, extra: str = "") -> tuple[str, str]:
    primeiro = (m.get("nome_completo") or "").split(" ")[0]
    rodape = ("\n\nRosto de frente, fundo claro e sem óculos. Pelo celular, toque em \"Câmera\" ou \"Galeria\".\n\n"
              "Se você já enviou a foto, desconsidere esta mensagem.\nSecretaria · MEVAM GYN")
    if etapa == "d0":
        assunto = "MEVAM GYN: ficha recebida, falta a foto 3x4"
        corpo = (f"Paz, {primeiro}!\n\nRecebemos a sua ficha de membro (protocolo #{m['id']}). Obrigado!\n\n"
                 f"Para concluir o cadastro, falta apenas a foto 3x4. Você tem até {prazo} para enviá-la "
                 f"por este link exclusivo:\n{link}")
    elif etapa in ("d1", "d10"):
        assunto = "MEVAM GYN: complete seu cadastro com a foto 3x4"
        corpo = (f"Paz, {primeiro}!\n\nSeu cadastro ainda está sem a foto 3x4. O prazo para enviá-la é {prazo}.\n\n"
                 f"Envie pelo seu link exclusivo:\n{link}")
    elif etapa == "d25":
        assunto = "MEVAM GYN: faltam 5 dias para enviar sua foto"
        corpo = (f"Paz, {primeiro}!\n\nFaltam 5 dias para terminar o prazo ({prazo}) de envio da foto 3x4 "
                 f"do seu cadastro.\n\nEnvie pelo seu link exclusivo:\n{link}")
    elif etapa == "d29":
        assunto = "MEVAM GYN: último dia para enviar sua foto"
        corpo = (f"Paz, {primeiro}!\n\nO prazo para enviar a foto 3x4 do seu cadastro termina amanhã ({prazo}).\n\n"
                 f"Envie agora pelo seu link exclusivo:\n{link}")
    elif etapa == "d30":
        assunto = "⚠️ MEVAM GYN: chamado especial para completar seu cadastro"
        corpo = (f"Paz, {primeiro}!\n\nHoje vence o prazo de 30 dias para completar o seu cadastro de membro do "
                 f"MEVAM GYN, e ainda falta a foto 3x4.\n\nEste é um chamado especial: queremos muito o seu cadastro "
                 f"completo. Leva menos de 1 minuto. Envie a foto por este link, válido até {prazo}:\n{link}\n\n"
                 f"Se tiver dificuldade, responda este e-mail ou procure a Secretaria.")
    else:
        assunto = "MEVAM GYN: seu cadastro continua incompleto"
        corpo = (f"Paz, {primeiro}!\n\nO prazo de 30 dias terminou e o seu cadastro continua sem a foto 3x4. "
                 f"Ele fica pendente até a foto ser enviada.\n\nEnvie por este novo link, válido até {prazo}:\n{link}")
    return assunto, corpo + extra + rodape


def _link_valido(c, membro_id) -> dict:
    """Link aberto do membro; se não houver (venceu ou foi usado), cria outro por 7 dias."""
    from .rotas import regularizacao as reg
    ultimo = reg._ultimos_links(c, [membro_id]).get(membro_id)
    if reg.situacao(ultimo) in ("ativo", "enviado"):
        return ultimo
    return reg._criar_link(c, membro_id, 7, AUTOR)


def _enviar(membro_id, etapa: str, extra: str = "") -> bool:
    """Grava a etapa (trava) e envia o e-mail. Devolve False se a etapa já tinha sido enviada."""
    from .rotas import regularizacao as reg
    with db.engine().begin() as c:
        m = c.execute(select(db.membros.c.id, db.membros.c.nome_completo, db.membros.c.email)
                      .where(db.membros.c.id == membro_id)).mappings().first()
        if not m or not m["email"]:
            return False
        try:
            with c.begin_nested():
                lid = c.execute(insert(db.lembretes_cadastro).values(
                    membro_id=membro_id, etapa=etapa, enviado_em=datas.agora_utc())).inserted_primary_key[0]
        except IntegrityError:
            return False
        link = _link_valido(c, membro_id)
    m = dict(m)
    prazo = datas.fmt_data_hora(reg._utc(link["expira_em"]))[:10]
    assunto, corpo = texto_email(etapa, m, reg.link_de(link), prazo, extra)
    erro = envios.enviar_email(m["email"], assunto, corpo)
    with db.engine().begin() as c:
        c.execute(update(db.lembretes_cadastro).where(db.lembretes_cadastro.c.id == lid)
                  .values(resultado="enviado" if erro is None else f"falha: {erro}"[:300]))
        if erro is None:
            reg._marcar_envio(c, link["id"], "email")
        auditar(None, "LEMBRETE_FOTO" if erro is None else "FALHA_LEMBRETE_FOTO", f"Membro #{membro_id}",
                f"Etapa {etapa}" + (f": {erro}" if erro else ""), conexao=c)
    return True


def iniciar(c, membro_id) -> None:
    """Na ficha enviada sem foto: abre o link de 30 dias (o e-mail d0 sai depois do commit, em `boas_vindas`)."""
    from .rotas import regularizacao as reg
    reg._criar_link(c, membro_id, PRAZO_DIAS, AUTOR)


def bloco_manual_pesquisa(membro_id) -> str:
    """Link do Manual do Membro e as 4 respostas da pesquisa de satisfação (um clique registra)."""
    from .rotas import pesquisa
    opcoes = "\n".join(f"  {rotulo}: {pesquisa.link(membro_id, chave)}" for chave, rotulo in pesquisa.OPCOES)
    return ("\n\n📘 Manual do Membro\nPreparamos um manual com o passo a passo do sistema. Baixe aqui:\n"
            f"{config.URL_BASE}/manual/membro\n\n"
            "⭐ Como foi fazer o seu cadastro?\nToque em uma opção para responder (leva 1 segundo):\n" + opcoes)


def boas_vindas(membro_id, sem_foto: bool) -> None:
    """E-mail de boas-vindas com o manual e a pesquisa; sem foto, também o link e o prazo de 30 dias (etapa d0)."""
    def tarefa():
        try:
            extra = bloco_manual_pesquisa(membro_id)
            if sem_foto:
                _enviar(membro_id, "d0", extra)
                return
            with db.engine().connect() as c:
                m = c.execute(select(db.membros.c.id, db.membros.c.nome_completo, db.membros.c.email)
                              .where(db.membros.c.id == membro_id)).mappings().first()
            if not m or not m["email"]:
                return
            primeiro = (m["nome_completo"] or "").split(" ")[0]
            corpo = (f"Paz, {primeiro}!\n\nRecebemos a sua ficha de membro (protocolo #{m['id']}). Obrigado!\n"
                     "A Secretaria vai analisar seus dados e depois enviará o link da Confissão de Fé." + extra +
                     "\n\nSecretaria · MEVAM GYN")
            erro = envios.enviar_email(m["email"], "MEVAM GYN: ficha recebida", corpo)
            auditar(None, "EMAIL_BOAS_VINDAS" if erro is None else "FALHA_EMAIL_BOAS_VINDAS",
                    f"Membro #{membro_id}", erro or "")
        except Exception:  # noqa: BLE001
            log.exception("Falha no e-mail de boas-vindas (membro %s)", membro_id)
    if config.ENVIO_SINCRONO:
        tarefa()
    else:
        threading.Thread(target=tarefa, daemon=True).start()


def pendentes(c) -> list[dict]:
    """Quem começou o fluxo (tem d0), ainda está sem foto e continua na membresia."""
    q = (select(db.membros.c.id, db.membros.c.criado_em)
         .where(db.membros.c.foto_3x4.is_(None), db.membros.c.email.isnot(None),
                db.membros.c.status.notin_(FORA),
                exists().where(db.lembretes_cadastro.c.membro_id == db.membros.c.id,
                               db.lembretes_cadastro.c.etapa == "d0")))
    return [dict(r) for r in c.execute(q).mappings()]


def rodar(agora=None) -> int:
    """Uma rodada: envia a etapa devida de cada pendente. Devolve quantos e-mails saíram."""
    from .rotas import regularizacao as reg
    agora = agora or datas.agora_utc()
    with db.engine().connect() as c:
        lista = pendentes(c)
    enviados = 0
    for p in lista:
        criado = reg._utc(p["criado_em"])
        if not criado:
            continue
        etapa = etapa_do_dia((agora - criado).days)
        if etapa and _enviar(p["id"], etapa):
            enviados += 1
    return enviados


def agendar() -> None:
    """Chamado pelo /healthz: roda em segundo plano, no máximo a cada 30 min, das 8h às 21h.

    Também roda a rotina dos aniversariantes (avisos de amanhã, resumo das 8h e e-mail do dia)."""
    if not 8 <= datas.agora().hour < 21:
        return
    with _trava:
        if _ultima_rodada["t"] and time.monotonic() - _ultima_rodada["t"] < INTERVALO_SEGUNDOS:
            return
        _ultima_rodada["t"] = time.monotonic()

    def tarefa():
        try:
            if envios.email_configurado():
                n = rodar()
                if n:
                    log.info("Lembretes de cadastro enviados: %s", n)
        except Exception:  # noqa: BLE001
            log.exception("Falha na rodada de lembretes de cadastro")
        try:
            from . import aniversarios
            r = aniversarios.rodar()
            if any(r.values()):
                log.info("Aniversariantes: %s", r)
        except Exception:  # noqa: BLE001
            log.exception("Falha na rotina dos aniversariantes")
    threading.Thread(target=tarefa, daemon=True).start()
