-- CPF como identificação única de cada membro e de cada pessoa da equipe.
-- Aditiva e idempotente: só cria colunas e índices; quem já tem cadastro informa o CPF em "Meu CPF".
-- Guardado só com os 11 dígitos. Vários registros sem CPF (NULL) continuam permitidos.
alter table public.membros  add column if not exists cpf varchar(11);
alter table public.usuarios add column if not exists cpf varchar(11);
create unique index if not exists membros_cpf_unico  on public.membros  (cpf) where cpf is not null;
create unique index if not exists usuarios_cpf_unico on public.usuarios (cpf) where cpf is not null;
