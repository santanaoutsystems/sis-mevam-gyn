-- =============================================================================
-- SIS MEVAM-GYN · Migração 004 · Id do setor como texto
-- O id da tabela legada 'departamentos' (Agenda) pode não ser numérico no Supabase.
-- Os vínculos passam a guardar o id como texto. Conversão sem perda (número -> texto).
-- Aplicada automaticamente ao iniciar; pode ser executada várias vezes.
-- =============================================================================
alter table public.membro_setores  alter column departamento_id type text using departamento_id::text;
alter table public.usuario_setores alter column departamento_id type text using departamento_id::text;
