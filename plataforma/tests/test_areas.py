"""Ministérios e Áreas (v2.15.0): estrutura oficial, lotação de Secretaria/Adm e isolamento entre áreas."""
from sqlalchemy import insert, select

from app import areas, db
from conftest import criar, logado, post

EVENTO = {"titulo": "Culto Kids", "data": "15/11/2026", "hora": "09:00", "valor_inscricao": "0,00",
          "controle_vagas": "livre", "limite_vagas": "", "local": "Sala Kids"}


def _sincronizar():
    with db.engine().begin() as c:
        return areas.sincronizar(c)


def _ids():
    with db.engine().connect() as c:
        return {n: i for i, n in c.execute(select(db.DEP_ID, db.departamentos.c.nome))}


def test_estrutura_oficial_renomeia_cria_e_nao_apaga_nada():
    sec, adm = criar("secretaria"), criar("admin")
    with db.engine().begin() as c:
        for nome in ("Louvor", "Kids", "Voluntariado", "Mídia e Comunicação", "Discipulado Inteiras"):
            c.execute(insert(db.departamentos).values(nome=nome, responsavel="Fulano"))
        c.execute(insert(db.eventos).values(titulo="Ensaio", data_inicio="2026-11-10T19:00:00", departamento="Louvor"))
        mid = c.execute(insert(db.membros).values(nome_completo="Ana Lima", status="Ativo")).inserted_primary_key[0]
        c.execute(insert(db.membro_interesses).values(membro_id=mid, setor="Kids"))
    feitos = _sincronizar()
    assert "Louvor → Ministério de Louvor (1 evento(s))" in feitos
    assert any("fora da lista oficial" in f and "Discipulado Inteiras" in f for f in feitos)
    with db.engine().connect() as c:
        deps = {d["nome"]: d for d in c.execute(select(db.departamentos)).mappings()}
        assert c.execute(select(db.eventos.c.departamento)).scalar() == "Ministério de Louvor"
        assert c.execute(select(db.membro_interesses.c.setor)).scalar() == "Ministério Kids"
        lot = dict(c.execute(select(db.usuarios.c.id, db.usuarios.c.area_id)).all())
    assert set(areas.NOMES) <= set(deps) and len(deps) == 19  # 18 oficiais + a de fora, que não é apagada
    assert deps["Discipulado Inteiras"]["categoria"] is None
    assert deps["Mídia"]["categoria"] == "Área de Apoio" and deps["Escola de Teologia"]["categoria"] == "Departamento de Ensino"
    assert deps["GC's (Grupos de Convívio)"]["categoria"] == "Frente Ministerial"
    assert deps["Ministério de Louvor"]["responsavel"] == "Fulano"  # responsáveis não são mexidos
    ids = _ids()
    assert lot[sec["id"]] == ids["Secretaria"] and lot[adm["id"]] == ids["Administração e Tesouraria"]
    assert _sincronizar() == []  # roda uma vez só


def test_tela_de_ministerios_e_areas_por_categoria():
    _sincronizar()
    adm = logado("admin")
    html = adm.get("/admin/setores").text
    for cat in areas.CATEGORIAS:
        assert f"{cat} <span" in html
    assert "Ministérios e Áreas" in adm.get("/inicio").text
    sid = _ids()["Bazar"]
    assert post(adm, "/admin/setores/salvar", {"id": sid, "nome": "Bazar", "categoria": ""}, pagina="/admin/setores").status_code == 303
    with db.engine().connect() as c:
        assert c.execute(select(db.departamentos.c.categoria).where(db.DEP_ID == sid)).scalar() == "Área de Apoio"
    # Desativar tira a área das listas sem apagar
    post(adm, "/admin/setores/salvar", {"id": sid, "nome": "Bazar", "categoria": "Área de Apoio"}, pagina="/admin/setores")
    form = logado("secretaria").get("/eventos/novo").text
    assert ">Bazar<" not in form and "Ministério Kids" in form and '<optgroup label="Frente Ministerial">' in form


def test_novo_usuario_da_secretaria_e_lotado_e_lotacao_editavel():
    _sincronizar()
    adm = logado("admin")
    post(adm, "/admin/usuarios/novo", {"nome": "Rita Souza", "email": "rita@mevam.test", "perfil": "secretaria"},
         pagina="/admin/usuarios")
    ids = _ids()
    with db.engine().connect() as c:
        uid, area = c.execute(select(db.usuarios.c.id, db.usuarios.c.area_id).where(db.usuarios.c.email == "rita@mevam.test")).one()
    assert area == ids["Secretaria"]
    post(adm, f"/admin/usuarios/{uid}", {"perfil": "secretaria", "ativo": "sim", "area_id": ids["Ministério Kids"]},
         pagina="/admin/usuarios")
    with db.engine().connect() as c:
        assert c.execute(select(db.usuarios.c.area_id).where(db.usuarios.c.id == uid)).scalar() == ids["Ministério Kids"]
    assert "Ministério / Área" in adm.get("/admin/usuarios").text


def _negados():
    with db.engine().connect() as c:
        return c.execute(select(db.auditoria.c.acao, db.auditoria.c.recurso)
                         .where(db.auditoria.c.acao.like("ACESSO_NEGADO%"))).all()


def test_coordenacao_de_uma_area_nao_acessa_outra():
    _sincronizar()
    ids = _ids()
    sec = logado("secretaria")
    for depto in ("Ministério Kids", "Ministério de Louvor"):
        assert post(sec, "/eventos/novo", {**EVENTO, "titulo": "Culto Kids" if "Kids" in depto else "Ensaio Geral", "departamento": depto,
                                           "hora": "09:00" if "Kids" in depto else "15:00"},
                    pagina="/eventos/novo").status_code == 303
    with db.engine().begin() as c:
        ev = {n: i for i, n in c.execute(select(db.eventos.c.id, db.eventos.c.departamento))}
    coord = logado("coordenacao")
    with db.engine().begin() as c:
        c.execute(insert(db.usuario_setores).values(usuario_id=coord.usuario["id"], departamento_id=ids["Ministério Kids"]))
    # Pode gerir o evento da própria área
    assert coord.get(f"/eventos/{ev['Ministério Kids']}/editar").status_code == 200
    # Não pode abrir para edição, excluir nem criar evento de outra área
    assert coord.get(f"/eventos/{ev['Ministério de Louvor']}/editar").status_code == 403
    r = post(coord, f"/eventos/{ev['Ministério de Louvor']}/excluir", {"justificativa": "teste de acesso"},
             pagina=f"/eventos/{ev['Ministério Kids']}")
    assert r.status_code == 403
    form = coord.get("/eventos/novo").text
    assert "Ministério Kids" in form and "Ministério de Louvor" not in form
    r = post(coord, "/eventos/novo", {**EVENTO, "titulo": "Intruso", "departamento": "Ministério de Louvor", "hora": "20:00"},
             pagina="/eventos/novo")
    assert r.status_code == 400
    # Não vê voluntários, relatórios nem fichas de outras áreas
    assert "Ministério de Louvor" not in coord.get("/voluntarios").text
    assert coord.get("/voluntarios?setor=Ministério de Louvor").text.count("Ministério de Louvor") == 0
    rel = coord.get("/relatorios/participantes?setor=Ministério de Louvor").text
    assert "Ensaio Geral" not in rel and "<option selected>Ministério de Louvor" not in rel
    for tela in ("/membros", "/necessidades/painel", "/admin/setores", "/coordenacao", "/mutirao"):
        assert coord.get(tela, follow_redirects=False).status_code == 403, tela
    negados = _negados()
    assert ("ACESSO_NEGADO_AREA", f"/eventos/{ev['Ministério de Louvor']}/editar") in negados
    assert ("ACESSO_NEGADO_PERFIL", "/membros") in negados


def test_membro_nao_acessa_telas_de_gestao():
    m = logado("membro")
    for tela in ("/membros", "/voluntarios", "/aniversariantes", "/necessidades/painel", "/eventos/novo", "/admin/usuarios"):
        assert m.get(tela, follow_redirects=False).status_code == 403, tela


def test_secretaria_e_adm_veem_tudo():
    _sincronizar()
    for perfil in ("secretaria", "admin"):
        cli = logado(perfil, email=f"{perfil}2@mevam.test")
        for tela in ("/membros", "/voluntarios", "/aniversariantes", "/necessidades/painel", "/coordenacao"):
            assert cli.get(tela).status_code == 200, (perfil, tela)
        assert "Ministério de Louvor" in cli.get("/voluntarios").text


def test_nomes_antigos_continuam_valendo():
    assert areas.nome_oficial("louvor") == "Ministério de Louvor"
    assert areas.nome_oficial("GC’s") == "GC's (Grupos de Convívio)"
    assert areas.nome_oficial("Escola Teológica") == "Escola de Teologia"
    assert areas.nome_oficial("Inventado") is None
    assert "Louvor" in areas.equivalentes("Ministério de Louvor")
