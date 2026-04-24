# EditMind v5.2

Plataforma SaaS para transformar vídeos longos em recortes curtos com foco em viralização (Shorts, Reels e TikTok).

## Stack
- **Backend:** FastAPI (Python)
- **Auth/DB/Storage:** Supabase Auth + Postgres + Storage
- **IA:** OpenAI Whisper + GPT
- **Mídia:** FFmpeg + ffprobe
- **Download de links:** yt-dlp
- **Deploy:** Render (API) + Vercel (frontend)

## Funcionalidades atuais
- Login e cadastro
- Recuperação/redefinição de senha
- Upload de vídeo local
- YouTube Clipper
- TikTok Clipper
- Até 3 recortes por processamento
- Foco do gancho por recorte
- Duração por recorte
- Formato vertical 9:16 sem achatar
- Histórico de recortes
- Download real de recortes
- Exclusão individual e em massa
- Download em massa em ZIP (`recortes_editmind.zip`)
- Demo integrada na landing page (sem backend)
- Perfil do usuário (nome, e-mail, senha)

## Arquitetura (linguagem simples)
1. O usuário autentica no Supabase (token Bearer).
2. O frontend envia vídeo local ou link para a API FastAPI.
3. A API baixa/processa mídia com yt-dlp + FFmpeg.
4. Whisper transcreve e GPT sugere os melhores trechos.
5. FFmpeg gera os recortes finais em **MP4/H.264/AAC**.
6. Recortes são salvos no Supabase Storage (ou fallback local).
7. Histórico fica no banco e aparece em “Meus Conteúdos”.

## Rodar localmente
### Pré-requisitos
- Python 3.11+
- FFmpeg/ffprobe instalados no sistema
- yt-dlp instalado
- Projeto Supabase configurado

### Backend
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend
Abra `frontend/home.html` em servidor estático local (ex.: `python -m http.server 5500` dentro de `frontend/`).

## Variáveis de ambiente
No backend (`.env`):
- `OPENAI_API_KEY`
- `SUPABASE_URL`
- `SUPABASE_KEY` (anon key)
- `SUPABASE_SERVICE_KEY`
- `SITE_URL` (ex.: `https://editmind.vercel.app`)
- `MAX_DURACAO_S` (default 180)
- `MAX_BYTES` (default 200MB)
- `YTDLP_COOKIES_FILE` (opcional)
- `YTDLP_EXTRACTOR_ARGS` (opcional)

No frontend (`frontend/js/config.js`):
- `API_URL` (URL pública do backend Render)

## SQL de migração (profiles)
Executar no Supabase SQL Editor:
- `supabase_profiles_v5_2.sql`

Esse SQL cria `profiles` com:
- `id uuid primary key`
- `user_id uuid unique`
- `email text`
- `nome text`
- `criado_em timestamptz`
- `atualizado_em timestamptz`

## Deploy
### Backend (Render)
1. Conectar o repositório.
2. Definir variáveis de ambiente.
3. Garantir FFmpeg e yt-dlp disponíveis na imagem (Dockerfile já contempla fluxo).
4. Deploy da API (`main.py`).

### Frontend (Vercel)
1. Publicar pasta `frontend`.
2. Usar `vercel.json` do projeto.
3. Confirmar rotas (`/`, `/app`, `/login`, `/cadastro`, `/esqueci`, `/redefinir`).

### Supabase
1. Criar bucket `cortes`.
2. Aplicar SQL de `supabase_cortes.sql` e `supabase_profiles_v5_2.sql`.
3. Configurar Auth (email/password + reset).

## Limitações conhecidas
- Em **Render Free**, vídeos longos podem estourar timeout/CPU.
- Vídeos muito grandes exigem ajuste de plano e de `MAX_DURACAO_S`.
- TikTok/YouTube podem impor bloqueios de automação em alguns links.
- Download em massa depende da disponibilidade momentânea dos arquivos remotos.

## Nota técnica v5.2
Para TikTok e links potencialmente incompatíveis, o pipeline agora normaliza mídia para browser com:
- `video codec: h264 (libx264)`
- `audio codec: aac`
- `container: mp4`
- `movflags: +faststart`
