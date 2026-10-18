"""v2.9.0: Coordenação por setor/período/evento e inativação/exclusão de membros com justificativa."""
from datetime import timedelta

from sqlalchemy import insert, select, update

from app import coordenacao, datas, db
from conftest import criar, entrar, logado, novo_cliente, post
from test_plataforma import _setor_id, criar_evento, designar


def _br(d):
    return d.strftime("%d/%m/%Y")


def _ficha(nome="Ana Paula Lima", status="Ativo", email="ana@mevam.test"):
    with db.engine().begin() as c:
        return c.execute(insert(db.membros).values(nome_completo=nome, status=status, email=email,
                                                   data_registro=datas.hoje())).inserted_primary_key[0]


def _perfil(uid):
    with db.engine().connect() as c:
        return c.execute(select(db.usuarios.c.perfil).where(db.usuarios.c.id == uid)).scalar()


def _designacoes(uid):
    with db.engine().connect() as c:
        return [dict(r) for r in c.execute(select(db.usuario_setores).where(db.usuario_setores.c.usuario_id == uid)).mappings()]


def _evento_futuro(cli, dias=20, setor="Jovens", titulo="Acampamento"):
    d = datas.hoje() + timedelta(days=dias)
    r = criar_evento(cli, titulo=titulo, departamento=setor, data=_br(d))
    assert r.status_code == 303, r.text
    return r.headers["location"].split("/")[-1]


# ---------------------------------------------------------------------------
# Coordenação
# ---------------------------------------------------------------------------
def test_designar_exige_disponibilidade_e_registra_no_setor_da_ficha():
    sec = logado("secretaria")
    criar_evento(sec)
    mid = _ficha()
    membro = criar("membro", email="ana@mevam.test", membro_id=mid)
    r = designar(sec, membro["id"], "Jovens", disponibilidade="")
    assert r.status_code == 303 and _perfil(membro["id"]) == "membro" and not _designacoes(membro["id"])
    assert designar(sec, membro["id"], "Jovens").status_code == 303
    assert _perfil(membro["id"]) == "coordenacao"
    d = _designacoes(membro["id"])[0]
    assert d["tipo"] == "permanente" and d["disponibilidade"] and d["inicio"] == datas.hoje() and d["fim"] is None
    with db.engine().connect() as c:
        funcao = c.execute(select(db.membro_setores.c.funcao).where(db.membro_setores.c.membro_id == mid)).scalar()
    assert funcao == "Coordenação"
    # Mesma pessoa e setor de novo: pede para editar a que já existe
    designar(sec, membro["id"], "Jovens")
    assert len(_designacoes(membro["id"])) == 1


def test_secretaria_e_adm_podem_ser_designados_sem_mudar_o_perfil():
    adm = logado("admin")
    criar_evento(adm)
    sec = criar("secretaria", email="sec2@mevam.test")
    assert designar(adm, sec["id"], "Família").status_code == 303
    assert _perfil(sec["id"]) == "secretaria" and len(_designacoes(sec["id"])) == 1
    html = adm.get("/coordenacao").text
    assert "Pessoa Secretaria" in html and "Família" in html


def test_ficha_validada_sem_login_ganha_acesso_ao_ser_designada():
    sec = logado("secretaria")
    criar_evento(sec)
    mid = _ficha("Carlos Mendes", email="carlos@mevam.test")
    assert f'value="m:{mid}"' in sec.get("/coordenacao").text
    r = post(sec, "/coordenacao/designar", {"pessoa": f"m:{mid}", "departamento_id": _setor_id("Jovens"),
                                            "tipo": "permanente", "disponibilidade": "sim"}, pagina="/coordenacao")
    assert r.status_code == 303
    with db.engine().connect() as c:
        u = c.execute(select(db.usuarios).where(db.usuarios.c.membro_id == mid)).mappings().first()
    assert u and u["perfil"] == "coordenacao" and u["trocar_senha"]
    assert "Senha provisória" in sec.get("/coordenacao").text


def test_ficha_inativa_nao_recebe_coordenacao():
    sec = logado("secretaria")
    criar_evento(sec)
    mid = _ficha(status="Inativo")
    membro = criar("membro", email="ana@mevam.test", membro_id=mid)
    designar(sec, membro["id"], "Jovens")
    assert not _designacoes(membro["id"]) and _perfil(membro["id"]) == "membro"


def test_coordenacao_por_periodo_vale_so_no_prazo_e_termina_sozinha():
    sec = logado("secretaria")
    criar_evento(sec)
    membro = criar("membro", email="lia@mevam.test")
    hoje = datas.hoje()
    # Término antes do início: recusado
    designar(sec, membro["id"], "Jovens", tipo="periodo", inicio=_br(hoje + timedelta(days=5)), fim=_br(hoje + timedelta(days=1)))
    assert not _designacoes(membro["id"])
    # Mais de 1 ano: recusado
    designar(sec, membro["id"], "Jovens", tipo="periodo", fim=_br(hoje + timedelta(days=400)))
    assert not _designacoes(membro["id"])
    # Começa daqui a 3 dias: ainda não libera o setor
    designar(sec, membro["id"], "Jovens", tipo="periodo", inicio=_br(hoje + timedelta(days=3)), fim=_br(hoje + timedelta(days=30)))
    c = novo_cliente()
    entrar(c, "lia@mevam.test")
    assert c.get("/eventos/novo").status_code == 403
    assert "Começa em" in c.get("/inicio").text
    # Editar para começar hoje libera
    did = _designacoes(membro["id"])[0]["id"]
    post(sec, f"/coordenacao/designacao/{did}/editar", {"tipo": "periodo", "inicio": _br(hoje), "fim": _br(hoje + timedelta(days=30))},
         pagina="/coordenacao")
    assert c.get("/eventos/novo").status_code == 200
    # Prazo vencido: a rotina diária encerra, guarda no histórico e devolve o perfil Membro
    with db.engine().begin() as cx:
        cx.execute(update(db.usuario_setores).where(db.usuario_setores.c.id == did).values(
            inicio=hoje - timedelta(days=10), fim=hoje - timedelta(days=1)))
    assert coordenacao.encerrar_vencidas() == 1
    assert not _designacoes(membro["id"]) and _perfil(membro["id"]) == "membro"
    with db.engine().connect() as cx:
        h = cx.execute(select(db.coordenacoes_historico)).mappings().first()
    assert h["motivo_encerramento"] == "Prazo encerrado" and h["setor_nome"] == "Jovens" and h["tipo"] == "periodo"


def test_coordenacao_para_um_evento_libera_so_aquele_evento():
    sec = logado("secretaria")
    eid = _evento_futuro(sec)
    outro = _evento_futuro(sec, dias=25, titulo="Vigília")
    membro = criar("membro", email="rui@mevam.test")
    # Evento de outro setor: recusado
    familia = _evento_futuro(sec, dias=22, setor="Família", titulo="Jantar")
    designar(sec, membro["id"], "Jovens", tipo="evento", evento_id=familia)
    assert not _designacoes(membro["id"])
    designar(sec, membro["id"], "Jovens", tipo="evento", evento_id=eid)
    d = _designacoes(membro["id"])[0]
    assert d["tipo"] == "evento" and d["fim"] == datas.hoje() + timedelta(days=20)
    c = novo_cliente()
    entrar(c, "rui@mevam.test")
    assert c.get(f"/eventos/{eid}/editar").status_code == 200
    assert c.get(f"/eventos/{outro}/editar").status_code == 403
    assert c.get("/eventos/novo").status_code == 403  # não cria outros eventos no setor
    assert "Acampamento" in c.get("/inicio").text


def test_encerrar_exige_justificativa_e_guarda_historico():
    sec = logado("secretaria")
    criar_evento(sec)
    membro = criar("membro", email="bia@mevam.test")
    designar(sec, membro["id"], "Jovens")
    designar(sec, membro["id"], "Família")
    d = _designacoes(membro["id"])
    post(sec, f"/coordenacao/designacao/{d[0]['id']}/encerrar", {"motivo": "curto"}, pagina="/coordenacao")
    assert len(_designacoes(membro["id"])) == 2
    post(sec, f"/coordenacao/designacao/{d[0]['id']}/encerrar", {"motivo": "Pediu para sair do setor"}, pagina="/coordenacao")
    assert len(_designacoes(membro["id"])) == 1 and _perfil(membro["id"]) == "coordenacao"
    post(sec, f"/coordenacao/{membro['id']}/remover", {"motivo": "Mudou de ministério"}, pagina="/coordenacao")
    assert not _designacoes(membro["id"]) and _perfil(membro["id"]) == "membro"
    html = sec.get("/coordenacao").text
    assert "Pediu para sair do setor" in html and "Mudou de ministério" in html
    with db.engine().connect() as c:
        acoes = set(c.execute(select(db.auditoria.c.acao)).scalars())
    assert {"COORDENACAO_DESIGNADA", "COORDENACAO_ENCERRADA", "COORDENACAO_REMOVIDA"} <= acoes


def test_coordenacao_nao_designa_e_aviso_por_email(monkeypatch):
    from app import envios
    enviados = []
    monkeypatch.setattr(envios, "email_configurado", lambda: True)
    monkeypatch.setattr(envios, "enviar_email", lambda d, a, c: enviados.append((d, a, c)))
    sec = logado("secretaria")
    criar_evento(sec)
    membro = criar("membro", email="eva@mevam.test")
    designar(sec, membro["id"], "Jovens", avisar="sim")
    aviso = [e for e in enviados if e[0] == "eva@mevam.test"]
    assert aviso and "Coordenação do setor Jovens" in aviso[0][1] and "Diretrizes" in aviso[0][2]
    coord = novo_cliente()
    entrar(coord, "eva@mevam.test")
    assert coord.get("/coordenacao").status_code == 403


# ---------------------------------------------------------------------------
# Membros: inativar, reativar, excluir (lixeira), restaurar, excluir definitivamente
# ---------------------------------------------------------------------------
def _status(mid):
    with db.engine().connect() as c:
        return c.execute(select(db.membros).where(db.membros.c.id == mid)).mappings().first()


def _login_ativo(uid):
    with db.engine().connect() as c:
        return c.execute(select(db.usuarios.c.ativo).where(db.usuarios.c.id == uid)).scalar()


def test_inativar_exige_justificativa_desliga_login_e_reativar_religa():
    sec = logado("secretaria")
    criar_evento(sec)
    mid = _ficha()
    membro = criar("membro", email="ana@mevam.test", membro_id=mid)
    designar(sec, membro["id"], "Jovens")
    post(sec, f"/membros/{mid}/inativar", {"motivo": "curto"}, pagina=f"/membros/{mid}")
    assert _status(mid)["status"] == "Ativo"
    post(sec, f"/membros/{mid}/inativar", {"motivo": "Mudou-se para Brasília"}, pagina=f"/membros/{mid}")
    m = _status(mid)
    assert m["status"] == "Inativo" and m["motivo_inativacao"] == "Mudou-se para Brasília" and m["inativado_por"]
    assert not _login_ativo(membro["id"]) and not _designacoes(membro["id"]) and _perfil(membro["id"]) == "membro"
    assert entrar(novo_cliente(), "ana@mevam.test").status_code != 303
    # O seletor de etapa não inativa nem reativa
    post(sec, f"/membros/{mid}/status", {"status": "Ativo"}, pagina=f"/membros/{mid}")
    assert _status(mid)["status"] == "Inativo"
    post(sec, f"/membros/{mid}/reativar", {"motivo": "Voltou a congregar"}, pagina=f"/membros/{mid}")
    assert _status(mid)["status"] == "Ativo" and _login_ativo(membro["id"])
    assert entrar(novo_cliente(), "ana@mevam.test").status_code == 303


def test_excluir_manda_para_lixeira_e_restaurar_devolve():
    sec = logado("secretaria")
    mid = _ficha("Bruno Teste")
    membro = criar("membro", email="ana@mevam.test", membro_id=mid)
    post(sec, f"/membros/{mid}/excluir", {"motivo": "Ficha em duplicidade", "confirmacao": "999"}, pagina=f"/membros/{mid}")
    assert _status(mid)["status"] == "Ativo"
    post(sec, f"/membros/{mid}/excluir", {"motivo": "Ficha em duplicidade", "confirmacao": str(mid)}, pagina=f"/membros/{mid}")
    m = _status(mid)
    assert m["status"] == db.EXCLUIDO and m["status_anterior"] == "Ativo" and not _login_ativo(membro["id"])
    sec.get("/membros")  # consome o aviso da exclusão
    assert "Bruno Teste" not in sec.get("/membros").text
    lixeira = sec.get("/membros/lixeira").text
    assert "Bruno Teste" in lixeira and "Ficha em duplicidade" in lixeira and "excluir-definitivo" not in lixeira
    post(sec, f"/membros/{mid}/restaurar", {"motivo": "Excluída por engano"}, pagina="/membros/lixeira")
    assert _status(mid)["status"] == "Ativo" and _login_ativo(membro["id"])
    assert "Bruno Teste" in sec.get("/membros").text


def test_ficha_inativa_excluida_e_restaurada_volta_inativa():
    sec = logado("secretaria")
    mid = _ficha("Clara Souza")
    post(sec, f"/membros/{mid}/inativar", {"motivo": "Não congrega há 1 ano"}, pagina=f"/membros/{mid}")
    post(sec, f"/membros/{mid}/excluir", {"motivo": "Limpeza de cadastro", "confirmacao": str(mid)}, pagina=f"/membros/{mid}")
    post(sec, f"/membros/{mid}/restaurar", {"motivo": "Decisão revista pela liderança"}, pagina="/membros/lixeira")
    assert _status(mid)["status"] == "Inativo"
    post(sec, f"/membros/{mid}/reativar", {"motivo": "Voltou a congregar"}, pagina=f"/membros/{mid}")
    assert _status(mid)["status"] == "Ativo"


def test_exclusao_definitiva_so_adm_e_so_da_lixeira():
    sec = logado("secretaria")
    adm = logado("admin")
    mid = _ficha("Davi Rocha")
    assert sec.post(f"/membros/{mid}/excluir-definitivo", data={}, follow_redirects=False).status_code in (403, 400)
    post(adm, f"/membros/{mid}/excluir-definitivo", {"motivo": "Pedido do titular LGPD", "confirmacao": str(mid)},
         pagina="/membros/lixeira")
    assert _status(mid) is not None  # fora da lixeira não apaga
    post(sec, f"/membros/{mid}/excluir", {"motivo": "Pedido do titular LGPD", "confirmacao": str(mid)}, pagina=f"/membros/{mid}")
    post(adm, f"/membros/{mid}/excluir-definitivo", {"motivo": "Pedido do titular (art. 18)", "confirmacao": str(mid)},
         pagina="/membros/lixeira")
    assert _status(mid) is None
    with db.engine().connect() as c:
        det = c.execute(select(db.auditoria.c.detalhes).where(db.auditoria.c.acao == "EXCLUSAO_DEFINITIVA_MEMBRO")).scalar()
    assert "Davi Rocha" in det and "art. 18" in det


def test_membro_comum_nao_inativa_nem_exclui():
    mid = _ficha()
    membro = logado("membro")
    for acao in ("inativar", "excluir", "reativar", "restaurar"):
        r = membro.post(f"/membros/{mid}/{acao}", data={"motivo": "tentativa indevida"}, follow_redirects=False)
        assert r.status_code in (400, 403)
    assert membro.get("/membros/lixeira").status_code == 403
    assert _status(mid)["status"] == "Ativo"
