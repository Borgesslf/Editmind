"""
EditMind - Backend API (MVP)
Stack: FastAPI + Whisper + FFmpeg + Groq
Deploy: Hugging Face Spaces (Docker)

Para rodar localmente:
    uvicorn main:app --reload --port 7860
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

load_dotenv()

# No HF Spaces, ffmpeg fica no PATH do sistema (instalado via apt no Dockerfile)
# Localmente no Windows, ajusta o caminho abaixo se necessario
FFMPEG_LOCAL  = Path(__file__).parent / "ffmpeg" / "bin" / "ffmpeg.exe"
FFPROBE_LOCAL = Path(__file__).parent / "ffmpeg" / "bin" / "ffprobe.exe"

if FFMPEG_LOCAL.exists():
    # Windows local: usa o ffmpeg portatil da pasta do projeto
    FFMPEG  = str(FFMPEG_LOCAL)
    FFPROBE = str(FFPROBE_LOCAL)
else:
    # Linux / HF Spaces: usa o ffmpeg instalado no sistema
    FFMPEG  = "ffmpeg"
    FFPROBE = "ffprobe"

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

whisper_model = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global whisper_model
    print("Iniciando EditMind API...")
    import whisper
    whisper_model = whisper.load_model("base")
    print("Whisper carregado!")
    yield
    print("Encerrando.")

app = FastAPI(title="EditMind API", version="1.0.0-MVP", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve os videos cortados
app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")


class YouTubeRequest(BaseModel):
    url: str


def segundos_para_hms(s: float) -> str:
    s = int(s)
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"


def obter_metadados_video(caminho: str) -> dict:
    cmd = [FFPROBE, "-v", "quiet", "-print_format", "json",
           "-show_streams", "-show_format", caminho]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return {"resolucao": "N/A", "fps": "N/A", "duracao_segundos": "N/A"}
    dados = json.loads(r.stdout)
    stream = next((s for s in dados.get("streams", []) if s.get("codec_type") == "video"), {})
    resolucao = f"{stream.get('width','?')}x{stream.get('height','?')}"
    try:
        num, den = stream.get("r_frame_rate", "0/1").split("/")
        fps = round(int(num) / int(den), 2)
    except Exception:
        fps = "N/A"
    duracao = round(float(dados.get("format", {}).get("duration", 0)), 1)
    return {"resolucao": resolucao, "fps": str(fps), "duracao_segundos": str(duracao)}


def extrair_audio(caminho_video: str, caminho_audio: str) -> None:
    cmd = [FFMPEG, "-y", "-i", caminho_video,
           "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", caminho_audio]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"FFmpeg falhou na extracao de audio: {r.stderr}")


def transcrever_com_whisper(caminho_audio: str) -> list:
    if whisper_model is None:
        raise RuntimeError("Whisper nao carregado.")
    resultado = whisper_model.transcribe(caminho_audio, language="pt", verbose=False)
    return [
        {"inicio": round(s["start"], 2), "fim": round(s["end"], 2), "texto": s["text"].strip()}
        for s in resultado.get("segments", [])
    ]


def formatar_transcricao(segmentos: list) -> str:
    return "\n".join(
        f"[{segundos_para_hms(s['inicio'])} -> {segundos_para_hms(s['fim'])}] {s['texto']}"
        for s in segmentos
    )


def analisar_com_groq(transcricao: str) -> dict:
    from groq import Groq
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY nao configurada. Adicione em Settings > Variables no HF Spaces.")
    cliente = Groq(api_key=GROQ_API_KEY)
    PROMPT = """Voce e um especialista em viralizacao de conteudo digital.
Analise a transcricao e identifique o trecho com MAIOR POTENCIAL VIRAL (30 a 60 segundos).
Criterios: gancho forte, insight surpreendente, inicio e fim naturais em frases completas.
Responda APENAS com JSON valido, sem texto extra:
{
  "inicio": "HH:MM:SS",
  "fim": "HH:MM:SS",
  "inicio_segundos": <float>,
  "fim_segundos": <float>,
  "motivo": "Explicacao em ate 30 palavras"
}"""
    resposta = cliente.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": PROMPT},
            {"role": "user", "content": f"Transcricao:\n\n{transcricao}"},
        ],
        temperature=0.3,
        max_tokens=300,
        response_format={"type": "json_object"},
    )
    return json.loads(resposta.choices[0].message.content)


def cortar_video(entrada: str, saida: str, inicio: float, fim: float) -> None:
    cmd = [FFMPEG, "-y", "-ss", str(inicio), "-i", entrada,
           "-t", str(fim - inicio), "-c:v", "copy",
           "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", saida]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"FFmpeg falhou no corte: {r.stderr[-500:]}")


# ── ENDPOINTS API ─────────────────────────────────────────────

@app.get("/api/health")
async def health_check():
    return {
        "status": "online",
        "servico": "EditMind API",
        "whisper": "carregado" if whisper_model else "nao carregado",
    }


@app.post("/api/upload")
async def upload_e_processar(background_tasks: BackgroundTasks, arquivo: UploadFile = File(...)):
    tipos_validos = ["video/mp4", "video/quicktime", "video/x-msvideo", "video/webm", "video/mpeg"]
    if arquivo.content_type not in tipos_validos:
        raise HTTPException(status_code=400, detail=f"Tipo invalido: {arquivo.content_type}")

    id_job   = str(uuid.uuid4())[:8]
    dir_temp = Path(tempfile.mkdtemp(prefix=f"editMind_{id_job}_"))
    print(f"\n{'='*50}\nNovo job: {id_job} | Arquivo: {arquivo.filename}\n{'='*50}")

    try:
        caminho_video = dir_temp / f"input_{arquivo.filename}"
        print(f"Salvando video...")
        with open(caminho_video, "wb") as f:
            f.write(await arquivo.read())

        print("Extraindo metadados...")
        metadados = obter_metadados_video(str(caminho_video))
        print(f"   -> {metadados}")

        caminho_audio = dir_temp / "audio.wav"
        print("Extraindo audio...")
        extrair_audio(str(caminho_video), str(caminho_audio))

        print("Transcrevendo com Whisper...")
        segmentos = transcrever_com_whisper(str(caminho_audio))
        transcricao_texto     = " ".join(s["texto"] for s in segmentos)
        transcricao_formatada = formatar_transcricao(segmentos)
        print(f"   -> {len(segmentos)} segmentos transcritos.")

        print("Enviando para Groq...")
        resultado_ia = analisar_com_groq(transcricao_formatada)
        print(f"   -> {resultado_ia.get('inicio')} -> {resultado_ia.get('fim')}")

        nome_saida    = f"corte_{id_job}.mp4"
        caminho_saida = OUTPUT_DIR / nome_saida
        inicio_seg    = float(resultado_ia.get("inicio_segundos", 0))
        fim_seg       = float(resultado_ia.get("fim_segundos", 60))
        print(f"Cortando video: {inicio_seg}s -> {fim_seg}s")
        cortar_video(str(caminho_video), str(caminho_saida), inicio_seg, fim_seg)

        background_tasks.add_task(shutil.rmtree, dir_temp, ignore_errors=True)
        print(f"Job {id_job} concluido!")

        return JSONResponse(content={
            "sucesso": True,
            "transcricao": transcricao_texto,
            "corte_sugerido": {
                "inicio": resultado_ia.get("inicio", "00:00:00"),
                "fim":    resultado_ia.get("fim",    "00:01:00"),
                "motivo": resultado_ia.get("motivo", "Trecho com alto potencial viral."),
            },
            "detalhes_tecnicos": {
                "resolucao":        metadados.get("resolucao", "N/A"),
                "fps":              metadados.get("fps", "N/A"),
                "duracao_segundos": metadados.get("duracao_segundos", "N/A"),
            },
            "url_corte": f"/outputs/{nome_saida}",
        })

    except Exception as e:
        shutil.rmtree(dir_temp, ignore_errors=True)
        print(f"ERRO no job {id_job}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Erro no pipeline: {str(e)}")


@app.post("/api/download-youtube")
async def download_youtube(dados: YouTubeRequest):
    if "youtube.com" not in dados.url and "youtu.be" not in dados.url:
        raise HTTPException(status_code=400, detail="URL invalida.")
    id_job   = str(uuid.uuid4())[:8]
    dir_temp = Path(tempfile.mkdtemp(prefix=f"editMind_yt_{id_job}_"))
    print(f"\nDownload YouTube - Job: {id_job}")
    try:
        cmd = [
            "yt-dlp",
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "-o", str(dir_temp / "%(title)s.%(ext)s"),
            "--no-playlist",
            dados.url,
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise RuntimeError(f"yt-dlp falhou: {r.stderr[-500:]}")
        arquivos = list(dir_temp.glob("*.mp4"))
        if not arquivos:
            raise RuntimeError("MP4 nao encontrado apos download.")
        return FileResponse(path=str(arquivos[0]), media_type="video/mp4", filename="Video_EditMind.mp4")
    except subprocess.TimeoutExpired:
        shutil.rmtree(dir_temp, ignore_errors=True)
        raise HTTPException(status_code=408, detail="Timeout no download.")
    except Exception as e:
        shutil.rmtree(dir_temp, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Erro: {str(e)}")


# ── SERVE O FRONTEND (deve ficar por ULTIMO) ──────────────────
# Rota raiz: redireciona para a landing page
@app.get("/")
async def root():
    return FileResponse("frontend/home.html")

# Serve todos os arquivos estaticos do frontend
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
