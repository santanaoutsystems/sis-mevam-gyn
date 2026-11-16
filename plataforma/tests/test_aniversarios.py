"""Aniversariantes (v2.8.0): quem é avisado, escopo da Coordenação, LGPD, mensagens e rotina diária."""
from datetime import date, timedelta

from sqlalchemy import func, insert, select

from app import aniversarios as an
from app import datas, db, envios
from conftest import criar, csrf_de, logado, novo_cliente, entrar, post

HOJE = datas.hoje()
AMANHA = HOJE + timedelta(days=1)


def _nasc(d: date, ano: int = 1990) -> date:
    return date(ano, d.month, 28 if (d.month, d.day) == (2, 29) else d.day)


def _base():
    """Louvor (com coordenação), Kids (interesse) e membros: serve, interesse, sem setor, recusou, inativo."""
    with db.engine().begin() as c:
        louvor = c.execute(insert(db.departamentos).values(nome="Louvor")).inserted_primary_key[0]
        c.execute(insert(db.departamentos).values(nome="Jovens"))
        novo = lambda nome, **kw: c.execute(insert(db.membros).values(
            nome_completo=nome, status=kw.pop("status", "Ativo"), lgpd_consentimento=True, **kw)).inserted_primary_key[0]
        ana = novo("Ana Paula Ribeiro", data_nascimento=_nasc(AMANHA, 1991), whatsapp="(62) 99999-0001", email="ana@x.test")
        bruno = novo("Bruno Santos", data_nascimento=_nasc(AMANHA, 1985), email="bruno@x.test")
        carla = novo("Carla Mendes", data_nascimento=_nasc(AMANHA, 2000))
        dani = novo("Daniela Recusou", data_nascimento=_nasc(AMANHA), homenagem_aniversario=False)
        novo("Eva Inativa", data_nascimento=_nasc(AMANHA), status="Inativo")
        hoje_id = novo("Hugo Hoje", data_nascimento=_nasc(HOJE, 1970), email="hugo@x.test", whatsapp="62988887777")
        c.execute(insert(db.membro_setores).values(membro_id=ana, departamento_id=str(louvor), funcao="Voluntário"))
        c.execute(insert(db.membro_setores).values(membro_id=hoje_id, departamento_id=str(louvor), funcao="Voluntário"))
        c.execute(insert(db.membro_interesses).values(membro_id=bruno, setor="Louvor"))
        c.execute(insert(db.membro_interesses).values(membro_id=dani, setor="Louvor"))
    return {"louvor": str(louvor), "ana": ana, "bruno": bruno, "carla": carla, "dani": dani, "hugo": hoje_id}


def _coord(ids, email="coord@mevam.test"):
    cli = logado("coordenacao", email=email)
    with db.engine().begin() as c:
        c.execute(insert(db.usuario_setores).values(usuario_id=cli.usuario["id"], departamento_id=ids["louvor"]))
    return cli


def test_regras_basicas():
    assert an.no_ano(date(2000, 2, 29), 2027) == date(2027, 2, 28)
    assert an.no_ano(date(2000, 2, 29), 2028) == date(2028, 2, 29)
    m = {"primeiro": "Ana", "nome": "Ana Paula", "setores": [{"nome": "Louvor", "tipo": "serve"}]}
    assert an.preencher("Paz, {primeiro_nome}! {setor} · {remetente}", m, "Marcos") == "Paz, Ana! Louvor · Marcos"
    assert an.link_whatsapp("(62) 99999-0001", "Oi ana").startswith("https://wa.me/5562999990001?text=Oi%20ana")
    assert an.link_whatsapp("", "x") == ""


def test_quem_recebe_o_aviso_de_amanha():
    ids = _base()
    coord = _coord(ids)
    sec = criar("secretaria")
    with db.engine().begin() as c:
        an.gerar_avisos(c, HOJE)
        an.gerar_avisos(c, HOJE)  # a segunda rodada não duplica
        av = {(r.usuario_id, r.membro_id, r.tipo): r.janela for r in c.execute(select(db.avisos))}
    uc = coord.usuario["id"]
    # Coordenação do Louvor: quem serve (Ana) e quem tem interesse (Bruno), na janela
    assert av[(uc, ids["ana"], an.AMANHA)] is True and av[(uc, ids["bruno"], an.AMANHA)] is True
    assert (uc, ids["carla"], an.AMANHA) not in av
    # Secretaria: todos no sino, mas na janela só quem não tem setor/coordenação
    assert av[(sec["id"], ids["carla"], an.AMANHA)] is True
    assert av[(sec["id"], ids["ana"], an.AMANHA)] is False
    # Recusou a homenagem ou inativo: ninguém é avisado
    assert not any(k[1] == ids["dani"] for k in av)
    assert len([k for k in av if k[0] == uc]) == 3  # Ana, Bruno e Hugo (hoje)
    assert av[(uc, ids["hugo"], an.HOJE)] is True


def test_setor_sem_coordenador_vai_para_secretaria():
    ids = _base()
    sec = criar("secretaria")
    with db.engine().begin() as c:
        an.gerar_avisos(c, HOJE)
        janela = c.execute(select(db.avisos.c.janela).where(db.avisos.c.usuario_id == sec["id"],
                                                            db.avisos.c.membro_id == ids["ana"])).scalar()
    assert janela is True


def test_janela_sino_e_calendario_da_coordenacao():
    ids = _base()
    coord = _coord(ids)
    r = coord.get("/inicio")
    assert "Amanhã é aniversário" in r.text and "Ana Paula Ribeiro" in r.text and "Bruno Santos" in r.text
    assert "Carla Mendes" not in r.text and "Daniela" not in r.text
    assert 'class="sino"' in r.text
    assert "Amanhã é aniversário" not in coord.get("/inicio").text  # a janela aparece uma vez por dia
    cal = coord.get(f"/aniversariantes?visao=lista&dia={AMANHA.isoformat()}")
    assert cal.status_code == 200 and "Ana Paula Ribeiro" in cal.text and "Carla Mendes" not in cal.text
    assert str(_nasc(AMANHA, 1991).year) not in cal.text.split("<main")[1]  # sem ano de nascimento
    # Abriu o calendário: avisos contam como vistos
    with db.engine().connect() as c:
        assert c.execute(select(func.count()).select_from(db.avisos).where(
            db.avisos.c.usuario_id == coord.usuario["id"], db.avisos.c.lido_em.is_(None))).scalar() == 0
    # Fora do escopo: nem por endereço direto
    assert coord.get(f"/aniversariantes/{ids['carla']}/mensagem").status_code == 404
    assert coord.get(f"/aniversariantes/{ids['dani']}/mensagem").status_code == 404
    assert coord.get("/aniversariantes/modelos").status_code == 403


def test_membro_nao_acessa_e_recebe_felicitacao_no_dia():
    ids = _base()
    with db.engine().begin() as c:
        c.execute(db.membros.update().where(db.membros.c.id == ids["hugo"]).values(homenagem_aniversario=True))
    cli = novo_cliente()
    u = criar("membro", membro_id=ids["hugo"])
    entrar(cli, u["email"])
    r = cli.get("/inicio")
    assert "Feliz aniversário" in r.text and "Paz, Hugo!" in r.text
    assert 'class="sino"' not in r.text
    assert cli.get("/aniversariantes").status_code == 403
    assert cli.get(f"/aniversariantes/{ids['ana']}/mensagem").status_code == 403


def test_membro_recusa_homenagem_pela_propria_ficha():
    ids = _base()
    cli = novo_cliente()
    u = criar("membro", membro_id=ids["ana"])
    entrar(cli, u["email"])
    r = post(cli, "/minha-ficha/homenagem", {"homenagem": "nao"}, pagina="/minha-ficha")
    assert r.status_code == 303
    with db.engine().connect() as c:
        assert c.execute(select(db.membros.c.homenagem_aniversario).where(db.membros.c.id == ids["ana"])).scalar() is False
        assert c.execute(select(func.count()).select_from(db.auditoria).where(
            db.auditoria.c.acao == "LGPD_HOMENAGEM_ANIVERSARIO")).scalar() == 1
        assert ids["ana"] not in {m["id"] for m in an.membros(c)}


def test_ficha_da_secretaria_grava_recusa():
    ids = _base()
    sec = logado("secretaria")
    pagina = sec.get(f"/membros/{ids['carla']}/editar")
    assert 'name="sem_homenagem"' in pagina.text


def test_mensagem_whatsapp_e_email():
    ids = _base()
    coord = _coord(ids)
    tela = coord.get(f"/aniversariantes/{ids['hugo']}/mensagem")
    assert tela.status_code == 200 and "Paz, Hugo!" in tela.text and "wa.me/5562988887777" in tela.text
    token = csrf_de(tela.text)
    r = coord.post(f"/aniversariantes/{ids['hugo']}/registrar", data={"csrf": token, "canal": "whatsapp"})
    assert r.json() == {"ok": True}
    assert coord.post(f"/aniversariantes/{ids['carla']}/registrar", data={"csrf": token, "canal": "whatsapp"}).status_code == 404
    with db.engine().connect() as c:
        env = an.enviados(c, [ids["hugo"]], [HOJE.year])
    assert env[(ids["hugo"], HOJE.year)][0]["canal"] == "whatsapp"
    cal = coord.get(f"/aniversariantes?dia={HOJE.isoformat()}")
    assert "enviado" in cal.text and "Mensagem enviada por Pessoa Coordenacao" in cal.text


def test_email_da_mensagem(monkeypatch):
    ids = _base()
    enviados = []
    monkeypatch.setattr(envios, "email_configurado", lambda: True)
    monkeypatch.setattr(envios, "enviar_email", lambda d, a, c: enviados.append((d, a, c)))
    sec = logado("secretaria")
    tela = sec.get(f"/aniversariantes/{ids['hugo']}/mensagem")
    r = sec.post(f"/aniversariantes/{ids['hugo']}/email", data={"csrf": csrf_de(tela.text), "texto": "Paz, Hugo! Parabéns!"},
                 follow_redirects=False)
    assert r.status_code == 303 and enviados[0][0] == "hugo@x.test" and "Hugo" in enviados[0][1]


def test_rotina_resumo_das_8h_e_email_automatico(monkeypatch):
    ids = _base()
    coord = _coord(ids)
    enviados = []
    monkeypatch.setattr(envios, "email_configurado", lambda: True)
    monkeypatch.setattr(envios, "enviar_email", lambda d, a, c: enviados.append((d, a, c)))
    r1 = an.rodar(HOJE)
    r2 = an.rodar(HOJE)  # nada se repete
    assert r1["resumo"] >= 1 and r1["automatico"] == 1 and r2 == {"avisos": 0, "resumo": 0, "automatico": 0}
    resumo = [e for e in enviados if e[0] == coord.usuario["email"]]
    assert len(resumo) == 1 and "Ana Paula Ribeiro" in resumo[0][2] and "Carla" not in resumo[0][2]
    assert str(_nasc(AMANHA, 1991).year) not in resumo[0][2]
    auto = [e for e in enviados if e[0] == "hugo@x.test"]
    assert len(auto) == 1 and auto[0][2].startswith("Paz, Hugo!")


def test_resumo_desligado_nao_envia(monkeypatch):
    ids = _base()
    coord = _coord(ids)
    r = post(coord, "/aniversariantes/resumo-email", {"ligar": "0"}, pagina="/aniversariantes")
    assert r.status_code == 303
    enviados = []
    monkeypatch.setattr(envios, "email_configurado", lambda: True)
    monkeypatch.setattr(envios, "enviar_email", lambda d, a, c: enviados.append(d))
    an.rodar(HOJE)
    assert coord.usuario["email"] not in enviados


def test_modelos_da_secretaria():
    ids = _base()
    sec = logado("secretaria")
    r = post(sec, "/aniversariantes/modelos/salvar", {"titulo": "Jovens", "texto": "Paz, {primeiro_nome}! Bora comemorar!",
                                                      "ativo": "1"}, pagina="/aniversariantes/modelos")
    assert r.status_code == 303
    with db.engine().connect() as c:
        mods = an.modelos(c)
    assert len(mods) == 1 and mods[0]["padrao"] is True  # o único ativo vira o padrão
    tela = sec.get(f"/aniversariantes/{ids['hugo']}/mensagem")
    assert "Bora comemorar" in tela.text


def test_relatorio_aniversariantes_na_coordenacao():
    ids = _base()
    coord = _coord(ids)
    r = coord.get(f"/relatorios/aniversariantes?mes={AMANHA.month}")
    assert r.status_code == 200 and "Ana Paula Ribeiro" in r.text and "Carla Mendes" not in r.text
    assert "99999-0001" not in r.text  # Coordenação não vê o telefone no relatório
