"""Fila do WhatsApp da Secretaria (v2.16.0): pedidos de complemento e do Credo sem WhatsApp Business.

Sem a API oficial, quem envia é a própria Secretaria, pelo celular dela (link wa.me): o sistema não usa
robôs nem WhatsApp Web automatizado, que são o que mais leva o WhatsApp a bloquear números. Para o
número não ser marcado como spam, a fila segue as práticas que o próprio WhatsApp recomenda:

- cota diária de contatos novos, crescendo aos poucos (aquecimento do número);
- intervalo mínimo entre uma mensagem e outra e envio só em horário comercial;
- "em 2 tempos": a primeira mensagem não tem link e pede uma resposta (SIM). Quem responde vira uma
  conversa de mão dupla e só então recebe o link, o que quase elimina as denúncias;
- texto com variações e o primeiro nome da pessoa, nunca a mesma mensagem idêntica;
- "SAIR" respeitado na hora e número inválido tirado da fila;
- no máximo um lembrete para quem não respondeu.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from sqlalchemy import func, insert, select, update

from . import config, datas, db, envios

# Etapas registradas em whatsapp_envios
CONVITE, LEMBRETE, LINK = "convite", "lembrete", "link"
COMPLEMENTO, CREDO = "complemento", "credo"
MODO_2_TEMPOS, MODO_DIRETO = "2tempos", "direto"
# Situação do contato (membros.whatsapp_situacao)
RESPONDEU, NAO_QUER, INVALIDO = "respondeu", "nao_quer", "invalido"

# Aquecimento: contatos novos por dia, contando a partir do primeiro convite enviado pelo sistema
AQUECIMENTO = ((7, 15), (14, 25))  # até o 7º dia: 15/dia; até o 14º: 25/dia
COTA_PLENA = 35
TOTAL_DIARIO = 80  # todas as mensagens do dia, incluindo os links para quem respondeu
INTERVALO_NOVO = 60  # segundos antes de uma mensagem para quem ainda não respondeu
INTERVALO_RESPOSTA = 20  # segundos antes de um link para quem já respondeu
HORA_INICIO, HORA_FIM = config.WHATSAPP_HORA_INICIO, config.WHATSAPP_HORA_FIM  # Goiânia
DIAS_PARA_LEMBRETE = 4
MAX_CONVITES = 2  # convite + um lembrete

CONVITES = {
    COMPLEMENTO: (
        "Paz, {nome}! Aqui é da Secretaria do MEVAM GYN. Estamos atualizando o cadastro dos membros e faltam "
        "alguns dados na sua ficha. Posso te enviar o link para você completar? É só responder SIM.\n"
        "(Se não quiser receber mensagens da Secretaria, responda SAIR.)",
        "Paz, {nome}! Tudo bem? Sou da Secretaria do MEVAM GYN. A sua ficha de membro já está no nosso novo "
        "sistema, mas precisa de um complemento rápido (CPF e foto). Posso mandar o link por aqui? Responda SIM.\n"
        "(Para não receber mais mensagens, responda SAIR.)",
        "Paz, {nome}! A Secretaria do MEVAM GYN está finalizando o seu cadastro de membro e falta pouco. "
        "Posso te mandar o link para completar os seus dados? Responda SIM, por favor.\n"
        "(Se preferir não receber, responda SAIR.)",
    ),
    CREDO: (
        "Paz, {nome}! Aqui é da Secretaria do MEVAM GYN. A sua ficha de membro foi registrada no novo sistema "
        "da igreja e falta só a sua assinatura na Confissão de Fé. Posso te enviar o link? É só responder SIM.\n"
        "(Se não quiser receber mensagens da Secretaria, responda SAIR.)",
        "Paz, {nome}! Tudo bem? Sou da Secretaria do MEVAM GYN. Para concluir o seu cadastro de membro falta a "
        "rubrica digital na Confissão de Fé. Posso mandar o link por aqui? Responda SIM.\n"
        "(Para não receber mais mensagens, responda SAIR.)",
        "Paz, {nome}! A Secretaria do MEVAM GYN está finalizando o seu cadastro de membro: só falta você ler e "
        "assinar a Confissão de Fé. Posso te mandar o link? Responda SIM, por favor.\n"
        "(Se preferir não receber, responda SAIR.)",
    ),
}
LEMBRETES = {
    COMPLEMENTO: "Paz, {nome}! Passando de novo para lembrar do seu cadastro no MEVAM GYN. Posso te enviar o "
                 "link para completar os seus dados? Responda SIM. (Para não receber mais, responda SAIR.)",
    CREDO: "Paz, {nome}! Passando de novo para lembrar da sua assinatura na Confissão de Fé do MEVAM GYN. "
           "Posso te enviar o link? Responda SIM. (Para não receber mais, responda SAIR.)",
}
RODAPE_DIRETO = "\n(Se não quiser receber mensagens da Secretaria, responda SAIR.)"


def primeiro_nome(m: dict) -> str:
    return ((m.get("nome_completo") or "").split(" ") or [""])[0]


def _utc(v) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, str):
        v = datetime.fromisoformat(v)
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


def _inicio_do_dia() -> datetime:
    return datetime.combine(datas.hoje(), datetime.min.time(), tzinfo=datas.TZ).astimezone(timezone.utc)


def url(numero: str | None, texto: str) -> str:
    return f"https://wa.me/{envios.numero_whatsapp(numero)}?text={quote(texto)}"


def numero_valido(numero: str | None) -> bool:
    d = envios.numero_whatsapp(numero)
    return 12 <= len(d) <= 13  # 55 + DDD + 8 ou 9 dígitos


# ---------------------------------------------------------------------------
# Cotas e ritmo
# ---------------------------------------------------------------------------
def cota_hoje(c) -> int:
    """Contatos novos permitidos hoje (aquecimento automático, ou o valor fixo de WHATSAPP_LIMITE_DIARIO)."""
    if config.WHATSAPP_LIMITE_DIARIO > 0:
        return config.WHATSAPP_LIMITE_DIARIO
    primeiro = _utc(c.execute(select(func.min(db.whatsapp_envios.c.enviado_em))
                              .where(db.whatsapp_envios.c.conta_cota.is_(True))).scalar())
    if not primeiro:
        return AQUECIMENTO[0][1]
    dias = (datas.hoje() - primeiro.astimezone(datas.TZ).date()).days + 1
    for ate, cota in AQUECIMENTO:
        if dias <= ate:
            return cota
    return COTA_PLENA


def resumo_do_dia(c) -> dict:
    """Números de hoje e quando a próxima mensagem fica liberada (para os dois tipos)."""
    e = db.whatsapp_envios.c
    inicio = _inicio_do_dia()
    novos = c.execute(select(func.count()).select_from(db.whatsapp_envios).where(e.enviado_em >= inicio, e.conta_cota.is_(True))).scalar() or 0
    total = c.execute(select(func.count()).select_from(db.whatsapp_envios).where(e.enviado_em >= inicio)).scalar() or 0
    ultimo = _utc(c.execute(select(func.max(e.enviado_em))).scalar())
    agora = datas.agora_utc()
    hora = datas.agora().hour
    cota = cota_hoje(c)

    def espera(intervalo: int) -> int:
        return max(0, int((ultimo + timedelta(seconds=intervalo) - agora).total_seconds())) if ultimo else 0

    return {"cota": cota, "novos": novos, "restam_novos": max(0, cota - novos), "total": total,
            "restam_total": max(0, TOTAL_DIARIO - total), "no_horario": HORA_INICIO <= hora < HORA_FIM,
            "espera_novo": espera(INTERVALO_NOVO), "espera_resposta": espera(INTERVALO_RESPOSTA),
            "HORA_INICIO": HORA_INICIO, "HORA_FIM": HORA_FIM, "fixa": config.WHATSAPP_LIMITE_DIARIO > 0}


def bloqueio(c, conta_cota: bool) -> str | None:
    """Motivo para não enviar agora, ou None."""
    r = resumo_do_dia(c)
    if not r["no_horario"]:
        return f"Envios só entre {HORA_INICIO}h e {HORA_FIM}h (horário de Goiânia), para não incomodar e não parecer robô."
    if r["restam_total"] <= 0:
        return f"Limite de {TOTAL_DIARIO} mensagens por dia atingido. Continue amanhã."
    if conta_cota and r["restam_novos"] <= 0:
        return f"Cota de hoje atingida ({r['cota']} contatos novos). Continue amanhã: a cota cresce aos poucos."
    espera = r["espera_novo"] if conta_cota else r["espera_resposta"]
    if espera:
        return f"Aguarde {espera} segundo(s) antes da próxima mensagem. Intervalos protegem o número da Secretaria."
    return None


# ---------------------------------------------------------------------------
# Fila de um lote
# ---------------------------------------------------------------------------
def historico(c, membro_ids: list[int]) -> dict[int, list[dict]]:
    if not membro_ids:
        return {}
    h: dict[int, list[dict]] = {}
    q = select(db.whatsapp_envios).where(db.whatsapp_envios.c.membro_id.in_(membro_ids)).order_by(db.whatsapp_envios.c.id)
    for r in c.execute(q).mappings():
        h.setdefault(r["membro_id"], []).append(dict(r))
    return h


def estado(m: dict, envios_m: list[dict], tipo: str, agora=None) -> str:
    """na_fila | lembrete | aguardando | sem_resposta | link_enviado | nao_quer | invalido"""
    if m.get("whatsapp_situacao") == NAO_QUER:
        return "nao_quer"
    if m.get("whatsapp_situacao") == INVALIDO or not numero_valido(m.get("whatsapp")):
        return "invalido"
    meus = [e for e in envios_m if e["tipo"] == tipo]
    if any(e["etapa"] == LINK for e in meus):
        return "link_enviado"
    convites = [e for e in meus if e["etapa"] in (CONVITE, LEMBRETE)]
    if not convites:
        return "na_fila"
    ultimo = _utc(convites[-1]["enviado_em"])
    if ultimo + timedelta(days=DIAS_PARA_LEMBRETE) > (agora or datas.agora_utc()):
        return "aguardando"
    return "lembrete" if len(convites) < MAX_CONVITES else "sem_resposta"


def montar(c, itens: list[tuple[dict, str]]) -> dict:
    """itens = [(membro, tipo)]. Devolve a fila separada por situação, na ordem de envio."""
    h = historico(c, [m["id"] for m, _ in itens])
    grupos = {k: [] for k in ("na_fila", "lembrete", "aguardando", "sem_resposta", "link_enviado", "nao_quer", "invalido")}
    for m, tipo in sorted(itens, key=lambda x: x[0]["id"]):
        meus = h.get(m["id"], [])
        st = estado(m, meus, tipo)
        ultimo = next((e for e in reversed(meus) if e["tipo"] == tipo), None)
        grupos[st].append({**m, "tipo": tipo, "estado": st, "ultimo_envio": ultimo["enviado_em"] if ultimo else None,
                           "convites": sum(1 for e in meus if e["tipo"] == tipo and e["etapa"] in (CONVITE, LEMBRETE))})
    grupos["proximos"] = grupos["na_fila"] + grupos["lembrete"]
    return grupos


def texto_convite(m: dict, tipo: str, etapa: str, modelo: int) -> str:
    if etapa == LEMBRETE:
        return LEMBRETES[tipo].format(nome=primeiro_nome(m))
    return CONVITES[tipo][modelo % len(CONVITES[tipo])].format(nome=primeiro_nome(m))


def registrar(c, m: dict, lote_id: int, tipo: str, etapa: str, conta_cota: bool, modelo: int, autor: str) -> None:
    c.execute(insert(db.whatsapp_envios).values(
        membro_id=m["id"], lote_id=lote_id, tipo=tipo, etapa=etapa, conta_cota=conta_cota, modelo=modelo,
        enviado_em=datas.agora_utc(), enviado_por=autor))


def marcar_situacao(c, membro_id: int, situacao: str | None) -> None:
    c.execute(update(db.membros).where(db.membros.c.id == membro_id).values(
        whatsapp_situacao=situacao, whatsapp_situacao_em=datas.agora_utc()))
