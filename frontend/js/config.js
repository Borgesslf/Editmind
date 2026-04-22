/* ============================================================
   EditMind — js/config.js
   Ponto central de configuração do frontend.
   Altere apenas este arquivo para mudar a URL do backend.
   ============================================================ */

const CONFIG = Object.freeze({
    // ── URL do backend (Render) ───────────────────────────────
    // Troque pela URL real do seu app no Render antes de commitar
    API_URL: 'https://editmind-ay26.onrender.com',

    // ── Chaves do localStorage ────────────────────────────────
    TOKEN_KEY: 'editmind_token',
    USER_KEY:  'editmind_user',

    // ── Configurações do upload ───────────────────────────────
    MAX_DURACAO_AVISO_SEGUNDOS: 180,  // Avisa o usuário se o vídeo for longo
    VERSAO: '2.1.0',
});

window.CONFIG = CONFIG;
