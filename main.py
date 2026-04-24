"""
EditMind API v5.0
=================
Stack : FastAPI · OpenAI (Whisper-1 + GPT-4o) · FFmpeg · Supabase
Deploy: Render (backend) + Vercel (frontend)

V5
--
- Múltiplos recortes por vídeo (1 a 3), com foco e duração individual.
- Prompt de análise viral reforçado para avaliar o vídeo inteiro e evitar vício no início.
- Endpoints genéricos para YouTube/TikTok: /api/processar-link e /api/download-link.
- Download real de recortes via /api/cortes/download com Content-Disposition attachment.
- Opção de renderização vertical 9:16 sem achatar o vídeo.
- MAX_DURACAO_S configurável por ambiente, com default seguro para Render Free.
"""

import os
import re
import json
import uuid
import asyncio
import tempfile
import shutil
import logging
import zipfile
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional, Any
from urllib.parse import urlparse, unquote

import httpx
from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Depends, Header, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, field_validator, Field
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

# Default seguro para Render Free. Para 30 minutos, configure MAX_DURACAO_S=1800 no Render.
MAX_DURACAO_S = int(os.getenv("MAX_DURACAO_S", "660"))
MAX_BYTES = int(os.getenv("MAX_BYTES", str(200 * 1024 * 1024)))

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

EXTS_VALIDAS = {".mp4", ".mov", ".avi", ".webm"}
DOMINIOS_SUPORTADOS = {"youtube.com", "www.youtube.com", "youtu.be", "tiktok.com", "www.tiktok.com", "vm.tiktok.com"}

YT_DLP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

DURACAO_CONFIGS = {
    "curto": {"label": "< 30s", "min": 10.0, "max": 29.0, "target": 24.0},
    "medio": {"label": "30s - 60s", "min": 30.0, "max": 60.0, "target": 45.0},
    "longo": {"label": "> 60s", "min": 61.0, "max": 90.0, "target": 75.0},
}

FOCOS_VALIDOS = {
    "Livre", "Humor", "Terror", "Emocionante", "Triste", "Polêmico", "Educativo",
    "Impactante", "Motivacional", "Surpreendente"
}


# ══════════════════════════════════════════════════════════════
# STARTUP
# ══════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 EditMind v5.2 iniciada")
    logger.info(f"   OpenAI        : {'✅' if OPENAI_API_KEY else '❌'}")
    logger.info(f"   Supabase Auth : {'✅' if supabase else '❌'}")
    logger.info(f"   Supabase Admin: {'✅' if supabase_admin else '❌ (SUPABASE_SERVICE_KEY ausente)'}")
    logger.info(f"   MAX_DURACAO_S : {MAX_DURACAO_S}s")
    logger.info(f"   Cookies yt-dlp: {'✅' if YTDLP_COOKIES_FILE and Path(YTDLP_COOKIES_FILE).exists() else '❌'}")
    yield
    logger.info("🛑 Encerrada")


app = FastAPI(title="EditMind API", version="5.2.0", lifespan=lifespan)

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


class AtualizarNomeRequest(BaseModel):
    nome: str

    @field_validator("nome")
    @classmethod
    def nome_ok(cls, v: str) -> str:
        nome = (v or "").strip()
        if not nome:
            raise ValueError("Nome é obrigatório.")
        if len(nome) > 80:
            raise ValueError("Nome deve ter no máximo 80 caracteres.")
        return nome


class AtualizarEmailRequest(BaseModel):
    email: EmailStr


class AtualizarSenhaRequest(BaseModel):
    nova_senha: str

    @field_validator("nova_senha")
    @classmethod
    def senha_ok(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Senha deve ter pelo menos 6 caracteres.")
        return v


class BulkDeleteRequest(BaseModel):
    ids: list[str]

    @field_validator("ids")
    @classmethod
    def ids_ok(cls, v: list[str]) -> list[str]:
        ids = [str(i).strip() for i in (v or []) if str(i).strip()]
        if not ids:
            raise ValueError("Informe ao menos um ID.")
        return ids[:100]


class CorteConfig(BaseModel):
    duracao_tipo: str = "medio"
    foco: str = "Livre"

    @field_validator("duracao_tipo")
    @classmethod
    def duracao_ok(cls, v: str) -> str:
        v = (v or "medio").strip().lower()
        aliases = {"rapido": "curto", "rápido": "curto", "padrao": "medio", "padrão": "medio", "profundo": "longo"}
        v = aliases.get(v, v)
        if v not in DURACAO_CONFIGS:
            return "medio"
        return v

    @field_validator("foco")
    @classmethod
    def foco_ok(cls, v: str) -> str:
        v = (v or "Livre").strip()
        return v if v in FOCOS_VALIDOS else "Livre"


class ProcessamentoConfig(BaseModel):
    cortes: list[CorteConfig] = Field(default_factory=lambda: [CorteConfig()])
    formato_vertical: bool = False

    @field_validator("cortes")
    @classmethod
    def cortes_ok(cls, v: list[CorteConfig]) -> list[CorteConfig]:
        if not v:
            return [CorteConfig()]
        return v[:3]


class LinkRequest(BaseModel):
    url: str
    config: Optional[ProcessamentoConfig] = None
    cortes: Optional[list[CorteConfig]] = None
    formato_vertical: bool = False

    @field_validator("url")
    @classmethod
    def url_suportada(cls, v: str) -> str:
        v = v.strip()
        validar_url_midia(v)
        return v


class YouTubeRequest(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def url_yt(cls, v: str) -> str:
        v = v.strip()
        if "youtube.com" not in v and "youtu.be" not in v:
            raise ValueError("URL deve ser do YouTube.")
        return v


# ══════════════════════════════════════════════════════════════
# VALIDAÇÃO / AUTH
# ══════════════════════════════════════════════════════════════

def dominio_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower().replace("www.", "www.")
    return host


def validar_url_midia(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if not parsed.scheme.startswith("http") or host not in DOMINIOS_SUPORTADOS:
        raise ValueError("URL suportada apenas para YouTube ou TikTok.")


def eh_tiktok_url(url: str) -> bool:
    host = (urlparse(url).netloc or "").lower()
    return "tiktok.com" in host


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

        user_meta = getattr(resp.user, "user_metadata", {}) or {}
        return {"id": user_id, "email": user_email, "token": token, "user_metadata": user_meta}
    except Exception as e:
        logger.warning(f"Falha ao validar token Supabase: {e}")
        raise HTTPException(401, "Sessão inválida ou expirada.")


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
        raise RuntimeError(f"FFmpeg falhou: {stderr.decode(errors='replace')[-600:]}")


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


async def obter_info_codecs(caminho: str) -> dict:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", "-show_format", caminho,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return {"video_codec": "", "audio_codec": "", "format_name": ""}
    dados = json.loads(stdout.decode() or "{}")
    video = next((s for s in dados.get("streams", []) if s.get("codec_type") == "video"), {})
    audio = next((s for s in dados.get("streams", []) if s.get("codec_type") == "audio"), {})
    return {
        "video_codec": (video.get("codec_name") or "").lower(),
        "audio_codec": (audio.get("codec_name") or "").lower(),
        "format_name": (dados.get("format", {}).get("format_name") or "").lower(),
    }


async def normalizar_video_para_browser(entrada: str, saida: str, forcar_reencode: bool = False) -> str:
    info = await obter_info_codecs(entrada)
    video_ok = info["video_codec"] == "h264"
    audio_ok = info["audio_codec"] in {"aac", "mp4a"}
    formato_ok = "mp4" in info["format_name"] or "mov" in info["format_name"]
    precisa_reencode = forcar_reencode or not (video_ok and audio_ok and formato_ok)

    if not precisa_reencode:
        await _ffmpeg("-y", "-i", entrada, "-c", "copy", "-movflags", "+faststart", saida)
        return saida

    await _ffmpeg(
        "-y", "-i", entrada,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k", "-ac", "2",
        "-movflags", "+faststart",
        saida,
    )
    return saida


async def extrair_audio(video: str, audio: str) -> None:
    await _ffmpeg(
        "-y", "-i", video, "-vn",
        "-acodec", "libmp3lame", "-ar", "16000", "-ac", "1", "-b:a", "32k", audio
    )


async def cortar_video(entrada: str, saida: str, inicio: float, fim: float, formato_vertical: bool = False) -> None:
    if formato_vertical:
        # Vertical 9:16 sem achatamento: mantém proporção e adiciona padding.
        filtro = "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1"
        await _ffmpeg(
            "-y", "-ss", str(inicio), "-to", str(fim), "-i", entrada,
            "-vf", filtro,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart", saida
        )
    else:
        await _ffmpeg(
            "-y", "-ss", str(inicio), "-to", str(fim), "-i", entrada,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ac", "2",
            "-movflags", "+faststart", saida
        )


def ts(s: float) -> str:
    s = max(0, int(s))
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def sanitizar(nome: str) -> str:
    return re.sub(r"[^\w.\-]", "_", Path(nome).name)[:100]


def parse_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    return str(v).lower() in {"1", "true", "sim", "yes", "on"}


def parse_processamento_config(raw: Optional[str] = None, formato_vertical: Optional[str] = None) -> ProcessamentoConfig:
    if not raw:
        return ProcessamentoConfig(formato_vertical=parse_bool(formato_vertical))
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            data = {"cortes": data}
        if formato_vertical is not None:
            data["formato_vertical"] = parse_bool(formato_vertical)
        return ProcessamentoConfig(**data)
    except Exception as e:
        logger.warning(f"Config de cortes inválida, usando padrão: {e}")
        return ProcessamentoConfig(formato_vertical=parse_bool(formato_vertical))


def config_from_link_request(dados: LinkRequest) -> ProcessamentoConfig:
    if dados.config:
        return dados.config
    return ProcessamentoConfig(cortes=dados.cortes or [CorteConfig()], formato_vertical=dados.formato_vertical)


# ══════════════════════════════════════════════════════════════
# HELPERS — YT-DLP (YouTube/TikTok)
# ══════════════════════════════════════════════════════════════

async def _ytdlp_download(url: str, output_path: str) -> None:
    validar_url_midia(url)
    common_args = [
        "--merge-output-format", "mp4",
        "--max-filesize", "500m",
        "--no-playlist",
        "--no-check-certificates",
        "--extractor-retries", "5",
        "--retries", "8",
        "--fragment-retries", "8",
        "--file-access-retries", "8",
        "--socket-timeout", "30",
        "--retry-sleep", "2",
        "--sleep-requests", "1",
        "--sleep-interval", "1",
        "--max-sleep-interval", "4",
        "--no-cache-dir",
        "--extractor-args", YTDLP_EXTRACTOR_ARGS,
        "--user-agent", YT_DLP_USER_AGENT,
        "--add-header", "Accept-Language:pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "--add-header", "Accept:text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    ]
    formatos = [
        "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/bestvideo[ext=mp4]+bestaudio/best[ext=mp4]/best",
        "bv*[height<=720]+ba/b[height<=720]/best",
        "best",
    ]

    usar_cookies = bool(YTDLP_COOKIES_FILE and Path(YTDLP_COOKIES_FILE).exists())
    if YTDLP_COOKIES_FILE and not usar_cookies:
        logger.warning(f"YTDLP_COOKIES_FILE definido, mas arquivo não existe: {YTDLP_COOKIES_FILE}")

    tentativas = []
    for i, fmt in enumerate(formatos, start=1):
        tentativas.append({"nome": f"sem-cookies-f{i}", "formato": fmt, "cookies": False})
        if usar_cookies:
            tentativas.append({"nome": f"com-cookies-f{i}", "formato": fmt, "cookies": True})

    ultimo_erro = ""
    for idx, tentativa in enumerate(tentativas, start=1):
        args = ["yt-dlp", *common_args, "-f", tentativa["formato"]]
        if tentativa["cookies"]:
            args.extend(["--cookies", YTDLP_COOKIES_FILE])
        args.extend(["-o", output_path, url])

        logger.info(f"yt-dlp tentativa {idx}/{len(tentativas)} | estratégia={tentativa['nome']} | url={url}")
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=420)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            ultimo_erro = "Timeout no yt-dlp."
            logger.warning(f"yt-dlp tentativa {idx} expirou (timeout).")
            continue

        if proc.returncode == 0:
            logger.info(f"yt-dlp download concluído na tentativa {idx} ({tentativa['nome']}).")
            return

        stderr_txt = stderr.decode(errors="replace")
        ultimo_erro = stderr_txt[-700:]
        logger.warning(f"yt-dlp tentativa {idx} falhou: {ultimo_erro}")

    erro_l = ultimo_erro.lower()
    if "sign in" in erro_l or "confirm" in erro_l or "bot" in erro_l:
        raise HTTPException(
            403,
            "A plataforma bloqueou o download automático. Tente novamente, configure cookies no Render ou use upload manual.",
        )
    raise RuntimeError(f"Falha ao baixar vídeo após múltiplas tentativas: {ultimo_erro[-300:]}")


# ══════════════════════════════════════════════════════════════
# HELPERS — OPENAI
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


def _limites_duracao(tipo: str, duracao_video: float) -> tuple[float, float, float]:
    cfg = DURACAO_CONFIGS.get(tipo, DURACAO_CONFIGS["medio"])
    minimo = min(cfg["min"], max(1.0, duracao_video))
    maximo = min(cfg["max"], max(1.0, duracao_video))
    alvo = min(cfg["target"], maximo)
    if maximo < minimo:
        minimo = maximo
    return minimo, maximo, alvo


def _normalizar_cortes(cortes: list[dict], configs: list[CorteConfig], duracao: float) -> list[dict]:
    normalizados: list[dict] = []
    usados: list[tuple[float, float]] = []

    for idx, cfg in enumerate(configs, start=1):
        raw = next((c for c in cortes if int(c.get("index", idx)) == idx), cortes[idx - 1] if idx - 1 < len(cortes) else {})
        min_d, max_d, alvo_d = _limites_duracao(cfg.duracao_tipo, duracao)
        try:
            ini = float(raw.get("inicio", 0))
            fim = float(raw.get("fim", ini + alvo_d))
        except Exception:
            ini, fim = 0.0, alvo_d

        ini = max(0.0, min(ini, max(0.0, duracao - min_d)))
        dur = fim - ini
        if dur < min_d:
            fim = ini + min_d
        elif dur > max_d:
            fim = ini + max_d
        fim = min(fim, duracao)
        if fim <= ini:
            fim = min(duracao, ini + alvo_d)

        # Evita sobreposição forte entre múltiplos cortes quando possível.
        for u_ini, u_fim in usados:
            overlap = max(0.0, min(fim, u_fim) - max(ini, u_ini))
            if overlap > 5 and duracao > max_d * (len(configs) + 1):
                novo_ini = min(max(0.0, u_fim + 8), max(0.0, duracao - (fim - ini)))
                ini, fim = novo_ini, min(duracao, novo_ini + (fim - ini))

        usados.append((ini, fim))
        normalizados.append({
            "index": idx,
            "inicio": round(ini, 2),
            "fim": round(fim, 2),
            "motivo": str(raw.get("motivo") or f"Trecho escolhido para foco {cfg.foco}.")[:500],
            "foco": cfg.foco,
            "duracao_tipo": cfg.duracao_tipo,
        })

    return normalizados


async def analisar_viral_multiplos(transcricao: str, duracao: float, configs: list[CorteConfig]) -> list[dict]:
    if not openai_client:
        raise RuntimeError("OPENAI_API_KEY não configurada.")

    pedidos = []
    for i, cfg in enumerate(configs, start=1):
        min_d, max_d, alvo_d = _limites_duracao(cfg.duracao_tipo, duracao)
        pedidos.append({
            "index": i,
            "duracao_tipo": cfg.duracao_tipo,
            "duracao_minima": min_d,
            "duracao_maxima": max_d,
            "foco": cfg.foco,
        })

    system = (
        "Você é editor especialista em TikTok, Reels e Shorts. "
        "Você deve avaliar o conteúdo inteiro do vídeo, incluindo começo, meio e fim. "
        "NÃO escolha automaticamente o início do vídeo. Em vídeos longos, evite concentrar todos os cortes nos primeiros 60 segundos. "
        "Procure picos reais de valor: humor, tensão, virada narrativa, emoção, frase de impacto, surpresa, conflito, aprendizado ou clímax. "
        "Respeite o foco solicitado para cada corte. Para múltiplos cortes, evite trechos redundantes ou muito sobrepostos. "
        "Retorne somente JSON válido, sem markdown."
    )
    user = {
        "duracao_video_segundos": duracao,
        "pedidos": pedidos,
        "formato_resposta": {
            "cortes": [
                {"index": 1, "inicio": 12.5, "fim": 42.8, "motivo": "motivo objetivo"}
            ]
        },
        "transcricao_completa": transcricao,
    }

    resp = await openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
        temperature=0.25,
        max_tokens=900,
        response_format={"type": "json_object"},
    )

    try:
        data = json.loads(resp.choices[0].message.content)
        cortes_raw = data.get("cortes", [])
        if not isinstance(cortes_raw, list):
            cortes_raw = []
    except Exception as e:
        logger.warning(f"Resposta da IA inválida, usando fallback: {e}")
        cortes_raw = []

    if not cortes_raw:
        # Fallback distribui cortes ao longo do vídeo para evitar vício no início.
        cortes_raw = []
        total = len(configs)
        for i, cfg in enumerate(configs, start=1):
            _, _, alvo = _limites_duracao(cfg.duracao_tipo, duracao)
            centro = duracao * (i / (total + 1))
            ini = max(0.0, centro - alvo / 2)
            cortes_raw.append({"index": i, "inicio": ini, "fim": ini + alvo, "motivo": "Fallback distribuído ao longo do vídeo."})

    return _normalizar_cortes(cortes_raw, configs, duracao)


# ══════════════════════════════════════════════════════════════
# HELPERS — SUPABASE STORAGE + DATABASE
# ══════════════════════════════════════════════════════════════

async def upload_storage(caminho_local: str, nome_arquivo: str) -> Optional[str]:
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
                {"content-type": "video/mp4", "upsert": "true"},
            )
        )

        url_resp = await asyncio.to_thread(
            lambda: supabase_admin.storage.from_(STORAGE_BUCKET).get_public_url(nome_arquivo)
        )
        url = url_resp if isinstance(url_resp, str) else (
            url_resp.get("publicUrl") or url_resp.get("data", {}).get("publicUrl", "")
        )
        logger.info(f"Storage: arquivo salvo → {url}")
        return url or None

    except Exception as e:
        logger.error(f"Storage upload falhou: {e}")
        return None


async def salvar_registro_corte(
    user_email: str,
    video_url: str,
    titulo: str,
    corte: Optional[dict] = None,
    formato_vertical: bool = False,
) -> Optional[dict]:
    if not user_email:
        raise ValueError("user_email é obrigatório para salvar o corte.")
    if not supabase_admin:
        logger.warning("SUPABASE_SERVICE_KEY não configurada — registro do corte não foi salvo no banco.")
        return None

    corte = corte or {}
    payload = {
        "user_email": user_email,
        "video_url": video_url,
        "titulo": titulo,
        "inicio_segundos": corte.get("inicio"),
        "fim_segundos": corte.get("fim"),
        "foco": corte.get("foco"),
        "duracao_tipo": corte.get("duracao_tipo"),
        "formato_vertical": formato_vertical,
    }
    payload_limpo = {k: v for k, v in payload.items() if v is not None}
    payload_basico = {"user_email": user_email, "video_url": video_url, "titulo": titulo}

    try:
        resp = await asyncio.to_thread(
            lambda: supabase_admin.table("cortes").insert(payload_limpo).execute()
        )
        logger.info(f"DB: corte vinculado ao usuário {user_email}")
        return (resp.data or [None])[0]
    except Exception as e:
        logger.warning(f"Insert estendido falhou; tentando payload básico. Erro: {e}")
        resp = await asyncio.to_thread(
            lambda: supabase_admin.table("cortes").insert(payload_basico).execute()
        )
        return (resp.data or [None])[0]


def _extrair_objeto_storage(video_url: str) -> Optional[str]:
    if not video_url:
        return None

    padroes = ("/storage/v1/object/public/cortes/", "/storage/v1/object/cortes/")
    for padrao in padroes:
        if padrao in video_url:
            return unquote(video_url.split(padrao, 1)[1]).lstrip("/")

    parsed = urlparse(video_url)
    if parsed.path.startswith("/storage/v1/object/public/cortes/"):
        return unquote(parsed.path.replace("/storage/v1/object/public/cortes/", "", 1)).lstrip("/")
    if parsed.path.startswith("/storage/v1/object/cortes/"):
        return unquote(parsed.path.replace("/storage/v1/object/cortes/", "", 1)).lstrip("/")
    return None


def _normalizar_video_url(video_url: str) -> str:
    if not video_url:
        return ""
    valor = video_url.strip()
    if valor.startswith("/outputs/"):
        return valor
    objeto = _extrair_objeto_storage(valor)
    if objeto:
        return f"storage:{objeto}"
    parsed = urlparse(valor)
    if parsed.path.startswith("/outputs/"):
        return parsed.path
    return valor


async def _remover_arquivo_corte(video_url: str) -> None:
    if not video_url:
        return

    objeto_storage = _extrair_objeto_storage(video_url)
    if objeto_storage:
        if not supabase_admin:
            raise RuntimeError("SUPABASE_SERVICE_KEY ausente para remover arquivo do Storage.")
        logger.info(f"DELETE corte | removendo arquivo do Storage: {objeto_storage}")
        await asyncio.to_thread(lambda: supabase_admin.storage.from_(STORAGE_BUCKET).remove([objeto_storage]))
        return

    if video_url.startswith("/outputs/"):
        arquivo_local = Path(video_url.removeprefix("/")).resolve()
        base_outputs = OUTPUT_DIR.resolve()
        if base_outputs in arquivo_local.parents and arquivo_local.exists():
            logger.info(f"DELETE corte | removendo arquivo local: {arquivo_local}")
            arquivo_local.unlink(missing_ok=True)
        return


def _nome_fallback(email: Optional[str]) -> str:
    if not email:
        return "Usuário"
    return email.split("@")[0]


async def _obter_perfil_usuario(usuario: dict) -> dict:
    user_id = usuario.get("id")
    email = usuario.get("email") or ""
    nome_meta = (usuario.get("user_metadata") or {}).get("nome") or (usuario.get("user_metadata") or {}).get("name")
    nome = nome_meta or _nome_fallback(email)

    perfil = None
    if supabase_admin and user_id:
        try:
            resp = await asyncio.to_thread(
                lambda: supabase_admin.table("profiles")
                .select("id,user_id,email,nome,criado_em,atualizado_em")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            perfil = (resp.data or [None])[0]
        except Exception as e:
            logger.warning(f"Não foi possível ler perfil: {e}")

    if perfil:
        nome = (perfil.get("nome") or "").strip() or nome
        email = perfil.get("email") or email
        return {"id": perfil.get("id"), "user_id": user_id, "email": email, "nome": nome}

    if supabase_admin and user_id:
        payload = {"user_id": user_id, "email": email, "nome": nome}
        try:
            upsert = await asyncio.to_thread(
                lambda: supabase_admin.table("profiles").upsert(payload, on_conflict="user_id").execute()
            )
            criado = (upsert.data or [None])[0]
            if criado:
                return {"id": criado.get("id"), "user_id": user_id, "email": criado.get("email"), "nome": criado.get("nome")}
        except Exception as e:
            logger.warning(f"Não foi possível criar perfil automaticamente: {e}")
    return {"id": None, "user_id": user_id, "email": email, "nome": nome}


async def _atualizar_auth_user(token: str, payload: dict) -> dict:
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise HTTPException(503, "Configuração do Supabase Auth ausente.")
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.put(f"{SUPABASE_URL}/auth/v1/user", headers=headers, json=payload)
    if resp.status_code >= 400:
        detalhe = resp.json().get("msg") if resp.headers.get("content-type", "").startswith("application/json") else resp.text
        raise HTTPException(400, detalhe or "Não foi possível atualizar dados da conta.")
    return resp.json()


# ══════════════════════════════════════════════════════════════
# PIPELINE CENTRAL
# ══════════════════════════════════════════════════════════════

async def _pipeline(video_path: str, job_id: str, tasks: BackgroundTasks, pasta_temp: Path, config: ProcessamentoConfig) -> dict:
    metadados = await obter_metadados(video_path)
    duracao = float(metadados["duracao_segundos"])
    logger.info(f"Job {job_id} | metadados: {metadados}")

    if duracao > MAX_DURACAO_S:
        raise HTTPException(
            413,
            f"Vídeo longo demais ({int(duracao)}s). Limite atual: {MAX_DURACAO_S}s. "
            "Para até 30 minutos, configure MAX_DURACAO_S=1800 em um plano Render adequado.",
        )

    audio_path = str(pasta_temp / "audio.mp3")
    logger.info(f"Job {job_id} | extraindo áudio...")
    await extrair_audio(video_path, audio_path)

    logger.info(f"Job {job_id} | transcrevendo...")
    transcricao = await transcrever(audio_path)

    logger.info(f"Job {job_id} | analisando viralidade para {len(config.cortes)} recorte(s)...")
    analises = await analisar_viral_multiplos(transcricao, duracao, config.cortes)

    cortes_resposta = []
    for analise in analises:
        idx = analise["index"]
        nome_saida = f"corte_{job_id}_{idx}.mp4" if len(analises) > 1 else f"corte_{job_id}.mp4"
        caminho_local = str(OUTPUT_DIR / nome_saida)
        logger.info(f"Job {job_id} | cortando recorte {idx}: {analise['inicio']}s → {analise['fim']}s")
        await cortar_video(video_path, caminho_local, analise["inicio"], analise["fim"], config.formato_vertical)

        url_publica = await upload_storage(caminho_local, nome_saida)
        if url_publica:
            tasks.add_task(lambda p=caminho_local: Path(p).unlink(missing_ok=True))
        url_corte = url_publica or f"/outputs/{nome_saida}"

        corte_info = {
            "index": idx,
            "inicio": ts(analise["inicio"]),
            "fim": ts(analise["fim"]),
            "inicio_segundos": analise["inicio"],
            "fim_segundos": analise["fim"],
            "duracao_segundos": round(analise["fim"] - analise["inicio"], 2),
            "motivo": analise.get("motivo", "Trecho viral identificado."),
            "foco": analise.get("foco", "Livre"),
            "duracao_tipo": analise.get("duracao_tipo", "medio"),
            "url_corte": url_corte,
            "storage": "supabase" if url_publica else "local",
            "formato_vertical": config.formato_vertical,
        }
        cortes_resposta.append(corte_info)

    tasks.add_task(shutil.rmtree, pasta_temp, ignore_errors=True)

    primeiro = cortes_resposta[0]
    return {
        "status": "sucesso",
        "transcricao": transcricao,
        "corte_sugerido": {k: primeiro[k] for k in ["inicio", "fim", "inicio_segundos", "fim_segundos", "motivo"]},
        "cortes": cortes_resposta,
        "detalhes_tecnicos": metadados,
        "url_corte": primeiro["url_corte"],
        "storage": primeiro["storage"],
    }


async def _salvar_cortes_do_resultado(usuario: dict, titulo_base: str, resultado: dict) -> dict:
    user_email = usuario.get("email") or usuario.get("id")
    for corte in resultado.get("cortes", []):
        titulo = titulo_base if len(resultado.get("cortes", [])) == 1 else f"{titulo_base} · Recorte {corte.get('index')}"
        registro = await salvar_registro_corte(
            user_email=user_email,
            video_url=corte.get("url_corte", ""),
            titulo=titulo,
            corte={"inicio": corte.get("inicio_segundos"), "fim": corte.get("fim_segundos"), "foco": corte.get("foco"), "duracao_tipo": corte.get("duracao_tipo")},
            formato_vertical=bool(corte.get("formato_vertical")),
        )
        if registro and registro.get("id"):
            corte["id"] = registro.get("id")
    return resultado


# ══════════════════════════════════════════════════════════════
# ENDPOINTS — AUTH
# ══════════════════════════════════════════════════════════════

@app.post("/api/auth/cadastro")
async def cadastro(dados: AuthRequest):
    if not supabase:
        raise HTTPException(503, "Auth indisponível.")
    try:
        res = await asyncio.to_thread(supabase.auth.sign_up, {"email": dados.email, "password": dados.senha})
        if res.session:
            return {"sucesso": True, "token": res.session.access_token, "usuario": {"email": dados.email}}
        return {"sucesso": True, "msg": "Confirme o seu e-mail para ativar a conta."}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/auth/login")
async def login(dados: AuthRequest):
    if not supabase:
        raise HTTPException(503, "Auth indisponível.")
    try:
        res = await asyncio.to_thread(supabase.auth.sign_in_with_password, {"email": dados.email, "password": dados.senha})
        return {"sucesso": True, "token": res.session.access_token, "usuario": {"email": dados.email}}
    except Exception:
        raise HTTPException(401, "E-mail ou senha incorretos.")


@app.post("/api/auth/esqueci-senha")
async def esqueci_senha(dados: EsqueciSenhaRequest):
    if not supabase:
        raise HTTPException(503, "Auth indisponível.")
    try:
        redirect = f"{SITE_URL}/redefinir-senha.html"
        await asyncio.to_thread(supabase.auth.reset_password_email, dados.email, {"redirect_to": redirect})
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
        await asyncio.to_thread(supabase_admin.auth.admin.update_user_by_id, user_resp.user.id, {"password": dados.nova_senha})
        return {"sucesso": True, "msg": "Senha atualizada com sucesso."}
    except Exception as e:
        raise HTTPException(400, f"Token inválido ou expirado: {e}")


@app.get("/api/user/profile")
async def obter_perfil(usuario: dict = Depends(get_current_user)):
    perfil = await _obter_perfil_usuario(usuario)
    return {"sucesso": True, "perfil": perfil}


@app.patch("/api/user/profile/name")
async def atualizar_nome(dados: AtualizarNomeRequest, usuario: dict = Depends(get_current_user)):
    if not supabase_admin:
        raise HTTPException(503, "Banco indisponível.")
    perfil = await _obter_perfil_usuario(usuario)
    await asyncio.to_thread(
        lambda: supabase_admin.table("profiles").upsert(
            {"user_id": usuario.get("id"), "email": perfil.get("email"), "nome": dados.nome},
            on_conflict="user_id",
        ).execute()
    )
    return {"sucesso": True, "mensagem": "Nome atualizado com sucesso.", "nome": dados.nome}


@app.patch("/api/user/profile/email")
async def atualizar_email(dados: AtualizarEmailRequest, usuario: dict = Depends(get_current_user)):
    token = usuario.get("token")
    if not token:
        raise HTTPException(401, "Token inválido.")
    _ = await _atualizar_auth_user(token, {"email": dados.email})
    if supabase_admin and usuario.get("id"):
        await asyncio.to_thread(
            lambda: supabase_admin.table("profiles").upsert(
                {"user_id": usuario.get("id"), "email": dados.email},
                on_conflict="user_id",
            ).execute()
        )
    return {
        "sucesso": True,
        "mensagem": "Solicitação de alteração de e-mail enviada. Verifique sua caixa de entrada para confirmar o novo e-mail no Supabase.",
    }


@app.patch("/api/user/profile/password")
async def atualizar_senha(dados: AtualizarSenhaRequest, usuario: dict = Depends(get_current_user)):
    token = usuario.get("token")
    if not token:
        raise HTTPException(401, "Token inválido.")
    await _atualizar_auth_user(token, {"password": dados.nova_senha})
    return {"sucesso": True, "mensagem": "Senha atualizada com sucesso."}


# ══════════════════════════════════════════════════════════════
# ENDPOINTS — PROCESSAMENTO
# ══════════════════════════════════════════════════════════════

@app.post("/api/processar")
async def processar_video(
    tasks: BackgroundTasks,
    file: UploadFile = File(...),
    cortes_config: Optional[str] = Form(None),
    formato_vertical: Optional[str] = Form(None),
    usuario: dict = Depends(get_current_user),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in EXTS_VALIDAS:
        raise HTTPException(400, f"Formato inválido. Use: {', '.join(EXTS_VALIDAS)}")

    config = parse_processamento_config(cortes_config, formato_vertical)
    job_id = str(uuid.uuid4())[:8]
    pasta_temp = Path(tempfile.mkdtemp(prefix=f"editmind_{job_id}_"))
    logger.info(f"Job {job_id} | usuário: {usuario['email']} | {file.filename} | cortes={len(config.cortes)} | vertical={config.formato_vertical}")

    try:
        nome = sanitizar(file.filename or f"video{ext}")
        video_path = pasta_temp / nome
        tamanho = 0
        with open(video_path, "wb") as f_out:
            while chunk := await file.read(1024 * 1024):
                tamanho += len(chunk)
                if tamanho > MAX_BYTES:
                    raise HTTPException(413, f"Arquivo muito grande. Máx {MAX_BYTES // 1024 // 1024}MB.")
                f_out.write(chunk)

        resultado = await _pipeline(str(video_path), job_id, tasks, pasta_temp, config)
        resultado = await _salvar_cortes_do_resultado(usuario, file.filename or f"upload_{job_id}", resultado)
        return JSONResponse(resultado)
    except HTTPException:
        shutil.rmtree(pasta_temp, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(pasta_temp, ignore_errors=True)
        logger.error(f"Job {job_id} | erro: {e}")
        raise HTTPException(500, str(e))


@app.post("/api/processar-link")
async def processar_link(tasks: BackgroundTasks, dados: LinkRequest, usuario: dict = Depends(get_current_user)):
    config = config_from_link_request(dados)
    job_id = str(uuid.uuid4())[:8]
    pasta_temp = Path(tempfile.mkdtemp(prefix=f"editmind_link_{job_id}_"))
    video_path = str(pasta_temp / "video.mp4")
    logger.info(f"Link Job {job_id} | usuário: {usuario['email']} | {dados.url} | cortes={len(config.cortes)}")
    try:
        await _ytdlp_download(dados.url, video_path)
        video_normalizado = str(pasta_temp / "video_browser.mp4")
        await normalizar_video_para_browser(video_path, video_normalizado, forcar_reencode=eh_tiktok_url(dados.url))
        resultado = await _pipeline(video_normalizado, job_id, tasks, pasta_temp, config)
        resultado = await _salvar_cortes_do_resultado(usuario, dados.url, resultado)
        return JSONResponse(resultado)
    except asyncio.TimeoutError:
        shutil.rmtree(pasta_temp, ignore_errors=True)
        raise HTTPException(408, "Timeout: vídeo demorou demais para baixar.")
    except HTTPException:
        shutil.rmtree(pasta_temp, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(pasta_temp, ignore_errors=True)
        logger.error(f"Link Job {job_id} | erro: {e}")
        raise HTTPException(500, str(e))


@app.post("/api/processar-youtube")
async def processar_youtube(tasks: BackgroundTasks, dados: YouTubeRequest, usuario: dict = Depends(get_current_user)):
    req = LinkRequest(url=dados.url)
    return await processar_link(tasks, req, usuario)


@app.post("/api/download-link")
async def download_link(tasks: BackgroundTasks, dados: LinkRequest, usuario: dict = Depends(get_current_user)):
    job_id = str(uuid.uuid4())[:8]
    pasta_temp = Path(tempfile.mkdtemp(prefix=f"editmind_dl_{job_id}_"))
    video_path = str(pasta_temp / "video.mp4")
    logger.info(f"DL Job {job_id} | usuário: {usuario['email']} | {dados.url}")
    try:
        await _ytdlp_download(dados.url, video_path)
        video_normalizado = str(pasta_temp / "video_browser.mp4")
        await normalizar_video_para_browser(video_path, video_normalizado, forcar_reencode=eh_tiktok_url(dados.url))
        file_size = Path(video_normalizado).stat().st_size

        def iterfile():
            try:
                with open(video_normalizado, "rb") as f:
                    while chunk := f.read(1024 * 1024):
                        yield chunk
            finally:
                shutil.rmtree(pasta_temp, ignore_errors=True)

        return StreamingResponse(
            iterfile(),
            media_type="video/mp4",
            headers={"Content-Disposition": 'attachment; filename="Video_EditMind.mp4"', "Content-Length": str(file_size)},
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


@app.post("/api/download-youtube")
async def download_youtube(tasks: BackgroundTasks, dados: YouTubeRequest, usuario: dict = Depends(get_current_user)):
    req = LinkRequest(url=dados.url)
    return await download_link(tasks, req, usuario)


# ══════════════════════════════════════════════════════════════
# ENDPOINTS — HISTÓRICO / DOWNLOAD / DELETE
# ══════════════════════════════════════════════════════════════

@app.get("/api/meus-cortes")
async def meus_cortes(usuario: dict = Depends(get_current_user)):
    if not supabase_admin:
        raise HTTPException(503, "Banco indisponível.")
    user_email = usuario.get("email")
    if not user_email:
        raise HTTPException(401, "Usuário inválido: email ausente no token.")
    try:
        resp = await asyncio.to_thread(
            lambda: supabase_admin.table("cortes")
            .select("*")
            .eq("user_email", user_email)
            .order("criado_em", desc=True)
            .execute()
        )
        cortes = resp.data or []
        logger.info(f"/api/meus-cortes usuário={user_email} registros={len(cortes)}")
        return {"sucesso": True, "cortes": cortes}
    except Exception as e:
        logger.error(f"Erro ao buscar cortes do usuário: {e}")
        raise HTTPException(500, "Erro ao buscar histórico de cortes.")


@app.get("/api/cortes/download")
async def download_corte(video_url: str, usuario: dict = Depends(get_current_user)):
    if not supabase_admin:
        raise HTTPException(503, "Banco indisponível.")
    user_email = usuario.get("email")
    if not user_email:
        raise HTTPException(401, "Usuário inválido: email ausente no token.")

    logger.info(f"GET /api/cortes/download | usuário={user_email} | video_url={video_url}")
    try:
        registros = await asyncio.to_thread(
            lambda: supabase_admin.table("cortes").select("video_url").eq("user_email", user_email).execute()
        )
        alvo = _normalizar_video_url(video_url)
        urls_usuario = {_normalizar_video_url(c.get("video_url", "")) for c in (registros.data or [])}
        if alvo not in urls_usuario:
            raise HTTPException(404, "Vídeo não encontrado para o usuário autenticado.")

        if alvo.startswith("/outputs/"):
            caminho = Path(alvo.removeprefix("/")).resolve()
            base_outputs = OUTPUT_DIR.resolve()
            if base_outputs not in caminho.parents or not caminho.exists():
                raise HTTPException(404, "Arquivo local não encontrado.")

            def iter_local():
                with open(caminho, "rb") as arquivo:
                    while chunk := arquivo.read(1024 * 1024):
                        yield chunk

            return StreamingResponse(iter_local(), media_type="video/mp4", headers={"Content-Disposition": 'attachment; filename="Corte_EditMind.mp4"'})

        async with httpx.AsyncClient(timeout=90.0, follow_redirects=True) as client:
            resp = await client.get(video_url.strip())
            if resp.status_code >= 400:
                raise HTTPException(502, "Falha ao obter arquivo remoto para download.")
            content_type = resp.headers.get("content-type", "video/mp4")
            return StreamingResponse(iter([resp.content]), media_type=content_type, headers={"Content-Disposition": 'attachment; filename="Corte_EditMind.mp4"'})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro em /api/cortes/download: {e}")
        raise HTTPException(500, "Erro ao baixar recorte.")


@app.delete("/api/cortes/{corte_id}")
async def excluir_corte(corte_id: str, usuario: dict = Depends(get_current_user)):
    if not supabase_admin:
        raise HTTPException(503, "Banco indisponível.")
    user_email = usuario.get("email")
    if not user_email:
        raise HTTPException(401, "Usuário inválido: email ausente no token.")
    try:
        busca = await asyncio.to_thread(
            lambda: supabase_admin.table("cortes")
            .select("id, user_email, video_url")
            .eq("id", corte_id)
            .eq("user_email", user_email)
            .limit(1)
            .execute()
        )
        corte = (busca.data or [None])[0]
        if not corte:
            raise HTTPException(404, "Recorte não encontrado.")
        await _remover_arquivo_corte(corte.get("video_url", ""))
        await asyncio.to_thread(lambda: supabase_admin.table("cortes").delete().eq("id", corte_id).eq("user_email", user_email).execute())
        return {"sucesso": True, "mensagem": "Recorte excluído com sucesso."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erro ao excluir corte {corte_id}: {e}")
        raise HTTPException(500, "Erro ao excluir recorte.")


@app.post("/api/cortes/bulk-delete")
async def excluir_cortes_em_massa(dados: BulkDeleteRequest, usuario: dict = Depends(get_current_user)):
    if not supabase_admin:
        raise HTTPException(503, "Banco indisponível.")
    user_email = usuario.get("email")
    if not user_email:
        raise HTTPException(401, "Usuário inválido.")

    busca = await asyncio.to_thread(
        lambda: supabase_admin.table("cortes")
        .select("id,video_url,user_email")
        .eq("user_email", user_email)
        .in_("id", dados.ids)
        .execute()
    )
    registros = busca.data or []
    if not registros:
        return {"sucesso": True, "excluidos": 0}

    for corte in registros:
        try:
            await _remover_arquivo_corte(corte.get("video_url", ""))
        except Exception as e:
            logger.warning(f"Falha ao remover arquivo do corte {corte.get('id')}: {e}")

    ids_existentes = [c.get("id") for c in registros if c.get("id")]
    await asyncio.to_thread(
        lambda: supabase_admin.table("cortes").delete().eq("user_email", user_email).in_("id", ids_existentes).execute()
    )
    return {"sucesso": True, "excluidos": len(ids_existentes)}


@app.post("/api/cortes/bulk-download")
async def baixar_cortes_em_massa(dados: BulkDeleteRequest, usuario: dict = Depends(get_current_user)):
    if not supabase_admin:
        raise HTTPException(503, "Banco indisponível.")
    user_email = usuario.get("email")
    if not user_email:
        raise HTTPException(401, "Usuário inválido.")

    busca = await asyncio.to_thread(
        lambda: supabase_admin.table("cortes")
        .select("id,titulo,video_url,user_email")
        .eq("user_email", user_email)
        .in_("id", dados.ids)
        .execute()
    )
    registros = busca.data or []
    if not registros:
        raise HTTPException(404, "Nenhum recorte encontrado para download.")

    pasta_temp = Path(tempfile.mkdtemp(prefix="editmind_zip_"))
    zip_path = pasta_temp / "recortes_editmind.zip"

    async def _baixar_para_arquivo(url: str, destino: Path):
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code >= 400:
                raise RuntimeError("Falha ao baixar arquivo remoto")
            destino.write_bytes(resp.content)

    try:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
            for i, corte in enumerate(registros, start=1):
                nome_base = sanitizar(corte.get("titulo") or f"recorte_{i}").removesuffix(".mp4")
                nome_zip = f"{nome_base}_{i}.mp4"
                url = corte.get("video_url", "")
                if url.startswith("/outputs/"):
                    arquivo = Path(url.removeprefix("/")).resolve()
                    if arquivo.exists():
                        zipf.write(arquivo, arcname=nome_zip)
                    continue
                if url:
                    destino = pasta_temp / f"tmp_{i}.mp4"
                    await _baixar_para_arquivo(url, destino)
                    zipf.write(destino, arcname=nome_zip)

        file_size = zip_path.stat().st_size

        def iter_zip():
            try:
                with open(zip_path, "rb") as f:
                    while chunk := f.read(1024 * 1024):
                        yield chunk
            finally:
                shutil.rmtree(pasta_temp, ignore_errors=True)

        return StreamingResponse(
            iter_zip(),
            media_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="recortes_editmind.zip"',
                "Content-Length": str(file_size),
            },
        )
    except HTTPException:
        shutil.rmtree(pasta_temp, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(pasta_temp, ignore_errors=True)
        logger.error(f"Erro ao gerar ZIP de recortes: {e}")
        raise HTTPException(500, "Falha ao gerar download em massa.")


@app.get("/")
async def health():
    return {
        "status": "online",
        "api": "EditMind",
        "versao": "5.2.0",
        "servicos": {
            "openai": "ok" if OPENAI_API_KEY else "ausente",
            "supabase_auth": "ok" if supabase else "ausente",
            "supabase_storage": "ok" if supabase_admin else "ausente (SUPABASE_SERVICE_KEY)",
            "max_duracao_s": MAX_DURACAO_S,
        },
    }
