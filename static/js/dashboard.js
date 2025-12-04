// dashboard.js - todo código seguro, sem inline handlers

document.addEventListener("DOMContentLoaded", function () {
    const btnAtualiza = document.getElementById('btnAtualiza');
    const btnAplicarFiltros = document.getElementById('btnAplicarFiltros');
    const tabsContainer = document.getElementById('tabs-container');
    const clientesContainer = document.getElementById('clientes-container');
    const exibidosSpan = document.getElementById('exibidos');

    const filtrosSalvos = { saldo: '', uf: '', orgao: '' };
    let currentStart = 0;
    let divulgadores = [];

    // CSRF token
    const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');

    async function postCSRF(url, data) {
        const res = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify(data)
        });
        return res;
    }

    async function carregarDivulgadores() {
        try {
            const res = await fetch("/get_divulgadores");
            divulgadores = res.ok ? await res.json() : [];
        } catch (e) {
            console.error("Erro ao buscar divulgadores:", e);
            divulgadores = [];
        }
    }

    carregarDivulgadores(); // mantém apenas a lista de divulgadores

    const camposExibir = [
        "nome", "cpf", "banco", "uf", "orgao_nome",
        "orgao_taxa_formatada", "saldo_devedor", "parcela",
        "prazo", "telefone_movel_1", "telefone_movel_2", "telefone_movel_3"
    ];

    btnAplicarFiltros.addEventListener('click', function () {
        filtrosSalvos.saldo = document.getElementById('filter_saldo').value.trim();
        filtrosSalvos.uf = document.getElementById('filter_uf').value.trim();
        filtrosSalvos.orgao = document.getElementById('filter_orgao').value.trim(); // input de texto
        currentStart = 0;
        exibidosSpan.innerText = 0;
        tabsContainer.innerHTML = "";
        clientesContainer.innerHTML = "";
    });

    async function atualizaClientes() {
        btnAtualiza.disabled = true;
        const originalText = btnAtualiza.innerText;
        btnAtualiza.innerText = "Carregando...";

        try {
            const res = await postCSRF('/atualiza_dataframe', {
                start: currentStart,
                limit: 10,
                saldo: filtrosSalvos.saldo,
                uf: filtrosSalvos.uf,
                orgao: filtrosSalvos.orgao
            });
            if (!res.ok) return console.error('Resposta inválida do servidor');

            const data = await res.json();
            const clientes = Array.isArray(data.clientes) ? data.clientes : [];
            tabsContainer.innerHTML = "";
            clientesContainer.innerHTML = "";

            clientes.forEach((cliente, index) => {
                const globalIndex = index;

                const tab = document.createElement('button');
                tab.className = 'tab-link';
                tab.type = 'button';
                tab.textContent = `Cliente ${currentStart + index + 1}`;
                tab.addEventListener('click', () => openCliente(globalIndex));
                tabsContainer.appendChild(tab);

                const div = document.createElement('div');
                div.className = 'tab-content';
                div.id = `cliente_${globalIndex}`;
                if (globalIndex !== 0) div.style.display = 'none';

                const btnSalvar = document.createElement('button');
                btnSalvar.type = 'button';
                btnSalvar.textContent = 'Salvar Cliente';
                btnSalvar.style.float = 'right';
                btnSalvar.style.marginBottom = '10px';
                div.appendChild(btnSalvar);

                camposExibir.forEach(key => {
                    const value = cliente[key];
                    if (value !== null && value !== undefined) {
                        const p = document.createElement('p');
                        const strong = document.createElement('b');
                        strong.textContent = `${key}: `;
                        p.appendChild(strong);

                        if (key.toLowerCase().includes('telefone')) {
                            const spanTel = document.createElement('span');
                            spanTel.className = 'telefone';
                            spanTel.textContent = String(value);
                            const copiarBtn = document.createElement('button');
                            copiarBtn.type = 'button';
                            copiarBtn.className = 'btn-copiar';
                            copiarBtn.textContent = '📋';
                            copiarBtn.addEventListener('click', () => copiarTelefone(copiarBtn));
                            p.appendChild(spanTel);
                            p.appendChild(document.createTextNode(' '));
                            p.appendChild(copiarBtn);

                        } else if (key === 'orgao_taxa_formatada') {
                            let txt = value ? String(value) : '—';
                            p.appendChild(document.createTextNode(txt));
                        } else {
                            p.appendChild(document.createTextNode(String(value || '—')));
                        }

                        div.appendChild(p);
                    }
                });

                const labelNovoTel = document.createElement('label');
                labelNovoTel.textContent = 'Novo número de telefone:';
                labelNovoTel.style.display = 'block';
                labelNovoTel.style.marginTop = '10px';
                const inputNovoTel = document.createElement('input');
                inputNovoTel.type = 'text';
                inputNovoTel.placeholder = '(DDD) 9XXXX-XXXX';
                inputNovoTel.style.width = '100%';
                inputNovoTel.style.marginBottom = '8px';
                inputNovoTel.addEventListener('input', () => {
                    inputNovoTel.value = inputNovoTel.value.replace(/\D/g, '');
                });
                div.appendChild(labelNovoTel);
                div.appendChild(inputNovoTel);

                btnSalvar.addEventListener('click', () => {
                    const novoNumero = inputNovoTel.value.trim();
                    if (novoNumero && !/^\d{10,11}$/.test(novoNumero)) {
                        alert('❌ Formato de número inválido! Use DDD + número, apenas dígitos.');
                        return;
                    }
                    if (novoNumero) cliente.novo_telefone = novoNumero;
                    salvarCliente(cliente);
                });

                clientesContainer.appendChild(div);
            });

            exibidosSpan.textContent = String(clientes.length);
            if (clientes.length > 0) openCliente(0);

            currentStart += clientes.length;
            if (currentStart >= (data.total_count || 0) || clientes.length === 0) currentStart = 0;

        } catch (e) {
            console.error('Erro ao atualizar clientes:', e);
        } finally {
            btnAtualiza.disabled = false;
            btnAtualiza.innerText = originalText || "🔁 Mostrar Próximos 10 Clientes";
        }
    }

    btnAtualiza.addEventListener('click', atualizaClientes);

    function openCliente(index) {
        const tabs = document.querySelectorAll('.tab-link');
        const contents = document.querySelectorAll('.tab-content');
        tabs.forEach((t, i) => t.classList.toggle('active', i === index));
        contents.forEach((c, i) => c.style.display = (i === index ? 'block' : 'none'));
    }

    async function salvarCliente(cliente) {
        try {
            const res = await postCSRF('/salvar_cliente', cliente);
            const data = await res.json();
            if (data.status === 'ok') {
                alert('✅ Cliente salvo com sucesso!');
            } else {
                alert('⚠️ Erro ao salvar cliente: ' + (data.mensagem || 'desconhecido'));
            }
        } catch (err) {
            console.error('Falha na conexão:', err);
            alert('❌ Falha de conexão ou erro inesperado.');
        }
    }
});

// Função global de copiar telefone
function copiarTelefone(botao) {
    try {
        const parent = botao.parentElement;
        const telefoneSpan = parent.querySelector('.telefone');
        const telefone = telefoneSpan ? telefoneSpan.textContent.trim() : '';
        if (!telefone) throw new Error('telefone_vazio');

        navigator.clipboard.writeText(telefone)
            .then(() => {
                const prev = botao.textContent;
                botao.textContent = '✅';
                setTimeout(() => { botao.textContent = prev || '📋'; }, 1000);
            })
            .catch(() => {
                alert('❌ Não foi possível copiar o número.');
            });
    } catch (e) {
        alert('❌ Não foi possível copiar o número.');
    }
}
