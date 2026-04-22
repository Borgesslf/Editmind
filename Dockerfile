# ══════════════════════════════════════════════════════════════
# EditMind — Dockerfile Produção
# Melhorias: usuário não-root, imagem slim, cache de layers otimizado
# ══════════════════════════════════════════════════════════════

FROM python:3.11-slim

# Metadados da imagem
LABEL maintainer="EditMind Squad"
LABEL description="EditMind API — FastAPI + FFmpeg + OpenAI"

# Evita prompts interativos no apt
ENV DEBIAN_FRONTEND=noninteractive
# Impede que o Python bufferize stdout (logs aparecem em tempo real)
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# ── Instala FFmpeg e cria usuário não-root ────────────────────
# Rodamos como usuário não-root por segurança:
# se a app for comprometida, o atacante não tem acesso root ao container
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash appuser

WORKDIR /app

# ── Copia requirements ANTES do código ───────────────────────
# Isso aproveita o cache do Docker: se o requirements.txt não mudar,
# o pip install não é re-executado mesmo que o código mude
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ── Copia o resto do projeto ──────────────────────────────────
COPY . .

# ── Cria pasta outputs com permissão correta ──────────────────
RUN mkdir -p outputs && chown -R appuser:appuser /app

# ── Troca para usuário não-root ───────────────────────────────
USER appuser

EXPOSE 8000

# ── Comando de produção ───────────────────────────────────────
# --workers 1: Render free tier tem 512MB RAM — 1 worker é o suficiente
# --timeout-keep-alive 75: evita timeout no Render
CMD ["uvicorn", "main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--timeout-keep-alive", "75"]
