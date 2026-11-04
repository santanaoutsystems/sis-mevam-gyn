"""v2.16.3: possíveis fichas duplicadas (caso real: 'Alessandra Nunes R Netto' x 'Alessandra Nunes Rosa Netto')."""
from sqlalchemy import insert, select

from app import datas, db, duplicidade
from conftest import logado, post
from test_mutirao import _criar_lote, _fichas, _lancar, _voluntaria
from test_plataforma import gerar_cpf


def _ficha(**kw):
    v = dict(nome_completo="Alessandra Nunes Rosa Netto", status="Ativo", data_nascimento=datas.parse_data("11/04/1973"),
             whatsapp="(62) 9 8475-1751", bairro="Jardim América", data_registro=datas.hoje(), credo_aceito=True,
             lgpd_consentimento=True, filhos=[], criado_em=datas.agora_utc(), atualizado_em=datas.agora_utc())
    v.update(kw)
    with db.engine().begin() as c:
        return c.execute(insert(db.membros).values(**v)).inserted_primary_key[0]


def test_nomes_compativeis():
    f = duplicidade.nomes_compativeis
    assert f("Alessandra Nunes R Netto", "Alessandra Nunes Rosa Netto")
    assert f("Maria Souza", "Maria da Silva Souza") and f("José Pereira Lima", "Jose Pereira Lima")
    assert not f("Maria Souza", "Mariana Souza") and not f("Ana Rocha", "Ana Lima")


def test_motivos_e_familia_com_mesmo_whatsapp():
    a = {"nome_completo": "Alessandra Nunes R Netto", "data_nascimento": datas.parse_data("11/04/1973"), "whatsapp": "62984751751"}
    b = {"nome_completo": "Alessandra Nunes Rosa Netto", "data_nascimento": datas.parse_data("11/04/1973"), "whatsapp": "(62) 9 8475-1751"}
    assert duplicidade.motivo(a, b)
    filha = {"nome_completo": "Beatriz Nunes Netto", "data_nascimento": datas.parse_data("02/02/2000"), "whatsapp": "62984751751"}
    assert not duplicidade.motivo(a, filha)
    assert not duplicidade.motivo({**a, "cpf": gerar_cpf(111111112)}, {**b, "cpf": gerar_cpf(222222223)})


def test_mutirao_barra_nome_abreviado_e_libera_com_confirmacao():
    _ficha()
    _, lt = _criar_lote()
    cli = _voluntaria(lt["codigo"])
    dados = dict(nome_completo="Alessandra Nunes R Netto", data_nascimento="11/04/1973", whatsapp="62984751751")
    r = _lancar(cli, lt["codigo"], **dados)
    assert r.status_code == 400 and "já está no sistema" in r.text and "outra_pessoa" in r.text
    assert _fichas(lt["id"]) == []
    assert _lancar(cli, lt["codigo"], outra_pessoa="sim", **dados).status_code == 303
    assert len(_fichas(lt["id"])) == 1


def test_aviso_lista_e_juntar():
    fica = _ficha()
    rep = _ficha(nome_completo="Alessandra Nunes R Netto", status="Aguardando Análise", bairro=None, credo_aceito=False,
                 cpf=gerar_cpf(456789123), email="ale@exemplo.com")
    sec = logado("secretaria")
    assert "Possíveis duplicados (1)" in sec.get("/membros").text
    assert f"#{fica}" in sec.get("/membros/duplicados").text
    html = sec.get(f"/membros/{rep}").text
    assert "Possível ficha repetida" in html and f"Juntar esta ficha na #{fica}" in html
    # sem confirmação não junta
    r = post(sec, f"/membros/{rep}/juntar", {"manter": str(fica)}, pagina=f"/membros/{rep}")
    with db.engine().connect() as c:
        assert c.execute(select(db.membros.c.status).where(db.membros.c.id == rep)).scalar() == "Aguardando Análise"
    r = post(sec, f"/membros/{rep}/juntar", {"manter": str(fica), "confirmo": "sim"}, pagina=f"/membros/{rep}")
    assert r.status_code == 303 and r.headers["location"] == f"/membros/{fica}"
    with db.engine().connect() as c:
        m = {r["id"]: dict(r) for r in c.execute(select(db.membros)).mappings()}
        aud = c.execute(select(db.auditoria.c.acao).where(db.auditoria.c.acao == "FICHAS_JUNTADAS")).first()
    assert m[rep]["status"] == db.EXCLUIDO and m[rep]["cpf"] is None and "juntada na ficha" in m[rep]["motivo_exclusao"]
    assert m[fica]["cpf"] == gerar_cpf(456789123) and m[fica]["email"] == "ale@exemplo.com"
    assert m[fica]["bairro"] == "Jardim América" and m[fica]["status"] == "Ativo" and aud
    assert "Possíveis duplicados" not in sec.get("/membros").text


def test_juntar_recusa_cpfs_diferentes():
    a = _ficha(cpf=gerar_cpf(111111112))
    b = _ficha(nome_completo="Alessandra Nunes R Netto", cpf=gerar_cpf(222222223))
    sec = logado("secretaria")
    post(sec, f"/membros/{b}/juntar", {"manter": str(a), "confirmo": "sim"}, pagina=f"/membros/{b}")
    with db.engine().connect() as c:
        assert c.execute(select(db.membros.c.status).where(db.membros.c.id == b)).scalar() == "Ativo"
