-- 016 (v2.15.0): estrutura oficial de Ministérios e Áreas.
-- Aditiva e idempotente: só acrescenta colunas. Nenhum dado existente é apagado.
-- Os nomes oficiais, as categorias e a lotação de Secretaria/Adm são aplicados pelo próprio
-- sistema na subida (app/areas.py, uma única vez, registrado na Auditoria como AREAS_OFICIAIS_V1).

alter table public.departamentos add column if not exists categoria varchar(40);
alter table public.departamentos add column if not exists ordem integer;
alter table public.departamentos add column if not exists ativo boolean not null default true;
alter table public.usuarios add column if not exists area_id varchar(64);
