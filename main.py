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
from groq import Groq
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

GROQ_CLIENT = Groq(api_key=os.getenv("GROQ_API_KEY"))
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
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        caminho_audio
    ]

    resultado = subprocess.run(cmd, capture_output=True, text=True)

    if resultado.returncode != 0:
        raise Exception(f"Erro ao extrair áudio: {resultado.stderr}")

def transcrever_audio(caminho_audio: str):
    with open(caminho_audio, "rb") as arquivo:
        resposta = GROQ_CLIENT.audio.transcriptions.create(
            file=(os.path.basename(caminho_audio), arquivo.read()),
            model="whisper-large-v3-turbo",
            response_format="verbose_json",
            language="pt"
        )

    return resposta

def analisar_viralidade(segmentos):
    segmentos_formatados = []

    for segmento in segmentos:
        inicio = round(segmento["start"], 2)
        fim = round(segmento["end"], 2)
        texto = segmento["text"].strip()

        segmentos_formatados.append(
            f"[{inicio}s - {fim}s] {texto}"
        )

    transcricao_formatada = "\n".join(segmentos_formatados)

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

Transcrição:
{transcricao_formatada}
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
        response_format={"type": "json_object"},
        temperature=0.4
    )

    return json.loads(resposta.choices[0].message.content)

def cortar_video(entrada: str, saida: str, inicio: float, fim: float):
    duracao = fim - inicio

    cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(inicio),
        "-i", entrada,
        "-t", str(duracao),
        "-c:v", "copy",
        "-c:a", "aac",
        "-movflags", "+faststart",
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
        "transcricao": "whisper-large-v3-turbo"
    }

@app.post("/api/upload")
async def upload_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...)
):
    job_id = str(uuid.uuid4())[:8]
    pasta_temp = Path(tempfile.mkdtemp(prefix=f"editmind_{job_id}_"))

    try:
        extensao = Path(file.filename).suffix

        video_path = pasta_temp / f"video{extensao}"
        audio_path = pasta_temp / "audio.wav"

        with open(video_path, "wb") as buffer:
            buffer.write(await file.read())

        detalhes_tecnicos = obter_metadados_video(str(video_path))

        extrair_audio(str(video_path), str(audio_path))

        transcricao = transcrever_audio(str(audio_path))

        segmentos = []
        texto_completo = []

        for segmento in transcricao.segments:
            segmentos.append({
                "start": segmento.start,
                "end": segmento.end,
                "text": segmento.text
            })

            texto_completo.append(segmento.text.strip())

        texto_transcricao = " ".join(texto_completo)

        analise = analisar_viralidade(segmentos)

        inicio_segundos = float(analise["inicio"])
        fim_segundos = float(analise["fim"])

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

    except Exception as e:
        shutil.rmtree(pasta_temp, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(e))