import os
import json
import uuid
import tempfile
import subprocess
import shutil
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI
from supabase import create_client, Client

load_dotenv()

# --- CONFIGURAÇÕES E CLIENTES ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

client = OpenAI(api_key=OPENAI_API_KEY)
# Inicializa o Supabase (Certifica-te que as ENVs estão no Render)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 EditMind Engine Iniciada")
    if not OPENAI_API_KEY:
        print("⚠️ AVISO: OPENAI_API_KEY não configurada!")
    yield
    print("🛑 Engine Encerrada")

app = FastAPI(title="EditMind API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")

# --- MODELOS DE DADOS ---
class AuthRequest(BaseModel):
    email: str
    senha: str

class YouTubeRequest(BaseModel):
    url: str

# --- FUNÇÕES AUXILIARES DE EDIÇÃO ---

def transcrever_audio_whisper(caminho_audio):
    """Usa a API da OpenAI para transcrever o áudio"""
    with open(caminho_audio, "rb") as audio_file:
        return client.audio.transcriptions.create(
            model="whisper-1", 
            file=audio_file,
            response_format="verbose_json"
        )

def analisar_corte_viral(texto_transcricao):
    """Usa GPT para decidir o melhor momento do corte"""
    prompt = (
        "Atue como um editor de vídeo viral. Analise a transcrição abaixo e escolha o melhor trecho "
        "(entre 30 a 60 segundos) para um Reels/TikTok. "
        "Responda APENAS em JSON no formato: {'inicio': float, 'fim': float, 'motivo': str}\n\n"
        f"Transcrição: {texto_transcricao}"
    )
    
    response = client.chat.completions.create(
        model="gpt-4o", # Ou gpt-5-nano quando disponível
        messages=[{"role": "system", "content": "Você é um especialista em viralidade."},
                  {"role": "user", "content": prompt}],
        response_format={ "type": "json_object" }
    )
    return json.loads(response.choices[0].message.content)

def cortar_video_ffmpeg(entrada, saida, inicio, fim):
    """Corta o vídeo usando Stream Copy (Instantâneo)"""
    duracao = fim - inicio
    cmd = [
        "ffmpeg", "-y", "-ss", str(inicio), "-i", str(entrada),
        "-t", str(duracao), "-c", "copy", "-movflags", "+faststart", str(saida)
    ]
    subprocess.run(cmd, capture_output=True, check=True)

# --- ROTAS DE AUTENTICAÇÃO (SUPABASE) ---

@app.post("/api/auth/cadastro")
async def cadastro(dados: AuthRequest):
    try:
        res = supabase.auth.sign_up({"email": dados.email, "password": dados.senha})
        if not res.session:
            return {"sucesso": True, "msg": "Verifique o seu e-mail para confirmar a conta."}
        return {"sucesso": True, "token": res.session.access_token, "usuario": {"email": dados.email}}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/auth/login")
async def login(dados: AuthRequest):
    try:
        res = supabase.auth.sign_in_with_password({"email": dados.email, "password": dados.senha})
        return {"sucesso": True, "token": res.session.access_token, "usuario": {"email": dados.email}}
    except Exception:
        raise HTTPException(status_code=401, detail="E-mail ou senha incorretos.")

# --- ROTA PRINCIPAL DE PROCESSAMENTO (PROTEGIDA) ---

@app.post("/api/processar")
async def processar_video(
    tasks: BackgroundTasks, 
    file: UploadFile = File(...),
    authorization: str = Header(None)
):
    # 1. Validação de Segurança
    if not authorization:
        raise HTTPException(status_code=401, detail="Acesso negado. Faça login.")
    
    try:
        token = authorization.replace("Bearer ", "")
        user = supabase.auth.get_user(token)
        if not user: raise Exception()
    except:
        raise HTTPException(status_code=401, detail="Sessão inválida ou expirada.")

    # 2. Setup de ficheiros
    job_id = str(uuid.uuid4())[:8]
    pasta_temp = Path(tempfile.mkdtemp(prefix=f"editmind_{job_id}_"))
    
    try:
        video_path = pasta_temp / file.filename
        audio_path = pasta_temp / "extraido.mp3"
        output_filename = f"corte_{job_id}.mp4"
        output_path = OUTPUT_DIR / output_filename

        with open(video_path, "wb") as f:
            f.write(await file.read())

        # 3. Extrair Áudio
        subprocess.run(["ffmpeg", "-i", str(video_path), "-vn", "-acodec", "libmp3lame", str(audio_path)], check=True)

        # 4. IA: Transcrever e Analisar
        transcricao = transcrever_audio_whisper(str(audio_path))
        analise = analisar_corte_viral(transcricao.text)

        # 5. Cortar Vídeo
        cortar_video_ffmpeg(video_path, output_path, analise['inicio'], analise['fim'])

        # Limpeza em background
        tasks.add_task(shutil.rmtree, pasta_temp, ignore_errors=True)

        return {
            "status": "sucesso",
            "url_corte": f"/outputs/{output_filename}",
            "transcricao": transcricao.text[:200] + "...",
            "corte_sugerido": analise
        }

    except Exception as e:
        shutil.rmtree(pasta_temp, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Erro no processamento: {str(e)}")

# --- ROTA YOUTUBE ---

@app.post("/api/download-youtube")
async def download_youtube(dados: YouTubeRequest):
    if "youtube.com" not in dados.url and "youtu.be" not in dados.url:
        raise HTTPException(status_code=400, detail="URL inválida.")

    job_id = str(uuid.uuid4())[:8]
    pasta_temp = Path(tempfile.mkdtemp(prefix=f"editmind_yt_{job_id}_"))

    try:
        cmd = [
            "yt-dlp", "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4", "-o", str(pasta_temp / "video.mp4"),
            "--no-playlist", dados.url
        ]
        subprocess.run(cmd, check=True)
        
        video_final = pasta_temp / "video.mp4"
        return FileResponse(path=str(video_final), media_type="video/mp4", filename=f"yt_{job_id}.mp4")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
def health_check():
    return {"status": "online", "engine": "EditMind Pro v2"}