/* ============================================================
   EditMind — js/auth.js
   Sistema de Autenticação Real (Supabase + FastAPI)
   ============================================================ */

const Auth = {
    // Verifica se existe um token válido no navegador
    estaLogado() {
        const token = localStorage.getItem(CONFIG.TOKEN_KEY);
        return token && token !== 'null' && token !== 'undefined';
    },

    // Retorna os dados do utilizador logado
    getUsuario() {
        try {
            const raw = localStorage.getItem(CONFIG.USER_KEY);
            return raw ? JSON.parse(raw) : null;
        } catch {
            return null;
        }
    },

    // Guarda o token e os dados do utilizador após login/cadastro
    _salvarSessao(token, usuario) {
        localStorage.setItem(CONFIG.TOKEN_KEY, token);
        localStorage.setItem(CONFIG.USER_KEY, JSON.stringify(usuario));
    },

    // Limpa a sessão e volta para a landing page
    logout() {
        localStorage.removeItem(CONFIG.TOKEN_KEY);
        localStorage.removeItem(CONFIG.USER_KEY);
        window.location.href = 'home.html';
    },

    // Faz a chamada de login para o teu backend no Render
    async login(email, senha) {
        try {
            const res = await fetch(`${CONFIG.API_URL}/api/auth/login`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, senha }),
            });

            const dados = await res.json();

            if (res.ok && dados.sucesso) {
                this._salvarSessao(dados.token, dados.usuario);
                return { sucesso: true };
            } else {
                return { sucesso: false, erro: dados.detail || 'E-mail ou senha incorretos.' };
            }
        } catch (err) {
            return { sucesso: false, erro: 'Servidor offline ou erro de rede.' };
        }
    },

    // Faz a chamada de cadastro para o teu backend no Render
    async cadastrar(nome, email, senha) {
        try {
            const res = await fetch(`${CONFIG.API_URL}/api/auth/cadastro`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, senha }), // O backend usa email/senha
            });

            const dados = await res.json();

            if (res.ok && dados.sucesso) {
                // Se o Supabase já devolver o token (sem precisar de confirmar email)
                if (dados.token) {
                    this._salvarSessao(dados.token, dados.usuario);
                    return { sucesso: true };
                }
                // Se precisar de confirmar email
                return { sucesso: true, msg: dados.msg };
            } else {
                return { sucesso: false, erro: dados.detail || 'Erro ao criar conta.' };
            }
        } catch (err) {
            return { sucesso: false, erro: 'Falha na conexão com o servidor.' };
        }
    },

    // Bloqueia o acesso a páginas protegidas (como o index.html)
    exigirLogin() {
        if (!this.estaLogado()) {
            window.location.href = 'login.html';
        }
    }
};
