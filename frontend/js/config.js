/* ============================================================
   EditMind — js/config.js
   Configurações globais do projeto
   ============================================================ */

const CONFIG = {
    // URL do backend no Render
    // Troque pela URL real do seu app no Render
    API_URL: 'https://editmind-ay26.onrender.com',

    // Versão do app
    VERSION: '2.0.0',

    // Chave do localStorage para o token
    TOKEN_KEY: 'editmind_token',
    USER_KEY: 'editmind_user',
};

// Exporta globalmente
window.CONFIG = CONFIG;