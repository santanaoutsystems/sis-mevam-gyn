"""
Migra as fichas do backup do app de Membros (SQLite/Render) para o banco único (Supabase).

    python migrar_membros.py backups/membros_AAAA-MM-DD_HHMM/membros.json            # simulação (não grava)
    python migrar_membros.py backups/membros_AAAA-MM-DD_HHMM/membros.json --executar # grava

- Mantém o MESMO número de protocolo (id) de cada ficha.
- Pode rodar de novo: fichas já migradas (mesma origem) são puladas, nada é duplicado.
- Nada é apagado: o arquivo de backup e o app antigo continuam intactos.
- Ao final confere a contagem e lista qualquer ficha com dado que precisou de ajuste.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, insert, select, text  # noqa: E402

from app import datas, db, ficha  # noqa: E402

SEXO = {"Masc.": "Masculino", "Fem.": "Feminino", "M": "Masculino", "F": "Feminino"}


def ts_legado(valor):
    """O app antigo gravava 'dd/mm/aaaa HH:MM:SS' no relógio do servidor (UTC no Render)."""
    if not valor:
        return None
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(valor)[:19], fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    d = datas.parse_data(valor)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc) if d else None


def converter(m: dict) -> tuple[dict, list[str]]:
    avisos, obs = [], [m.get("observacoes") or ""]
    nasc = datas.parse_data(m.get("data_nascimento"))
    if m.get("data_nascimento") and not nasc:
        avisos.append(f"data de nascimento '{m['data_nascimento']}' ilegível")
        obs.append(f"[Migração] Data de nascimento informada: {m['data_nascimento']}")
    bat = datas.parse_data(m.get("data_batismo"))
    if m.get("data_batismo") and not bat and m.get("batizado") == "Sim":
        avisos.append(f"data de batismo '{m['data_batismo']}' não é data")
        obs.append(f"[Migração] Data de batismo informada: {m['data_batismo']}")
    filhos = []
    for f in m.get("filhos") or []:
        if f.get("nome"):
            dn = datas.parse_data(f.get("data_nascimento") or f.get("nascimento"))
            filhos.append({"nome": f["nome"], "data_nascimento": datas.fmt_data(dn) if dn else ""})
    assinatura = m.get("assinatura_rubrica") or None
    dados = {
        "id": int(m["id"]),
        "data_registro": datas.parse_data(m.get("data_registro")) or (ts_legado(m.get("created_at")) or datetime.now(timezone.utc)).date(),
        "nome_completo": (m.get("nome_completo") or "").strip() or f"Sem nome #{m['id']}",
        "endereco": m.get("endereco"), "bairro": m.get("bairro"), "cidade": m.get("cidade"),
        "cep": ficha.fmt_cep(m.get("cep") or "") or None,
        "data_nascimento": nasc, "naturalidade": m.get("naturalidade"),
        "sexo": SEXO.get(m.get("sexo"), m.get("sexo")), "estado_civil": m.get("estado_civil"),
        "conjuge": m.get("conjuge"), "filhos": filhos,
        "email": (m.get("email") or "").strip().lower() or None,
        "telefone": ficha.fmt_telefone(m.get("telefone") or "") or None,
        "whatsapp": ficha.fmt_telefone(m.get("whatsapp") or "") or None,
        "escolaridade": m.get("escolaridade"), "formacao_academica": m.get("formacao_academica"),
        "profissao": m.get("profissao"), "empresa": m.get("empresa"),
        "batizado": m.get("batizado"), "data_batismo": bat,
        "congregava_antes": m.get("congregava_antes"), "onde_congregava": m.get("onde_congregava"),
        "area_ministerial": m.get("area_ministerial"), "interesse_batismo_familia": m.get("interesse_batismo_familia"),
        # O app antigo marcava credo_aceito=1 por padrão; só conta como aceito se houver rúbrica
        "credo_aceito": bool(assinatura) and bool(m.get("credo_aceito", 1)),
        "nome_assinante": m.get("nome_assinante") if assinatura else None,
        "assinatura_rubrica": assinatura,
        "data_assinatura": ts_legado(m.get("data_assinatura")) if assinatura else None,
        "hash_autenticidade": m.get("hash_autenticidade") if assinatura else None,
        "ocr_documento_nome": m.get("ocr_documento_nome"),
        "foto_3x4": m.get("foto_3x4") or None,
        "lgpd_consentimento": bool(m.get("lgpd_consentimento", 1)),
        "lgpd_versao_termo": m.get("lgpd_versao_termo") or "v1.0-2026",
        "lgpd_data_consentimento": ts_legado(m.get("lgpd_data_consentimento")),
        "lgpd_ip_origem": m.get("lgpd_ip_origem"),
        "status_lgpd": m.get("status_lgpd") or "Consentimento Ativo",
        "status": m.get("status") or "Aguardando Análise",
        "validado_por": m.get("validado_por"),
        "data_validacao": ts_legado(m.get("data_validacao")),
        "link_credo_enviado": bool(m.get("link_credo_enviado")),
        "observacoes": "\n".join(o for o in obs if o) or None,
        "origem": f"membros_app:membros#{m['id']}",
        "criado_em": ts_legado(m.get("created_at")) or datetime.now(timezone.utc),
        "atualizado_em": datetime.now(timezone.utc),
    }
    if not m.get("nome_completo"):
        avisos.append("sem nome")
    return dados, avisos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("arquivo")
    ap.add_argument("--executar", action="store_true", help="Grava de fato. Sem isso, só simula.")
    a = ap.parse_args()
    origem = json.load(open(a.arquivo, encoding="utf-8"))
    print(f"{len(origem)} fichas no backup. Banco de destino: {db.engine().url.render_as_string(hide_password=True)}")

    novos, pulados, com_aviso = 0, 0, []
    with db.engine().begin() as c:
        ja = {r[0] for r in c.execute(select(db.membros.c.origem).where(db.membros.c.origem.like("membros_app:%")))}
        ids_ocupados = {r[0] for r in c.execute(select(db.membros.c.id))}
        for m in origem:
            dados, avisos = converter(m)
            if dados["origem"] in ja:
                pulados += 1
                continue
            if dados["id"] in ids_ocupados:
                avisos.append(f"protocolo #{dados['id']} já usado por outra ficha: recebeu um número novo")
                dados.pop("id")
            if avisos:
                com_aviso.append((m["id"], dados["nome_completo"], avisos))
            if a.executar:
                c.execute(insert(db.membros).values(**dados))
            novos += 1
        if a.executar and c.dialect.name == "postgresql":
            c.execute(text("select setval(pg_get_serial_sequence('public.membros','id'), "
                           "greatest((select max(id) from public.membros), 1))"))
        total = c.execute(select(func.count()).select_from(db.membros)
                          .where(db.membros.c.origem.like("membros_app:%"))).scalar()
        if not a.executar:
            c.rollback()

    print(f"{'Gravadas' if a.executar else 'Seriam gravadas'}: {novos} · já existentes (puladas): {pulados}")
    if a.executar:
        esperado = len(origem)
        print(f"Conferência: {total} fichas migradas no destino de {esperado} no backup "
              f"→ {'OK' if total == esperado else 'ATENÇÃO, diferença'}")
    for mid, nome, avisos in com_aviso:
        print(f"  #{mid} {nome}: " + "; ".join(avisos))
    if not a.executar:
        print("Simulação concluída. Para gravar, rode de novo com --executar.")


if __name__ == "__main__":
    main()
