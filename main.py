"""
EditMind API v3.1
=================
Stack : FastAPI · OpenAI (Whisper-1 + GPT-4o) · FFmpeg · Supabase
Deploy: Render (backend) + Vercel (frontend)

Correções v3.1
--------------------
- /api/meus-cortes adicionado para alimentar a aba "Meus Conteúdos"
- upload para Supabase Storage corrigido (upsert como string, compatível com supabase-py)
- persistência de cortes vinculada ao usuário autenticado
- yt-dlp com headers anti-bot, retries e suporte opcional a cookies
- logging estruturado
- Async FFmpeg
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
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, field_validator
from dotenv import load_dotenv
from openai import AsyncOpenAI
from supabase import create_client, Client

# ── Logging ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("editmind")

load_dotenv()

# ── Variáveis de ambiente ─────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_KEY", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
SITE_URL = os.getenv("SITE_URL", "https://editmind.vercel.app")
YTDLP_COOKIES_FILE = os.getenv("YTDLP_COOKIES_FILE", "").strip()
YTDLP_EXTRACTOR_ARGS = os.getenv("YTDLP_EXTRACTOR_ARGS", "youtube:player_client=android,web")

# ── Clientes ──────────────────────────────────────────────────
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

supabase: Optional[Client] = (
    create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    if SUPABASE_URL and SUPABASE_ANON_KEY else None
)

supabase_admin: Optional[Client] = (
    create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    if SUPABASE_URL and SUPABASE_SERVICE_KEY else None
)

STORAGE_BUCKET = "cortes"
OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)

MAX_DURACAO_S = 180
MAX_BYTES = 200 * 1024 * 1024
EXTS_VALIDAS = {".mp4", ".mov", ".avi", ".webm"}

YT_DLP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


# ══════════════════════════════════════════════════════════════
# STARTUP
# ══════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 EditMind v3.1 iniciada")
    logger.info(f"   OpenAI        : {'✅' if OPENAI_API_KEY else '❌'}")
    logger.info(f"   Supabase Auth : {'✅' if supabase else '❌'}")
    logger.info(f"   Supabase Admin: {'✅' if supabase_admin else '❌ (SUPABASE_SERVICE_KEY ausente)'}")
    logger.info(f"   Cookies yt-dlp: {'✅' if YTDLP_COOKIES_FILE and Path(YTDLP_COOKIES_FILE).exists() else '❌'}")
    yield
    logger.info("🛑 Encerrada")


app = FastAPI(title="EditMind API", version="3.1.0", lifespan=lifespan)

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
    def senha_ok(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Senha deve ter pelo menos 6 caracteres.")
        return v


class EsqueciSenhaRequest(BaseModel):
    email: EmailStr


class RedefinirSenhaRequest(BaseModel):
    token: str
    nova_senha: str

    @field_validator("nova_senha")
    @classmethod
    def senha_ok(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Senha deve ter pelo menos 6 caracteres.")
        return v


class YouTubeRequest(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def url_yt(cls, v: str) -> str:
        if "youtube.com" not in v and "youtu.be" not in v:
            raise ValueError("URL deve ser do YouTube.")
        return v.strip()


# ══════════════════════════════════════════════════════════════
# DEPENDÊNCIA DE AUTH
# ══════════════════════════════════════════════════════════════

async def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    """Valida o Bearer token do Supabase e extrai id/email do usuário."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Token ausente.", headers={"WWW-Authenticate": "Bearer"})
    if not supabase:
        raise HTTPException(503, "Serviço de auth indisponível.")

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(401, "Token ausente.", headers={"WWW-Authenticate": "Bearer"})

    try:
        resp = await asyncio.to_thread(supabase.auth.get_user, token)
        if not resp or not resp.user:
            raise ValueError("Usuário não encontrado no token")

        user_email = getattr(resp.user, "email", None)
        user_id = getattr(resp.user, "id", None)
        if not user_email and not user_id:
            raise ValueError("Token sem email/id")

        return {"id": user_id, "email": user_email}
    except Exception as e:
        logger.warning(f"Falha ao validar token Supabase: {e}")
        raise HTTPException(401, "Sessão inválida ou expirada.")


async def get_usuario(authorization: Optional[str] = Header(None)) -> dict:
    """Compatibilidade retroativa."""
    return await get_current_user(authorization)


# ══════════════════════════════════════════════════════════════
# HELPERS — FFMPEG ASSÍNCRONO
# ══════════════════════════════════════════════════════════════

async def _ffmpeg(*args: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg falhou: {stderr.decode(errors='replace')[-400:]}")


async def obter_metadados(caminho: str) -> dict:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", "-show_format", caminho,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return {"resolucao": "N/A", "fps": "N/A", "duracao_segundos": "0"}

    dados = json.loads(stdout.decode())
    stream = next((s for s in dados.get("streams", []) if s.get("codec_type") == "video"), {})
    res = f"{stream.get('width', '?')}x{stream.get('height', '?')}"

    try:
        n, d = stream.get("r_frame_rate", "0/1").split("/")
        fps = round(int(n) / int(d), 2)
    except Exception:
        fps = 0

    dur = round(float(dados.get("format", {}).get("duration", 0)), 2)
    return {"resolucao": res, "fps": str(fps), "duracao_segundos": str(dur)}


async def extrair_audio(video: str, audio: str) -> None:
    await _ffmpeg(
        "-y", "-i", video, "-vn",
        "-acodec", "libmp3lame", "-ar", "16000", "-ac", "1", "-b:a", "32k", audio
    )


async def cortar_video(entrada: str, saida: str, inicio: float, fim: float) -> None:
    await _ffmpeg(
        "-y", "-ss", str(inicio), "-to", str(fim), "-i", entrada,
        "-c", "copy", "-avoid_negative_ts", "1", "-movflags", "+faststart", saida
    )


def ts(s: float) -> str:
    s = int(s)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def sanitizar(nome: str) -> str:
    return re.sub(r"[^\w.\-]", "_", Path(nome).name)[:100]


# ══════════════════════════════════════════════════════════════
# HELPERS — YT-DLP (ANTI-BOT)
# ══════════════════════════════════════════════════════════════

async def _ytdlp_download(url: str, output_path: str) -> None:
    args = [
        "yt-dlp",
        "-f", "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/bestvideo[ext=mp4]+bestaudio/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "--max-filesize", "200m",
        "--no-playlist",
        "--no-check-certificates",
        "--extractor-retries", "3",
        "--retries", "3",
        "--fragment-retries", "3",
        "--file-access-retries", "3",
        "--socket-timeout", "30",
        "--no-cache-dir",
        "--extractor-args", YTDLP_EXTRACTOR_ARGS,
        "--user-agent", YT_DLP_USER_AGENT,
        "--add-header", "Accept-Language:pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "--add-header", "Accept:text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "--no-geo-bypass",
    ]

    if YTDLP_COOKIES_FILE and Path(YTDLP_COOKIES_FILE).exists():
        logger.info("yt-dlp usando arquivo de cookies configurado via YTDLP_COOKIES_FILE")
        args.extend(["--cookies", YTDLP_COOKIES_FILE])

    args.extend(["-o", output_path, url])

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

    if proc.returncode != 0:
        stderr_txt = stderr.decode(errors="replace")
        logger.error(f"yt-dlp stderr: {stderr_txt[-500:]}")

        if "Sign in" in stderr_txt or "confirm" in stderr_txt.lower() or "bot" in stderr_txt.lower():
            hint = (
                "O YouTube bloqueou o download automático. "
                "Tente novamente em alguns minutos, use o upload direto de arquivo"
                " ou configure YTDLP_COOKIES_FILE no Render com um cookies.txt exportado do navegador."
            )
            raise HTTPException(403, hint)

        raise RuntimeError(f"yt-dlp falhou: {stderr_txt[-300:]}")


# ══════════════════════════════════════════════════════════════
# HELPERS — OPENAI ASSÍNCRONO
# ══════════════════════════════════════════════════════════════

async def transcrever(audio_path: str) -> str:
    if not openai_client:
        raise RuntimeError("OPENAI_API_KEY não configurada.")

    mb = Path(audio_path).stat().st_size / 1024 / 1024
    if mb > 24:
        raise HTTPException(413, f"Áudio muito grande ({mb:.1f}MB). Máx: 25MB.")

    with open(audio_path, "rb") as f:
        resp = await openai_client.audio.transcriptions.create(
            model="whisper-1", file=f, language="pt", response_format="text"
        )

    texto = resp if isinstance(resp, str) else getattr(resp, "text", "")

    corr = await openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "Corrija erros de transcrição, pontuação e concordância em português brasileiro. "
                    "NÃO resuma nem invente. Retorne APENAS o texto corrigido."
                ),
            },
            {"role": "user", "content": texto},
        ],
        temperature=0.1,
        max_tokens=4000,
    )
    return corr.choices[0].message.content.strip()


async def analisar_viral(transcricao: str, duracao: float) -> dict:
    if not openai_client:
        raise RuntimeError("OPENAI_API_KEY não configurada.")

    resp = await openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": (
                    "Você é editor especialista em TikTok, Reels e Shorts. "
                    "Escolha trecho de 15–60s com maior potencial viral. "
                    f"Vídeo tem {duracao:.1f}s. Responda SÓ JSON válido, sem markdown."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Transcrição:\n{transcricao}\n\n"
                    '{"inicio": 12.5, "fim": 42.8, "motivo": "..."}'
                ),
            },
        ],
        temperature=0.2,
        max_tokens=200,
        response_format={"type": "json_object"},
    )

    d = json.loads(resp.choices[0].message.content)
    ini = max(0.0, float(d.get("inicio", 0)))
    fim = min(float(d.get("fim", min(60, duracao))), duracao)
    if fim <= ini:
        fim = min(ini + 30, duracao)

    d["inicio"] = round(ini, 2)
    d["fim"] = round(fim, 2)
    return d


# ══════════════════════════════════════════════════════════════
# HELPERS — SUPABASE STORAGE + DATABASE
# ══════════════════════════════════════════════════════════════

async def upload_storage(caminho_local: str, nome_arquivo: str) -> Optional[str]:
    """
    Faz upload para o bucket 'cortes' no Supabase Storage.
    Retorna a URL pública, ou None se o Storage não estiver configurado.
    """
    if not supabase_admin:
        logger.warning("SUPABASE_SERVICE_KEY não configurada — Storage desativado, usando fallback local.")
        return None

    try:
        with open(caminho_local, "rb") as f:
            dados = f.read()

        await asyncio.to_thread(
            lambda: supabase_admin.storage.from_(STORAGE_BUCKET).upload(
                nome_arquivo,
                dados,
                {
                    "content-type": "video/mp4",
                    "upsert": "true",
                },
            )
        )

        url_resp = await asyncio.to_thread(
            lambda: supabase_admin.storage.from_(STORAGE_BUCKET).get_public_url(nome_arquivo)
        )

        if isinstance(url_resp, str):
            url = url_resp
        else:
            url = url_resp.get("publicUrl") or url_resp.get("data", {}).get("publicUrl", "")

        logger.info(f"Storage: arquivo salvo → {url}")
        return url or None

    except Exception as e:
        logger.error(f"Storage upload falhou: {e}")
        return None


async def salvar_registro_corte(user_email: str, video_url: str, titulo: str) -> None:
    """Persiste o corte vinculado ao usuário autenticado."""
    if not user_email:
        raise ValueError("user_email é obrigatório para salvar o corte.")
    if not supabase_admin:
        logger.warning("SUPABASE_SERVICE_KEY não configurada — registro do corte não foi salvo no banco.")
        return

    payload = {
        "user_email": user_email,
        "video_url": video_url,
        "titulo": titulo,
    }

    try:
        await asyncio.to_thread(
            lambda: supabase_admin.table("cortes").insert(payload).execute()
        )
        logger.info(f"DB: corte vinculado ao usuário {user_email}")
    except Exception as e:
        logger.error(f"Erro ao salvar corte no Supabase: {e}")
        raise


# ══════════════════════════════════════════════════════════════
# PIPELINE CENTRAL
# ══════════════════════════════════════════════════════════════

async def _pipeline(video_path: str, job_id: str, tasks: BackgroundTasks, pasta_temp: Path) -> dict:
    metadados = await obter_metadados(video_path)
    duracao = float(metadados["duracao_segundos"])
    logger.info(f"Job {job_id} | metadados: {metadados}")

    if duracao > MAX_DURACAO_S:
        raise HTTPException(413, f"Vídeo longo demais ({int(duracao)}s). Máx: {MAX_DURACAO_S}s.")

    audio_path = str(pasta_temp / "audio.mp3")
    logger.info(f"Job {job_id} | extraindo áudio...")
    await extrair_audio(video_path, audio_path)

    logger.info(f"Job {job_id} | transcrevendo...")
    transcricao = await transcrever(audio_path)

    logger.info(f"Job {job_id} | analisando viralidade...")
    analise = await analisar_viral(transcricao, duracao)
    logger.info(f"Job {job_id} | corte: {analise['inicio']}s → {analise['fim']}s")

    nome_saida = f"corte_{job_id}.mp4"
    caminho_local = str(OUTPUT_DIR / nome_saida)
    logger.info(f"Job {job_id} | cortando vídeo...")
    await cortar_video(video_path, caminho_local, analise["inicio"], analise["fim"])

    url_publica = await upload_storage(caminho_local, nome_saida)

    tasks.add_task(shutil.rmtree, pasta_temp, ignore_errors=True)
    if url_publica:
        tasks.add_task(lambda p=caminho_local: Path(p).unlink(missing_ok=True))

    url_corte = url_publica or f"/outputs/{nome_saida}"

    return {
        "status": "sucesso",
        "transcricao": transcricao,
        "corte_sugerido": {
            "inicio": ts(analise["inicio"]),
            "fim": ts(analise["fim"]),
            "inicio_segundos": analise["inicio"],
            "fim_segundos": analise["fim"],
            "motivo": analise.get("motivo", "Trecho viral identificado."),
        },
        "detalhes_tecnicos": metadados,
        "url_corte": url_corte,
        "storage": "supabase" if url_publica else "local",
    }


# ══════════════════════════════════════════════════════════════
# ENDPOINTS — AUTH
# ══════════════════════════════════════════════════════════════

@app.post("/api/auth/cadastro")
async def cadastro(dados: AuthRequest):
    if not supabase:
        raise HTTPException(503, "Auth indisponível.")
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
        return {"sucesso": True, "msg": "Confirme o seu e-mail para ativar a conta."}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/auth/login")
async def login(dados: AuthRequest):
    if not supabase:
        raise HTTPException(503, "Auth indisponível.")
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
        raise HTTPException(401, "E-mail ou senha incorretos.")


@app.post("/api/auth/esqueci-senha")
async def esqueci_senha(dados: EsqueciSenhaRequest):
    if not supabase:
        raise HTTPException(503, "Auth indisponível.")
    try:
        redirect = f"{SITE_URL}/redefinir-senha.html"
        await asyncio.to_thread(
            supabase.auth.reset_password_email,
            dados.email,
            {"redirect_to": redirect},
        )
        return {"sucesso": True, "msg": "Se esse e-mail existir, você receberá as instruções."}
    except Exception as e:
        logger.error(f"Erro ao enviar reset: {e}")
        return {"sucesso": True, "msg": "Se esse e-mail existir, você receberá as instruções."}


@app.post("/api/auth/redefinir-senha")
async def redefinir_senha(dados: RedefinirSenhaRequest):
    if not supabase_admin:
        raise HTTPException(503, "Admin indisponível. Configure SUPABASE_SERVICE_KEY.")
    if not supabase:
        raise HTTPException(503, "Auth indisponível.")

    try:
        user_resp = await asyncio.to_thread(supabase.auth.get_user, dados.token)
        if not user_resp or not user_resp.user:
            raise ValueError("Token inválido")

        user_id = user_resp.user.id
        await asyncio.to_thread(
            supabase_admin.auth.admin.update_user_by_id,
            user_id,
            {"password": dados.nova_senha},
        )
        return {"sucesso": True, "msg": "Senha atualizada com sucesso."}
    except Exception as e:
        raise HTTPException(400, f"Token inválido ou expirado: {e}")


# ══════════════════════════════════════════════════════════════
# ENDPOINTS — PROCESSAMENTO
# ══════════════════════════════════════════════════════════════

@app.post("/api/processar")
async def processar_video(
    tasks: BackgroundTasks,
    file: UploadFile = File(...),
    usuario: dict = Depends(get_current_user),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in EXTS_VALIDAS:
        raise HTTPException(400, f"Formato inválido. Use: {', '.join(EXTS_VALIDAS)}")

    job_id = str(uuid.uuid4())[:8]
    pasta_temp = Path(tempfile.mkdtemp(prefix=f"editmind_{job_id}_"))
    logger.info(f"Job {job_id} | usuário: {usuario['email']} | {file.filename}")

    try:
        nome = sanitizar(file.filename or f"video{ext}")
        video_path = pasta_temp / nome
        tamanho = 0

        with open(video_path, "wb") as f_out:
            while chunk := await file.read(1024 * 1024):
                tamanho += len(chunk)
                if tamanho > MAX_BYTES:
                    raise HTTPException(413, "Arquivo muito grande. Máx 200MB.")
                f_out.write(chunk)

        logger.info(f"Job {job_id} | salvo: {tamanho / 1024 / 1024:.1f}MB")
        resultado = await _pipeline(str(video_path), job_id, tasks, pasta_temp)

        await salvar_registro_corte(
            user_email=usuario.get("email") or usuario.get("id"),
            video_url=resultado.get("url_corte", ""),
            titulo=file.filename or f"upload_{job_id}",
        )
        return JSONResponse(resultado)

    except HTTPException:
        shutil.rmtree(pasta_temp, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(pasta_temp, ignore_errors=True)
        logger.error(f"Job {job_id} | erro: {e}")
        raise HTTPException(500, str(e))


@app.post("/api/processar-youtube")
async def processar_youtube(
    tasks: BackgroundTasks,
    dados: YouTubeRequest,
    usuario: dict = Depends(get_current_user),
):
    job_id = str(uuid.uuid4())[:8]
    pasta_temp = Path(tempfile.mkdtemp(prefix=f"editmind_yt_{job_id}_"))
    video_path = str(pasta_temp / "video.mp4")

    logger.info(f"YT Job {job_id} | usuário: {usuario['email']} | {dados.url}")

    try:
        await _ytdlp_download(dados.url, video_path)
        logger.info(f"YT Job {job_id} | download concluído")

        resultado = await _pipeline(video_path, job_id, tasks, pasta_temp)
        await salvar_registro_corte(
            user_email=usuario.get("email") or usuario.get("id"),
            video_url=resultado.get("url_corte", ""),
            titulo=dados.url,
        )
        return JSONResponse(resultado)

    except asyncio.TimeoutError:
        shutil.rmtree(pasta_temp, ignore_errors=True)
        raise HTTPException(408, "Timeout: vídeo demorou demais para baixar.")
    except HTTPException:
        shutil.rmtree(pasta_temp, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(pasta_temp, ignore_errors=True)
        logger.error(f"YT Job {job_id} | erro: {e}")
        raise HTTPException(500, str(e))


@app.post("/api/download-youtube")
async def download_youtube(
    tasks: BackgroundTasks,
    dados: YouTubeRequest,
    usuario: dict = Depends(get_current_user),
):
    """Baixa o vídeo do YouTube e devolve como stream para o cliente."""
    job_id = str(uuid.uuid4())[:8]
    pasta_temp = Path(tempfile.mkdtemp(prefix=f"editmind_dl_{job_id}_"))
    video_path = str(pasta_temp / "video.mp4")

    logger.info(f"DL Job {job_id} | usuário: {usuario['email']} | {dados.url}")

    try:
        await _ytdlp_download(dados.url, video_path)

        file_size = Path(video_path).stat().st_size
        logger.info(f"DL Job {job_id} | {file_size / 1024 / 1024:.1f}MB baixado")

        def iterfile():
            try:
                with open(video_path, "rb") as f:
                    while chunk := f.read(1024 * 1024):
                        yield chunk
            finally:
                shutil.rmtree(pasta_temp, ignore_errors=True)

        return StreamingResponse(
            iterfile(),
            media_type="video/mp4",
            headers={
                "Content-Disposition": 'attachment; filename="Video_EditMind.mp4"',
                "Content-Length": str(file_size),
            },
        )

    except asyncio.TimeoutError:
        shutil.rmtree(pasta_temp, ignore_errors=True)
        raise HTTPException(408, "Timeout: vídeo demorou demais para baixar.")
    except HTTPException:
        shutil.rmtree(pasta_temp, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(pasta_temp, ignore_errors=True)
        logger.error(f"DL Job {job_id} | erro: {e}")
        raise HTTPException(500, str(e))


# ══════════════════════════════════════════════════════════════
# ENDPOINT — HISTÓRICO DO USUÁRIO
# ══════════════════════════════════════════════════════════════

@app.get("/api/meus-cortes")
async def meus_cortes(usuario: dict = Depends(get_current_user)):
    if not supabase_admin:
        raise HTTPException(503, "Banco indisponível.")

    try:
        resp = await asyncio.to_thread(
            lambda: supabase_admin.table("cortes")
            .select("id, user_email, video_url, titulo, criado_em")
            .eq("user_email", usuario["email"])
            .order("criado_em", desc=True)
            .execute()
        )
        return {"sucesso": True, "cortes": resp.data or []}
    except Exception as e:
        logger.error(f"Erro ao buscar cortes do usuário: {e}")
        raise HTTPException(500, "Erro ao buscar histórico de cortes.")


# ══════════════════════════════════════════════════════════════
# HEALTH CHECK
# ══════════════════════════════════════════════════════════════

@app.get("/")
async def health():
    return {
        "status": "online",
        "api": "EditMind",
        "versao": "3.1.0",
        "servicos": {
            "openai": "ok" if OPENAI_API_KEY else "ausente",
            "supabase_auth": "ok" if supabase else "ausente",
            "supabase_storage": "ok" if supabase_admin else "ausente (SUPABASE_SERVICE_KEY)",
        },
    }
