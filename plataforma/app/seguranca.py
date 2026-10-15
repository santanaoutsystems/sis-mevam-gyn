"""
Segurança: senhas, sessão, perfis de acesso, CSRF e tokens de link.
"""

from __future__ import annotations

import functools
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque

from sqlalchemy import select
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from . import config, db

ITERACOES_PADRAO = 600_000  # PBKDF2-HMAC-SHA256 (recomendação OWASP 2023+)
SENHA_MIN = 8


# ---------------------------------------------------------------------------
# Senhas
# ---------------------------------------------------------------------------
def hash_senha(senha: str, salt: str | None = None, iteracoes: int = ITERACOES_PADRAO) -> tuple[str, str, int]:
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), salt.encode("utf-8"), iteracoes)
    return h.hex(), salt, iteracoes


def verificar_senha(senha: str, senha_hash: str, salt: str, iteracoes: int) -> bool:
    calculado, _, _ = hash_senha(senha, salt, iteracoes)
    return hmac.compare_digest(calculado, senha_hash)


def validar_forca_senha(senha: str) -> str | None:
    """Retorna mensagem de erro ou None se a senha é aceitável."""
    if len(senha) < SENHA_MIN:
        return f"A senha precisa ter pelo menos {SENHA_MIN} caracteres."
    if senha.lower() == senha or senha.upper() == senha or not any(c.isdigit() for c in senha):
        return "Use letras maiúsculas, minúsculas e pelo menos um número."
    return None


def senha_temporaria() -> str:
    """Senha provisória legível para o admin repassar (o usuário troca no primeiro acesso)."""
    alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
    base = "".join(secrets.choice(alfabeto) for _ in range(10))
    return base[:5] + "-" + base[5:] + secrets.choice("23456789")


# ---------------------------------------------------------------------------
# Tokens assinados (links do Credo enviados por WhatsApp)
# ---------------------------------------------------------------------------
def token_link(finalidade: str, ident: int | str) -> str:
    msg = f"{finalidade}:{ident}".encode()
    return hmac.new(config.SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()[:32]


def conferir_token_link(finalidade: str, ident: int | str, token: str | None) -> bool:
    return bool(token) and hmac.compare_digest(token_link(finalidade, ident), token)


# ---------------------------------------------------------------------------
# CSRF (token por sessão, conferido em todo POST)
# ---------------------------------------------------------------------------
def csrf_token(request: Request) -> str:
    tok = request.session.get("csrf")
    if not tok:
        tok = secrets.token_urlsafe(32)
        request.session["csrf"] = tok
    return tok


async def conferir_csrf(request: Request) -> bool:
    esperado = request.session.get("csrf")
    if not esperado:
        return False
    recebido = request.headers.get("x-csrf-token")
    if not recebido:
        form = await request.form()
        recebido = form.get("csrf")
    return bool(recebido) and hmac.compare_digest(str(recebido), esperado)


# ---------------------------------------------------------------------------
# Limite de tentativas por IP (complementa o bloqueio por conta no banco)
# ---------------------------------------------------------------------------
_tentativas_ip: dict[str, deque] = defaultdict(deque)
JANELA_IP_SEG = 15 * 60
MAX_POR_IP = 20


def ip_bloqueado(ip: str) -> bool:
    agora = time.monotonic()
    fila = _tentativas_ip[ip]
    while fila and agora - fila[0] > JANELA_IP_SEG:
        fila.popleft()
    return len(fila) >= MAX_POR_IP


def registrar_falha_ip(ip: str) -> None:
    _tentativas_ip[ip].append(time.monotonic())


def limpar_falhas_ip(ip: str | None = None) -> None:
    if ip is None:
        _tentativas_ip.clear()
    else:
        _tentativas_ip.pop(ip, None)


# ---------------------------------------------------------------------------
# Sessão e perfis
# ---------------------------------------------------------------------------
def ip_cliente(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else ""


def limite_inatividade(usuario: dict | None) -> int:
    """Segundos sem uso até o acesso ser bloqueado."""
    if usuario and usuario.get("perfil") in ("secretaria", "admin"):
        return config.INATIVIDADE_MIN_GESTAO * 60
    return config.INATIVIDADE_MIN_PADRAO * 60


def usuario_atual(request: Request) -> dict | None:
    """Relê o usuário no banco a cada requisição: desativar ou trocar o perfil vale na hora."""
    if hasattr(request.state, "usuario"):
        return request.state.usuario
    uid = request.session.get("uid")
    usuario = None
    if uid:
        agora = time.time()
        inicio = request.session.get("inicio", 0)
        if agora - inicio <= config.SESSAO_MAX_SEGUNDOS:
            with db.engine().connect() as c:
                row = c.execute(select(db.usuarios).where(db.usuarios.c.id == uid)).mappings().first()
            if row and row["ativo"] and row["senha_hash"] and request.session.get("ver") == row["senha_hash"][:12]:
                usuario = dict(row)
        if usuario is not None:
            ultimo = request.session.get("ultimo", inicio)
            if agora - ultimo > limite_inatividade(usuario):
                usuario = None
                request.state.expirou = True
            elif agora - ultimo >= 30:  # renova sem regravar o cookie a cada clique
                request.session["ultimo"] = int(agora)
        else:
            request.state.expirou = True
        if usuario is None:
            request.session.clear()
    request.state.usuario = usuario
    return usuario


def iniciar_sessao(request: Request, usuario: dict) -> None:
    csrf = request.session.get("csrf")
    request.session.clear()
    request.session.update({
        "uid": usuario["id"],
        "inicio": int(time.time()),
        "ultimo": int(time.time()),
        # Trocar a senha invalida as sessões antigas
        "ver": usuario["senha_hash"][:12],
        "csrf": csrf or secrets.token_urlsafe(32),
    })


def exigir(*perfis: str):
    """Decorator de rota: exige login e (opcionalmente) um dos perfis informados."""
    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(request: Request, *args, **kwargs) -> Response:
            u = usuario_atual(request)
            if not u:
                destino = request.url.path
                aviso = "&expirou=1" if getattr(request.state, "expirou", False) else ""
                return RedirectResponse(f"/entrar?proximo={destino}{aviso}", status_code=303)
            if u["trocar_senha"] and request.url.path not in ("/trocar-senha", "/sair"):
                return RedirectResponse("/trocar-senha", status_code=303)
            if perfis and u["perfil"] not in perfis:
                from .web import render
                return render(request, "erro.html", {"titulo": "Acesso restrito",
                              "mensagem": "Seu perfil não tem permissão para esta área."}, status_code=403)
            if request.method == "POST" and not await conferir_csrf(request):
                from .web import render
                return render(request, "erro.html", {"titulo": "Formulário expirado",
                              "mensagem": "Recarregue a página e tente novamente."}, status_code=400)
            return await fn(request, *args, **kwargs)
        return wrapper
    return deco


def pode(usuario: dict | None, *perfis: str) -> bool:
    return bool(usuario) and usuario["perfil"] in perfis
