import re
from datetime import date, datetime

from sqlalchemy import insert, select

from app import datas, db, seguranca
from conftest import SENHA, criar, csrf_de, entrar, logado, novo_cliente, post

FOTO = "data:image/jpeg;base64," + "A" * 200

FICHA_OK = {
    "nome_completo": "maria da silva souza", "data_nascimento": "15/03/1985", "naturalidade": "Goiânia - GO",
    "sexo": "Feminino", "estado_civil": "Casado(a)", "conjuge": "joão souza", "cep": "74000000",
    "endereco": "Rua 1, Qd 2 Lt 3", "bairro": "Setor Bueno", "cidade": "Goiânia - GO",
    "whatsapp": "62999998888", "telefone": "", "email": "Maria@Exemplo.com", "escolaridade": "Ensino Médio",
    "formacao_academica": "Ensino Médio", "profissao": "Professora", "empresa": "Escola X",
    "batizado": "Sim", "data_batismo": "10/10/2010", "congregava_antes": "Não", "onde_congregava": "",
    "area_ministerial": "Louvor", "interesse_batismo_familia": "Não",
    "filhos_json": '[{"nome":"ana souza","data_nascimento":"01/02/2015"}]',
    "foto_3x4": FOTO, "lgpd_consentimento": "sim",
}


def enviar_ficha(cliente, **mudancas):
    pagina = cliente.get("/ficha")
    return cliente.post("/ficha", data={**FICHA_OK, **mudancas, "csrf": csrf_de(pagina.text)}, follow_redirects=False)


def membro_id_mais_recente():
    with db.engine().connect() as c:
        return c.execute(select(db.membros.c.id).order_by(db.membros.c.id.desc())).scalar()


# ---------------------------------------------------------------------------
# Datas
# ---------------------------------------------------------------------------
def test_datas_padrao_brasileiro():
    assert datas.parse_data("15/10/2026") == date(2026, 10, 15)
    assert datas.parse_data("15102026") == date(2026, 10, 15)
    assert datas.parse_data("2026-10-15") == date(2026, 10, 15)
    assert datas.parse_data("31/02/2026") is None
    assert datas.fmt_data(date(2026, 1, 5)) == "05/01/2026"
    assert datas.parse_hora("9:05").strftime("%H:%M") == "09:05"
    assert datas.parse_hora("25:00") is None
    assert datas.iso_evento(date(2026, 11, 15), datas.parse_hora("09:00")) == "2026-11-15T09:00:00"


def test_horario_de_goiania():
    from datetime import datetime, timezone
    utc = datetime(2026, 10, 15, 2, 30, tzinfo=timezone.utc)
    assert datas.fmt_data_hora(utc) == "14/10/2026 23:30"
    assert datas.agora().utcoffset().total_seconds() == -3 * 3600


def test_eventos_legados_sao_lidos():
    assert datas.parse_data_hora_local("2026-11-15T09:00:00").hour == 9
    assert datas.parse_data_hora_local("2026-11-15 09:00:00").minute == 0


# ---------------------------------------------------------------------------
# Login e perfis
# ---------------------------------------------------------------------------
def test_login_direciona_para_inicio_e_mostra_perfil():
    c = logado("secretaria")
    r = c.get("/inicio")
    assert r.status_code == 200
    assert "Secretaria" in r.text and "Fichas aguardando análise" in r.text


def test_login_errado_e_bloqueio_por_tentativas():
    c = novo_cliente()
    u = criar("membro")
    for _ in range(5):
        assert entrar(c, u["email"], "errada").status_code == 401
    r = entrar(c, u["email"])  # senha certa, mas conta bloqueada
    assert r.status_code == 429


def test_rotas_exigem_login():
    c = novo_cliente()
    for url in ("/inicio", "/membros", "/agenda", "/admin/usuarios", "/minha-ficha"):
        r = c.get(url, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/entrar")


def test_membro_nao_acessa_areas_de_gestao():
    c = logado("membro")
    assert c.get("/membros").status_code == 403
    assert c.get("/admin/usuarios").status_code == 403
    assert c.get("/eventos/novo").status_code == 403
    assert c.get("/agenda").status_code == 200


def test_secretaria_nao_acessa_administracao():
    c = logado("secretaria")
    assert c.get("/membros").status_code == 200
    assert c.get("/admin/usuarios").status_code == 403
    assert c.get("/admin/auditoria").status_code == 403


def test_post_sem_csrf_e_recusado():
    c = logado("admin")
    r = c.post("/admin/usuarios/novo", data={"nome": "Fulano de Tal", "email": "f@x.com", "perfil": "admin"},
               follow_redirects=False)
    assert r.status_code == 400
    with db.engine().connect() as cx:
        assert cx.execute(select(db.usuarios).where(db.usuarios.c.email == "f@x.com")).first() is None


def test_senha_provisoria_obriga_troca():
    c = novo_cliente()
    u = criar("membro", trocar=True)
    r = entrar(c, u["email"])
    assert r.headers["location"] == "/trocar-senha"
    assert c.get("/agenda", follow_redirects=False).headers["location"] == "/trocar-senha"
    r = post(c, "/trocar-senha", {"atual": SENHA, "nova": "NovaSenha99", "confirma": "NovaSenha99"}, pagina="/trocar-senha")
    assert r.headers["location"] == "/inicio"
    assert c.get("/agenda").status_code == 200


def test_desativar_usuario_derruba_sessao():
    adm = logado("admin")
    membro = logado("membro", email="m2@mevam.test")
    assert membro.get("/agenda").status_code == 200
    post(adm, f"/admin/usuarios/{membro.usuario['id']}", {"perfil": "membro"}, pagina="/admin/usuarios")
    assert membro.get("/agenda", follow_redirects=False).status_code == 303


def test_admin_nao_remove_o_ultimo_admin():
    adm = logado("admin")
    post(adm, f"/admin/usuarios/{adm.usuario['id']}", {"perfil": "membro", "ativo": "sim"}, pagina="/admin/usuarios")
    with db.engine().connect() as c:
        assert c.execute(select(db.usuarios.c.perfil).where(db.usuarios.c.id == adm.usuario["id"])).scalar() == "admin"


def test_admin_cria_usuario_com_senha_provisoria_exibida_uma_vez():
    adm = logado("admin")
    post(adm, "/admin/usuarios/novo", {"nome": "Ana Lider", "email": "ana@x.com", "perfil": "secretaria"},
         pagina="/admin/usuarios")
    pagina = adm.get("/admin/usuarios").text
    senha = re.search(r'monospace;font-size:1.15rem">([^<]+)<', pagina).group(1)
    assert "Senha provisória" not in adm.get("/admin/usuarios").text  # não aparece de novo
    nova = novo_cliente()
    assert entrar(nova, "ana@x.com", senha).headers["location"] == "/trocar-senha"


def test_hash_legado_de_100_mil_iteracoes_continua_valido_e_e_atualizado():
    h, s, it = seguranca.hash_senha("Antiga123", iteracoes=100_000)
    with db.engine().begin() as c:
        c.execute(insert(db.usuarios).values(nome="Legado Silva", email="legado@x.com", senha_hash=h, salt=s,
                                             iteracoes=it, perfil="membro", ativo=True, trocar_senha=False,
                                             tentativas_falhas=0))
    assert entrar(novo_cliente(), "legado@x.com", "Antiga123").status_code == 303
    with db.engine().connect() as c:
        assert c.execute(select(db.usuarios.c.iteracoes).where(db.usuarios.c.email == "legado@x.com")).scalar() == 600_000


# ---------------------------------------------------------------------------
# Ficha de membro
# ---------------------------------------------------------------------------
def test_ficha_publica_grava_normalizado_e_aguarda_analise():
    c = novo_cliente()
    r = enviar_ficha(c)
    assert r.status_code == 303 and r.headers["location"] == "/ficha/recebida"
    assert "#" in c.get("/ficha/recebida").text
    with db.engine().connect() as cx:
        m = cx.execute(select(db.membros)).mappings().one()
    assert m["nome_completo"] == "Maria da Silva Souza"
    assert m["conjuge"] == "João Souza"
    assert m["data_nascimento"] == date(1985, 3, 15)
    assert m["whatsapp"] == "(62) 99999-8888"
    assert m["cep"] == "74000-000"
    assert m["email"] == "maria@exemplo.com"
    assert m["status"] == "Aguardando Análise"
    assert m["lgpd_consentimento"] is True and m["lgpd_versao_termo"]
    assert m["filhos"] == [{"nome": "Ana Souza", "data_nascimento": "01/02/2015"}]


def test_ficha_valida_campos_obrigatorios_foto_e_lgpd():
    c = novo_cliente()
    r = enviar_ficha(c, nome_completo="", data_nascimento="31/02/1990", foto_3x4="", lgpd_consentimento="")
    assert r.status_code == 400
    assert "Nome completo é obrigatório" in r.text
    assert "Data de nascimento inválida" in r.text
    assert "foto 3x4" in r.text and "LGPD" in r.text
    assert membro_id_mais_recente() is None


def test_ficha_sem_csrf_nao_grava():
    c = novo_cliente()
    c.get("/ficha")
    c.post("/ficha", data=FICHA_OK, follow_redirects=False)
    assert membro_id_mais_recente() is None


def test_ficha_escapa_html():
    c = novo_cliente()
    enviar_ficha(c, profissao="<script>alert(1)</script>")
    sec = logado("secretaria")
    pagina = sec.get(f"/membros/{membro_id_mais_recente()}").text
    assert "<script>alert(1)</script>" not in pagina
    assert "&lt;script&gt;" in pagina


def test_fluxo_completo_validacao_credo_e_pdf():
    enviar_ficha(novo_cliente())
    mid = membro_id_mais_recente()
    token = seguranca.token_link("credo", mid)
    publico = novo_cliente()

    # Antes da validação o link do Credo não abre
    assert publico.get(f"/credo/{mid}?t={token}").status_code == 403

    sec = logado("secretaria")
    post(sec, f"/membros/{mid}/validar", {}, pagina=f"/membros/{mid}")
    detalhe = sec.get(f"/membros/{mid}").text
    assert "wa.me/5562999998888" in detalhe and f"/credo/{mid}?t={token}" in detalhe

    # Token errado não abre
    assert publico.get(f"/credo/{mid}?t=errado").status_code == 403
    pagina = publico.get(f"/credo/{mid}?t={token}")
    assert pagina.status_code == 200 and "Credo Apostólico" in pagina.text
    assert "A Natureza de Deus e de Seu Cristo" in pagina.text
    r = publico.post(f"/credo/{mid}", data={"t": token, "csrf": csrf_de(pagina.text), "aceite": "sim",
                                            "nome_assinante": "Maria da Silva Souza",
                                            "assinatura": "data:image/png;base64,iVBORw0KGgo="}, follow_redirects=False)
    assert r.status_code == 303
    with db.engine().connect() as c:
        m = c.execute(select(db.membros).where(db.membros.c.id == mid)).mappings().one()
    assert m["credo_aceito"] and m["status"] == "Ativo" and len(m["hash_autenticidade"]) == 64

    pdf = publico.get(f"/credo/{mid}/pdf?t={token}")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert sec.get(f"/membros/{mid}/pdf").content.startswith(b"%PDF")


def test_pdf_nao_vaza_ficha_de_outra_pessoa():
    enviar_ficha(novo_cliente())
    mid = membro_id_mais_recente()
    assert novo_cliente().get(f"/membros/{mid}/pdf", follow_redirects=False).status_code == 303
    outro = logado("membro")
    assert outro.get(f"/membros/{mid}/pdf").status_code == 403
    assert novo_cliente().get(f"/credo/{mid}/pdf?t=000").status_code == 403


def test_membro_ve_somente_a_propria_ficha():
    enviar_ficha(novo_cliente())
    mid = membro_id_mais_recente()
    dono = logado("membro", email="maria@exemplo.com", membro_id=mid)
    r = dono.get("/minha-ficha")
    assert r.status_code == 200 and "Maria da Silva Souza" in r.text
    assert dono.get(f"/membros/{mid}/pdf").status_code == 200
    assert dono.get(f"/membros/{mid}").status_code == 403


def test_secretaria_cria_login_do_membro_apos_validar():
    enviar_ficha(novo_cliente())
    mid = membro_id_mais_recente()
    sec = logado("secretaria")
    post(sec, f"/membros/{mid}/criar-acesso", {}, pagina=f"/membros/{mid}")
    assert "Valide a ficha" in sec.get(f"/membros/{mid}").text
    post(sec, f"/membros/{mid}/validar", {}, pagina=f"/membros/{mid}")
    post(sec, f"/membros/{mid}/criar-acesso", {}, pagina=f"/membros/{mid}")
    with db.engine().connect() as c:
        u = c.execute(select(db.usuarios).where(db.usuarios.c.email == "maria@exemplo.com")).mappings().one()
    assert u["perfil"] == "membro" and u["membro_id"] == mid and u["trocar_senha"]


def test_anonimizacao_lgpd():
    enviar_ficha(novo_cliente())
    mid = membro_id_mais_recente()
    sec = logado("secretaria")
    post(sec, f"/membros/{mid}/anonimizar", {"motivo": "Pedido expresso da titular"}, pagina=f"/membros/{mid}")
    with db.engine().connect() as c:
        m = c.execute(select(db.membros).where(db.membros.c.id == mid)).mappings().one()
        log = c.execute(select(db.auditoria).where(db.auditoria.c.acao == "ANONIMIZACAO_LGPD")).mappings().one()
    assert m["email"] is None and m["foto_3x4"] is None and m["whatsapp"] is None
    assert m["nome_completo"] == f"Titular Anonimizado #{mid}"
    assert "Pedido expresso" in log["detalhes"]


def test_visualizacao_de_ficha_fica_auditada():
    enviar_ficha(novo_cliente())
    mid = membro_id_mais_recente()
    sec = logado("secretaria")
    sec.get(f"/membros/{mid}")
    with db.engine().connect() as c:
        acoes = [r[0] for r in c.execute(select(db.auditoria.c.acao))]
    assert "CADASTRO_MEMBRO" in acoes and "VISUALIZACAO_FICHA" in acoes and "LOGIN" in acoes


def test_exportacao_csv_somente_admin():
    enviar_ficha(novo_cliente())
    assert logado("secretaria").get("/membros/exportar.csv").status_code == 403
    r = logado("admin").get("/membros/exportar.csv")
    assert r.status_code == 200 and "Maria da Silva Souza" in r.text and "15/03/1985" in r.text


# ---------------------------------------------------------------------------
# Agenda (mesmas tabelas da Agenda atual no Supabase)
# ---------------------------------------------------------------------------
EVENTO = {"titulo": "Family Day", "departamento": "Família", "data": "15/11/2026", "hora": "09:00",
          "valor_inscricao": "50,00", "controle_vagas": "fixo", "limite_vagas": "2", "local": "Templo sede"}


def criar_evento(cliente, **mudancas):
    with db.engine().begin() as c:
        if not c.execute(select(db.departamentos).where(db.departamentos.c.nome == "Família")).first():
            c.execute(insert(db.departamentos).values(nome="Família", responsavel="Pr. João"))
            c.execute(insert(db.departamentos).values(nome="Jovens", responsavel="Lia"))
    return post(cliente, "/eventos/novo", {**EVENTO, **mudancas}, pagina="/eventos/novo")


def test_evento_gravado_no_formato_legado():
    sec = logado("secretaria")
    r = criar_evento(sec)
    assert r.status_code == 303
    with db.engine().connect() as c:
        e = c.execute(select(db.eventos)).mappings().one()
    assert datas.parse_data_hora_local(e["data_inicio"]) == datetime(2026, 11, 15, 9, 0)
    assert e["valor_inscricao"] == 50.0 and e["limite_vagas"] == 2
    assert "Pessoa Secretaria em" in e["criado_por"]


def test_conflito_de_data_entre_setores():
    sec = logado("secretaria")
    criar_evento(sec)
    r = criar_evento(sec, titulo="Culto Jovem", departamento="Jovens", hora="19:00")
    assert r.status_code == 400 and "Conflito de agenda" in r.text


def test_inscricoes_vagas_valores_e_financeiro():
    sec = logado("secretaria")
    eid = int(criar_evento(sec).headers["location"].split("/")[-1])
    pag = f"/eventos/{eid}"
    post(sec, f"{pag}/inscricoes", {"nome": "ana", "tipo_ingresso": "Inteira", "forma_pagamento": "Pix",
                                    "status_pagamento": "Confirmado", "lgpd": "sim"}, pagina=pag)
    post(sec, f"{pag}/inscricoes", {"nome": "bia", "tipo_ingresso": "Meia (5-11 anos)", "forma_pagamento": "A Receber",
                                    "status_pagamento": "Confirmado", "lgpd": "sim"}, pagina=pag)
    post(sec, f"{pag}/inscricoes", {"nome": "caio", "tipo_ingresso": "Inteira", "forma_pagamento": "Pix",
                                    "status_pagamento": "Confirmado", "lgpd": "sim"}, pagina=pag)  # sem vaga
    post(sec, f"{pag}/custos", {"descricao": "Lanche", "valor": "30,00"}, pagina=pag)
    with db.engine().connect() as c:
        insc = c.execute(select(db.inscricoes).order_by(db.inscricoes.c.id)).mappings().all()
    assert [i["nome"] for i in insc] == ["Ana", "Bia"]
    assert insc[1]["valor_pago"] == 25.0 and insc[1]["status_pagamento"] == "Pendente"
    texto = sec.get(pag).text
    assert "R$ 50,00" in texto and "R$ 30,00" in texto and "R$ 20,00" in texto and "R$ 25,00" in texto


def test_inscricao_exige_consentimento_lgpd():
    sec = logado("secretaria")
    eid = int(criar_evento(sec).headers["location"].split("/")[-1])
    post(sec, f"/eventos/{eid}/inscricoes", {"nome": "ana", "tipo_ingresso": "Inteira"}, pagina=f"/eventos/{eid}")
    with db.engine().connect() as c:
        assert c.execute(select(db.inscricoes)).first() is None


def test_evento_com_inscricoes_nao_e_excluido():
    sec = logado("secretaria")
    eid = int(criar_evento(sec).headers["location"].split("/")[-1])
    post(sec, f"/eventos/{eid}/inscricoes", {"nome": "ana", "tipo_ingresso": "Inteira", "lgpd": "sim"}, pagina=f"/eventos/{eid}")
    post(sec, f"/eventos/{eid}/excluir", {"justificativa": "Chuva forte"}, pagina=f"/eventos/{eid}")
    with db.engine().connect() as c:
        assert c.execute(select(db.eventos)).first() is not None


def test_editar_evento_exige_justificativa_e_registra_historico():
    sec = logado("secretaria")
    eid = int(criar_evento(sec).headers["location"].split("/")[-1])
    r = post(sec, f"/eventos/{eid}/editar", {**EVENTO, "hora": "10:00"}, pagina=f"/eventos/{eid}/editar")
    assert r.status_code == 400
    post(sec, f"/eventos/{eid}/editar", {**EVENTO, "hora": "10:00", "justificativa": "Mudança aprovada"},
         pagina=f"/eventos/{eid}/editar")
    with db.engine().connect() as c:
        e = c.execute(select(db.eventos)).mappings().one()
    assert datas.parse_data_hora_local(e["data_inicio"]) == datetime(2026, 11, 15, 10, 0) and "Mudança aprovada" in e["historico_alteracoes"]


def test_membro_ve_agenda_sem_dados_financeiros():
    sec = logado("secretaria")
    eid = int(criar_evento(sec).headers["location"].split("/")[-1])
    post(sec, f"/eventos/{eid}/inscricoes", {"nome": "ana", "telefone": "62988887777", "lgpd": "sim"}, pagina=f"/eventos/{eid}")
    membro = logado("membro")
    assert "Family Day" in membro.get("/agenda?mes=2026-11").text
    pagina = membro.get(f"/eventos/{eid}").text
    assert "Family Day" in pagina and "Ana" not in pagina and "Receita" not in pagina


def test_renomear_setor_mantem_eventos_vinculados():
    adm = logado("admin")
    criar_evento(adm)
    with db.engine().connect() as c:
        sid = c.execute(select(db.departamentos.c.id).where(db.departamentos.c.nome == "Família")).scalar()
    post(adm, "/admin/setores/salvar", {"id": str(sid), "nome": "Famílias", "responsavel": "Pr. João"}, pagina="/admin/setores")
    with db.engine().connect() as c:
        assert c.execute(select(db.eventos.c.departamento)).scalar() == "Famílias"


# ---------------------------------------------------------------------------
# Cabeçalhos de segurança
# ---------------------------------------------------------------------------
def test_cabecalhos_de_seguranca_e_saude():
    r = novo_cliente().get("/healthz")
    assert r.json()["status"] == "ok"
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    pagina = novo_cliente().get("/entrar")
    assert "httponly" in pagina.headers["set-cookie"].lower()


def test_botao_de_tema_em_todas_as_telas():
    """Login, telas públicas e telas internas trazem o botão dia/noite e aplicam a escolha antes de pintar."""
    for c, url in ((novo_cliente(), "/entrar"), (novo_cliente(), "/ficha"), (logado("membro"), "/inicio")):
        html = c.get(url).text
        assert 'class="botao-tema"' in html, url
        assert 'localStorage.getItem("tema")' in html, url
        assert "/static/js/tema.js" in html, url
    css = novo_cliente().get("/static/css/app.css").text
    assert 'html[data-tema="escuro"]' in css and "prefers-color-scheme: dark" in css


def test_producao_recusa_sqlite():
    """Em produção o app não sobe com SQLite: o disco do Render gratuito é apagado a cada deploy ou reinício."""
    import subprocess, sys
    base = {"PATH": "", "AMBIENTE": "producao", "SECRET_KEY": "x" * 48}
    r = subprocess.run([sys.executable, "-c", "import app.config"], capture_output=True, text=True,
                       env={**base, "DATABASE_URL": "sqlite:///./igreja.db"})
    assert r.returncode != 0 and "Supabase" in r.stderr
    ok = subprocess.run([sys.executable, "-c", "import app.config"], capture_output=True, text=True,
                        env={**base, "DATABASE_URL": "postgresql://u:s@h:5432/postgres"})
    assert ok.returncode == 0, ok.stderr
