/* ============================================================
   EditMind — js/app.js  v5.0
   - Múltiplos recortes com foco/duração
   - YouTube + TikTok via endpoints genéricos
   - Download real via backend
   - UX refinada: hover apenas em controles clicáveis
   ============================================================ */

const API = window.CONFIG?.API_URL ?? '';
const TIMEOUT = 5 * 60 * 1000;

const $ = id => document.getElementById(id);

const painelUpload = $('painel-upload');
const painelIa = $('painel-ia');
const areaSoltar = $('area-soltar');
const entrada = $('entrada-arquivo');
const nomeArq = $('nome-arquivo');
const barraP = $('barra-progresso');
const porcT = $('porcentagem-envio');
const msgT = $('mensagem-envio');
const metaRes = $('meta-res');
const metaFps = $('meta-fps');
const metaDur = $('meta-duracao');
const txtTransc = $('texto-transcricao');
const corteIni = $('corte-inicio');
const corteFim = $('corte-fim');
const corteMot = $('corte-motivo');
const conteudosLista = $('conteudos-lista');
const conteudosEmptyTemplate = $('conteudos-empty-template');
const conteudosFeedback = $('conteudos-feedback');
const quantidadeRecortes = $('quantidade-recortes');
const recortesConfig = $('recortes-config');
const formatoVertical = $('formato-vertical');
const conteudosCount = $('conteudos-count');
const btnSelectAll = $('btn-select-all');
const btnClearSelection = $('btn-clear-selection');
const btnDownloadSelected = $('btn-download-selected');
const btnDeleteSelected = $('btn-delete-selected');
const profileNome = $('profile-nome');
const profileEmail = $('profile-email');
const profileSenha = $('profile-senha');
const profileFeedback = $('profile-feedback');

window.ultimoResultado = null;
window.meusCortes = [];
window.selectedCortes = new Set();

const FOCOS = [
    'Livre', 'Humor', 'Terror', 'Emocionante', 'Triste',
    'Polêmico', 'Educativo', 'Impactante', 'Motivacional', 'Surpreendente'
];

const DURACOES = [
    { value: 'curto', label: '< 30s' },
    { value: 'medio', label: '30s - 60s' },
    { value: 'longo', label: '> 60s' },
];

const PRESET_PARA_DURACAO = {
    '<30s': 'curto',
    '30s-60s': 'medio',
    '>60s': 'longo',
};

const DURACAO_PARA_PRESET = {
    curto: '<30s',
    medio: '30s-60s',
    longo: '>60s',
};

let engineDuracaoPadrao = 'medio';
let _iv = null;
let _t0 = null;

// ── INIT ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    if (!window.Auth?.estaLogado()) {
        window.location.href = 'login.html';
        return;
    }

    const u = window.Auth.getUsuario();
    const el = $('user-nome');
    if (el && u) el.textContent = u.nome || u.email?.split('@')[0] || 'Usuário';

    const logoutFn = () => window.Auth.logout();
    $('btn-logout')?.addEventListener('click', logoutFn);
    $('btn-logout-mobile')?.addEventListener('click', logoutFn);

    const toggle = $('navToggle'), nav = $('btnNav');
    if (toggle && nav) {
        toggle.addEventListener('click', e => {
            e.stopPropagation();
            nav.classList.toggle('open');
        });
        document.addEventListener('click', e => {
            if (!nav.contains(e.target)) nav.classList.remove('open');
        });
    }

    quantidadeRecortes?.addEventListener('change', renderRecortesConfig);
    renderRecortesConfig();

    document.querySelectorAll('.engine-card[data-duration], .engine-card[data-preset]').forEach(card => {
        card.addEventListener('click', () => selecionarEnginePreset(card));
    });

    btnSelectAll?.addEventListener('click', selecionarTodosCortes);
    btnClearSelection?.addEventListener('click', limparSelecaoCortes);
    btnDownloadSelected?.addEventListener('click', baixarSelecionadosZip);
    btnDeleteSelected?.addEventListener('click', excluirSelecionados);

    carregarPerfil();
    $('form-profile-nome')?.addEventListener('submit', salvarNomePerfil);
    $('form-profile-email')?.addEventListener('submit', salvarEmailPerfil);
    $('form-profile-senha')?.addEventListener('submit', salvarSenhaPerfil);
});

// ── ENGINE PRESETS ───────────────────────────────────────────
function normalizarPresetEngine(valor) {
    if (!valor) return 'medio';
    const v = String(valor).trim();
    if (PRESET_PARA_DURACAO[v]) return PRESET_PARA_DURACAO[v];
    return ['curto', 'medio', 'longo'].includes(v) ? v : 'medio';
}

window.selecionarEnginePreset = function (card) {
    if (!card) return;
    const valor = card.getAttribute('data-preset') || card.getAttribute('data-duration') || 'medio';
    engineDuracaoPadrao = normalizarPresetEngine(valor);

    document.querySelectorAll('.engine-card[data-duration], .engine-card[data-preset]').forEach(c => {
        c.classList.remove('active', 'selected');
    });
    card.classList.add('selected', 'active');

    document.querySelectorAll('.recorte-duracao').forEach(select => {
        select.value = engineDuracaoPadrao;
    });
};

// ── AUTH HELPERS ─────────────────────────────────────────────
function getAuthToken() {
    return localStorage.getItem('editmind_token') || window.Auth?.getToken?.() || null;
}

function getAuthHeaders(extra = {}) {
    const token = getAuthToken();
    return {
        ...extra,
        ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
    };
}

// ── CONFIGURAÇÃO DE RECORTES ─────────────────────────────────
function renderRecortesConfig() {
    if (!recortesConfig) return;
    const qtd = Math.max(1, Math.min(3, Number(quantidadeRecortes?.value || 1)));
    const html = Array.from({ length: qtd }, (_, i) => {
        const n = i + 1;
        return `
            <div class="recorte-config-item" data-recorte-index="${n}">
                <div class="recorte-config-title">Recorte ${n}</div>
                <div class="recorte-config-grid">
                    <div>
                        <label class="input-label">Duração</label>
                        <select class="input-field select-field recorte-duracao" data-recorte-duration="${n}">
                            ${DURACOES.map(d => `<option value="${d.value}" ${d.value === engineDuracaoPadrao ? 'selected' : ''}>${d.label}</option>`).join('')}
                        </select>
                    </div>
                    <div>
                        <label class="input-label">Foco do Gancho</label>
                        <select class="input-field select-field recorte-foco" data-recorte-focus="${n}">
                            ${FOCOS.map(f => `<option value="${f}">${f}</option>`).join('')}
                        </select>
                    </div>
                </div>
            </div>
        `;
    }).join('');
    recortesConfig.innerHTML = html;
}

function coletarConfigProcessamento() {
    const qtd = Math.max(1, Math.min(3, Number(quantidadeRecortes?.value || 1)));
    const cortes = [];
    for (let i = 1; i <= qtd; i++) {
        cortes.push({
            duracao_tipo: document.querySelector(`[data-recorte-duration="${i}"]`)?.value || engineDuracaoPadrao,
            foco: document.querySelector(`[data-recorte-focus="${i}"]`)?.value || 'Livre',
        });
    }
    return {
        cortes,
        formato_vertical: Boolean(formatoVertical?.checked),
    };
}

// ── TIMER ─────────────────────────────────────────────────────
function startTimer() {
    _t0 = Date.now();
    _iv = setInterval(() => {
        const s = Math.floor((Date.now() - _t0) / 1000);
        const el = $('timer-display');
        if (el) el.textContent = `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
    }, 1000);
}

function stopTimer() {
    clearInterval(_iv);
    _iv = null;
    const e = _t0 ? Math.floor((Date.now() - _t0) / 1000) : 0;
    _t0 = null;
    return e;
}

// ── UI HELPERS ────────────────────────────────────────────────
function pct(v) {
    if (barraP) barraP.style.width = v + '%';
    if (porcT) porcT.textContent = v + '%';
}

function msg(html, cor = '#6b7280') {
    if (!msgT) return;
    msgT.innerHTML = html;
    msgT.style.color = cor;
}

function animCard(el, val) {
    if (!el) return;
    el.style.transition = 'none';
    el.style.opacity = '0';
    el.style.transform = 'translateY(6px)';
    el.textContent = val;
    requestAnimationFrame(() => requestAnimationFrame(() => {
        el.style.transition = 'opacity .4s ease, transform .4s ease';
        el.style.opacity = '1';
        el.style.transform = 'translateY(0)';
    }));
}

function resetUI() {
    pct(0);
    msg('Engine pronta para receber seu projeto.');
    if (barraP) barraP.style.background = '';
    if (nomeArq) nomeArq.textContent = 'Aguardando feed...';
    if (metaRes) metaRes.textContent = '—';
    if (metaFps) metaFps.textContent = '—';
    if (metaDur) metaDur.textContent = '—';
    if (entrada) entrada.value = '';
    const te = $('timer-display');
    if (te) te.textContent = '00:00';
}

function escaparHtml(texto) {
    return String(texto ?? '')
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#39;');
}

function montarUrlVideo(videoUrl) {
    if (!videoUrl) return '#';
    return videoUrl.startsWith('http') ? videoUrl : `${API}${videoUrl}`;
}

function formatarDataPtBR(isoString) {
    if (!isoString) return 'Data indisponível';
    const data = new Date(isoString);
    if (Number.isNaN(data.getTime())) return 'Data inválida';
    return data.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
}

function duracaoLabel(tipo) {
    return DURACOES.find(d => d.value === tipo)?.label || tipo || '—';
}

// ── DRAG & DROP ───────────────────────────────────────────────
if (areaSoltar) {
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(e =>
        areaSoltar.addEventListener(e, ev => { ev.preventDefault(); ev.stopPropagation(); }));
    ['dragenter', 'dragover'].forEach(e =>
        areaSoltar.addEventListener(e, () => {
            areaSoltar.style.borderColor = '#f97316';
            areaSoltar.style.background = 'rgba(249,115,22,0.06)';
        }));
    ['dragleave', 'drop'].forEach(e =>
        areaSoltar.addEventListener(e, () => {
            areaSoltar.style.borderColor = '';
            areaSoltar.style.background = '';
        }));
    areaSoltar.addEventListener('drop', e => processar(e.dataTransfer.files));
}
if (entrada) entrada.addEventListener('change', e => processar(e.target.files));

// ── PIPELINE PRINCIPAL ────────────────────────────────────────
async function processar(arquivos) {
    if (!arquivos?.length) return;
    const arq = arquivos[0];
    const ext = arq.name.split('.').pop().toLowerCase();
    if (!['mp4', 'mov', 'avi', 'webm'].includes(ext)) {
        alert('Aceito apenas: mp4, mov, avi, webm.');
        return;
    }

    const config = coletarConfigProcessamento();
    await _executar(async (ctrl) => {
        const form = new FormData();
        form.append('file', arq);
        form.append('cortes_config', JSON.stringify(config));
        form.append('formato_vertical', String(config.formato_vertical));
        if (nomeArq) nomeArq.textContent = arq.name;
        return fetch(`${API}/api/processar`, {
            method: 'POST',
            headers: getAuthHeaders(),
            body: form,
            signal: ctrl.signal,
        });
    });
}

// ── PROCESSAR LINKS ──────────────────────────────────────────
async function processarLinkGenerico(inputId, btnId, nomeFonte) {
    const input = $(inputId);
    const btn = $(btnId);
    const link = input?.value.trim();
    if (!link) {
        alert(`Insira um link válido do ${nomeFonte}.`);
        return;
    }

    mudarAba('inicio');
    if (nomeArq) nomeArq.textContent = link;
    if (btn) { btn.disabled = true; btn.textContent = 'Processando...'; }

    const config = coletarConfigProcessamento();
    await _executar(async (ctrl) =>
        fetch(`${API}/api/processar-link`, {
            method: 'POST',
            headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ url: link, config }),
            signal: ctrl.signal,
        })
    );

    if (btn) { btn.textContent = 'Processar'; btn.disabled = false; }
    if (input) input.value = '';
}

window.processarYouTube = () => processarLinkGenerico('input-youtube', 'btn-yt-processar', 'YouTube');
window.processarTikTok = () => processarLinkGenerico('input-tiktok', 'btn-tt-processar', 'TikTok');

window.processarLink = function (plataforma) {
    const p = String(plataforma || '').toLowerCase();
    if (p === 'youtube') return window.processarYouTube();
    if (p === 'tiktok') return window.processarTikTok();
    alert('Plataforma não suportada.');
};

async function baixarLinkGenerico(inputId, btnId, nomeArquivo = 'Video_EditMind.mp4') {
    const input = $(inputId);
    const btn = $(btnId);
    const link = input?.value.trim();
    if (!link) {
        alert('Insira um link válido.');
        return;
    }
    if (btn) { btn.disabled = true; btn.textContent = 'Baixando...'; }

    try {
        const res = await fetch(`${API}/api/download-link`, {
            method: 'POST',
            headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ url: link }),
            signal: AbortSignal.timeout(300_000),
        });
        if (!res.ok) {
            const e = await res.json().catch(() => ({}));
            throw new Error(e.detail || `Erro ${res.status}`);
        }
        const blob = await res.blob();
        baixarBlob(blob, nomeArquivo);
        if (btn) btn.textContent = 'Concluído';
        if (input) input.value = '';
        setTimeout(() => { if (btn) { btn.textContent = 'Baixar MP4'; btn.disabled = false; } }, 2500);
    } catch (e) {
        alert('Erro: ' + (e.message || 'Falha no download.'));
        if (btn) { btn.textContent = 'Baixar MP4'; btn.disabled = false; }
    }
}

window.baixarYouTube = () => baixarLinkGenerico('input-youtube', 'btn-yt-baixar', 'Video_YouTube_EditMind.mp4');
window.baixarTikTok = () => baixarLinkGenerico('input-tiktok', 'btn-tt-baixar', 'Video_TikTok_EditMind.mp4');

window.baixarLink = function (plataforma) {
    const p = String(plataforma || '').toLowerCase();
    if (p === 'youtube') return window.baixarYouTube();
    if (p === 'tiktok') return window.baixarTikTok();
    alert('Plataforma não suportada.');
};

// ── EXECUTOR GENÉRICO ─────────────────────────────────────────
async function _executar(fetchFn) {
    if (barraP) barraP.style.background = 'linear-gradient(to right,#f97316,#facc15)';
    startTimer();

    const etapas = [
        { p: 10, m: 'Enviando para o servidor...', d: 0 },
        { p: 25, m: 'FFmpeg extraindo áudio...', d: 5000 },
        { p: 50, m: 'Whisper transcrevendo...', d: 12000 },
        { p: 70, m: 'IA avaliando o vídeo inteiro...', d: 22000 },
        { p: 85, m: 'Selecionando recortes por foco...', d: 32000 },
        { p: 93, m: 'Renderizando os cortes...', d: 42000 },
    ];
    const tids = etapas.map(({ p, m, d }) => setTimeout(() => { pct(p); msg(m); }, d));

    const ctrl = new AbortController();
    const tId = setTimeout(() => ctrl.abort(), TIMEOUT);

    try {
        const res = await fetchFn(ctrl);
        clearTimeout(tId); tids.forEach(clearTimeout);
        const data = await res.json();
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

        const mm = String(Math.floor(elapsed / 60)).padStart(2, '0');
        const ss = String(elapsed % 60).padStart(2, '0');
        msg(`
            <div style="display:flex;flex-direction:column;gap:10px;margin-top:10px;">
                <span style="font-size:11px;color:#22c55e;font-weight:700;">Concluído em ${mm}:${ss}</span>
                <button onclick="mostrarResultado()" class="btn-inline-result">Ver Relatório da IA</button>
            </div>`, '#22c55e');
    } catch (err) {
        clearTimeout(tId); tids.forEach(clearTimeout); stopTimer();
        const m_ = err.name === 'AbortError'
            ? 'Timeout: processamento demorou mais de 5 minutos.'
            : `${err.message || 'Erro desconhecido.'}`;
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
    if (painelIa) painelIa.classList.remove('hidden', 'fade-out');

    if (txtTransc) txtTransc.textContent = data.transcricao || '—';

    const cortes = Array.isArray(data.cortes) && data.cortes.length ? data.cortes : [{
        ...data.corte_sugerido,
        url_corte: data.url_corte,
        storage: data.storage,
        foco: 'Livre',
        duracao_tipo: 'medio'
    }];

    const primeiro = cortes[0] || {};
    if (corteIni) corteIni.textContent = primeiro.inicio || '00:00:00';
    if (corteFim) corteFim.textContent = primeiro.fim || '00:00:00';
    if (corteMot) corteMot.textContent = primeiro.motivo || '—';

    const inf = data.detalhes_tecnicos || {};
    const em = $('ia-meta-info');
    if (em && inf.resolucao) em.textContent = `${inf.resolucao} • ${inf.fps} FPS • ${inf.duracao_segundos}s`;
    if (data.elapsed !== undefined) {
        const tp = $('tempo-processamento');
        if (tp) tp.textContent = `Processado em ${String(Math.floor(data.elapsed / 60)).padStart(2, '0')}:${String(data.elapsed % 60).padStart(2, '0')}`;
    }

    const area = $('area-download');
    if (!area) return;
    area.innerHTML = cortes.map((corte, idx) => renderCorteResultado(corte, idx)).join('');
}

function renderCorteResultado(corte, idx) {
    const urlCorte = montarUrlVideo(corte.url_corte || corte.video_url);
    const storageTag = corte.storage === 'supabase'
        ? '<span class="storage-chip storage-ok">Supabase Storage</span>'
        : '<span class="storage-chip storage-local">Servidor local</span>';
    const titulo = `Recorte ${corte.index || idx + 1}`;
    return `
        <article class="resultado-corte-card">
            <div class="resultado-corte-head">
                <strong>${titulo}</strong>
                ${storageTag}
            </div>
            <video src="${urlCorte}" controls preload="metadata" class="video-result-player" playsinline></video>
            <div class="resultado-meta-grid">
                <span>Início: <b>${escaparHtml(corte.inicio || '—')}</b></span>
                <span>Fim: <b>${escaparHtml(corte.fim || '—')}</b></span>
                <span>Duração: <b>${escaparHtml(String(corte.duracao_segundos || '—'))}s</b></span>
                <span>Foco: <b>${escaparHtml(corte.foco || 'Livre')}</b></span>
            </div>
            <p class="resultado-motivo">${escaparHtml(corte.motivo || 'Trecho viral identificado.')}</p>
            <div class="result-btns">
                <button type="button" class="btn-assistir btn-play-inline">Assistir</button>
                <button type="button" class="btn-download btn-download-video" data-url="${urlCorte}">Baixar MP4</button>
            </div>
        </article>
    `;
}

window.resetarNovoCorte = function () {
    if (painelIa) painelIa.classList.add('fade-out');
    setTimeout(() => {
        if (painelIa) { painelIa.classList.add('hidden'); painelIa.classList.remove('fade-out'); }
        if (painelUpload) painelUpload.classList.remove('hidden');
        resetUI();
        window.ultimoResultado = null;
    }, 400);
};

// ── DOWNLOAD REAL DOS RECORTES ────────────────────────────────
function baixarBlob(blob, filename) {
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = blobUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(blobUrl);
}

async function baixarArquivoVideo(urlVideo, botaoRef = null) {
    if (!urlVideo || urlVideo === '#') {
        alert('Não foi possível identificar a URL do vídeo para download.');
        return;
    }
    const btn = botaoRef || null;
    const textoOriginal = btn ? btn.textContent : '';
    if (btn) { btn.disabled = true; btn.textContent = 'Baixando...'; }
    try {
        const endpoint = `${API}/api/cortes/download?video_url=${encodeURIComponent(urlVideo)}`;
        const res = await fetch(endpoint, { method: 'GET', headers: getAuthHeaders() });
        if (!res.ok) throw new Error(`Falha no download (${res.status}).`);
        const blob = await res.blob();
        baixarBlob(blob, 'Corte_EditMind.mp4');
    } catch (err) {
        console.error('[EditMind] Erro ao baixar vídeo:', err);
        alert('Não foi possível baixar o vídeo agora. Tente novamente em instantes.');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = textoOriginal || 'Baixar MP4'; }
    }
}
window.baixarArquivoVideo = baixarArquivoVideo;

// ── ABAS ──────────────────────────────────────────────────────
window.mudarAba = function (id) {
    document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    document.querySelector(`.nav-item[data-aba="${id}"]`)?.classList.add('active');
    $(`aba-${id}`)?.classList.add('active');
    if (id === 'conteudos') carregarMeusConteudos();
};

// ── MEUS CONTEÚDOS ────────────────────────────────────────────
function renderEmptyStateConteudos() {
    if (!conteudosLista || !conteudosEmptyTemplate) return;
    conteudosLista.innerHTML = conteudosEmptyTemplate.innerHTML;
}

function setConteudosFeedback(texto, tipo = 'erro') {
    if (!conteudosFeedback) return;
    conteudosFeedback.textContent = texto || '';
    conteudosFeedback.style.color = tipo === 'erro' ? '#ef4444' : '#22c55e';
}

function renderConteudos(cortes) {
    if (!conteudosLista) return;
    window.meusCortes = Array.isArray(cortes) ? cortes : [];
    if (window.meusCortes.length === 0) {
        renderEmptyStateConteudos();
        limparSelecaoCortes();
        return;
    }
    limparSelecaoCortes();

    conteudosLista.innerHTML = window.meusCortes.map((corte) => {
        const titulo = escaparHtml(corte.titulo || 'Sem título');
        const dataFmt = formatarDataPtBR(corte.criado_em);
        const urlVideo = montarUrlVideo(corte.video_url);
        const corteId = escaparHtml(corte.id || '');
        const foco = escaparHtml(corte.foco || 'Livre');
        const duracaoTipo = escaparHtml(duracaoLabel(corte.duracao_tipo));
        return `
            <article class="tool-bentoCard conteudo-card" data-corte-id="${corteId}">
                <label class="conteudo-select-wrap"><input type="checkbox" class="conteudo-select" data-corte-id="${corteId}"> Selecionar</label>
                <video src="${urlVideo}" controls preload="metadata" class="conteudo-video"></video>
                <h3 class="tool-title conteudo-title">${titulo}</h3>
                <p class="tool-description conteudo-date">Criado em: ${dataFmt}</p>
                <p class="conteudo-tags">Foco: <b>${foco}</b> · Duração: <b>${duracaoTipo}</b></p>
                <div class="result-btns">
                    <a href="${urlVideo}" target="_blank" rel="noopener noreferrer" class="btn-assistir">Abrir vídeo</a>
                    <button type="button" class="btn-download btn-download-video" data-url="${urlVideo}">Baixar</button>
                    <button type="button" class="btn-excluir-corte" data-corte-id="${corteId}">Excluir</button>
                </div>
            </article>
        `;
    }).join('');
}

async function carregarMeusConteudos() {
    const token = getAuthToken();
    if (!token) { window.Auth.logout(); return; }
    try {
        setConteudosFeedback('');
        const res = await fetch(`${API}/api/meus-cortes`, { method: 'GET', headers: getAuthHeaders() });
        if (res.status === 401) { window.Auth.logout(); return; }
        const dados = await res.json();
        if (!res.ok || !dados?.sucesso) throw new Error(dados?.detail || 'Falha ao carregar conteúdos.');
        renderConteudos(Array.isArray(dados.cortes) ? dados.cortes : []);
    } catch (err) {
        console.error('[EditMind] Erro ao carregar Meus Conteúdos:', err);
        setConteudosFeedback(err.message || 'Falha ao carregar conteúdos.');
        renderEmptyStateConteudos();
    }
}

async function excluirCorte(corteId, btn) {
    if (!corteId) return;
    if (!confirm('Tem certeza que deseja excluir este recorte?')) return;
    const token = getAuthToken();
    if (!token) { window.Auth.logout(); return; }
    try {
        setConteudosFeedback('');
        if (btn) btn.disabled = true;
        const res = await fetch(`${API}/api/cortes/${corteId}`, { method: 'DELETE', headers: getAuthHeaders() });
        if (res.status === 401) { window.Auth.logout(); return; }
        const dados = await res.json();
        if (!res.ok || !dados?.sucesso) throw new Error(dados?.detail || dados?.mensagem || 'Erro ao excluir recorte.');
        window.meusCortes = window.meusCortes.filter(c => c.id !== corteId);
        document.querySelector(`.conteudo-card[data-corte-id="${corteId}"]`)?.remove();
        setConteudosFeedback('Recorte excluído com sucesso.', 'ok');
        if (window.meusCortes.length === 0) renderEmptyStateConteudos();
    } catch (err) {
        console.error(`[EditMind] Erro ao excluir recorte ${corteId}:`, err);
        setConteudosFeedback(err.message || 'Falha ao excluir recorte.');
        alert(err.message || 'Falha ao excluir recorte.');
    } finally {
        if (btn) btn.disabled = false;
    }
}

function setProfileFeedback(texto, tipo = 'ok') {
    if (!profileFeedback) return;
    profileFeedback.textContent = texto || '';
    profileFeedback.style.color = tipo === 'erro' ? '#ef4444' : '#22c55e';
}

async function carregarPerfil() {
    const token = getAuthToken();
    if (!token) return;
    try {
        const res = await fetch(`${API}/api/user/profile`, { headers: getAuthHeaders() });
        if (!res.ok) return;
        const data = await res.json();
        const perfil = data?.perfil || {};
        const nome = perfil.nome || perfil.email?.split('@')[0] || 'Usuário';
        if (profileNome) profileNome.value = perfil.nome || '';
        if (profileEmail) profileEmail.value = perfil.email || '';
        const userEl = $('user-nome');
        if (userEl) userEl.textContent = nome;
        const oldUser = window.Auth?.getUsuario?.() || {};
        localStorage.setItem(window.CONFIG?.USER_KEY || 'editmind_user', JSON.stringify({ ...oldUser, nome, email: perfil.email || oldUser.email }));
    } catch (e) {
        console.warn('Falha ao carregar perfil', e);
    }
}

async function salvarNomePerfil(event) {
    event.preventDefault();
    const nome = profileNome?.value.trim();
    if (!nome) return setProfileFeedback('Informe um nome válido.', 'erro');
    const res = await fetch(`${API}/api/user/profile/name`, {
        method: 'PATCH',
        headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ nome }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return setProfileFeedback(data.detail || 'Não foi possível atualizar o nome.', 'erro');
    setProfileFeedback('Nome atualizado com sucesso.');
    carregarPerfil();
}

async function salvarEmailPerfil(event) {
    event.preventDefault();
    const email = profileEmail?.value.trim();
    if (!email) return setProfileFeedback('Informe um e-mail válido.', 'erro');
    const res = await fetch(`${API}/api/user/profile/email`, {
        method: 'PATCH',
        headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ email }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return setProfileFeedback(data.detail || 'Não foi possível atualizar o e-mail.', 'erro');
    setProfileFeedback(data.mensagem || 'Verifique seu e-mail para confirmar a alteração.');
}

async function salvarSenhaPerfil(event) {
    event.preventDefault();
    const nova_senha = profileSenha?.value || '';
    if (nova_senha.length < 6) return setProfileFeedback('A senha deve ter pelo menos 6 caracteres.', 'erro');
    const res = await fetch(`${API}/api/user/profile/password`, {
        method: 'PATCH',
        headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ nova_senha }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return setProfileFeedback(data.detail || 'Não foi possível atualizar a senha.', 'erro');
    profileSenha.value = '';
    setProfileFeedback('Senha atualizada com sucesso.');
}

function atualizarContadorSelecao() {
    if (!conteudosCount) return;
    const total = window.selectedCortes.size;
    conteudosCount.textContent = `${total} selecionado${total === 1 ? '' : 's'}`;
}

function selecionarTodosCortes() {
    window.meusCortes.forEach(c => { if (c.id) window.selectedCortes.add(c.id); });
    document.querySelectorAll('.conteudo-select').forEach(cb => { cb.checked = true; });
    atualizarContadorSelecao();
}

function limparSelecaoCortes() {
    window.selectedCortes.clear();
    document.querySelectorAll('.conteudo-select').forEach(cb => { cb.checked = false; });
    atualizarContadorSelecao();
}

async function baixarSelecionadosZip() {
    if (!window.selectedCortes.size) return alert('Selecione ao menos um recorte.');
    const res = await fetch(`${API}/api/cortes/bulk-download`, {
        method: 'POST',
        headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ ids: Array.from(window.selectedCortes) }),
    });
    if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        return alert(data.detail || 'Falha ao baixar ZIP.');
    }
    const blob = await res.blob();
    baixarBlob(blob, 'recortes_editmind.zip');
}

async function excluirSelecionados() {
    if (!window.selectedCortes.size) return alert('Selecione ao menos um recorte.');
    if (!confirm(`Excluir ${window.selectedCortes.size} recorte(s)?`)) return;
    const res = await fetch(`${API}/api/cortes/bulk-delete`, {
        method: 'POST',
        headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ ids: Array.from(window.selectedCortes) }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return alert(data.detail || 'Falha ao excluir recortes.');
    const ids = new Set(window.selectedCortes);
    window.meusCortes = window.meusCortes.filter(c => !ids.has(c.id));
    ids.forEach(id => document.querySelector(`.conteudo-card[data-corte-id="${id}"]`)?.remove());
    limparSelecaoCortes();
    setConteudosFeedback(`${data.excluidos || ids.size} recorte(s) excluído(s).`, 'ok');
    if (!window.meusCortes.length) renderEmptyStateConteudos();
}

// ── EVENT DELEGATION ─────────────────────────────────────────
document.addEventListener('click', (event) => {
    const btnDownload = event.target.closest('.btn-download-video');
    if (btnDownload) {
        const videoUrl = btnDownload.getAttribute('data-url');
        baixarArquivoVideo(videoUrl, btnDownload);
        return;
    }

    const btnPlay = event.target.closest('.btn-play-inline');
    if (btnPlay) {
        const card = btnPlay.closest('.resultado-corte-card');
        const video = card?.querySelector('video');
        if (video) { video.scrollIntoView({ behavior: 'smooth', block: 'center' }); video.play(); }
        return;
    }

    const btnExcluir = event.target.closest('.btn-excluir-corte');
    if (btnExcluir) {
        excluirCorte(btnExcluir.getAttribute('data-corte-id'), btnExcluir);
        return;
    }

    const cb = event.target.closest('.conteudo-select');
    if (cb) {
        const id = cb.getAttribute('data-corte-id');
        if (cb.checked) window.selectedCortes.add(id);
        else window.selectedCortes.delete(id);
        atualizarContadorSelecao();
    }
});
