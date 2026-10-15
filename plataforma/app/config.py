"""
Configuração da Plataforma Unificada SIS MEVAM-GYN.

Todos os segredos vêm de variáveis de ambiente. Nada sensível fica no código.
"""

import os
import secrets


class ConfiguracaoInvalida(RuntimeError):
    pass


def _bool(valor: str | None, padrao: bool = False) -> bool:
    if valor is None:
        return padrao
    return valor.strip().lower() in ("1", "true", "sim", "yes", "on")


AMBIENTE = os.getenv("AMBIENTE", "desenvolvimento")  # desenvolvimento | homologacao | producao
EM_PRODUCAO = AMBIENTE in ("homologacao", "producao")

# Banco único. Em produção: string de conexão Postgres do Supabase
# (Project Settings > Database > Connection string, modo "Session pooler").
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./plataforma_dev.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len("postgres://"):]
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len("postgresql://"):]

SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    if EM_PRODUCAO:
        raise ConfiguracaoInvalida(
            "SECRET_KEY não definida. Gere uma com: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )
    # Em desenvolvimento, uma chave aleatória por execução (sessões caem a cada reinício).
    SECRET_KEY = secrets.token_urlsafe(48)

FUSO_HORARIO = "America/Sao_Paulo"
URL_BASE = os.getenv("URL_BASE", "http://localhost:8000").rstrip("/")

# Sessão
SESSAO_MAX_SEGUNDOS = int(os.getenv("SESSAO_MAX_SEGUNDOS", str(60 * 60 * 12)))  # 12 horas
COOKIE_SEGURO = _bool(os.getenv("COOKIE_SEGURO"), padrao=EM_PRODUCAO)

# Proteção contra força bruta no login
LOGIN_MAX_TENTATIVAS = int(os.getenv("LOGIN_MAX_TENTATIVAS", "5"))
LOGIN_BLOQUEIO_MINUTOS = int(os.getenv("LOGIN_BLOQUEIO_MINUTOS", "15"))

# E-mail (opcional). Use senha de app do Gmail guardada como variável de ambiente.
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORTA = int(os.getenv("SMTP_PORTA", "587"))
SMTP_USUARIO = os.getenv("SMTP_USUARIO", "")
SMTP_SENHA = os.getenv("SMTP_SENHA", "")

VERSAO_TERMO_LGPD = "v2.0-2026"
VERSAO_APP = "2.0.0-unificada"
