# EditMind V5

## Alterações principais

- Removido o botão de demonstração da tela de login.
- Adicionado botão de demonstração no CTA final da landing page.
- Landing page recebeu o mesmo background radial usado no app autenticado.
- Ferramentas Extras agora inclui YouTube e TikTok, com botões sem emojis e estilos separados.
- Adicionados parâmetros de extração com cards: `< 30s`, `30s - 60s` e `> 60s`.
- Novo Projeto agora permite configurar de 1 a 3 recortes por vídeo.
- Cada recorte pode ter duração e foco próprios.
- Backend atualizado para múltiplos recortes e prompt de IA que considera o vídeo inteiro.
- Adicionado endpoint genérico `/api/processar-link` para YouTube/TikTok.
- Adicionado endpoint genérico `/api/download-link`.
- Download real de recortes mantido via `/api/cortes/download` com `Content-Disposition: attachment`.
- Opção de saída vertical 9:16 sem achatamento, usando `scale` + `pad` no FFmpeg.
- `MAX_DURACAO_S` agora é variável de ambiente. Default seguro: `180`. Para 30 minutos, configurar `MAX_DURACAO_S=1800` em plano Render adequado.
- UX refinada para hover/zoom apenas em elementos realmente clicáveis.

## Migração SQL

O arquivo `supabase_cortes.sql` foi atualizado com colunas opcionais:

- `inicio_segundos`
- `fim_segundos`
- `foco`
- `duracao_tipo`
- `formato_vertical`

As alterações usam `add column if not exists`, então não quebram dados existentes.

## Segurança do pacote

Este pacote não inclui `.env`, cookies, chaves privadas ou tokens.
