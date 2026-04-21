"""
EditMind - Backend API
Stack: FastAPI + OpenAI Whisper API + GPT-4o + FFmpeg
Deploy: Render (backend) + Vercel (frontend)
"""

import os
import json
import uuid
import tempfile
import subprocess
import shutil
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
client = OpenAI(api_key=OPENAI_API_KEY)

OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Iniciando EditMind API...")
    if not OPENAI_API_KEY:
        print("AVISO: OPENAI_API_KEY nao configurada!")
    else:
        print("OpenAI configurada.")
    yield
    print("Encerrando.")


app = FastAPI(title="EditMind API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")


class YouTubeRequest(BaseModel):
    url: str


# ── HELPERS ──────────────────────────────────────────────────

def segundos_para_timestamp(segundos: float) -> str:
    s = int(segundos)
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"


def obter_metadados_video(caminho_video: str) -> dict:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate",
        "-show_entries", "format=duration",
        "-of", "json",
        caminho_video,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return {"resolucao": "N/A", "fps": "N/A", "duracao_segundos": "N/A"}

    dados = json.loads(r.stdout)
    stream = dados.get("streams", [{}])[0]
    duracao = round(float(dados.get("format", {}).get("duration", 0)), 2)

    largura  = stream.get("width", 0)
    altura   = stream.get("height", 0)
    fps_raw  = stream.get("r_frame_rate", "0/1")

    try:
        num, den = fps_raw.split("/")
        fps = round(float(num) / float(den), 2)
    except Exception:
        fps = 0

    return {
        "resolucao": f"{largura}x{altura}",
        "fps": str(fps),
        "duracao_segundos": str(duracao),
    }


def extrair_audio(caminho_video: str, caminho_audio: str) -> None:
    """
    Extrai audio em MP3 comprimido.
    Taxa 16kHz mono — ideal para fala, mantém arquivo pequeno (limite 25MB da API).
    """
    cmd = [
        "ffmpeg", "-y", "-i", caminho_video,
        "-vn",
        "-acodec", "libmp3lame",
        "-ar", "16000",   # 16kHz — suficiente para fala, nao para musica
        "-ac", "1",       # mono
        "-b:a", "32k",    # bitrate baixo = arquivo menor
        caminho_audio,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"FFmpeg falhou na extracao de audio: {r.stderr}")


def transcrever_audio(caminho_audio: str) -> str:
    """
    Etapa 1: Transcreve com whisper-1 (unico modelo de transcricao da OpenAI).
    Etapa 2: Corrige a transcricao com gpt-4o-mini (rapido e barato).
    """
    # ── Verificar tamanho (limite 25MB) ──────────────────────
    tamanho_mb = Path(caminho_audio).stat().st_size / (1024 * 1024)
    print(f"   -> Audio: {tamanho_mb:.1f} MB")
    if tamanho_mb > 24:
        raise RuntimeError(
            f"Audio muito grande ({tamanho_mb:.1f}MB). "
            "Use um video mais curto (max ~3 minutos com as configuracoes atuais)."
        )

    # ── Transcricao bruta com Whisper ─────────────────────────
    with open(caminho_audio, "rb") as f:
        resposta = client.audio.transcriptions.create(
            model="whisper-1",          # Unico modelo de transcricao da OpenAI
            file=f,
            language="pt",              # Forca portugues
            response_format="text",     # Texto simples, sem timestamps
        )

    texto_bruto = resposta if isinstance(resposta, str) else resposta.text
    print(f"   -> Transcricao bruta: {len(texto_bruto)} chars")

    # ── Correcao e limpeza com GPT-4o-mini ───────────────────
    correcao = client.chat.completions.create(
        model="gpt-4o-mini",            # Modelo real e barato da OpenAI
        messages=[
            {
                "role": "system",
                "content": (
                    "Voce e um corretor de transcricoes automaticas em portugues brasileiro. "
                    "Corrija erros de transcricao, pontuacao e concordancia. "
                    "NAO resuma, NAO corte conteudo, NAO invente informacoes. "
                    "Retorne APENAS o texto corrigido, sem explicacoes."
                ),
            },
            {"role": "user", "content": texto_bruto},
        ],
        temperature=0.1,
        max_tokens=4000,
    )

    texto_corrigido = correcao.choices[0].message.content.strip()
    print(f"   -> Transcricao corrigida: {len(texto_corrigido)} chars")
    return texto_corrigido


def analisar_viralidade(transcricao: str, duracao_total: float) -> dict:
    """
    Usa GPT-4o para identificar o melhor trecho viral (15 a 60 segundos).
    """
    resposta = client.chat.completions.create(
        model="gpt-4o",                 # Modelo mais inteligente para analise
        messages=[
            {
                "role": "system",
                "content": (
                    "Voce e um editor especialista em TikTok, Reels e YouTube Shorts. "
                    "Analise a transcricao e escolha o melhor trecho continuo com potencial viral. "
                    "Priorize: emocao, curiosidade, revelacao, humor, polêmica ou frase de impacto. "
                    "O trecho deve ter entre 15 e 60 segundos. "
                    "Inicio e fim NUNCA podem ser iguais. "
                    f"O video tem {duracao_total} segundos no total. "
                    "Responda APENAS com JSON valido, sem markdown."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Transcricao:\n{transcricao}\n\n"
                    "Formato de resposta:\n"
                    '{"inicio": 12.5, "fim": 42.8, "motivo": "Explicacao curta"}'
                ),
            },
        ],
        temperature=0.2,
        max_tokens=200,
        response_format={"type": "json_object"},
    )

    dados = json.loads(resposta.choices[0].message.content)

    inicio = float(dados.get("inicio", 0))
    fim    = float(dados.get("fim", min(60, duracao_total)))

    # Sanitizacao dos valores
    inicio = max(0, inicio)
    fim    = min(fim, duracao_total)

    if fim <= inicio:
        fim = min(inicio + 30, duracao_total)

    dados["inicio"] = inicio
    dados["fim"]    = fim
    return dados


def cortar_video(entrada: str, saida: str, inicio: float, fim: float) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(inicio),
        "-to", str(fim),
        "-i", entrada,
        "-c", "copy",
        "-avoid_negative_ts", "1",
        saida,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"FFmpeg falhou no corte: {r.stderr[-500:]}")


# ── ENDPOINTS ─────────────────────────────────────────────────

@app.get("/")
def home():
    return {
        "status": "online",
        "api": "EditMind API",
        "modelos": {
            "transcricao": "whisper-1",
            "correcao": "gpt-4o-mini",
            "analise_viral": "gpt-4o",
        },
    }


@app.post("/api/upload")
async def upload_video(
    background_tasks: BackgroundTasks,
    arquivo: UploadFile = File(...),
):
    extensao = Path(arquivo.filename).suffix.lower()
    if extensao not in [".mp4", ".mov", ".avi", ".webm"]:
        raise HTTPException(status_code=400, detail="Formato invalido. Use mp4, mov, avi ou webm.")

    job_id    = str(uuid.uuid4())[:8]
    pasta_temp = Path(tempfile.mkdtemp(prefix=f"editmind_{job_id}_"))

    print(f"\n{'='*50}\nJob: {job_id} | Arquivo: {arquivo.filename}\n{'='*50}")

    try:
        # 1. Salvar video
        video_path = pasta_temp / f"video{extensao}"
        with open(video_path, "wb") as f:
            shutil.copyfileobj(arquivo.file, f)
        print(f"Video salvo: {video_path.stat().st_size / 1024 / 1024:.1f} MB")

        # 2. Metadados
        print("Extraindo metadados...")
        detalhes = obter_metadados_video(str(video_path))
        duracao  = float(detalhes["duracao_segundos"])
        print(f"   -> {detalhes}")

        # Limite de duracao: 3 minutos
        if duracao > 180:
            raise HTTPException(
                status_code=413,
                detail=f"Video muito longo ({int(duracao)}s). Maximo permitido: 3 minutos (180s).",
            )

        # 3. Extrair audio
        audio_path = pasta_temp / "audio.mp3"
        print("Extraindo audio...")
        extrair_audio(str(video_path), str(audio_path))

        # 4. Transcrever + corrigir
        print("Transcrevendo com Whisper-1 + corrigindo com GPT-4o-mini...")
        transcricao = transcrever_audio(str(audio_path))

        # 5. Analisar viralidade
        print("Analisando viralidade com GPT-4o...")
        analise = analisar_viralidade(transcricao, duracao)
        print(f"   -> Corte: {analise['inicio']}s -> {analise['fim']}s")
        print(f"   -> Motivo: {analise['motivo']}")

        # 6. Cortar video
        nome_saida    = f"corte_{job_id}.mp4"
        caminho_saida = OUTPUT_DIR / nome_saida
        print(f"Cortando video...")
        cortar_video(str(video_path), str(caminho_saida), analise["inicio"], analise["fim"])

        background_tasks.add_task(shutil.rmtree, pasta_temp, ignore_errors=True)
        print(f"Job {job_id} concluido!")

        return JSONResponse(content={
            "sucesso": True,
            "transcricao": transcricao,
            "corte_sugerido": {
                "inicio": segundos_para_timestamp(analise["inicio"]),
                "fim":    segundos_para_timestamp(analise["fim"]),
                "motivo": analise.get("motivo", "Trecho com alto potencial viral."),
            },
            "detalhes_tecnicos": detalhes,
            "url_corte": f"/outputs/{nome_saida}",
        })

    except HTTPException:
        shutil.rmtree(pasta_temp, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(pasta_temp, ignore_errors=True)
        print(f"ERRO job {job_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/download-youtube")
async def download_youtube(dados: YouTubeRequest):
    if "youtube.com" not in dados.url and "youtu.be" not in dados.url:
        raise HTTPException(status_code=400, detail="URL invalida.")

    job_id    = str(uuid.uuid4())[:8]
    pasta_temp = Path(tempfile.mkdtemp(prefix=f"editmind_yt_{job_id}_"))

    try:
        cmd = [
            "yt-dlp",
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "-o", str(pasta_temp / "%(title)s.%(ext)s"),
            "--no-playlist",
            dados.url,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise RuntimeError(f"yt-dlp: {r.stderr[-300:]}")

        arquivos = list(pasta_temp.glob("*.mp4"))
        if not arquivos:
            raise RuntimeError("MP4 nao encontrado.")

        return FileResponse(
            path=str(arquivos[0]),
            media_type="video/mp4",
            filename="Video_EditMind.mp4",
        )
    except subprocess.TimeoutExpired:
        shutil.rmtree(pasta_temp, ignore_errors=True)
        raise HTTPException(status_code=408, detail="Timeout no download.")
    except Exception as e:
        shutil.rmtree(pasta_temp, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(e))