"""
SIS MEVAM-GYN — Plataforma Unificada (Membros + Agenda + Administração).

Execução local:
    cd plataforma && uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
import os

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.middleware.gzip import GZipMiddleware
from starlette.staticfiles import StaticFiles

from . import config, datas, db, lembretes, seguranca
from .rotas import acesso, admin, agenda, membros, pesquisa, regularizacao, relatorios, voluntarios
from .web import BASE, render

CSP = ("default-src 'self'; "
       "script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
       "worker-src 'self' blob: https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
       "style-src 'self' 'unsafe-inline'; "
       "font-src 'self'; "
       "img-src 'self' data: blob:; "
       "connect-src 'self' https://viacep.com.br https://cdn.jsdelivr.net https://tessdata.projectnaptha.com data: blob:; "
       "frame-ancestors 'none'; base-uri 'self'; form-action 'self'")


class CabecalhosSeguranca(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("Content-Security-Policy", CSP)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(self), geolocation=()")
        if config.COOKIE_SEGURO:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.url.path.startswith(("/static/fonts/", "/static/img/")):
            resp.headers.setdefault("Cache-Control", "public, max-age=2592000")  # 30 dias: não mudam
        elif request.url.path.startswith("/static/"):
            resp.headers.setdefault("Cache-Control", "no-cache")  # CSS/JS: confere versão a cada visita (ETag)
        if request.url.path.startswith(("/membros", "/minha-ficha", "/admin", "/credo", "/relatorios", "/voluntarios")):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp


async def healthz(request: Request):
    lembretes.agendar()  # o UptimeRobot chama a cada 5 min: serve de agendador dos lembretes de cadastro
    return JSONResponse({"status": "ok", "app": "SIS MEVAM-GYN", "versao": config.VERSAO_APP,
                         "hora_gyn": datas.agora().strftime("%d/%m/%Y %H:%M")})


async def privacidade(request: Request):
    return render(request, "publico/privacidade.html")


async def service_worker(request: Request):
    return FileResponse(os.path.join(BASE, "static", "sw.js"), media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/"})


async def nao_encontrado(request: Request, exc):
    return render(request, "erro.html", {"titulo": "Página não encontrada",
                                         "mensagem": "O endereço acessado não existe."}, status_code=404)


async def erro_interno(request: Request, exc):
    logging.getLogger("mevam").error("Erro em %s %s", request.method, request.url.path, exc_info=exc)
    ctx = {"titulo": "Algo deu errado", "mensagem": "Tente novamente. Se persistir, avise a Secretaria."}
    try:
        u = seguranca.usuario_atual(request)
    except Exception:
        u = None
    if u and u.get("perfil") == "admin":
        # Só o Adm vê o detalhe técnico, para repassar ao suporte
        ctx["detalhe"] = f"{type(exc).__name__}: {str(exc).splitlines()[0][:400] if str(exc) else ''}"
    return render(request, "erro.html", ctx, status_code=500)


rotas = [
    Route("/healthz", healthz),
    Route("/privacidade", privacidade),
    Route("/sw.js", service_worker),
    Mount("/static", app=StaticFiles(directory=os.path.join(BASE, "static")), name="static"),
    *acesso.rotas, *membros.rotas, *regularizacao.rotas, *voluntarios.rotas, *pesquisa.rotas, *relatorios.rotas, *agenda.rotas, *admin.rotas,
]

middleware = [
    Middleware(GZipMiddleware, minimum_size=800),
    Middleware(CabecalhosSeguranca),
    Middleware(SessionMiddleware, secret_key=config.SECRET_KEY, session_cookie="mevam_sessao",
               max_age=config.SESSAO_MAX_SEGUNDOS, same_site="lax", https_only=config.COOKIE_SEGURO),
]


def criar_app() -> Starlette:
    db.criar_tabelas_dev()
    db.aplicar_migracoes_aditivas()
    return Starlette(routes=rotas, middleware=middleware,
                     exception_handlers={404: nao_encontrado, 500: erro_interno})


app = criar_app()
