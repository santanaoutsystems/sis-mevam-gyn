/**
 * Auth & LGPD Manager - SIS MEVAM-GYN
 * Controle de Autenticação, Perfis de Acesso (RBAC), Trilha de Auditoria e Direitos do Titular (LGPD)
 */

class AuthManager {
  constructor() {
    this.currentUser = null;
    this.init();
  }

  async init() {
    this.bindEvents();
    await this.verificarAutenticacao();
  }

  bindEvents() {
    // Botões de alternância no modal de login
    const tabLogin = document.getElementById('tabAuthLogin');
    const tabRegister = document.getElementById('tabAuthRegister');
    const formLogin = document.getElementById('formAuthLogin');
    const formRegister = document.getElementById('formAuthRegister');

    if (tabLogin && tabRegister) {
      tabLogin.addEventListener('click', () => {
        tabLogin.classList.add('active');
        tabRegister.classList.remove('active');
        formLogin.style.display = 'block';
        formRegister.style.display = 'none';
      });

      tabRegister.addEventListener('click', () => {
        tabRegister.classList.add('active');
        tabLogin.classList.remove('active');
        formLogin.style.display = 'none';
        formRegister.style.display = 'block';
      });
    }

    // Submissão do Formulário de Login
    if (formLogin) {
      formLogin.addEventListener('submit', async (e) => {
        e.preventDefault();
        const email = document.getElementById('loginEmail').value.trim();
        const senha = document.getElementById('loginSenha').value;
        await this.realizarLogin(email, senha);
      });
    }

    // Submissão do Formulário de Registro (Modal)
    if (formRegister) {
      formRegister.addEventListener('submit', async (e) => {
        e.preventDefault();
        const nome = document.getElementById('regNome').value.trim();
        const email = document.getElementById('regEmail').value.trim();
        const senha = document.getElementById('regSenha').value;
        const senhaConfirma = document.getElementById('regSenhaConfirma').value;

        if (senha !== senhaConfirma) {
          window.mostrarToast("As senhas não coincidem.", "error");
          return;
        }

        await this.realizarRegistro(nome, email, senha);
      });
    }

    // Portal de Acesso Inicial (Primeira Tela)
    const portalTabLogin = document.getElementById('portalTabLogin');
    const portalTabRegister = document.getElementById('portalTabRegister');
    const portalFormLogin = document.getElementById('portalFormLogin');
    const portalFormRegister = document.getElementById('portalFormRegister');

    if (portalTabLogin && portalTabRegister && portalFormLogin && portalFormRegister) {
      portalTabLogin.addEventListener('click', () => {
        portalTabLogin.classList.add('active');
        portalTabRegister.classList.remove('active');
        portalFormLogin.style.display = 'block';
        portalFormRegister.style.display = 'none';
      });

      portalTabRegister.addEventListener('click', () => {
        portalTabRegister.classList.add('active');
        portalTabLogin.classList.remove('active');
        portalFormLogin.style.display = 'none';
        portalFormRegister.style.display = 'block';
      });

      portalFormLogin.addEventListener('submit', async (e) => {
        e.preventDefault();
        const email = document.getElementById('portalLoginEmail').value.trim();
        const senha = document.getElementById('portalLoginSenha').value;
        await this.realizarLogin(email, senha);
      });

      portalFormRegister.addEventListener('submit', async (e) => {
        e.preventDefault();
        const nome = document.getElementById('portalRegNome').value.trim();
        const email = document.getElementById('portalRegEmail').value.trim();
        const senha = document.getElementById('portalRegSenha').value;
        const senhaConfirma = document.getElementById('portalRegSenhaConfirma').value;

        if (senha !== senhaConfirma) {
          window.mostrarToast("As senhas não coincidem.", "error");
          return;
        }

        await this.realizarRegistro(nome, email, senha);
      });
    }


    // Botões da Aba de Usuários e LGPD
    const tabUsuarios = document.getElementById('tabNavUsuarios');
    const tabLgpd = document.getElementById('tabNavLgpd');
    const tabCadastro = document.getElementById('tabNavCadastro');
    const tabErp = document.getElementById('tabNavErp');

    const viewCadastro = document.getElementById('viewCadastro');
    const viewErp = document.getElementById('viewErp');
    const viewUsuarios = document.getElementById('viewUsuarios');
    const viewLgpd = document.getElementById('viewLgpd');

    const ocultarTodasViews = () => {
      [viewCadastro, viewErp, viewUsuarios, viewLgpd].forEach(v => { if (v) v.style.display = 'none'; });
      [tabCadastro, tabErp, tabUsuarios, tabLgpd].forEach(t => { if (t) t.classList.remove('active'); });
    };

    if (tabUsuarios) {
      tabUsuarios.addEventListener('click', () => {
        ocultarTodasViews();
        tabUsuarios.classList.add('active');
        if (viewUsuarios) viewUsuarios.style.display = 'block';
        if (window.UsuariosManagerInstance) window.UsuariosManagerInstance.carregarUsuarios();
      });
    }

    if (tabLgpd) {
      tabLgpd.addEventListener('click', () => {
        ocultarTodasViews();
        tabLgpd.classList.add('active');
        if (viewLgpd) viewLgpd.style.display = 'block';
        if (window.LgpdManagerInstance) window.LgpdManagerInstance.carregarLogs();
      });
    }
  }

  async verificarAutenticacao() {
    try {
      const res = await fetch('/api/auth/me');
      const data = await res.json();
      if (data.authenticated && data.user) {
        this.currentUser = data.user;
        this.renderizarUsuarioLogado();
      } else {
        this.currentUser = null;
        this.renderizarUsuarioDeslogado();
      }
    } catch (e) {
      console.warn("Erro ao checar autenticação:", e);
      this.renderizarUsuarioDeslogado();
    }
  }

  renderizarUsuarioLogado() {
    const container = document.getElementById('headerUserArea');
    if (!container) return;

    const perfil = this.currentUser.perfil || 'membro';
    const perfilNomes = {
      'admin': '👑 Administrador',
      'secretaria': '📋 Secretaria',
      'membro': '👤 Membro'
    };

    const iniciais = (this.currentUser.nome || 'U')
      .split(' ')
      .map(p => p[0])
      .slice(0, 2)
      .join('')
      .toUpperCase();

    container.innerHTML = `
      <div class="user-profile-chip">
        <div class="user-avatar-circle">${iniciais}</div>
        <div class="user-info-text">
          <span class="user-name-title" title="${this.currentUser.nome}">${this.currentUser.nome}</span>
          <span class="badge-role ${perfil}">${perfilNomes[perfil] || perfil}</span>
        </div>
        <button type="button" class="btn btn-secondary btn-sm" id="btnHeaderLogout" title="Encerrar Sessão" style="padding: 4px 8px; font-size: 0.78rem;">
          🚪 Sair
        </button>
      </div>
    `;

    document.getElementById('btnHeaderLogout').addEventListener('click', () => this.realizarLogout());

    // Alternar visão: Esconder Portal de Acesso e Exibir Aplicação
    const portal = document.getElementById('viewPortalAcesso');
    const appViews = document.getElementById('appViewsWrapper');
    const mainNav = document.getElementById('mainNavPills');

    if (portal) portal.style.display = 'none';
    if (appViews) appViews.style.display = 'block';
    if (mainNav) mainNav.style.display = 'flex';

    // Ajustar visibilidade das abas conforme permissão
    const tabErp = document.getElementById('tabNavErp');
    const tabUsuarios = document.getElementById('tabNavUsuarios');
    const tabLgpd = document.getElementById('tabNavLgpd');

    if (tabErp) tabErp.style.display = (perfil === 'admin' || perfil === 'secretaria') ? 'flex' : 'none';
    if (tabUsuarios) tabUsuarios.style.display = (perfil === 'admin') ? 'flex' : 'none';
    if (tabLgpd) tabLgpd.style.display = (perfil === 'admin') ? 'flex' : 'none';
  }

  renderizarUsuarioDeslogado() {
    const container = document.getElementById('headerUserArea');
    if (container) {
      container.innerHTML = `
        <button type="button" class="btn btn-primary btn-sm" onclick="window.AuthManagerInstance.abrirModalAuth('login')">
          🔑 Entrar / Cadastrar
        </button>
      `;
    }

    // Alternar visão: Exibir Portal de Acesso e Esconder Aplicação
    const portal = document.getElementById('viewPortalAcesso');
    const appViews = document.getElementById('appViewsWrapper');
    const mainNav = document.getElementById('mainNavPills');

    if (portal) portal.style.display = 'flex';
    if (appViews) appViews.style.display = 'none';
    if (mainNav) mainNav.style.display = 'none';

    // Esconder abas restritas se deslogado
    const tabErp = document.getElementById('tabNavErp');
    const tabUsuarios = document.getElementById('tabNavUsuarios');
    const tabLgpd = document.getElementById('tabNavLgpd');

    if (tabErp) tabErp.style.display = 'none';
    if (tabUsuarios) tabUsuarios.style.display = 'none';
    if (tabLgpd) tabLgpd.style.display = 'none';
  }

  abrirModalAuth(aba = 'login') {
    const modal = document.getElementById('modalAuth');
    if (!modal) return;
    modal.style.display = 'flex';

    if (aba === 'registro') {
      document.getElementById('tabAuthRegister').click();
    } else {
      document.getElementById('tabAuthLogin').click();
    }
  }

  fecharModalAuth() {
    const modal = document.getElementById('modalAuth');
    if (modal) modal.style.display = 'none';
  }

  async realizarLogin(email, senha) {
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, senha })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Falha no login");

      window.mostrarToast(data.message || "Login realizado com sucesso!", "success");
      this.fecharModalAuth();
      this.currentUser = data.user;
      this.renderizarUsuarioLogado();

      // Recarregar dados do ERP se estiver na aba do ERP
      if (window.ErpDashboardInstance) window.ErpDashboardInstance.carregarDados();
    } catch (err) {
      window.mostrarToast(err.message, "error");
    }
  }

  async realizarRegistro(nome, email, senha) {
    try {
      const res = await fetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nome, email, senha })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Falha ao registrar");

      window.mostrarToast("Conta criada e login efetuado com sucesso!", "success");
      this.fecharModalAuth();
      this.currentUser = data.user;
      this.renderizarUsuarioLogado();
    } catch (err) {
      window.mostrarToast(err.message, "error");
    }
  }

  async realizarLogout() {
    try {
      await fetch('/api/auth/logout', { method: 'POST' });
      window.mostrarToast("Sessão encerrada.", "success");
      this.currentUser = null;
      this.renderizarUsuarioDeslogado();
      // Voltar para aba de cadastro
      document.getElementById('tabNavCadastro').click();
    } catch (e) {
      location.reload();
    }
  }
}


// ==============================================================================
// GESTÃO DE USUÁRIOS E PERFIS DE ACESSO (RBAC)
// ==============================================================================
class UsuariosManager {
  constructor() {
    this.usuarios = [];
    this.initElements();
  }

  initElements() {
    const searchInput = document.getElementById('userSearchInput');
    if (searchInput) {
      searchInput.addEventListener('input', (e) => {
        const termo = e.target.value.toLowerCase();
        this.renderizarTabela(this.usuarios.filter(u => 
          u.nome.toLowerCase().includes(termo) || 
          u.email.toLowerCase().includes(termo) ||
          u.perfil.toLowerCase().includes(termo)
        ));
      });
    }

    const btnNovo = document.getElementById('btnNovoUsuarioModal');
    if (btnNovo) {
      btnNovo.addEventListener('click', () => {
        const modal = document.getElementById('modalCriarUsuarioAdmin');
        if (modal) modal.style.display = 'flex';
      });
    }

    const formCriar = document.getElementById('formCriarUsuarioAdmin');
    if (formCriar) {
      formCriar.addEventListener('submit', async (e) => {
        e.preventDefault();
        const nome = document.getElementById('adminNewUserNome').value.trim();
        const email = document.getElementById('adminNewUserEmail').value.trim();
        const senha = document.getElementById('adminNewUserSenha').value;
        const perfil = document.getElementById('adminNewUserPerfil').value;

        try {
          const res = await fetch('/api/usuarios', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ nome, email, senha, perfil })
          });
          const data = await res.json();
          if (!res.ok) throw new Error(data.error || "Erro ao criar usuário");

          window.mostrarToast("Usuário cadastrado com sucesso!", "success");
          document.getElementById('modalCriarUsuarioAdmin').style.display = 'none';
          formCriar.reset();
          await this.carregarUsuarios();
        } catch (err) {
          window.mostrarToast(err.message, "error");
        }
      });
    }
  }

  async carregarUsuarios() {
    try {
      const res = await fetch('/api/usuarios');
      if (!res.ok) throw new Error("Acesso não autorizado.");
      this.usuarios = await res.json();
      this.atualizarMetricas();
      this.renderizarTabela(this.usuarios);
    } catch (err) {
      console.warn("Erro ao buscar usuários:", err);
    }
  }

  atualizarMetricas() {
    const elTotal = document.getElementById('metricTotalUsuarios');
    const elAdmins = document.getElementById('metricAdmins');
    const elSecr = document.getElementById('metricSecretarias');
    const elMembros = document.getElementById('metricMembros');

    if (elTotal) elTotal.textContent = this.usuarios.length;
    if (elAdmins) elAdmins.textContent = this.usuarios.filter(u => u.perfil === 'admin').length;
    if (elSecr) elSecr.textContent = this.usuarios.filter(u => u.perfil === 'secretaria').length;
    if (elMembros) elMembros.textContent = this.usuarios.filter(u => u.perfil === 'membro').length;
  }

  renderizarTabela(lista) {
    const tbody = document.getElementById('usuariosTableBody');
    if (!tbody) return;

    if (!lista || lista.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding: 24px; color: var(--text-muted);">Nenhum usuário encontrado.</td></tr>`;
      return;
    }

    tbody.innerHTML = lista.map(u => {
      const isCurrentUser = window.AuthManagerInstance.currentUser && window.AuthManagerInstance.currentUser.sub === u.id;
      return `
        <tr>
          <td><strong>#${u.id}</strong></td>
          <td>
            <div style="font-weight: 600; color: var(--text-main);">${u.nome}</div>
            <small style="color: var(--text-muted); font-size: 0.78rem;">${u.email}</small>
          </td>
          <td>
            <select class="form-select form-select-sm" style="font-size: 0.82rem; padding: 4px 8px; border-radius: 6px;" 
                    onchange="window.UsuariosManagerInstance.alterarPerfil(${u.id}, this.value)" ${isCurrentUser ? 'disabled title="Você não pode alterar seu próprio perfil"' : ''}>
              <option value="admin" ${u.perfil === 'admin' ? 'selected' : ''}>👑 Administrador</option>
              <option value="secretaria" ${u.perfil === 'secretaria' ? 'selected' : ''}>📋 Secretaria</option>
              <option value="membro" ${u.perfil === 'membro' ? 'selected' : ''}>👤 Membro</option>
            </select>
          </td>
          <td>
            <button type="button" class="btn btn-sm ${u.ativo ? 'btn-secondary' : 'btn-accent'}" 
                    style="font-size: 0.75rem; padding: 3px 8px;"
                    onclick="window.UsuariosManagerInstance.alternarStatus(${u.id}, ${u.ativo ? 0 : 1})" ${isCurrentUser ? 'disabled' : ''}>
              ${u.ativo ? '🟢 Ativo' : '🔴 Inativo'}
            </button>
          </td>
          <td style="font-size: 0.8rem; color: var(--text-muted);">
            ${u.ultimo_login ? u.ultimo_login.slice(0, 16) : 'Nunca acessou'}
          </td>
          <td>
            ${isCurrentUser ? '<small style="color: var(--text-muted);">Você</small>' : `
              <button type="button" class="btn btn-secondary btn-sm" style="color: var(--danger); padding: 4px 8px;" 
                      onclick="window.UsuariosManagerInstance.excluirUsuario(${u.id}, '${u.nome}')" title="Excluir Usuário">
                🗑️
              </button>
            `}
          </td>
        </tr>
      `;
    }).join('');
  }

  async alterarPerfil(userId, novoPerfil) {
    try {
      const res = await fetch(`/api/usuarios/${userId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ perfil: novoPerfil })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Falha ao alterar perfil");
      window.mostrarToast("Perfil de acesso atualizado com sucesso!", "success");
      await this.carregarUsuarios();
    } catch (err) {
      window.mostrarToast(err.message, "error");
      await this.carregarUsuarios();
    }
  }

  async alternarStatus(userId, novoAtivo) {
    try {
      const res = await fetch(`/api/usuarios/${userId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ativo: novoAtivo })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Falha ao alterar status");
      window.mostrarToast(`Usuário ${novoAtivo ? 'ativado' : 'desativado'} com sucesso!`, "success");
      await this.carregarUsuarios();
    } catch (err) {
      window.mostrarToast(err.message, "error");
    }
  }

  async excluirUsuario(userId, nome) {
    if (!confirm(`Deseja realmente excluir o usuário "${nome}"? Esta ação é irreversível.`)) return;
    try {
      const res = await fetch(`/api/usuarios/${userId}`, { method: 'DELETE' });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Erro ao excluir usuário");
      window.mostrarToast("Usuário removido com sucesso.", "success");
      await this.carregarUsuarios();
    } catch (err) {
      window.mostrarToast(err.message, "error");
    }
  }
}


// ==============================================================================
// GESTÃO DE AUDITORIA & PRIVACIDADE LGPD
// ==============================================================================
class LgpdManager {
  constructor() {
    this.logs = [];
    this.initElements();
  }

  initElements() {
    const inputBusca = document.getElementById('lgpdSearchInput');
    if (inputBusca) {
      inputBusca.addEventListener('input', (e) => {
        const termo = e.target.value.toLowerCase();
        this.renderizarTabela(this.logs.filter(l => 
          (l.usuario_nome || '').toLowerCase().includes(termo) ||
          (l.acao || '').toLowerCase().includes(termo) ||
          (l.recurso || '').toLowerCase().includes(termo) ||
          (l.detalhes || '').toLowerCase().includes(termo) ||
          (l.ip_origem || '').toLowerCase().includes(termo)
        ));
      });
    }

    const btnAtualizar = document.getElementById('btnLgpdAtualizarLogs');
    if (btnAtualizar) {
      btnAtualizar.addEventListener('click', () => this.carregarLogs());
    }

    const btnVerPolitica = document.getElementById('btnAbrirPoliticaLgpd');
    if (btnVerPolitica) {
      btnVerPolitica.addEventListener('click', () => this.abrirModalPolitica());
    }

    // Modal de Anonimização
    const btnConfirmarAnon = document.getElementById('btnConfirmarAnonimizacao');
    if (btnConfirmarAnon) {
      btnConfirmarAnon.addEventListener('click', async () => {
        const membroId = document.getElementById('anonMembroId').value;
        const motivo = document.getElementById('anonMotivo').value.trim() || 'Solicitação expressa do titular (Art. 18 LGPD)';
        if (!membroId) {
          window.mostrarToast("Informe o ID do membro para anonimização.", "error");
          return;
        }

        try {
          const res = await fetch(`/api/membros/${membroId}/anonimizar`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ motivo })
          });
          const data = await res.json();
          if (!res.ok) throw new Error(data.error || "Erro ao anonimizar dados");

          window.mostrarToast(data.message || "Dados anonimizados com sucesso!", "success");
          document.getElementById('modalAnonimizacaoLgpd').style.display = 'none';
          document.getElementById('anonMembroId').value = '';
          await this.carregarLogs();
          if (window.ErpDashboardInstance) window.ErpDashboardInstance.carregarDados();
        } catch (err) {
          window.mostrarToast(err.message, "error");
        }
      });
    }
  }

  async carregarLogs() {
    try {
      const res = await fetch('/api/lgpd/logs');
      if (!res.ok) throw new Error("Acesso negado aos relatórios de auditoria.");
      this.logs = await res.json();
      this.renderizarTabela(this.logs);
    } catch (err) {
      console.warn("Erro ao buscar logs LGPD:", err);
    }
  }

  renderizarTabela(lista) {
    const tbody = document.getElementById('lgpdTableBody');
    if (!tbody) return;

    if (!lista || lista.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding: 24px; color: var(--text-muted);">Nenhum log de auditoria registrado ainda.</td></tr>`;
      return;
    }

    const formatarAcaoBadge = (acao) => {
      let classe = 'consulta';
      if (acao.includes('LOGIN')) classe = 'login';
      else if (acao.includes('CADASTRO')) classe = 'cadastro';
      else if (acao.includes('EXCLUSAO')) classe = 'exclusao';
      else if (acao.includes('ANONIMIZACAO')) classe = 'anonimizacao';
      else if (acao.includes('ALTERACAO')) classe = 'alteracao';
      return `<span class="badge-audit-action ${classe}">${acao}</span>`;
    };

    tbody.innerHTML = lista.map(l => `
      <tr>
        <td style="font-size: 0.78rem; color: var(--text-muted);">${l.criado_em ? l.criado_em.slice(0, 19) : ''}</td>
        <td><strong>${l.usuario_nome || 'Sistema'}</strong></td>
        <td>${formatarAcaoBadge(l.acao)}</td>
        <td style="font-weight: 500;">${l.recurso || '-'}</td>
        <td style="font-size: 0.8rem; color: var(--text-muted); max-width: 250px;">${l.detalhes || ''}</td>
        <td><code style="font-size: 0.75rem; background: var(--border-color); padding: 2px 6px; border-radius: 4px;">${l.ip_origem || '127.0.0.1'}</code></td>
      </tr>
    `).join('');
  }

  abrirModalPolitica() {
    const modal = document.getElementById('modalPoliticaLgpd');
    if (modal) modal.style.display = 'flex';
  }
}

// Inicializar Módulos no Carregamento do DOM
document.addEventListener('DOMContentLoaded', () => {
  window.AuthManagerInstance = new AuthManager();
  window.UsuariosManagerInstance = new UsuariosManager();
  window.LgpdManagerInstance = new LgpdManager();
});
