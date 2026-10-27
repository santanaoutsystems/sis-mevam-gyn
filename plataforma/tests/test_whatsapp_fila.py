"""v2.16.0: fila do WhatsApp da Secretaria (sem WhatsApp Business): cota, intervalo, horário e 2 tempos."""
from datetime import timedelta
from urllib.parse import unquote

import pytest
from sqlalchemy import insert, select, update

from app import config, datas, db
from app import whatsapp_fila as zap
from conftest import logado, post
from test_mutirao import _criar_lote, _fichas, _lancar, _voluntaria
from test_plataforma import gerar_cpf


@pytest.fixture(autouse=True)
def _livre(monkeypatch):
    """Sem horário nem intervalo, para os testes que não tratam disso."""
    monkeypatch.setattr(zap, "HORA_INICIO", 0)
    monkeypatch.setattr(zap, "HORA_FIM", 24)
    monkeypatch.setattr(zap, "INTERVALO_NOVO", 0)
    monkeypatch.setattr(zap, "INTERVALO_RESPOSTA", 0)
    monkeypatch.setattr(config, "WHATSAPP_LIMITE_DIARIO", 0)


def _lote_com(*fichas):
    sec, lt = _criar_lote()
    cli = _voluntaria(lt["codigo"])
    for kw in fichas:
        assert _lancar(cli, lt["codigo"], **kw).status_code == 303
    return sec, lt, sorted(_fichas(lt["id"]), key=lambda m: m["id"])


def _zap(sec, lt, mid, acao):
    return post(sec, f"/mutirao/lotes/{lt['id']}/zap/{mid}", {"acao": acao}, pagina=f"/mutirao/lotes/{lt['id']}")


def _texto(r):
    assert r.status_code == 303 and r.headers["location"].startswith("https://wa.me/55"), r.headers["location"]
    return unquote(r.headers["location"].split("?text=", 1)[1])


def _envios(mid):
    with db.engine().connect() as c:
        return [dict(r) for r in c.execute(select(db.whatsapp_envios).where(
            db.whatsapp_envios.c.membro_id == mid).order_by(db.whatsapp_envios.c.id)).mappings()]


def test_complemento_em_2_tempos_convite_sem_link_e_link_para_quem_respondeu():
    sec, lt, [m] = _lote_com({"whatsapp": "62999990001"})
    html = sec.get(f"/mutirao/lotes/{lt['id']}").text
    assert "Fila do WhatsApp (1 para enviar)" in html and "Hoje: 0 de 15 contatos novos" in html
    assert "Responda SIM" in html or "responder SIM" in html
    convite = _texto(_zap(sec, lt, m["id"], "enviar"))
    assert convite.startswith("Paz, Joana!") and "SAIR" in convite and "http" not in convite
    [e] = _envios(m["id"])
    assert e["etapa"] == "convite" and e["conta_cota"] and e["tipo"] == "complemento"
    # Clicar de novo não manda outro convite
    r = _zap(sec, lt, m["id"], "enviar")
    assert r.headers["location"].endswith("#fila") and len(_envios(m["id"])) == 1
    html = sec.get(f"/mutirao/lotes/{lt['id']}").text
    assert "Aguardando resposta (1)" in html and "Hoje: 1 de 15 contatos novos" in html
    link = _texto(_zap(sec, lt, m["id"], "respondeu"))
    assert "/atualizar/" in link and "Paz, Joana!" in link
    e = _envios(m["id"])[-1]
    assert e["etapa"] == "link" and not e["conta_cota"]
    with db.engine().connect() as c:
        reg = c.execute(select(db.regularizacoes).where(db.regularizacoes.c.membro_id == m["id"])).mappings().one()
        assert reg["enviado_em"] and "whatsapp" in reg["canais"]
        assert c.execute(select(db.membros.c.whatsapp_situacao).where(db.membros.c.id == m["id"])).scalar() == "respondeu"
        acoes = [a for (a,) in c.execute(select(db.auditoria.c.acao).where(db.auditoria.c.acao.like("WHATSAPP_%")))]
    assert acoes == ["WHATSAPP_CONVITE", "WHATSAPP_LINK"]
    assert "Link enviado (1)" in sec.get(f"/mutirao/lotes/{lt['id']}").text
    # Reenviar usa o mesmo link válido
    assert _texto(_zap(sec, lt, m["id"], "link_de_novo")) == link


def test_cota_diaria_intervalo_e_horario(monkeypatch):
    sec, lt, fichas = _lote_com({"whatsapp": "62999990001"}, {"whatsapp": "62999990002", "nome_completo": "Ana Lima"},
                                {"whatsapp": "62999990003", "nome_completo": "Rute Alves"})
    monkeypatch.setattr(config, "WHATSAPP_LIMITE_DIARIO", 1)
    _texto(_zap(sec, lt, fichas[0]["id"], "enviar"))
    r = _zap(sec, lt, fichas[1]["id"], "enviar")
    assert r.headers["location"].endswith("#fila") and not _envios(fichas[1]["id"])
    assert "Cota de hoje atingida (1 contatos novos)" in sec.get(f"/mutirao/lotes/{lt['id']}").text
    # Quem já respondeu não gasta a cota de contatos novos
    _texto(_zap(sec, lt, fichas[0]["id"], "respondeu"))
    monkeypatch.setattr(config, "WHATSAPP_LIMITE_DIARIO", 5)
    monkeypatch.setattr(zap, "INTERVALO_NOVO", 60)
    r = _zap(sec, lt, fichas[1]["id"], "enviar")
    assert not _envios(fichas[1]["id"])
    assert "Aguarde" in sec.get(f"/mutirao/lotes/{lt['id']}").text
    monkeypatch.setattr(zap, "INTERVALO_NOVO", 0)
    monkeypatch.setattr(zap, "HORA_INICIO", 25)
    _zap(sec, lt, fichas[1]["id"], "enviar")
    assert not _envios(fichas[1]["id"])
    assert "Envios só entre" in sec.get(f"/mutirao/lotes/{lt['id']}").text


def test_aquecimento_do_numero():
    with db.engine().begin() as c:
        assert zap.cota_hoje(c) == 15
        c.execute(insert(db.whatsapp_envios).values(membro_id=1, tipo="credo", etapa="convite", conta_cota=True,
                                                    enviado_em=datas.agora_utc() - timedelta(days=9)))
        assert zap.cota_hoje(c) == 25
        c.execute(insert(db.whatsapp_envios).values(membro_id=1, tipo="credo", etapa="convite", conta_cota=True,
                                                    enviado_em=datas.agora_utc() - timedelta(days=30)))
        assert zap.cota_hoje(c) == zap.COTA_PLENA


def test_sair_numero_invalido_e_voltar_para_a_fila():
    sec, lt, fichas = _lote_com({"whatsapp": "62999990001"}, {"whatsapp": "62999990002", "nome_completo": "Ana Lima"})
    _zap(sec, lt, fichas[1]["id"], "invalido")
    html = sec.get(f"/mutirao/lotes/{lt['id']}").text
    assert "Fila do WhatsApp (1 para enviar)" in html and "número inválido: corrija na ficha" in html
    _texto(_zap(sec, lt, fichas[0]["id"], "enviar"))
    _zap(sec, lt, fichas[0]["id"], "nao_quer")
    html = sec.get(f"/mutirao/lotes/{lt['id']}").text
    assert "pediu para não receber" in html and "Aguardando resposta (0)" in html
    assert _zap(sec, lt, fichas[0]["id"], "respondeu").headers["location"].endswith("#fila")
    assert len(_envios(fichas[0]["id"])) == 1
    _zap(sec, lt, fichas[0]["id"], "reabrir")
    assert "Aguardando resposta (1)" in sec.get(f"/mutirao/lotes/{lt['id']}").text


def test_um_lembrete_so_depois_de_alguns_dias():
    sec, lt, [m] = _lote_com({"whatsapp": "62999990001"})
    _texto(_zap(sec, lt, m["id"], "enviar"))
    antes = datas.agora_utc() - timedelta(days=zap.DIAS_PARA_LEMBRETE + 1)
    with db.engine().begin() as c:
        c.execute(update(db.whatsapp_envios).where(db.whatsapp_envios.c.membro_id == m["id"]).values(enviado_em=antes))
    assert "· lembrete" in sec.get(f"/mutirao/lotes/{lt['id']}").text
    assert "Passando de novo" in _texto(_zap(sec, lt, m["id"], "enviar"))
    with db.engine().begin() as c:
        c.execute(update(db.whatsapp_envios).where(db.whatsapp_envios.c.membro_id == m["id"]).values(enviado_em=antes))
    html = sec.get(f"/mutirao/lotes/{lt['id']}").text
    assert "Sem resposta depois do lembrete (1)" in html and "Fila do WhatsApp (0 para enviar)" in html
    assert _zap(sec, lt, m["id"], "enviar").headers["location"].endswith("#fila")


def test_modo_direto_e_credo_de_ficha_validada():
    sec, lt, [m] = _lote_com({"whatsapp": "62999990001", "cpf": gerar_cpf(555444333)})
    assert m["status"] == "Validado pela Secretaria"
    post(sec, f"/mutirao/lotes/{lt['id']}/zap-modo", {"modo": "direto"}, pagina=f"/mutirao/lotes/{lt['id']}")
    texto = _texto(_zap(sec, lt, m["id"], "enviar"))
    assert "Confissão de Fé" in texto and "/credo/" in texto and "responda SAIR" in texto
    [e] = _envios(m["id"])
    assert e["etapa"] == "link" and e["conta_cota"] and e["tipo"] == "credo"
    assert _fichas(lt["id"])[0]["link_credo_enviado"]


def test_so_secretaria_e_adm_usam_a_fila():
    sec, lt, [m] = _lote_com({"whatsapp": "62999990001"})
    for perfil in ("membro", "coordenacao"):
        cli = logado(perfil)
        r = post(cli, f"/mutirao/lotes/{lt['id']}/zap/{m['id']}", {"acao": "enviar"}, pagina="/inicio")
        assert r.status_code == 403
    assert not _envios(m["id"])
