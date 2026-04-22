"""
EditMind API v2.1 — Produção
Stack: FastAPI + AsyncOpenAI + Supabase + FFmpeg (async)
Deploy: Render (backend) | Vercel (frontend)

Melhorias aplicadas:
- subprocess.run() substituído por asyncio.create_subprocess_exec() (não bloqueia o event loop)
- AsyncOpenAI em vez de OpenAI (não bloqueia o event loop)
- Supabase síncrono executado via asyncio.to_thread() (não bloqueia o event loop)
- Autenticação extraída para Dependency (DRY, testável, reutilizável)
- Validação Pydantic com EmailStr e field_validator
- Logging estruturado em vez de print()
- Limpeza de arquivos temporários garantida mesmo em caso de erro
- Verificação de tamanho de arquivo antes de salvar
- Sanitização do nome do arquivo de upload
"""

import os
import re
import json
import uuid
import asyncio
import tempfile
import shutil
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, field_validator
from dotenv import load_dotenv
from openai import AsyncOpenAI
from supabase import create_client, Client

# ── Logging estruturado ───────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("editmind")

load_dotenv()

# ── Variáveis de ambiente ─────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
SUPABASE_URL   = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY   = os.getenv("SUPABASE_KEY", "")

# ── Clientes globais ──────────────────────────────────────────
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
supabase: Optional[Client] = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

# ── Constantes ────────────────────────────────────────────────
MAX_DURACAO_SEGUNDOS = 180
MAX_TAMANHO_BYTES    = 200 * 1024 * 1024  # 200 MB
EXTENSOES_VALIDAS    = {".mp4", ".mov", ".avi", ".webm"}


# ══════════════════════════════════════════════════════════════
# LIFESPAN — Startup e Shutdown
# ══════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 EditMind Engine iniciada")
    logger.info(f"   OpenAI : {'✅' if OPENAI_API_KEY else '❌ não configurada'}")
    logger.info(f"   Supabase: {'✅' if SUPABASE_URL else '❌ não configurada'}")

    # Verifica ffmpeg no PATH
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-version",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        logger.info(f"   FFmpeg : {'✅ encontrado' if proc.returncode == 0 else '❌ não encontrado no PATH'}")
    except FileNotFoundError:
        logger.error("   FFmpeg : ❌ não encontrado no PATH")

    yield
    logger.info("🛑 Engine encerrada")


# ══════════════════════════════════════════════════════════════
# APP
# ══════════════════════════════════════════════════════════════

app = FastAPI(
    title="EditMind API",
    version="2.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")


# ══════════════════════════════════════════════════════════════
# MODELOS PYDANTIC
# ══════════════════════════════════════════════════════════════

class AuthRequest(BaseModel):
    email: EmailStr
    senha: str

    @field_validator("senha")
    @classmethod
    def senha_minima(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Senha deve ter pelo menos 6 caracteres.")
        return v


class YouTubeRequest(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def url_youtube(cls, v: str) -> str:
        if "youtube.com" not in v and "youtu.be" not in v:
            raise ValueError("URL deve ser do YouTube.")
        return v.strip()


# ══════════════════════════════════════════════════════════════
# DEPENDÊNCIA DE AUTENTICAÇÃO
# ══════════════════════════════════════════════════════════════

async def get_usuario_logado(authorization: Optional[str] = Header(None)) -> dict:
    """
    FastAPI Dependency — valida o token Bearer do Supabase.
    Executa a chamada síncrona em asyncio.to_thread() para não bloquear o event loop.
    Uso: usuario = Depends(get_usuario_logado) em qualquer rota protegida.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Token de autenticação ausente.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not supabase:
        raise HTTPException(status_code=503, detail="Serviço de autenticação indisponível.")

    token = authorization.removeprefix("Bearer ").strip()

    try:
        response = await asyncio.to_thread(supabase.auth.get_user, token)
        if not response or not response.user:
            raise ValueError("Usuário não encontrado.")
        return {"id": response.user.id, "email": response.user.email}
    except Exception as e:
        logger.warning(f"Token inválido: {e}")
        raise HTTPException(
            status_code=401,
            detail="Sessão inválida ou expirada. Faça login novamente.",
        )


# ══════════════════════════════════════════════════════════════
# HELPERS — FFMPEG ASSÍNCRONO
# ══════════════════════════════════════════════════════════════

async def _run_ffmpeg(*args: str) -> None:
    """
    Executa FFmpeg de forma assíncrona via asyncio.create_subprocess_exec().
    Não bloqueia o event loop — outras requisições continuam sendo atendidas
    enquanto o vídeo é processado.
    """
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        erro = stderr.decode(errors="replace")[-600:]
        raise RuntimeError(f"FFmpeg erro (código {proc.returncode}): {erro}")


async def obter_metadados_video(caminho: str) -> dict:
    """Extrai resolução, FPS e duração via ffprobe (assíncrono)."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams", "-show_format",
        caminho,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()

    if proc.returncode != 0:
        return {"resolucao": "N/A", "fps": "N/A", "duracao_segundos": "0"}

    dados = json.loads(stdout.decode())
    stream = next((s for s in dados.get("streams", []) if s.get("codec_type") == "video"), {})

    resolucao = f"{stream.get('width', '?')}x{stream.get('height', '?')}"
    try:
        num, den = stream.get("r_frame_rate", "0/1").split("/")
        fps = round(int(num) / int(den), 2)
    except Exception:
        fps = 0

    duracao = round(float(dados.get("format", {}).get("duration", 0)), 2)
    return {"resolucao": resolucao, "fps": str(fps), "duracao_segundos": str(duracao)}


async def extrair_audio(caminho_video: str, caminho_audio: str) -> None:
    """Extrai áudio em MP3 comprimido (16kHz mono 32k bitrate) — assíncrono."""
    await _run_ffmpeg(
        "-y", "-i", caminho_video,
        "-vn",
        "-acodec", "libmp3lame",
        "-ar", "16000",
        "-ac", "1",
        "-b:a", "32k",
        caminho_audio,
    )


async def cortar_video(entrada: str, saida: str, inicio: float, fim: float) -> None:
    """Corta o vídeo usando stream copy (sem re-encoding) — assíncrono."""
    await _run_ffmpeg(
        "-y",
        "-ss", str(inicio),
        "-to", str(fim),
        "-i", entrada,
        "-c", "copy",
        "-avoid_negative_ts", "1",
        "-movflags", "+faststart",
        saida,
    )


def segundos_para_timestamp(s: float) -> str:
    s = int(s)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def sanitizar_nome_arquivo(nome: str) -> str:
    """Remove caracteres perigosos do nome do arquivo."""
    nome = Path(nome).name
    nome = re.sub(r"[^\w.\-]", "_", nome)
    return nome[:100]


# ══════════════════════════════════════════════════════════════
# HELPERS — OPENAI ASSÍNCRONO
# ══════════════════════════════════════════════════════════════

async def transcrever_audio(caminho_audio: str) -> str:
    """
    Etapa 1: Transcreve com whisper-1 via API (assíncrono).
    Etapa 2: Corrige com gpt-4o-mini (assíncrono).
    """
    if not openai_client:
        raise RuntimeError("OPENAI_API_KEY não configurada.")

    tamanho_mb = Path(caminho_audio).stat().st_size / (1024 * 1024)
    logger.info(f"   Áudio: {tamanho_mb:.1f} MB")

    if tamanho_mb > 24:
        raise HTTPException(
            status_code=413,
            detail=f"Áudio muito grande ({tamanho_mb:.1f}MB). Limite da API Whisper: 25MB. Use vídeos mais curtos.",
        )

    with open(caminho_audio, "rb") as f:
        resposta = await openai_client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            language="pt",
            response_format="text",
        )

    texto_bruto = resposta if isinstance(resposta, str) else getattr(resposta, "text", "")
    logger.info(f"   Transcrição bruta: {len(texto_bruto)} chars")

    # Corrige pontuação e erros com gpt-4o-mini (rápido e barato)
    correcao = await openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "Você é um corretor de transcrições automáticas em português brasileiro. "
                    "Corrija apenas erros de transcrição, pontuação e concordância. "
                    "NÃO resuma, NÃO corte conteúdo, NÃO invente informações. "
                    "Retorne APENAS o texto corrigido, sem explicações."
                ),
            },
            {"role": "user", "content": texto_bruto},
        ],
        temperature=0.1,
        max_tokens=4000,
    )

    texto_corrigido = correcao.choices[0].message.content.strip()
    logger.info(f"   Transcrição corrigida: {len(texto_corrigido)} chars")
    return texto_corrigido


async def analisar_viralidade(transcricao: str, duracao_total: float) -> dict:
    """Usa GPT-4o para identificar o melhor trecho viral (assíncrono)."""
    if not openai_client:
        raise RuntimeError("OPENAI_API_KEY não configurada.")

    resposta = await openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": (
                    "Você é um editor especialista em TikTok, Reels e YouTube Shorts. "
                    "Analise a transcrição e escolha o melhor trecho contínuo com potencial viral. "
                    "Priorize: emoção, curiosidade, revelação, humor, polêmica ou frase de impacto. "
                    f"O vídeo tem {duracao_total:.1f} segundos. "
                    "O trecho deve ter entre 15 e 60 segundos. "
                    "Início e fim NUNCA podem ser iguais. "
                    "Responda APENAS com JSON válido, sem markdown."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Transcrição:\n{transcricao}\n\n"
                    'Formato: {"inicio": 12.5, "fim": 42.8, "motivo": "Explicação curta"}'
                ),
            },
        ],
        temperature=0.2,
        max_tokens=200,
        response_format={"type": "json_object"},
    )

    dados = json.loads(resposta.choices[0].message.content)

    # Sanitização dos valores retornados pela IA
    inicio = max(0.0, float(dados.get("inicio", 0)))
    fim    = min(float(dados.get("fim", min(60, duracao_total))), duracao_total)

    if fim <= inicio:
        fim = min(inicio + 30, duracao_total)

    dados["inicio"] = round(inicio, 2)
    dados["fim"]    = round(fim, 2)
    return dados


# ══════════════════════════════════════════════════════════════
# ENDPOINTS — AUTH (Supabase)
# ══════════════════════════════════════════════════════════════

@app.post("/api/auth/cadastro")
async def cadastro(dados: AuthRequest):
    if not supabase:
        raise HTTPException(status_code=503, detail="Serviço de autenticação indisponível.")
    try:
        res = await asyncio.to_thread(
            supabase.auth.sign_up,
            {"email": dados.email, "password": dados.senha}
        )
        if res.session:
            return {
                "sucesso": True,
                "token": res.session.access_token,
                "usuario": {"email": dados.email},
            }
        return {"sucesso": True, "msg": "Verifique o seu e-mail para confirmar a conta."}
    except Exception as e:
        logger.error(f"Erro no cadastro: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/auth/login")
async def login(dados: AuthRequest):
    if not supabase:
        raise HTTPException(status_code=503, detail="Serviço de autenticação indisponível.")
    try:
        res = await asyncio.to_thread(
            supabase.auth.sign_in_with_password,
            {"email": dados.email, "password": dados.senha}
        )
        return {
            "sucesso": True,
            "token": res.session.access_token,
            "usuario": {"email": dados.email},
        }
    except Exception:
        raise HTTPException(status_code=401, detail="E-mail ou senha incorretos.")


# ══════════════════════════════════════════════════════════════
# ENDPOINT PRINCIPAL — PROCESSAR VÍDEO
# ══════════════════════════════════════════════════════════════

@app.post("/api/processar")
async def processar_video(
    tasks: BackgroundTasks,
    file: UploadFile = File(...),
    usuario: dict = Depends(get_usuario_logado),
):
    """
    Pipeline completo:
    1. Valida arquivo
    2. Extrai metadados (ffprobe async)
    3. Extrai áudio (ffmpeg async)
    4. Transcreve (whisper-1 async)
    5. Analisa viralidade (gpt-4o async)
    6. Corta vídeo (ffmpeg async)
    7. Retorna resultado
    """
    # ── Validação do arquivo ──────────────────────────────────
    ext = Path(file.filename or "").suffix.lower()
    if ext not in EXTENSOES_VALIDAS:
        raise HTTPException(
            status_code=400,
            detail=f"Formato '{ext}' inválido. Use: {', '.join(EXTENSOES_VALIDAS)}",
        )

    job_id     = str(uuid.uuid4())[:8]
    pasta_temp = Path(tempfile.mkdtemp(prefix=f"editmind_{job_id}_"))

    logger.info(f"Job {job_id} iniciado | usuário: {usuario['email']} | arquivo: {file.filename}")

    try:
        # ── Salvar arquivo com nome sanitizado ────────────────
        nome_seguro = sanitizar_nome_arquivo(file.filename or f"video{ext}")
        video_path  = pasta_temp / nome_seguro
        audio_path  = pasta_temp / "audio.mp3"

        # Lê em chunks para não explodir a memória com arquivos grandes
        tamanho = 0
        with open(video_path, "wb") as f_out:
            while chunk := await file.read(1024 * 1024):  # 1MB por vez
                tamanho += len(chunk)
                if tamanho > MAX_TAMANHO_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Arquivo muito grande. Máximo: {MAX_TAMANHO_BYTES // 1024 // 1024}MB.",
                    )
                f_out.write(chunk)

        logger.info(f"Job {job_id} | Salvo: {tamanho / 1024 / 1024:.1f} MB")

        # ── Metadados ─────────────────────────────────────────
        metadados = await obter_metadados_video(str(video_path))
        duracao   = float(metadados["duracao_segundos"])
        logger.info(f"Job {job_id} | Metadados: {metadados}")

        if duracao > MAX_DURACAO_SEGUNDOS:
            raise HTTPException(
                status_code=413,
                detail=f"Vídeo muito longo ({int(duracao)}s). Máximo: {MAX_DURACAO_SEGUNDOS}s (3 minutos).",
            )

        # ── Extração de áudio ─────────────────────────────────
        logger.info(f"Job {job_id} | Extraindo áudio...")
        await extrair_audio(str(video_path), str(audio_path))

        # ── Transcrição ───────────────────────────────────────
        logger.info(f"Job {job_id} | Transcrevendo com Whisper-1...")
        transcricao = await transcrever_audio(str(audio_path))

        # ── Análise viral ─────────────────────────────────────
        logger.info(f"Job {job_id} | Analisando viralidade com GPT-4o...")
        analise = await analisar_viralidade(transcricao, duracao)
        logger.info(f"Job {job_id} | Corte: {analise['inicio']}s → {analise['fim']}s | {analise.get('motivo', '')}")

        # ── Corte do vídeo ────────────────────────────────────
        nome_saida    = f"corte_{job_id}.mp4"
        caminho_saida = OUTPUT_DIR / nome_saida
        logger.info(f"Job {job_id} | Cortando vídeo...")
        await cortar_video(str(video_path), str(caminho_saida), analise["inicio"], analise["fim"])

        # ── Limpeza em background ─────────────────────────────
        tasks.add_task(shutil.rmtree, pasta_temp, ignore_errors=True)
        logger.info(f"Job {job_id} | ✅ Concluído!")

        return JSONResponse(content={
            "status": "sucesso",
            "transcricao": transcricao,
            "corte_sugerido": {
                "inicio": segundos_para_timestamp(analise["inicio"]),
                "fim":    segundos_para_timestamp(analise["fim"]),
                "inicio_segundos": analise["inicio"],
                "fim_segundos":    analise["fim"],
                "motivo": analise.get("motivo", "Trecho com alto potencial viral."),
            },
            "detalhes_tecnicos": metadados,
            "url_corte": f"/outputs/{nome_saida}",
        })

    except HTTPException:
        shutil.rmtree(pasta_temp, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(pasta_temp, ignore_errors=True)
        logger.error(f"Job {job_id} | ❌ Erro: {e}")
        raise HTTPException(status_code=500, detail=f"Erro no processamento: {str(e)}")


# ══════════════════════════════════════════════════════════════
# ENDPOINT — YOUTUBE DOWNLOADER
# ══════════════════════════════════════════════════════════════

@app.post("/api/download-youtube")
async def download_youtube(
    dados: YouTubeRequest,
    usuario: dict = Depends(get_usuario_logado),
):
    job_id     = str(uuid.uuid4())[:8]
    pasta_temp = Path(tempfile.mkdtemp(prefix=f"editmind_yt_{job_id}_"))
    saida      = pasta_temp / "video.mp4"

    logger.info(f"YT Job {job_id} | URL: {dados.url}")

    try:
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "-o", str(saida),
            "--no-playlist",
            dados.url,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

        if proc.returncode != 0:
            raise RuntimeError(stderr.decode(errors="replace")[-300:])

        if not saida.exists():
            raise RuntimeError("Arquivo não encontrado após download.")

        return FileResponse(
            path=str(saida),
            media_type="video/mp4",
            filename=f"yt_{job_id}.mp4",
        )
    except asyncio.TimeoutError:
        shutil.rmtree(pasta_temp, ignore_errors=True)
        raise HTTPException(status_code=408, detail="Timeout: vídeo demorou demais para baixar.")
    except Exception as e:
        shutil.rmtree(pasta_temp, ignore_errors=True)
        logger.error(f"YT Job {job_id} | Erro: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ══════════════════════════════════════════════════════════════
# HEALTH CHECK
# ══════════════════════════════════════════════════════════════

@app.get("/")
async def health_check():
    return {
        "status": "online",
        "api": "EditMind Pro",
        "versao": "2.1.0",
        "servicos": {
            "openai":   "configurado" if OPENAI_API_KEY else "ausente",
            "supabase": "configurado" if SUPABASE_URL else "ausente",
        },
    }
