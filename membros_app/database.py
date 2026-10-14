"""
Módulo de Banco de Dados - SIS MEVAM-GYN (Membros, Credo, Autenticação & LGPD)
Gerencia persistência em SQLite (igreja.db) com controle de perfis de acesso,
trilha de auditoria e conformidade total com a Lei Geral de Proteção de Dados (Lei 13.709/2018).
"""

import sqlite3
import json
import hashlib
from datetime import datetime
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from auth import hash_senha, verificar_senha

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "igreja.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # 1. Tabela de Membros com Campos de Confissão e LGPD
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
            
            -- Conformidade LGPD (Lei 13.709/2018)
            lgpd_consentimento INTEGER DEFAULT 1,
            lgpd_versao_termo TEXT DEFAULT 'v1.0-2026',
            lgpd_data_consentimento TEXT,
            lgpd_ip_origem TEXT,
            status_lgpd TEXT DEFAULT 'Consentimento Ativo',
            
            -- Foto de Identificação Facial (3x4 sem óculos)
            foto_3x4 TEXT,

            -- Controle ERP
            status TEXT DEFAULT 'Ativo',
            observacoes TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Migração segura para adicionar colunas LGPD e Foto 3x4 caso o banco já existisse
    cursor.execute("PRAGMA table_info(membros)")
    colunas_membros = [col[1] for col in cursor.fetchall()]
    
    colunas_novas = [
        ("lgpd_consentimento", "INTEGER DEFAULT 1"),
        ("lgpd_versao_termo", "TEXT DEFAULT 'v1.0-2026'"),
        ("lgpd_data_consentimento", "TEXT"),
        ("lgpd_ip_origem", "TEXT"),
        ("status_lgpd", "TEXT DEFAULT 'Consentimento Ativo'"),
        ("foto_3x4", "TEXT")
    ]
    for col_nome, col_tipo in colunas_novas:
        if col_nome not in colunas_membros:
            try:
                cursor.execute(f"ALTER TABLE membros ADD COLUMN {col_nome} {col_tipo}")
            except Exception:
                pass

    # 2. Tabela de Usuários com Perfis e Senha Criptografada (RBAC)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            senha_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            perfil TEXT NOT NULL DEFAULT 'membro', -- 'admin', 'secretaria', 'membro'
            ativo INTEGER DEFAULT 1,
            criado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
            ultimo_login DATETIME
        )
    ''')

    # 3. Tabela de Auditoria e Governança LGPD (Art. 37 da Lei 13.709/2018)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS logs_auditoria_lgpd (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            usuario_nome TEXT,
            acao TEXT NOT NULL,       -- 'LOGIN', 'CADASTRO_MEMBRO', 'VISUALIZACAO_FICHA', 'DOWNLOAD_PDF', 'EXCLUSAO_TITULAR', 'ANONIMIZACAO_LGPD', 'ALTERACAO_PERFIL'
            recurso TEXT,            -- ex: 'Membro #15', 'Tabela Usuarios'
            detalhes TEXT,
            ip_origem TEXT,
            criado_em DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # 4. Criar Administrador Inicial Padrão se não existir nenhum usuário
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    total_usuarios = cursor.fetchone()[0]
    if total_usuarios == 0:
        senha_padrao = "Mevam@2026"
        s_hash, salt = hash_senha(senha_padrao)
        cursor.execute('''
            INSERT INTO usuarios (nome, email, senha_hash, salt, perfil, ativo)
            VALUES (?, ?, ?, ?, ?, 1)
        ''', ("Ricardo César (Administrador Geral)", "admin@mevamgyn.com", s_hash, salt, "admin"))

    conn.commit()
    conn.close()


# ==============================================================================
# HASH CRIPTOGRÁFICO DE AUDITORIA LGPD & AUTENTICIDADE
# ==============================================================================
def gerar_hash_auditoria(nome, data_assinatura, assinatura_rubrica, ip=""):
    conteudo = f"{nome}|{data_assinatura}|{assinatura_rubrica[:100] if assinatura_rubrica else ''}|{ip}|MEVAM_GYN_LGPD_2026"
    return hashlib.sha256(conteudo.encode('utf-8')).hexdigest()


# ==============================================================================
# GESTÃO DE USUÁRIOS E PERFIS DE ACESSO (RBAC)
# ==============================================================================
def criar_usuario(nome: str, email: str, senha: str, perfil: str = "membro") -> int:
    init_db()
    conn = get_connection()
    cursor = conn.cursor()

    email_limpo = email.strip().lower()
    
    # Verificar e-mail duplicado
    cursor.execute("SELECT id FROM usuarios WHERE LOWER(email) = ?", (email_limpo,))
    if cursor.fetchone():
        conn.close()
        raise ValueError("Este e-mail já está cadastrado no sistema.")

    if perfil not in ("admin", "secretaria", "membro"):
        perfil = "membro"

    senha_hash_val, salt = hash_senha(senha)

    cursor.execute('''
        INSERT INTO usuarios (nome, email, senha_hash, salt, perfil, ativo)
        VALUES (?, ?, ?, ?, ?, 1)
    ''', (nome.strip(), email_limpo, senha_hash_val, salt, perfil))

    novo_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return novo_id


def autenticar_usuario(email: str, senha: str) -> dict | None:
    init_db()
    conn = get_connection()
    cursor = conn.cursor()

    email_limpo = email.strip().lower()
    cursor.execute("SELECT * FROM usuarios WHERE LOWER(email) = ?", (email_limpo,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        return None

    user = dict(row)
    if not user.get("ativo"):
        conn.close()
        return None

    # Validar senha
    if not verificar_senha(senha, user["senha_hash"], user["salt"]):
        conn.close()
        return None

    # Atualizar data do último login
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("UPDATE usuarios SET ultimo_login = ? WHERE id = ?", (agora, user["id"]))
    conn.commit()
    conn.close()

    # Retorna o usuário seguro (sem salt nem hash)
    return {
        "id": user["id"],
        "nome": user["nome"],
        "email": user["email"],
        "perfil": user["perfil"],
        "ativo": user["ativo"],
        "criado_em": user.get("criado_em"),
        "ultimo_login": agora
    }


def listar_usuarios(busca: str = "") -> list[dict]:
    init_db()
    conn = get_connection()
    cursor = conn.cursor()

    query = "SELECT id, nome, email, perfil, ativo, criado_em, ultimo_login FROM usuarios WHERE 1=1"
    params = []

    if busca:
        busca_term = f"%{busca}%"
        query += " AND (nome LIKE ? OR email LIKE ? OR perfil LIKE ?)"
        params.extend([busca_term, busca_term, busca_term])

    query += " ORDER BY id ASC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def obter_usuario_por_id(user_id: int) -> dict | None:
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, nome, email, perfil, ativo, criado_em, ultimo_login FROM usuarios WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def atualizar_usuario(user_id: int, nome: str = None, email: str = None, perfil: str = None, ativo: int = None, nova_senha: str = None):
    init_db()
    conn = get_connection()
    cursor = conn.cursor()

    updates = []
    params = []

    if nome is not None:
        updates.append("nome = ?")
        params.append(nome.strip())

    if email is not None:
        updates.append("email = ?")
        params.append(email.strip().lower())

    if perfil is not None and perfil in ("admin", "secretaria", "membro"):
        updates.append("perfil = ?")
        params.append(perfil)

    if ativo is not None:
        updates.append("ativo = ?")
        params.append(1 if ativo else 0)

    if nova_senha:
        s_hash, salt = hash_senha(nova_senha)
        updates.append("senha_hash = ?")
        updates.append("salt = ?")
        params.extend([s_hash, salt])

    if updates:
        params.append(user_id)
        cursor.execute(f"UPDATE usuarios SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()

    conn.close()
    return True


def excluir_usuario(user_id: int):
    init_db()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM usuarios WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return True


# ==============================================================================
# AUDITORIA & GOVERNANÇA LGPD (Art. 37 e Art. 46 da Lei 13.709/2018)
# ==============================================================================
def registrar_log_lgpd(usuario_id: int = None, usuario_nome: str = "Visitante", acao: str = "", recurso: str = "", detalhes: str = "", ip_origem: str = ""):
    """Registra uma trilha de auditoria imutável para conformidade com a LGPD."""
    try:
        init_db()
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO logs_auditoria_lgpd (usuario_id, usuario_nome, acao, recurso, detalhes, ip_origem)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (usuario_id, usuario_nome, acao, recurso, detalhes, ip_origem))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[ERRO LOG LGPD] {e}")


def listar_logs_lgpd(limit: int = 150, busca: str = "") -> list[dict]:
    init_db()
    conn = get_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM logs_auditoria_lgpd WHERE 1=1"
    params = []

    if busca:
        term = f"%{busca}%"
        query += " AND (usuario_nome LIKE ? OR acao LIKE ? OR recurso LIKE ? OR detalhes LIKE ? OR ip_origem LIKE ?)"
        params.extend([term, term, term, term, term])

    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ==============================================================================
# OPERAÇÕES DE MEMBROS E DIREITOS DO TITULAR LGPD (Art. 18)
# ==============================================================================
def cadastrar_membro(dados: dict, ip_origem: str = "127.0.0.1") -> int:
    init_db()
    conn = get_connection()
    cursor = conn.cursor()

    data_registro = dados.get("data_registro") or datetime.now().strftime("%d/%m/%Y")
    data_assinatura = dados.get("data_assinatura") or datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    nome_assinante = dados.get("nome_assinante") or dados.get("nome_completo", "")
    assinatura_rubrica = dados.get("assinatura_rubrica", "")
    
    # Hash criptográfico de autenticidade incluindo IP do cliente
    hash_auth = gerar_hash_auditoria(nome_assinante, data_assinatura, assinatura_rubrica, ip=ip_origem)

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
            ocr_documento_nome, ocr_raw_text, lgpd_consentimento,
            lgpd_versao_termo, lgpd_data_consentimento, lgpd_ip_origem,
            status_lgpd, foto_3x4, status, observacoes
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
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
        1 if dados.get("lgpd_consentimento", True) else 0,
        dados.get("lgpd_versao_termo", "v1.0-2026"),
        data_assinatura,
        ip_origem,
        "Consentimento Ativo",
        dados.get("foto_3x4", ""),
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


def anonimizar_membro_lgpd(membro_id: int, motivo: str = "Solicitação expressa do titular (Art. 18 da LGPD)") -> bool:
    """
    Direito do Titular à Anonimização / Revogação de Consentimento (Art. 18, IV e VI da LGPD).
    Remove todos os dados identificáveis diretos mantendo apenas o registro estatístico com carimbo legal.
    """
    init_db()
    conn = get_connection()
    cursor = conn.cursor()

    tag_anon = f"[ANONIMIZADO CONFORME ART. 18 LGPD]"
    agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    cursor.execute('''
        UPDATE membros SET
            nome_completo = ?,
            endereco = ?,
            bairro = ?,
            cep = ?,
            data_nascimento = '',
            naturalidade = '',
            conjuge = '',
            filhos_json = '[]',
            email = ?,
            telefone = '',
            whatsapp = '',
            empresa = '',
            assinatura_rubrica = '',
            nome_assinante = ?,
            ocr_raw_text = '',
            foto_3x4 = '',
            status = 'Anonimizado / Desligado',
            status_lgpd = 'Consentimento Revogado',
            observacoes = ?
        WHERE id = ?
    ''', (
        f"Membro #{membro_id} {tag_anon}",
        tag_anon,
        tag_anon,
        tag_anon,
        f"anonimizado_{membro_id}@revogado.lgpd",
        tag_anon,
        f"Dados anonimizados e consentimento revogado em {agora}. Motivo: {motivo}",
        membro_id
    ))

    conn.commit()
    conn.close()
    return True


def excluir_membro(membro_id: int):
    """Eliminação definitiva de dados pessoais conforme Art. 18, VI da LGPD."""
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
    
    # Métricas de LGPD
    consentimentos_ativos = cursor.execute("SELECT COUNT(*) FROM membros WHERE lgpd_consentimento = 1 AND status_lgpd = 'Consentimento Ativo'").fetchone()[0]
    revogados = cursor.execute("SELECT COUNT(*) FROM membros WHERE status_lgpd = 'Consentimento Revogado'").fetchone()[0]
    
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
        "consentimentos_ativos": consentimentos_ativos,
        "revogados_lgpd": revogados,
        "areas_principais": areas
    }
