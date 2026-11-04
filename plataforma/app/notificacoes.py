"""Alertas por e-mail (opcional). Falhas ficam registradas na auditoria em vez de sumirem."""

from __future__ import annotations

import threading

from sqlalchemy import insert, select

from . import config, datas, db, envios

ASSUNTOS = {
    "novo": "📅 SIS MEVAM-GYN: Novo evento - {titulo}",
    "atualizado": "🔄 SIS MEVAM-GYN: Evento atualizado - {titulo}",
    "cancelado": "❌ SIS MEVAM-GYN: Evento cancelado - {titulo}",
}


def _destinatarios() -> list[str]:
    with db.engine().connect() as c:
        return [r[0] for r in c.execute(select(db.usuarios.c.email).where(
            db.usuarios.c.ativo.is_(True), db.usuarios.c.perfil.in_(("admin", "secretaria"))))]


def _enviar(assunto: str, corpo: str, emails: list[str]) -> None:
    falhas = [f"{d}: {erro}" for d in emails if (erro := envios.enviar_email(d, assunto, corpo))]
    if falhas:  # registra para a administração ver
        with db.engine().begin() as c:
            c.execute(insert(db.auditoria).values(usuario_nome="Sistema", acao="FALHA_EMAIL",
                                                  recurso=assunto[:200], detalhes="; ".join(falhas)[:500],
                                                  criado_em=datas.agora_utc()))


def alerta_evento(tipo: str, evento: dict, autor: str, motivo: str = "") -> None:
    if not envios.email_configurado():
        return
    emails = _destinatarios()
    if not emails:
        return
    quando = datas.parse_data_hora_local(evento["data_inicio"])
    corpo = (f"Paz!\n\nEvento: {evento['titulo']}\n"
             f"Data/Hora: {quando.strftime('%d/%m/%Y às %H:%M') if quando else '-'}\n"
             f"Departamento: {evento.get('departamento') or 'Geral'}\n"
             f"Responsável pela ação: {autor}\n" + (f"Motivo: {motivo}\n" if motivo else "") +
             f"\nAcesse: {config.URL_BASE}/agenda\n")
    assunto = ASSUNTOS[tipo].format(titulo=evento["titulo"])
    threading.Thread(target=_enviar, args=(assunto, corpo, emails), daemon=True).start()
