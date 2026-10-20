"""Fase A (v2.11.0): Dia do Profissional, intenção de dízimo, pesquisa mensal de necessidades e Instituto."""
from sqlalchemy import func, insert, select

from app import aniversarios as an
from app import datas, db, profissional
from app.rotas import necessidades as nec
from conftest import criar, logado, novo_cliente, post
from test_plataforma import enviar_ficha, membro_id_mais_recente

HOJE = datas.hoje()


def test_sugestao_e_formato_do_dia():
    assert profissional.sugerir("Professora de Matemática") == ("15/10", "Dia do Professor")
    assert profissional.sugerir("técnica de enfermagem")[0] == "20/05"
    assert profissional.sugerir("Enfermeira")[0] == "12/05"
    assert profissional.sugerir("Médico Veterinário")[0] == "09/09"
    assert profissional.sugerir("Do lar") is None
    assert profissional.sugerir("Engenheiro civil")[0] == "11/12"
    assert profissional.normalizar("5/9") == "05/09" and profissional.normalizar("29/02") == "29/02"
    assert profissional.normalizar("31/04") is None and profissional.normalizar("abc") is None


def test_ficha_guarda_dia_sugerido_corrigido_e_dizimo():
    c = novo_cliente()
    assert enviar_ficha(c).status_code == 303  # profissão "Professora", dia vazio: usa a sugestão
    with db.engine().connect() as cx:
        m = cx.execute(select(db.membros).where(db.membros.c.id == membro_id_mais_recente())).mappings().first()
    assert m["dia_profissional"] == "15/10" and m["homenagem_profissional"] is True and m["deseja_dizimista"] is None
    assert enviar_ficha(novo_cliente(), dia_profissional="1/3", sem_homenagem_prof="1",
                        deseja_dizimista="Sim", dia_dizimo="10").status_code == 303
    with db.engine().connect() as cx:
        m = cx.execute(select(db.membros).where(db.membros.c.id == membro_id_mais_recente())).mappings().first()
    assert (m["dia_profissional"], m["homenagem_profissional"], m["deseja_dizimista"], m["dia_dizimo"]) == ("01/03", False, "Sim", 10)
    r = enviar_ficha(novo_cliente(), dia_profissional="40/13", deseja_dizimista="Sim", dia_dizimo="45")
    assert r.status_code == 400 and "Dia do Profissional inválido" in r.text and "entre 1 e 31" in r.text
    # O formulário mostra os campos novos
    html = novo_cliente().get("/ficha").text
    assert 'id="dia_profissional"' in html and 'data-mascara="diames"' in html and "Deseja se tornar dizimista?" in html


def test_aviso_do_dia_do_profissional():
    hoje = HOJE.strftime("%d/%m")
    with db.engine().begin() as c:
        novo = lambda nome, **kw: c.execute(insert(db.membros).values(
            nome_completo=nome, status=kw.pop("status", "Ativo"), lgpd_consentimento=True,
            data_nascimento=datas.parse_data("10/01/1980"), **kw)).inserted_primary_key[0]
        prof = novo("Paula Professora", profissao="Professora", dia_profissional=hoje, whatsapp="(62) 9 9999-0001",
                    homenagem_aniversario=False)  # recusou o aniversário, mas aceita a homenagem da profissão
        novo("Rui Recusou", dia_profissional=hoje, homenagem_profissional=False)
        novo("Ines Inativa", dia_profissional=hoje, status="Inativo")
    sec = logado("secretaria")
    with db.engine().begin() as c:
        criados = profissional.gerar_avisos(c, HOJE)
        assert profissional.gerar_avisos(c, HOJE) == 0  # não duplica
        n = c.execute(select(func.count()).select_from(db.avisos).where(db.avisos.c.tipo == an.PROFISSIONAL)).scalar()
    assert criados == n == 1
    html = sec.get("/avisos").text
    assert "Paula Professora" in html and "💼" in html and "wa.me/5562999990001" in html
    assert "Rui Recusou" not in html and "Ines Inativa" not in html


def test_pesquisa_mensal_anonima_uma_vez_por_mes():
    m1 = logado("membro", email="m1@mevam.test")
    assert "Pesquisa do mês" in m1.get("/inicio").text
    r = post(m1, "/necessidades", {"cat_saude": "1", "int_saude": "3", "cat_casamento": "1", "comentario": "Orem por nós"},
             pagina="/necessidades")
    assert r.status_code == 303
    assert "Obrigado" in m1.get("/necessidades").text and 'href="/necessidades">Responder' not in m1.get("/inicio").text
    # Segunda tentativa no mesmo mês não grava
    post(m1, "/necessidades", {"cat_luto": "1"}, pagina="/inicio")
    m2 = logado("membro", email="m2@mevam.test")
    assert post(m2, "/necessidades", {}, pagina="/necessidades").status_code == 400  # nada marcado
    post(m2, "/necessidades", {"cat_saude": "1", "quer_contato": "sim"}, pagina="/necessidades")
    with db.engine().connect() as c:
        resp = c.execute(select(db.necessidades_respostas)).mappings().all()
        itens = c.execute(select(db.necessidades_itens.c.categoria)).scalars().all()
    assert len(resp) == 2 and sorted(itens) == ["casamento", "saude", "saude"]
    assert "usuario_id" not in db.necessidades_respostas.c  # a resposta não guarda quem respondeu
    assert [r["contato_usuario_id"] is not None for r in resp] == [False, True]
    # Painel: liderança vê números; comentários e contatos só Secretaria/Adm; membro não entra
    assert m1.get("/necessidades/painel", follow_redirects=False).status_code in (302, 303, 403)
    coord = logado("coordenacao")
    html = coord.get("/necessidades/painel").text
    assert "Saúde" in html and "Orem por nós" not in html and "Pediram para ser procurados" not in html
    html = logado("secretaria").get("/necessidades/painel").text
    assert "Orem por nós" in html and "Pediram para ser procurados (1)" in html
    assert nec.mes_atual() in html


def test_instituto_so_adm_e_menu():
    assert "Em preparação" in logado("admin").get("/instituto").text
    assert logado("secretaria").get("/instituto", follow_redirects=False).status_code in (302, 303, 403)
    html = logado("membro").get("/inicio").text
    assert "/instituto" not in html and "Pesquisa do mês" in html and "/necessidades/painel" not in html


def test_termo_ministerio_no_lugar_de_setor():
    """Ricardo, 20/10/2026: o termo visível 'Setor(es)' passou a ser 'Ministério(s)' (rotas e dados continuam iguais)."""
    adm = logado("admin")
    for url in ("/admin/setores", "/coordenacao", "/voluntarios", "/aniversariantes", "/relatorios"):
        html = adm.get(url).text
        visivel = html.split("<main", 1)[-1]
        assert "Setor" not in visivel.replace("Bairro / Setor", ""), url
    assert "Ministérios em que deseja servir" in novo_cliente().get("/ficha").text


def test_resumo_dos_relatorios_usa_ministerios():
    """Os números do topo dos relatórios também dizem 'ministérios' (correção da v2.11.1)."""
    import re
    from app.rotas import relatorios as rel
    adm = logado("admin")
    for slug in [r.chave for r in rel.CATALOGO]:
        html = adm.get(f"/relatorios/{slug}").text
        assert not re.search(r"<span>[^<]*\bsetor(es)?\b", html), slug


def test_campo_ministerio_nos_modelos_de_mensagem():
    m = {"primeiro": "Igor", "nome": "Igor Barbosa", "setores": [{"nome": "Louvor", "tipo": "serve"}]}
    assert an.preencher("{primeiro_nome} · {ministerio} · {setor}", m, "Lia") == "Igor · Louvor · Louvor"
    assert "{ministerio}" in an.CAMPOS and "{setor}" not in an.CAMPOS
