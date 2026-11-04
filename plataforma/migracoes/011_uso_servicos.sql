-- 011 (v2.8.0): contadores diários de uso dos serviços gratuitos (Render, Supabase, e-mail).
-- Aditiva e idempotente: só cria a tabela.
create table if not exists public.uso_diario (
  dia    date        not null,
  chave  varchar(40) not null,  -- banda_bytes | requisicoes | email_google | email_brevo | email_smtp | email_falha
  valor  bigint      not null default 0,
  primary key (dia, chave)
);

alter table public.uso_diario enable row level security;
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    execute 'revoke all on public.uso_diario from anon, authenticated';
  end if;
end $$;
