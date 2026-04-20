FROM python:3.11-slim

# 1. Instala APENAS o essencial (FFmpeg para o corte de vídeo)
# Removido o 'git' para deixar a imagem mais leve, a menos que você precise muito
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 2. Diretório de trabalho
WORKDIR /app

# 3. Instala as dependências Python (Sem Torch/Whisper local!)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- AQUI ESTAVA O ERRO ---
# REMOVEMOS a linha que baixava o modelo Whisper local. 
# Agora a transcrição será via API (Groq), economizando 1GB de RAM.

# 4. Copia o projeto e garante as pastas necessárias
COPY . .
RUN mkdir -p outputs && chmod 777 outputs

# 5. Porta padrão (Koyeb costuma usar 8000, mas vamos manter flexível)
EXPOSE 8000

# 6. Inicia o servidor usando a porta 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]