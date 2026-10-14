# Dockerfile - SIS MEVAM-GYN (Membros, OCR & Credo)
FROM python:3.11-slim

WORKDIR /app

# Instalar dependências de sistema para PyMuPDF e fontes
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libmupdf-dev \
    && rm -rf /var/lib/apt/lists/*

# Copiar dependências e instalar
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código da aplicação
COPY . .

# Expor porta da aplicação
ENV PORT=8080
EXPOSE 8080

# Iniciar servidor Uvicorn / Starlette
CMD ["python", "membros_app/server.py"]
