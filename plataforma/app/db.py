"""
Banco de dados único (Supabase Postgres em produção, SQLite em desenvolvimento/testes).

Tabelas LEGADAS da Agenda (já existem no Supabase e têm dados reais):
    departamentos, eventos, inscricoes, custos_evento, administradores, logs_auditoria
    -> São usadas como estão. Só recebem colunas NOVAS e opcionais (nunca removemos nem
       renomeamos colunas). Ver migracoes/001_unificacao.sql.

Tabelas NOVAS da plataforma:
    usuarios, membros, membro_setores, auditoria, usuario_setores
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON, Boolean, Column, cast, Date, DateTime, Float, ForeignKey, Integer, MetaData,
    String, Table, Text, UniqueConstraint, Uuid, FetchedValue, create_engine, func,
)
from sqlalchemy import text
from sqlalchemy.engine import Engine

from . import config

metadata = MetaData()

# ---------------------------------------------------------------------------
# Tabelas legadas da Agenda (Supabase)
# ---------------------------------------------------------------------------
departamentos = Table(
    "departamentos", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("nome", String, nullable=False),
    Column("responsavel", String),
)

eventos = Table(
    "eventos", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("titulo", String, nullable=False),
    # Texto ISO "AAAA-MM-DDTHH:MM:SS" no horário de Goiânia (formato legado preservado)
    Column("data_inicio", String, nullable=False),
    Column("departamento", String),
    Column("valor_inscricao", Float, default=0.0),
    Column("limite_vagas", Integer, default=0),
    Column("criado_por", String),
    Column("historico_alteracoes", Text),
    # Novas (opcionais)
    Column("descricao", Text),
    Column("local", String),
)

inscricoes = Table(
    "inscricoes", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("evento_id", Integer, nullable=False),
    Column("nome", String, nullable=False),
    Column("telefone", String),
    Column("forma_pagamento", String),
    Column("status_pagamento", String),
    Column("tipo_ingresso", String),
    Column("valor_pago", Float, default=0.0),
    Column("observacoes", Text),
    # Nova (opcional): liga a inscrição ao cadastro do membro, quando houver
    Column("membro_id", Integer),
)

custos_evento = Table(
    "custos_evento", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("evento_id", Integer, nullable=False),
    Column("descricao", String),
    Column("valor", Float, default=0.0),
)

# Somente leitura: usado apenas pelo script de migração de logins.
administradores = Table(
    "administradores", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("nome", String),
    Column("telefone", String),
    Column("email", String),
    Column("senha", String),
)

# ---------------------------------------------------------------------------
# Tabelas novas
# ---------------------------------------------------------------------------
usuarios = Table(
    "usuarios", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("nome", String, nullable=False),
    Column("email", String, nullable=False, unique=True),
    Column("senha_hash", String, nullable=False),
    Column("salt", String, nullable=False),
    Column("iteracoes", Integer, nullable=False, default=600_000),
    Column("perfil", String, nullable=False, default="membro"),  # membro | coordenacao | secretaria | admin
    Column("ativo", Boolean, nullable=False, default=True),
    Column("trocar_senha", Boolean, nullable=False, default=False),
    Column("membro_id", Integer, ForeignKey("membros.id", ondelete="SET NULL")),
    Column("tentativas_falhas", Integer, nullable=False, default=0),
    Column("bloqueado_ate", DateTime(timezone=True)),
    Column("ultimo_login", DateTime(timezone=True)),
    Column("origem", String),  # 'novo', 'agenda:administradores#ID', 'membros_app:usuarios#ID'
    Column("criado_em", DateTime(timezone=True), server_default=func.now()),
)

membros = Table(
    "membros", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("data_registro", Date),
    # 1. Dados pessoais
    Column("nome_completo", String, nullable=False),
    Column("endereco", String), Column("bairro", String), Column("cidade", String), Column("cep", String),
    Column("data_nascimento", Date), Column("naturalidade", String), Column("sexo", String),
    Column("estado_civil", String), Column("conjuge", String),
    Column("filhos", JSON),  # [{"nome":..., "data_nascimento":"dd/mm/aaaa"}]
    # 2. Contato e profissão
    Column("email", String), Column("telefone", String), Column("whatsapp", String),
    Column("escolaridade", String), Column("formacao_academica", String),
    Column("profissao", String), Column("empresa", String),
    # 3. Vida cristã
    Column("batizado", String), Column("data_batismo", Date),
    Column("congregava_antes", String), Column("onde_congregava", String),
    Column("area_ministerial", String), Column("interesse_batismo_familia", String),
    # Credo e rúbrica digital
    Column("credo_aceito", Boolean, nullable=False, default=False),
    Column("nome_assinante", String),
    Column("assinatura_rubrica", Text),
    Column("data_assinatura", DateTime(timezone=True)),
    Column("hash_autenticidade", String),
    # Documento lido por OCR
    Column("ocr_documento_nome", String),
    # Foto 3x4 (data URL). Próxima fase: Supabase Storage.
    Column("foto_3x4", Text),
    # LGPD
    Column("lgpd_consentimento", Boolean, nullable=False, default=False),
    Column("lgpd_versao_termo", String),
    Column("lgpd_data_consentimento", DateTime(timezone=True)),
    Column("lgpd_ip_origem", String),
    Column("status_lgpd", String, default="Consentimento Ativo"),
    # Fluxo da secretaria
    Column("status", String, nullable=False, default="Aguardando Análise"),
    Column("validado_por", String),
    Column("data_validacao", DateTime(timezone=True)),
    Column("link_credo_enviado", Boolean, nullable=False, default=False),
    Column("observacoes", Text),
    Column("origem", String),  # 'novo' ou 'membros_app:membros#ID'
    Column("criado_em", DateTime(timezone=True), server_default=func.now()),
    Column("atualizado_em", DateTime(timezone=True), server_default=func.now()),
)

membro_setores = Table(
    "membro_setores", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("membro_id", Integer, ForeignKey("membros.id", ondelete="CASCADE"), nullable=False),
    # Texto: o id da tabela legada 'departamentos' pode ser número ou UUID no Supabase
    Column("departamento_id", String, nullable=False),
    Column("funcao", String, default="Voluntário"),  # Líder | Voluntário | Apoio
    UniqueConstraint("membro_id", "departamento_id", name="uq_membro_setor"),
)

# Setores que cada usuário do perfil Coordenação pode gerenciar na agenda
usuario_setores = Table(
    "usuario_setores", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("usuario_id", Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
    Column("departamento_id", String, nullable=False),
    UniqueConstraint("usuario_id", "departamento_id", name="uq_usuario_setor"),
)

auditoria = Table(
    "auditoria", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("criado_em", DateTime(timezone=True), server_default=func.now()),
    Column("usuario_id", Integer),
    Column("usuario_nome", String),
    Column("acao", String, nullable=False),
    Column("recurso", String),
    Column("detalhes", Text),
    Column("ip", String),
)

# Id do setor sempre comparado como texto (funciona com id numérico ou UUID na tabela legada)
DEP_ID = cast(departamentos.c.id, String)


def texto(coluna):
    """Compara ids como texto: nas tabelas legadas do Supabase o id pode ser uuid em vez de número."""
    return cast(coluna, String)

PERFIS = ("membro", "coordenacao", "secretaria", "admin")
PERFIS_ROTULO = {"membro": "Membro", "coordenacao": "Coordenação", "secretaria": "Secretaria", "admin": "Adm"}
# Perfis que gerenciam a agenda. A Coordenação fica restrita aos seus setores (usuario_setores).
PERFIS_AGENDA = ("coordenacao", "secretaria", "admin")

STATUS_MEMBRO = ("Aguardando Análise", "Validado pela Secretaria", "Ativo", "Inativo", "Anonimizado (LGPD)")

_engine: Engine | None = None

# A coluna legada eventos.data_inicio pode ser texto ISO ou timestamp no Supabase.
# O tipo real é lido do banco na conexão e os valores são convertidos conforme ele.
_DATA_EVENTO = {"modo": "texto"}  # texto | timestamp | timestamptz


def _detectar_tipos(eng: Engine) -> None:
    if eng.dialect.name != "postgresql":
        return
    with eng.connect() as c:
        tipo = c.execute(text(
            "select data_type from information_schema.columns "
            "where table_schema='public' and table_name='eventos' and column_name='data_inicio'")).scalar()
        tipos_id = dict(c.execute(text(
            "select table_name || '.' || column_name, data_type from information_schema.columns "
            "where table_schema='public' and table_name in ('eventos', 'inscricoes', 'custos_evento') "
            "and column_name in ('id', 'evento_id')")).all())
    # Ids legados da Agenda podem ser uuid (ou texto) no Supabase, e não número.
    for nome, tipo_id in tipos_id.items():
        tabela, coluna = nome.split(".")
        col = metadata.tables[tabela].c[coluna]
        if tipo_id not in ("uuid", "text", "character varying"):
            continue
        col.type = Uuid(as_uuid=False) if tipo_id == "uuid" else String()
        if col.primary_key:
            # Gerado pelo banco (gen_random_uuid()), não por sequência numérica
            col.autoincrement = False
            col.server_default = FetchedValue()
    if tipo and tipo.startswith("timestamp"):
        com_fuso = "with time zone" in tipo and "without" not in tipo
        _DATA_EVENTO["modo"] = "timestamptz" if com_fuso else "timestamp"
        eventos.c.data_inicio.type = DateTime(timezone=com_fuso)
    elif tipo == "date":
        _DATA_EVENTO["modo"] = "date"
        eventos.c.data_inicio.type = Date()


def data_evento(iso: str):
    """Converte 'AAAA-MM-DDTHH:MM:SS' (horário de Goiânia) para o tipo da coluna eventos.data_inicio."""
    modo = _DATA_EVENTO["modo"]
    if modo == "texto":
        return iso
    dt = datetime.fromisoformat(iso)
    if modo == "date":
        return dt.date()
    if modo == "timestamptz":
        from zoneinfo import ZoneInfo
        return dt.replace(tzinfo=ZoneInfo(config.FUSO_HORARIO))
    return dt


def engine() -> Engine:
    global _engine
    if _engine is None:
        kwargs = {"future": True, "pool_pre_ping": True}
        if config.DATABASE_URL.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(config.DATABASE_URL, **kwargs)
        _detectar_tipos(_engine)
    return _engine


def definir_engine(novo: Engine) -> None:
    """Usado pelos testes."""
    global _engine
    _engine = novo


def criar_tabelas_dev() -> None:
    """Somente desenvolvimento/testes (SQLite). Em produção use migracoes/*.sql."""
    if engine().dialect.name == "sqlite":
        metadata.create_all(engine())


def aplicar_migracoes_aditivas() -> None:
    """Aplica no Postgres as migrações aditivas e idempotentes que não exigem passo manual.

    Hoje: migracoes/003_coordenacao.sql (perfil Coordenação + tabela usuario_setores).
    Só cria/alarga; nunca remove dados. Se falhar, o app sobe mesmo assim e registra o erro.
    """
    import logging
    import os
    eng = engine()
    if eng.dialect.name != "postgresql":
        return
    pasta = os.path.join(os.path.dirname(os.path.dirname(__file__)), "migracoes")
    for nome in ("003_coordenacao.sql", "004_setor_texto.sql"):
        try:
            with open(os.path.join(pasta, nome), encoding="utf-8") as f:
                sql = f.read()
            with eng.begin() as c:
                c.exec_driver_sql(sql)
        except Exception:  # noqa: BLE001
            logging.getLogger("mevam").exception("Falha ao aplicar a migração %s", nome)
