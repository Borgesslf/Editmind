# EditMind V5.1

## Base
Esta versão parte da V5 e incorpora as melhores ideias dos arquivos enviados depois, sem substituir a base estável inteira.

## Alterações principais
- Configuração de 1 a 3 recortes virou botões rápidos em vez de select simples.
- Cada recorte agora usa botões/pills para duração e foco, deixando a experiência mais clara.
- Mantido backend V5 com fallback de insert no Supabase e retorno de `id` dos cortes salvos.
- Formato vertical 9:16 agora usa fundo borrado + foreground proporcional, evitando vídeo achatado e ficando mais profissional que padding simples.
- `MAX_DURACAO_S` continua seguro por padrão e com hard cap de 1800s.
- Histórico passa a salvar/aceitar metadados extras opcionais: motivo, duração real e índice do corte.
- CSS recebeu ajustes da versão enviada: menos elementos falsamente clicáveis e UX mais profissional nos controles de recorte.

## Banco
Rode `supabase_cortes.sql` novamente no SQL Editor. Ele usa `add column if not exists`, então não apaga dados existentes.

## Deploy
- Render: redeploy backend após subir `main.py`.
- Vercel: redeploy frontend após subir `frontend/`.
- Para testar vídeos até 30 minutos em plano adequado, configure `MAX_DURACAO_S=1800`.
