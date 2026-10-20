import os
import re
import sys
import tempfile

import pytest

_tmp = tempfile.mkdtemp()
# Por padrão SQLite; para testar contra Postgres: TEST_DATABASE_URL=postgresql://... pytest
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_tmp}/teste.db"
os.environ["SECRET_KEY"] = "chave-de-teste-nao-usar-em-producao"
os.environ["AMBIENTE"] = "desenvolvimento"
os.environ["ENVIO_SINCRONO"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import delete, text  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from app import aniversarios, db, seguranca, uso  # noqa: E402
from app.main import app  # noqa: E402
from app.rotas.admin import criar_usuario  # noqa: E402

SENHA = "Senha1234"
CODIGO_INTEGRA = "TESTE1"


@pytest.fixture(autouse=True)
def banco_limpo():
    with db.engine().begin() as c:
        if c.dialect.name == "postgresql":
            nomes = ", ".join(t.name for t in db.metadata.sorted_tables)
            c.execute(text(f"truncate {nomes} restart identity cascade"))
        else:
            for t in reversed(db.metadata.sorted_tables):
                c.execute(delete(t))
    # Turma do INTEGRA com código válido: as fichas de teste (FICHA_OK) chegam com o INTEGRA confirmado
    from datetime import timedelta
    from app import datas
    with db.engine().begin() as c:
        c.execute(db.integra_turmas.insert().values(
            nome="Turma de teste", data_conclusao=datas.hoje() - timedelta(days=1), codigo=CODIGO_INTEGRA,
            codigo_valido_ate=datas.agora_utc() + timedelta(days=1)))
    seguranca.limpar_falhas_ip()
    aniversarios._garantido["dia"] = None
    uso._pendente.clear()
    yield


def novo_cliente() -> TestClient:
    return TestClient(app, base_url="https://testserver")


@pytest.fixture
def cliente():
    return novo_cliente()


def csrf_de(html: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    assert m, "token CSRF não encontrado na página"
    return m.group(1)


def criar(perfil: str, email: str | None = None, membro_id=None, trocar=False) -> dict:
    email = email or f"{perfil}@mevam.test"
    with db.engine().begin() as c:
        uid, _ = criar_usuario(c, f"Pessoa {perfil.title()}", email, perfil, membro_id=membro_id, senha=SENHA)
        c.execute(db.usuarios.update().where(db.usuarios.c.id == uid).values(trocar_senha=trocar))
    return {"id": uid, "email": email}


def entrar(cliente: TestClient, email: str, senha: str = SENHA):
    pagina = cliente.get("/entrar")
    return cliente.post("/entrar", data={"email": email, "senha": senha, "csrf": csrf_de(pagina.text)},
                        follow_redirects=False)


def logado(perfil: str, **kw) -> TestClient:
    c = novo_cliente()
    u = criar(perfil, **kw)
    r = entrar(c, u["email"])
    assert r.status_code == 303, r.text
    c.usuario = u
    return c


def post(cliente: TestClient, url: str, dados: dict, pagina: str = "/inicio", **kw):
    token = csrf_de(cliente.get(pagina).text)
    return cliente.post(url, data={**dados, "csrf": token}, follow_redirects=False, **kw)
