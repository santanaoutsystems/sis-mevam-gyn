"""
Tabelas com filtro e ordenação pelos cabeçalhos (lista de Membros e Central de Relatórios).

Cada coluna tem um tipo de dado, e o menu do cabeçalho oferece o filtro desse tipo:
    texto        "contém"
    lista        caixas de seleção com a quantidade de cada valor (aceita célula com vários valores)
    data         de / até (dd/mm/aaaa)
    aniversario  mês do aniversário, sem mostrar o ano
    simnao       Sim / Não
    numero/moeda de / até

Tudo fica no endereço da página (f.<coluna>..., ordem=col:asc,col2:desc, cols=a,b), então o mesmo
relatório pode ser salvo, impresso ou exportado com os mesmos filtros. Os filtros são aplicados no
servidor sobre linhas que já respeitam o limite do perfil: o menu nunca mostra valores de fora dele.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable
from urllib.parse import urlencode

from . import datas

VAZIO = "__vazio__"
MESES = datas.MESES
LIMITE_TELA = 300
LIMITE_OPCOES = 80


@dataclass
class Coluna:
    chave: str
    rotulo: str
    tipo: str = "texto"            # texto | lista | data | aniversario | simnao | numero | moeda
    padrao: bool = True            # aparece sem o usuário escolher
    filtravel: bool = True
    ordenavel: bool = True
    sensivel: bool = False         # dado pessoal sensível: nunca vira filtro de lista
    link: Callable[[dict], str] | None = None
    fmt: Callable[[Any], str] | None = None
    destaque: bool = False         # texto em negrito (ex.: nome)


def local(v) -> datetime | None:
    """Timestamp de sistema (UTC, com ou sem fuso) → horário de Goiânia sem fuso, como os eventos."""
    if not isinstance(v, datetime):
        return v
    if v.tzinfo is None:
        from datetime import timezone
        v = v.replace(tzinfo=timezone.utc)
    return v.astimezone(datas.TZ).replace(tzinfo=None)


def _norm(v) -> str:
    s = unicodedata.normalize("NFKD", str(v or "")).encode("ascii", "ignore").decode()
    return s.lower().strip()


def _num(v) -> float | None:
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(".", "").replace(",", ".")) if "," in str(v) else float(v)
    except ValueError:
        return None


def _como_data(v) -> date | None:
    if isinstance(v, datetime):
        return datas.parse_data_hora_local(v).date()
    if isinstance(v, date):
        return v
    return datas.parse_data(v) if v else None


def _valores(v) -> list[str]:
    """Valores de uma célula de lista (pode ter vários, ex.: setores)."""
    if isinstance(v, (list, tuple, set)):
        return [str(x) for x in v if x not in (None, "")] or [VAZIO]
    return [str(v)] if v not in (None, "") else [VAZIO]


def exibir(col: Coluna, v) -> str:
    if col.fmt:
        return col.fmt(v)
    if v is None or v == "" or v == []:
        return "-"
    if col.tipo == "simnao":
        return "Sim" if v else "Não"
    if col.tipo in ("data", "aniversario"):
        if isinstance(v, datetime):  # as linhas já chegam no horário de Goiânia (ver local())
            return datas.parse_data_hora_local(v).strftime("%d/%m/%Y %H:%M")
        return datas.fmt_data(v)
    if col.tipo == "moeda":
        return ("R$ {:,.2f}".format(float(v or 0))).replace(",", "X").replace(".", ",").replace("X", ".")
    if col.tipo == "numero":
        n = float(v)
        return str(int(n)) if n.is_integer() else f"{n:.1f}".replace(".", ",")
    if isinstance(v, (list, tuple, set)):
        return ", ".join(str(x) for x in v) or "-"
    return str(v)


# ---------------------------------------------------------------------------
# Estado (lido do endereço)
# ---------------------------------------------------------------------------
def _pares(params) -> list[tuple[str, str]]:
    return list(params.multi_items()) if hasattr(params, "multi_items") else list(params.items())


def _chaves_da_coluna(chave: str) -> set[str]:
    return {f"f.{chave}", f"f.{chave}.de", f"f.{chave}.ate", f"f.{chave}.mes"}


def ler_estado(params, colunas: list[Coluna]) -> dict:
    pares = _pares(params)
    por = {}
    for k, v in pares:
        por.setdefault(k, []).append(v)
    cols = {c.chave: c for c in colunas}
    filtros: dict[str, dict] = {}
    for c in colunas:
        if not c.filtravel:
            continue
        f = {}
        if c.tipo == "lista":
            vals = [v for v in por.get(f"f.{c.chave}", []) if v != ""]
            if vals:
                f["em"] = vals
        elif c.tipo in ("texto",):
            t = (por.get(f"f.{c.chave}", [""])[0] or "").strip()
            if t:
                f["contem"] = t
        elif c.tipo == "simnao":
            t = por.get(f"f.{c.chave}", [""])[0]
            if t in ("sim", "nao"):
                f["sim"] = t
        elif c.tipo == "aniversario":
            m = por.get(f"f.{c.chave}.mes", [""])[0]
            if m.isdigit() and 1 <= int(m) <= 12:
                f["mes"] = int(m)
        if c.tipo in ("data", "aniversario"):
            de = datas.parse_data(por.get(f"f.{c.chave}.de", [""])[0])
            ate = datas.parse_data(por.get(f"f.{c.chave}.ate", [""])[0])
            if de:
                f["de"] = de
            if ate:
                f["ate"] = ate
        if c.tipo in ("numero", "moeda"):
            de, ate = _num(por.get(f"f.{c.chave}.de", [""])[0]), _num(por.get(f"f.{c.chave}.ate", [""])[0])
            if de is not None:
                f["de"] = de
            if ate is not None:
                f["ate"] = ate
        if f:
            filtros[c.chave] = f
    ordem = []
    for item in (por.get("ordem", [""])[0] or "").split(","):
        chave, _, direcao = item.partition(":")
        if chave in cols and cols[chave].ordenavel and chave not in [o[0] for o in ordem]:
            ordem.append((chave, "desc" if direcao == "desc" else "asc"))
    escolhidas = list(dict.fromkeys(k for v in por.get("cols", []) for k in v.split(",") if k in cols))
    visiveis = escolhidas or [c.chave for c in colunas if c.padrao]
    return {"pares": pares, "filtros": filtros, "ordem": ordem[:4], "visiveis": visiveis,
            "cols_escolhidas": bool(escolhidas)}


# ---------------------------------------------------------------------------
# Aplicação
# ---------------------------------------------------------------------------
def _passa(col: Coluna, f: dict, v) -> bool:
    if "em" in f:
        alvo = set(f["em"])
        return any(x in alvo for x in _valores(v))
    if "contem" in f:
        return _norm(f["contem"]) in _norm(exibir(col, v) if v not in (None, "") else "")
    if "sim" in f:
        return bool(v) == (f["sim"] == "sim")
    if col.tipo in ("data", "aniversario"):
        d = _como_data(v)
        if "mes" in f and (not d or d.month != f["mes"]):
            return False
        if "de" in f and (not d or d < f["de"]):
            return False
        if "ate" in f and (not d or d > f["ate"]):
            return False
        return True
    if col.tipo in ("numero", "moeda"):
        n = _num(v)
        if "de" in f and (n is None or n < f["de"]):
            return False
        if "ate" in f and (n is None or n > f["ate"]):
            return False
    return True


def _chave_ordem(col: Coluna, v):
    if v is None or v == "" or v == []:
        return (1, 0)
    if col.tipo == "aniversario":
        d = _como_data(v)
        return (0, (d.month, d.day) if d else (13, 0))
    if col.tipo == "data":
        d = datas.parse_data_hora_local(v) if isinstance(v, datetime) else _como_data(v)
        if isinstance(d, datetime):
            pass
        elif isinstance(d, date):
            d = datetime(d.year, d.month, d.day)
        return (0, d)
    if col.tipo in ("numero", "moeda"):
        return (0, _num(v) or 0)
    if col.tipo == "simnao":
        return (0, 0 if v else 1)
    if isinstance(v, (list, tuple)):
        v = ", ".join(map(str, v))
    return (0, _norm(v))


def aplicar(linhas: list[dict], colunas: list[Coluna], estado: dict) -> dict:
    cols = {c.chave: c for c in colunas}
    filtros = estado["filtros"]

    def passa_todos(l, exceto=None):
        return all(_passa(cols[k], f, l.get(k)) for k, f in filtros.items() if k != exceto)

    resultado = [l for l in linhas if passa_todos(l)]
    # Ordem: do último nível para o primeiro (sort estável); vazios sempre no fim
    for chave, direcao in reversed(estado["ordem"]):
        col = cols[chave]
        cheios = [l for l in resultado if _chave_ordem(col, l.get(chave))[0] == 0]
        vazios = [l for l in resultado if _chave_ordem(col, l.get(chave))[0] == 1]
        cheios.sort(key=lambda l: _chave_ordem(col, l.get(chave))[1], reverse=(direcao == "desc"))
        resultado = cheios + vazios
    # Valores (com quantidade) de cada coluna de lista, considerando os demais filtros
    opcoes = {}
    for c in colunas:
        if c.tipo == "lista" and c.filtravel and not c.sensivel:
            cont: dict[str, int] = {}
            for l in linhas:
                if passa_todos(l, exceto=c.chave):
                    for x in _valores(l.get(c.chave)):
                        cont[x] = cont.get(x, 0) + 1
            ordenadas = sorted(cont.items(), key=lambda kv: (kv[0] == VAZIO, _norm(kv[0])))
            opcoes[c.chave] = ordenadas[:LIMITE_OPCOES]
    return {"linhas": resultado, "opcoes": opcoes}


# ---------------------------------------------------------------------------
# Montagem para o template
# ---------------------------------------------------------------------------
def _url(caminho: str, pares: list[tuple[str, str]]) -> str:
    q = urlencode([(k, v) for k, v in pares if v not in (None, "")])
    return caminho + ("?" + q if q else "")


def _sem(pares, chaves: set[str]):
    return [(k, v) for k, v in pares if k not in chaves]


def _texto_ordem(ordem) -> str:
    return ",".join(f"{k}:{d}" for k, d in ordem)


def _resumo_filtro(col: Coluna, f: dict) -> str:
    if "em" in f:
        return ", ".join("(em branco)" if v == VAZIO else v for v in f["em"])
    if "contem" in f:
        return f"contém \"{f['contem']}\""
    if "sim" in f:
        return "Sim" if f["sim"] == "sim" else "Não"
    partes = []
    if "mes" in f:
        partes.append(f"aniversário em {MESES[f['mes'] - 1]}")
    if "de" in f:
        partes.append("de " + (datas.fmt_data(f["de"]) if isinstance(f["de"], date) else exibir(col, f["de"])))
    if "ate" in f:
        partes.append("até " + (datas.fmt_data(f["ate"]) if isinstance(f["ate"], date) else exibir(col, f["ate"])))
    return " ".join(partes)


def texto_filtros(colunas: list[Coluna], estado: dict) -> list[str]:
    cols = {c.chave: c for c in colunas}
    itens = [f"{cols[k].rotulo}: {_resumo_filtro(cols[k], f)}" for k, f in estado["filtros"].items()]
    if estado["ordem"]:
        itens.append("Ordem: " + ", ".join(f"{i}º {cols[k].rotulo} {'A→Z' if d == 'asc' else 'Z→A'}"
                                             for i, (k, d) in enumerate(estado["ordem"], 1)))
    return itens


def montar(caminho: str, linhas: list[dict], colunas: list[Coluna], estado: dict,
           tudo: bool = False) -> dict:
    """Aplica filtros/ordem e devolve o que o template parciais/tabela.html precisa."""
    r = aplicar(linhas, colunas, estado)
    pares = [(k, v) for k, v in estado["pares"] if k not in ("tudo", "imprimir", "formato")]
    cols = {c.chave: c for c in colunas}
    ordem = estado["ordem"]
    visiveis = [cols[k] for k in estado["visiveis"]]

    menus = []
    for col in visiveis:
        base = _sem(pares, {"ordem"})
        nivel = next((i for i, (k, _) in enumerate(ordem, 1) if k == col.chave), None)
        direcao = next((d for k, d in ordem if k == col.chave), None)
        resto = [(k, d) for k, d in ordem if k != col.chave]
        m = {"col": col, "nivel": nivel, "direcao": direcao, "filtro": estado["filtros"].get(col.chave),
             "opcoes": r["opcoes"].get(col.chave, []), "ocultos": _sem(pares, _chaves_da_coluna(col.chave)),
             "limpar": _url(caminho, _sem(pares, _chaves_da_coluna(col.chave)))}
        if col.ordenavel:
            m["asc"] = _url(caminho, base + [("ordem", _texto_ordem([(col.chave, "asc")]))])
            m["desc"] = _url(caminho, base + [("ordem", _texto_ordem([(col.chave, "desc")]))])
            if ordem and not nivel:
                m["tambem"] = _url(caminho, base + [("ordem", _texto_ordem(ordem + [(col.chave, "asc")]))])
            if nivel:
                m["sem_ordem"] = _url(caminho, base + [("ordem", _texto_ordem(resto))] if resto else base)
        menus.append(m)

    chips = []
    for k, f in estado["filtros"].items():
        chips.append({"texto": f"{cols[k].rotulo}: {_resumo_filtro(cols[k], f)}",
                      "remover": _url(caminho, _sem(pares, _chaves_da_coluna(k))), "tipo": "filtro"})
    for i, (k, d) in enumerate(ordem, 1):
        resto = [(kk, dd) for kk, dd in ordem if kk != k]
        base = _sem(pares, {"ordem"})
        chips.append({"texto": f"{i}º {cols[k].rotulo} {'A→Z' if d == 'asc' else 'Z→A'}",
                      "remover": _url(caminho, base + [("ordem", _texto_ordem(resto))] if resto else base),
                      "tipo": "ordem"})
    limpar_tudo = _url(caminho, [(k, v) for k, v in pares if not k.startswith("f.") and k != "ordem"])

    total = len(r["linhas"])
    mostradas = r["linhas"] if tudo else r["linhas"][:LIMITE_TELA]
    corpo = [[{"texto": exibir(c, l.get(c.chave)), "link": c.link(l) if c.link else None, "col": c}
              for c in visiveis] for l in mostradas]
    return {"colunas": visiveis, "todas": colunas, "menus": menus, "chips": chips, "limpar_tudo": limpar_tudo,
            "corpo": corpo, "linhas": r["linhas"], "total": total, "cortado": total > len(mostradas),
            "visiveis": estado["visiveis"], "pares": pares, "caminho": caminho,
            "ocultos_cols": _sem(pares, {"cols"}), "filtros_texto": texto_filtros(colunas, estado),
            "url_tudo": _url(caminho, pares + [("tudo", "1"), ("imprimir", "1")]),
            "url_csv": _url(caminho, pares + [("formato", "csv")])}


def csv_de(tabela: dict) -> str:
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([c.rotulo for c in tabela["colunas"]])
    for l in tabela["linhas"]:
        w.writerow([exibir(c, l.get(c.chave)) if l.get(c.chave) not in (None, "") else "" for c in tabela["colunas"]])
    return "﻿" + buf.getvalue()
