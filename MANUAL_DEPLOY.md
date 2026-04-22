# EditMind v4 — Checklist de Deploy

## Supabase
- [ ] Criar a tabela `public.cortes` rodando `supabase_cortes.sql`.
- [ ] Criar o bucket `cortes` em Storage e marcar como **Public**.
- [ ] Em Storage > Policies, permitir `INSERT`/`UPDATE`/`DELETE` para `service_role` no bucket `cortes`.
- [ ] Em Authentication > URL Configuration, definir `Site URL` como a URL final da Vercel.
- [ ] Em Authentication > Redirect URLs, adicionar a URL pública de `redefinir-senha.html`.
- [ ] Copiar `SUPABASE_URL`, `anon key` e `service_role key`.

## Render (backend)
- [ ] **Recomendado:** criar um Web Service com runtime **Docker** apontando para a raiz do repositório.
- [ ] O `Dockerfile` já instala `ffmpeg`, atualiza `yt-dlp` e sobe `uvicorn` usando `${PORT}` do Render.
- [ ] Variáveis: `OPENAI_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SERVICE_KEY`, `SITE_URL`.
- [ ] Opcional para YouTube mais resiliente: `YTDLP_COOKIES_FILE` e `YTDLP_EXTRACTOR_ARGS`.
- [ ] **Alternativa nativa (Python runtime):** Build Command `pip install -r requirements.txt` e Start Command `uvicorn main:app --host 0.0.0.0 --port $PORT`, mas só use se você garantir `ffmpeg`/`ffprobe` no ambiente.

## Vercel (frontend)
- [ ] Importar o mesmo repositório na Vercel.
- [ ] Root Directory: `/`
- [ ] Framework Preset: `Other`
- [ ] Não definir Output Directory.
- [ ] Validar que `/` abre `home.html`, `/login` abre `login.html` e `/app` abre `index.html`.
- [ ] Editar `js/config.js` com a URL pública do backend Render e as chaves públicas do Supabase.
