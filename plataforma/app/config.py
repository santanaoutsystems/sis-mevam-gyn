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
# Em homologação/produção o banco precisa ser o Postgres do Supabase. SQLite no Render gratuito fica num
# disco temporário que é apagado a cada publicação ou reinício (foi assim que o app antigo perdeu fichas).
if EM_PRODUCAO and not DATABASE_URL.startswith("postgresql+psycopg://"):
    raise ConfiguracaoInvalida(
        "Em homologação/produção, DATABASE_URL deve apontar para o Postgres do Supabase. "
        "Arquivo SQLite no servidor é apagado a cada publicação ou reinício."
    )

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

VERSAO = "2.4.2"

# Sessão
# Sem uso por este tempo, o acesso é bloqueado e é preciso entrar de novo.
# Quem vê dados pessoais (Secretaria e Adm) tem um tempo menor.
INATIVIDADE_MIN_GESTAO = int(os.getenv("INATIVIDADE_MIN_GESTAO", "15"))
INATIVIDADE_MIN_PADRAO = int(os.getenv("INATIVIDADE_MIN_PADRAO", "30"))
SESSAO_MAX_SEGUNDOS = int(os.getenv("SESSAO_MAX_SEGUNDOS", str(60 * 60 * 12)))  # 12 horas
COOKIE_SEGURO = _bool(os.getenv("COOKIE_SEGURO"), padrao=EM_PRODUCAO)

# Proteção contra força bruta no login
LOGIN_MAX_TENTATIVAS = int(os.getenv("LOGIN_MAX_TENTATIVAS", "5"))
LOGIN_BLOQUEIO_MINUTOS = int(os.getenv("LOGIN_BLOQUEIO_MINUTOS", "15"))

# E-mail (opcional). Use senha de app do Gmail guardada como variável de ambiente.
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORTA = int(os.getenv("SMTP_PORTA", "587"))
SMTP_USUARIO = os.getenv("SMTP_USUARIO", "")
SMTP_SENHA = os.getenv("SMTP_SENHA", "").replace(" ", "")  # senha de app do Google vem com espaços

# WhatsApp automático (opcional) pela Evolution API. Sem estas variáveis, o envio é manual (wa.me).
EVOLUTION_API_URL = os.getenv("EVOLUTION_API_URL", "").rstrip("/")
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "")
EVOLUTION_INSTANCIA = os.getenv("EVOLUTION_INSTANCIA", "")

# Regularização de fichas antigas: prazo padrão do link exclusivo
REGULARIZACAO_PRAZO_DIAS = int(os.getenv("REGULARIZACAO_PRAZO_DIAS", "30"))
# Testes: disparos sem thread em segundo plano
ENVIO_SINCRONO = os.getenv("ENVIO_SINCRONO", "") == "1"

# Primeiro acesso: cria o 1º Administrador pela página /primeiro-acesso (o Render gratuito não tem terminal).
# Só funciona enquanto não existir nenhum Administrador e exige este código. Apague a variável depois do uso.
CODIGO_PRIMEIRO_ACESSO = os.getenv("CODIGO_PRIMEIRO_ACESSO", "")

VERSAO_TERMO_LGPD = "v2.0-2026"
VERSAO_APP = "2.0.0-unificada"
