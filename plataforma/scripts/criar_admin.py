"""Cria o primeiro Administrador da plataforma (pergunta os dados na tela; a senha não aparece)."""
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, select  # noqa: E402

from app import db, seguranca  # noqa: E402
from app.rotas.admin import criar_usuario  # noqa: E402

nome = input("Nome completo: ").strip()
email = input("E-mail: ").strip().lower()
senha = getpass.getpass("Senha: ")
if senha != getpass.getpass("Confirme a senha: "):
    sys.exit("As senhas não conferem.")
erro = seguranca.validar_forca_senha(senha)
if erro:
    sys.exit(erro)
with db.engine().begin() as c:
    if c.execute(select(db.usuarios.c.id).where(func.lower(db.usuarios.c.email) == email)).first():
        sys.exit("Já existe um usuário com esse e-mail.")
    uid, _ = criar_usuario(c, nome, email, "admin", senha=senha)
    c.execute(db.usuarios.update().where(db.usuarios.c.id == uid).values(trocar_senha=False))
print(f"Administrador criado: {email}")
