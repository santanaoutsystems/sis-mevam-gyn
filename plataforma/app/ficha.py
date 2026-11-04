"""
Regras da Ficha de Membro (validação, normalização e opções dos campos).

Mantém as regras da v1.26: seções 1, 2 e 3 obrigatórias. Desde a v2.6.0 a foto 3x4 é opcional no pré-cadastro:
quem não envia recebe lembretes por e-mail e tem 30 dias para completar (ver lembretes.py).
"""

from __future__ import annotations

import json
import re

from . import areas, datas, profissional

ESTADOS_CIVIS = ["Solteiro(a)", "Casado(a)", "União Estável", "Divorciado(a)", "Viúvo(a)"]
ESCOLARIDADES = ["Ensino Fundamental", "Ensino Médio", "Superior Incompleto", "Superior Completo",
                 "Pós-Graduação / Especialização", "Mestrado", "Doutorado"]
SEXOS = ["Masculino", "Feminino"]
SIM_NAO = ["Sim", "Não"]
DIZIMO_OPCOES = ["Sim", "Não", "Já sou dizimista"]

# Setores padronizados (proposta "Padronização dos Setores", Edição 02): nome completo e o que a equipe faz.
# Ministérios e Áreas em que o membro deseja servir: a lista oficial (app/areas.py)
SETORES_INTERESSE = [(nome, descricao) for nome, _cat, descricao, _antigos in areas.AREAS]
NOMES_SETORES = list(areas.NOMES)


def setor_padrao(nome: str) -> str | None:
    """Nome oficial de uma área cadastrada (aceita os nomes antigos)."""
    return areas.nome_oficial(nome)


def interesses_do_form(form) -> list[str]:
    escolhidos = set(form.getlist("interesses")) if hasattr(form, "getlist") else set(form.get("interesses") or [])
    escolhidos = {setor_padrao(n) or n for n in escolhidos}  # aceita também os nomes antigos
    return [n for n in NOMES_SETORES if n in escolhidos]

OBRIGATORIOS = {
    "nome_completo": "Nome completo",
    "data_nascimento": "Data de nascimento",
    "naturalidade": "Naturalidade",
    "sexo": "Sexo",
    "estado_civil": "Estado civil",
    "cep": "CEP",
    "endereco": "Endereço",
    "bairro": "Bairro",
    "cidade": "Cidade",
    "whatsapp": "WhatsApp",
    "email": "E-mail",
    "escolaridade": "Escolaridade",
    "formacao_academica": "Formação acadêmica",
    "profissao": "Profissão",
    "empresa": "Empresa / ocupação",
    "batizado": "Batizado nas águas",
    "congregava_antes": "Congregava antes",
}

CAMPOS_TEXTO = ["nome_completo", "naturalidade", "sexo", "estado_civil", "conjuge", "cep", "endereco",
                "bairro", "cidade", "whatsapp", "telefone", "email", "escolaridade", "formacao_academica",
                "profissao", "empresa", "batizado", "congregava_antes", "onde_congregava", "area_ministerial",
                "interesse_batismo_familia"]

_RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def so_digitos(v: str) -> str:
    return re.sub(r"\D", "", v or "")


ERRO_TELEFONE = "Use o padrão (62) 9 9999-9999: DDD + 9 dígitos."


def _digitos_telefone(v: str) -> str:
    d = so_digitos(v)
    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]
    return d


def telefone_valido(v: str) -> bool:
    """Padrão obrigatório (##) # ####-####: DDD + 9 dígitos."""
    return len(_digitos_telefone(v)) == 11


def fmt_telefone(v: str) -> str:
    d = _digitos_telefone(v)
    if len(d) == 11:
        return f"({d[:2]}) {d[2]} {d[3:7]}-{d[7:]}"
    if len(d) == 10:  # registros antigos (fixo) continuam legíveis
        return f"({d[:2]}) {d[2:6]}-{d[6:]}"
    return (v or "").strip()


def fmt_cep(v: str) -> str:
    d = so_digitos(v)
    return f"{d[:5]}-{d[5:]}" if len(d) == 8 else (v or "").strip()


def cpf_valido(v: str) -> bool:
    """Confere os dois dígitos verificadores do CPF."""
    d = so_digitos(v)
    if len(d) != 11 or d == d[0] * 11:
        return False
    for n in (9, 10):
        soma = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        if (soma * 10) % 11 % 10 != int(d[n]):
            return False
    return True


def fmt_cpf(v) -> str:
    d = so_digitos(v or "")
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}" if len(d) == 11 else (v or "")


ERRO_CPF = "CPF inválido. Confira os 11 números."


def nome_proprio(v: str) -> str:
    minusculas = {"da", "de", "do", "das", "dos", "e"}
    partes = re.sub(r"\s+", " ", (v or "").strip()).split(" ")
    return " ".join(p.lower() if p.lower() in minusculas and i > 0 else p[:1].upper() + p[1:].lower()
                    for i, p in enumerate(partes) if p)


def validar(form, exigir_foto: bool = True, exigir_lgpd: bool = True, exigir_cpf: bool = True) -> tuple[dict, dict]:
    """Recebe o formulário e devolve (dados normalizados, erros por campo)."""
    dados: dict = {}
    erros: dict = {}

    for campo in CAMPOS_TEXTO:
        dados[campo] = (form.get(campo) or "").strip()

    for campo, rotulo in OBRIGATORIOS.items():
        if not dados.get(campo) and campo not in ("data_nascimento",):
            erros[campo] = f"{rotulo} é obrigatório."

    dados["nome_completo"] = nome_proprio(dados["nome_completo"])
    if dados["nome_completo"] and len(dados["nome_completo"].split()) < 2:
        erros["nome_completo"] = "Informe nome e sobrenome."
    if dados["conjuge"]:
        dados["conjuge"] = nome_proprio(dados["conjuge"])

    cpf = so_digitos(form.get("cpf") or "")
    if not cpf:
        if exigir_cpf:
            erros["cpf"] = "CPF é obrigatório."
    elif not cpf_valido(cpf):
        erros["cpf"] = ERRO_CPF
    dados["cpf"] = cpf or None

    dados["homenagem_aniversario"] = not form.get("sem_homenagem")  # LGPD: recusa da homenagem de aniversário

    # Dia do Profissional (dd/mm): se ficar vazio, usa a data sugerida pela profissão
    texto_dia = (form.get("dia_profissional") or "").strip()
    dia = profissional.normalizar(texto_dia)
    if texto_dia and not dia:
        erros["dia_profissional"] = "Dia do Profissional inválido (use dd/mm)."
    if not texto_dia:
        sug = profissional.sugerir(dados["profissao"])
        dia = sug[0] if sug else None
    dados["dia_profissional"] = dia
    dados["homenagem_profissional"] = not form.get("sem_homenagem_prof")

    # Intenção de dízimo (opcional; visível só para Secretaria/Adm)
    quer = form.get("deseja_dizimista") or ""
    dados["deseja_dizimista"] = quer if quer in DIZIMO_OPCOES else None
    dados["dia_dizimo"] = None
    if quer in ("Sim", "Já sou dizimista") and (form.get("dia_dizimo") or "").strip():
        try:
            d = int(so_digitos(form.get("dia_dizimo")))
        except ValueError:
            d = 0
        if 1 <= d <= 31:
            dados["dia_dizimo"] = d
        else:
            erros["dia_dizimo"] = "Informe um dia entre 1 e 31."

    nasc = datas.parse_data(form.get("data_nascimento"))
    if not nasc:
        erros["data_nascimento"] = "Data de nascimento inválida (use dd/mm/aaaa)."
    elif nasc > datas.hoje() or nasc.year < 1900:
        erros["data_nascimento"] = "Data de nascimento fora do intervalo permitido."
    dados["data_nascimento"] = nasc

    dados["data_batismo"] = None
    if dados["batizado"] == "Sim":
        bat = datas.parse_data(form.get("data_batismo"))
        if not bat:
            erros["data_batismo"] = "Informe a data do batismo (dd/mm/aaaa)."
        elif bat > datas.hoje():
            erros["data_batismo"] = "A data do batismo não pode ser futura."
        dados["data_batismo"] = bat

    if dados["estado_civil"] in ("Casado(a)", "União Estável") and not dados["conjuge"]:
        erros["conjuge"] = "Informe o nome do cônjuge."
    if dados["congregava_antes"] == "Sim" and not dados["onde_congregava"]:
        erros["onde_congregava"] = "Informe a igreja anterior."

    if dados["email"]:
        dados["email"] = dados["email"].lower()
        if not _RE_EMAIL.match(dados["email"]):
            erros["email"] = "E-mail inválido."

    if dados["whatsapp"] and not telefone_valido(dados["whatsapp"]):
        erros["whatsapp"] = ERRO_TELEFONE
    if dados["telefone"] and not telefone_valido(dados["telefone"]):
        erros["telefone"] = ERRO_TELEFONE
    dados["whatsapp"] = fmt_telefone(dados["whatsapp"])
    dados["telefone"] = fmt_telefone(dados["telefone"])

    if dados["cep"] and len(so_digitos(dados["cep"])) != 8:
        erros["cep"] = "CEP deve ter 8 dígitos."
    dados["cep"] = fmt_cep(dados["cep"])

    # Filhos: JSON montado pelo formulário [{nome, data_nascimento}]
    filhos = []
    try:
        brutos = json.loads(form.get("filhos_json") or "[]")
    except (ValueError, TypeError):
        brutos = []
    for i, f in enumerate(brutos if isinstance(brutos, list) else []):
        nome = nome_proprio(str(f.get("nome", "")))
        if not nome:
            continue
        dn = datas.parse_data(f.get("data_nascimento"))
        if not dn or dn > datas.hoje():
            erros[f"filho_{i}"] = f"Data de nascimento inválida para {nome}."
        filhos.append({"nome": nome, "data_nascimento": datas.fmt_data(dn) if dn else ""})
    dados["filhos"] = filhos

    foto = form.get("foto_3x4") or ""
    if foto and not foto.startswith("data:image/"):
        foto = ""
    if len(foto) > 1_500_000:
        erros["foto_3x4"] = "Foto muito grande. Tente novamente pela câmera ou outra imagem."
    if exigir_foto and not foto:
        erros["foto_3x4"] = "Envie a foto 3x4 (sem óculos) para concluir o cadastro."
    dados["foto_3x4"] = foto or None

    dados["ocr_documento_nome"] = (form.get("ocr_documento_nome") or "")[:200] or None

    if exigir_lgpd and form.get("lgpd_consentimento") != "sim":
        erros["lgpd_consentimento"] = "É necessário aceitar o termo de tratamento de dados (LGPD)."

    return dados, erros
