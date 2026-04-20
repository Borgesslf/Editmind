import os
import json
import uuid
import tempfile
import subprocess
import shutil
from pathlib import Path
from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="EditMind Pro API")

# Permite que seu Frontend fale com o Backend sem bloqueios
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)
app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")

# --- FUNÇÕES DE ELITE ---

def transcrever_audio(caminho_audio: str):
    """O 'Whisper rapidão' via Groq"""
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    with open(caminho_audio, "rb") as file:
        return client.audio.transcriptions.create(
            file=(caminho_audio, file.read()),
            model="whisper-large-v3-turbo",
            response_format="verbose_json",
            language="pt"
        )

def analisar_viralidade(texto: str):
    """Cérebro GPT-5-Nano: O melhor custo-benefício"""
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    prompt = "Você é um editor profissional. Escolha o melhor trecho (30-60s) para TikTok/Reels. Responda APENAS JSON: {'inicio': float, 'fim': float, 'motivo': str}"
    
    res = client.chat.completions.create(
        model="gpt-5-nano",
        messages=[{"role": "system", "content": prompt}, {"role": "user", "content": texto}],
        response_format={"type": "json_object"}
    )
    return json.loads(res.choices[0].message.content)

def cortar_video_pro(entrada: str, saida: str, inicio: float, fim: float):
    """Corte instantâneo sem re-encodificação (Stream Copy)"""
    cmd = [
        "ffmpeg", "-y", "-ss", str(inicio), "-i", entrada, 
        "-t", str(fim - inicio), "-c", "copy", "-movflags", "+faststart", saida
    ]
    subprocess.run(cmd, capture_output=True)

# --- ENDPOINTS ---

@app.post("/api/processar")
async def processar_video(tasks: BackgroundTasks, file: UploadFile = File(...)):
    job_id = str(uuid.uuid4())[:8]
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"edit_{job_id}"))
    
    try:
        video_path = tmp_dir / file.filename
        audio_path = tmp_dir / "audio.mp3"
        
        with open(video_path, "wb") as f:
            f.write(await file.read())

        # Extração rápida de áudio
        subprocess.run(["ffmpeg", "-i", str(video_path), "-vn", "-acodec", "libmp3lame", str(audio_path)], capture_output=True)

        # Pipeline de IA
        transcricao = transcrever_audio(str(audio_path))
        texto_completo = " ".join([s['text'] for s in transcricao.segments])
        analise = analisar_viralidade(texto_completo)

        # Execução do corte
        output_name = f"final_{job_id}.mp4"
        output_path = OUTPUT_DIR / output_name
        cortar_video_pro(str(video_path), str(output_path), analise['inicio'], analise['fim'])

        # Limpeza automática em segundo plano
        tasks.add_task(shutil.rmtree, tmp_dir, ignore_errors=True)

        return {
            "status": "sucesso",
            "video_url": f"/outputs/{output_name}",
            "insight": analise['motivo']
        }

    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def home():
    return {"message": "EditMind Pro Online - Pronto para o gpt-5-nano"}