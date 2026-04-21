/* ============================================================
   EditMind — js/app.js
   Controlo de Upload e Processamento de Vídeo
   ============================================================ */

const API_BASE_URL = CONFIG.API_URL;
const HEADERS_PADRAO = { "ngrok-skip-browser-warning": "true" };

// Elementos da Interface
const painelUpload = document.getElementById('painel-upload');
const areaSoltar = document.getElementById('area-soltar');
const entradaArquivo = document.getElementById('entrada-arquivo');
const nomeArquivoTexto = document.getElementById('nome-arquivo');
const barraProgresso = document.getElementById('barra-progresso');
const porcentagemTexto = document.getElementById('porcentagem-envio');
const mensagemTexto = document.getElementById('mensagem-envio');
const painelIa = document.getElementById('painel-ia');
const textoTranscricao = document.getElementById('texto-transcricao');
const corteInicio = document.getElementById('corte-inicio');
const corteFim = document.getElementById('corte-fim');
const corteMotivo = document.getElementById('corte-motivo');

// Garantir que o utilizador está logado
Auth.exigirLogin();

window.ultimoResultadoIA = null;
let _timerInterval = null;

// Funções de UI
function setMensagem(texto, cor = '#94a3b8') {
    mensagemTexto.textContent = texto;
    mensagemTexto.style.color = cor;
}

function resetUI() {
    barraProgresso.style.width = '0%';
    barraProgresso.style.background = 'linear-gradient(90deg, #f97316, #fb923c)';
    porcentagemTexto.textContent = '0%';
    setMensagem('Aguardando ficheiro...');
    nomeArquivoTexto.textContent = 'Nenhum ficheiro selecionado';
}

// Lógica de Envio
async function enviarArquivo(arquivo) {
    if (!arquivo) return;

    // 1. Pegar o Token de Autenticação
    const token = localStorage.getItem(CONFIG.TOKEN_KEY);

    const formData = new FormData();
    formData.append('file', arquivo);

    resetUI();
    setMensagem('A enviar vídeo...');

    try {
        const xhr = new XMLHttpRequest();

        xhr.upload.onprogress = (e) => {
            if (e.lengthComputable) {
                const percent = Math.round((e.loaded / e.total) * 100);
                barraProgresso.style.width = percent + '%';
                porcentagemTexto.textContent = percent + '%';
                if (percent === 100) setMensagem('🎬 Processando vídeo com IA... (Pode demorar)');
            }
        };

        xhr.onload = function () {
            if (xhr.status === 200) {
                const resultado = JSON.parse(xhr.responseText);
                window.ultimoResultadoIA = resultado;
                setMensagem('✅ Concluído!', '#22c55e');
                mostrarResultadosIA(resultado);
            } else {
                const erro = JSON.parse(xhr.responseText);
                setMensagem(`❌ Erro: ${erro.detail || 'Falha no processamento'}`, '#ef4444');
            }
        };

        xhr.onerror = () => setMensagem('❌ Erro de conexão.', '#ef4444');

        xhr.open('POST', `${API_BASE_URL}/api/processar`);

        // 2. ADICIONAR OS HEADERS DE SEGURANÇA
        xhr.setRequestHeader('Authorization', `Bearer ${token}`);
        xhr.setRequestHeader('ngrok-skip-browser-warning', 'true');

        xhr.send(formData);

    } catch (erro) {
        setMensagem('❌ Erro inesperado.', '#ef4444');
    }
}

function mostrarResultadosIA(resultado) {
    painelUpload.classList.add('hidden');
    painelIa.classList.remove('hidden');

    textoTranscricao.textContent = resultado.transcricao || 'Transcrição concluída.';

    if (resultado.corte_sugerido) {
        corteInicio.textContent = resultado.corte_sugerido.inicio + 's';
        corteFim.textContent = resultado.corte_sugerido.fim + 's';
        corteMotivo.textContent = resultado.corte_sugerido.motivo || 'Destaque viral identificado.';
    }

    const areaDownload = document.getElementById('area-download');
    if (areaDownload && resultado.url_corte) {
        areaDownload.innerHTML = `
            <a href="${API_BASE_URL}${resultado.url_corte}" download class="btn-download">
                ⬇ BAIXAR CORTE VIRAL (MP4)
            </a>
        `;
    }
}

// Event Listeners de Drag & Drop
areaSoltar.addEventListener('click', () => entradaArquivo.click());
entradaArquivo.addEventListener('change', () => {
    if (entradaArquivo.files[0]) {
        nomeArquivoTexto.textContent = entradaArquivo.files[0].name;
        enviarArquivo(entradaArquivo.files[0]);
    }
});

areaSoltar.addEventListener('dragover', (e) => {
    e.preventDefault();
    areaSoltar.style.borderColor = '#f97316';
});

areaSoltar.addEventListener('dragleave', () => {
    areaSoltar.style.borderColor = 'rgba(255,255,255,0.1)';
});

areaSoltar.addEventListener('drop', (e) => {
    e.preventDefault();
    areaSoltar.style.borderColor = 'rgba(255,255,255,0.1)';
    const ficheiro = e.dataTransfer.files[0];
    if (ficheiro) {
        nomeArquivoTexto.textContent = ficheiro.name;
        enviarArquivo(ficheiro);
    }
});

window.resetarNovoCorte = function () {
    painelIa.classList.add('hidden');
    painelUpload.classList.remove('hidden');
    resetUI();
};

// Verificar se o utilizador está logado ao carregar a página
window.onload = function () {
    if (!Auth.estaLogado()) {
        const urlAtual = window.location.pathname;
        if (!urlAtual.endsWith('home.html')) {
            window.location.href = 'home.html';
        }
    }
};