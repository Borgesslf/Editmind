# EditMind v5.1

## Resumo
Versão visual e funcional consolidada em cima da V5, preservando a base mais estável do backend e aplicando os trechos de UI solicitados.

## Mantido da V5
- Backend com múltiplos recortes.
- Download real por endpoint backend.
- Histórico de recortes.
- Exclusão de recortes.
- Suporte a YouTube/TikTok via endpoints genéricos.
- Opção 9:16 sem achatar vídeo.
- `MAX_DURACAO_S` configurável por ambiente.

## Alterações v5.1
- Ferramentas Extras agora usa o bloco visual solicitado para YouTube e TikTok.
- Adicionados wrappers `processarLink('youtube'|'tiktok')` e `baixarLink('youtube'|'tiktok')` no `frontend/js/app.js`.
- Ajustes da Engine agora usa o layout com cards `engine-grid`, `engine-card`, `engine-label`, `engine-name`, `engine-desc`.
- Corrigido risco de ID duplicado: a seção continua `id="aba-configs"` e o wrapper interno virou `id="engine-configs"`.
- CSS consolidado para YouTube vermelho, TikTok branco, botões secundários e cards de múltiplos cortes.
- Background do `body` definido como `#0b0d11`, conforme solicitado.
- Hover/cursor reforçado apenas para elementos clicáveis.

## Arquivos principais alterados
- `frontend/index.html`
- `frontend/js/app.js`
- `frontend/css/style.css`
- `CHANGELOG_V5_1.md`

## Validação executada
- `python -m py_compile main.py`
- `node --check frontend/js/app.js`
- validação estrutural simples do HTML/CSS/JS
