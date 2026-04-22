/* ============================================================
   EditMind — js/app.js  v3.0

   Novidades:
   - Módulo YouTube: "Processar com IA" (não só baixar)
   - Video player no painel de resultado
   - Botões "▶ Assistir" e "⬇ Baixar" separados
   - Fetch com AbortController (timeout 5min)
   - Auth guard + logout
   ============================================================ */

const API       = window.CONFIG?.API_URL ?? '';
const TIMEOUT   = 5 * 60 * 1000; // 5 minutos

// ── DOM ───────────────────────────────────────────────────────
const $ = id => document.getElementById(id);

const painelUpload  = $('painel-upload');
const painelIa      = $('painel-ia');
const areaSoltar    = $('area-soltar');
const entrada       = $('entrada-arquivo');
const nomeArq       = $('nome-arquivo');
const barraP        = $('barra-progresso');
const porcT         = $('porcentagem-envio');
const msgT          = $('mensagem-envio');
const metaRes       = $('meta-res');
const metaFps       = $('meta-fps');
const metaDur       = $('meta-duracao');
const txtTransc     = $('texto-transcricao');
const corteIni      = $('corte-inicio');
const corteFim      = $('corte-fim');
const corteMot      = $('corte-motivo');

window.ultimoResultado = null;

// ── INIT ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    if (!window.Auth?.estaLogado()) { window.location.href = 'login.html'; return; }

    const u   = window.Auth.getUsuario();
    const el  = $('user-nome');
    if (el && u) el.textContent = u.nome || u.email?.split('@')[0] || 'Usuário';

    $('btn-logout')?.addEventListener('click', () => window.Auth.logout());

    // Nav hamburguer
    const toggle = $('navToggle'), nav = $('btnNav');
    if (toggle && nav) {
        toggle.addEventListener('click', e => { e.stopPropagation(); nav.classList.toggle('open'); });
        document.addEventListener('click', e => { if (!nav.contains(e.target)) nav.classList.remove('open'); });
    }
});

// ── TIMER ─────────────────────────────────────────────────────
let _iv = null, _t0 = null;

function startTimer() {
    _t0 = Date.now();
    _iv = setInterval(() => {
        const s = Math.floor((Date.now() - _t0) / 1000);
        const el = $('timer-display');
        if (el) el.textContent =
            `${String(Math.floor(s/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`;
    }, 1000);
}

function stopTimer() {
    clearInterval(_iv); _iv = null;
    const e = _t0 ? Math.floor((Date.now() - _t0) / 1000) : 0;
    _t0 = null; return e;
}

// ── UI HELPERS ────────────────────────────────────────────────
function pct(v) {
    if (barraP) barraP.style.width  = v + '%';
    if (porcT)  porcT.textContent   = v + '%';
}

function msg(html, cor = '#6b7280') {
    if (!msgT) return;
    msgT.innerHTML   = html;
    msgT.style.color = cor;
}

function animCard(el, val) {
    if (!el) return;
    el.style.transition = 'none'; el.style.opacity = '0'; el.style.transform = 'translateY(6px)';
    el.textContent = val;
    requestAnimationFrame(() => requestAnimationFrame(() => {
        el.style.transition = 'opacity .4s ease, transform .4s ease';
        el.style.opacity    = '1'; el.style.transform = 'translateY(0)';
    }));
}

function resetUI() {
    pct(0); msg('Motor em standby.');
    if (barraP)  barraP.style.background = '';
    if (nomeArq) nomeArq.textContent     = 'Aguardando feed...';
    if (metaRes) metaRes.textContent     = '—';
    if (metaFps) metaFps.textContent     = '—';
    if (metaDur) metaDur.textContent     = '—';
    if (entrada) entrada.value           = '';
    const te = $('timer-display'); if (te) te.textContent = '00:00';
}

// ── DRAG & DROP ───────────────────────────────────────────────
if (areaSoltar) {
    ['dragenter','dragover','dragleave','drop'].forEach(e =>
        areaSoltar.addEventListener(e, ev => { ev.preventDefault(); ev.stopPropagation(); }));
    ['dragenter','dragover'].forEach(e =>
        areaSoltar.addEventListener(e, () => { areaSoltar.style.borderColor='#f97316'; areaSoltar.style.background='rgba(249,115,22,0.06)'; }));
    ['dragleave','drop'].forEach(e =>
        areaSoltar.addEventListener(e, () => { areaSoltar.style.borderColor=''; areaSoltar.style.background=''; }));
    areaSoltar.addEventListener('drop', e => processar(e.dataTransfer.files));
}
if (entrada) entrada.addEventListener('change', e => processar(e.target.files));

// ── PIPELINE PRINCIPAL ────────────────────────────────────────
async function processar(arquivos) {
    if (!arquivos?.length) return;
    const arq = arquivos[0];
    const ext = arq.name.split('.').pop().toLowerCase();
    if (!['mp4','mov','avi','webm'].includes(ext)) {
        alert('Aceito apenas: mp4, mov, avi, webm.');
        return;
    }
    await _executar(async (ctrl) => {
        const form = new FormData();
        form.append('file', arq);
        if (nomeArq) nomeArq.textContent = arq.name;
        return fetch(`${API}/api/processar`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${window.Auth.getToken()}` },
            body: form,
            signal: ctrl.signal,
        });
    });
}

// ── PROCESSAR VIA YOUTUBE (pipeline completo) ─────────────────
window.processarYouTube = async function () {
    const input = $('input-youtube');
    const btn   = $('btn-yt-processar');
    const link  = input?.value.trim();

    if (!link || (!link.includes('youtube.com') && !link.includes('youtu.be'))) {
        alert('Insira um link válido do YouTube.');
        return;
    }

    // Troca para a aba de upload e inicia feedback
    mudarAba('inicio');
    if (nomeArq) nomeArq.textContent = link;

    if (btn) { btn.disabled = true; btn.textContent = 'PROCESSANDO...'; }

    await _executar(async (ctrl) =>
        fetch(`${API}/api/processar-youtube`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${window.Auth.getToken()}`,
            },
            body: JSON.stringify({ url: link }),
            signal: ctrl.signal,
        })
    );

    if (btn) { btn.textContent = 'PROCESSAR COM IA ⚡'; btn.disabled = false; }
    if (input) input.value = '';
};

// ── EXECUTOR GENÉRICO (compartilhado por upload e YouTube) ────
async function _executar(fetchFn) {
    if (barraP) barraP.style.background = 'linear-gradient(to right,#f97316,#facc15)';
    startTimer();

    const etapas = [
        { p: 10, m: '📤 Enviando para o servidor...',         d: 0      },
        { p: 25, m: '🎵 FFmpeg extraindo áudio...',           d: 5000   },
        { p: 50, m: '🎙️ Whisper-1 transcrevendo...',         d: 12000  },
        { p: 70, m: '✏️ GPT-4o-mini corrigindo texto...',    d: 22000  },
        { p: 85, m: '🤖 GPT-4o analisando viralidade...',     d: 30000  },
        { p: 93, m: '✂️ Cortando o trecho...',                d: 40000  },
    ];
    const tids = etapas.map(({ p, m, d }) => setTimeout(() => { pct(p); msg(m); }, d));

    const ctrl = new AbortController();
    const tId  = setTimeout(() => ctrl.abort(), TIMEOUT);

    try {
        const res     = await fetchFn(ctrl);
        clearTimeout(tId); tids.forEach(clearTimeout);
        const data    = await res.json();
        const elapsed = stopTimer();

        if (!res.ok) {
            if (res.status === 401) { window.Auth.logout(); return; }
            throw new Error(data.detail || `Erro ${res.status}`);
        }

        const infos = data.detalhes_tecnicos || {};
        animCard(metaRes, infos.resolucao || 'N/A');
        animCard(metaFps, infos.fps ? `${infos.fps} FPS` : 'N/A');
        animCard(metaDur, infos.duracao_segundos ? `${infos.duracao_segundos}s` : 'N/A');

        pct(100);
        window.ultimoResultado = { ...data, elapsed };

        const mm = String(Math.floor(elapsed/60)).padStart(2,'0');
        const ss = String(elapsed%60).padStart(2,'0');
        msg(`
            <div style="display:flex;flex-direction:column;gap:10px;margin-top:10px;">
                <span style="font-size:11px;color:#22c55e;font-weight:700;">
                    ✅ Concluído em ${mm}:${ss}
                </span>
                <button onclick="mostrarResultado()"
                    style="padding:12px 28px;background:#f97316;color:white;border:none;
                           border-radius:999px;font-size:11px;font-weight:900;
                           letter-spacing:.1em;cursor:pointer;
                           box-shadow:0 8px 24px rgba(249,115,22,.4)">
                    Ver Relatório da IA ⚡
                </button>
            </div>`, '#22c55e');

    } catch (err) {
        clearTimeout(tId); tids.forEach(clearTimeout); stopTimer();
        const m_ = err.name === 'AbortError'
            ? '⏱️ Timeout: processamento demorou mais de 5 minutos.'
            : `❌ ${err.message || 'Erro desconhecido.'}`;
        msg(m_, '#ef4444');
        if (barraP) barraP.style.background = '#ef4444';
        setTimeout(resetUI, 6000);
    }
}

// ── PAINEL DE RESULTADO ───────────────────────────────────────
window.mostrarResultado = function () {
    if (window.ultimoResultado) exibirResultado(window.ultimoResultado);
};

function exibirResultado(data) {
    if (painelUpload) painelUpload.classList.add('hidden');
    if (painelIa)     { painelIa.classList.remove('hidden','fade-out'); }

    // Transcrição
    if (txtTransc) txtTransc.textContent = data.transcricao || '—';

    // Tempos do corte
    const c = data.corte_sugerido || {};
    if (corteIni) corteIni.textContent = c.inicio || '00:00:00';
    if (corteFim) corteFim.textContent = c.fim    || '00:00:00';
    if (corteMot) corteMot.textContent = c.motivo || '—';

    // Chips de meta
    const inf = data.detalhes_tecnicos || {};
    const em  = $('ia-meta-info');
    if (em && inf.resolucao) em.textContent = `${inf.resolucao} • ${inf.fps} FPS • ${inf.duracao_segundos}s`;
    if (data.elapsed !== undefined) {
        const tp = $('tempo-processamento');
        if (tp) tp.textContent =
            `Processado em ${String(Math.floor(data.elapsed/60)).padStart(2,'0')}:${String(data.elapsed%60).padStart(2,'0')}`;
    }

    // ── Video player + botões ─────────────────────────────────
    const area = $('area-download');
    if (area && data.url_corte) {
        const urlCorte = data.url_corte.startsWith('http')
            ? data.url_corte           // Supabase Storage (URL absoluta)
            : `${API}${data.url_corte}`; // Render local (/outputs/...)

        area.innerHTML = `
            <!-- Player -->
            <div class="video-result-wrapper">
                <video
                    id="player-resultado"
                    src="${urlCorte}"
                    controls
                    preload="metadata"
                    class="video-result-player"
                    poster=""
                ></video>
            </div>

            <!-- Botões -->
            <div class="result-btns">
                <button
                    class="btn-assistir"
                    onclick="document.getElementById('player-resultado').play()">
                    ▶ Assistir
                </button>
                <a
                    href="${urlCorte}"
                    download="Corte_EditMind.mp4"
                    class="btn-download">
                    ⬇ Baixar MP4
                </a>
            </div>
        `;
    }
}

window.resetarNovoCorte = function () {
    if (painelIa) painelIa.classList.add('fade-out');
    setTimeout(() => {
        if (painelIa)     { painelIa.classList.add('hidden'); painelIa.classList.remove('fade-out'); }
        if (painelUpload) painelUpload.classList.remove('hidden');
        resetUI();
        window.ultimoResultado = null;
    }, 400);
};

// ── DOWNLOAD DO YOUTUBE (só baixar, sem processar) ────────────
window.baixarYouTube = async function () {
    const input = $('input-youtube');
    const btn   = $('btn-yt-baixar');
    const link  = input?.value.trim();
    if (!link || (!link.includes('youtube.com') && !link.includes('youtu.be'))) {
        alert('Insira um link válido do YouTube.');
        return;
    }
    if (btn) { btn.disabled = true; btn.textContent = 'BAIXANDO...'; }
    try {
        const res = await fetch(`${API}/api/download-youtube`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${window.Auth.getToken()}`,
            },
            body: JSON.stringify({ url: link }),
            signal: AbortSignal.timeout(300_000),
        });
        if (!res.ok) { const e = await res.json(); throw new Error(e.detail); }
        const blob = await res.blob();
        const url  = URL.createObjectURL(blob);
        const a    = document.createElement('a');
        a.href = url; a.download = 'Video_EditMind.mp4';
        document.body.appendChild(a); a.click();
        URL.revokeObjectURL(url); document.body.removeChild(a);
        if (btn) { btn.textContent = 'CONCLUÍDO ✅'; input.value = ''; }
        setTimeout(() => { if (btn) { btn.textContent = 'SÓ BAIXAR'; btn.disabled = false; } }, 3000);
    } catch (e) {
        alert('Erro: ' + e.message);
        if (btn) { btn.textContent = 'SÓ BAIXAR'; btn.disabled = false; }
    }
};

// ── ABAS ──────────────────────────────────────────────────────
window.mudarAba = function (id) {
    document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    document.querySelector(`.nav-item[data-aba="${id}"]`)?.classList.add('active');
    $(`aba-${id}`)?.classList.add('active');
};
