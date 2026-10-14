/**
 * Admin.js - Módulo de Gestão ERP & Secretaria da Igreja
 * Gestão de Membros, Visualização de Rúbrica, Filtros, Estatísticas e Exportação
 */

class ErpDashboard {
  constructor() {
    this.membros = [];
    this.filtroStatus = 'Todos';
    this.filtroBusca = '';
    this.initElements();
  }

  initElements() {
    this.tabelaCorpo = document.getElementById('erpTableBody');
    this.inputBusca = document.getElementById('erpSearchInput');
    this.selectStatus = document.getElementById('erpFilterStatus');
    this.btnExportar = document.getElementById('btnErpExportarCsv');
    this.btnAtualizar = document.getElementById('btnErpAtualizar');

    if (this.inputBusca) {
      this.inputBusca.addEventListener('input', (e) => {
        this.filtroBusca = e.target.value.toLowerCase();
        this.renderizarTabela();
      });
    }

    if (this.selectStatus) {
      this.selectStatus.addEventListener('change', (e) => {
        this.filtroStatus = e.target.value;
        this.renderizarTabela();
      });
    }

    if (this.btnExportar) {
      this.btnExportar.addEventListener('click', () => this.exportarCsv());
    }

    if (this.btnAtualizar) {
      this.btnAtualizar.addEventListener('click', () => this.carregarDados());
    }
  }

  async carregarDados() {
    try {
      const res = await fetch('/api/membros');
      if (!res.ok) throw new Error("Erro ao consultar API");
      this.membros = await res.json();
      
      this.atualizarEstatisticas();
      this.renderizarTabela();
    } catch (err) {
      console.warn("Erro ao buscar dados do servidor, lendo LocalStorage:", err);
      this.membros = JSON.parse(localStorage.getItem('membros_offline') || '[]');
      this.atualizarEstatisticas();
      this.renderizarTabela();
    }
  }

  atualizarEstatisticas() {
    const total = this.membros.length;
    const batizados = this.membros.filter(m => m.batizado === 'Sim').length;
    const assinados = this.membros.filter(m => m.assinatura_rubrica).length;
    const interesseBatismo = this.membros.filter(m => m.interesse_batismo_familia && m.interesse_batismo_familia.toLowerCase().includes('sim')).length;

    const elTotal = document.getElementById('statTotalMembros');
    const elBatizados = document.getElementById('statTotalBatizados');
    const elAssinados = document.getElementById('statTotalAssinados');
    const elInteresse = document.getElementById('statInteresseBatismo');

    if (elTotal) elTotal.textContent = total;
    if (elBatizados) elBatizados.textContent = batizados;
    if (elAssinados) elAssinados.textContent = assinados;
    if (elInteresse) elInteresse.textContent = interesseBatismo;
  }

  renderizarTabela() {
    if (!this.tabelaCorpo) return;

    let filtrados = this.membros.filter(m => {
      const matchBusca = !this.filtroBusca || 
        (m.nome_completo && m.nome_completo.toLowerCase().includes(this.filtroBusca)) ||
        (m.email && m.email.toLowerCase().includes(this.filtroBusca)) ||
        (m.whatsapp && m.whatsapp.includes(this.filtroBusca)) ||
        (m.bairro && m.bairro.toLowerCase().includes(this.filtroBusca));

      let matchStatus = true;
      if (this.filtroStatus === 'Batizados') matchStatus = (m.batizado === 'Sim');
      if (this.filtroStatus === 'NaoBatizados') matchStatus = (m.batizado !== 'Sim');
      if (this.filtroStatus === 'ComAssinatura') matchStatus = !!m.assinatura_rubrica;

      return matchBusca && matchStatus;
    });

    if (filtrados.length === 0) {
      this.tabelaCorpo.innerHTML = `
        <tr>
          <td colspan="7" style="text-align: center; padding: 32px; color: #94a3b8;">
            Nenhum membro encontrado com os filtros aplicados.
          </td>
        </tr>
      `;
      return;
    }

    this.tabelaCorpo.innerHTML = filtrados.map(m => {
      const temAssinatura = m.assinatura_rubrica ? 
        `<span class="badge badge-success">✓ Rúbrica Registrada</span>` : 
        `<span class="badge badge-warning">Pendente</span>`;

      const batismoBadge = m.batizado === 'Sim' ? 
        `<span class="badge badge-primary">Sim</span>` : 
        `<span class="badge badge-info">Não</span>`;

      return `
        <tr>
          <td><strong>#${m.id}</strong></td>
          <td>
            <div style="display: flex; align-items: center; gap: 10px;">
              <div style="width: 34px; height: 44px; border-radius: 6px; border: 1.5px solid var(--border-color); overflow: hidden; background: #e2e8f0; flex-shrink: 0; display: flex; align-items: center; justify-content: center;">
                ${m.foto_3x4 ? `<img src="${m.foto_3x4}" style="width: 100%; height: 100%; object-fit: cover;">` : `<span style="font-size: 1rem; opacity: 0.6;">👤</span>`}
              </div>
              <div>
                <strong>${m.nome_completo}</strong><br/>
                <small style="color: #64748b;">${m.email || 'Sem e-mail'}</small>
              </div>
            </div>
          </td>
          <td>${m.whatsapp || m.telefone || '-'}</td>
          <td>${m.cidade || 'Goiânia'}<br/><small style="color: #64748b;">${m.bairro || '-'}</small></td>
          <td>${batismoBadge}</td>
          <td>${temAssinatura}</td>
          <td>
            <div style="display: flex; gap: 6px;">
              <button class="btn btn-secondary btn-sm" onclick="ErpDashboard.abrirDetalhes(${m.id})">🔍 Ver Ficha</button>
              <button class="btn btn-primary btn-sm" onclick="window.open('/api/membros/${m.id}/pdf', '_blank')">📄 PDF</button>
              <button class="btn btn-secondary btn-sm" style="color: #ef4444;" onclick="ErpDashboard.excluirMembro(${m.id})" title="Excluir">✕</button>
            </div>
          </td>
        </tr>
      `;
    }).join('');
  }

  static abrirDetalhes(id) {
    const dashboard = window.ErpDashboardInstance;
    const m = dashboard.membros.find(item => item.id == id);
    if (!m) return;

    const modal = document.getElementById('modalDetalhesMembro');
    const corpo = document.getElementById('modalDetalhesCorpo');
    if (!modal || !corpo) return;

    let filhosHtml = '<p>Nenhum filho registrado.</p>';
    if (m.filhos && m.filhos.length > 0) {
      filhosHtml = `
        <table style="width: 100%; border-collapse: collapse; margin-top: 8px;">
          <thead>
            <tr style="background: #f1f5f9; text-align: left; font-size: 0.8rem;">
              <th style="padding: 6px;">Nome</th>
              <th style="padding: 6px;">Nascimento</th>
              <th style="padding: 6px;">Idade</th>
            </tr>
          </thead>
          <tbody>
            ${m.filhos.map(f => `
              <tr style="border-bottom: 1px solid #e2e8f0; font-size: 0.85rem;">
                <td style="padding: 6px;">${f.nome}</td>
                <td style="padding: 6px;">${f.nascimento || '-'}</td>
                <td style="padding: 6px;">${f.idade || '-'} anos</td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      `;
    }

    let rubricaHtml = '<p style="color: #ef4444;">Nenhuma assinatura digital registrada.</p>';
    if (m.assinatura_rubrica) {
      rubricaHtml = `
        <div style="background: #ffffff; border: 1.5px solid #0f274a; border-radius: 8px; padding: 12px; text-align: center; margin-top: 8px;">
          <img src="${m.assinatura_rubrica}" alt="Rúbrica Digital" style="max-height: 90px; max-width: 100%;">
          <div style="font-size: 0.75rem; color: #64748b; margin-top: 6px; border-top: 1px solid #e2e8f0; padding-top: 4px;">
            <strong>Assinado por:</strong> ${m.nome_assinante || m.nome_completo}<br/>
            <strong>Data/Hora:</strong> ${m.data_assinatura || m.data_registro}<br/>
            <strong>Hash LGPD:</strong> ${m.hash_autenticidade || 'VALIDADO-MEVAM-GYN'}
          </div>
        </div>
      `;
    }

    corpo.innerHTML = `
      <div style="display: flex; gap: 16px; align-items: flex-start; margin-bottom: 16px; border-bottom: 1px solid #e2e8f0; padding-bottom: 14px;">
        <div style="width: 80px; height: 106px; border-radius: 8px; border: 2px solid var(--primary-light); overflow: hidden; background: #e2e8f0; flex-shrink: 0; display: flex; align-items: center; justify-content: center; box-shadow: var(--shadow-sm);">
          ${m.foto_3x4 ? `<img src="${m.foto_3x4}" style="width: 100%; height: 100%; object-fit: cover;">` : `<span style="font-size: 2rem; opacity: 0.5;">👤</span>`}
        </div>
        <div style="flex: 1;">
          <h3 style="font-size: 1.25rem; color: #0f172a; margin: 0;">${m.nome_completo}</h3>
          <span style="font-size: 0.8rem; color: #64748b;">Cadastrado em: ${m.data_registro} (ID: #${m.id})</span><br/>
          <span class="badge badge-info" style="margin-top: 6px; display: inline-block; font-size: 0.72rem;">Foto 3x4 Identificação Facial</span>
        </div>
        <div style="display: flex; gap: 8px; flex-direction: column;">
          <button class="btn btn-primary btn-sm" onclick="window.open('/api/membros/${m.id}/pdf', '_blank')">📄 Baixar PDF</button>
          <button class="btn btn-secondary btn-sm" style="color: #b45309; border-color: #fde68a; background: #fef3c7;" onclick="ErpDashboard.anonimizarDireitoTitular(${m.id})">🛡️ Anonimizar</button>
        </div>
      </div>

      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 14px; font-size: 0.88rem; line-height: 1.6;">
        <div>
          <strong>📍 Endereço:</strong> ${m.endereco || '-'}<br/>
          <strong>Bairro / Cidade:</strong> ${m.bairro || '-'}, ${m.cidade || 'Goiânia'} - CEP: ${m.cep || '-'}<br/>
          <strong>Data Nascimento:</strong> ${m.data_nascimento || '-'} (${m.naturalidade || 'Naturalidade não inf.'})<br/>
          <strong>Sexo / Estado Civil:</strong> ${m.sexo || '-'} | ${m.estado_civil || '-'}<br/>
          <strong>Cônjuge:</strong> ${m.conjuge || 'Nenhum'}
        </div>
        <div>
          <strong>📱 WhatsApp:</strong> ${m.whatsapp || '-'}<br/>
          <strong>📞 Telefone:</strong> ${m.telefone || '-'}<br/>
          <strong>✉️ E-mail:</strong> ${m.email || '-'}<br/>
          <strong>🎓 Escolaridade:</strong> ${m.escolaridade || '-'}<br/>
          <strong>💼 Profissão:</strong> ${m.profissao || '-'} (${m.empresa || '-'})
        </div>
      </div>

      <div style="margin-top: 16px; padding: 12px; background: #f8fafc; border-radius: 8px;">
        <strong>⛪ Vida Eclesiástica:</strong><br/>
        • <strong>Batizado:</strong> ${m.batizado || 'Não'} (Data: ${m.data_batismo || 'Não inf.'})<br/>
        • <strong>Congregava Antes:</strong> ${m.congregava_antes || 'Não'} (Onde: ${m.onde_congregava || 'Não inf.'})<br/>
        • <strong>Área Ministerial:</strong> ${m.area_ministerial || 'Nenhuma informada'}<br/>
        • <strong>Interesse de Batismo na Família:</strong> ${m.interesse_batismo_familia || 'Não inf.'}
      </div>

      <div style="margin-top: 16px;">
        <strong>👨‍👩‍👧‍👦 Filhos Cadastrados:</strong>
        ${filhosHtml}
      </div>

      <div style="margin-top: 16px;">
        <strong>📜 Aceite da Confissão de Fé & Rúbrica Registrada:</strong>
        ${rubricaHtml}
      </div>
    `;

    modal.style.display = 'flex';
  }

  static anonimizarDireitoTitular(id) {
    const modalDetalhes = document.getElementById('modalDetalhesMembro');
    if (modalDetalhes) modalDetalhes.style.display = 'none';
    const inputId = document.getElementById('anonMembroId');
    if (inputId) inputId.value = id;
    const modalAnon = document.getElementById('modalAnonimizacaoLgpd');
    if (modalAnon) modalAnon.style.display = 'flex';
  }

  static async excluirMembro(id) {
    if (!confirm(`Deseja realmente excluir o cadastro do membro #${id}? Esta ação elimina definitivamente todos os dados pessoais (Art. 18, VI da LGPD).`)) return;

    try {
      const res = await fetch(`/api/membros/${id}`, { method: 'DELETE' });
      const data = await res.json();
      if (res.ok) {
        window.mostrarToast("Membro excluído com sucesso conforme diretrizes da LGPD.", "success");
        window.ErpDashboardInstance.carregarDados();
      } else {
        window.mostrarToast(data.error || "Apenas Administradores têm permissão para excluir registros.", "error");
      }
    } catch (e) {
      window.mostrarToast("Erro ao excluir do servidor.", "error");
    }
  }

  exportarCsv() {
    if (this.membros.length === 0) {
      window.mostrarToast("Não há dados para exportar.", "error");
      return;
    }

    const headers = [
      "ID", "Data Registro", "Nome Completo", "Endereço", "Bairro", "Cidade", "CEP",
      "Data Nascimento", "Sexo", "Estado Civil", "Cônjuge", "WhatsApp", "E-mail",
      "Profissão", "Batizado", "Área Ministerial", "Credo Aceito", "Data Assinatura"
    ];

    const rows = this.membros.map(m => [
      m.id,
      `"${m.data_registro || ''}"`,
      `"${m.nome_completo || ''}"`,
      `"${m.endereco || ''}"`,
      `"${m.bairro || ''}"`,
      `"${m.cidade || ''}"`,
      `"${m.cep || ''}"`,
      `"${m.data_nascimento || ''}"`,
      `"${m.sexo || ''}"`,
      `"${m.estado_civil || ''}"`,
      `"${m.conjuge || ''}"`,
      `"${m.whatsapp || ''}"`,
      `"${m.email || ''}"`,
      `"${m.profissao || ''}"`,
      `"${m.batizado || ''}"`,
      `"${m.area_ministerial || ''}"`,
      m.credo_aceito ? "Sim" : "Não",
      `"${m.data_assinatura || ''}"`
    ]);

    const csvContent = "\uFEFF" + [headers.join(","), ...rows.map(r => r.join(","))].join("\n");
    const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", `membros_mevam_gyn_${new Date().toISOString().slice(0,10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.mostrarToast("Planilha CSV exportada com sucesso!", "success");
  }
}

document.addEventListener('DOMContentLoaded', () => {
  window.ErpDashboardInstance = new ErpDashboard();
  window.ErpDashboard = ErpDashboard;
});
