/* ============================================================
   EditMind — js/config.js  v3.0
   Ponto central de configuração. Altere só aqui.
   ============================================================ */

const CONFIG = Object.freeze({

    // ── Backend (Render) ──────────────────────────────────────
    API_URL: 'https://editmind-ay26.onrender.com',

    // ── Supabase (necessário para reset de senha no frontend) ─
    // Copie do Dashboard Supabase > Project Settings > API
    SUPABASE_URL:      'https://SEU-PROJETO.supabase.co',
    SUPABASE_ANON_KEY: 'eyJ...',   // chave "anon public"

    // ── localStorage keys ─────────────────────────────────────
    TOKEN_KEY: 'editmind_token',
    USER_KEY:  'editmind_user',

    // ── Misc ──────────────────────────────────────────────────
    VERSAO: '3.0.0',
    MAX_DURACAO_AVISO: 180,
});

window.CONFIG = CONFIG;
