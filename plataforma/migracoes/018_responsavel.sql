-- 018 (v2.17.0): responsável legal para membros menores de 18 anos (cadastro a partir de 15).
-- Aditiva e idempotente: só colunas novas, sem valor padrão. Nenhum dado existente é alterado.
alter table public.membros add column if not exists responsavel_nome varchar(120);
alter table public.membros add column if not exists responsavel_cpf varchar(14);
alter table public.membros add column if not exists responsavel_telefone varchar(30);
alter table public.membros add column if not exists responsavel_parentesco varchar(40);
alter table public.membros add column if not exists responsavel_ciencia_em timestamptz;
