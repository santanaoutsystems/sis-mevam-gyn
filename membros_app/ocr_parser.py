"""
Módulo OCR & Parser Inteligente de Documentos - SIS MEVAM-GYN
Processa arquivos PDF, imagens (JPG, PNG) e extrai campos cadastrais
para pré-preenchimento automático da Ficha de Membros.
"""

import re
import os
from typing import Dict, Any

try:
    import pymupdf as fitz  # PyMuPDF moderno
    PYMUPDF_AVAILABLE = True
except ImportError:
    try:
        import fitz
        PYMUPDF_AVAILABLE = True
    except ImportError:
        PYMUPDF_AVAILABLE = False


def extrair_texto_pdf(caminho_arquivo: str) -> str:
    """Extrai texto bruto de um PDF usando PyMuPDF."""
    if not PYMUPDF_AVAILABLE:
        return ""
    texto_total = []
    try:
        doc = fitz.open(caminho_arquivo)
        for page in doc:
            texto_total.append(page.get_text())
        doc.close()
    except Exception as e:
        print(f"Erro ao extrair texto do PDF: {e}")
    return "\n".join(texto_total)


def parsear_texto_ficha(texto: str) -> Dict[str, Any]:
    """
    Analisa o texto extraído (OCR ou digital) e mapeia os campos
    da Ficha de Membros e do Credo MEVAM GYN.
    """
    dados = {
        "nome_completo": "",
        "endereco": "",
        "bairro": "",
        "cidade": "Goiânia",
        "cep": "",
        "data_nascimento": "",
        "naturalidade": "",
        "sexo": "",
        "estado_civil": "",
        "conjuge": "",
        "email": "",
        "telefone": "",
        "whatsapp": "",
        "escolaridade": "",
        "formacao_academica": "",
        "profissao": "",
        "empresa": "",
        "batizado": "",
        "data_batismo": "",
        "congregava_antes": "",
        "onde_congregava": "",
        "area_ministerial": "",
        "interesse_batismo_familia": "",
        "filhos": [],
        "confidence_score": 0,
        "campos_identificados": 0,
        "texto_bruto": texto
    }

    if not texto:
        return dados

    # 1. E-mail
    match_email = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', texto)
    if match_email:
        dados["email"] = match_email.group(0)

    # 2. Telefones e WhatsApp
    telefones = re.findall(r'(?:\(?\b\d{2}\)?\s*)?(?:9\s*)?\d{4,5}[-.\s]?\d{4}\b', texto)
    if telefones:
        # Limpar e formatar
        dados["whatsapp"] = telefones[0].strip()
        if len(telefones) > 1:
            dados["telefone"] = telefones[1].strip()
        else:
            dados["telefone"] = telefones[0].strip()

    # 3. CEP
    match_cep = re.search(r'\b\d{5}[-.\s]?\d{3}\b', texto)
    if match_cep:
        dados["cep"] = match_cep.group(0).replace(" ", "-")

    # 4. Datas (Nascimento, Batismo)
    datas = re.findall(r'\b(?:0[1-9]|[12]\d|3[01])[\/\.-](?:0[1-9]|1[0-2])[\/\.-](?:19\d{2}|20\d{2})\b', texto)
    if datas:
        dados["data_nascimento"] = datas[0]
        if len(datas) > 1:
            dados["data_batismo"] = datas[1]

    # 5. Mapeamento por linhas e rótulos
    linhas = [l.strip() for l in texto.split("\n") if l.strip()]
    for i, linha in enumerate(linhas):
        linha_lower = linha.lower()

        # Nome Completo
        if "nome completo" in linha_lower or "nome:" in linha_lower:
            partes = re.split(r'nome\s*(?:completo)?\s*[:\-]', linha, flags=re.IGNORECASE)
            if len(partes) > 1 and partes[1].strip():
                dados["nome_completo"] = partes[1].strip()
            elif i + 1 < len(linhas) and not any(k in linhas[i+1].lower() for k in ["endereço", "cpf", "rg", "nasc"]):
                dados["nome_completo"] = linhas[i+1].strip()

        # Endereço
        if "endereço" in linha_lower or "endereco" in linha_lower:
            partes = re.split(r'endere[çc]o\s*[:\-]', linha, flags=re.IGNORECASE)
            if len(partes) > 1 and partes[1].strip():
                dados["endereco"] = partes[1].strip()

        # Bairro
        if "bairro" in linha_lower:
            partes = re.split(r'bairro\s*[:\-]', linha, flags=re.IGNORECASE)
            if len(partes) > 1 and partes[1].strip():
                dados["bairro"] = partes[1].strip().split("Cidade")[0].strip()

        # Cidade
        if "cidade" in linha_lower:
            partes = re.split(r'cidade\s*[:\-]', linha, flags=re.IGNORECASE)
            if len(partes) > 1 and partes[1].strip():
                dados["cidade"] = partes[1].strip().split("CEP")[0].strip()

        # Naturalidade
        if "naturalidade" in linha_lower:
            partes = re.split(r'naturalidade\s*[:\-]', linha, flags=re.IGNORECASE)
            if len(partes) > 1 and partes[1].strip():
                dados["naturalidade"] = partes[1].strip()

        # Sexo
        if "masc" in linha_lower or "fem" in linha_lower or "sexo" in linha_lower:
            if "masc" in linha_lower and "fem" not in linha_lower:
                dados["sexo"] = "Masc."
            elif "fem" in linha_lower and "masc" not in linha_lower:
                dados["sexo"] = "Fem."
            elif "(x) masc" in linha_lower or "(x)masc" in linha_lower or "[x] masc" in linha_lower:
                dados["sexo"] = "Masc."
            elif "(x) fem" in linha_lower or "(x)fem" in linha_lower or "[x] fem" in linha_lower:
                dados["sexo"] = "Fem."

        # Estado Civil
        for ec in ["Casado", "Casada", "Solteiro", "Solteira", "Divorciado", "Divorciada", "Viúvo", "Viúva", "União Estável"]:
            if ec.lower() in linha_lower:
                dados["estado_civil"] = ec
                break

        # Cônjuge
        if "cônjuge" in linha_lower or "conjuge" in linha_lower:
            partes = re.split(r'c[ôo]njuge\s*[:\-]', linha, flags=re.IGNORECASE)
            if len(partes) > 1 and partes[1].strip():
                dados["conjuge"] = partes[1].strip()

        # Profissão
        if "profissão" in linha_lower or "profissao" in linha_lower:
            partes = re.split(r'profiss[ãa]o\s*[:\-]', linha, flags=re.IGNORECASE)
            if len(partes) > 1 and partes[1].strip():
                dados["profissao"] = partes[1].strip()

        # Empresa
        if "empresa" in linha_lower:
            partes = re.split(r'empresa\s*(?:que trabalha)?\s*[:\-]', linha, flags=re.IGNORECASE)
            if len(partes) > 1 and partes[1].strip():
                dados["empresa"] = partes[1].strip()

        # Escolaridade
        if "escolaridade" in linha_lower:
            partes = re.split(r'escolaridade\s*[:\-]', linha, flags=re.IGNORECASE)
            if len(partes) > 1 and partes[1].strip():
                dados["escolaridade"] = partes[1].strip()

        # Batizado
        if "batizado" in linha_lower:
            if "sim" in linha_lower and "não" not in linha_lower:
                dados["batizado"] = "Sim"
            elif "(x) sim" in linha_lower or "[x] sim" in linha_lower:
                dados["batizado"] = "Sim"
            elif "(x) não" in linha_lower or "[x] não" in linha_lower:
                dados["batizado"] = "Não"

        # Congregava antes
        if "congregava antes" in linha_lower:
            if "sim" in linha_lower and "não" not in linha_lower:
                dados["congregava_antes"] = "Sim"
            elif "(x) sim" in linha_lower or "[x] sim" in linha_lower:
                dados["congregava_antes"] = "Sim"
            elif "(x) não" in linha_lower or "[x] não" in linha_lower:
                dados["congregava_antes"] = "Não"

        # Onde
        if "onde?" in linha_lower or "onde congregava" in linha_lower:
            partes = re.split(r'onde\??\s*[:\-]', linha, flags=re.IGNORECASE)
            if len(partes) > 1 and partes[1].strip():
                dados["onde_congregava"] = partes[1].strip()

        # Área ministerial
        if "área ministerial" in linha_lower or "area ministerial" in linha_lower:
            partes = re.split(r'[áa]rea ministerial\s*(?:que j[áa] praticou antes)?\s*[:\-]', linha, flags=re.IGNORECASE)
            if len(partes) > 1 and partes[1].strip():
                dados["area_ministerial"] = partes[1].strip()

        # Interesse de batizar
        if "interesse de se batizar" in linha_lower:
            partes = re.split(r'interesse de se batizar[^\:]*[:\-]?', linha, flags=re.IGNORECASE)
            if len(partes) > 1 and partes[1].strip():
                dados["interesse_batismo_familia"] = partes[1].strip()

    # Cálculo de métricas de acurácia
    campos_chave = ["nome_completo", "email", "whatsapp", "data_nascimento", "endereco", "bairro", "cep", "profissao", "estado_civil"]
    detectados = sum(1 for k in campos_chave if dados[k])
    dados["campos_identificados"] = detectados
    dados["confidence_score"] = round((detectados / len(campos_chave)) * 100)

    return dados
