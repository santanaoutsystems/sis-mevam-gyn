-- Garante nas tabelas legadas da Agenda as colunas que a plataforma usa.
-- Aditiva e idempotente: só cria o que falta, nunca altera nem apaga dados.
-- (No Supabase, inscricoes.observacoes não existia: as tabelas de inscrições e despesas estavam vazias.)
alter table public.eventos       add column if not exists departamento text;
alter table public.eventos       add column if not exists valor_inscricao double precision default 0;
alter table public.eventos       add column if not exists limite_vagas integer default 0;
alter table public.eventos       add column if not exists criado_por text;
alter table public.eventos       add column if not exists historico_alteracoes text;
alter table public.eventos       add column if not exists descricao text;
alter table public.eventos       add column if not exists local text;

alter table public.inscricoes    add column if not exists telefone text;
alter table public.inscricoes    add column if not exists forma_pagamento text;
alter table public.inscricoes    add column if not exists status_pagamento text;
alter table public.inscricoes    add column if not exists tipo_ingresso text;
alter table public.inscricoes    add column if not exists valor_pago double precision default 0;
alter table public.inscricoes    add column if not exists observacoes text;
alter table public.inscricoes    add column if not exists membro_id bigint;

alter table public.custos_evento add column if not exists descricao text;
alter table public.custos_evento add column if not exists valor double precision default 0;
