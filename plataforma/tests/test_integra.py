"""v2.12.0: INTEGRA como porta de entrada."""
from datetime import timedelta

from sqlalchemy import insert, select, update

from app import datas, db, integra
from conftest import CODIGO_INTEGRA, criar, csrf_de, entrar, logado, novo_cliente, post
from test_plataforma import FICHA_OK, enviar_ficha, gerar_cpf, membro_id_mais_recente


def _m(mid):
    with db.engine().connect() as c:
        return dict(c.execute(select(db.membros).where(db.membros.c.id == mid)).mappings().first())


def _usuario(uid):
    with db.engine().connect() as c:
        return dict(c.execute(select(db.usuarios).where(db.usuarios.c.id == uid)).mappings().first())


def _ativo_antigo(nome="Pedro Antigo", email="pedro@mevam.test", cpf="52998224725"):
    """Ficha anterior à v2.12.0: ativa, Credo assinado, sem INTEGRA informado, com login de membro."""
    with db.engine().begin() as c:
        mid = c.execute(insert(db.membros).values(
            nome_completo=nome, status="Ativo", email=email, cpf=cpf, credo_aceito=True,
            data_registro=datas.hoje())).inserted_primary_key[0]
    u = criar("membro", email=email, membro_id=mid)
    return mid, u


def test_ficha_com_codigo_vai_para_analise_e_sem_integra_fica_nc():
    cli = novo_cliente()
    assert enviar_ficha(cli).status_code == 303
    m = _m(membro_id_mais_recente())
    assert m["status"] == "Aguardando Análise" and m["integra_situacao"] == "concluido" and m["integra_turma_id"]

    assert enviar_ficha(novo_cliente(), integra="Não", integra_codigo="").status_code == 303
    m = _m(membro_id_mais_recente())
    assert m["status"] == db.NC_INTEGRA and m["integra_situacao"] == "nao_concluido"

    r = enviar_ficha(novo_cliente(), integra="Sim", integra_codigo="", integra_data="05/10/2026")
    assert r.status_code == 303
    m = _m(membro_id_mais_recente())
    assert m["status"] == db.NC_INTEGRA and m["integra_situacao"] == "aguardando"


def test_ficha_exige_resposta_codigo_existente_e_maioridade():
    cli = novo_cliente()
    assert enviar_ficha(cli, integra="").status_code == 400
    r = enviar_ficha(cli, integra_codigo="ZZZZZZ")
    assert r.status_code == 400 and "Código não encontrado" in r.text
    menor = (datas.hoje() - timedelta(days=17 * 365)).strftime("%d/%m/%Y")
    r = enviar_ficha(cli, data_nascimento=menor)
    assert r.status_code == 400 and "a partir de 18 anos" in r.text


def test_nc_integra_nao_valida_ate_secretaria_registrar():
    enviar_ficha(novo_cliente(), integra="Não", integra_codigo="")
    mid = membro_id_mais_recente()
    sec = logado("secretaria")
    post(sec, f"/membros/{mid}/validar", {}, pagina=f"/membros/{mid}")
    assert _m(mid)["status"] == db.NC_INTEGRA
    html = sec.get(f"/membros/{mid}").text
    assert "N/C INTEGRA" in html and "Registrar conclusão" in html
    assert post(sec, f"/membros/{mid}/integra", {"acao": "registrar", "data": "01/09/2026"},
                pagina=f"/membros/{mid}").status_code == 303
    m = _m(mid)
    assert m["status"] == "Aguardando Análise" and m["integra_situacao"] == "concluido"
    post(sec, f"/membros/{mid}/validar", {}, pagina=f"/membros/{mid}")
    assert _m(mid)["status"] == "Validado pela Secretaria"


def test_qr_code_registra_ficha_existente_e_abre_ficha_para_quem_nao_tem():
    cpf = gerar_cpf(222333444)
    enviar_ficha(novo_cliente(), integra="Não", integra_codigo="", cpf=cpf)
    mid = membro_id_mais_recente()
    cli = novo_cliente()
    pag = cli.get(f"/integra/c/{CODIGO_INTEGRA.lower()}")
    assert pag.status_code == 200 and "Turma de teste" in pag.text
    r = cli.post(f"/integra/c/{CODIGO_INTEGRA}", data={"cpf": cpf, "csrf": csrf_de(pag.text)})
    assert r.status_code == 200 and "INTEGRA registrado" in r.text
    assert _m(mid)["status"] == "Aguardando Análise"
    # CPF sem ficha: abre a ficha com o código preenchido
    r = cli.post(f"/integra/c/{CODIGO_INTEGRA}", data={"cpf": gerar_cpf(555666777), "csrf": csrf_de(pag.text)},
                 follow_redirects=False)
    assert r.headers["location"] == f"/ficha?integra={CODIGO_INTEGRA}"
    assert 'value="TESTE1"' in cli.get(r.headers["location"]).text
    # Código vencido
    with db.engine().begin() as c:
        c.execute(update(db.integra_turmas).values(codigo_valido_ate=datas.agora_utc() - timedelta(minutes=1)))
    assert "já venceu" in cli.get(f"/integra/c/{CODIGO_INTEGRA}").text


def test_secretaria_cria_turma_e_inclui_concluinte():
    sec = logado("secretaria")
    r = post(sec, "/integra/turmas", {"nome": "INTEGRA Novembro", "data_conclusao": "20/11/2026"}, pagina="/integra")
    assert r.status_code == 303
    tid = int(r.headers["location"].rsplit("/", 1)[1])
    html = sec.get(f"/integra/turmas/{tid}").text
    with db.engine().connect() as c:
        t = c.execute(select(db.integra_turmas).where(db.integra_turmas.c.id == tid)).mappings().first()
    assert len(t["codigo"]) == 6 and t["codigo"] in html
    enviar_ficha(novo_cliente(), integra="Não", integra_codigo="", nome_completo="Lucas Turma Nova")
    mid = membro_id_mais_recente()
    assert "Lucas Turma Nova" in sec.get(f"/integra/turmas/{tid}?q=Lucas").text
    post(sec, f"/integra/turmas/{tid}/incluir", {"membro_id": mid}, pagina=f"/integra/turmas/{tid}")
    m = _m(mid)
    assert m["integra_turma_id"] == tid and m["status"] == "Aguardando Análise"
    assert "/integra" in sec.get("/inicio").text  # item no menu


def test_campanha_prazo_bloqueio_e_liberacao_pela_secretaria():
    mid, u = _ativo_antigo()
    sec = logado("secretaria")
    assert "1</b> sem pedido" in sec.get("/integra").text
    post(sec, "/integra/campanha", {}, pagina="/integra")
    m = _m(mid)
    assert m["integra_pedido_em"] and m["integra_prazo"] == datas.hoje() + timedelta(days=30)
    # O membro vê o aviso na tela inicial
    cli = novo_cliente()
    entrar(cli, u["email"])
    assert "Você fez o INTEGRA?" in cli.get("/inicio").text
    # Prazo vencido sem resposta: N/C INTEGRA e login suspenso
    with db.engine().begin() as c:
        c.execute(update(db.membros).where(db.membros.c.id == mid).values(integra_prazo=datas.hoje() - timedelta(days=1)))
    assert integra.rodar_prazos()["suspensos"] == 1
    assert _m(mid)["status"] == db.NC_INTEGRA and not _usuario(u["id"])["ativo"]
    r = entrar(novo_cliente(), u["email"])
    assert r.status_code == 403 and "Procure a Secretaria" in r.text
    # Secretaria dispensa: volta a Ativo e o acesso é religado
    post(sec, f"/membros/{mid}/integra", {"acao": "dispensar", "motivo": "Membro fundador da igreja"}, pagina=f"/membros/{mid}")
    m = _m(mid)
    assert m["status"] == "Ativo" and m["integra_situacao"] == "dispensado" and _usuario(u["id"])["ativo"]
    assert entrar(novo_cliente(), u["email"]).status_code == 303


def test_link_da_campanha_sim_sem_codigo_aguarda_e_nao_suspende():
    mid, u = _ativo_antigo()
    integra.enviar_pedidos()
    link = integra.link_atualizar(mid).split("testserver", 1)[-1].replace("http://localhost:8000", "")
    cli = novo_cliente()
    pag = cli.get(link)
    assert pag.status_code == 200 and "Você fez o INTEGRA?" in pag.text
    r = cli.post(link, data={"integra": "Sim", "integra_data": "10/03/2019", "integra_codigo": "",
                             "csrf": csrf_de(pag.text), "t": link.split("t=")[1]})
    assert r.status_code == 200 and "Aguardando confirmação" in r.text
    m = _m(mid)
    assert m["integra_situacao"] == "aguardando" and m["status"] == "Ativo" and _usuario(u["id"])["ativo"]
    assert integra.rodar_prazos()["suspensos"] == 0  # respondeu: sai da contagem do prazo
    # Link adulterado
    assert novo_cliente().get(f"/integra/atualizar/{mid}?t=errado").status_code == 403


def test_link_da_campanha_nao_suspende_o_acesso():
    mid, u = _ativo_antigo(nome="Rita Sem Integra", email="rita@mevam.test", cpf="11144477735")
    link = integra.link_atualizar(mid).replace("http://localhost:8000", "")
    cli = novo_cliente()
    pag = cli.get(link)
    cli.post(link, data={"integra": "Não", "csrf": csrf_de(pag.text), "t": link.split("t=")[1]})
    assert _m(mid)["status"] == db.NC_INTEGRA and not _usuario(u["id"])["ativo"]


def test_bloqueio_administrativo_so_adm():
    enviar_ficha(novo_cliente())
    mid = membro_id_mais_recente()
    sec = logado("secretaria")
    post(sec, f"/membros/{mid}/integra", {"acao": "bloquear", "motivo": "Motivo administrativo grave"}, pagina=f"/membros/{mid}")
    assert _m(mid)["integra_situacao"] == "concluido"
    adm = logado("admin")
    post(adm, f"/membros/{mid}/integra", {"acao": "bloquear", "motivo": "Motivo administrativo grave"}, pagina=f"/membros/{mid}")
    m = _m(mid)
    assert m["integra_situacao"] == "bloqueado" and m["status"] == db.NC_INTEGRA
    post(sec, f"/membros/{mid}/integra", {"acao": "dispensar", "motivo": "Tentativa de liberar"}, pagina=f"/membros/{mid}")
    assert _m(mid)["integra_situacao"] == "bloqueado"
    post(adm, f"/membros/{mid}/integra", {"acao": "desbloquear", "motivo": "Situação resolvida com a liderança"}, pagina=f"/membros/{mid}")
    m = _m(mid)
    assert m["integra_situacao"] == "concluido" and m["status"] == "Aguardando Análise"
