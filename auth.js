/* ============================================================
   EditMind — js/auth.js
   Sistema de autenticação:
   - Modo Demo: funciona sem backend (localStorage)
   - Modo Real: chama /api/auth/* no Render
   ============================================================ */

const Auth = {

    // ── Verifica se está logado ─────────────────────────────
    estaLogado() {
        const token = localStorage.getItem(CONFIG.TOKEN_KEY);
        return token && token !== 'null' && token !== 'undefined';
    },

    // ── Pega dados do usuário atual ─────────────────────────
    getUsuario() {
        try {
            const raw = localStorage.getItem(CONFIG.USER_KEY);
            return raw ? JSON.parse(raw) : null;
        } catch {
            return null;
        }
    },

    // ── Salva sessão no localStorage ────────────────────────
    _salvarSessao(token, usuario) {
        localStorage.setItem(CONFIG.TOKEN_KEY, token);
        localStorage.setItem(CONFIG.USER_KEY, JSON.stringify(usuario));
    },

    // ── Limpa sessão ────────────────────────────────────────
    logout() {
        localStorage.removeItem(CONFIG.TOKEN_KEY);
        localStorage.removeItem(CONFIG.USER_KEY);
        window.location.href = 'home.html';
    },

    // ── MODO DEMO — funciona sem qualquer backend ───────────
    modoDemo() {
        const usuario = {
            nome: 'Usuário Demo',
            email: 'demo@editmind.app',
            modo: 'demo',
        };
        this._salvarSessao('demo_token_' + Date.now(), usuario);
        window.location.href = 'index.html';
    },

    // ── LOGIN DEV — para testes rápidos ─────────────────────
    loginDev() {
        const usuario = {
            nome: 'Dev',
            email: 'dev@editmind.app',
            modo: 'dev',
        };
        this._salvarSessao('dev_token_' + Date.now(), usuario);
        window.location.href = 'index.html';
    },

    // ── LOGIN REAL ──────────────────────────────────────────
    async login(email, senha) {
        // Se o backend não tiver rota de auth, usa modo demo automaticamente
        try {
            const res = await fetch(`${CONFIG.API_URL}/api/auth/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, senha }),
            });

            if (res.ok) {
                const dados = await res.json();
                this._salvarSessao(dados.token, dados.usuario);
                return { sucesso: true };
            }

            // Fallback: aceita qualquer email/senha no modo MVP
            // REMOVA este bloco em produção real
            if (email && senha && senha.length >= 6) {
                const usuario = { nome: email.split('@')[0], email, modo: 'local' };
                this._salvarSessao('local_' + Date.now(), usuario);
                return { sucesso: true };
            }

            const erro = await res.json().catch(() => ({}));
            return { sucesso: false, erro: erro.detail || 'Email ou senha incorretos.' };

        } catch {
            // Sem backend — aceita qualquer credencial válida (MVP)
            if (email && senha && senha.length >= 6) {
                const usuario = { nome: email.split('@')[0], email, modo: 'local' };
                this._salvarSessao('local_' + Date.now(), usuario);
                return { sucesso: true };
            }
            return { sucesso: false, erro: 'Senha deve ter pelo menos 6 caracteres.' };
        }
    },

    // ── CADASTRO REAL ───────────────────────────────────────
    async cadastrar(nome, email, senha) {
        try {
            const res = await fetch(`${CONFIG.API_URL}/api/auth/cadastro`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ nome, email, senha }),
            });

            if (res.ok) {
                const dados = await res.json();
                this._salvarSessao(dados.token, dados.usuario);
                return { sucesso: true };
            }

            // Fallback MVP — registra localmente
            const usuario = { nome, email, modo: 'local' };
            this._salvarSessao('local_' + Date.now(), usuario);
            return { sucesso: true };

        } catch {
            // Sem backend — cadastra localmente
            const usuario = { nome, email, modo: 'local' };
            this._salvarSessao('local_' + Date.now(), usuario);
            return { sucesso: true };
        }
    },

    // ── Protege páginas que exigem login ────────────────────
    // Chame no início de páginas protegidas
    exigirLogin(redirecionarPara = 'login.html') {
        if (!this.estaLogado()) {
            window.location.href = redirecionarPara;
            return false;
        }
        return true;
    },
};

window.Auth = Auth;