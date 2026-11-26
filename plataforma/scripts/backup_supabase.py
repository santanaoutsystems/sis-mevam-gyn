"""
BACKUP do banco Supabase (Agenda e, após a migração, a plataforma inteira) — SOMENTE LEITURA.

Uso:
    set DATABASE_URL=postgresql://...   (Windows)   |   export DATABASE_URL=...   (Linux/Mac)
    python backup_supabase.py

Pega a string em: Supabase > Project Settings > Database > Connection string (Session pooler).
Gera backups/supabase_AAAA-MM-DD_HHMM/ com um JSON por tabela, um CSV por tabela e resumo.txt.
Também é usado pela rotina diária de backup (GitHub Actions).
"""
import csv
import json
import os
import sys
from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import psycopg


def serial(v):
    if isinstance(v, (datetime, date, time)):
        return v.isoformat()
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, Decimal):
        return float(v)
    return v


def main():
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("Defina DATABASE_URL.")
    agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
    pasta = os.path.join(os.environ.get("BACKUP_DIR", "backups"), f"supabase_{agora:%Y-%m-%d_%H%M}")
    os.makedirs(pasta, exist_ok=True)
    linhas_resumo = [f"Backup em {agora:%d/%m/%Y %H:%M} (Goiânia)"]
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("SET default_transaction_read_only = on")
        tabelas = [r[0] for r in conn.execute(
            "select table_name from information_schema.tables where table_schema='public' and table_type='BASE TABLE' order by 1")]
        colunas_info = {}
        for t in tabelas:
            cur = conn.execute(f'select * from public."{t}"')
            nomes = [d.name for d in cur.description]
            registros = [dict(zip(nomes, map(serial, r))) for r in cur.fetchall()]
            with open(os.path.join(pasta, f"{t}.json"), "w", encoding="utf-8") as f:
                json.dump(registros, f, ensure_ascii=False, indent=1, default=str)
            with open(os.path.join(pasta, f"{t}.csv"), "w", encoding="utf-8-sig", newline="") as f:
                w = csv.DictWriter(f, fieldnames=nomes, delimiter=";")
                w.writeheader()
                w.writerows(registros)
            colunas_info[t] = [dict(zip(("coluna", "tipo", "nulo"), r)) for r in conn.execute(
                "select column_name, data_type, is_nullable from information_schema.columns "
                "where table_schema='public' and table_name=%s order by ordinal_position", (t,))]
            linhas_resumo.append(f"{t}: {len(registros)} registros")
        with open(os.path.join(pasta, "estrutura.json"), "w", encoding="utf-8") as f:
            json.dump(colunas_info, f, ensure_ascii=False, indent=1)
    open(os.path.join(pasta, "resumo.txt"), "w", encoding="utf-8").write("\n".join(linhas_resumo) + "\n")
    print("\n".join(linhas_resumo))
    print(f"Salvo em {pasta}. Contém dados pessoais: guarde em local seguro (LGPD).")


if __name__ == "__main__":
    main()
