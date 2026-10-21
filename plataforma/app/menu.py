"""Menu lateral: funções agrupadas por processo de trabalho, filtradas pelo perfil.

Cada item tem o endereço, o ícone, o rótulo, os perfis que o veem (vazio = todos) e outros
prefixos de endereço que também o marcam como tela atual (ex.: /eventos/12 é da Agenda).
"""
GESTAO = ("coordenacao", "secretaria", "admin")
SEC_ADM = ("secretaria", "admin")
ADM = ("admin",)

INICIO = ("/inicio", "🏠", "Início", (), ())

GRUPOS = [
    ("agenda", "📅", "Agenda", [
        ("/agenda", "🗓️", "Agenda", (), ("/eventos", "/inscricoes", "/custos")),
        ("/eventos/novo", "➕", "Novo evento", GESTAO, ()),
    ]),
    ("pessoas", "👥", "Pessoas", [
        ("/membros", "📇", "Membros", SEC_ADM, ("/credo",)),
        ("/integra", "🎓", "INTEGRA", SEC_ADM, ()),
        ("/mutirao", "📥", "Mutirão de fichas", SEC_ADM, ()),
        ("/regularizacao", "📋", "Regularização", SEC_ADM, ()),
        ("/coordenacao", "🧭", "Coordenação", SEC_ADM, ()),
        ("/membros/lixeira", "🗑️", "Lixeira", SEC_ADM, ()),
    ]),
    ("cuidado", "💛", "Cuidado", [
        ("/aniversariantes", "🎂", "Aniversariantes", GESTAO, ()),
        ("/voluntarios", "🙋", "Voluntários", GESTAO, ()),
        ("/avisos", "🔔", "Avisos", GESTAO, ()),
        ("/necessidades/painel", "📊", "Necessidades da igreja", GESTAO, ()),
    ]),
    ("relatorios", "🖨️", "Relatórios", [
        ("/relatorios", "📊", "Central de relatórios", (), ()),
        ("/admin/satisfacao", "⭐", "Pesquisa de satisfação", SEC_ADM, ()),
    ]),
    ("minha", "🪪", "Minha área", [
        ("/minha-ficha", "📝", "Minha ficha", (), ()),
        ("/meu-cpf", "🔢", "Meu CPF", (), ()),
        ("/necessidades", "📝", "Pesquisa do mês", (), ()),
        ("/trocar-senha", "🔑", "Trocar senha", (), ()),
        ("/manual/membro", "📘", "Manual do Membro", (), ()),
    ]),
    ("instituto", "🎓", "Instituto", [
        ("/instituto", "🎓", "Instituto", ADM, ()),
    ]),
    ("admin", "🔐", "Administração", [
        ("/admin/usuarios", "👤", "Usuários", ADM, ()),
        ("/admin/setores", "🏢", "Ministérios", ADM, ()),
        ("/admin/auditoria", "🔍", "Auditoria", ADM, ()),
        ("/admin/servicos", "📶", "Uso dos serviços", ADM, ()),
    ]),
]

# Atalhos da barra inferior do celular (além de Início e do botão Menu)
ATALHOS = {
    "membro": ("/agenda", "/minha-ficha"),
    "coordenacao": ("/agenda", "/eventos/novo"),
    "secretaria": ("/agenda", "/membros"),
    "admin": ("/agenda", "/membros"),
}


def _casa(caminho: str, prefixo: str) -> bool:
    return caminho == prefixo or caminho.startswith(prefixo.rstrip("/") + "/") or (
        prefixo.endswith("/") and caminho.startswith(prefixo))


def montar(usuario: dict | None, caminho: str) -> dict:
    """Devolve {"inicio", "grupos", "atalhos"} já filtrados e com a tela atual marcada."""
    perfil = (usuario or {}).get("perfil", "")

    def item(t):
        href, ic, rotulo, perfis, extras = t
        return {"href": href, "ic": ic, "rotulo": rotulo, "prefixos": (href, *extras), "ativo": False}

    inicio = item(INICIO)
    grupos = []
    for chave, ic, rotulo, itens in GRUPOS:
        vis = [item(t) for t in itens if not t[3] or perfil in t[3]]
        if vis:
            grupos.append({"chave": chave, "ic": ic, "rotulo": rotulo, "itens": vis, "aberto": False})

    # Tela atual = o prefixo mais longo que casa com o endereço (ex.: /membros/lixeira vence /membros)
    todos = [inicio] + [i for g in grupos for i in g["itens"]]
    melhor, tam = None, -1
    for i in todos:
        for p in i["prefixos"]:
            if _casa(caminho, p) and len(p) > tam:
                melhor, tam = i, len(p)
    if melhor:
        melhor["ativo"] = True
    for g in grupos:
        g["aberto"] = any(i["ativo"] for i in g["itens"])

    por_href = {i["href"]: i for i in todos}
    atalhos = [inicio] + [por_href[h] for h in ATALHOS.get(perfil, ()) if h in por_href]
    return {"inicio": inicio, "grupos": grupos, "atalhos": atalhos}
