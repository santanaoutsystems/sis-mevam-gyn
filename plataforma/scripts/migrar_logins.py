"""
Cria os logins da plataforma a partir dos dois apps antigos.

    python migrar_logins.py --usuarios-membros backups/membros_.../usuarios.json \
                            --admins ricardo@exemplo.com [--executar]

1) Agenda (tabela 'administradores' no Supabase): as senhas estão em texto puro.
   Elas viram hash seguro (a pessoa entra com a MESMA senha) e a troca é obrigatória no primeiro acesso,
   porque essas senhas ficaram expostas.
2) App de Membros: o backup não traz senhas (o app não as expõe). Cada login recebe uma senha provisória,
   gravada em senhas_provisorias.csv para a Administração repassar. APAGUE esse arquivo depois.

Perfis: e-mails passados em --admins viram Administrador; demais líderes da Agenda viram Secretaria;
perfis do app de Membros são mantidos. Sem --executar, apenas simula.
"""
import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, select  # noqa: E402

from app import db, seguranca  # noqa: E402
from app.rotas.admin import criar_usuario  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--usuarios-membros", help="usuarios.json gerado pelo backup_membros_render.py")
    ap.add_argument("--admins", nargs="*", default=[], help="E-mails que serão Administradores")
    ap.add_argument("--executar", action="store_true")
    a = ap.parse_args()
    admins = {e.strip().lower() for e in a.admins}
    relatorio, provisorias = [], []

    with db.engine().begin() as c:
        existentes = {r[0] for r in c.execute(select(func.lower(db.usuarios.c.email)))}

        def ja_existe(email):
            return email in existentes

        # 1. Agenda
        for adm in c.execute(select(db.administradores)).mappings():
            email = (adm["email"] or "").strip().lower()
            if not email or "@" not in email:
                relatorio.append(f"Agenda · {adm['nome']}: SEM E-MAIL, não migrado (crie pelo painel)")
                continue
            if ja_existe(email):
                relatorio.append(f"Agenda · {email}: já existe, pulado")
                continue
            perfil = "admin" if email in admins else "secretaria"
            senha = adm["senha"] or None
            uid, senha_final = criar_usuario(c, adm["nome"] or email, email, perfil, senha=senha,
                                             origem=f"agenda:administradores#{adm['id']}")
            existentes.add(email)
            if not senha:
                provisorias.append((adm["nome"], email, perfil, senha_final))
            relatorio.append(f"Agenda · {email}: {perfil}, " + ("mesma senha, troca obrigatória" if senha else "senha provisória"))

        # 2. App de Membros
        if a.usuarios_membros:
            for u in json.load(open(a.usuarios_membros, encoding="utf-8")):
                email = (u.get("email") or "").strip().lower()
                if not email or ja_existe(email):
                    relatorio.append(f"Membros · {email or u.get('nome')}: já existe ou sem e-mail, pulado")
                    continue
                if email == "admin@mevamgyn.com":
                    relatorio.append("Membros · admin@mevamgyn.com: conta padrão do app antigo, NÃO migrada")
                    continue
                perfil = "admin" if email in admins else (u.get("perfil") if u.get("perfil") in db.PERFIS else "membro")
                membro = c.execute(select(db.membros.c.id).where(func.lower(db.membros.c.email) == email)).first()
                uid, senha = criar_usuario(c, u.get("nome") or email, email, perfil, membro_id=membro[0] if membro else None,
                                           origem=f"membros_app:usuarios#{u.get('id')}")
                if not u.get("ativo", 1):
                    c.execute(db.usuarios.update().where(db.usuarios.c.id == uid).values(ativo=False))
                existentes.add(email)
                provisorias.append((u.get("nome"), email, perfil, senha))
                relatorio.append(f"Membros · {email}: {perfil}, senha provisória" + (f", ligado à ficha #{membro[0]}" if membro else ""))

        if not a.executar:
            c.rollback()

    print("\n".join(relatorio) or "Nada a migrar.")
    if a.executar and provisorias:
        with open("senhas_provisorias.csv", "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["nome", "email", "perfil", "senha_provisoria"])
            w.writerows(provisorias)
        print(f"{len(provisorias)} senha(s) provisória(s) em senhas_provisorias.csv. Repasse e APAGUE o arquivo.")
    if not a.executar:
        print("Simulação concluída. Para gravar, rode de novo com --executar.")


if __name__ == "__main__":
    main()
