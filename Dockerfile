FROM python:3.11-slim

# Instala FFmpeg e dependencias do sistema
RUN apt-get update && apt-get install -y \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

# Diretorio de trabalho
WORKDIR /app

# Copia e instala dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-baixa o modelo Whisper base (fica dentro da imagem, nao baixa a cada restart)
RUN python -c "import whisper; whisper.load_model('base')"

# Copia o projeto inteiro
COPY . .

# Cria pasta de outputs
RUN mkdir -p outputs

# Porta padrao do Hugging Face Spaces
EXPOSE 7860

# Inicia o servidor
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
