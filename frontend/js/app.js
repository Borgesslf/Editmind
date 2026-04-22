/* ============================================================
   EditMind — js/app.js v2.1

   Melhorias:
   - XHR substituído por fetch() com AbortController (timeout real)
   - Cronômetro ao vivo durante o processamento
   - Meta cards animados (resolução, fps, duração)
   - Auth guard no DOMContentLoaded
   - Feedback visual em todas as etapas do pipeline
   - Campos do formulário compatíveis com o backend (field: 'file')
   ============================================================ */

// ── Configuração ──────────────────────────────────────────────
const API_BASE_URL    = window.CONFIG?.API_URL ?? '';
const TIMEOUT_MS      = 5 * 60 * 1000; // 5 minutos (processamento pode demorar)

// ── Referências ao DOM ────────────────────────────────────────
const $ = (id) => document.getElementById(id);

const painelUpload      = $('painel-upload');
const painelIa          = $('painel-ia');
const areaSoltar        = $('area-soltar');
const entradaArquivo    = $('entrada-arquivo');
const nomeArquivoTexto  = $('nome-arquivo');
const barraProgresso    = $('barra-progresso');
const porcentagemTexto  = $('porcentagem-envio');
const mensagemTexto     = $('mensagem-envio');
const metaRes           = $('meta-res');
const metaFps           = $('meta-fps');
const metaDuracao       = $('meta-duracao');
const textoTranscricao  = $('texto-transcricao');
const corteInicio       = $('corte-inicio');
const corteFim          = $('corte-fim');
const corteMotivo       = $('corte-motivo');

window.ultimoResultadoIA = null;

// ── Auth Guard + Init ─────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    // Redireciona para login se não estiver autenticado
    if (!window.Auth?.estaLogado()) {
        window.location.href = 'login.html';
        return;
    }

    // Mostra nome do usuário no header (se existir o elemento)
    const usuario = window.Auth.getUsuario();
    const elUser  = $('user-nome');
    if (elUser && usuario) {
        elUser.textContent = usuario.nome || usuario.email?.split('@')[0] || 'Usuário';
    }

    // Botão de logout
    const btnLogout = $('btn-logout');
    if (btnLogout) {
        btnLogout.addEventListener('click', () => window.Auth.logout());
    }

    // Nav toggle (menu hamburguer)
    const navToggle = $('navToggle');
    const btnNav    = $('btnNav');
    if (navToggle && btnNav) {
        navToggle.addEventListener('click', (e) => {
            e.stopPropagation();
            btnNav.classList.toggle('open');
        });
        document.addEventListener('click', (e) => {
            if (!btnNav.contains(e.target)) btnNav.classList.remove('open');
        });
    }
});

// ── Cronômetro ────────────────────────────────────────────────
let _timerInterval = null;
let _timerStart    = null;

function iniciarTimer() {
    _timerStart    = Date.now();
    _timerInterval = setInterval(() => {
        const elapsed = Math.floor((Date.now() - _timerStart) / 1000);
        const m = String(Math.floor(elapsed / 60)).padStart(2, '0');
        const s = String(elapsed % 60).padStart(2, '0');
        const el = $('timer-display');
        if (el) el.textContent = `${m}:${s}`;
    }, 1000);
}

function pararTimer() {
    clearInterval(_timerInterval);
    _timerInterval = null;
    const elapsed  = _timerStart ? Math.floor((Date.now() - _timerStart) / 1000) : 0;
    _timerStart    = null;
    return elapsed;
}

// ── Helpers de UI ─────────────────────────────────────────────
function setProgresso(pct) {
    if (barraProgresso)    barraProgresso.style.width   = `${pct}%`;
    if (porcentagemTexto)  porcentagemTexto.textContent = `${pct}%`;
}

function setMensagem(html, cor = '#6b7280') {
    if (!mensagemTexto) return;
    mensagemTexto.innerHTML   = html;
    mensagemTexto.style.color = cor;
}

function animarMetaCard(elemento, valor) {
    if (!elemento) return;
    elemento.style.transition = 'none';
    elemento.style.opacity    = '0';
    elemento.style.transform  = 'translateY(6px)';
    elemento.textContent      = valor;
    requestAnimationFrame(() => requestAnimationFrame(() => {
        elemento.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
        elemento.style.opacity    = '1';
        elemento.style.transform  = 'translateY(0)';
    }));
}

function resetUI() {
    setProgresso(0);
    setMensagem('Motor em standby.');
    if (barraProgresso)   barraProgresso.style.background = '';
    if (nomeArquivoTexto) nomeArquivoTexto.textContent    = 'Aguardando feed...';
    if (metaRes)          metaRes.textContent    = '—';
    if (metaFps)          metaFps.textContent    = '—';
    if (metaDuracao)      metaDuracao.textContent = '—';
    if (entradaArquivo)   entradaArquivo.value    = '';
    const el = $('timer-display');
    if (el) el.textContent = '00:00';
}

// ── Drag & Drop ───────────────────────────────────────────────
if (areaSoltar) {
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach((evt) =>
        areaSoltar.addEventListener(evt, (e) => { e.preventDefault(); e.stopPropagation(); })
    );

    ['dragenter', 'dragover'].forEach((evt) =>
        areaSoltar.addEventListener(evt, () => {
            areaSoltar.style.borderColor = '#f97316';
            areaSoltar.style.background  = 'rgba(249,115,22,0.06)';
        })
    );

    ['dragleave', 'drop'].forEach((evt) =>
        areaSoltar.addEventListener(evt, () => {
            areaSoltar.style.borderColor = '';
            areaSoltar.style.background  = '';
        })
    );

    areaSoltar.addEventListener('drop', (e) => processarArquivos(e.dataTransfer.files));
}

if (entradaArquivo) {
    entradaArquivo.addEventListener('change', (e) => processarArquivos(e.target.files));
}

// ── Pipeline principal ────────────────────────────────────────
async function processarArquivos(arquivos) {
    if (!arquivos?.length) return;

    const arquivo = arquivos[0];
    const ext     = arquivo.name.split('.').pop().toLowerCase();

    if (!['mp4', 'mov', 'avi', 'webm'].includes(ext)) {
        alert('EditMind aceita apenas vídeos: mp4, mov, avi ou webm.');
        return;
    }

    // ── Setup visual ──────────────────────────────────────────
    if (nomeArquivoTexto) nomeArquivoTexto.textContent = arquivo.name;
    if (barraProgresso)   barraProgresso.style.background = 'linear-gradient(to right, #f97316, #facc15)';
    iniciarTimer();

    // Etapas visuais simuladas (feedback enquanto o backend processa)
    const etapas = [
        { pct: 10, msg: '📤 Enviando vídeo...',                delay: 0     },
        { pct: 25, msg: '🎵 FFmpeg extraindo áudio...',        delay: 5000  },
        { pct: 50, msg: '🎙️ Whisper-1 transcrevendo...',      delay: 12000 },
        { pct: 70, msg: '✏️ GPT-4o-mini corrigindo texto...', delay: 22000 },
        { pct: 85, msg: '🤖 GPT-4o analisando viralidade...',  delay: 30000 },
        { pct: 93, msg: '✂️ FFmpeg cortando o trecho...',      delay: 40000 },
    ];

    const timeouts = etapas.map(({ pct, msg, delay }) =>
        setTimeout(() => { setProgresso(pct); setMensagem(msg); }, delay)
    );

    // FormData com campo 'file' (compatível com o backend)
    const dados = new FormData();
    dados.append('file', arquivo);

    const token = window.Auth?.getToken();

    const controller = new AbortController();
    const timeoutId  = setTimeout(() => controller.abort(), TIMEOUT_MS);

    try {
        const resposta = await fetch(`${API_BASE_URL}/api/processar`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'ngrok-skip-browser-warning': 'true',
            },
            body: dados,
            signal: controller.signal,
        });

        clearTimeout(timeoutId);
        timeouts.forEach(clearTimeout);

        const resultado  = await resposta.json();
        const tempoTotal = pararTimer();

        if (!resposta.ok) {
            // Token expirado — redireciona para login
            if (resposta.status === 401) {
                window.Auth?.logout();
                return;
            }
            throw new Error(resultado.detail || `Erro ${resposta.status}`);
        }

        // ── Atualiza meta cards com animação ──────────────────
        const infos = resultado.detalhes_tecnicos || {};
        animarMetaCard(metaRes,     infos.resolucao || 'N/A');
        animarMetaCard(metaFps,     infos.fps ? `${infos.fps} FPS` : 'N/A');
        animarMetaCard(metaDuracao, infos.duracao_segundos ? `${infos.duracao_segundos}s` : 'N/A');

        setProgresso(100);
        window.ultimoResultadoIA = { ...resultado, tempoTotal };

        const mm = String(Math.floor(tempoTotal / 60)).padStart(2, '0');
        const ss = String(tempoTotal % 60).padStart(2, '0');

        setMensagem(`
            <div style="display:flex;flex-direction:column;gap:10px;margin-top:10px;">
                <div style="display:inline-flex;align-items:center;gap:8px;font-size:11px;color:#22c55e;font-weight:700;">
                    <span style="width:8px;height:8px;border-radius:50%;background:#22c55e;display:inline-block;"></span>
                    Concluído em ${mm}:${ss}
                </div>
                <button
                    onclick="acionarTelaIA()"
                    style="padding:12px 28px;background:#f97316;color:white;border:none;
                           border-radius:999px;font-size:11px;font-weight:900;
                           letter-spacing:0.12em;cursor:pointer;
                           box-shadow:0 8px 24px rgba(249,115,22,0.4);transition:transform .2s;"
                    onmouseover="this.style.transform='scale(1.05)'"
                    onmouseout="this.style.transform='scale(1)'">
                    Ver Relatório da IA ⚡
                </button>
            </div>
        `, '#22c55e');

    } catch (erro) {
        clearTimeout(timeoutId);
        timeouts.forEach(clearTimeout);
        pararTimer();

        const msg = erro.name === 'AbortError'
            ? '⏱️ Timeout: o processamento demorou mais de 5 minutos.'
            : `❌ ${erro.message || 'Erro de conexão.'}`;

        setMensagem(msg, '#ef4444');
        if (barraProgresso) barraProgresso.style.background = '#ef4444';
        setTimeout(resetUI, 6000);
        console.error('[EditMind] Erro no pipeline:', erro);
    }
}

// ── Exibe painel de resultado ─────────────────────────────────
window.acionarTelaIA = function () {
    if (window.ultimoResultadoIA) mostrarResultadosIA(window.ultimoResultadoIA);
};

function mostrarResultadosIA(resultado) {
    if (painelUpload) painelUpload.classList.add('hidden');
    if (painelIa)     painelIa.classList.remove('hidden', 'fade-out');

    if (textoTranscricao) {
        textoTranscricao.textContent = resultado.transcricao || 'Sem transcrição disponível.';
    }

    const corte = resultado.corte_sugerido;
    if (corte) {
        if (corteInicio) corteInicio.textContent = corte.inicio || '00:00:00';
        if (corteFim)    corteFim.textContent    = corte.fim    || '00:00:00';
        if (corteMotivo) corteMotivo.textContent = corte.motivo || '—';
    }

    // Tempo de processamento
    if (resultado.tempoTotal !== undefined) {
        const mm = String(Math.floor(resultado.tempoTotal / 60)).padStart(2, '0');
        const ss = String(resultado.tempoTotal % 60).padStart(2, '0');
        const el = $('tempo-processamento');
        if (el) el.textContent = `Processado em ${mm}:${ss}`;
    }

    // Meta info
    const infos  = resultado.detalhes_tecnicos || {};
    const elMeta = $('ia-meta-info');
    if (elMeta && infos.resolucao) {
        elMeta.textContent = `${infos.resolucao} • ${infos.fps} FPS • ${infos.duracao_segundos}s`;
    }

    // Botão de download
    const areaDownload = $('area-download');
    if (areaDownload && resultado.url_corte) {
        areaDownload.innerHTML = `
            <a href="${API_BASE_URL}${resultado.url_corte}"
               download="Corte_EditMind.mp4"
               class="btn-download">
                ⬇ Baixar Corte (MP4)
            </a>
        `;
    }
}

window.resetarNovoCorte = function () {
    if (painelIa) painelIa.classList.add('fade-out');
    setTimeout(() => {
        if (painelIa)     painelIa.classList.add('hidden');
        if (painelIa)     painelIa.classList.remove('fade-out');
        if (painelUpload) painelUpload.classList.remove('hidden');
        resetUI();
        window.ultimoResultadoIA = null;
    }, 400);
};

// ── YouTube Downloader ────────────────────────────────────────
async function baixarYouTube() {
    const input = $('input-youtube');
    const btn   = $('btn-youtube');
    const link  = input?.value.trim();

    if (!link || (!link.includes('youtube.com') && !link.includes('youtu.be'))) {
        alert('Insira um link válido do YouTube.');
        return;
    }

    if (btn) { btn.disabled = true; btn.textContent = 'PROCESSANDO...'; }

    const token = window.Auth?.getToken();

    try {
        const res = await fetch(`${API_BASE_URL}/api/download-youtube`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`,
            },
            body: JSON.stringify({ url: link }),
            signal: AbortSignal.timeout(300_000),
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || `Erro ${res.status}`);
        }

        const blob = await res.blob();
        const url  = URL.createObjectURL(blob);
        const a    = document.createElement('a');
        a.href     = url;
        a.download = 'Video_EditMind.mp4';
        document.body.appendChild(a);
        a.click();
        URL.revokeObjectURL(url);
        document.body.removeChild(a);

        if (btn) { btn.textContent = 'CONCLUÍDO ✅'; input.value = ''; }
        setTimeout(() => { if (btn) { btn.textContent = 'BAIXAR'; btn.disabled = false; } }, 3000);

    } catch (err) {
        alert(`Erro: ${err.message}`);
        if (btn) { btn.textContent = 'BAIXAR'; btn.disabled = false; }
    }
}

// ── Troca de abas ─────────────────────────────────────────────
window.mudarAba = function (idAba) {
    document.querySelectorAll('.nav-item').forEach((b) => b.classList.remove('active'));
    document.querySelectorAll('.section').forEach((s) => s.classList.remove('active'));

    const navAlvo = document.querySelector(`.nav-item[data-aba="${idAba}"]`);
    if (navAlvo) navAlvo.classList.add('active');

    const abaAlvo = $(`aba-${idAba}`);
    if (abaAlvo) abaAlvo.classList.add('active');
};
