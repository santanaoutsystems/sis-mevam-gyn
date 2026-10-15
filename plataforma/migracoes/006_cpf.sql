-- CPF para identificação única de membros e da equipe (formato 000.000.000-00).
-- Aditiva e idempotente: só cria o que falta, nunca altera nem apaga dados.
-- Cadastros antigos ficam sem CPF até a própria pessoa (tela "Meu CPF") ou a Secretaria informar.
alter table public.membros  add column if not exists cpf text;
alter table public.usuarios add column if not exists cpf text;

-- Um CPF não pode se repetir na mesma tabela (vazios são permitidos)
create unique index if not exists uq_membros_cpf  on public.membros  (cpf) where cpf is not null;
create unique index if not exists uq_usuarios_cpf on public.usuarios (cpf) where cpf is not null;
