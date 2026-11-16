"""Popula um banco SQLite LOCAL com dados fictícios para testar as telas. Recusa rodar contra Postgres."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import insert  # noqa: E402

from app import datas, db  # noqa: E402
from app.rotas.admin import criar_usuario  # noqa: E402

if db.engine().dialect.name != "sqlite":
    sys.exit("Este script só roda em banco SQLite local de desenvolvimento.")

db.criar_tabelas_dev()
with db.engine().begin() as c:
    for nome, resp in [("Família", "Pr. João"), ("Jovens", "Lia"), ("Louvor", "Davi"), ("Infantil", "Ruth")]:
        c.execute(insert(db.departamentos).values(nome=nome, responsavel=resp))
    for perfil in db.PERFIS:
        criar_usuario(c, f"Demo {db.PERFIS_ROTULO[perfil]}", f"{perfil}@demo.local", perfil, senha="Demo1234")
    c.execute(db.usuarios.update().values(trocar_senha=False))
    hoje = datas.hoje()
    for i, (t, d, h) in enumerate([("Culto da Família", "Família", "19:30"), ("Family Day", "Família", "09:00"),
                                   ("Encontro de Jovens", "Jovens", "20:00"), ("Ensaio Geral", "Louvor", "18:00")]):
        dia = hoje.replace(day=min(5 + i * 6, 28))
        c.execute(insert(db.eventos).values(titulo=t, departamento=d, data_inicio=datas.iso_evento(dia, datas.parse_hora(h)),
                                            valor_inscricao=50.0 if i == 1 else 0, limite_vagas=120 if i == 1 else 0,
                                            criado_por="Demo Secretaria", historico_alteracoes="[Demo] Criado"))
    for i, (nome, st) in enumerate([("Maria da Silva Souza", "Aguardando Análise"), ("José Pereira Lima", "Ativo"),
                                    ("Ana Clara Rocha", "Validado pela Secretaria")]):
        c.execute(insert(db.membros).values(nome_completo=nome, status=st, data_registro=hoje, whatsapp="(62) 99999-000%d" % i,
                                            bairro="Setor Bueno", cidade="Goiânia - GO", email=f"m{i}@demo.local",
                                            data_nascimento=datas.parse_data("15/03/1985"), sexo="Feminino",
                                            batizado="Sim", lgpd_consentimento=True, credo_aceito=st == "Ativo",
                                            criado_em=datas.agora_utc(), atualizado_em=datas.agora_utc(), filhos=[]))
print("Pronto. Logins: admin@demo.local / secretaria@demo.local / membro@demo.local, senha Demo1234")
