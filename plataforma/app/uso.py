"""Uso dos serviços gratuitos (Render, Supabase, e-mail) para evitar bloqueio por limite.

Os contadores ficam na memória e são gravados em uso_diario a cada chamada do /healthz (5 min).
"""

from __future__ import annotations

import calendar
import logging
import threading
import time
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func, insert, select, update

from . import config, datas, db

log = logging.getLogger("mevam")
_trava = threading.Lock()
_pendente: dict[tuple[date, str], int] = defaultdict(int)
INICIO = time.time()


def contar(chave: str, n: int = 1) -> None:
    with _trava:
        _pendente[(datas.agora().date(), chave)] += n


def gravar() -> None:
    with _trava:
        itens = list(_pendente.items())
        _pendente.clear()
    if not itens:
        return
    t = db.uso_diario
    try:
        with db.engine().begin() as c:
            for (dia, chave), n in itens:
                r = c.execute(update(t).where(t.c.dia == dia, t.c.chave == chave).values(valor=t.c.valor + n))
                if not r.rowcount:
                    c.execute(insert(t).values(dia=dia, chave=chave, valor=n))
    except Exception:  # noqa: BLE001
        log.exception("Falha ao gravar o uso dos serviços")
        with _trava:  # devolve para tentar na próxima rodada
            for k, n in itens:
                _pendente[k] += n


def soma(chaves: tuple[str, ...], de: date, ate: date) -> int:
    t = db.uso_diario
    with db.engine().connect() as c:
        total = c.execute(select(func.coalesce(func.sum(t.c.valor), 0))
                          .where(t.c.chave.in_(chaves), t.c.dia >= de, t.c.dia <= ate)).scalar() or 0
    with _trava:
        total += sum(n for (d, k), n in _pendente.items() if k in chaves and de <= d <= ate)
    return int(total)


def hoje(chave: str) -> int:
    d = datas.agora().date()
    return soma((chave,), d, d)


def por_dia(chaves: tuple[str, ...], dias: int) -> list[tuple[date, int]]:
    fim = datas.agora().date()
    ini = fim - timedelta(days=dias - 1)
    t = db.uso_diario
    with db.engine().connect() as c:
        linhas = dict(c.execute(select(t.c.dia, func.sum(t.c.valor)).where(t.c.chave.in_(chaves), t.c.dia >= ini)
                                .group_by(t.c.dia)).all())
    with _trava:
        for (d, k), n in _pendente.items():
            if k in chaves and d >= ini:
                linhas[d] = linhas.get(d, 0) + n
    return [(ini + timedelta(days=i), int(linhas.get(ini + timedelta(days=i), 0))) for i in range(dias)]


def banco() -> dict:
    """Tamanho do banco, maiores tabelas e espaço das fotos."""
    eng = db.engine()
    with eng.connect() as c:
        if eng.dialect.name == "postgresql":
            total = c.exec_driver_sql("select pg_database_size(current_database())").scalar()
            tabelas = c.exec_driver_sql(
                "select c.relname, pg_total_relation_size(c.oid) from pg_class c join pg_namespace n on n.oid = c.relnamespace "
                "where n.nspname = 'public' and c.relkind = 'r' order by 2 desc limit 8").all()
        else:
            total = c.exec_driver_sql("pragma page_count").scalar() * c.exec_driver_sql("pragma page_size").scalar()
            tabelas = []
        m = db.membros.c
        fotos, n_fotos = c.execute(select(func.coalesce(func.sum(func.length(m.foto_3x4)), 0),
                                          func.count(m.foto_3x4))).one()
        n_membros = c.execute(select(func.count()).select_from(db.membros)).scalar()
    return {"bytes": int(total or 0), "tabelas": [(n, int(b)) for n, b in tabelas], "fotos": int(fotos or 0),
            "n_fotos": int(n_fotos or 0), "n_membros": int(n_membros or 0)}


def _nivel(pct: float) -> str:
    return "vermelho" if pct >= 90 else "amarelo" if pct >= 70 else "verde"


def _item(nome, usado, limite, unidade, detalhe, projecao=None, so_estouro=False):
    pct = usado * 100 / limite if limite else 0
    base = max(pct, projecao * 100 / limite) if projecao is not None and limite else pct
    nivel = ("vermelho" if base > 100 else "verde") if so_estouro else _nivel(base)
    return {"nome": nome, "usado": usado, "limite": limite, "unidade": unidade, "pct": min(round(pct), 100),
            "pct_real": round(pct, 1), "projecao": projecao, "nivel": nivel, "detalhe": detalhe}


def painel() -> dict:
    agora = datas.agora()
    hoje_ = agora.date()
    ini_mes = hoje_.replace(day=1)
    dias_mes = calendar.monthrange(hoje_.year, hoje_.month)[1]
    dia_n = hoje_.day - 1 + (agora.hour * 60 + agora.minute) / 1440
    fator = dias_mes / dia_n if dia_n > 0.5 else None

    banda = soma(("banda_bytes",), ini_mes, hoje_) / 1024 ** 2
    horas = dia_n * 24  # o UptimeRobot mantém o serviço sempre acordado
    b = banco()
    eg = soma(("email_google",), hoje_, hoje_)
    eb = soma(("email_brevo",), hoje_, hoje_)
    itens = [
        _item("Render · horas do servidor no mês", round(horas), config.LIMITE_HORAS_RENDER, "h",
              f"Sempre acordado pelo UptimeRobot: {dias_mes * 24} h no mês, dentro do limite só se este for o ÚNICO serviço "
              "gratuito acordado na conta do Render. Não crie outro serviço gratuito nessa conta.",
              dias_mes * 24, so_estouro=True),
        _item("Render · banda de saída no mês", round(banda, 1), round(config.LIMITE_BANDA_RENDER_GB * 1024), "MB",
              "Medida pelo próprio sistema desde a publicação da v2.8.0 (páginas, arquivos e PDFs dos manuais).",
              round(banda * fator, 1) if fator else None),
        _item("Supabase · tamanho do banco", round(b["bytes"] / 1024 ** 2, 1), config.LIMITE_BANCO_MB, "MB",
              f"{b['n_membros']} fichas; as {b['n_fotos']} fotos ocupam {b['fotos'] / 1024 ** 2:.1f} MB."),
        _item("E-mail · Google (Gmail da Secretaria) hoje", eg, config.LIMITE_EMAIL_GOOGLE_DIA, "e-mails",
              "Ao chegar no limite, o sistema passa a enviar pelo Brevo (se configurado) até a meia-noite."),
        _item("E-mail · Brevo (reserva) hoje", eb, config.LIMITE_EMAIL_BREVO_DIA, "e-mails", "Usado só quando o Google atinge o limite."),
    ]
    return {"itens": itens, "banco": b, "alerta": max(itens, key=lambda i: ("verde", "amarelo", "vermelho").index(i["nivel"]))["nivel"],
            "emails_30": por_dia(("email_google", "email_brevo", "email_smtp"), 30),
            "falhas_hoje": hoje("email_falha"), "requisicoes_hoje": hoje("requisicoes"),
            "no_ar_desde": datas.agora() - timedelta(seconds=time.time() - INICIO)}


class MedirBanda:
    """Middleware ASGI: soma os bytes enviados aos navegadores (banda de saída do Render)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def enviar(msg):
            if msg["type"] == "http.response.start":
                contar("requisicoes")
                contar("banda_bytes", 300)  # cabeçalhos, em média
            elif msg["type"] == "http.response.body":
                contar("banda_bytes", len(msg.get("body", b"")))
            await send(msg)

        await self.app(scope, receive, enviar)
