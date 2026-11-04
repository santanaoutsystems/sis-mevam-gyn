"""Ministérios e Áreas: a estrutura oficial do MEVAM GYN (Relação Oficial de Ministérios,
Departamentos e Áreas de Apoio, recebida em 22/10/2026).

As áreas ficam na tabela legada `departamentos` (nome, responsável) com três campos novos
(migração 016): categoria, ordem e ativo. `sincronizar()` roda uma única vez na subida do sistema:
renomeia as áreas que já existiam para o nome oficial (levando junto eventos e interesses),
cria as que faltam, preenche a categoria e lota os usuários da Secretaria e do Adm.
Nada é apagado. Uma área fora da lista oficial continua lá, sem categoria, para o Adm decidir.

Estar numa área NÃO dá acesso: o acesso vem do perfil (Membro, Coordenação, Secretaria, Adm).
"""
import logging
import unicodedata

from sqlalchemy import func, insert, select, update

from . import datas, db

CATEGORIAS = ["Ministério", "Adm. / Tesouraria", "Área de Apoio", "Frente Ministerial", "Departamento de Ensino"]
FORA_DA_LISTA = "Fora da lista oficial"

# (nome oficial, categoria, descrição para quem quer servir, nomes antigos que viram este)
AREAS = [
    ("Ministério de Voluntários", "Ministério", "Recepção, apoio e serviço nos cultos e eventos",
     ("Voluntariado", "Voluntários", "Líder dos Voluntários", "Ministério de Voluntariado")),
    ("Ministério Kids", "Ministério", "Cuidado e ensino das crianças", ("Kids", "Ministério Infantil", "Infantil")),
    ("Ministério de Mulheres", "Ministério", "Cultos e encontros de mulheres, incluindo o Inteiras (Mulheres Inteiras)",
     ("Mulheres",)),
    ("Ministério Mães de Pequenos", "Ministério", "Apoio e encontros para mães de filhos pequenos", ("Mães de Pequenos",)),
    ("Ministério Teens", "Ministério", "Adolescentes", ("Teens", "Adolescentes")),
    ("Ministério de Jovens", "Ministério", "Cultos e encontros de jovens", ("Jovens",)),
    ("Ministério de Homens", "Ministério", "Cultos e encontros de homens, incluindo o MP6 (Mesa para Seis)", ("Homens",)),
    ("Ministério de Louvor", "Ministério", "Música e ministração nos cultos", ("Louvor",)),
    ("Ministério Social", "Ministério", "Ação social do MEVAM", ("Mevam Social", "Social", "Ação Social")),
    ("Ministério de Intercessão", "Ministério", "Oração e intercessão pela igreja", ("Intercessão",)),
    ("Administração e Tesouraria", "Adm. / Tesouraria", "Administração, finanças e tesouraria",
     ("Administração", "Tesouraria")),
    ("Secretaria", "Adm. / Tesouraria", "Cadastro de membros, documentos e atendimento", ()),
    ("Mídia", "Área de Apoio", "Redes sociais, fotos, vídeos, transmissões e avisos",
     ("Mídia e Comunicação", "Comunicação")),
    ("Led (Projeção / Audiovisual)", "Área de Apoio", "Projeção, telão e audiovisual nos cultos", ("LED", "Projeção")),
    ("Bazar", "Área de Apoio", "Organização e vendas do bazar", ()),
    ("GC's (Grupos de Convívio)", "Frente Ministerial", "Grupos que se reúnem nas casas durante a semana",
     ("GCs", "GC's", "GC’s", "Líder dos GC's", "Líder dos GC’s", "Grupos de Convívio")),
    ("Store (Livraria)", "Área de Apoio", "Livraria e loja do MEVAM", ("Store", "Livraria")),
    ("Escola de Teologia", "Departamento de Ensino", "Cursos, aulas e formação bíblica",
     ("Escola Teológica", "Teologia")),
]
NOMES = [a[0] for a in AREAS]
CATEGORIA_DE = {a[0]: a[1] for a in AREAS}
AREA_SECRETARIA = "Secretaria"
AREA_ADM = "Administração e Tesouraria"
LOTACAO_PADRAO = {"secretaria": AREA_SECRETARIA, "admin": AREA_ADM}
MARCA_SINCRONIA = "AREAS_OFICIAIS_V1"


def chave(nome: str) -> str:
    """Compara nomes sem acento, maiúsculas, apóstrofos ou espaços extras."""
    t = unicodedata.normalize("NFD", (nome or "").replace("’", "'")).encode("ascii", "ignore").decode()
    return " ".join(t.lower().split())


_OFICIAL = {}
for _nome, _cat, _desc, _antigos in AREAS:
    for _n in (_nome, *_antigos):
        _OFICIAL[chave(_n)] = _nome
_OFICIAL[chave("Discipulado Inteiras")] = "Ministério de Mulheres"  # só para interesses/aniversários; não funde a área


def nome_oficial(nome: str) -> str | None:
    """Nome oficial de uma área (aceita os nomes antigos). None se não for da lista."""
    return _OFICIAL.get(chave(nome))


def equivalentes(nome: str) -> list[str]:
    """O nome oficial e os nomes antigos que valem como ele (para buscas em dados já gravados)."""
    oficial = nome_oficial(nome) or nome
    for n, _c, _d, antigos in AREAS:
        if n == oficial:
            return [n, *antigos] + (["Discipulado Inteiras"] if n == "Ministério de Mulheres" else [])
    return [nome]


def lista(c, so_ativas: bool = False) -> list[dict]:
    """Áreas cadastradas, na ordem oficial (as de fora da lista no fim)."""
    linhas = [dict(r) for r in c.execute(select(db.departamentos)).mappings()]
    if so_ativas:
        linhas = [d for d in linhas if d.get("ativo") is not False]
    for d in linhas:
        d["categoria"] = d.get("categoria") or FORA_DA_LISTA
    ordem_cat = {k: i for i, k in enumerate(CATEGORIAS + [FORA_DA_LISTA])}
    return sorted(linhas, key=lambda d: (ordem_cat.get(d["categoria"], 99), d.get("ordem") or 999, chave(d["nome"])))


def agrupar(areas: list[dict]) -> list[tuple[str, list[dict]]]:
    """[(categoria, [áreas])] na ordem oficial, para <optgroup> e listas."""
    grupos: dict[str, list] = {}
    for d in areas:
        grupos.setdefault(d.get("categoria") or FORA_DA_LISTA, []).append(d)
    return [(cat, grupos[cat]) for cat in CATEGORIAS + [FORA_DA_LISTA] if cat in grupos]


def interesses_agrupados() -> list[tuple[str, list[tuple[str, str]]]]:
    """Para a ficha: [(categoria, [(nome, descrição)])]."""
    return [(cat, [(n, d) for n, c, d, _ in AREAS if c == cat]) for cat in CATEGORIAS]


def id_por_nome(c, nome: str) -> str | None:
    for i, n in c.execute(select(db.DEP_ID, db.departamentos.c.nome)):
        if n == nome:
            return i
    return None


def sincronizar(c, forcar: bool = False) -> list[str]:
    """Aplica a estrutura oficial uma vez (marca na Auditoria). Devolve o que foi feito."""
    ja = c.execute(select(func.count()).select_from(db.auditoria)
                   .where(db.auditoria.c.acao == MARCA_SINCRONIA)).scalar()
    if ja and not forcar:
        return []
    feitos: list[str] = []
    existentes = [dict(r) for r in c.execute(select(db.DEP_ID.label("sid"), db.departamentos.c.nome)).mappings()]
    por_chave = {chave(d["nome"]): d for d in existentes}
    for ordem, (nome, categoria, _desc, antigos) in enumerate(AREAS, start=1):
        alvo = por_chave.get(chave(nome))
        if not alvo:
            alvo = next((por_chave[chave(a)] for a in antigos if chave(a) in por_chave), None)
            if alvo:
                antigo = alvo["nome"]
                c.execute(update(db.departamentos).where(db.DEP_ID == alvo["sid"]).values(nome=nome))
                # Eventos guardam o nome da área: renomeia junto para não perder o vínculo
                n_ev = c.execute(update(db.eventos).where(db.eventos.c.departamento == antigo)
                                 .values(departamento=nome)).rowcount
                feitos.append(f"{antigo} → {nome} ({n_ev} evento(s))")
                por_chave.pop(chave(antigo), None)
                alvo = {"sid": alvo["sid"], "nome": nome}
                por_chave[chave(nome)] = alvo
        if alvo:
            c.execute(update(db.departamentos).where(db.DEP_ID == alvo["sid"])
                      .values(categoria=categoria, ordem=ordem, ativo=True))
        else:
            c.execute(insert(db.departamentos).values(nome=nome, categoria=categoria, ordem=ordem, ativo=True))
            feitos.append(f"criada: {nome}")
    # Interesses ("Em que deseja servir") gravados com nomes antigos passam para o nome oficial
    mi = db.membro_interesses.c
    for mid, setor, iid in c.execute(select(mi.membro_id, mi.setor, mi.id)).all():
        novo = nome_oficial(setor)
        if novo and novo != setor:
            tem = c.execute(select(func.count()).select_from(db.membro_interesses)
                            .where(mi.membro_id == mid, mi.setor == novo)).scalar()
            if tem:
                continue  # já marcado com o nome novo; o antigo é ignorado na leitura
            c.execute(update(db.membro_interesses).where(mi.id == iid).values(setor=novo))
    # Secretaria e Adm lotados nas suas áreas (o acesso deles continua completo)
    ids = {n: id_por_nome(c, n) for n in LOTACAO_PADRAO.values()}
    for perfil, area in LOTACAO_PADRAO.items():
        n = c.execute(update(db.usuarios).where(db.usuarios.c.perfil == perfil, db.usuarios.c.area_id.is_(None))
                      .values(area_id=ids[area])).rowcount
        if n:
            feitos.append(f"{n} usuário(s) {perfil} lotado(s) em {area}")
    oficiais = {chave(x) for x in NOMES}
    fora = [n for n in c.execute(select(db.departamentos.c.nome)).scalars() if chave(n) not in oficiais]
    if fora:
        feitos.append("fora da lista oficial (decidir no Adm): " + ", ".join(fora))
    c.execute(insert(db.auditoria).values(usuario_nome="Sistema", acao=MARCA_SINCRONIA, recurso="Ministérios e Áreas",
                                          detalhes="; ".join(feitos)[:2000] or "nada a mudar",
                                          ip="", criado_em=datas.agora_utc()))
    return feitos


def sincronizar_na_subida() -> None:
    try:
        with db.engine().begin() as c:
            feitos = sincronizar(c)
        if feitos:
            logging.getLogger("mevam").info("Ministérios e Áreas: %s", "; ".join(feitos))
    except Exception:  # noqa: BLE001
        logging.getLogger("mevam").exception("Falha ao aplicar a estrutura oficial de Ministérios e Áreas")


def lotacao_padrao(c, perfil: str) -> str | None:
    area = LOTACAO_PADRAO.get(perfil)
    return id_por_nome(c, area) if area else None
