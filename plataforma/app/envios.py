"""Envio de mensagens individuais: e-mail (Google Apps Script, Brevo ou SMTP) e WhatsApp (Evolution API, opcional).

Cada função devolve None quando deu certo ou o motivo da falha, para registrar na auditoria.
"""

from __future__ import annotations

import base64
import json
import smtplib
import urllib.error
import urllib.request
from email.mime.text import MIMEText

from . import config
from .ficha import so_digitos


def _google_ok() -> bool:
    return bool(config.EMAIL_GOOGLE_URL and config.EMAIL_GOOGLE_SEGREDO)


def _brevo_ok() -> bool:
    return bool(config.BREVO_API_KEY and config.EMAIL_REMETENTE)


def email_configurado() -> bool:
    return _google_ok() or _brevo_ok() or bool(config.SMTP_USUARIO and config.SMTP_SENHA)


def canal_email() -> str:
    if _google_ok():
        return "Gmail (Google Apps Script)"
    if _brevo_ok():
        return "Brevo (HTTPS)"
    return "SMTP" if email_configurado() else "não configurado"


def whatsapp_configurado() -> bool:
    return bool(config.EVOLUTION_API_URL and config.EVOLUTION_API_KEY and config.EVOLUTION_INSTANCIA)


def numero_whatsapp(v: str | None) -> str:
    """Número no formato internacional (55 + DDD + número) ou vazio."""
    d = so_digitos(v or "")
    if not d:
        return ""
    return d if d.startswith("55") and len(d) >= 12 else "55" + d


def _email_google(destino: str, assunto: str, corpo: str) -> str | None:
    req = urllib.request.Request(
        config.EMAIL_GOOGLE_URL,
        data=json.dumps({"segredo": config.EMAIL_GOOGLE_SEGREDO, "para": destino, "assunto": assunto,
                         "corpo": corpo, "nome": config.EMAIL_NOME}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # o Google responde com um redirecionamento
            texto = r.read().decode("utf-8", "replace")
        try:
            resposta = json.loads(texto)
        except ValueError:
            return "resposta inesperada do Google (confira se o script foi implantado com acesso 'Qualquer pessoa')"
        return None if resposta.get("ok") else f"Google: {resposta.get('erro') or 'falha sem detalhe'}"[:300]
    except urllib.error.HTTPError as e:
        return f"Google HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {e}"[:300]


def drive_configurado() -> bool:
    return _google_ok() and bool(config.MUTIRAO_DRIVE_PASTA)


def salvar_no_drive(nome: str, mime: str, dados: bytes) -> tuple[str | None, str | None]:
    """Grava um arquivo na pasta do mutirão (Drive da Secretaria) pelo Apps Script. Devolve (id, erro)."""
    req = urllib.request.Request(
        config.EMAIL_GOOGLE_URL,
        data=json.dumps({"segredo": config.EMAIL_GOOGLE_SEGREDO, "acao": "drive", "pasta": config.MUTIRAO_DRIVE_PASTA,
                         "nome": nome, "mime": mime, "dados": base64.b64encode(dados).decode()}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            texto = r.read().decode("utf-8", "replace")
        try:
            resposta = json.loads(texto)
        except ValueError:
            return None, "resposta inesperada do Google"
        if resposta.get("ok") and resposta.get("id"):
            return str(resposta["id"]), None
        return None, f"Google: {resposta.get('erro') or 'o script ainda não tem a função do Drive'}"[:300]
    except urllib.error.HTTPError as e:
        return None, f"Google HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"[:300]


def _email_brevo(destino: str, assunto: str, corpo: str) -> str | None:
    req = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=json.dumps({"sender": {"email": config.EMAIL_REMETENTE, "name": config.EMAIL_NOME},
                         "to": [{"email": destino}], "subject": assunto, "textContent": corpo}).encode(),
        headers={"api-key": config.BREVO_API_KEY, "Content-Type": "application/json",
                 "Accept": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return None if 200 <= r.status < 300 else f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return f"Brevo HTTP {e.code}: {e.read().decode('utf-8', 'replace')}"[:300]
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {e}"[:300]


def _email_smtp(destino: str, assunto: str, corpo: str) -> str | None:
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


def enviar_email(destino: str, assunto: str, corpo: str) -> str | None:
    if not email_configurado():
        return "e-mail não configurado"
    from . import uso
    # Gmail comum aceita 100 destinatários por dia no Apps Script: no limite, passa para o Brevo até a meia-noite
    google = _google_ok() and not (_brevo_ok() and uso.hoje("email_google") >= config.LIMITE_EMAIL_GOOGLE_DIA)
    if google:
        canal, erro = "email_google", _email_google(destino, assunto, corpo)
    elif _brevo_ok():
        if uso.hoje("email_brevo") >= config.LIMITE_EMAIL_BREVO_DIA:
            return "limite diário de e-mails atingido; tente amanhã"
        canal, erro = "email_brevo", _email_brevo(destino, assunto, corpo)
    else:
        canal, erro = "email_smtp", _email_smtp(destino, assunto, corpo)
    uso.contar(canal)
    if erro:
        uso.contar("email_falha")
    return erro


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
