"""INTEGRA como porta de entrada (v2.12.0).

Só segue para a análise da Secretaria, o Credo e o login quem concluiu o INTEGRA (ou foi dispensado).
A Secretaria/Adm cadastra a turma; no encerramento o sistema mostra um código de 6 caracteres e o QR Code,
que o participante lê no celular. O código vale até o fim do dia do encerramento (pode ser prorrogado).

Situações (membros.integra_situacao):
  concluido      INTEGRA confirmado (pelo código da turma ou lançado pela Secretaria/Adm)
  aguardando     disse que fez, mas sem código válido: a Secretaria confere e lança
  nao_concluido  ainda não fez
  dispensado     dispensa da Secretaria/Adm, com justificativa
  bloqueado      bloqueio administrativo do Adm, com justificativa
  (vazio)        ficha anterior à v2.12.0 que ainda não respondeu à campanha

Quem já tinha cadastro recebe a campanha: 30 dias para responder, lembrete no 25º dia; sem resposta, a ficha
passa a N/C INTEGRA e o login de Membro/Coordenação é suspenso até a Secretaria lançar ou dispensar.
"""

from __future__ import annotations

import logging
import secrets
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select, update

from . import config, datas, db, envios, seguranca

log = logging.getLogger("mevam")

NC = db.NC_INTEGRA
SITUACOES = {
    "concluido": "Concluído",
    "aguardando": "Aguardando confirmação",
    "nao_concluido": "Não concluído",
    "dispensado": "Dispensado",
    "bloqueado": "Bloqueado pelo Adm",
    None: "Não informado",
}
LIBERADO = ("concluido", "dispensado")  # pode seguir para análise e ter acesso
IDADE_MINIMA = 18
PRAZO_DIAS = 30
LEMBRETE_DIA = 25
LIMITE_DIARIO = 80  # cota do Gmail da Secretaria
ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sem 0/O, 1/I
STATUS_RESTAURAVEIS = ("Ativo", "Validado pela Secretaria", "Aguardando Análise")


def rotulo(situacao: str | None) -> str:
    return SITUACOES.get(situacao, situacao or "Não informado")


def liberado(m: dict) -> bool:
    return m.get("integra_situacao") in LIBERADO


def idade(nasc: date | None, hoje: date | None = None) -> int | None:
    return datas.idade(nasc, hoje)


# ---------------------------------------------------------------------------
# Turmas e código
# ---------------------------------------------------------------------------
def gerar_codigo(c) -> str:
    while True:
        codigo = "".join(secrets.choice(ALFABETO) for _ in range(6))
        if not c.execute(select(db.integra_turmas.c.id).where(db.integra_turmas.c.codigo == codigo)).first():
            return codigo


def fim_do_dia(d: date) -> datetime:
    """23:59:59 de Goiânia, em UTC."""
    return datetime.combine(d, time(23, 59, 59), tzinfo=datas.TZ).astimezone(timezone.utc)


def normalizar_codigo(texto: str | None) -> str:
    return "".join(ch for ch in (texto or "").upper() if ch.isalnum())[:10]


def _utc(v):
    if v is None:
        return None
    if isinstance(v, str):
        v = datetime.fromisoformat(v)
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


def codigo_vigente(turma: dict, agora: datetime | None = None) -> bool:
    agora = agora or datas.agora_utc()
    return _utc(turma["codigo_valido_ate"]) >= agora


def turma_do_codigo(c, codigo: str | None, agora: datetime | None = None) -> tuple[dict | None, str | None]:
    """(turma, erro). Erro quando o código não existe ou já venceu."""
    codigo = normalizar_codigo(codigo)
    if not codigo:
        return None, "Informe o código da turma."
    t = c.execute(select(db.integra_turmas).where(db.integra_turmas.c.codigo == codigo)).mappings().first()
    if not t:
        return None, "Código não encontrado. Confira as letras e números."
    if not codigo_vigente(t, agora):
        return dict(t), "Este código já venceu. A Secretaria vai conferir a lista da turma."
    return dict(t), None


def link_turma(turma: dict) -> str:
    return f"{config.URL_BASE}/integra/c/{turma['codigo']}"


# ---------------------------------------------------------------------------
# Mudanças de situação (sempre dentro de uma transação; quem chama audita)
# ---------------------------------------------------------------------------
def _religar(c, m: dict) -> None:
    from .rotas.membros import _religar_login
    _religar_login(c, m)


def _suspender(c, m: dict, por: str, motivo: str) -> None:
    from .rotas.membros import _suspender_login
    _suspender_login(c, m["id"], por, motivo)


def liberar(c, m: dict, situacao: str, por: str, *, data_integra: date | None = None, turma_id: int | None = None,
            justificativa: str | None = None) -> str:
    """Concluído ou dispensado. Se a ficha estava N/C INTEGRA, volta ao fluxo. Devolve o novo status."""
    status = m["status"]
    if status == NC:
        anterior = m.get("status_anterior")
        status = anterior if anterior in STATUS_RESTAURAVEIS else "Aguardando Análise"
    valores = dict(integra_situacao=situacao, integra_registrado_por=por, integra_registrado_em=datas.agora_utc(),
                   integra_justificativa=justificativa, status=status, integra_prazo=None)
    if data_integra is not None or turma_id is not None:
        valores.update(integra_data=data_integra, integra_turma_id=turma_id)
    c.execute(update(db.membros).where(db.membros.c.id == m["id"]).values(**valores))
    if m["status"] == NC:
        _religar(c, m)
    return status


def segurar(c, m: dict, situacao: str, por: str, justificativa: str | None = None) -> None:
    """Não concluído, aguardando confirmação ou bloqueado: ficha N/C INTEGRA e login suspenso."""
    valores = dict(integra_situacao=situacao, integra_registrado_por=por, integra_registrado_em=datas.agora_utc())
    if justificativa is not None:
        valores["integra_justificativa"] = justificativa
    if m["status"] not in (NC,) + db.STATUS_FORA:
        valores.update(status=NC, status_anterior=m["status"])
    c.execute(update(db.membros).where(db.membros.c.id == m["id"]).values(**valores))
    if m["status"] not in db.STATUS_FORA:
        _suspender(c, m, por, f"INTEGRA: {rotulo(situacao)}")


def resposta_do_form(c, form, agora: datetime | None = None, exigir_resposta: bool = True) -> tuple[dict, dict]:
    """Lê 'integra' (Sim/Não), 'integra_data' e 'integra_codigo'. Devolve (valores, erros).

    valores: integra_situacao, integra_data, integra_turma_id."""
    erros: dict = {}
    resp = form.get("integra") or ""
    if resp not in ("Sim", "Não"):
        if exigir_resposta:
            erros["integra"] = "Informe se você fez o INTEGRA."
        return {}, erros
    if resp == "Não":
        return {"integra_situacao": "nao_concluido", "integra_data": None, "integra_turma_id": None}, erros
    data_i = datas.parse_data(form.get("integra_data"))
    if not data_i:
        erros["integra_data"] = "Informe a data em que concluiu o INTEGRA (dd/mm/aaaa)."
    elif data_i > datas.hoje():
        erros["integra_data"] = "A data do INTEGRA não pode ser futura."
    valores = {"integra_situacao": "aguardando", "integra_data": data_i, "integra_turma_id": None}
    if (form.get("integra_codigo") or "").strip():
        turma, erro = turma_do_codigo(c, form.get("integra_codigo"), agora)
        if turma and not erro:
            valores.update(integra_situacao="concluido", integra_turma_id=turma["id"],
                           integra_data=turma["data_conclusao"])
            erros.pop("integra_data", None)
        elif turma:  # código vencido: guarda a turma para a Secretaria conferir
            valores["integra_turma_id"] = turma["id"]
            valores["integra_data"] = valores["integra_data"] or turma["data_conclusao"]
            erros.pop("integra_data", None)
        else:
            erros["integra_codigo"] = erro
    return valores, erros


# ---------------------------------------------------------------------------
# Campanha para quem já tinha cadastro
# ---------------------------------------------------------------------------
def link_atualizar(mid: int) -> str:
    return f"{config.URL_BASE}/integra/atualizar/{mid}?t={seguranca.token_link('integra', mid)}"


def candidatos_campanha(c) -> list[dict]:
    """Fichas já no fluxo (validadas ou ativas) que nunca responderam e ainda não receberam o pedido."""
    q = (select(db.membros.c.id, db.membros.c.nome_completo, db.membros.c.email, db.membros.c.whatsapp,
                db.membros.c.status)
         .where(db.membros.c.integra_situacao.is_(None), db.membros.c.integra_pedido_em.is_(None),
                db.membros.c.status.in_(("Ativo", "Validado pela Secretaria", "Aguardando Análise")))
         .order_by(db.membros.c.nome_completo))
    return [dict(r) for r in c.execute(q).mappings()]


def texto_pedido(m: dict, prazo: date, lembrete: bool = False) -> tuple[str, str]:
    primeiro = (m.get("nome_completo") or "").split(" ")[0]
    assunto = ("Lembrete: informe seu INTEGRA" if lembrete else "Atualize seu cadastro: você fez o INTEGRA?") + " · MEVAM GYN"
    corpo = (f"Paz, {primeiro}!\n\n"
             "O MEVAM GYN passou a usar o INTEGRA como porta de entrada para a membresia, os ministérios e as "
             "atividades da agenda. Precisamos saber se você já fez o INTEGRA.\n\n"
             f"Responda pelo link abaixo até {datas.fmt_data(prazo)}:\n{link_atualizar(m['id'])}\n\n"
             "Sem resposta até essa data, o seu acesso ao sistema fica suspenso até você falar com a Secretaria.\n\n"
             "Secretaria MEVAM GYN")
    return assunto, corpo


def texto_bloqueio(m: dict) -> tuple[str, str]:
    primeiro = (m.get("nome_completo") or "").split(" ")[0]
    return ("Seu acesso ao SIS MEVAM-GYN foi suspenso · INTEGRA",
            f"Paz, {primeiro}!\n\nO prazo para informar o INTEGRA terminou e o seu acesso ao sistema foi suspenso. "
            "Procure a Secretaria do MEVAM GYN para atualizar os seus dados e liberar o acesso novamente.\n\n"
            "Secretaria MEVAM GYN")


def enviar_pedidos(limite: int = LIMITE_DIARIO, hoje: date | None = None) -> dict:
    """Marca o prazo e envia o e-mail para até `limite` fichas. Sem e-mail: só marca (WhatsApp manual)."""
    hoje = hoje or datas.hoje()
    prazo = hoje + timedelta(days=PRAZO_DIAS)
    agora = datas.agora_utc()
    with db.engine().begin() as c:
        lista = candidatos_campanha(c)[:limite]
        for m in lista:
            c.execute(update(db.membros).where(db.membros.c.id == m["id"]).values(
                integra_pedido_em=agora, integra_prazo=prazo))
    enviados = sem_email = 0
    for m in lista:
        if m.get("email") and envios.email_configurado():
            assunto, corpo = texto_pedido(m, prazo)
            if envios.enviar_email(m["email"], assunto, corpo) is None:
                enviados += 1
                continue
        sem_email += 1
    return {"marcados": len(lista), "enviados": enviados, "sem_email": sem_email, "prazo": prazo}


def rodar_prazos(hoje: date | None = None) -> dict:
    """Rotina diária: lembrete no 25º dia e suspensão quando o prazo vence sem resposta."""
    hoje = hoje or datas.hoje()
    r = {"lembretes": 0, "suspensos": 0}
    with db.engine().connect() as c:
        pendentes = [dict(x) for x in c.execute(select(db.membros).where(
            db.membros.c.integra_situacao.is_(None), db.membros.c.integra_prazo.isnot(None),
            db.membros.c.status.notin_(db.STATUS_FORA + (NC,)))).mappings()]
    for m in pendentes:
        prazo = m["integra_prazo"]
        if isinstance(prazo, str):
            prazo = date.fromisoformat(prazo)
        if prazo < hoje:
            with db.engine().begin() as c:
                segurar(c, m, None, "Sistema (prazo do INTEGRA)")
                from .web import auditar
                auditar(None, "INTEGRA_PRAZO_VENCIDO", f"Membro #{m['id']}",
                        "Sem resposta em 30 dias: ficha N/C INTEGRA e acesso suspenso",
                        usuario={"id": None, "nome": "Sistema"}, conexao=c)
            r["suspensos"] += 1
            if m.get("email") and envios.email_configurado():
                envios.enviar_email(m["email"], *texto_bloqueio(m))
        elif (prazo - hoje).days <= PRAZO_DIAS - LEMBRETE_DIA and not m.get("integra_lembrete_em"):
            with db.engine().begin() as c:
                c.execute(update(db.membros).where(db.membros.c.id == m["id"]).values(integra_lembrete_em=datas.agora_utc()))
            if m.get("email") and envios.email_configurado():
                envios.enviar_email(m["email"], *texto_pedido(m, prazo, lembrete=True))
                r["lembretes"] += 1
    return r


def enviar_copia_credo(m: dict, link_pdf: str) -> None:
    """Depois da assinatura do Credo: e-mail com o link da cópia assinada (PDF)."""
    if not m.get("email") or not envios.email_configurado():
        return
    primeiro = (m.get("nome_completo") or "").split(" ")[0]
    envios.enviar_email(
        m["email"], "Sua ficha assinada · MEVAM GYN",
        f"Paz, {primeiro}!\n\nSeja bem-vindo(a) à família MEVAM GYN. A sua assinatura do Credo foi registrada.\n\n"
        f"Guarde a cópia do seu documento assinado (PDF):\n{link_pdf}\n\nSecretaria MEVAM GYN")
