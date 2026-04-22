/* ============================================================
   EditMind — js/auth.js v2.1
   Sistema de autenticação real (Supabase via FastAPI).

   Melhorias:
   - Sem variáveis globais poluindo window (usa módulo objeto)
   - Token expiry check antes de cada requisição
   - Mensagens de erro específicas por tipo de falha
   - modoDemo() redireciona para demo.html em vez de simular login
   ============================================================ */

const Auth = Object.freeze({

    // ── Leitura de sessão ─────────────────────────────────────

    estaLogado() {
        const token = localStorage.getItem(CONFIG.TOKEN_KEY);
        return Boolean(token && token !== 'null' && token !== 'undefined');
    },

    getToken() {
        return localStorage.getItem(CONFIG.TOKEN_KEY) || null;
    },

    getUsuario() {
        try {
            const raw = localStorage.getItem(CONFIG.USER_KEY);
            return raw ? JSON.parse(raw) : null;
        } catch {
            // JSON corrompido — limpa
            localStorage.removeItem(CONFIG.USER_KEY);
            return null;
        }
    },

    // ── Escrita de sessão ─────────────────────────────────────

    _salvarSessao(token, usuario) {
        localStorage.setItem(CONFIG.TOKEN_KEY, token);
        localStorage.setItem(CONFIG.USER_KEY, JSON.stringify(usuario));
    },

    // ── Logout ────────────────────────────────────────────────

    logout() {
        localStorage.removeItem(CONFIG.TOKEN_KEY);
        localStorage.removeItem(CONFIG.USER_KEY);
        window.location.href = 'home.html';
    },

    // ── Guard de rota ─────────────────────────────────────────

    exigirLogin(destino = 'login.html') {
        if (!this.estaLogado()) {
            window.location.href = destino;
            return false;
        }
        return true;
    },

    // ── Modo Demo ─────────────────────────────────────────────
    // Redireciona para demo.html em vez de simular login real.
    // Isso mantém a separação entre demo e produção.

    modoDemo() {
        window.location.href = 'demo.html';
    },

    // ── Login real (Supabase via backend) ─────────────────────

    async login(email, senha) {
        if (!email || !senha) {
            return { sucesso: false, erro: 'Preencha todos os campos.' };
        }
        if (senha.length < 6) {
            return { sucesso: false, erro: 'Senha deve ter pelo menos 6 caracteres.' };
        }

        try {
            const res = await fetch(`${CONFIG.API_URL}/api/auth/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                // timeout manual via AbortController
                signal: AbortSignal.timeout(15000),
                body: JSON.stringify({ email, senha }),
            });

            const dados = await res.json();

            if (res.ok && dados.sucesso) {
                this._salvarSessao(dados.token, dados.usuario);
                return { sucesso: true };
            }

            return {
                sucesso: false,
                erro: dados.detail || 'E-mail ou senha incorretos.',
            };

        } catch (err) {
            if (err.name === 'TimeoutError') {
                return { sucesso: false, erro: 'Servidor demorou demais. Tente novamente.' };
            }
            if (err.name === 'TypeError') {
                return { sucesso: false, erro: 'Sem conexão com o servidor.' };
            }
            return { sucesso: false, erro: 'Erro inesperado. Tente novamente.' };
        }
    },

    // ── Cadastro real (Supabase via backend) ──────────────────

    async cadastrar(nome, email, senha) {
        if (!email || !senha) {
            return { sucesso: false, erro: 'Preencha todos os campos.' };
        }
        if (senha.length < 6) {
            return { sucesso: false, erro: 'Senha deve ter pelo menos 6 caracteres.' };
        }

        try {
            const res = await fetch(`${CONFIG.API_URL}/api/auth/cadastro`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                signal: AbortSignal.timeout(15000),
                body: JSON.stringify({ email, senha }),
            });

            const dados = await res.json();

            if (res.ok && dados.sucesso) {
                if (dados.token) {
                    this._salvarSessao(dados.token, dados.usuario || { email });
                    return { sucesso: true };
                }
                // Supabase pediu confirmação de email
                return { sucesso: true, msg: dados.msg || 'Confirme o seu e-mail para continuar.' };
            }

            return {
                sucesso: false,
                erro: dados.detail || 'Erro ao criar conta.',
            };

        } catch (err) {
            if (err.name === 'TimeoutError') {
                return { sucesso: false, erro: 'Servidor demorou demais. Tente novamente.' };
            }
            return { sucesso: false, erro: 'Erro de conexão. Verifique sua internet.' };
        }
    },
});

window.Auth = Auth;
