"""
Datas e horas no padrão MEVAM GYN.

- Fuso oficial: America/Sao_Paulo (GMT-03:00).
- Entrada e exibição: dd/mm/aaaa e HH:MM.
- Banco: date / timestamp com fuso (UTC) para registros de sistema.
- Eventos legados da Agenda guardam "AAAA-MM-DDTHH:MM:SS" no horário local de Goiânia;
  esse formato é mantido para não alterar dados existentes.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from .config import FUSO_HORARIO

TZ = ZoneInfo(FUSO_HORARIO)

_RE_BR = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$")
_RE_ISO = re.compile(r"^\s*(\d{4})-(\d{2})-(\d{2})")
_RE_HORA = re.compile(r"^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$")

DIAS_SEMANA = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
         "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]


def agora() -> datetime:
    """Momento atual no fuso de Goiânia (com tzinfo)."""
    return datetime.now(TZ)


def agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def hoje() -> date:
    return agora().date()


def parse_data(valor) -> date | None:
    """Aceita dd/mm/aaaa, aaaa-mm-dd, date ou datetime. Retorna None se vazio ou inválido."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()
    m = _RE_BR.match(texto)
    if m:
        d, mth, a = (int(x) for x in m.groups())
    else:
        m = _RE_ISO.match(texto)
        if not m:
            # Também aceita somente dígitos ddmmaaaa digitados sem máscara
            digitos = re.sub(r"\D", "", texto)
            if len(digitos) != 8:
                return None
            d, mth, a = int(digitos[:2]), int(digitos[2:4]), int(digitos[4:])
        else:
            a, mth, d = (int(x) for x in m.groups())
    try:
        return date(a, mth, d)
    except ValueError:
        return None


def parse_hora(valor) -> time | None:
    if valor is None or valor == "":
        return None
    if isinstance(valor, time):
        return valor
    m = _RE_HORA.match(str(valor))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return None
    return time(h, mi)


def parse_data_hora_local(valor) -> datetime | None:
    """Lê data/hora de evento (legado: texto ISO sem fuso, ou timestamp do Postgres) como horário local."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        if valor.tzinfo is not None:
            return valor.astimezone(TZ).replace(tzinfo=None)
        return valor
    texto = str(valor).strip().replace(" ", "T")
    try:
        dt = datetime.fromisoformat(texto)
    except ValueError:
        d = parse_data(texto[:10])
        return datetime.combine(d, time(0, 0)) if d else None
    if dt.tzinfo is not None:
        dt = dt.astimezone(TZ).replace(tzinfo=None)
    return dt


def iso_evento(d: date, h: time | None) -> str:
    """Formato gravado na coluna eventos.data_inicio (compatível com a Agenda atual)."""
    h = h or time(0, 0)
    return f"{d.isoformat()}T{h.strftime('%H:%M:%S')}"


def fmt_data(valor) -> str:
    d = parse_data(valor) if not isinstance(valor, datetime) else valor.date()
    return d.strftime("%d/%m/%Y") if d else ""


def fmt_data_hora(valor) -> str:
    """Formata timestamp (UTC/aware ou naive local) como dd/mm/aaaa HH:MM em Goiânia."""
    if valor is None or valor == "":
        return ""
    if isinstance(valor, str):
        try:
            valor = datetime.fromisoformat(valor.replace(" ", "T").replace("Z", "+00:00"))
        except ValueError:
            return valor
    if isinstance(valor, datetime):
        if valor.tzinfo is not None:
            valor = valor.astimezone(TZ)
        return valor.strftime("%d/%m/%Y %H:%M")
    return fmt_data(valor)


def dia_semana(d: date) -> str:
    return DIAS_SEMANA[d.weekday()]


def idade(nascimento, referencia: date | None = None) -> int | None:
    n = parse_data(nascimento)
    if not n:
        return None
    r = referencia or hoje()
    return r.year - n.year - ((r.month, r.day) < (n.month, n.day))
