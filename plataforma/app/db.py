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
    JSON, BigInteger, Boolean, Column, cast, Date, DateTime, Float, ForeignKey, Integer, MetaData,
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
    Column("cpf", String(11), unique=True),  # só dígitos; identifica quem não tem ficha (equipe)
    Column("tentativas_falhas", Integer, nullable=False, default=0),
    Column("bloqueado_ate", DateTime(timezone=True)),
    Column("ultimo_login", DateTime(timezone=True)),
    Column("origem", String),  # 'novo', 'agenda:administradores#ID', 'membros_app:usuarios#ID'
    Column("email_avisos", Boolean, nullable=False, default=True),  # resumo diário dos avisos por e-mail
    Column("criado_em", DateTime(timezone=True), server_default=func.now()),
)

membros = Table(
    "membros", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("data_registro", Date),
    # 1. Dados pessoais
    Column("nome_completo", String, nullable=False),
    Column("cpf", String(11), unique=True),  # só dígitos; identificação única de cada membro
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
    Column("origem", String),  # 'novo', 'ficha_impressa' ou 'membros_app:membros#ID'
    # Ficha impressa original escaneada (data URL de imagem ou PDF), para auditoria
    Column("ficha_escaneada", Text),
    Column("ficha_escaneada_em", DateTime(timezone=True)),
    Column("ficha_escaneada_por", String),
    # LGPD: o membro pode recusar a homenagem de aniversário (some dos avisos, do calendário e das mensagens)
    Column("homenagem_aniversario", Boolean, nullable=False, default=True),
    # v2.9.0: inativação e exclusão (lixeira) sempre com justificativa
    Column("inativado_em", DateTime(timezone=True)),
    Column("inativado_por", String(120)),
    Column("motivo_inativacao", Text),
    Column("excluido_em", DateTime(timezone=True)),
    Column("excluido_por", String(120)),
    Column("motivo_exclusao", Text),
    Column("status_anterior", String(40)),  # para restaurar da lixeira ou reativar
    Column("login_suspenso", Boolean, nullable=False, default=False),  # o login foi desligado pela inativação/exclusão
    # v2.11.0: Dia do Profissional ("dd/mm") e intenção de dízimo (só Secretaria/Adm veem)
    Column("dia_profissional", String(5)),
    Column("homenagem_profissional", Boolean, nullable=False, default=True),
    Column("deseja_dizimista", String(20)),  # Sim | Não | Já sou dizimista
    Column("dia_dizimo", Integer),  # dia do mês preferido para a entrega
    # v2.12.0: INTEGRA como porta de entrada (ver app/integra.py)
    Column("integra_situacao", String(30)),  # concluido | nao_concluido | aguardando | dispensado | bloqueado
    Column("integra_data", Date),
    Column("integra_turma_id", Integer),
    Column("integra_registrado_por", String(120)),
    Column("integra_registrado_em", DateTime(timezone=True)),
    Column("integra_justificativa", Text),
    Column("integra_pedido_em", DateTime(timezone=True)),  # campanha para quem já tinha cadastro
    Column("integra_prazo", Date),
    Column("integra_lembrete_em", DateTime(timezone=True)),
    Column("credo_email_em", DateTime(timezone=True)),  # v2.13.0: e-mail com o link do Credo (mutirão)
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
    # v2.9.0: cada linha é uma designação de Coordenação com tipo e prazo (migração 012)
    Column("tipo", String(20), nullable=False, default="permanente"),  # permanente | periodo | evento
    Column("inicio", Date),
    Column("fim", Date),  # vazio = até nova decisão
    Column("evento_id", String(64)),  # tipo 'evento': só este evento
    Column("observacao", Text),
    Column("disponibilidade", Boolean, nullable=False, default=False),  # a pessoa se dispôs a servir no setor
    Column("criado_por", String(120)),
    Column("criado_em", DateTime(timezone=True), server_default=func.now()),
    UniqueConstraint("usuario_id", "departamento_id", name="uq_usuario_setor"),
)

# Coordenações encerradas (pelo prazo ou por decisão da Secretaria/Adm). Nada se perde.
coordenacoes_historico = Table(
    "coordenacoes_historico", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("usuario_id", Integer),
    Column("usuario_nome", String(160)),
    Column("departamento_id", String(64)),
    Column("setor_nome", String(160)),
    Column("tipo", String(20)),
    Column("inicio", Date),
    Column("fim", Date),
    Column("evento_id", String(64)),
    Column("evento_titulo", String(200)),
    Column("observacao", Text),
    Column("criado_por", String(120)),
    Column("criado_em", DateTime(timezone=True)),
    Column("encerrado_em", DateTime(timezone=True), server_default=func.now()),
    Column("encerrado_por", String(120)),
    Column("motivo_encerramento", Text),
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

# Links exclusivos de atualização cadastral (fichas impressas antigas)
regularizacoes = Table(
    "regularizacoes", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("membro_id", Integer, ForeignKey("membros.id", ondelete="CASCADE"), nullable=False),
    Column("segredo", String(64), nullable=False),  # com a SECRET_KEY gera o token do link
    Column("criado_em", DateTime(timezone=True), server_default=func.now()),
    Column("criado_por", String),
    Column("expira_em", DateTime(timezone=True), nullable=False),
    Column("enviado_em", DateTime(timezone=True)),
    Column("canais", String),  # ex.: "email, whatsapp"
    Column("concluido_em", DateTime(timezone=True)),
    Column("revogado", Boolean, nullable=False, default=False),
    Column("desfecho", String),  # quem não atualizou no prazo: em_analise | inativado
)

# Lembretes por e-mail de quem fez o pré-cadastro sem foto (etapas: d0, d1, d10, d25, d29, d30, s1, s2...)
lembretes_cadastro = Table(
    "lembretes_cadastro", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("membro_id", Integer, ForeignKey("membros.id", ondelete="CASCADE"), nullable=False),
    Column("etapa", String(10), nullable=False),
    Column("enviado_em", DateTime(timezone=True), server_default=func.now()),
    Column("resultado", String),
    UniqueConstraint("membro_id", "etapa", name="lembretes_cadastro_unico"),
)

# Setores em que o membro deseja servir (nomes padronizados de ficha.SETORES_INTERESSE)
membro_interesses = Table(
    "membro_interesses", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("membro_id", Integer, ForeignKey("membros.id", ondelete="CASCADE"), nullable=False),
    Column("setor", String(80), nullable=False),
    Column("criado_em", DateTime(timezone=True), server_default=func.now()),
    UniqueConstraint("membro_id", "setor", name="membro_interesses_unico"),
)

# Pesquisa de satisfação enviada no e-mail de boas-vindas (uma resposta por membro; pode mudar depois)
pesquisa_satisfacao = Table(
    "pesquisa_satisfacao", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("membro_id", Integer, ForeignKey("membros.id", ondelete="CASCADE"), nullable=False, unique=True),
    Column("resposta", String(20), nullable=False),  # bom | regular | ruim | nao_opinar
    Column("respondido_em", DateTime(timezone=True), server_default=func.now()),
)

# Central de Relatórios: combinações de filtros salvas por usuário ("⭐ Meus filtros")
relatorios_salvos = Table(
    "relatorios_salvos", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("usuario_id", Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
    Column("nome", String(80), nullable=False),
    Column("relatorio", String(40), nullable=False),
    Column("consulta", Text, nullable=False, default=""),  # parâmetros do endereço (filtros, ordem, colunas)
    Column("criado_em", DateTime(timezone=True), server_default=func.now()),
)

# Aniversariantes (v2.8.0): avisos do sino/janela, modelos de mensagem e mensagens enviadas
avisos = Table(
    "avisos", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("usuario_id", Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False),
    Column("tipo", String(30), nullable=False),  # aniversario_amanha | aniversario_hoje
    Column("membro_id", Integer, ForeignKey("membros.id", ondelete="CASCADE")),
    Column("referencia", Date, nullable=False),  # dia do aniversário
    Column("janela", Boolean, nullable=False, default=False),  # também aparece na janela (não só no sino)
    Column("criado_em", DateTime(timezone=True), server_default=func.now()),
    Column("lido_em", DateTime(timezone=True)),
    Column("email_em", DateTime(timezone=True)),  # entrou no e-mail resumo
    UniqueConstraint("usuario_id", "tipo", "membro_id", "referencia", name="avisos_unico"),
)

mensagens_modelo = Table(
    "mensagens_modelo", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("tipo", String(30), nullable=False, default="aniversario"),
    Column("titulo", String(80), nullable=False),
    Column("texto", Text, nullable=False),
    Column("ativo", Boolean, nullable=False, default=True),
    Column("padrao", Boolean, nullable=False, default=False),  # usado no e-mail automático do Ministério
    Column("criado_por", String(120)),
    Column("atualizado_em", DateTime(timezone=True), server_default=func.now()),
)

aniversario_envios = Table(
    "aniversario_envios", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("membro_id", Integer, ForeignKey("membros.id", ondelete="CASCADE"), nullable=False),
    Column("ano", Integer, nullable=False),
    Column("canal", String(20), nullable=False),  # whatsapp | email | copia | email_auto
    Column("usuario_id", Integer, ForeignKey("usuarios.id", ondelete="SET NULL")),
    Column("usuario_nome", String(120)),
    Column("enviado_em", DateTime(timezone=True), server_default=func.now()),
    Column("resultado", Text),
    Column("chave", String(60), unique=True),  # só no e-mail automático: trava de 1 por ano
)

# Uso dos serviços gratuitos (v2.8.0): contadores por dia, gravados pelo /healthz
uso_diario = Table(
    "uso_diario", metadata,
    Column("dia", Date, primary_key=True),
    Column("chave", String(40), primary_key=True),  # banda_bytes | requisicoes | email_google | email_brevo | email_smtp | email_falha
    Column("valor", BigInteger, nullable=False, default=0),
)

# Pesquisa mensal de necessidades (v2.11.0). Respostas anônimas: a resposta não guarda quem respondeu;
# o controle guarda só quem já respondeu em cada mês, sem ligação com a resposta.
necessidades_controle = Table(
    "necessidades_controle", metadata,
    Column("mes", String(7), primary_key=True),  # AAAA-MM
    Column("usuario_id", Integer, ForeignKey("usuarios.id", ondelete="CASCADE"), primary_key=True),
)
necessidades_respostas = Table(
    "necessidades_respostas", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("mes", String(7), nullable=False),
    Column("faixa", String(30)),
    Column("comentario", Text),
    Column("nenhuma", Boolean, nullable=False, default=False),  # "Neste mês estou bem"
    Column("contato_usuario_id", Integer, ForeignKey("usuarios.id", ondelete="SET NULL")),  # só se pediu contato
)
necessidades_itens = Table(
    "necessidades_itens", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("resposta_id", Integer, ForeignKey("necessidades_respostas.id", ondelete="CASCADE"), nullable=False),
    Column("categoria", String(30), nullable=False),
    Column("intensidade", Integer, nullable=False, default=2),  # 1 pouca · 2 média · 3 muita
)

# Instituto (v2.11.0): estrutura reservada para o futuro módulo; ainda sem telas de cadastro.
instituto_cursos = Table(
    "instituto_cursos", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("nome", String(160), nullable=False),
    Column("descricao", Text),
    Column("ativo", Boolean, nullable=False, default=True),
    Column("criado_em", DateTime(timezone=True), server_default=func.now()),
)
instituto_turmas = Table(
    "instituto_turmas", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("curso_id", Integer, ForeignKey("instituto_cursos.id", ondelete="CASCADE"), nullable=False),
    Column("nome", String(160), nullable=False),
    Column("inicio", Date), Column("fim", Date),
)
instituto_matriculas = Table(
    "instituto_matriculas", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("turma_id", Integer, ForeignKey("instituto_turmas.id", ondelete="CASCADE"), nullable=False),
    Column("membro_id", Integer, ForeignKey("membros.id", ondelete="CASCADE"), nullable=False),
    Column("situacao", String(30), nullable=False, default="Matriculado"),
    UniqueConstraint("turma_id", "membro_id", name="instituto_matricula_unica"),
)

integra_turmas = Table(
    "integra_turmas", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("nome", String(120), nullable=False),
    Column("data_conclusao", Date, nullable=False),
    Column("local", String(120)),
    Column("codigo", String(10), nullable=False, unique=True),
    Column("codigo_valido_ate", DateTime(timezone=True), nullable=False),
    Column("criado_por", String(120)),
    Column("criado_em", DateTime(timezone=True), server_default=func.now()),
)

# v2.13.0: mutirão de fichas históricas (lançadas por voluntárias com o link do lote)
mutirao_lotes = Table(
    "mutirao_lotes", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("nome", String(120), nullable=False),
    Column("justificativa", Text, nullable=False),
    Column("codigo", String(10), nullable=False, unique=True),
    Column("valido_ate", DateTime(timezone=True), nullable=False),
    Column("criado_por", String(120)),
    Column("criado_em", DateTime(timezone=True), server_default=func.now()),
)

# v2.12.0: quem não concluiu o INTEGRA fica fora da análise, sem login e sem agenda
NC_INTEGRA = "N/C INTEGRA"
STATUS_MEMBRO = (NC_INTEGRA, "Aguardando Análise", "Validado pela Secretaria", "Ativo", "Inativo", "Anonimizado (LGPD)")
# Ficha na lixeira (v2.9.0): some das listas, relatórios e avisos; a Secretaria/Adm pode restaurar
EXCLUIDO = "Excluído"
ANONIMIZADO = "Anonimizado (LGPD)"
# Fichas que não entram em avisos, lembretes, voluntários e listas de ativos
STATUS_FORA = ("Inativo", ANONIMIZADO, EXCLUIDO)

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

    Hoje: 003 (Coordenação), 004 (id de setor como texto) e 005 (colunas que faltam na Agenda legada)
    006 (CPF em membros e usuários)
    007 (regularização de fichas antigas), 008 (lembretes de cadastro e setores de interesse)
    009 (filtros salvos da Central de Relatórios), 010 (aniversariantes), 011 (uso dos serviços)
    012 (Coordenação por período/evento e inativação/exclusão de membros) e 013 (Dia do Profissional,
    intenção de dízimo, pesquisa mensal de necessidades e Instituto) e 014 (INTEGRA).
    Só cria/alarga; nunca remove dados. Se falhar, o app sobe mesmo assim e registra o erro.
    """
    import logging
    import os
    eng = engine()
    if eng.dialect.name != "postgresql":
        return
    pasta = os.path.join(os.path.dirname(os.path.dirname(__file__)), "migracoes")
    for nome in ("003_coordenacao.sql", "004_setor_texto.sql", "005_colunas_agenda.sql", "006_cpf.sql", "007_regularizacao.sql",
                 "008_lembretes_interesses.sql", "009_relatorios_salvos.sql", "010_aniversariantes.sql",
                 "011_uso_servicos.sql", "012_coordenacao_membros.sql", "013_fase_a.sql", "014_integra.sql",
                 "015_mutirao.sql"):
        try:
            with open(os.path.join(pasta, nome), encoding="utf-8") as f:
                sql = f.read()
            with eng.begin() as c:
                c.exec_driver_sql(sql)
        except Exception:  # noqa: BLE001
            logging.getLogger("mevam").exception("Falha ao aplicar a migração %s", nome)
