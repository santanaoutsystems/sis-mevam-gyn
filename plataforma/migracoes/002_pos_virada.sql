-- =============================================================================
-- SIS MEVAM-GYN · Migração 002 · Fechamento após a virada
-- Rodar SOMENTE depois que a plataforma unificada estiver em uso e o app
-- Streamlit (agenda-mevam) for desligado: a partir daqui a chave pública
-- do Supabase deixa de ler as tabelas da Agenda, e o Streamlit para de funcionar.
-- Faça um backup novo antes (scripts/backup_supabase.py).
-- =============================================================================
begin;

alter table public.eventos         enable row level security;
alter table public.inscricoes      enable row level security;
alter table public.custos_evento   enable row level security;
alter table public.departamentos   enable row level security;
alter table public.administradores enable row level security;
alter table public.logs_auditoria  enable row level security;
revoke all on public.eventos, public.inscricoes, public.custos_evento, public.departamentos,
              public.administradores, public.logs_auditoria from anon, authenticated;

commit;

-- Opcional, depois de conferir que todos entram na plataforma nova:
-- as senhas antigas em texto puro deixam de ser necessárias (LGPD / segurança).
-- update public.administradores set senha = null;
