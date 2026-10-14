"""
Módulo de Autenticação, Criptografia e Segurança de Sessão
Em conformidade com as melhores práticas de segurança e LGPD (Lei 13.709/2018).
"""

import os
import hmac
import hashlib
import json
import base64
import time
from typing import Optional, Tuple, Dict, Any

# Chave secreta de assinatura de tokens de sessão (pode ser sobrescrita por variável de ambiente na nuvem)
SECRET_KEY = os.getenv("SECRET_KEY", "MEVAM_GYN_SUPER_SECRET_SESSION_KEY_2026_SECURE_AUTH").encode('utf-8')
SESSION_DURATION_SECONDS = 60 * 60 * 24 * 7  # 7 dias de validade da sessão


# ==============================================================================
# CRIPTOGRAFIA DE SENHAS (PBKDF2-HMAC-SHA256 COM SALT INDIVIDUAL)
# ==============================================================================
def gerar_salt() -> str:
    """Gera um salt criptográfico aleatório de 16 bytes em hexadecimal."""
    return os.urandom(16).hex()


def hash_senha(senha: str, salt: Optional[str] = None) -> Tuple[str, str]:
    """
    Gera o hash seguro da senha usando PBKDF2 com 100.000 iterações de SHA-256.
    Retorna a tupla (senha_hash_hex, salt_hex).
    """
    if not salt:
        salt = gerar_salt()
    
    hash_bytes = hashlib.pbkdf2_hmac(
        'sha256',
        senha.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    )
    return hash_bytes.hex(), salt


def verificar_senha(senha: str, senha_hash: str, salt: str) -> bool:
    """Valida se a senha fornecida confere com o hash armazenado de forma segura contra timing attacks."""
    novo_hash, _ = hash_senha(senha, salt)
    return hmac.compare_digest(novo_hash, senha_hash)


# ==============================================================================
# GESTÃO DE TOKENS DE SESSÃO ASSINADOS (HMAC-SHA256 - SEM DEPENDÊNCIAS EXTERNAS)
# ==============================================================================
def base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode('utf-8').rstrip('=')


def base64url_decode(data_str: str) -> bytes:
    padding = '=' * (4 - (len(data_str) % 4)) if len(data_str) % 4 != 0 else ''
    return base64.urlsafe_b64decode(data_str + padding)


def criar_token_sessao(usuario: Dict[str, Any]) -> str:
    """Cria um token assinado contendo dados do usuário e expiração."""
    payload = {
        "sub": usuario.get("id"),
        "nome": usuario.get("nome"),
        "email": usuario.get("email"),
        "perfil": usuario.get("perfil", "membro"),
        "exp": int(time.time()) + SESSION_DURATION_SECONDS
    }
    
    payload_json = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    payload_b64 = base64url_encode(payload_json)
    
    assinatura = hmac.new(SECRET_KEY, payload_b64.encode('utf-8'), hashlib.sha256).digest()
    assinatura_b64 = base64url_encode(assinatura)
    
    return f"{payload_b64}.{assinatura_b64}"


def verificar_token_sessao(token: str) -> Optional[Dict[str, Any]]:
    """Verifica a integridade e expiração do token de sessão. Retorna o payload se válido."""
    if not token or "." not in token:
        return None
    
    try:
        payload_b64, assinatura_b64 = token.split(".", 1)
        assinatura_esperada = hmac.new(SECRET_KEY, payload_b64.encode('utf-8'), hashlib.sha256).digest()
        assinatura_recebida = base64url_decode(assinatura_b64)
        
        if not hmac.compare_digest(assinatura_esperada, assinatura_recebida):
            return None
        
        payload_bytes = base64url_decode(payload_b64)
        payload = json.loads(payload_bytes.decode('utf-8'))
        
        # Validar expiração
        if payload.get("exp", 0) < time.time():
            return None
            
        return payload
    except Exception:
        return None


def obter_ip_cliente(request) -> str:
    """Obtém o IP real do cliente mesmo atrás de proxies ou load balancers (ex: Render, Cloudflare)."""
    # 1. Cabeçalhos de proxy reverso
    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    
    x_real_ip = request.headers.get("x-real-ip")
    if x_real_ip:
        return x_real_ip.strip()
    
    # 2. IP do cliente direto
    if request.client and request.client.host:
        return request.client.host
    
    return "127.0.0.1"


def obter_usuario_da_requisicao(request) -> Optional[Dict[str, Any]]:
    """
    Identifica o usuário atual a partir do cookie HTTP-Only 'mevam_session'
    ou do cabeçalho 'Authorization: Bearer <token>'.
    """
    token = request.cookies.get("mevam_session")
    
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1].strip()
            
    if not token:
        return None
        
    return verificar_token_sessao(token)
