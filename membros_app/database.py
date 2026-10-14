"""
Módulo de Banco de Dados - SIS MEVAM-GYN (Membros & Credo)
Gerencia persistência em SQLite (igreja.db) com suporte e fallback
e integração com Supabase se configurado.
"""

import sqlite3
import json
import hashlib
from datetime import datetime
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "igreja.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS membros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_registro TEXT,
            nome_completo TEXT NOT NULL,
            endereco TEXT,
            bairro TEXT,
            cidade TEXT,
            cep TEXT,
            data_nascimento TEXT,
            naturalidade TEXT,
            sexo TEXT,
            estado_civil TEXT,
            conjuge TEXT,
            filhos_json TEXT,
            email TEXT,
            telefone TEXT,
            whatsapp TEXT,
            escolaridade TEXT,
            formacao_academica TEXT,
            profissao TEXT,
            empresa TEXT,
            batizado TEXT,
            data_batismo TEXT,
            congregava_antes TEXT,
            onde_congregava TEXT,
            area_ministerial TEXT,
            interesse_batismo_familia TEXT,
            
            -- Confissão de Fé & Aceite
            credo_aceito INTEGER DEFAULT 1,
            nome_assinante TEXT,
            assinatura_rubrica TEXT,
            data_assinatura TEXT,
            hash_autenticidade TEXT,
            
            -- OCR e Documento Anexo
            ocr_documento_nome TEXT,
            ocr_raw_text TEXT,
            
            -- Controle ERP
            status TEXT DEFAULT 'Ativo',
            observacoes TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def gerar_hash_auditoria(nome, data_assinatura, assinatura_rubrica):
    conteudo = f"{nome}|{data_assinatura}|{assinatura_rubrica[:100] if assinatura_rubrica else ''}|MEVAM_GYN_SALT_2026"
    return hashlib.sha256(conteudo.encode('utf-8')).hexdigest()

def cadastrar_membro(dados: dict) -> int:
    init_db()
    conn = get_connection()
    cursor = conn.cursor()

    data_registro = dados.get("data_registro") or datetime.now().strftime("%d/%m/%Y")
    data_assinatura = dados.get("data_assinatura") or datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    nome_assinante = dados.get("nome_assinante") or dados.get("nome_completo", "")
    assinatura_rubrica = dados.get("assinatura_rubrica", "")
    hash_auth = gerar_hash_auditoria(nome_assinante, data_assinatura, assinatura_rubrica)

    filhos_json = json.dumps(dados.get("filhos", []), ensure_ascii=False)

    cursor.execute('''
        INSERT INTO membros (
            data_registro, nome_completo, endereco, bairro, cidade, cep,
            data_nascimento, naturalidade, sexo, estado_civil, conjuge,
            filhos_json, email, telefone, whatsapp, escolaridade,
            formacao_academica, profissao, empresa, batizado, data_batismo,
            congregava_antes, onde_congregava, area_ministerial,
            interesse_batismo_familia, credo_aceito, nome_assinante,
            assinatura_rubrica, data_assinatura, hash_autenticidade,
            ocr_documento_nome, ocr_raw_text, status, observacoes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        data_registro,
        dados.get("nome_completo", "").strip(),
        dados.get("endereco", "").strip(),
        dados.get("bairro", "").strip(),
        dados.get("cidade", "Goiânia").strip(),
        dados.get("cep", "").strip(),
        dados.get("data_nascimento", "").strip(),
        dados.get("naturalidade", "").strip(),
        dados.get("sexo", "Masc.").strip(),
        dados.get("estado_civil", "Solteiro(a)").strip(),
        dados.get("conjuge", "").strip(),
        filhos_json,
        dados.get("email", "").strip(),
        dados.get("telefone", "").strip(),
        dados.get("whatsapp", "").strip(),
        dados.get("escolaridade", "").strip(),
        dados.get("formacao_academica", "").strip(),
        dados.get("profissao", "").strip(),
        dados.get("empresa", "").strip(),
        dados.get("batizado", "Não").strip(),
        dados.get("data_batismo", "").strip(),
        dados.get("congregava_antes", "Não").strip(),
        dados.get("onde_congregava", "").strip(),
        dados.get("area_ministerial", "").strip(),
        dados.get("interesse_batismo_familia", "Não").strip(),
        1 if dados.get("credo_aceito", True) else 0,
        nome_assinante.strip(),
        assinatura_rubrica,
        data_assinatura,
        hash_auth,
        dados.get("ocr_documento_nome", ""),
        dados.get("ocr_raw_text", ""),
        dados.get("status", "Ativo"),
        dados.get("observacoes", "")
    ))

    novo_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return novo_id

def listar_membros(busca: str = "", status: str = "", limit: int = 200):
    init_db()
    conn = get_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM membros WHERE 1=1"
    params = []

    if busca:
        busca_term = f"%{busca}%"
        query += " AND (nome_completo LIKE ? OR email LIKE ? OR whatsapp LIKE ? OR telefone LIKE ? OR bairro LIKE ?)"
        params.extend([busca_term, busca_term, busca_term, busca_term, busca_term])

    if status and status != "Todos":
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    resultado = []
    for r in rows:
        d = dict(r)
        try:
            d["filhos"] = json.loads(d.get("filhos_json") or "[]")
        except:
            d["filhos"] = []
        resultado.append(d)
    return resultado

def obter_membro_por_id(membro_id: int):
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM membros WHERE id = ?", (membro_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    try:
        d["filhos"] = json.loads(d.get("filhos_json") or "[]")
    except:
        d["filhos"] = []
    return d

def excluir_membro(membro_id: int):
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM membros WHERE id = ?", (membro_id,))
    conn.commit()
    conn.close()
    return True

def obter_estatisticas():
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    
    total = cursor.execute("SELECT COUNT(*) FROM membros").fetchone()[0]
    batizados = cursor.execute("SELECT COUNT(*) FROM membros WHERE batizado = 'Sim'").fetchone()[0]
    interesse_batismo = cursor.execute("SELECT COUNT(*) FROM membros WHERE interesse_batismo_familia LIKE '%Sim%'").fetchone()[0]
    com_assinatura = cursor.execute("SELECT COUNT(*) FROM membros WHERE assinatura_rubrica IS NOT NULL AND assinatura_rubrica != ''").fetchone()[0]
    
    # Agrupamento por área ministerial
    areas_cursor = cursor.execute("SELECT area_ministerial, COUNT(*) as qtd FROM membros WHERE area_ministerial != '' GROUP BY area_ministerial ORDER BY qtd DESC LIMIT 5").fetchall()
    areas = [{"area": a[0], "total": a[1]} for a in areas_cursor]

    conn.close()
    return {
        "total_membros": total,
        "batizados": batizados,
        "nao_batizados": total - batizados,
        "interesse_batismo": interesse_batismo,
        "com_assinatura": com_assinatura,
        "areas_principais": areas
    }
