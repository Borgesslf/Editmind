import os
import json
import uuid
import tempfile
import subprocess
import shutil
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

app = FastAPI(title="EditMind Pro API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")

OPENAI_CLIENT = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def segundos_para_timestamp(segundos: float) -> str:
    horas = int(segundos // 3600)
    minutos = int((segundos % 3600) // 60)
    segundos_restantes = int(segundos % 60)
    return f"{horas:02}:{minutos:02}:{segundos_restantes:02}"

def obter_metadados_video(caminho_video: str):
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate",
        "-show_entries", "format=duration",
        "-of", "json",
        caminho_video
    ]

    resultado = subprocess.run(cmd, capture_output=True, text=True)

    if resultado.returncode != 0:
        raise Exception("Erro ao obter metadados do vídeo")

    dados = json.loads(resultado.stdout)

    stream = dados["streams"][0]
    duracao = float(dados["format"]["duration"])

    largura = stream.get("width", 0)
    altura = stream.get("height", 0)

    fps_raw = stream.get("r_frame_rate", "0/1")
    numerador, denominador = fps_raw.split("/")
    fps = round(float(numerador) / float(denominador), 2)

    return {
        "resolucao": f"{largura}x{altura}",
        "fps": str(fps),
        "duracao_segundos": str(round(duracao, 2))
    }

def extrair_audio(caminho_video: str, caminho_audio: str):
    cmd = [
        "ffmpeg",
        "-y",
        "-i", caminho_video,
        "-vn",
        "-acodec", "mp3",
        "-ar", "8000",
        "-ac", "1",
        caminho_audio
    ]

    resultado = subprocess.run(cmd, capture_output=True, text=True)

    if resultado.returncode != 0:
        raise Exception(f"Erro ao extrair áudio: {resultado.stderr}")

def transcrever_audio(caminho_audio: str):
    with open(caminho_audio, "rb") as arquivo:
        resposta = OPENAI_CLIENT.audio.transcriptions.create(
            model="gpt-4o-mini-transcribe",
            file=arquivo,
            language="pt"
        )

    return resposta.text

def analisar_viralidade(texto_transcricao: str):
    prompt = f"""
Você é um editor especialista em TikTok, Reels e Shorts.

Analise a transcrição abaixo e escolha o melhor trecho contínuo com potencial viral.

Regras:
- Escolha um trecho entre 15 e 60 segundos
- Priorize partes com emoção, curiosidade, punchline, revelação, humor, polêmica ou frase forte
- Nunca escolha começo vazio ou final cortado
- Responda SOMENTE JSON válido

Formato:
{{
  "inicio": 12.5,
  "fim": 42.8,
  "motivo": "Explicação curta"
}}

IMPORTANTE:
- O início e fim devem ser em segundos
- O início nunca pode ser maior que o fim
- O trecho deve existir dentro do vídeo
- Evite escolher o vídeo inteiro

Transcrição:
{texto_transcricao}
"""

    resposta = OPENAI_CLIENT.chat.completions.create(
        model="gpt-5-mini",
        messages=[
            {
                "role": "system",
                "content": "Você é um editor profissional especialista em vídeos virais."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        response_format={"type": "json_object"}
    )

    conteudo = resposta.choices[0].message.content
    return json.loads(conteudo)

def cortar_video(entrada: str, saida: str, inicio: float, fim: float):
    cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(inicio),
        "-to", str(fim),
        "-i", entrada,
        "-c", "copy",
        "-avoid_negative_ts", "1",
        saida
    ]

    resultado = subprocess.run(cmd, capture_output=True, text=True)

    if resultado.returncode != 0:
        raise Exception(f"Erro ao cortar vídeo: {resultado.stderr}")

@app.get("/")
def home():
    return {
        "status": "online",
        "api": "EditMind Pro API",
        "llm": "gpt-5-mini",
        "transcricao": "gpt-4o-mini-transcribe"
    }

@app.post("/api/upload")
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...)
):
    job_id = str(uuid.uuid4())[:8]
    pasta_temp = Path(tempfile.mkdtemp(prefix=f"editmind_{job_id}_"))

    try:
        extensao = Path(file.filename).suffix.lower()

        if extensao not in [".mp4", ".mov", ".avi", ".webm"]:
            raise HTTPException(
                status_code=400,
                detail="Formato inválido. Use mp4, mov, avi ou webm."
            )

        video_path = pasta_temp / f"video{extensao}"
        audio_path = pasta_temp / "audio.mp3"

        with open(video_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        detalhes_tecnicos = obter_metadados_video(str(video_path))

        duracao_video = float(detalhes_tecnicos["duracao_segundos"])

        if duracao_video > 90:
            raise HTTPException(
                status_code=413,
                detail="Vídeo muito longo. Máximo permitido: 90 segundos."
            )

        extrair_audio(str(video_path), str(audio_path))

        texto_transcricao = transcrever_audio(str(audio_path))
        analise = analisar_viralidade(texto_transcricao)

        inicio_segundos = float(analise["inicio"])
        fim_segundos = float(analise["fim"])

        if inicio_segundos < 0:
            inicio_segundos = 0

        if fim_segundos > duracao_video:
            fim_segundos = duracao_video

        if fim_segundos <= inicio_segundos:
            fim_segundos = min(inicio_segundos + 30, duracao_video)

        nome_saida = f"corte_{job_id}.mp4"
        caminho_saida = OUTPUT_DIR / nome_saida

        cortar_video(
            str(video_path),
            str(caminho_saida),
            inicio_segundos,
            fim_segundos
        )

        background_tasks.add_task(
            shutil.rmtree,
            pasta_temp,
            ignore_errors=True
        )

        return {
            "sucesso": True,
            "transcricao": texto_transcricao,
            "corte_sugerido": {
                "inicio": segundos_para_timestamp(inicio_segundos),
                "fim": segundos_para_timestamp(fim_segundos),
                "motivo": analise["motivo"]
            },
            "detalhes_tecnicos": detalhes_tecnicos,
            "url_corte": f"/outputs/{nome_saida}"
        }

    except HTTPException:
        shutil.rmtree(pasta_temp, ignore_errors=True)
        raise

    except Exception as e:
        shutil.rmtree(pasta_temp, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(e))