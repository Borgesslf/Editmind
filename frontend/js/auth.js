/* ============================================================
   EditMind — js/auth.js  v3.0
   Autenticação via FastAPI + Supabase.

   Novidades v3.0:
   - esquecerSenha(email)  — dispara e-mail de reset
   - redefinirSenha(token, novaSenha) — atualiza senha
   - AbortSignal.timeout() em todas as chamadas
   ============================================================ */

const Auth = Object.freeze({

    // ── Leitura de sessão ─────────────────────────────────────

    estaLogado() {
        const t = localStorage.getItem(CONFIG.TOKEN_KEY);
        return Boolean(t && t !== 'null' && t !== 'undefined');
    },

    getToken() {
        return localStorage.getItem(CONFIG.TOKEN_KEY) || null;
    },

    getUsuario() {
        try {
            const raw = localStorage.getItem(CONFIG.USER_KEY);
            return raw ? JSON.parse(raw) : null;
        } catch {
            localStorage.removeItem(CONFIG.USER_KEY);
            return null;
        }
    },

    // ── Sessão ────────────────────────────────────────────────

    _salvar(token, usuario) {
        localStorage.setItem(CONFIG.TOKEN_KEY, token);
        localStorage.setItem(CONFIG.USER_KEY, JSON.stringify(usuario));
    },

    logout() {
        localStorage.removeItem(CONFIG.TOKEN_KEY);
        localStorage.removeItem(CONFIG.USER_KEY);
        window.location.href = '/';
    },

    exigirLogin(dest = 'login.html') {
        if (!this.estaLogado()) { window.location.href = dest; return false; }
        return true;
    },

    modoDemo() { window.location.href = 'demo.html'; },

    // ── Chamada genérica ao backend ───────────────────────────

    async _post(rota, body, timeout = 15000) {
        try {
            const res = await fetch(`${CONFIG.API_URL}${rota}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                signal: AbortSignal.timeout(timeout),
                body: JSON.stringify(body),
            });
            const dados = await res.json();
            if (res.ok) return { sucesso: true, ...dados };
            return { sucesso: false, erro: dados.detail || 'Erro desconhecido.' };
        } catch (err) {
            if (err.name === 'TimeoutError') return { sucesso: false, erro: 'Servidor demorou. Tente novamente.' };
            return { sucesso: false, erro: 'Sem conexão com o servidor.' };
        }
    },

    // ── Login ─────────────────────────────────────────────────

    async login(email, senha) {
        if (!email || !senha) return { sucesso: false, erro: 'Preencha todos os campos.' };
        if (senha.length < 6) return { sucesso: false, erro: 'Senha mínima: 6 caracteres.' };

        const res = await this._post('/api/auth/login', { email, senha });
        if (res.sucesso && res.token) this._salvar(res.token, res.usuario || { email });
        return res;
    },

    // ── Cadastro ──────────────────────────────────────────────

    async cadastrar(nome, email, senha) {
        if (!email || !senha) return { sucesso: false, erro: 'Preencha todos os campos.' };
        if (senha.length < 6) return { sucesso: false, erro: 'Senha mínima: 6 caracteres.' };

        const res = await this._post('/api/auth/cadastro', { email, senha });
        if (res.sucesso && res.token) this._salvar(res.token, res.usuario || { email });
        return res;
    },

    // ── Esqueci a senha ───────────────────────────────────────
    // Envia e-mail com link de recovery para o usuário.
    // O backend chama supabase.auth.reset_password_email()
    // que redireciona para /redefinir-senha.html#access_token=...

    async esquecerSenha(email) {
        if (!email) return { sucesso: false, erro: 'Informe o e-mail.' };
        return await this._post('/api/auth/esqueci-senha', { email });
    },

    // ── Redefinir senha ───────────────────────────────────────
    // Chamado na página redefinir-senha.html após extrair
    // o token do hash da URL.

    async redefinirSenha(token, novaSenha) {
        if (!token)           return { sucesso: false, erro: 'Token inválido.' };
        if (novaSenha.length < 6) return { sucesso: false, erro: 'Senha mínima: 6 caracteres.' };
        return await this._post('/api/auth/redefinir-senha',
            { token, nova_senha: novaSenha });
    },
});

window.Auth = Auth;
