"""
BACKUP do app de Membros em produção (Render) — SOMENTE LEITURA.

O banco desse app é um SQLite no disco do Render, que é apagado a cada deploy.
Rode este script ANTES de qualquer push no repositório sis-mevam-gyn.

Uso (no seu computador):
    python backup_membros_render.py --url https://sis-mevam-gyn.onrender.com --email SEU_EMAIL_ADMIN

A senha é pedida na tela (não fica no histórico). Gera a pasta backups/membros_AAAA-MM-DD_HHMM/ com:
    membros.json   todas as fichas completas (inclui foto e rúbrica)
    usuarios.json  lista de logins (sem senhas, o app não as expõe)
    resumo.txt     contagens para conferência
"""
import argparse
import getpass
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://sis-mevam-gyn.onrender.com")
    ap.add_argument("--email", required=True)
    ap.add_argument("--saida", default="backups")
    ap.add_argument("--varrer-ate", type=int, default=0, help="Também tenta IDs até este número (padrão: maior ID + 50)")
    a = ap.parse_args()

    s = requests.Session()
    print("Acordando o servidor (pode levar até 1 minuto no plano gratuito)...")
    s.get(f"{a.url}/healthz", timeout=90)
    r = s.post(f"{a.url}/api/auth/login", json={"email": a.email, "senha": getpass.getpass("Senha do admin: ")}, timeout=60)
    if r.status_code != 200:
        sys.exit(f"Falha no login: {r.status_code} {r.text[:200]}")

    membros = {m["id"]: m for m in s.get(f"{a.url}/api/membros", timeout=120).json()}
    # A listagem do app antigo limita 200 por consulta: busca também por status e por ID
    for st in ("Aguardando Análise", "Validado pela Secretaria", "Ativo", "Inativo", "Anonimizado (LGPD)"):
        for m in s.get(f"{a.url}/api/membros", params={"status": st}, timeout=120).json():
            membros.setdefault(m["id"], m)
    limite = a.varrer_ate or (max(membros) + 50 if membros else 50)
    for mid in range(1, limite + 1):
        if mid in membros:
            continue
        r = s.get(f"{a.url}/api/membros/{mid}", timeout=60)
        if r.status_code == 200:
            membros[mid] = r.json()
            print(f"  ficha #{mid} encontrada fora da listagem")

    usuarios = s.get(f"{a.url}/api/usuarios", timeout=60)
    usuarios = usuarios.json() if usuarios.status_code == 200 else []

    agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
    pasta = os.path.join(a.saida, f"membros_{agora:%Y-%m-%d_%H%M}")
    os.makedirs(pasta, exist_ok=True)
    with open(os.path.join(pasta, "membros.json"), "w", encoding="utf-8") as f:
        json.dump(sorted(membros.values(), key=lambda m: m["id"]), f, ensure_ascii=False, indent=1)
    with open(os.path.join(pasta, "usuarios.json"), "w", encoding="utf-8") as f:
        json.dump(usuarios, f, ensure_ascii=False, indent=1)
    por_status = {}
    for m in membros.values():
        por_status[m.get("status")] = por_status.get(m.get("status"), 0) + 1
    resumo = (f"Backup em {agora:%d/%m/%Y %H:%M} (Goiânia)\nOrigem: {a.url}\n"
              f"Fichas: {len(membros)}\nPor status: {por_status}\nUsuários: {len(usuarios)}\n")
    open(os.path.join(pasta, "resumo.txt"), "w", encoding="utf-8").write(resumo)
    print(resumo + f"Salvo em {pasta}. Guarde esta pasta em local seguro: ela contém dados pessoais (LGPD).")


if __name__ == "__main__":
    main()
