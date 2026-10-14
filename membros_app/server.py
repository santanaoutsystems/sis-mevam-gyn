"""
Servidor Web Assíncrono - SIS MEVAM-GYN (Membros, OCR & Credo)
Construído com Starlette e Uvicorn para máxima performance em smartphones, iPhones e PCs.
"""

import os
import sys
import json
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles
from starlette.responses import JSONResponse, HTMLResponse, Response
from starlette.templating import Jinja2Templates

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from database import (
    init_db, cadastrar_membro, listar_membros,
    obter_membro_por_id, excluir_membro, obter_estatisticas
)
from pdf_generator import gerar_pdf_membro
from ocr_parser import parsear_texto_ficha, extrair_texto_pdf

STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Inicializar Banco na subida do servidor
init_db()


# ==========================================
# ROTAS DE PÁGINAS HTML
# ==========================================
async def index_view(request):
    """Página principal do aplicativo (Mobile & Desktop)."""
    return templates.TemplateResponse(request, "index.html", context={})


async def comprovante_print_view(request):
    """Página formatada para impressão do documento oficial assinado."""
    membro_id = int(request.path_params['id'])
    membro = obter_membro_por_id(membro_id)
    if not membro:
        return HTMLResponse("<h1>Membro não encontrado</h1>", status_code=404)
    return templates.TemplateResponse(request, "comprovante_print.html", context={"membro": membro})


# ==========================================
# ROTAS DA API REST
# ==========================================
async def api_listar_membros(request):
    busca = request.query_params.get("busca", "")
    status = request.query_params.get("status", "")
    membros = listar_membros(busca=busca, status=status)
    return JSONResponse(membros)


async def api_obter_membro(request):
    membro_id = int(request.path_params['id'])
    membro = obter_membro_por_id(membro_id)
    if not membro:
        return JSONResponse({"error": "Membro não encontrado"}, status_code=404)
    return JSONResponse(membro)


async def api_cadastrar_membro(request):
    try:
        dados = await request.json()
        if not dados.get("nome_completo"):
            return JSONResponse({"error": "Nome completo é obrigatório"}, status_code=400)

        novo_id = cadastrar_membro(dados)
        return JSONResponse({
            "status": "success",
            "id": novo_id,
            "message": "Membro cadastrado e Confissão de Fé registrada com sucesso!"
        }, status_code=201)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def api_excluir_membro(request):
    membro_id = int(request.path_params['id'])
    excluir_membro(membro_id)
    return JSONResponse({"status": "deleted", "id": membro_id})


async def api_download_pdf(request):
    membro_id = int(request.path_params['id'])
    membro = obter_membro_por_id(membro_id)
    if not membro:
        return JSONResponse({"error": "Membro não encontrado"}, status_code=404)

    pdf_bytes = gerar_pdf_membro(membro)
    nome_arquivo = f"MEVAM_GYN_Membro_{membro_id}_{membro.get('nome_completo','').replace(' ','_')}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename=\"{nome_arquivo}\""
        }
    )


async def api_ocr_parse_fallback(request):
    """Endpoint backend para processamento de arquivo PDF/Imagem se necessário."""
    try:
        form = await request.form()
        arquivo = form.get("file")
        if not arquivo:
            return JSONResponse({"error": "Nenhum arquivo enviado"}, status_code=400)

        caminho_temp = os.path.join(UPLOADS_DIR, arquivo.filename)
        with open(caminho_temp, "wb") as f:
            f.write(await arquivo.read())

        texto = ""
        if arquivo.filename.lower().endswith(".pdf"):
            texto = extrair_texto_pdf(caminho_temp)

        dados_extraidos = parsear_texto_ficha(texto)
        return JSONResponse(dados_extraidos)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def api_estatisticas(request):
    stats = obter_estatisticas()
    return JSONResponse(stats)


# ==========================================
# CONFIGURAÇÃO DE ROTAS E ARQUIVOS ESTÁTICOS
# ==========================================
routes = [
    Route("/", index_view, methods=["GET"]),
    Route("/membro/{id:int}/comprovante", comprovante_print_view, methods=["GET"]),
    
    # API Endpoints
    Route("/api/membros", api_listar_membros, methods=["GET"]),
    Route("/api/membros", api_cadastrar_membro, methods=["POST"]),
    Route("/api/membros/{id:int}", api_obter_membro, methods=["GET"]),
    Route("/api/membros/{id:int}", api_excluir_membro, methods=["DELETE"]),
    Route("/api/membros/{id:int}/pdf", api_download_pdf, methods=["GET"]),
    Route("/api/ocr/parse", api_ocr_parse_fallback, methods=["POST"]),
    Route("/api/estatisticas", api_estatisticas, methods=["GET"]),

    # Arquivos Estáticos
    Mount("/static", app=StaticFiles(directory=STATIC_DIR), name="static"),
]

app = Starlette(debug=True, routes=routes)

if __name__ == "__main__":
    porta = int(os.environ.get("PORT", 8080))
    print("=========================================================")
    print(f"SIS MEVAM-GYN (Membros, OCR & Credo) Rodando!")
    print(f"Acesso em Celular / iPhone / PC: http://localhost:{porta}")
    print("=========================================================")
    uvicorn.run(app, host="0.0.0.0", port=porta, log_level="info")
