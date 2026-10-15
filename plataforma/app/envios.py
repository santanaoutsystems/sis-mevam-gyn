"""Envio de mensagens individuais: e-mail (SMTP) e WhatsApp (Evolution API, opcional).

Cada função devolve None quando deu certo ou o motivo da falha, para registrar na auditoria.
"""

from __future__ import annotations

import json
import smtplib
import urllib.request
from email.mime.text import MIMEText

from . import config
from .ficha import so_digitos


def email_configurado() -> bool:
    return bool(config.SMTP_USUARIO and config.SMTP_SENHA)


def whatsapp_configurado() -> bool:
    return bool(config.EVOLUTION_API_URL and config.EVOLUTION_API_KEY and config.EVOLUTION_INSTANCIA)


def numero_whatsapp(v: str | None) -> str:
    """Número no formato internacional (55 + DDD + número) ou vazio."""
    d = so_digitos(v or "")
    if not d:
        return ""
    return d if d.startswith("55") and len(d) >= 12 else "55" + d


def enviar_email(destino: str, assunto: str, corpo: str) -> str | None:
    if not email_configurado():
        return "e-mail não configurado"
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORTA, timeout=20) as s:
            s.starttls()
            s.login(config.SMTP_USUARIO, config.SMTP_SENHA)
            msg = MIMEText(corpo, "plain", "utf-8")
            msg["Subject"], msg["From"], msg["To"] = assunto, config.SMTP_USUARIO, destino
            s.sendmail(config.SMTP_USUARIO, [destino], msg.as_string())
        return None
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {e}"[:300]


def enviar_whatsapp(numero: str, texto: str) -> str | None:
    if not whatsapp_configurado():
        return "WhatsApp automático não configurado"
    numero = numero_whatsapp(numero)
    if not numero:
        return "sem número de WhatsApp"
    req = urllib.request.Request(
        f"{config.EVOLUTION_API_URL}/message/sendText/{config.EVOLUTION_INSTANCIA}",
        data=json.dumps({"number": numero, "text": texto}).encode(),
        headers={"apikey": config.EVOLUTION_API_KEY, "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return None if 200 <= r.status < 300 else f"HTTP {r.status}"
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {e}"[:300]
