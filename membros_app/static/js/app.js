/**
 * App.js - Controlador Principal da Aplicação SIS MEVAM-GYN
 * Fluxo Mobile-First, Stepper, ViaCEP, Tabela Dinâmica e Persistência
 */

document.addEventListener('DOMContentLoaded', () => {
  // Inicialização dos Módulos
  const ocr = new OcrEngine();
  const sigCanvas = document.getElementById('signatureCanvas');
  const signaturePad = new SignaturePad(sigCanvas);

  // Variáveis de Estado
  let currentStep = 1;
  const totalSteps = 4;
  let ocrDataExtracted = null;
  let foto3x4Base64 = "";

  // Elementos do DOM
  const wizardSteps = document.querySelectorAll('.wizard-step-content');
  const stepItems = document.querySelectorAll('.step-item');
  const progressBar = document.getElementById('stepperProgressBar');
  const btnPrev = document.getElementById('btnPrevStep');
  const btnNext = document.getElementById('btnNextStep');
  const btnFinalizar = document.getElementById('btnFinalizarCadastro');
  const btnClearSig = document.getElementById('btnClearSignature');
  const btnUndoSig = document.getElementById('btnUndoSignature');
  const btnColorBlue = document.getElementById('btnPenBlue');
  const btnColorBlack = document.getElementById('btnPenBlack');
  const filhosContainer = document.getElementById('filhosContainer');
  const btnAddFilho = document.getElementById('btnAddFilho');
  const fileInput = document.getElementById('docFileInput');
  const ocrDropzone = document.getElementById('ocrDropzone');
  const ocrProgressBox = document.getElementById('ocrProgressBox');
  const ocrProgressBar = document.getElementById('ocrProgressBarFill');
  const ocrStatusText = document.getElementById('ocrStatusText');
  const ocrBadge = document.getElementById('ocrResultBadge');

  // Navegação entre Tabs Superiores (Cadastro vs ERP Secretaria)
  const tabCadastro = document.getElementById('tabNavCadastro');
  const tabErp = document.getElementById('tabNavErp');
  const viewCadastro = document.getElementById('viewCadastro');
  const viewErp = document.getElementById('viewErp');

  if (tabCadastro && tabErp) {
    tabCadastro.addEventListener('click', () => {
      tabCadastro.classList.add('active');
      tabErp.classList.remove('active');
      viewCadastro.style.display = 'block';
      viewErp.style.display = 'none';
    });

    tabErp.addEventListener('click', () => {
      tabErp.classList.add('active');
      tabCadastro.classList.remove('active');
      viewCadastro.style.display = 'none';
      viewErp.style.display = 'block';
      if (window.ErpDashboard) window.ErpDashboard.carregarDados();
    });
  }

  // Stepper Logic
  function updateStepperUI() {
    wizardSteps.forEach(w => w.style.display = 'none');
    const activeWizard = document.getElementById(`step-${currentStep}`);
    if (activeWizard) activeWizard.style.display = 'block';

    stepItems.forEach((item, idx) => {
      const stepNum = idx + 1;
      item.classList.remove('active', 'completed');
      if (stepNum === currentStep) {
        item.classList.add('active');
      } else if (stepNum < currentStep) {
        item.classList.add('completed');
      }
    });

    // Atualiza barra de progresso
    const percent = ((currentStep - 1) / (totalSteps - 1)) * 100;
    if (progressBar) progressBar.style.width = `${percent}%`;

    // Atualiza botões
    if (btnPrev) btnPrev.style.visibility = (currentStep === 1) ? 'hidden' : 'visible';
    
    if (currentStep === totalSteps) {
      if (btnNext) btnNext.style.display = 'none';
      if (btnFinalizar) btnFinalizar.style.display = 'inline-flex';
      // Ajusta tamanho da assinatura após o container ficar visível
      setTimeout(() => signaturePad.handleResize(), 50);
    } else {
      if (btnNext) btnNext.style.display = 'inline-flex';
      if (btnFinalizar) btnFinalizar.style.display = 'none';
    }

    // Scroll para o topo no mobile
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // Botões de Avançar e Voltar
  if (btnNext) {
    btnNext.addEventListener('click', () => {
      if (validarPassoAtual(currentStep)) {
        if (currentStep < totalSteps) {
          currentStep++;
          updateStepperUI();
        }
      }
    });
  }

  if (btnPrev) {
    btnPrev.addEventListener('click', () => {
      if (currentStep > 1) {
        currentStep--;
        updateStepperUI();
      }
    });
  }

  // Clique direto nos passos
  stepItems.forEach(item => {
    item.addEventListener('click', () => {
      const targetStep = parseInt(item.getAttribute('data-step'));
      if (targetStep < currentStep || validarPassoAtual(currentStep)) {
        currentStep = targetStep;
        updateStepperUI();
      }
    });
  });

  function validarPassoAtual(step) {
    if (step === 2) {
      const nome = document.getElementById('nome_completo').value.trim();
      const whatsapp = document.getElementById('whatsapp').value.trim();
      if (!nome) {
        mostrarToast("Por favor, preencha o Nome Completo.", "error");
        document.getElementById('nome_completo').focus();
        return false;
      }
      if (!whatsapp) {
        mostrarToast("Por favor, preencha o WhatsApp ou Telefone.", "error");
        document.getElementById('whatsapp').focus();
        return false;
      }
    }
    if (step === 3) {
      const termoCheckbox = document.getElementById('chkCredoAceito');
      if (termoCheckbox && !termoCheckbox.checked) {
        mostrarToast("É necessário marcar o aceite do Credo e Confissão de Fé para prosseguir.", "error");
        termoCheckbox.focus();
        return false;
      }
    }
    return true;
  }

  // --- OCR FILE UPLOAD & RECONHECIMENTO ---
  if (ocrDropzone && fileInput) {
    ocrDropzone.addEventListener('click', () => fileInput.click());

    ['dragenter', 'dragover'].forEach(eventName => {
      ocrDropzone.addEventListener(eventName, (e) => {
        e.preventDefault();
        ocrDropzone.classList.add('drag-over');
      }, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
      ocrDropzone.addEventListener(eventName, (e) => {
        e.preventDefault();
        ocrDropzone.classList.remove('drag-over');
      }, false);
    });

    ocrDropzone.addEventListener('drop', (e) => {
      const dt = e.dataTransfer;
      const files = dt.files;
      if (files.length) handleFileUpload(files[0]);
    });

    fileInput.addEventListener('change', (e) => {
      if (e.target.files.length) handleFileUpload(e.target.files[0]);
    });
  }

  // Trigger Câmera Smartphone
  const btnCamera = document.getElementById('btnCameraCapture');
  const cameraInput = document.getElementById('cameraFileInput');
  if (btnCamera && cameraInput) {
    btnCamera.addEventListener('click', () => cameraInput.click());
    cameraInput.addEventListener('change', (e) => {
      if (e.target.files.length) handleFileUpload(e.target.files[0]);
    });
  }

  async function handleFileUpload(file) {
    ocrProgressBox.style.display = 'block';
    ocrProgressBar.style.width = '10%';
    ocrStatusText.textContent = "Iniciando reconhecimento óptico...";

    try {
      const dados = await ocr.processFile(file, (percent, msg) => {
        ocrProgressBar.style.width = `${percent}%`;
        ocrStatusText.textContent = msg;
      });

      ocrDataExtracted = dados;
      preencherFormularioComOcr(dados);

      // Exibir badge de campos extraídos
      if (ocrBadge) {
        ocrBadge.style.display = 'flex';
        document.getElementById('ocrCountDisplay').textContent = `${dados.extractedFieldsCount} campos identificados`;
      }

      mostrarToast(`OCR Concluído! ${dados.extractedFieldsCount} campos extraídos com sucesso.`, "success");

      // Auto-avançar para a ficha para conferência após 1 segundo
      setTimeout(() => {
        currentStep = 2;
        updateStepperUI();
      }, 1200);

    } catch (err) {
      console.error("Erro no OCR:", err);
      ocrStatusText.textContent = "Erro ao processar arquivo: " + err.message;
      mostrarToast("Não foi possível extrair o texto automaticamente. Você pode preencher manualmente.", "error");
    }
  }

  function preencherFormularioComOcr(dados) {
    const mapaCampos = {
      'nome_completo': dados.nome_completo,
      'endereco': dados.endereco,
      'bairro': dados.bairro,
      'cidade': dados.cidade,
      'cep': dados.cep,
      'data_nascimento': dados.data_nascimento,
      'naturalidade': dados.naturalidade,
      'conjuge': dados.conjuge,
      'email': dados.email,
      'telefone': dados.telefone,
      'whatsapp': dados.whatsapp,
      'profissao': dados.profissao,
      'empresa': dados.empresa,
      'data_batismo': dados.data_batismo,
      'onde_congregava': dados.onde_congregava,
      'area_ministerial': dados.area_ministerial
    };

    for (const [id, valor] of Object.entries(mapaCampos)) {
      if (valor) {
        const input = document.getElementById(id);
        if (input) {
          input.value = valor;
          destacarCampoOcr(input);
        }
      }
    }

    // Sexo Radio
    if (dados.sexo) {
      const radioMasc = document.getElementById('sexo_masc');
      const radioFem = document.getElementById('sexo_fem');
      if (dados.sexo.includes('Masc') && radioMasc) radioMasc.checked = true;
      if (dados.sexo.includes('Fem') && radioFem) radioFem.checked = true;
    }

    // Estado Civil
    if (dados.estado_civil) {
      const selectEc = document.getElementById('estado_civil');
      if (selectEc) selectEc.value = dados.estado_civil;
    }

    // Batizado Radio
    if (dados.batizado) {
      const rSim = document.getElementById('batizado_sim');
      const rNao = document.getElementById('batizado_nao');
      if (dados.batizado === 'Sim' && rSim) rSim.checked = true;
      if (dados.batizado === 'Não' && rNao) rNao.checked = true;
    }

    // Congregava antes Radio
    if (dados.congregava_antes) {
      const rSim = document.getElementById('congregava_sim');
      const rNao = document.getElementById('congregava_nao');
      if (dados.congregava_antes === 'Sim' && rSim) rSim.checked = true;
      if (dados.congregava_antes === 'Não' && rNao) rNao.checked = true;
    }

    // Preencher também o Nome do Assinante no Credo automaticamente
    const inputNomeAssinante = document.getElementById('nome_assinante');
    if (inputNomeAssinante && dados.nome_completo) {
      inputNomeAssinante.value = dados.nome_completo;
    }

    // Se CEP foi extraído, dispara consulta ViaCEP
    if (dados.cep && dados.cep.length >= 8) {
      consultarViaCep(dados.cep);
    }
  }

  function destacarCampoOcr(element) {
    element.style.borderColor = '#10b981';
    element.style.backgroundColor = 'rgba(16, 185, 129, 0.05)';
    setTimeout(() => {
      element.style.backgroundColor = '';
    }, 2000);
  }

  // --- CONSULTA AUTOMÁTICA DE CEP (ViaCEP API) ---
  const inputCep = document.getElementById('cep');
  if (inputCep) {
    inputCep.addEventListener('blur', (e) => {
      const cep = e.target.value.replace(/\D/g, '');
      if (cep.length === 8) consultarViaCep(cep);
    });
  }

  async function consultarViaCep(cepLimpo) {
    try {
      const res = await fetch(`https://viacep.com.br/ws/${cepLimpo}/json/`);
      const data = await res.json();
      if (!data.erro) {
        if (!document.getElementById('endereco').value) document.getElementById('endereco').value = data.logradouro || '';
        if (!document.getElementById('bairro').value) document.getElementById('bairro').value = data.bairro || '';
        if (!document.getElementById('cidade').value) document.getElementById('cidade').value = data.localidade || 'Goiânia';
        mostrarToast("Endereço localizado pelo CEP!", "success");
      }
    } catch (e) {
      console.warn("ViaCEP offline ou indisponível:", e);
    }
  }

  // Sincronizar Nome Completo com Campo de Assinatura do Credo
  const inputNome = document.getElementById('nome_completo');
  const inputNomeAssinante = document.getElementById('nome_assinante');
  if (inputNome && inputNomeAssinante) {
    inputNome.addEventListener('input', (e) => {
      if (!inputNomeAssinante.dataset.userEdited) {
        inputNomeAssinante.value = e.target.value;
      }
    });
    inputNomeAssinante.addEventListener('input', () => {
      inputNomeAssinante.dataset.userEdited = "true";
    });
  }

  // --- TABELA DINÂMICA DE FILHOS ---
  if (btnAddFilho && filhosContainer) {
    btnAddFilho.addEventListener('click', () => adicionarLinhaFilho());
  }

  function adicionarLinhaFilho(nome = '', nascimento = '', idade = '') {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><input type="text" class="form-control filho-nome" placeholder="Nome do Filho(a)" value="${nome}"></td>
      <td><input type="text" class="form-control filho-nasc" placeholder="DD/MM/AAAA" value="${nascimento}"></td>
      <td><input type="text" class="form-control filho-idade" placeholder="Ex: 5" value="${idade}"></td>
      <td style="text-align: center;">
        <button type="button" class="btn btn-secondary btn-sm btn-remover-filho" title="Remover">✕</button>
      </td>
    `;

    // Auto-cálculo da idade ao digitar nascimento
    const inputNasc = tr.querySelector('.filho-nasc');
    const inputIdade = tr.querySelector('.filho-idade');
    inputNasc.addEventListener('blur', () => {
      const parts = inputNasc.value.split('/');
      if (parts.length === 3) {
        const ano = parseInt(parts[2]);
        const anoAtual = new Date().getFullYear();
        if (ano > 1900 && ano <= anoAtual) {
          inputIdade.value = anoAtual - ano;
        }
      }
    });

    tr.querySelector('.btn-remover-filho').addEventListener('click', () => tr.remove());
    filhosContainer.appendChild(tr);
  }

  // --- GESTÃO DA FOTO DE IDENTIFICAÇÃO FACIAL 3x4 (SEM ÓCULOS) ---
  const btnUploadFoto = document.getElementById('btnUploadFoto3x4');
  const btnCameraFoto = document.getElementById('btnCameraFoto3x4');
  const inputArquivo = document.getElementById('inputFoto3x4Arquivo');
  const inputCamera = document.getElementById('inputFoto3x4Camera');
  const btnRemoverFoto = document.getElementById('btnRemoverFoto3x4');
  const previewFoto = document.getElementById('previewFoto3x4');
  const placeholderFoto = document.getElementById('placeholderFoto3x4');
  const statusFoto = document.getElementById('statusFoto3x4');

  if (btnUploadFoto && inputArquivo) {
    btnUploadFoto.addEventListener('click', () => inputArquivo.click());
    inputArquivo.addEventListener('change', (e) => processarArquivoFoto(e.target.files[0]));
  }

  if (btnCameraFoto && inputCamera) {
    btnCameraFoto.addEventListener('click', () => inputCamera.click());
    inputCamera.addEventListener('change', (e) => processarArquivoFoto(e.target.files[0]));
  }

  if (btnRemoverFoto) {
    btnRemoverFoto.addEventListener('click', () => {
      foto3x4Base64 = "";
      if (previewFoto) {
        previewFoto.src = "";
        previewFoto.style.display = "none";
      }
      if (placeholderFoto) placeholderFoto.style.display = "block";
      btnRemoverFoto.style.display = "none";
      if (statusFoto) statusFoto.textContent = "";
      if (inputArquivo) inputArquivo.value = "";
      if (inputCamera) inputCamera.value = "";
    });
  }

  function processarArquivoFoto(file) {
    if (!file) return;

    if (!file.type.startsWith('image/')) {
      mostrarToast("Por favor, selecione um arquivo de imagem válido (JPG, PNG ou WEBP).", "error");
      return;
    }

    const reader = new FileReader();
    reader.onload = (e) => {
      const img = new Image();
      img.onload = () => {
        // Redimensionar e otimizar para proporção 3x4 (max 600x800) usando canvas
        const canvas = document.createElement('canvas');
        const maxW = 600;
        const maxH = 800;
        let w = img.width;
        let h = img.height;

        if (w > maxW || h > maxH) {
          const ratio = Math.min(maxW / w, maxH / h);
          w = Math.round(w * ratio);
          h = Math.round(h * ratio);
        }

        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0, w, h);

        foto3x4Base64 = canvas.toDataURL('image/jpeg', 0.85);

        if (previewFoto) {
          previewFoto.src = foto3x4Base64;
          previewFoto.style.display = "block";
        }
        if (placeholderFoto) placeholderFoto.style.display = "none";
        if (btnRemoverFoto) btnRemoverFoto.style.display = "inline-block";
        if (statusFoto) statusFoto.textContent = "✓ Foto 3x4 anexada e otimizada com sucesso!";
        mostrarToast("Foto 3x4 carregada com sucesso!", "success");
      };
      img.src = e.target.result;
    };
    reader.readAsDataURL(file);
  }

  // --- CONTROLES DA RÚBRICA / ASSINATURA ---
  if (btnClearSig) {
    btnClearSig.addEventListener('click', () => signaturePad.clear());
  }
  if (btnUndoSig) {
    btnUndoSig.addEventListener('click', () => signaturePad.undo());
  }
  if (btnColorBlue) {
    btnColorBlue.addEventListener('click', () => {
      signaturePad.setColor('#003399');
      btnColorBlue.classList.add('active');
      btnColorBlack.classList.remove('active');
    });
  }
  if (btnColorBlack) {
    btnColorBlack.addEventListener('click', () => {
      signaturePad.setColor('#111827');
      btnColorBlack.classList.add('active');
      btnColorBlue.classList.remove('active');
    });
  }

  // --- ACCORDION DOS ARTIGOS DO CREDO ---
  const triggers = document.querySelectorAll('.artigo-trigger');
  triggers.forEach(trigger => {
    trigger.addEventListener('click', () => {
      const card = trigger.closest('.artigo-card');
      const body = card.querySelector('.artigo-body');
      const icon = trigger.querySelector('.artigo-toggle-icon');
      if (body.style.display === 'none' || !body.style.display) {
        body.style.display = 'block';
        if (icon) icon.textContent = '▲';
      } else {
        body.style.display = 'none';
        if (icon) icon.textContent = '▼';
      }
    });
  });

  // Botão "Expandir Todos os Artigos"
  const btnToggleAllArtigos = document.getElementById('btnToggleAllArtigos');
  if (btnToggleAllArtigos) {
    let allExpanded = false;
    btnToggleAllArtigos.addEventListener('click', () => {
      allExpanded = !allExpanded;
      document.querySelectorAll('.artigo-body').forEach(b => {
        b.style.display = allExpanded ? 'block' : 'none';
      });
      document.querySelectorAll('.artigo-toggle-icon').forEach(i => {
        i.textContent = allExpanded ? '▲' : '▼';
      });
      btnToggleAllArtigos.textContent = allExpanded ? "Recolher Artigos" : "Expandir Todos os 10 Artigos";
    });
  }

  // --- FINALIZAR E SALVAR CADASTRO ---
  if (btnFinalizar) {
    btnFinalizar.addEventListener('click', async () => {
      // Validações Finais
      const nomeAssinante = document.getElementById('nome_assinante').value.trim();
      const chkCredo = document.getElementById('chkCredoAceito');

      if (!chkCredo || !chkCredo.checked) {
        mostrarToast("Você deve marcar o aceite da Confissão de Fé para finalizar.", "error");
        currentStep = 3;
        updateStepperUI();
        return;
      }

      if (!nomeAssinante) {
        mostrarToast("Por favor, confirme seu Nome Completo no campo de assinatura.", "error");
        document.getElementById('nome_assinante').focus();
        return;
      }

      const chkLgpd = document.getElementById('checkConsentimentoLgpd');
      if (chkLgpd && !chkLgpd.checked) {
        mostrarToast("É obrigatório consentir com a Política de Privacidade e LGPD para finalizar.", "error");
        return;
      }

      if (signaturePad.isEmpty()) {
        mostrarToast("Por favor, faça a sua rúbrica/assinatura no quadro digital.", "error");
        return;
      }

      // Coletar dados dos filhos
      const filhos = [];
      document.querySelectorAll('#filhosContainer tr').forEach(tr => {
        const n = tr.querySelector('.filho-nome')?.value.trim();
        const d = tr.querySelector('.filho-nasc')?.value.trim();
        const i = tr.querySelector('.filho-idade')?.value.trim();
        if (n) filhos.push({ nome: n, nascimento: d, idade: i });
      });

      // Montar Payload Completo
      const payload = {
        data_registro: new Date().toLocaleDateString('pt-BR'),
        nome_completo: document.getElementById('nome_completo').value.trim(),
        endereco: document.getElementById('endereco').value.trim(),
        bairro: document.getElementById('bairro').value.trim(),
        cidade: document.getElementById('cidade').value.trim() || 'Goiânia',
        cep: document.getElementById('cep').value.trim(),
        data_nascimento: document.getElementById('data_nascimento').value.trim(),
        naturalidade: document.getElementById('naturalidade').value.trim(),
        sexo: document.querySelector('input[name="sexo"]:checked')?.value || 'Masc.',
        estado_civil: document.getElementById('estado_civil').value,
        conjuge: document.getElementById('conjuge').value.trim(),
        filhos: filhos,
        email: document.getElementById('email').value.trim(),
        telefone: document.getElementById('telefone').value.trim(),
        whatsapp: document.getElementById('whatsapp').value.trim(),
        escolaridade: document.getElementById('escolaridade').value,
        formacao_academica: document.getElementById('formacao_academica').value.trim(),
        profissao: document.getElementById('profissao').value.trim(),
        empresa: document.getElementById('empresa').value.trim(),
        batizado: document.querySelector('input[name="batizado"]:checked')?.value || 'Não',
        data_batismo: document.getElementById('data_batismo').value.trim(),
        congregava_antes: document.querySelector('input[name="congregava_antes"]:checked')?.value || 'Não',
        onde_congregava: document.getElementById('onde_congregava').value.trim(),
        area_ministerial: document.getElementById('area_ministerial').value.trim(),
        interesse_batismo_familia: document.getElementById('interesse_batismo_familia').value.trim(),

        // Credo e Assinatura
        credo_aceito: true,
        nome_assinante: nomeAssinante,
        assinatura_rubrica: signaturePad.toDataURL(),
        data_assinatura: new Date().toLocaleString('pt-BR'),

        // Conformidade LGPD (Lei 13.709/2018)
        lgpd_consentimento: chkLgpd ? chkLgpd.checked : true,
        lgpd_versao_termo: 'v1.0-2026',

        // Foto 3x4 de Identificação Facial
        foto_3x4: foto3x4Base64,

        // OCR Metadados
        ocr_documento_nome: ocrDataExtracted?.fileName || '',
        ocr_raw_text: ocrDataExtracted?.rawText || ''
      };

      btnFinalizar.disabled = true;
      btnFinalizar.innerHTML = "⏳ Gravando registro...";

      try {
        const response = await fetch('/api/membros', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });

        const resJson = await response.json();

        if (response.ok && resJson.id) {
          mostrarSucessoModal(resJson.id, payload);
          mostrarToast("Cadastro e Confissão de Fé registrados com sucesso!", "success");
        } else {
          throw new Error(resJson.error || "Erro ao salvar cadastro.");
        }
      } catch (err) {
        console.error("Erro na gravação:", err);
        mostrarToast("Erro ao conectar com o servidor. Salvando localmente...", "error");
        // Salva cópia de segurança em LocalStorage
        const offlineMembros = JSON.parse(localStorage.getItem('membros_offline') || '[]');
        payload.id = 'LOCAL-' + Date.now();
        offlineMembros.push(payload);
        localStorage.setItem('membros_offline', JSON.stringify(offlineMembros));
        mostrarSucessoModal(payload.id, payload);
      } finally {
        btnFinalizar.disabled = false;
        btnFinalizar.innerHTML = "✓ Finalizar & Registrar Aceite";
      }
    });
  }

  function mostrarSucessoModal(id, dados) {
    const modal = document.getElementById('modalSucesso');
    if (!modal) return;
    document.getElementById('sucessoProtocolo').textContent = `#${id}`;
    document.getElementById('sucessoNome').textContent = dados.nome_completo;
    document.getElementById('btnDownloadPdfSucesso').onclick = () => {
      window.open(`/api/membros/${id}/pdf`, '_blank');
    };
    document.getElementById('btnImprimirSucesso').onclick = () => {
      window.open(`/membro/${id}/comprovante`, '_blank');
    };
    modal.style.display = 'flex';
  }

  // Toast Function
  window.mostrarToast = function(msg, tipo = "info") {
    let container = document.getElementById('toastContainer');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toastContainer';
      container.className = 'toast-container';
      document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = `toast toast-${tipo}`;
    toast.innerHTML = `<span>${tipo === 'success' ? '✓' : tipo === 'error' ? '✕' : 'ℹ'}</span> <span>${msg}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      setTimeout(() => toast.remove(), 300);
    }, 4000);
  };

  // Inicializar Stepper no Passo 1
  updateStepperUI();
});
