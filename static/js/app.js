
const app = {
  currentPin: "",
  currentUser: null,
  activeModule: "week",
  clientTabLoaded: {},
  orderDetailCache: {},
  clientTabCache: { loaded: {} },
  orderDetailCache: {},
  weekOffset: 0,
  currentMonth: 8,

  async init() {
    const urlParams = new URLSearchParams(window.location.search);
    const token = urlParams.get('acesso') || urlParams.get('token') || urlParams.get('convite');
    if (token) {
      await this.handleTokenLogin(token);
      return;
    }

    const saved = localStorage.getItem("mp_auth_user");
    if (saved) {
      try {
        this.currentUser = JSON.parse(saved);
        this.showApp();
      } catch(e) {
        localStorage.removeItem("mp_auth_user");
        this.showLogin();
      }
    } else {
      this.showLogin();
    }

    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sw.js');
    }
  },

  async handleTokenLogin(token) {
    try {
      const res = await fetch(`/api/auth/token_login?token=${encodeURIComponent(token.trim())}`);
      const data = await res.json();
      if (res.ok && data.success) {
        this.currentUser = data.user;
        localStorage.setItem("mp_auth_user", JSON.stringify(data.user));
        // Remove o token da URL da barra do navegador para discrição
        window.history.replaceState({}, document.title, window.location.pathname);
        this.showApp();
      } else {
        this.showLogin();
        const err = document.getElementById("loginErrorMsg");
        if (err) {
          err.innerText = data.detail || "Link de acesso inválido ou revogado.";
          err.style.display = "block";
        }
      }
    } catch(e) {
      this.showLogin();
      const err = document.getElementById("loginErrorMsg");
      if (err) {
        err.innerText = "Erro ao validar link de acesso. Verifique sua conexão.";
        err.style.display = "block";
      }
    }
  },

  async submitAdminKey() {
    const input = document.getElementById("loginAdminKey");
    const key = (input ? input.value : "").trim();
    const err = document.getElementById("loginErrorMsg");
    if (err) err.style.display = "none";

    if (!key) {
      if (err) { err.innerText = "Digite a chave mestra de acesso."; err.style.display = "block"; }
      return;
    }

    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin: key })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        this.currentUser = data.user;
        localStorage.setItem("mp_auth_user", JSON.stringify(data.user));
        this.showApp();
      } else {
        if (err) {
          err.innerText = data.detail || "Chave mestra incorreta.";
          err.style.display = "block";
        }
      }
    } catch(e) {
      if (err) {
        err.innerText = "Erro de conexão com o servidor.";
        err.style.display = "block";
      }
    }
  },

  logout() {
    localStorage.removeItem("mp_auth_user");
    this.currentUser = null;
    const input = document.getElementById("loginAdminKey");
    if (input) input.value = "";
    this.showLogin();
  },

  showLogin() {
    document.getElementById("loginScreen").style.display = "flex";
    document.getElementById("appContainer").style.display = "none";
  },

  isMonetaryAllowed() {
    const r = (this.currentUser?.role || "").toLowerCase();
    return r === "admin" || r === "engenharia" || r === "administracao" || r === "adm";
  },

  isFinancialAllowed() {
    const r = (this.currentUser?.role || "").toLowerCase();
    return r === "admin" || r === "engenharia";
  },

  isAdmin() {
    const r = (this.currentUser?.role || "").toLowerCase();
    return r === "admin";
  },

  renderHeader() {
    const greetingEl = document.getElementById("headerGreeting");
    const roleBadgeEl = document.getElementById("headerRoleBadge");
    const userName = (this.currentUser && this.currentUser.nome) ? this.currentUser.nome.split(" ")[0] : "Paulo";
    const userRole = (this.currentUser && this.currentUser.role) ? this.currentUser.role : "admin";
    const roleEmoji = {
      'admin': '👑 Admin',
      'engenharia': '🏗️ Eng',
      'administracao': '📦 Adm',
      'campo': '👷 Campo',
      'suporte': '🔧 Apoio'
    }[userRole] || '👤 Membro';

    if (greetingEl) greetingEl.innerText = `Olá, ${userName}`;
    if (roleBadgeEl) roleBadgeEl.innerText = roleEmoji;
  },

  showApp() {
    document.getElementById("loginScreen").style.display = "none";
    document.getElementById("appContainer").style.display = "block";
    
    this.renderHeader();

    // Permissões das abas
    document.getElementById("tabSuppliers").style.display = this.isMonetaryAllowed() ? "block" : "none";
    document.getElementById("tabFinancial").style.display = this.isFinancialAllowed() ? "block" : "none";
    document.getElementById("tabExport").style.display = this.isFinancialAllowed() ? "block" : "none";
    document.getElementById("tabTeam").style.display = (this.currentUser && this.currentUser.is_master) ? "block" : "none";

    this.setModule("week");
  },

  setModule(mod) {
    if (mod === "team" && (!this.currentUser || !this.currentUser.is_master)) {
      mod = "week";
    }
    this.activeModule = mod;
    document.querySelectorAll(".module-tab").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".module-section").forEach(s => s.classList.remove("active"));

    const tabMap = {
      week: document.querySelector(".module-tab[onclick*='week']"),
      month: document.querySelector(".module-tab[onclick*='month']"),
      search: document.querySelector(".module-tab[onclick*='search']"),
      groups: document.querySelector(".module-tab[onclick*='groups']"),
      recent: document.querySelector(".module-tab[onclick*='recent']"),
      suppliers: document.getElementById("tabSuppliers"),
      financial: document.getElementById("tabFinancial"),
      team: document.getElementById("tabTeam"),
      excel: document.getElementById("tabExport")
    };
    if (tabMap[mod]) tabMap[mod].classList.add("active");

    const secMap = {
      week: document.getElementById("modWeek"),
      month: document.getElementById("modMonth"),
      search: document.getElementById("modSearch"),
      groups: document.getElementById("modGroups"),
      recent: document.getElementById("modRecent"),
      suppliers: document.getElementById("modSuppliers"),
      financial: document.getElementById("modFinancial"),
      team: document.getElementById("modTeam"),
      excel: document.getElementById("modExcel")
    };
    if (secMap[mod]) secMap[mod].classList.add("active");

    // Se a aba ainda não foi carregada nesta sessão, carrega os dados
    if (!this.clientTabLoaded[mod]) {
      this.clientTabLoaded[mod] = true;
      if (mod === "week") this.loadWeek();
      else if (mod === "month") this.loadMonth();
      else if (mod === "search") this.loadCatalogAZ();
      else if (mod === "groups") this.loadGroups();
      else if (mod === "recent") this.loadRecent();
      else if (mod === "suppliers") this.loadSuppliers();
      else if (mod === "financial") this.loadFinancial();
      else if (mod === "team") this.loadTeam();
      else if (mod === "excel") this.loadExcelViewer();
    }
  },

  async loadWeek() {
    const list = document.getElementById("weekCards");
    list.innerHTML = '<div style="padding:20px;text-align:center;color:#94a3b8">⏳ Carregando entregas da semana...</div>';
    try {
      const res = await fetch(`/api/deliveries/week?offset=${this.weekOffset}&role=${this.currentUser.role}`);
      const data = await res.json();
      
      if (data.periodo) {
        const titles = { 0: "Esta Semana", 1: "Próxima Semana", "-1": "Semana Passada" };
        const prefix = titles[this.weekOffset] || `Semana (${this.weekOffset > 0 ? '+' : ''}${this.weekOffset})`;
        document.getElementById("weekTitle").innerHTML = `${prefix}<br><span style="font-size:11px;color:#94a3b8">${data.periodo}</span>`;
      }

      if (!data.cards || data.cards.length === 0) {
        list.innerHTML = '<div style="padding:24px;text-align:center;color:#94a3b8">Nenhuma entrega prevista para este período.<br><br><button class="nav-arrow" onclick="app.shiftWeek(-' + this.weekOffset + ')">Voltar para Esta Semana</button></div>';
        return;
      }
      list.innerHTML = data.cards.map(c => this.renderOrderCard(c)).join("");
    } catch(e) {
      list.innerHTML = '<div style="padding:20px;text-align:center;color:#ef4444">Erro ao carregar entregas.</div>';
    }
  },

  shiftWeek(d) {
    this.weekOffset += d;
    const titles = { 0: "Esta Semana", 1: "Próxima Semana", "-1": "Semana Passada" };
    document.getElementById("weekTitle").innerText = titles[this.weekOffset] || `Semana (${this.weekOffset > 0 ? '+' : ''}${this.weekOffset})`;
    this.loadWeek();
  },

  async loadMonth() {
    const list = document.getElementById("monthCards");
    list.innerHTML = '<div style="padding:20px;text-align:center;color:#94a3b8">⏳ Carregando entregas do mês...</div>';
    try {
      const res = await fetch(`/api/deliveries/month?mes=${this.currentMonth}&ano=2026&role=${this.currentUser.role}`);
      const data = await res.json();
      if (!data.cards || data.cards.length === 0) {
        list.innerHTML = '<div style="padding:20px;text-align:center;color:#94a3b8">Nenhum pedido previsto para este mês.</div>';
        return;
      }
      list.innerHTML = data.cards.map(c => this.renderOrderCard(c)).join("");
    } catch(e) {
      list.innerHTML = '<div style="padding:20px;text-align:center;color:#ef4444">Erro ao carregar pedidos do mês.</div>';
    }
  },

  selectMonth(m) {
    this.currentMonth = m;
    document.querySelectorAll(".month-pill").forEach(p => {
      const oc = p.getAttribute("onclick") || "";
      if (oc.includes(`selectMonth(${m})`)) {
        p.classList.add("active");
      } else {
        p.classList.remove("active");
      }
    });
    this.loadMonth();
  },

  renderOrderCard(c) {
    let itemsListHtml = "";
    if (c.itens_resumo && c.itens_resumo.length > 0) {
      itemsListHtml = `
        <div class="card-items-snippet">
          ${c.itens_resumo.map(it => `<div class="card-item-line">${it}</div>`).join("")}
          ${c.extra_itens_count > 0 ? `<div class="card-item-more">➕ + ${c.extra_itens_count} itens</div>` : ''}
        </div>
      `;
    } else {
      itemsListHtml = `<div class="card-summary-desc">${c.descricao_resumo || 'Diversos'}</div>`;
    }

    return `
      <div class="item-card" onclick="app.openOrder('${c.pc}')">
        <div class="card-header-row">
          <span class="card-tag-pc">PC ${c.pc}</span>
          <span class="card-tag-date">🚚 ${c.data_entrega}</span>
        </div>
        <div class="card-supplier-name">${c.fornecedor}</div>
        ${itemsListHtml}
        <div class="card-footer-row">
          <span>📦 ${c.total_itens} ${c.total_itens > 1 ? 'itens' : 'item'}</span>
          ${c.valor_total_formatado ? `<span class="card-money-val">${c.valor_total_formatado}</span>` : ''}
        </div>
      </div>
    `;
  },

  async openOrder(pc) {
    if (this.orderDetailCache[pc]) {
      this.renderOrderModal(this.orderDetailCache[pc]);
      return;
    }

    // Abertura instantânea (0ms) com dados conhecidos do cartão
    const knownCard = (this.currentCards || []).find(c => String(c.pc) === String(pc));
    document.getElementById("mOrderNum").innerText = `PC ${pc}`;
    
    if (knownCard) {
      document.getElementById("mFornec").innerText = knownCard.fornecedor || "Carregando...";
      document.getElementById("mOrderMeta").innerHTML = `
        <div>🚚 <b>Entrega Prevista:</b> ${knownCard.data_entrega || "A Confirmar"}</div>
        <div>📅 <b>Emissão:</b> ${knownCard.data_emissao || "-"}</div>
        ${knownCard.valor_total_formatado ? `<div>💰 <b>Valor Total:</b> <span style="color:#10b981;font-weight:800">${knownCard.valor_total_formatado}</span></div>` : ''}
      `;
      if (knownCard.itens_resumo && knownCard.itens_resumo.length) {
        document.getElementById("mItemsList").innerHTML = knownCard.itens_resumo.map(it => `
          <div class="item-box-row">
            <div>
              <div style="font-weight:700">${it}</div>
            </div>
          </div>
        `).join("") + '<div style="padding:10px;text-align:center;color:#94a3b8;font-size:11.5px;">⏳ Buscando itens completos e contatos...</div>';
      } else {
        document.getElementById("mItemsList").innerHTML = `
          <div style="padding:14px;text-align:center;color:#94a3b8;font-size:11.5px;">⏳ Carregando itens do pedido...</div>
        `;
      }
    } else {
      document.getElementById("mFornec").innerText = "Carregando fornecedor...";
      document.getElementById("mOrderMeta").innerHTML = `
        <div style="color:#94a3b8;padding:6px 0;font-size:11.5px;">⏳ Buscando dados do pedido...</div>
      `;
      document.getElementById("mItemsList").innerHTML = `
        <div style="padding:14px;text-align:center;color:#94a3b8;font-size:11.5px;">Carregando itens do pedido...</div>
      `;
    }

    const contactSec = document.getElementById("mContactSection");
    if (contactSec) contactSec.innerHTML = "";
    document.getElementById("mModalActions").innerHTML = "";
    document.getElementById("orderModal").classList.add("show");
    document.body.style.overflow = "hidden";

    try {
      const res = await fetch(`/api/order/${pc}?role=${this.currentUser.role}`);
      const data = await res.json();
      this.orderDetailCache[pc] = data;
      this.renderOrderModal(data);
    } catch(e) {
      document.getElementById("mFornec").innerText = "Erro de conexão";
      document.getElementById("mItemsList").innerHTML = '<div style="padding:20px;text-align:center;color:#ef4444">Erro ao carregar detalhes deste pedido.</div>';
    }
  },

  renderOrderModal(data) {
    document.getElementById("mOrderNum").innerText = `PC ${data.pc}`;
    document.getElementById("mFornec").innerText = data.fornecedor;
    
    let contactHtml = "";
    if (data.contatos) {
      const v = data.contatos.vendedor;
      const emp = data.contatos.empresa;
      
      const hasVendor = v && (v.nome || v.telefone);
      const hasCompany = emp && (emp.telefone || emp.email);

      if (hasVendor || hasCompany) {
        contactHtml = `
          <div style="margin-top:12px;display:flex;flex-direction:column;gap:8px;">
            <div style="font-size:11.5px;font-weight:700;color:#94a3b8;text-transform:uppercase;letter-spacing:0.5px;">Contatos do Fornecedor</div>
            ${hasVendor ? `
              <div class="contact-sub-box">
                <div class="contact-box-header">👤 <b>Vendedor:</b> ${v.nome || 'Atendimento'}</div>
                ${v.telefone ? `<div class="contact-box-line">📱 Celular: <b>${v.telefone}</b></div>` : ''}
                <div class="sup-actions">
                  ${v.telefone_clean ? `<button onclick="app.promptCall('${v.nome || 'Vendedor'}', '${v.telefone || v.telefone_clean}')" class="btn-call" style="border:none;cursor:pointer;">📞 Ligar Vendedor</button>` : ''}
                  ${v.telefone_clean ? `<a href="https://wa.me/55${v.telefone_clean}?text=Ol%C3%A1%20${encodeURIComponent(v.nome || '')}%2C%20referente%20ao%20Pedido%20PC%20${data.pc}%20da%20obra%20Maison%20Plage..." target="_blank" class="btn-wpp">💬 WhatsApp</a>` : ''}
                </div>
              </div>
            ` : ''}

            ${hasCompany ? `
              <div class="contact-sub-box" style="background:rgba(255,255,255,0.02);">
                <div class="contact-box-header">🏢 <b>Central da Empresa</b></div>
                ${emp.telefone ? `<div class="contact-box-line">☎️ Fixo: <b>${emp.telefone}</b></div>` : ''}
                ${emp.email ? `<div class="contact-box-line">✉️ E-mail: <b>${emp.email}</b></div>` : ''}
                <div class="sup-actions">
                  ${emp.telefone_clean ? `<button onclick="app.promptCall('Central da Empresa', '${emp.telefone || emp.telefone_clean}')" class="btn-call" style="background:#475569;border:none;cursor:pointer;">☎️ Ligar Loja</button>` : ''}
                  ${emp.email ? `<a href="mailto:${emp.email}?subject=Pedido%20de%20Compra%20PC%20${data.pc}%20-%20Residencial%20Maison%20Plage" class="btn-mail">✉️ Enviar E-mail</a>` : ''}
                </div>
              </div>
            ` : ''}
          </div>
        `;
      }
    }

    document.getElementById("mOrderMeta").innerHTML = `
      <div>🚚 <b>Entrega Prevista:</b> ${data.data_entrega}</div>
      <div>📅 <b>Emissão:</b> ${data.data_emissao}</div>
      ${data.condicao_pagamento ? `<div>💳 <b>Pagamento:</b> ${data.condicao_pagamento}</div>` : ''}
      ${data.valor_total_formatado ? `<div>💰 <b>Valor Total:</b> <span style="color:#10b981;font-weight:800">${data.valor_total_formatado}</span></div>` : ''}
    `;

    document.getElementById("mItemsList").innerHTML = data.itens.map(it => `
      <div class="item-box-row">
        <div>
          <div style="font-weight:700">${it.descricao}</div>
          <div style="color:#60a5fa;font-size:11px">Qtd: ${it.quantidade} ${it.unidade} ${it.valor_unitario ? `• Un: ${it.valor_unitario}` : ''}</div>
        </div>
        ${it.valor_total ? `<div style="font-weight:800;color:#10b981">${it.valor_total}</div>` : ''}
      </div>
    `).join("");

    const contactSec = document.getElementById("mContactSection");
    if (contactSec) {
      contactSec.innerHTML = contactHtml;
    }

    if (data.can_pdf) {
      document.getElementById("mModalActions").innerHTML = `
        <div style="display:flex;gap:8px;">
          <a href="/api/order/${data.pc}/pdf?role=${this.currentUser.role}" target="_blank" class="btn-pdf-action" style="margin-top:0;flex:1;">
            📄 Abrir PDF
          </a>
          <button onclick="app.shareOrderPdf('${data.pc}')" class="btn-pdf-action" style="margin-top:0;flex:1;background:linear-gradient(135deg, #7c3aed, #6d28d9);box-shadow:0 4px 15px rgba(124,58,237,0.4);border:none;cursor:pointer;">
            📤 Compartilhar / Salvar
          </button>
        </div>
      `;
    } else {
      document.getElementById("mModalActions").innerHTML = "";
    }
    document.getElementById("orderModal").classList.add("show");
    document.body.style.overflow = "hidden";
  },

  closeModal() {
    document.getElementById("orderModal").classList.remove("show");
    const matOpen = document.getElementById("matOrdersModal") && document.getElementById("matOrdersModal").classList.contains("show");
    if (!matOpen) {
      document.body.style.overflow = "";
    }
  },

  currentLetter: "TODOS",
  catalogQuery: "",
  allInsumosCache: null,
  totalInsumosCadastrados: 0,

  renderLettersBar() {
    const bar = document.getElementById("lettersBar");
    if (!bar) return;
    const letters = ["TODOS", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z"];
    bar.innerHTML = letters.map(l => `
      <button class="letter-pill ${this.currentLetter === l ? 'active' : ''}" onclick="app.selectLetter('${l}')">${l}</button>
    `).join("");
  },

  selectLetter(l) {
    this.currentLetter = l;
    this.renderLettersBar();
    this.renderCatalogList();
  },

  handleSearch(val) {
    const q = (val || "").trim();
    const btn = document.getElementById("clearSearchBtn");
    if (btn) btn.style.display = q ? "block" : "none";

    if (this.activeModule === "suppliers") {
      this.filterSuppliers(q);
    } else {
      if (this.activeModule !== "search") {
        this.setModule("search");
      }
      this.filterCatalog(q);
    }
  },

  clearSearch() {
    const input = document.getElementById("searchInput");
    if (input) input.value = "";
    const btn = document.getElementById("clearSearchBtn");
    if (btn) btn.style.display = "none";
    if (this.activeModule === "suppliers") {
      this.filterSuppliers("");
    } else {
      this.filterCatalog("");
    }
  },

  filterCatalog(val) {
    this.catalogQuery = (val || "").trim();
    this.renderCatalogList();
  },

  async loadCatalogAZ() {
    this.renderLettersBar();
    const list = document.getElementById("materialsLeanList");
    
    if (!this.allInsumosCache || this.allInsumosCache.length === 0) {
      list.innerHTML = '<div style="padding:24px;text-align:center;color:#94a3b8">⏳ Carregando catálogo de insumos...</div>';
      try {
        const res = await fetch(`/api/materials/catalog?role=${this.currentUser.role}`);
        const data = await res.json();
        this.allInsumosCache = data.insumos || [];
        this.totalInsumosCadastrados = data.total_cadastrados || this.allInsumosCache.length;
      } catch(e) {
        list.innerHTML = '<div style="padding:20px;text-align:center;color:#ef4444">Erro ao carregar catálogo de insumos.</div>';
        return;
      }
    }

    this.renderCatalogList();
  },

  renderCatalogList() {
    const list = document.getElementById("materialsLeanList");
    if (!list) return;

    if (!this.allInsumosCache) {
      this.loadCatalogAZ();
      return;
    }

    let filtered = this.allInsumosCache;

    if (this.currentLetter && this.currentLetter !== "TODOS") {
      const l = this.currentLetter.toUpperCase();
      filtered = filtered.filter(m => m.nome.toUpperCase().startsWith(l));
    }

    if (this.catalogQuery) {
      const q = this.catalogQuery.toLowerCase();
      filtered = filtered.filter(m => 
        m.nome.toLowerCase().includes(q) || 
        (m.codigo && m.codigo.toLowerCase().includes(q)) || 
        (m.familia && m.familia.toLowerCase().includes(q))
      );
    }

    const metricsElem = document.getElementById("catalogMetrics");
    if (metricsElem) {
      metricsElem.innerHTML = `📋 <b>${filtered.length}</b> de <b>${this.totalInsumosCadastrados}</b> insumos cadastrados`;
    }

    if (filtered.length === 0) {
      list.innerHTML = '<div style="padding:24px;text-align:center;color:#94a3b8">Nenhum insumo localizado com este filtro.</div>';
      return;
    }

    list.innerHTML = filtered.slice(0, 300).map(m => `
      <div class="material-lean-row" onclick="app.openMaterialOrders('${encodeURIComponent(m.nome)}')">
        <div class="mat-lean-name">${m.nome}</div>
        <div class="mat-lean-badge">${m.qtd_formatada} • ${m.pedidos_count} PC</div>
      </div>
    `).join("");
  },

  async openMaterialOrders(encodedName) {
    const name = decodeURIComponent(encodedName);
    document.getElementById("matModalTitle").innerText = name;
    document.getElementById("matModalSub").innerText = "Carregando pedidos...";
    const cardsDiv = document.getElementById("matOrdersCards");
    cardsDiv.innerHTML = '<div style="padding:20px;text-align:center;color:#94a3b8">⏳ Buscando pedidos...</div>';
    document.getElementById("matOrdersModal").classList.add("show");
    document.body.style.overflow = "hidden";

    try {
      const res = await fetch(`/api/materials/orders?nome=${encodeURIComponent(name)}&role=${this.currentUser.role}`);
      const data = await res.json();
      document.getElementById("matModalSub").innerText = `${data.total_pedidos} Pedido(s) de Compra`;
      if (!data.cards || data.cards.length === 0) {
        cardsDiv.innerHTML = '<div style="padding:20px;text-align:center;color:#94a3b8">Nenhum pedido encontrado.</div>';
        return;
      }
      cardsDiv.innerHTML = data.cards.map(c => this.renderOrderCard(c)).join("");
    } catch(e) {
      cardsDiv.innerHTML = '<div style="padding:20px;text-align:center;color:#ef4444">Erro ao carregar pedidos deste insumo.</div>';
    }
  },

  closeMatOrdersModal(e) {
    if (e && e.target && e.target.id !== "matOrdersModal" && !e.target.classList.contains("btn-close")) return;
    document.getElementById("matOrdersModal").classList.remove("show");
    document.body.style.overflow = "";
  },

  async loadGroups() {
    const grid = document.getElementById("groupsGrid");
    grid.innerHTML = '<div style="padding:20px;text-align:center;color:#94a3b8">⏳ Carregando Macro-Grupos da obra...</div>';
    try {
      const res = await fetch('/api/groups');
      const data = await res.json();
      
      const macroMap = [
        { title: "Obra Grossa & Estrutura", icon: "🏗️", keywords: ["BLOCO", "PRODUTOS METÁLICOS", "AGREGADO", "ARGAMASSA", "MADEIRA", "PRÉ-MOLDADO", "ESTRUTURA", "AÇO"] },
        { title: "Instalações Prediais", icon: "⚡", keywords: ["ELÉTRICA", "HIDRÁULICA", "INCÊNDIO", "GÁS", "TUBO", "CONEX", "FIAÇÃO", "PVC"] },
        { title: "Acabamentos & Pintura", icon: "🛡️", keywords: ["IMPERMEABILIZ", "TINTA", "VERNIZ", "LOUÇA", "METAL", "PAVIMENTA", "DRENAGEM", "REVESTIMENTO", "PISO"] },
        { title: "Segurança, EPIs & Apoio", icon: "🦺", keywords: ["EPI", "EPC", "FERRAMENTA", "EQUIPAMENTO", "AUXILIAR", "LIMPEZA", "EXPEDIENTE", "ALIMENTA"] },
        { title: "Serviços & Esquadrias", icon: "🚜", keywords: ["ESQUADRIA", "VIDRO", "SERVIÇO", "LOCAÇÃO", "MÁQUINA", "EMPREITADO", "PAISAGISMO"] }
      ];

      const groups = data.groups || [];
      const assigned = new Set();
      const macroCards = [];

      for (const m of macroMap) {
        const subList = groups.filter(g => {
          const match = m.keywords.some(k => g.familia.toUpperCase().includes(k));
          if (match) assigned.add(g.familia);
          return match;
        });
        if (subList.length > 0) {
          const totOrders = subList.reduce((acc, curr) => acc + (curr.orders_count || 0), 0);
          const totItems = subList.reduce((acc, curr) => acc + (curr.items_count || 0), 0);
          macroCards.push({
            title: m.title,
            icon: m.icon,
            orders: totOrders,
            items: totItems,
            subs: subList
          });
        }
      }

      const remaining = groups.filter(g => !assigned.has(g.familia));
      if (remaining.length > 0) {
        const totOrders = remaining.reduce((acc, curr) => acc + (curr.orders_count || 0), 0);
        const totItems = remaining.reduce((acc, curr) => acc + (curr.items_count || 0), 0);
        macroCards.push({
          title: "Outros Suprimentos & Diversos",
          icon: "📦",
          orders: totOrders,
          items: totItems,
          subs: remaining
        });
      }

      grid.innerHTML = macroCards.map((m, idx) => `
        <div class="macro-group-card" id="macroCard_${idx}" onclick="app.toggleMacro(${idx})">
          <div class="macro-card-head">
            <div class="macro-title-row">
              <span class="macro-icon">${m.icon}</span>
              <div class="macro-title">${m.title}</div>
            </div>
            <div class="macro-right-meta">
              <span class="macro-badge">${m.orders} pedidos</span>
              <span class="macro-chevron">▼</span>
            </div>
          </div>
          <div class="macro-sub-summary">
            <span>📦 ${m.items} itens</span>
            <span>•</span>
            <span>📁 ${m.subs.length} subgrupos</span>
          </div>
          <div class="macro-subs-wrapper">
            <div class="macro-subs-grid">
              ${m.subs.map(s => `
                <div class="macro-sub-item" onclick="event.stopPropagation(); app.openGroupOrders('${s.familia}')">
                  <span>📁 ${s.familia}</span>
                  <span class="macro-sub-item-badge">${s.orders_count} peds</span>
                </div>
              `).join("")}
            </div>
          </div>
        </div>
      `).join("");

    } catch(e) {
      grid.innerHTML = '<div style="padding:20px;text-align:center;color:#ef4444">Erro ao carregar grupos.</div>';
    }
  },

  toggleMacro(idx) {
    const card = document.getElementById(`macroCard_${idx}`);
    if (card) {
      card.classList.toggle("expanded");
    }
  },

  async openGroupOrders(fam) {
    document.getElementById("matModalTitle").innerText = `📁 ${fam}`;
    document.getElementById("matModalSub").innerText = "Carregando pedidos do grupo...";
    const cardsDiv = document.getElementById("matOrdersCards");
    cardsDiv.innerHTML = '<div style="padding:20px;text-align:center;color:#94a3b8">⏳ Buscando pedidos...</div>';
    document.getElementById("matOrdersModal").classList.add("show");
    document.body.style.overflow = "hidden";

    try {
      const res = await fetch(`/api/groups/orders?familia=${encodeURIComponent(fam)}&role=${this.currentUser.role}`);
      const data = await res.json();
      document.getElementById("matModalSub").innerText = `${data.total_pedidos} Pedido(s) de Compra`;
      if (!data.cards || data.cards.length === 0) {
        cardsDiv.innerHTML = '<div style="padding:20px;text-align:center;color:#94a3b8">Nenhum pedido encontrado para este grupo.</div>';
        return;
      }
      cardsDiv.innerHTML = data.cards.map(c => this.renderOrderCard(c)).join("");
    } catch(e) {
      cardsDiv.innerHTML = '<div style="padding:20px;text-align:center;color:#ef4444">Erro ao carregar pedidos deste grupo.</div>';
    }
  },

  async loadRecent() {
    const list = document.getElementById("recentCards");
    list.innerHTML = '<div style="padding:20px;text-align:center;color:#94a3b8">⏳ Carregando compras recentes...</div>';
    try {
      const res = await fetch(`/api/recent_purchases?role=${this.currentUser.role}`);
      const data = await res.json();
      if (!data.cards || data.cards.length === 0) {
        list.innerHTML = '<div style="padding:20px;text-align:center;color:#94a3b8">Nenhuma compra recente encontrada.</div>';
        return;
      }
      list.innerHTML = data.cards.map(c => this.renderOrderCard(c)).join("");
    } catch(e) {
      list.innerHTML = '<div style="padding:20px;text-align:center;color:#ef4444">Erro ao carregar compras recentes.</div>';
    }
  },

  currentSupplierLetter: "TODOS",
  supplierQuery: "",
  allSuppliersCache: null,
  totalSuppliersCadastrados: 0,

  renderSupplierLettersBar() {
    const bar = document.getElementById("supplierLettersBar");
    if (!bar) return;
    const letters = ["TODOS", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z"];
    bar.innerHTML = letters.map(l => `
      <button class="letter-pill ${this.currentSupplierLetter === l ? 'active' : ''}" onclick="app.selectSupplierLetter('${l}')">${l}</button>
    `).join("");
  },

  selectSupplierLetter(l) {
    this.currentSupplierLetter = l;
    this.renderSupplierLettersBar();
    this.renderSuppliersList();
  },

  filterSuppliers(val) {
    this.supplierQuery = (val || "").trim();
    this.renderSuppliersList();
  },

  async loadSuppliers() {
    this.renderSupplierLettersBar();
    const list = document.getElementById("suppliersCards");
    
    if (!this.allSuppliersCache || this.allSuppliersCache.length === 0) {
      list.innerHTML = '<div style="padding:24px;text-align:center;color:#94a3b8">⏳ Carregando fornecedores homologados...</div>';
      try {
        const res = await fetch(`/api/suppliers?role=${this.currentUser.role}`);
        const data = await res.json();
        this.allSuppliersCache = data.suppliers || [];
        this.totalSuppliersCadastrados = this.allSuppliersCache.length;
      } catch(e) {
        list.innerHTML = '<div style="padding:20px;text-align:center;color:#ef4444">Erro ao carregar fornecedores.</div>';
        return;
      }
    }

    this.renderSuppliersList();
  },

  renderSuppliersList() {
    const list = document.getElementById("suppliersCards");
    if (!list) return;

    if (!this.allSuppliersCache) {
      this.loadSuppliers();
      return;
    }

    let filtered = this.allSuppliersCache;

    if (this.currentSupplierLetter && this.currentSupplierLetter !== "TODOS") {
      const l = this.currentSupplierLetter.toUpperCase();
      filtered = filtered.filter(s => (s.razao_social || "").toUpperCase().startsWith(l));
    }

    if (this.supplierQuery) {
      const q = this.supplierQuery.toLowerCase();
      filtered = filtered.filter(s => {
        const r = (s.razao_social || "").toLowerCase();
        const v = (s.vendedor?.nome || "").toLowerCase();
        const e = (s.empresa?.email || "").toLowerCase();
        return r.includes(q) || v.includes(q) || e.includes(q);
      });
    }

    const metricsElem = document.getElementById("supplierMetrics");
    if (metricsElem) {
      metricsElem.innerHTML = `📋 <b>${filtered.length}</b> de <b>${this.totalSuppliersCadastrados}</b> fornecedores homologados`;
    }

    if (filtered.length === 0) {
      list.innerHTML = '<div style="padding:24px;text-align:center;color:#94a3b8">Nenhum fornecedor localizado com este filtro.</div>';
      return;
    }

    list.innerHTML = filtered.map(s => {
      const v = s.vendedor || {};
      const emp = s.empresa || {};
      
      return `
        <div class="supplier-card">
          <div class="sup-name">${s.razao_social}</div>
          
          <!-- BLOCO 1: VENDEDOR DIRETO -->
          <div class="contact-sub-box">
            <div class="contact-box-header">👤 <b>Vendedor Responsável:</b> ${v.nome || 'Atendimento Comercial'}</div>
            ${v.telefone ? `<div class="contact-box-line">📱 Celular: <b>${v.telefone}</b></div>` : ''}
            <div class="sup-actions">
              ${v.telefone_clean ? `<button onclick="app.promptCall('${v.nome || 'Vendedor'}', '${v.telefone || v.telefone_clean}')" class="btn-call" style="border:none;cursor:pointer;">📞 Ligar Vendedor</button>` : ''}
              ${v.telefone_clean ? `<a href="https://wa.me/55${v.telefone_clean}?text=Ol%C3%A1%20${encodeURIComponent(v.nome || '')}%2C%20sou%20da%20obra%20Residencial%20Maison%20Plage..." target="_blank" class="btn-wpp">💬 WhatsApp</a>` : ''}
            </div>
          </div>

          <!-- BLOCO 2: CENTRAL DA EMPRESA -->
          ${(emp.telefone || emp.email) ? `
            <div class="contact-sub-box" style="margin-top:8px;background:rgba(255,255,255,0.02);">
              <div class="contact-box-header">🏢 <b>Central da Empresa / Loja</b></div>
              ${emp.telefone ? `<div class="contact-box-line">☎️ Fixo / Central: <b>${emp.telefone}</b></div>` : ''}
              ${emp.email ? `<div class="contact-box-line">✉️ E-mail: <b>${emp.email}</b></div>` : ''}
              <div class="sup-actions">
                ${emp.telefone_clean ? `<button onclick="app.promptCall('Central da Empresa', '${emp.telefone || emp.telefone_clean}')" class="btn-call" style="background:#475569;border:none;cursor:pointer;">☎️ Ligar Loja</button>` : ''}
                ${emp.email ? `<a href="mailto:${emp.email}?subject=Residencial%20Maison%20Plage%20-%20Consulta" class="btn-mail">✉️ Enviar E-mail</a>` : ''}
              </div>
            </div>
          ` : ''}

        </div>
      `;
    }).join("");
  },

  async loadFinancial() {
    const box = document.getElementById("financialBox");
    box.innerHTML = '<div style="padding:30px;text-align:center;color:#94a3b8">⏳ Calculando previsão do fluxo financeiro...</div>';
    
    try {
      const res = await fetch(`/api/financial/summary?role=${this.currentUser.role}`);
      const data = await res.json();
      
      const kpis = data.kpis || {};
      const bars = data.monthly_bars || [];
      const groups = data.macro_groups || [];

      const fmtKpi = (valStr) => {
        const num = parseFloat((valStr || '').replace('R$', '').replace(/\./g, '').replace(',', '.')) || 0;
        if (num >= 1000000) return `R$ ${(num / 1000000).toFixed(2).replace('.', ',')}M`;
        if (num >= 1000) return `R$ ${(num / 1000).toFixed(1).replace('.', ',')}k`;
        return valStr || 'R$ 0';
      };

      box.innerHTML = `
        <!-- 1. CARD HERO PRINCIPAL: PREVISÃO TOTAL DE DESEMBOLSO -->
        <div class="fin-hero-card">
          <div class="fin-hero-head">
            <span class="fin-hero-label">💰 TOTAL DESEMBOLSO PROJETADO</span>
            <span class="fin-hero-badge">${kpis.periodo_label || 'Jun-Nov/26'}</span>
          </div>
          <div class="fin-hero-val">${kpis.total_desembolso || 'R$ 0,00'}</div>
          <div class="fin-hero-sub">Projeção calculada pelas condições de parcelamento (30/60/90 dias)</div>
        </div>

        <!-- 2. DUPLA DE CARDS SECUNDÁRIOS COMPACTOS -->
        <div class="fin-dual-grid">
          <div class="fin-sub-card border-gold">
            <div class="fin-sub-label">🟡 ${kpis.mes_atual_nome || 'Agosto'} (Mês Vigente)</div>
            <div class="fin-sub-val" style="color:#fbbf24;">${kpis.mes_atual}</div>
            <div class="fin-sub-pct">41.2% do fluxo total</div>
          </div>
          <div class="fin-sub-card border-green">
            <div class="fin-sub-label">⏳ A Realizar (Futuro)</div>
            <div class="fin-sub-val" style="color:#34d399;">${kpis.futuro}</div>
            <div class="fin-sub-pct">36.2% (Set a Nov)</div>
          </div>
        </div>

        <!-- 3. CRONOGRAMA DE DESEMBOLSO POR MÊS DE VENCIMENTO -->
        <div class="fin-section-box">
          <div class="fin-section-header">
            <div class="fin-section-title">📊 Desembolso por Mês de Vencimento</div>
            <div style="font-size:9.5px;color:#94a3b8;font-weight:700;background:rgba(255,255,255,0.06);padding:2px 6px;border-radius:4px;">Base: Vencimentos</div>
          </div>
          
          <div style="display:flex;flex-direction:column;gap:8px;padding-top:4px;">
            ${bars.map(b => {
              const isPast = b.mes_num < 8;
              const statusTag = b.is_current ? '⭐ Mês Atual' : (isPast ? 'Realizado' : 'Futuro');
              const barColor = b.is_current ? 'linear-gradient(90deg, #f59e0b, #fbbf24)' : (isPast ? '#10b981' : '#3b82f6');
              const textHighlight = b.is_current ? 'color:#fbbf24;font-weight:900;' : 'color:#e2e8f0;';
              
              return `
                <div style="${b.is_current ? 'background:rgba(251,191,36,0.08);border:1px solid rgba(251,191,36,0.25);border-radius:8px;padding:6px 8px;' : ''}">
                  <div style="display:flex;justify-content:space-between;align-items:center;font-size:11px;font-weight:700;margin-bottom:3px;">
                    <span style="${textHighlight}">
                      ${b.mes_nome}/2026 <span style="font-size:9px;font-weight:600;color:${b.is_current ? '#fbbf24' : (isPast ? '#10b981' : '#60a5fa')};">(${statusTag})</span>
                    </span>
                    <span style="color:#fff;font-weight:800;">
                      ${b.valor_fmt} <span style="font-size:9.5px;color:#94a3b8;font-weight:600;">(${b.pct}%)</span>
                    </span>
                  </div>
                  <div style="background:rgba(255,255,255,0.06);height:6px;border-radius:3px;overflow:hidden;width:100%;">
                    <div style="height:100%;border-radius:3px;width:${Math.max(b.pct, 2)}%;background:${barColor};"></div>
                  </div>
                </div>
              `;
            }).join("")}
          </div>
        </div>

        <!-- 4. DISTRIBUIÇÃO POR MACRO-GRUPOS DA OBRA -->
        <div class="fin-section-box">
          <div class="fin-section-header">
            <div class="fin-section-title">🏢 Investimento por Macro-Grupos</div>
            <div style="font-size:10.5px;color:#60a5fa;font-weight:800;">${kpis.total_contratado || ''}</div>
          </div>
          
          <!-- Barra Multi-Cor Segmentada Unificada (100% do Orçamento) -->
          <div class="macro-stacked-bar">
            ${groups.map(g => `
              <div class="macro-segment" style="width:${g.pct}%;background:${g.color};" title="${g.name}: ${g.pct}% (${g.valor_fmt})"></div>
            `).join("")}
          </div>

          <!-- Linhas de Macro-Grupos Claras e Enquadradas -->
          <div style="display:flex;flex-direction:column;gap:6px;padding-top:4px;">
            ${groups.map(g => `
              <div class="macro-row-compact">
                <div class="macro-row-head">
                  <span class="macro-row-title">
                    <span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${g.color};flex-shrink:0;"></span>
                    <span>${g.icon} ${g.name}</span>
                  </span>
                  <span class="macro-row-val">${g.valor_fmt} <span style="color:#94a3b8;font-weight:600;font-size:9.5px;">(${g.pct}%)</span></span>
                </div>
                <div class="macro-row-track">
                  <div class="macro-row-fill" style="width:${g.pct}%;background:${g.color};"></div>
                </div>
              </div>
            `).join("")}
          </div>
        </div>
      `;

    } catch(e) {
      box.innerHTML = '<div style="padding:20px;text-align:center;color:#ef4444">Erro ao carregar previsão financeira.</div>';
    }
  },

  async downloadExcel() {
    const url = `/api/export/excel?role=${this.currentUser.role}`;
    
    // Tenta abrir em nova aba primeiro (padrão iOS)
    const win = window.open(url, '_blank');
    if (!win) {
      window.location.href = url;
    }
  },

  currentPdfUrl: "",
  currentPdfName: "",

  viewPdf(pc) {
    const url = `/api/order/${pc}/pdf?role=${this.currentUser.role}`;
    this.currentPdfUrl = url;
    this.currentPdfName = `PC_${pc}.pdf`;

    document.getElementById("pdfViewerTitle").innerText = `Pedido PC ${pc}`;
    document.getElementById("pdfViewerSub").innerText = `Documento Oficial Sienge`;
    document.getElementById("pdfFrame").src = url;
    document.getElementById("pdfViewerModal").classList.add("show");
  },

  closePdfViewer() {
    document.getElementById("pdfViewerModal").classList.remove("show");
    document.getElementById("pdfFrame").src = "";
  },

  async sharePdf() {
    if (!this.currentPdfUrl) return;
    try {
      if (navigator.share) {
        const res = await fetch(this.currentPdfUrl);
        const blob = await res.blob();
        const file = new File([blob], this.currentPdfName, { type: "application/pdf" });
        await navigator.share({
          files: [file],
          title: this.currentPdfName,
          text: `Segue PDF do ${this.currentPdfName} da obra Maison Plage`
        });
      } else {
        window.open(this.currentPdfUrl, '_blank');
      }
    } catch(e) {
      window.open(this.currentPdfUrl, '_blank');
    }
  },

  excelDataCache: null,

  loadExcelViewer() {
    // Aba agora exibe os Cards Especializados de Planilhas
  },

  currentCallTarget: "",

  promptCall(name, number) {
    this.currentCallTarget = name;
    document.getElementById("callModalContactName").innerText = name;
    document.getElementById("callPhoneInput").value = number;
    document.getElementById("callModal").classList.add("show");
    setTimeout(() => {
      document.getElementById("callPhoneInput").focus();
    }, 150);
  },

  closeCallModal(e) {
    if (e && e.target && e.target.id !== "callModal" && !e.target.classList.contains("btn-close")) return;
    document.getElementById("callModal").classList.remove("show");
  },

  confirmCall() {
    const rawVal = document.getElementById("callPhoneInput").value;
    const cleanNum = rawVal.replace(/[^0-9+]/g, '');
    if (!cleanNum) {
      alert("Por favor, digite um número válido para discar.");
      return;
    }
    document.getElementById("callModal").classList.remove("show");
    window.location.href = `tel:${cleanNum}`;
  },

  async shareOrderPdf(pc) {
    const url = `/api/order/${pc}/pdf?role=${this.currentUser.role}`;
    const filename = `PedidoCompra_${pc}.pdf`;
    try {
      if (navigator.share) {
        const res = await fetch(url);
        if (!res.ok) throw new Error("Falha ao baixar PDF");
        const blob = await res.blob();
        const file = new File([blob], filename, { type: "application/pdf" });
        await navigator.share({
          files: [file],
          title: `Pedido PC ${pc} - Maison Plage`,
          text: `Segue o pedido de compra PC ${pc} da obra Residencial Maison Plage.`
        });
      } else {
        window.open(url, '_blank');
      }
    } catch(e) {
      if (e.name !== "AbortError") {
        window.open(url, '_blank');
      }
    }
  },

  async loadTeam() {
    const list = document.getElementById("collaboratorsList") || document.getElementById("teamList");
    if (!list) return;
    list.innerHTML = '<div style="padding:20px;text-align:center;color:#94a3b8">⏳ Carregando acessos ativos...</div>';

    try {
      const res = await fetch(`/api/collaborators?role=${this.currentUser.role}`);
      const data = await res.json();
      const collabs = data.collaborators || [];

      if (collabs.length === 0) {
        list.innerHTML = '<div style="padding:20px;text-align:center;color:#94a3b8">Nenhum colaborador com acesso no momento.<br><br>Clique em <b>"➕ Gerar Acesso WhatsApp"</b> acima para enviar o primeiro link.</div>';
        return;
      }

      list.innerHTML = collabs.map(c => {
        const isRevoked = c.status === "revoked";
        const roleLabel = {
          'engenharia': '🏗️ Engenharia',
          'administracao': '📦 Administração',
          'campo': '👷 Campo'
        }[c.role] || c.role;

        const roleColor = {
          'engenharia': '#60a5fa',
          'administracao': '#c084fc',
          'campo': '#fbbf24'
        }[c.role] || '#94a3b8';

        const waText = encodeURIComponent(`Olá ${c.nome}, seu link de acesso exclusivo ao App de Pedidos da obra Maison Plage está ativo:\n${c.link}`);

        return `
          <div class="user-card" style="${isRevoked ? 'opacity:0.55;border-left:4px solid #ef4444;' : 'border-left:4px solid ' + roleColor + ';'}">
            <div style="flex:1;">
              <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                <span class="user-meta-name" style="font-size:13.5px;color:#fff;">${c.nome}</span>
                <span style="font-size:10px;font-weight:800;color:${roleColor};background:rgba(255,255,255,0.06);padding:2px 6px;border-radius:4px;">
                  ${roleLabel}
                </span>
                ${isRevoked ? '<span style="font-size:10px;font-weight:800;color:#ef4444;background:rgba(239,68,68,0.15);padding:2px 6px;border-radius:4px;">Revogado</span>' : ''}
              </div>
              <div class="user-meta-role" style="font-size:11px;margin-top:3px;color:#94a3b8;">
                Criado em: ${c.created_at} • Último login: <b>${c.last_login}</b>
              </div>
            </div>

            <div class="user-actions" style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-top:8px;">
              <select class="role-select" style="font-size:11px;padding:4px 6px;border-radius:6px;background:var(--surface);" onchange="app.updateCollabRole('${c.token}', this.value)" ${isRevoked ? 'disabled' : ''}>
                <option value="engenharia" ${c.role==='engenharia'?'selected':''}>🏗️ Eng</option>
                <option value="administracao" ${c.role==='administracao'?'selected':''}>📦 Adm</option>
                <option value="campo" ${c.role==='campo'?'selected':''}>👷 Campo</option>
              </select>

              <button class="btn-pdf-action" onclick="app.copyText('${c.link}')" style="margin-top:0;padding:5px 9px;font-size:11px;background:#334155;border:none;cursor:pointer;border-radius:6px;" title="Copiar link">
                📋 Copiar
              </button>

              <a href="https://wa.me/?text=${waText}" target="_blank" class="btn-pdf-action" style="margin-top:0;padding:5px 9px;font-size:11px;background:#10b981;text-decoration:none;border-radius:6px;" title="Enviar no WhatsApp">
                💬 WhatsApp
              </a>

              ${!isRevoked ? `
                <button class="btn-del-user" onclick="app.revokeCollab('${c.token}')" style="padding:5px 9px;font-size:11px;border-radius:6px;" title="Revogar Acesso">
                  ✕ Revogar
                </button>
              ` : `
                <button class="btn-del-user" onclick="app.deleteCollab('${c.token}')" style="padding:5px 9px;font-size:11px;background:#b91c1c;border-radius:6px;" title="Excluir Definitivamente">
                  🗑️ Excluir
                </button>
              `}
            </div>
          </div>
        `;
      }).join("");

    } catch(e) {
      list.innerHTML = '<div style="padding:20px;text-align:center;color:#ef4444">Erro ao carregar colaboradores.</div>';
    }
  },

  openNewCollaboratorModal() {
    document.getElementById("collabFormSection").style.display = "flex";
    document.getElementById("collabResultSection").style.display = "none";
    document.getElementById("collabNameInput").value = "";
    document.getElementById("collabPhoneInput").value = "";
    document.getElementById("collaboratorModal").classList.add("show");
    document.body.style.overflow = "hidden";
  },

  closeCollaboratorModal(e) {
    if (e && e.target && e.target.id !== "collaboratorModal" && !e.target.classList.contains("btn-close")) return;
    document.getElementById("collaboratorModal").classList.remove("show");
    document.body.style.overflow = "";
  },

  async submitNewCollaborator() {
    const nome = document.getElementById("collabNameInput").value.trim();
    const role = document.getElementById("collabRoleSelect").value;
    const phone = document.getElementById("collabPhoneInput").value.trim();

    if (!nome) {
      alert("Por favor, digite o nome do colaborador.");
      return;
    }

    try {
      const res = await fetch(`/api/collaborators/create?role=${this.currentUser.role}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nome: nome, role: role, whatsapp: phone })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        document.getElementById("collabFormSection").style.display = "none";
        document.getElementById("collabResultSection").style.display = "block";
        document.getElementById("collabResultDesc").innerText = `Acesso permanente liberado para ${data.nome} (${data.role.toUpperCase()}).`;
        document.getElementById("collabGeneratedLink").value = data.link;

        const waBtn = document.getElementById("collabWhatsAppBtn");
        if (data.whatsapp_url) {
          waBtn.href = data.whatsapp_url;
        } else {
          waBtn.href = `https://wa.me/?text=${encodeURIComponent(data.message)}`;
        }

        this.loadTeam();
      } else {
        alert(data.detail || "Erro ao criar colaborador.");
      }
    } catch(e) {
      alert("Erro ao conectar com o servidor.");
    }
  },

  copyCollabLink() {
    const input = document.getElementById("collabGeneratedLink");
    if (!input) return;
    input.select();
    navigator.clipboard.writeText(input.value).then(() => {
      alert("📋 Link de acesso copiado com sucesso!");
    }).catch(() => {
      document.execCommand("copy");
      alert("📋 Link de acesso copiado!");
    });
  },

  copyText(txt) {
    navigator.clipboard.writeText(txt).then(() => {
      alert("📋 Link copiado com sucesso!");
    }).catch(() => {
      alert("Link: " + txt);
    });
  },

  async updateCollabRole(token, newRole) {
    try {
      const res = await fetch(`/api/collaborators/update_role?role=${this.currentUser.role}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: token, role: newRole })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        this.loadTeam();
      } else {
        alert(data.detail || "Erro ao atualizar perfil.");
      }
    } catch(e) {
      alert("Erro ao atualizar perfil.");
    }
  },

  async revokeCollab(token) {
    if (!confirm("Tem certeza que deseja revogar o acesso deste colaborador? Ele não conseguirá mais abrir o app.")) return;
    try {
      const res = await fetch(`/api/collaborators/revoke?role=${this.currentUser.role}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: token })
      });
      const data = await res.json();
      if (res.ok && data.success) {
        this.loadTeam();
      } else {
        alert(data.detail || "Erro ao revogar acesso.");
      }
    } catch(e) {
      alert("Erro ao revogar acesso.");
    }
  },

  async deleteCollab(token) {
    if (!confirm("Excluir definitivamente este registro da lista?")) return;
    try {
      const res = await fetch(`/api/collaborators/${token}?role=${this.currentUser.role}`, {
        method: 'DELETE'
      });
      const data = await res.json();
      if (res.ok && data.success) {
        this.loadTeam();
      } else {
        alert(data.detail || "Erro ao excluir.");
      }
    } catch(e) {
      alert("Erro ao excluir.");
    }
  }
};

window.onload = () => app.init();
