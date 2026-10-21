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
    r = _lancar(cli, lt["codigo"], cpf=gerar_cpf(111222333))
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
    _lancar(cli, lt["codigo"], email="joana@mevam.test", whatsapp="", cpf=gerar_cpf(444555666))
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
        _lancar(cli, lt["codigo"], nome_completo=f"Pessoa Numero {chr(65 + i)}", email=f"p{i}@mevam.test",
                cpf=gerar_cpf(700000001 + i))
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


def test_ficha_sem_cpf_segue_a_regularizacao(monkeypatch):
    enviados = _email(monkeypatch)
    sec, lt = _criar_lote()
    cli = _voluntaria(lt["codigo"])
    _lancar(cli, lt["codigo"], email="sem.cpf@mevam.test")
    [m] = _fichas(lt["id"])
    assert m["status"] == "Aguardando Análise" and m["integra_situacao"] == "concluido" and not m["validado_por"]
    html = sec.get(f"/mutirao/lotes/{lt['id']}").text
    assert "Sem CPF: complemento de dados (1)" in html and "sem link" in html
    # Fora do envio do Credo enquanto não tiver CPF e validação
    post(sec, f"/mutirao/lotes/{lt['id']}/credo", {}, pagina=f"/mutirao/lotes/{lt['id']}")
    assert not _fichas(lt["id"])[0]["credo_email_em"]
    # Link de complemento da Regularização, com o prazo padrão
    post(sec, f"/mutirao/lotes/{lt['id']}/complemento", {}, pagina=f"/mutirao/lotes/{lt['id']}")
    with db.engine().connect() as c:
        regs = c.execute(select(db.regularizacoes).where(db.regularizacoes.c.membro_id == m["id"])).mappings().all()
    assert len(regs) == 1 and any("/atualizar/" in e[2] for e in enviados)
    assert (regs[0]["expira_em"] - regs[0]["criado_em"]).days == config.REGULARIZACAO_PRAZO_DIAS
    # Segundo clique não gera outro link
    post(sec, f"/mutirao/lotes/{lt['id']}/complemento", {}, pagina=f"/mutirao/lotes/{lt['id']}")
    with db.engine().connect() as c:
        assert c.execute(select(db.regularizacoes).where(db.regularizacoes.c.membro_id == m["id"])).all().__len__() == 1
    # Depois do complemento a Secretaria valida (INTEGRA já concluído) e o Credo entra no envio em lote
    with db.engine().begin() as c:
        c.execute(update(db.membros).where(db.membros.c.id == m["id"]).values(cpf=gerar_cpf(987123654)))
    post(sec, f"/membros/{m['id']}/validar", {}, pagina=f"/membros/{m['id']}")
    post(sec, f"/mutirao/lotes/{lt['id']}/credo", {}, pagina=f"/mutirao/lotes/{lt['id']}")
    [m] = _fichas(lt["id"])
    assert m["status"] == "Validado pela Secretaria" and m["credo_email_em"]


def test_foto_da_ficha_vai_para_o_drive(monkeypatch):
    gravados = []
    monkeypatch.setattr(envios, "drive_configurado", lambda: True)
    monkeypatch.setattr(envios, "salvar_no_drive", lambda n, m, d: (gravados.append((n, m, d)) or f"ID{len(gravados)}x", None))
    sec, lt = _criar_lote()
    cli = _voluntaria(lt["codigo"])
    pag = cli.get(f"/mutirao/{lt['codigo']}")
    assert "Fotografar a ficha" in pag.text and 'name="arquivo"' not in pag.text
    fotos = [("foto_ficha", ("a.jpg", b"frente", "image/jpeg")), ("foto_ficha", ("b.jpg", b"verso", "image/jpeg"))]
    dados = {k: v for k, v in FICHA.items() if k != "arquivo"}
    r = cli.post(f"/mutirao/{lt['codigo']}", data={**dados, "csrf": csrf_de(pag.text)}, files=fotos, follow_redirects=False)
    assert r.status_code == 303 and "foi para o Drive" in cli.get(r.headers["location"]).text
    [m] = _fichas(lt["id"])
    assert [g[0] for g in gravados] == [f"Joana D'arc Pereira - ficha {m['id']} (1).jpg", f"Joana D'arc Pereira - ficha {m['id']} (2).jpg"]
    assert gravados[0][2] == b"frente" and "https://drive.google.com/file/d/ID1x/view" in m["observacoes"]
    assert m["ocr_documento_nome"].startswith("Drive: Joana")
    assert "https://drive.google.com/file/d/ID2x/view" in sec.get(f"/mutirao/lotes/{lt['id']}").text
    # Falha no Drive: a ficha fica salva e a voluntária é avisada para separar a ficha
    monkeypatch.setattr(envios, "salvar_no_drive", lambda n, m, d: (None, "Google HTTP 500"))
    pag = cli.get(f"/mutirao/{lt['codigo']}")
    r = cli.post(f"/mutirao/{lt['codigo']}", data={**dados, "nome_completo": "Rita Souza", "csrf": csrf_de(pag.text)},
                 files=fotos[:1], follow_redirects=False)
    assert "não chegou ao Drive" in cli.get(r.headers["location"]).text
    rita = [x for x in _fichas(lt["id"]) if x["nome_completo"] == "Rita Souza"][0]
    assert "Foto não enviada ao Drive" in rita["observacoes"]
    # Tipo de arquivo inválido não grava a ficha
    pag = cli.get(f"/mutirao/{lt['codigo']}")
    r = cli.post(f"/mutirao/{lt['codigo']}", data={**dados, "nome_completo": "Zeca Lima", "csrf": csrf_de(pag.text)},
                 files=[("foto_ficha", ("x.exe", b"MZ", "application/octet-stream"))], follow_redirects=False)
    assert r.status_code == 400 and "JPG ou PNG" in r.text and len(_fichas(lt["id"])) == 2
