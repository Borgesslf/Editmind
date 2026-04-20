/* ============================================================
   EditMind — js/app.js
   ============================================================ */

const API_BASE_URL = "https://editmind-ay26.onrender.com";
const HEADERS_PADRAO = { "ngrok-skip-browser-warning": "true" };

const painelUpload = document.getElementById('painel-upload');
const areaSoltar = document.getElementById('area-soltar');
const entradaArquivo = document.getElementById('entrada-arquivo');
const nomeArquivoTexto = document.getElementById('nome-arquivo');
const barraProgresso = document.getElementById('barra-progresso');
const porcentagemTexto = document.getElementById('porcentagem-envio');
const mensagemTexto = document.getElementById('mensagem-envio');
const metaRes = document.getElementById('meta-res');
const metaFps = document.getElementById('meta-fps');
const metaDuracao = document.getElementById('meta-duracao');
const painelIa = document.getElementById('painel-ia');
const textoTranscricao = document.getElementById('texto-transcricao');
const corteInicio = document.getElementById('corte-inicio');
const corteFim = document.getElementById('corte-fim');
const corteMotivo = document.getElementById('corte-motivo');

window.ultimoResultadoIA = null;

let _timerInterval = null;
let _timerStart = null;

function iniciarTimer() {
    _timerStart = Date.now();

    _timerInterval = setInterval(() => {
        const elapsed = Math.floor((Date.now() - _timerStart) / 1000);
        const m = String(Math.floor(elapsed / 60)).padStart(2, '0');
        const s = String(elapsed % 60).padStart(2, '0');
        const el = document.getElementById('timer-display');

        if (el) el.textContent = `${m}:${s}`;
    }, 1000);
}

function pararTimer() {
    clearInterval(_timerInterval);
    _timerInterval = null;

    const elapsed = _timerStart
        ? Math.floor((Date.now() - _timerStart) / 1000)
        : 0;

    _timerStart = null;
    return elapsed;
}

['dragenter', 'dragover', 'dragleave', 'drop'].forEach(evt => {
    areaSoltar.addEventListener(evt, e => {
        e.preventDefault();
        e.stopPropagation();
    });
});

['dragenter', 'dragover'].forEach(evt => {
    areaSoltar.addEventListener(evt, () => {
        areaSoltar.style.borderColor = '#f97316';
        areaSoltar.style.background = 'rgba(249,115,22,0.06)';
    });
});

['dragleave', 'drop'].forEach(evt => {
    areaSoltar.addEventListener(evt, () => {
        areaSoltar.style.borderColor = '';
        areaSoltar.style.background = '';
    });
});

areaSoltar.addEventListener('drop', e => processarArquivos(e.dataTransfer.files));
entradaArquivo.addEventListener('change', e => processarArquivos(e.target.files));

function setProgresso(pct) {
    barraProgresso.style.width = pct + '%';
    porcentagemTexto.textContent = pct + '%';
}

function setMensagem(html, cor = '#6b7280') {
    mensagemTexto.innerHTML = html;
    mensagemTexto.style.color = cor;
}

function animarMetaCard(elemento, valor) {
    elemento.style.transition = 'none';
    elemento.style.opacity = '0';
    elemento.style.transform = 'translateY(6px)';
    elemento.textContent = valor;

    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            elemento.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
            elemento.style.opacity = '1';
            elemento.style.transform = 'translateY(0)';
        });
    });
}

function resetUI() {
    setProgresso(0);
    setMensagem('Motor Python em Standby.');
    barraProgresso.style.background = '';
    nomeArquivoTexto.textContent = 'Aguardando feed...';
    metaRes.textContent = '—';
    metaFps.textContent = '—';
    metaDuracao.textContent = '—';
    entradaArquivo.value = '';

    const timerEl = document.getElementById('timer-display');
    if (timerEl) timerEl.textContent = '00:00';
}

async function processarArquivos(arquivos) {
    if (!arquivos || arquivos.length === 0) return;

    const arquivo = arquivos[0];

    const tiposValidos = ['video/mp4', 'video/quicktime', 'video/x-msvideo', 'video/webm'];
    const extsValidas = /\.(mp4|mov|avi|webm)$/i;

    if (!tiposValidos.includes(arquivo.type) && !extsValidas.test(arquivo.name)) {
        alert('O EditMind aceita apenas arquivos mp4, mov, avi e webm.');
        return;
    }

    nomeArquivoTexto.textContent = arquivo.name;
    barraProgresso.style.background = 'linear-gradient(to right, #f97316, #facc15)';

    iniciarTimer();

    const etapas = [
        { pct: 10, msg: '📤 Enviando vídeo para o servidor...', delay: 0 },
        { pct: 25, msg: '🎵 FFmpeg extraindo áudio...', delay: 4000 },
        { pct: 50, msg: '🎙️ Whisper transcrevendo...', delay: 8000 },
        { pct: 75, msg: '🤖 GPT-5 Mini analisando viralidade...', delay: 15000 },
        { pct: 90, msg: '✂️ Cortando o trecho selecionado...', delay: 22000 }
    ];

    const timeouts = [];

    etapas.forEach(({ pct, msg, delay }) => {
        timeouts.push(setTimeout(() => {
            setProgresso(pct);
            setMensagem(msg);
        }, delay));
    });

    const dados = new FormData();
    dados.append('file', arquivo);

    try {
        const resposta = await fetch(`${API_BASE_URL}/api/upload`, {
            method: 'POST',
            headers: HEADERS_PADRAO,
            body: dados
        });

        timeouts.forEach(clearTimeout);

        const resultado = await resposta.json();
        const tempoTotal = pararTimer();

        if (!resposta.ok) {
            throw new Error(resultado.detail || 'Falha no processamento.');
        }

        const infos = resultado.detalhes_tecnicos || {};

        animarMetaCard(metaRes, infos.resolucao || 'N/A');
        animarMetaCard(metaFps, infos.fps ? `${infos.fps} FPS` : 'N/A');
        animarMetaCard(metaDuracao, infos.duracao_segundos ? `${infos.duracao_segundos}s` : 'N/A');

        setProgresso(100);

        window.ultimoResultadoIA = {
            ...resultado,
            tempoTotal
        };

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
                    style="padding:12px 28px;background:#f97316;color:white;border:none;border-radius:999px;font-size:11px;font-weight:900;letter-spacing:0.12em;cursor:pointer;box-shadow:0 8px 24px rgba(249,115,22,0.4);transition:transform .2s;"
                >
                    Ver Relatório da IA ⚡
                </button>
            </div>
        `, '#22c55e');

    } catch (erro) {
        timeouts.forEach(clearTimeout);
        pararTimer();

        console.error('Erro:', erro);

        setMensagem(`❌ ${erro.message || 'Erro de conexão.'}`, '#ef4444');
        barraProgresso.style.background = '#ef4444';

        setTimeout(resetUI, 5000);
    }
}

window.acionarTelaIA = function () {
    if (window.ultimoResultadoIA) {
        mostrarResultadosIA(window.ultimoResultadoIA);
    }
};

function mostrarResultadosIA(resultado) {
    painelUpload.classList.add('hidden');
    painelIa.classList.remove('hidden');
    painelIa.classList.remove('fade-out');

    textoTranscricao.textContent = resultado.transcricao || 'Sem transcrição disponível.';

    if (resultado.corte_sugerido) {
        corteInicio.textContent = resultado.corte_sugerido.inicio || '00:00:00';
        corteFim.textContent = resultado.corte_sugerido.fim || '00:00:00';
        corteMotivo.textContent = resultado.corte_sugerido.motivo || '—';
    }

    const areaDownload = document.getElementById('area-download');

    if (areaDownload && resultado.url_corte) {
        areaDownload.innerHTML = `
            <a href="${API_BASE_URL}${resultado.url_corte}" download="Corte_EditMind.mp4" class="btn-download">
                ⬇ Baixar Corte (MP4)
            </a>
        `;
    }
}

window.resetarNovoCorte = function () {
    painelIa.classList.add('fade-out');

    setTimeout(() => {
        painelIa.classList.add('hidden');
        painelIa.classList.remove('fade-out');
        painelUpload.classList.remove('hidden');
        resetUI();
        window.ultimoResultadoIA = null;
    }, 400);
};
