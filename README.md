# EditMind v3.0

**Clipador automático de vídeos com IA** — transcreve, analisa e recorta o trecho de maior
potencial viral do seu conteúdo.

---

## Arquitetura

```
Vercel (Frontend)               Render (Backend)
─────────────────               ─────────────────
home.html        ──── fetch ──▶ FastAPI
login.html                      │
cadastro.html                   ├── OpenAI Whisper-1   (transcrição)
index.html (app)                ├── OpenAI GPT-4o-mini (correção texto)
esqueci-senha.html              ├── OpenAI GPT-4o      (análise viral)
redefinir-senha.html            ├── FFmpeg             (corte de vídeo)
demo.html                       └── yt-dlp             (download YouTube)
                                         │
                                Supabase (Auth + Storage)
                                ├── Autenticação de usuários
                                └── Bucket "cortes" (vídeos processados)
```

---

## Stack

| Camada | Tecnologia |
|---|---|
| Frontend | HTML Vanilla · Tailwind CSS CDN · JavaScript ES6+ |
| Backend | Python 3.11 · FastAPI · Uvicorn |
| IA Transcrição | OpenAI Whisper-1 (API) |
| IA Correção | OpenAI GPT-4o-mini |
| IA Análise Viral | OpenAI GPT-4o |
| Processamento | FFmpeg · yt-dlp |
| Auth | Supabase Auth |
| Storage | Supabase Storage (bucket `cortes`) |
| Deploy Backend | Render |
| Deploy Frontend | Vercel |

---

## Variáveis de Ambiente (Render)

```env
OPENAI_API_KEY        = sk-proj-...         # OpenAI API Key
SUPABASE_URL          = https://xxx.supabase.co
SUPABASE_KEY          = eyJ...              # Chave anon/public (auth de usuários)
SUPABASE_SERVICE_KEY  = eyJ...              # Service role key (storage + admin)
SITE_URL              = https://editmind.vercel.app  # URL do frontend (reset senha)
```

> `SUPABASE_SERVICE_KEY` é diferente da `SUPABASE_KEY`. Encontre em:
> Supabase Dashboard → Project Settings → API → `service_role`.

---

## Endpoints da API

### Auth

| Método | Rota | Descrição |
|---|---|---|
| POST | `/api/auth/cadastro` | Cria conta via Supabase |
| POST | `/api/auth/login` | Login, retorna JWT |
| POST | `/api/auth/esqueci-senha` | Dispara e-mail de recuperação |
| POST | `/api/auth/redefinir-senha` | Atualiza senha com token de recovery |

**Payload `/api/auth/cadastro` e `/api/auth/login`:**
```json
{ "email": "user@example.com", "senha": "minimo6" }
```

**Payload `/api/auth/esqueci-senha`:**
```json
{ "email": "user@example.com" }
```

**Payload `/api/auth/redefinir-senha`:**
```json
{ "token": "access_token_do_hash_da_url", "nova_senha": "nova123" }
```

### Processamento (protegidos por Bearer token)

| Método | Rota | Descrição |
|---|---|---|
| POST | `/api/processar` | Upload direto de vídeo → pipeline completo |
| POST | `/api/processar-youtube` | URL do YouTube → download + pipeline |
| POST | `/api/download-youtube` | Só baixa o vídeo (sem IA) |
| GET  | `/` | Health check |

**Header obrigatório nas rotas protegidas:**
```
Authorization: Bearer <jwt_token>
```

**Resposta de `/api/processar` e `/api/processar-youtube`:**
```json
{
  "status": "sucesso",
  "transcricao": "Texto corrigido do vídeo...",
  "corte_sugerido": {
    "inicio": "00:00:14",
    "fim": "00:00:46",
    "inicio_segundos": 14.0,
    "fim_segundos": 46.8,
    "motivo": "Revelação impactante com gancho forte nos primeiros 3s"
  },
  "detalhes_tecnicos": {
    "resolucao": "1920x1080",
    "fps": "60.0",
    "duracao_segundos": "180.5"
  },
  "url_corte": "https://xxx.supabase.co/storage/v1/object/public/cortes/corte_abc123.mp4",
  "storage": "supabase"
}
```

---

## Pipeline de Processamento

```
Vídeo recebido (upload ou YouTube URL)
         │
         ▼
[ffprobe] Extração de metadados
         │  resolucao, fps, duracao_segundos
         ▼
[FFmpeg]  Extração de áudio
         │  MP3 · 16kHz · mono · 32k bitrate
         ▼
[Whisper-1]  Transcrição
         │  português · response_format=text
         ▼
[GPT-4o-mini]  Correção de texto
         │  pontuação · concordância · sem inventar
         ▼
[GPT-4o]  Análise de viralidade
         │  JSON: { inicio, fim, motivo }
         ▼
[FFmpeg]  Corte do vídeo
         │  stream copy · sem re-encoding · +faststart
         ▼
[Supabase Storage]  Upload do corte
         │  bucket "cortes" · URL pública
         ▼
JSON de resposta para o frontend
```

---

## Frontend — Estrutura de Arquivos

```
/
├── vercel.json             → Roteamento Vercel
├── home.html               → Landing page
├── login.html              → Login + link "esqueci senha"
├── cadastro.html           → Cadastro
├── index.html              → App principal (upload, resultado, YouTube)
├── esqueci-senha.html      → Formulário de recuperação de senha
├── redefinir-senha.html    → Callback do link do e-mail de reset
├── demo.html               → Demo interativa (sem backend)
├── js/
│   ├── config.js           → API_URL, chaves, constantes
│   ├── auth.js             → login, cadastro, esquecerSenha, redefinirSenha
│   └── app.js              → pipeline upload, YouTube, player, botões
└── css/
    └── style.css           → estilos do app (não usa Tailwind)
```

### js/config.js
Único arquivo que precisa ser editado para mudar URL do backend ou chaves.

### js/auth.js
Métodos disponíveis:
- `Auth.estaLogado()` — bool
- `Auth.getToken()` — JWT string
- `Auth.getUsuario()` — objeto `{email}`
- `Auth.login(email, senha)` — `{sucesso, erro?}`
- `Auth.cadastrar(nome, email, senha)` — `{sucesso, msg?, erro?}`
- `Auth.esquecerSenha(email)` — `{sucesso, msg, erro?}`
- `Auth.redefinirSenha(token, novaSenha)` — `{sucesso, erro?}`
- `Auth.logout()` — limpa sessão e redireciona
- `Auth.exigirLogin()` — redireciona se não logado
- `Auth.modoDemo()` — vai para demo.html

### js/app.js
Funções globais expostas:
- `processarYouTube()` — processa link YT com IA
- `baixarYouTube()` — só baixa o MP4
- `mostrarResultado()` — exibe painel IA
- `resetarNovoCorte()` — volta ao painel de upload
- `mudarAba(id)` — navegação entre abas

---

## Supabase Storage — Configuração

1. Acesse o Supabase Dashboard → Storage
2. Crie um bucket chamado **`cortes`**
3. Marque como **Public** (permite URL pública sem autenticação)
4. Em Policies, adicione uma policy INSERT para `service_role`
5. Adicione `SUPABASE_SERVICE_KEY` nas variáveis de ambiente do Render

Se o `SUPABASE_SERVICE_KEY` não estiver configurado, os vídeos são servidos
localmente pelo endpoint `/outputs/` do Render (funcionamento degradado, mas sem crash).

---

## Supabase Auth — Configuração do Reset de Senha

1. Supabase Dashboard → Authentication → URL Configuration
2. Defina **Site URL** como `https://editmind.vercel.app`
3. Em **Redirect URLs**, adicione: `https://editmind.vercel.app/redefinir-senha.html`
4. Personalize o e-mail de reset em Authentication → Email Templates

---

## Instalação e Execução Local

```bash
# Clone o projeto
git clone https://github.com/seuuser/editmind.git
cd editmind

# Instale as dependências Python
pip install -r requirements.txt

# Configure as variáveis de ambiente
cp .env.example .env
# Edite o .env com suas chaves

# Instale o FFmpeg (se não tiver)
# macOS: brew install ffmpeg
# Ubuntu: sudo apt install ffmpeg
# Windows: baixe em ffmpeg.org e adicione ao PATH

# Rode o servidor
uvicorn main:app --reload --port 8000
```

Para o frontend, basta abrir `home.html` no navegador ou usar um servidor estático:
```bash
python -m http.server 3000
```

---

## Deploy

### Backend (Render)
1. Conecte o repositório no Render
2. Build Command: `pip install -r requirements.txt`
3. Start Command: `uvicorn main:app --host 0.0.0.0 --port 8000`
4. Adicione todas as variáveis de ambiente
5. Plano: Free tier é suficiente para MVP

### Frontend (Vercel)
1. Conecte o repositório no Vercel
2. Root Directory: `/` (raiz do projeto)
3. Framework: Other (não é Next.js)
4. Nenhuma variável de ambiente necessária (tudo em config.js)

---

## Limites e Considerações

| Limite | Valor | Motivo |
|---|---|---|
| Duração máxima do vídeo | 3 min (180s) | Whisper API · tempo de processamento |
| Tamanho máximo do arquivo | 200 MB | Memória do Render free tier |
| Tamanho máximo do áudio | 25 MB | Limite da API Whisper |
| Timeout do processamento | 5 min | AbortController no frontend |
| Duração do corte | 15–60s | Limitação do prompt GPT-4o |

---

## Roadmap Futuro

- [ ] Histórico de cortes por usuário (Supabase Database)
- [ ] Múltiplos cortes por vídeo
- [ ] Exportação com legendas (SRT)
- [ ] Redimensionamento para formato 9:16 (Reels/TikTok)
- [ ] Integração com agendamento de posts
- [ ] Planos de assinatura (Stripe)
