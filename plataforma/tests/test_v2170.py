"""v2.17.0: jovens a partir de 15 anos; quem respondeu SAIR no WhatsApp fica visível para a Secretaria."""
from sqlalchemy import insert, select, update

from app import datas, db
from conftest import logado, post
from conftest import novo_cliente
from test_mutirao import _criar_lote, _fichas, _lancar, _voluntaria
from test_plataforma import enviar_ficha, membro_id_mais_recente


def test_mutirao_aceita_15_anos_e_recusa_14():
    _, lt = _criar_lote()
    cli = _voluntaria(lt["codigo"])
    d15 = (datas.hoje().replace(year=datas.hoje().year - 15) - __import__("datetime").timedelta(days=5)).strftime("%d/%m/%Y")
    d14 = (datas.hoje().replace(year=datas.hoje().year - 14)).strftime("%d/%m/%Y")
    r = _lancar(cli, lt["codigo"], nome_completo="Jovem Quinze", data_nascimento=d14)
    assert r.status_code == 400 and "Menor de 15 anos" in r.text
    assert _lancar(cli, lt["codigo"], nome_completo="Jovem Quinze", data_nascimento=d15).status_code == 400  # falta o responsável
    assert _lancar(cli, lt["codigo"], nome_completo="Jovem Quinze", data_nascimento=d15, responsavel_nome="Maria Souza Lima", responsavel_telefone="62999992222", responsavel_parentesco="Mãe", responsavel_ciencia="sim").status_code == 303
    assert len(_fichas(lt["id"])) == 1


def test_ficha_publica_aceita_15_anos():
    d15 = (datas.hoje().replace(year=datas.hoje().year - 15) - __import__("datetime").timedelta(days=5)).strftime("%d/%m/%Y")
    r = enviar_ficha(novo_cliente(), data_nascimento=d15)
    assert r.status_code == 400 and "responsável legal" in r.text  # menor sem responsável não envia
    enviar_ficha(novo_cliente(), data_nascimento=d15, responsavel_nome="Maria Souza Lima", responsavel_telefone="62999992222", responsavel_parentesco="Mãe", responsavel_ciencia="sim")
    m = membro_id_mais_recente()
    with db.engine().connect() as c:
        row = c.execute(select(db.membros.c.responsavel_nome, db.membros.c.responsavel_ciencia_em).where(db.membros.c.id == m)).one()
    assert row.responsavel_nome == "Maria Souza Lima" and row.responsavel_ciencia_em is not None


def test_pediram_sair_aparece_na_lista_e_na_ficha():
    with db.engine().begin() as c:
        mid = c.execute(insert(db.membros).values(nome_completo="Pessoa Que Saiu", status="Aguardando Análise",
              data_registro=datas.hoje(), whatsapp="62999991111", lgpd_consentimento=True, filhos=[],
              whatsapp_situacao="nao_quer", whatsapp_situacao_em=datas.agora_utc(),
              criado_em=datas.agora_utc(), atualizado_em=datas.agora_utc())).inserted_primary_key[0]
    sec = logado("secretaria")
    assert "Pediram SAIR no WhatsApp (1)" in sec.get("/membros").text
    assert "Pessoa Que Saiu" in sec.get("/membros/pediram-sair").text
    assert "Pediu SAIR no WhatsApp" in sec.get(f"/membros/{mid}").text


def test_ficha_incompleta_mostra_excluir_em_destaque():
    with db.engine().begin() as c:
        mid = c.execute(insert(db.membros).values(nome_completo="Sem Contato Mais", status="Aguardando Análise",
              data_registro=datas.hoje(), lgpd_consentimento=True, filhos=[],
              criado_em=datas.agora_utc(), atualizado_em=datas.agora_utc())).inserted_primary_key[0]
    sec = logado("secretaria")
    assert "Excluir ficha incompleta" in sec.get(f"/membros/{mid}").text
