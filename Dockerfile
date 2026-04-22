# ══════════════════════════════════════════════════════════════
# EditMind — Dockerfile Produção v3.0
# ══════════════════════════════════════════════════════════════

FROM python:3.11-slim

LABEL maintainer="EditMind Squad"
LABEL description="EditMind API — FastAPI + FFmpeg + OpenAI"

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Instala FFmpeg, curl e cria usuário não-root
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# Copia requirements e instala dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --upgrade yt-dlp

# Copia o resto do projeto
COPY . .

# Cria pasta outputs com permissão correta
RUN mkdir -p outputs && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--timeout-keep-alive", "75"]
