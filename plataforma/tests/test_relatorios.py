"""Central de Relatórios (v2.7.0): catálogo por perfil, limite no servidor, filtros dos cabeçalhos, LGPD."""
from datetime import date, datetime, timezone

from sqlalchemy import insert, select

from app import datas, db, tabelas
from app.tabelas import Coluna
from conftest import criar, logado, post

HOJE = datas.hoje()
MES = f"{HOJE.year:04d}-{HOJE.month:02d}"


def _base():
    """Dois setores, um evento em cada (neste mês), inscrições e membros."""
    with db.engine().begin() as c:
        jov = c.execute(insert(db.departamentos).values(nome="Jovens", responsavel="Lia")).inserted_primary_key[0]
        fam = c.execute(insert(db.departamentos).values(nome="Família", responsavel="Pr. João")).inserted_primary_key[0]
        ej = c.execute(insert(db.eventos).values(titulo="Culto Jovem", data_inicio=f"{MES}-10T19:00:00", departamento="Jovens",
                                                 valor_inscricao=20, limite_vagas=10, local="Templo")).inserted_primary_key[0]
        ef = c.execute(insert(db.eventos).values(titulo="Encontro de Casais", data_inicio=f"{MES}-12T19:00:00",
                                                 departamento="Família", valor_inscricao=50, limite_vagas=0)).inserted_primary_key[0]
        m1 = c.execute(insert(db.membros).values(nome_completo="Ana Paula Ribeiro", cpf="52998224725", bairro="Centro",
                                                 whatsapp="62999990001", status="Ativo", data_nascimento=date(1990, HOJE.month, 5),
                                                 data_registro=date(2026, 1, 10), credo_aceito=True, sexo="Feminino",
                                                 batizado="Sim", lgpd_consentimento=True)).inserted_primary_key[0]
        m2 = c.execute(insert(db.membros).values(nome_completo="Bruno Santos", bairro="Setor Bueno", whatsapp="62999990002",
                                                 status="Aguardando Análise", data_nascimento=date(1985, 2, 20),
                                                 data_registro=date(2026, 3, 1), credo_aceito=False, sexo="Masculino",
                                                 lgpd_consentimento=True)).inserted_primary_key[0]
        c.execute(insert(db.membros).values(nome_completo="Fulano Anonimizado", status="Anonimizado (LGPD)",
                                            lgpd_consentimento=False))
        c.execute(insert(db.membro_setores).values(membro_id=m1, departamento_id=str(jov), funcao="Líder"))
        c.execute(insert(db.inscricoes).values(evento_id=ej, nome="Carla Mendes", telefone="62988887777", forma_pagamento="Pix",
                                               status_pagamento="Confirmado", tipo_ingresso="Inteira", valor_pago=20, membro_id=m1))
        c.execute(insert(db.inscricoes).values(evento_id=ej, nome="Diego Souza", telefone="62977776666",
                                               forma_pagamento="A Receber", status_pagamento="Pendente",
                                               tipo_ingresso="Inteira", valor_pago=20))
        c.execute(insert(db.inscricoes).values(evento_id=ef, nome="Elaine Costa", telefone="62966665555",
                                               forma_pagamento="A Receber", status_pagamento="Pendente",
                                               tipo_ingresso="Inteira", valor_pago=50))
        c.execute(insert(db.custos_evento).values(evento_id=ej, descricao="Lanche", valor=5))
    return {"jov": str(jov), "fam": str(fam), "ej": ej, "ef": ef, "m1": m1, "m2": m2}


def _coord_jovens(ids):
    coord = logado("coordenacao")
    with db.engine().begin() as c:
        c.execute(insert(db.usuario_setores).values(usuario_id=coord.usuario["id"], departamento_id=ids["jov"]))
    return coord


# ---------------------------------------------------------------------------
# Motor de tabelas
# ---------------------------------------------------------------------------
class P(dict):
    """Imita QueryParams (multi_items) para testar o motor sem HTTP."""
    def __init__(self, pares):
        super().__init__(pares)
        self._pares = pares

    def multi_items(self):
        return self._pares


def test_motor_filtra_por_tipo_e_ordena_em_niveis():
    cols = [Coluna("nome", "Nome"), Coluna("bairro", "Bairro", "lista"), Coluna("nasc", "Nascimento", "aniversario"),
            Coluna("ok", "Credo", "simnao"), Coluna("valor", "Valor", "moeda"), Coluna("setores", "Setores", "lista")]
    linhas = [
        {"nome": "Bruna", "bairro": "Centro", "nasc": date(1990, 3, 5), "ok": True, "valor": 10, "setores": ["Louvor", "Kids"]},
        {"nome": "Ana", "bairro": "Centro", "nasc": date(1980, 3, 1), "ok": False, "valor": 30, "setores": []},
        {"nome": "Ângela", "bairro": "Bueno", "nasc": date(1970, 7, 9), "ok": True, "valor": 20, "setores": ["Kids"]},
        {"nome": "Caio", "bairro": None, "nasc": None, "ok": True, "valor": None, "setores": ["Louvor"]},
    ]
    e = tabelas.ler_estado(P([("f.bairro", "Centro"), ("f.bairro", "Bueno"), ("ordem", "bairro:asc,nome:desc")]), cols)
    r = tabelas.aplicar(linhas, cols, e)
    assert [l["nome"] for l in r["linhas"]] == ["Ângela", "Bruna", "Ana"]
    # Quantidades da lista consideram os demais filtros, não o da própria coluna; vazio aparece como (em branco)
    assert dict(r["opcoes"]["bairro"]) == {"Bueno": 1, "Centro": 2, tabelas.VAZIO: 1}
    # Mês do aniversário, sem ano; Sim/Não; texto sem acento; faixa de valor; lista com vários valores por célula
    assert [l["nome"] for l in tabelas.aplicar(linhas, cols, tabelas.ler_estado(P([("f.nasc.mes", "3")]), cols))["linhas"]] == ["Bruna", "Ana"]
    assert len(tabelas.aplicar(linhas, cols, tabelas.ler_estado(P([("f.ok", "nao")]), cols))["linhas"]) == 1
    assert len(tabelas.aplicar(linhas, cols, tabelas.ler_estado(P([("f.nome", "angela")]), cols))["linhas"]) == 1
    assert len(tabelas.aplicar(linhas, cols, tabelas.ler_estado(P([("f.valor.de", "15"), ("f.valor.ate", "25")]), cols))["linhas"]) == 1
    assert len(tabelas.aplicar(linhas, cols, tabelas.ler_estado(P([("f.setores", "Kids")]), cols))["linhas"]) == 2
    # Aniversário ordena por mês/dia, vazios no fim
    r = tabelas.aplicar(linhas, cols, tabelas.ler_estado(P([("ordem", "nasc:asc")]), cols))
    assert [l["nome"] for l in r["linhas"]] == ["Ana", "Bruna", "Ângela", "Caio"]
    # Coluna desconhecida ou repetida na ordem é ignorada
    assert tabelas.ler_estado(P([("ordem", "x:asc,nome:asc,nome:desc")]), cols)["ordem"] == [("nome", "asc")]


def test_lista_sensivel_nao_vira_filtro_de_lista():
    cols = [Coluna("cpf", "CPF", "lista", sensivel=True)]
    r = tabelas.aplicar([{"cpf": "1"}], cols, tabelas.ler_estado(P([]), cols))
    assert "cpf" not in r["opcoes"]


# ---------------------------------------------------------------------------
# Catálogo e limite por perfil
# ---------------------------------------------------------------------------
def test_catalogo_mostra_so_o_que_cada_perfil_pode_emitir():
    _base()
    membro = logado("membro")
    r = membro.get("/relatorios")
    assert r.status_code == 200 and "Agenda do período" in r.text and "Minhas inscrições" in r.text
    assert "Participantes" not in r.text and "Membros por situação" not in r.text and "Auditoria" not in r.text
    assert "Planilha (CSV)" not in r.text
    for chave in ("participantes", "a-receber", "membros", "aniversariantes", "auditoria", "usuarios"):
        assert membro.get(f"/relatorios/{chave}").status_code == 403
    assert membro.get("/relatorios/agenda?formato=csv").status_code == 403

    coord = logado("coordenacao")
    r = coord.get("/relatorios")
    assert "Participantes" in r.text and "Membros por situação" not in r.text and "Usuários e perfis" not in r.text
    assert coord.get("/relatorios/membros").status_code == 403
    assert coord.get("/relatorios/pendencias").status_code == 403

    sec = logado("secretaria")
    r = sec.get("/relatorios")
    assert "Membros por situação" in r.text and "Usuários e perfis" not in r.text and "Planilha (CSV)" in r.text
    assert sec.get("/relatorios/auditoria").status_code == 403
    adm = logado("admin")
    assert "Usuários e perfis" in adm.get("/relatorios").text
    for r in __import__("app.rotas.relatorios", fromlist=["CATALOGO"]).CATALOGO:
        assert adm.get(f"/relatorios/{r.chave}").status_code == 200, r.chave


def test_coordenacao_so_ve_seus_setores_mesmo_mexendo_no_endereco():
    ids = _base()
    coord = _coord_jovens(ids)
    r = coord.get("/relatorios/participantes")
    assert "Carla Mendes" in r.text and "Diego Souza" in r.text and "Elaine Costa" not in r.text
    # Escolher setor ou evento alheio pelo endereço não traz nada de fora
    r = coord.get(f"/relatorios/participantes?setor=Família&evento={ids['ef']}")
    assert "Elaine Costa" not in r.text and "Encontro de Casais" not in r.text
    r = coord.get("/relatorios/a-receber?f.titulo=Encontro+de+Casais")
    assert "Elaine Costa" not in r.text
    # Lista de presença sem telefone; telefone só em "A receber"
    assert "(62) 9 8888-7777" not in coord.get("/relatorios/participantes").text
    assert "(62) 9 7777-6666" in coord.get("/relatorios/a-receber").text
    # Financeiro só do setor
    r = coord.get("/relatorios/financeiro")
    assert "Culto Jovem" in r.text and "Encontro de Casais" not in r.text and "R$ 15,00" in r.text


def test_secretaria_ve_todos_os_setores():
    _base()
    sec = logado("secretaria")
    r = sec.get("/relatorios/a-receber")
    assert "Diego Souza" in r.text and "Elaine Costa" in r.text and "R$ 70,00" in r.text
    r = sec.get("/relatorios/a-receber?setor=Família")
    assert "Elaine Costa" in r.text and "Diego Souza" not in r.text


def test_membro_ve_so_as_proprias_inscricoes():
    ids = _base()
    sem_ficha = logado("membro")
    assert "não está ligado a uma ficha" in sem_ficha.get("/relatorios/minhas-inscricoes").text
    u = criar("membro", email="ana@mevam.test", membro_id=ids["m1"])
    from conftest import entrar, novo_cliente
    c = novo_cliente()
    entrar(c, u["email"])
    r = c.get("/relatorios/minhas-inscricoes")
    assert "Culto Jovem" in r.text and "Diego" not in r.text and "Elaine" not in r.text
    assert "R$ 20,00" in c.get("/relatorios/extrato").text


# ---------------------------------------------------------------------------
# LGPD
# ---------------------------------------------------------------------------
def test_relatorios_de_pessoas_respeitam_lgpd():
    _base()
    sec = logado("secretaria")
    r = sec.get("/relatorios/membros")
    assert "Ana Paula Ribeiro" in r.text and "Anonimizado" not in r.text.split("Filtros aplicados")[1]
    assert "529.982.247-25" not in r.text and "52998224725" not in r.text
    assert r.headers.get("cache-control") == "no-store"
    # Aniversariantes: dia/mês, sem ano
    r = sec.get(f"/relatorios/aniversariantes?mes={HOJE.month}")
    assert f"05/{HOJE.month:02d}" in r.text and f"05/{HOJE.month:02d}/1990" not in r.text
    # Estatísticas: grupos com menos de 3 pessoas não aparecem com número
    r = sec.get("/relatorios/estatisticas")
    assert "menos de 3" in r.text and "Ana Paula" not in r.text
    # Pendências
    r = sec.get("/relatorios/pendencias")
    assert "Bruno Santos" in r.text and "Sem CPF" in r.text and "Credo não assinado" in r.text


def test_emissao_impressao_e_planilha_vao_para_auditoria():
    _base()
    sec = logado("secretaria")
    sec.get("/relatorios/a-receber")
    r = sec.get("/relatorios/a-receber?formato=csv&f.titulo=Culto+Jovem")
    assert r.status_code == 200 and "text/csv" in r.headers["content-type"]
    assert "Diego Souza" in r.text and "Elaine" not in r.text and r.text.startswith("﻿Nome;Telefone")
    assert post(sec, "/relatorios/impressao", {"relatorio": "a-receber", "filtros": "Setor: Jovens", "linhas": "1"},
                pagina="/relatorios/a-receber").status_code == 200
    with db.engine().connect() as c:
        acoes = list(c.execute(select(db.auditoria.c.acao, db.auditoria.c.detalhes)).all())
    nomes = [a for a, _ in acoes]
    assert "RELATORIO_EMITIDO" in nomes and "RELATORIO_PLANILHA" in nomes and "RELATORIO_IMPRESSO" in nomes
    assert any("Evento: contém" in (d or "") or "Evento:" in (d or "") for a, d in acoes if a == "RELATORIO_PLANILHA")
    # Impressão de relatório de outro perfil é recusada
    membro = logado("membro")
    assert post(membro, "/relatorios/impressao", {"relatorio": "auditoria"}, pagina="/relatorios").status_code == 403


def test_meus_filtros_salvar_usar_e_excluir():
    _base()
    sec = logado("secretaria")
    r = post(sec, "/relatorios/salvar", {"relatorio": "membros", "nome": "Ativos do Centro",
                                         "consulta": "f.status=Ativo&f.bairro=Centro&ordem=nome_completo%3Aasc"},
             pagina="/relatorios/membros")
    assert r.status_code == 303
    pagina = sec.get("/relatorios/membros")
    assert "Ativos do Centro" in pagina.text
    with db.engine().connect() as c:
        sid = c.execute(select(db.relatorios_salvos.c.id)).scalar()
    # Outro usuário não vê nem exclui
    outra = logado("admin")
    assert "Ativos do Centro" not in outra.get("/relatorios/membros").text
    post(outra, f"/relatorios/salvos/{sid}/excluir", {}, pagina="/relatorios")
    with db.engine().connect() as c:
        assert c.execute(select(db.relatorios_salvos.c.id)).scalar() == sid
    post(sec, f"/relatorios/salvos/{sid}/excluir", {}, pagina="/relatorios")
    with db.engine().connect() as c:
        assert c.execute(select(db.relatorios_salvos.c.id)).scalar() is None


# ---------------------------------------------------------------------------
# Lista de Membros com filtro e ordenação nos cabeçalhos
# ---------------------------------------------------------------------------
def test_lista_de_membros_filtra_e_ordena_pelos_cabecalhos():
    _base()
    sec = logado("secretaria")
    r = sec.get("/membros?f.bairro=Centro")
    assert "Ana Paula Ribeiro" in r.text and "Bruno Santos" not in r.text and "Bairro: Centro" in r.text
    r = sec.get("/membros?ordem=nome_completo:desc")
    assert r.text.index("Bruno Santos") < r.text.index("Ana Paula Ribeiro")
    r = sec.get("/membros?f.status=Aguardando+An%C3%A1lise")
    assert "Bruno Santos" in r.text and "Ana Paula Ribeiro" not in r.text
    r = sec.get("/membros?f.setores=Jovens")
    assert "Ana Paula Ribeiro" in r.text and "Bruno Santos" not in r.text
    # Colunas escolhidas
    r = sec.get("/membros?cols=nome_completo,credo_aceito")
    assert "Credo assinado" in r.text and ">WhatsApp" not in r.text
    # Planilha com os mesmos filtros (Secretaria pode; vai para a auditoria)
    r = sec.get("/membros?f.bairro=Centro&formato=csv")
    assert "Ana Paula Ribeiro" in r.text and "Bruno" not in r.text
    # Coordenação continua sem acesso à lista
    assert logado("coordenacao").get("/membros").status_code in (302, 303, 403)
    # Colunas de controle só para o Adm
    assert "Origem do cadastro" not in sec.get("/membros").text
    assert "Origem do cadastro" in logado("admin").get("/membros").text


def test_relatorio_antigo_do_periodo_leva_para_a_central():
    _base()
    sec = logado("secretaria")
    r = sec.get("/relatorios/periodo?de=01/10/2026&ate=31/10/2026", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/relatorios/agenda?de=01%2F10%2F2026")
