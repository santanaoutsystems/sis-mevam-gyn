"""v2.13.0: mutirão de fichas históricas."""
from datetime import timedelta

from sqlalchemy import select, update

from app import config, datas, db, envios, seguranca
from conftest import csrf_de, logado, novo_cliente, post
from test_plataforma import gerar_cpf

FICHA = {"nome_completo": "joana d'arc pereira", "data_nascimento": "12/05/1970", "cpf": "",
         "whatsapp": "62999990001", "email": "", "arquivo": "Joana Pereira.pdf", "conferido": "sim"}


def _criar_lote():
    sec = logado("secretaria")
    r = post(sec, "/mutirao/lotes", {"nome": "Fichas históricas", "justificativa": "INTEGRA aprovado pelo pastor fundador.",
                                     "dias": "30"}, pagina="/mutirao")
    assert r.status_code == 303
    lid = int(r.headers["location"].rsplit("/", 1)[1])
    with db.engine().connect() as c:
        lt = c.execute(select(db.mutirao_lotes).where(db.mutirao_lotes.c.id == lid)).mappings().one()
    return sec, dict(lt)


def _voluntaria(codigo, nome="Ana Voluntária"):
    cli = novo_cliente()
    pag = cli.get(f"/mutirao/{codigo}")
    assert pag.status_code == 200 and "Seu nome completo" in pag.text
    cli.post(f"/mutirao/{codigo}", data={"acao": "identificar", "voluntaria": nome, "csrf": csrf_de(pag.text)})
    return cli


def _lancar(cli, codigo, **kw):
    pag = cli.get(f"/mutirao/{codigo}")
    return cli.post(f"/mutirao/{codigo}", data={**FICHA, **kw, "csrf": csrf_de(pag.text)}, follow_redirects=False)


def _email(monkeypatch):
    enviados = []
    monkeypatch.setattr(envios, "email_configurado", lambda: True)
    monkeypatch.setattr(envios, "enviar_email", lambda d, a, c: enviados.append((d, a, c)))
    monkeypatch.setattr(config, "ENVIO_SINCRONO", True)
    return enviados


def _fichas(lid):
    with db.engine().connect() as c:
        return [dict(r) for r in c.execute(select(db.membros).where(
            db.membros.c.origem.like(f"mutirao:{lid}:%"))).mappings()]


def test_voluntaria_lanca_ficha_validada_com_integra_historico():
    sec, lt = _criar_lote()
    cli = _voluntaria(lt["codigo"].lower())
    r = _lancar(cli, lt["codigo"])
    assert r.status_code == 303
    assert "Ficha de Joana salva" in cli.get(r.headers["location"]).text
    [m] = _fichas(lt["id"])
    assert m["nome_completo"] == "Joana D'arc Pereira" and m["status"] == "Validado pela Secretaria"
    assert m["integra_situacao"] == "concluido" and m["integra_justificativa"] == "INTEGRA aprovado pelo pastor fundador."
    assert m["validado_por"] == "Mutirão · Ana Voluntária" and not m["lgpd_consentimento"]
    assert m["ocr_documento_nome"] == "Joana Pereira.pdf"
    # A tela pública não mostra dados de ninguém; o painel do lote mostra a ficha e a voluntária
    assert "Joana D'arc Pereira" not in cli.get(f"/mutirao/{lt['codigo']}").text
    html = sec.get(f"/mutirao/lotes/{lt['id']}").text
    assert "Joana D&#39;arc Pereira" in html and "Ana Voluntária: 1" in html and "wa.me/5562999990001" in html


def test_regras_duplicada_menor_contato_e_conferencia():
    _, lt = _criar_lote()
    cli = _voluntaria(lt["codigo"])
    cpf = gerar_cpf(321654987)
    assert _lancar(cli, lt["codigo"], cpf=cpf).status_code == 303
    r = _lancar(cli, lt["codigo"], cpf=cpf, nome_completo="Outra Pessoa")
    assert r.status_code == 400 and "CPF" in r.text
    r = _lancar(cli, lt["codigo"])  # mesmo nome e nascimento
    assert r.status_code == 400 and "já está no sistema" in r.text
    menor = (datas.hoje() - timedelta(days=16 * 365)).strftime("%d/%m/%Y")
    r = _lancar(cli, lt["codigo"], nome_completo="Pedro Menor", data_nascimento=menor)
    assert r.status_code == 400 and "Menor de 18 anos" in r.text
    r = _lancar(cli, lt["codigo"], nome_completo="Sem Contato", whatsapp="", email="")
    assert r.status_code == 400 and "WhatsApp ou o e-mail" in r.text
    r = _lancar(cli, lt["codigo"], nome_completo="Nao Conferiu", conferido="")
    assert r.status_code == 400 and "Confira os dados" in r.text
    assert len(_fichas(lt["id"])) == 1


def test_link_encerrado_e_sem_identificacao():
    sec, lt = _criar_lote()
    assert novo_cliente().get("/mutirao/ZZZZZZ").status_code == 404
    # Sem informar o nome, não grava
    cli = novo_cliente()
    pag = cli.get(f"/mutirao/{lt['codigo']}")
    cli.post(f"/mutirao/{lt['codigo']}", data={**FICHA, "csrf": csrf_de(pag.text)})
    assert _fichas(lt["id"]) == []
    post(sec, f"/mutirao/lotes/{lt['id']}/validade", {"acao": "encerrar"}, pagina=f"/mutirao/lotes/{lt['id']}")
    assert novo_cliente().get(f"/mutirao/{lt['codigo']}").status_code == 410


def test_credo_em_lote_por_email_e_assinatura_com_lgpd(monkeypatch):
    enviados = _email(monkeypatch)
    sec, lt = _criar_lote()
    cli = _voluntaria(lt["codigo"])
    _lancar(cli, lt["codigo"], email="joana@mevam.test", whatsapp="")
    [m] = _fichas(lt["id"])
    assert post(sec, f"/mutirao/lotes/{lt['id']}/credo", {}, pagina=f"/mutirao/lotes/{lt['id']}").status_code == 303
    [m] = _fichas(lt["id"])
    assert m["credo_email_em"] and m["link_credo_enviado"]
    assert len(enviados) == 1 and enviados[0][0] == "joana@mevam.test" and f"/credo/{m['id']}?t=" in enviados[0][2]
    # Assinatura: na ficha de papel não há consentimento LGPD; ele é pedido junto com o Credo
    token = seguranca.token_link("credo", m["id"])
    pub = novo_cliente()
    pag = pub.get(f"/credo/{m['id']}?t={token}")
    assert 'name="lgpd_consentimento"' in pag.text
    base = {"t": token, "aceite": "sim", "nome_assinante": "Joana D'arc Pereira",
            "assinatura": "data:image/png;base64,iVBORw0KGgo="}
    pub.post(f"/credo/{m['id']}", data={**base, "csrf": csrf_de(pag.text)})
    assert not _fichas(lt["id"])[0]["credo_aceito"]
    pag = pub.get(f"/credo/{m['id']}?t={token}")
    pub.post(f"/credo/{m['id']}", data={**base, "lgpd_consentimento": "sim", "csrf": csrf_de(pag.text)})
    [m] = _fichas(lt["id"])
    assert m["credo_aceito"] and m["status"] == "Ativo" and m["lgpd_consentimento"]
    assert m["status_lgpd"] == "Consentimento Ativo"


def test_limite_diario_de_emails(monkeypatch):
    _email(monkeypatch)
    sec, lt = _criar_lote()
    cli = _voluntaria(lt["codigo"])
    for i in range(3):
        _lancar(cli, lt["codigo"], nome_completo=f"Pessoa Numero {chr(65 + i)}", email=f"p{i}@mevam.test")
    from app.rotas import mutirao
    antigo = mutirao.LIMITE_DIARIO
    mutirao.LIMITE_DIARIO = 2
    try:
        post(sec, f"/mutirao/lotes/{lt['id']}/credo", {}, pagina=f"/mutirao/lotes/{lt['id']}")
        assert sum(1 for m in _fichas(lt["id"]) if m["credo_email_em"]) == 2
        post(sec, f"/mutirao/lotes/{lt['id']}/credo", {}, pagina=f"/mutirao/lotes/{lt['id']}")
        assert sum(1 for m in _fichas(lt["id"]) if m["credo_email_em"]) == 2
    finally:
        mutirao.LIMITE_DIARIO = antigo


def test_membro_e_coordenacao_nao_acessam_painel():
    for perfil in ("membro", "coordenacao"):
        r = logado(perfil).get("/mutirao", follow_redirects=False)
        assert r.status_code in (302, 303, 403)
