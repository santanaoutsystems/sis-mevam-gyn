"""Dia do Profissional (v2.11.0): data de homenagem à profissão de cada membro.

A ficha sugere a data a partir da profissão informada e a pessoa pode corrigir. Guardamos só dia e mês ("dd/mm").
Na data, a Coordenação dos setores do membro e a Secretaria/Adm recebem o aviso no sino, como no aniversário.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import date

from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from . import datas, db

log = logging.getLogger("mevam")
TIPO = "profissional_hoje"

# Palavra-chave (sem acento, minúscula, começo de palavra) → (dia/mês, nome da data). A primeira que casar vale.
DIAS = [
    ("tecnico de enfermagem", "20/05", "Dia do Técnico de Enfermagem"),
    ("tecnica de enfermagem", "20/05", "Dia do Técnico de Enfermagem"),
    ("auxiliar de enfermagem", "20/05", "Dia do Técnico e Auxiliar de Enfermagem"),
    ("enferm", "12/05", "Dia do Enfermeiro"),
    ("professor", "15/10", "Dia do Professor"),
    ("docente", "15/10", "Dia do Professor"),
    ("pedagog", "20/05", "Dia do Pedagogo"),
    ("psicopedagog", "12/11", "Dia do Psicopedagogo"),
    ("veterinar", "09/09", "Dia do Médico Veterinário"),
    ("medic", "18/10", "Dia do Médico"),
    ("dentista", "25/10", "Dia do Dentista"),
    ("odontolog", "25/10", "Dia do Dentista"),
    ("farmac", "20/01", "Dia do Farmacêutico"),
    ("nutricion", "31/08", "Dia do Nutricionista"),
    ("fisioterap", "13/10", "Dia do Fisioterapeuta"),
    ("psicolog", "27/08", "Dia do Psicólogo"),
    ("assistente social", "15/05", "Dia do Assistente Social"),
    ("advog", "11/08", "Dia do Advogado"),
    ("engenheir", "11/12", "Dia do Engenheiro"),
    ("arquitet", "15/12", "Dia do Arquiteto"),
    ("contador", "22/09", "Dia do Contador"),
    ("contabil", "22/09", "Dia do Contador"),
    ("administrador", "09/09", "Dia do Administrador"),
    ("economista", "13/08", "Dia do Economista"),
    ("bancari", "28/08", "Dia do Bancário"),
    ("secretari", "30/09", "Dia da Secretária"),
    ("jornalist", "07/04", "Dia do Jornalista"),
    ("publicitari", "01/02", "Dia do Publicitário"),
    ("designer", "05/11", "Dia do Designer"),
    ("fotograf", "08/01", "Dia do Fotógrafo"),
    ("music", "22/11", "Dia do Músico"),
    ("bibliotecari", "12/03", "Dia do Bibliotecário"),
    ("biolog", "03/09", "Dia do Biólogo"),
    ("programador", "13/09", "Dia do Programador"),
    ("desenvolvedor", "13/09", "Dia do Programador"),
    ("motorista", "25/07", "Dia do Motorista"),
    ("bombeir", "02/07", "Dia do Bombeiro"),
    ("policial", "21/04", "Dia do Policial"),
    ("militar", "25/08", "Dia do Soldado"),
    ("carteir", "25/01", "Dia do Carteiro"),
    ("garcom", "11/08", "Dia do Garçom"),
    ("gari", "16/05", "Dia do Gari"),
    ("agricult", "28/07", "Dia do Agricultor"),
    ("vendedor", "01/10", "Dia do Vendedor"),
    ("comerciari", "30/10", "Dia do Comerciário"),
    ("empresari", "05/10", "Dia do Empreendedor"),
    ("empreendedor", "05/10", "Dia do Empreendedor"),
    ("servidor publico", "28/10", "Dia do Servidor Público"),
    ("funcionario publico", "28/10", "Dia do Servidor Público"),
    ("aposentad", "24/01", "Dia do Aposentado"),
    ("estudante", "11/08", "Dia do Estudante"),
]

_RE_DIA = re.compile(r"^(\d{1,2})/(\d{1,2})$")


def _normal(texto: str) -> str:
    t = unicodedata.normalize("NFD", (texto or "").lower())
    return " " + "".join(ch for ch in t if unicodedata.category(ch) != "Mn") + " "


def sugerir(profissao: str) -> tuple[str, str] | None:
    """(dd/mm, nome da data) sugeridos para a profissão, ou None."""
    t = _normal(profissao)
    for chave, dia, nome in DIAS:
        if re.search(r"[^a-z]" + re.escape(chave), t):
            return dia, nome
    return None


def normalizar(texto: str) -> str | None:
    """'5/9' → '05/09'. None se vazio ou inválido (29/02 é aceito)."""
    m = _RE_DIA.match((texto or "").strip())
    if not m:
        return None
    d, mes = int(m.group(1)), int(m.group(2))
    try:
        date(2024, mes, d)  # ano bissexto: aceita 29/02
    except ValueError:
        return None
    return f"{d:02d}/{mes:02d}"


def nome_da_data(dia: str, profissao: str = "") -> str:
    s = sugerir(profissao)
    if s and s[0] == dia:
        return s[1]
    return "Dia do Profissional"


def hoje_ddmm(d: date) -> str:
    return d.strftime("%d/%m")


def gerar_avisos(c, hoje: date | None = None) -> int:
    """Cria (uma vez) o aviso do Dia do Profissional de hoje para a Coordenação dos setores e para Secretaria/Adm."""
    from . import aniversarios as an
    hoje = hoje or datas.hoje()
    chaves = [hoje_ddmm(hoje)]
    if hoje.month == 3 and hoje.day == 1 and not _bissexto(hoje.year):
        chaves.append("29/02")  # quem faz no 29/02 é lembrado em 01/03 nos anos comuns
    m = db.membros.c
    ids = set(c.execute(select(m.id).where(m.dia_profissional.in_(chaves), m.status.notin_(db.STATUS_FORA),
                                           m.homenagem_profissional.isnot(False))).scalars())
    if not ids:
        return 0
    lista = an.membros(c, ids, so_aniversario=False)
    coords, gest = an.coordenadores(c), an.gestores(c)
    a = db.avisos.c
    existentes = set(c.execute(select(a.usuario_id, a.membro_id).where(a.tipo == TIPO, a.referencia == hoje)).all())
    criados = 0
    for pessoa in lista:
        for uid in an.destinatarios(pessoa, coords, gest):
            if (uid, pessoa["id"]) in existentes:
                continue
            try:
                with c.begin_nested():
                    c.execute(insert(db.avisos).values(usuario_id=uid, tipo=TIPO, membro_id=pessoa["id"], referencia=hoje,
                                                       janela=False, criado_em=datas.agora_utc()))
                criados += 1
            except IntegrityError:
                pass
    return criados


def _bissexto(ano: int) -> bool:
    return ano % 4 == 0 and (ano % 100 != 0 or ano % 400 == 0)


def mensagem(primeiro: str, nome_data: str, remetente: str) -> str:
    return (f"Paz, {primeiro}! Hoje é o {nome_data}. Agradecemos a Deus pelo seu trabalho e pela forma como você "
            f"serve as pessoas com a sua profissão. Que o Senhor abençoe as obras das suas mãos (Salmos 90:17). "
            f"Com carinho, {remetente} · MEVAM GYN")
