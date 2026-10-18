from app import config, envios, uso
from conftest import logado


def test_contadores_gravam_e_somam():
    uso.contar("email_google", 3)
    assert uso.hoje("email_google") == 3  # ainda na memória
    uso.gravar()
    uso.contar("email_google", 2)
    uso.gravar()
    assert uso.hoje("email_google") == 5


def test_banda_medida_pelas_respostas(cliente):
    uso.gravar()
    antes = uso.hoje("banda_bytes")
    r = cliente.get("/entrar")
    assert r.status_code == 200
    assert antes + 300 < uso.hoje("banda_bytes") < antes + len(r.content) + 300  # mede o que sai comprimido


def test_painel_do_adm():
    r = logado("admin").get("/admin/servicos")
    assert r.status_code == 200
    assert "Supabase · tamanho do banco" in r.text and "Render · banda de saída no mês" in r.text


def test_painel_restrito_ao_adm():
    assert logado("secretaria").get("/admin/servicos", follow_redirects=False).status_code in (302, 303, 403)


def test_google_no_limite_passa_para_o_brevo(monkeypatch):
    canais = []
    monkeypatch.setattr(envios, "email_configurado", lambda: True)
    monkeypatch.setattr(envios, "_google_ok", lambda: True)
    monkeypatch.setattr(envios, "_brevo_ok", lambda: True)
    monkeypatch.setattr(envios, "_email_google", lambda *a: canais.append("google"))
    monkeypatch.setattr(envios, "_email_brevo", lambda *a: canais.append("brevo"))
    monkeypatch.setattr(config, "LIMITE_EMAIL_GOOGLE_DIA", 2)
    for _ in range(3):
        assert envios.enviar_email("a@b.com", "x", "y") is None
    assert canais == ["google", "google", "brevo"]
