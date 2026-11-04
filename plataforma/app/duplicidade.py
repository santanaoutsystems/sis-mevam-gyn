"""Possíveis fichas duplicadas (v2.16.3).

O CPF já impede duas fichas com o mesmo número, mas muitas fichas antigas e do mutirão não têm CPF.
Aqui a mesma pessoa é reconhecida por sinais combinados:
  - mesma data de nascimento + mesmo WhatsApp;
  - mesma data de nascimento + mesmo e-mail;
  - mesma data de nascimento + nomes compatíveis ("Alessandra Nunes R Netto" ≈ "Alessandra Nunes Rosa Netto");
  - mesmo WhatsApp + nomes compatíveis (quando falta a data).
Família que divide o WhatsApp não cai: muda o nome e a data de nascimento.
"""
import re
import unicodedata

from sqlalchemy import select

from . import db, ficha

LIGACOES = {"da", "de", "do", "das", "dos", "e", "d"}
FORA = (db.ANONIMIZADO, db.EXCLUIDO)


def _tokens(nome: str) -> list[str]:
    t = unicodedata.normalize("NFD", (nome or "").replace("’", "'")).encode("ascii", "ignore").decode().lower()
    return [p for p in re.split(r"[^a-z]+", t) if p and p not in LIGACOES]


def _casa(a: str, b: str) -> bool:
    """Palavra igual, ou uma é a inicial da outra (R = Rosa)."""
    return a == b or (len(a) == 1 and b.startswith(a)) or (len(b) == 1 and a.startswith(b))


def nomes_compativeis(n1: str, n2: str) -> bool:
    """Mesmo primeiro nome, mesmo último sobrenome e o nome mais curto cabe, em ordem, no mais longo."""
    a, b = _tokens(n1), _tokens(n2)
    if len(a) < 2 or len(b) < 2 or a[0] != b[0] or not _casa(a[-1], b[-1]):
        return False
    curto, longo = (a, b) if len(a) <= len(b) else (b, a)
    i = 0
    for p in curto:
        while i < len(longo) and not _casa(p, longo[i]):
            i += 1
        if i == len(longo):
            return False
        i += 1
    return True


def motivo(m1: dict, m2: dict) -> str | None:
    """Por que as duas fichas parecem ser da mesma pessoa, ou None."""
    cpf1, cpf2 = m1.get("cpf") or "", m2.get("cpf") or ""
    if cpf1 and cpf2 and cpf1 != cpf2:
        return None  # dois CPFs válidos e diferentes: são pessoas diferentes
    nasc = m1.get("data_nascimento") and m1.get("data_nascimento") == m2.get("data_nascimento")
    z1, z2 = ficha.so_digitos(m1.get("whatsapp") or "")[-11:], ficha.so_digitos(m2.get("whatsapp") or "")[-11:]
    mesmo_zap = len(z1) >= 10 and z1 == z2
    e1, e2 = (m1.get("email") or "").strip().lower(), (m2.get("email") or "").strip().lower()
    mesmo_email = bool(e1) and e1 == e2
    nomes = nomes_compativeis(m1.get("nome_completo") or "", m2.get("nome_completo") or "")
    if nasc and nomes:
        return "nome parecido e mesma data de nascimento" + (" e WhatsApp" if mesmo_zap else "")
    if nasc and mesmo_zap and _tokens(m1.get("nome_completo"))[:1] == _tokens(m2.get("nome_completo"))[:1]:
        return "mesmo primeiro nome, data de nascimento e WhatsApp"
    if nasc and mesmo_email:
        return "mesma data de nascimento e e-mail"
    if nomes and (mesmo_zap or mesmo_email) and not (m1.get("data_nascimento") and m2.get("data_nascimento")):
        return "nome parecido e mesmo " + ("WhatsApp" if mesmo_zap else "e-mail")
    return None


COLS = ("id", "nome_completo", "data_nascimento", "whatsapp", "email", "cpf", "status")


def _todas(c) -> list[dict]:
    t = db.membros.c
    return [dict(r) for r in c.execute(select(*[getattr(t, k) for k in COLS]).where(t.status.notin_(FORA))).mappings()]


def parecidas(c, dados: dict, ignorar_id=None) -> list[dict]:
    """Fichas ativas no sistema que parecem ser da mesma pessoa de `dados`."""
    saida = []
    for m in _todas(c):
        if m["id"] == ignorar_id:
            continue
        por = motivo(dados, m)
        if por:
            saida.append({**m, "motivo": por})
    return saida


def grupos(c) -> list[list[dict]]:
    """Todos os pares suspeitos do cadastro, agrupados (para a lista de Membros)."""
    fichas = _todas(c)
    pai = {m["id"]: m["id"] for m in fichas}

    def raiz(x):
        while pai[x] != x:
            pai[x] = pai[pai[x]]
            x = pai[x]
        return x
    # só compara quem divide data de nascimento, WhatsApp ou e-mail (evita n²)
    baldes: dict = {}
    for m in fichas:
        for k in (("n", m["data_nascimento"]), ("z", ficha.so_digitos(m["whatsapp"] or "")[-11:]),
                  ("e", (m["email"] or "").lower())):
            if k[1]:
                baldes.setdefault(k, []).append(m)
    vistos = set()
    for lista in baldes.values():
        for i, a in enumerate(lista):
            for b in lista[i + 1:]:
                par = (min(a["id"], b["id"]), max(a["id"], b["id"]))
                if par in vistos:
                    continue
                vistos.add(par)
                if motivo(a, b):
                    pai[raiz(a["id"])] = raiz(b["id"])
    por_raiz: dict = {}
    for m in fichas:
        por_raiz.setdefault(raiz(m["id"]), []).append(m)
    return sorted([sorted(g, key=lambda m: m["id"]) for g in por_raiz.values() if len(g) > 1], key=lambda g: g[0]["id"])


def ids_suspeitos(c) -> set[int]:
    return {m["id"] for g in grupos(c) for m in g}
