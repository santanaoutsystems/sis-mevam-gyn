"""Instituto (v2.11.0): espaço reservado no menu para o futuro módulo. Por enquanto só o Adm vê."""

from __future__ import annotations

from starlette.requests import Request
from starlette.routing import Route

from .. import seguranca
from ..web import render


@seguranca.exigir("admin")
async def inicio(request: Request):
    return render(request, "instituto/inicio.html")


rotas = [Route("/instituto", inicio)]
