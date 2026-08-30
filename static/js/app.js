
const app = {
  currentPin: "",
  currentUser: null,
  activeModule: "week",
  clientTabCache: { loaded: {} },
  orderDetailCache: {},
  weekOffset: 0,
  currentMonth: 8,

  init() {
    // 1. Verifica convite na URL
    const urlParams = new URLSearchParams(window.location.search);
    const inviteToken = urlParams.get('convite') || urlParams.get('invite');
    if (inviteToken) {
      this.handleInviteEntry(inviteToken);
      return;
    }
    
    // 2. Verifica usuário autenticado salvo
    const savedUser = localStorage.getItem("mp_auth_user");
    if (savedUser) {
      try {
        this.currentUser = JSON.parse(savedUser);
        this.showApp();
        return;
      } catch(e) {
        localStorage.removeItem("mp_auth_user");
      }
    }

    // 3. Verifica se há solicitação pendente
    const savedReq = localStorage.getItem("mp_pending_req_id");
    if (savedReq) {
      this.showPendingInviteScreen(savedReq);
      return;
    }

    // 4. Exibe tela de login padrão
    this.showLogin();

    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sw.js');
    }
  },

  pressPin(n) {
    if (this.currentPin.length < 4) {
      this.currentPin += n;
      this.updatePinDots();
      if (this.currentPin.length === 4) {
        setTimeout(() => this.submitPin(), 100);
      }
    }
  },

  clearPin() {
    this.currentPin = "";
    this.updatePinDots();
  },

  updatePinDots() {
    for (let i = 1; i <= 4; i++) {
      const el = document.getElementById(`dot${i}`);
      if (i <= this.currentPin.length) el.classList.add("filled");
      else el.classList.remove("filled");
    }
  },

  quickLogin(role) {
    const pins = {
      admin: "8459",
      engenharia: "7722",
      administracao: "4411",
      campo: "1003"
    };
    this.currentPin = pins[role] || "0421";
    this.submitPin();
  },

  async submitNativePin() {

    const pinInput = document.getElementById("nativePinInput");
    const btn = document.getElementById("btnEnterApp");
    if (!pinInput) return;
    const pin = pinInput.value.trim();
    if (pin.length !== 4) {
      alert("Por favor, digite seu PIN de 4 dígitos.");
      return;
    }
    if (btn) {
      btn.innerText = "⏳ Entrando...";
      btn.style.opacity = "0.7";
    }
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin: pin })
      });
      const data = await res.json();
      if (data.success) {
        this.currentUser = data.user;
        localStorage.setItem("mp_auth_user", JSON.stringify(data.user));
        this.showApp();
      } else {
        alert(data.detail || "PIN incorreto.");
        pinInput.value = "";
        if (btn) {
          btn.innerText = "➔ Entrar no App";
          btn.style.opacity = "1";
        }
      }
    } catch(e) {
      alert("Erro ao validar PIN.");
      if (btn) {
        btn.innerText = "➔ Entrar no App";
        btn.style.opacity = "1";
      }
    }
  },

  async submitPin() {
    await this.submitNativePin();
  },

  pressPin(n) {},
  clearPin() {
    const el = document.getElementById("nativePinInput");
    if (el) el.value = "";
  },

  logout() {
    localStorage.removeItem("mp_auth_user");
    this.currentUser = null;
    this.clearPin();
    this.showLogin();
  },

  showLogin() {
    document.getElementById("loginScreen").style.display = "flex";
    document.getElementById("appContainer").style.display = "none";
  },

  showApp() {
    document.getElementById("loginScreen").style.display = "none";
    document.getElementById("appContainer").style.display = "block";
    
    document.getElementById("userGreeting").innerText = `Olá, ${this.currentUser.nome.split(" ")[0]}`;
    const roleLabels = { admin: "👑 Admin Master", engenharia: "🏗️ Engenharia", administracao: "📦 Administração", campo: "👷 Campo" };
    document.getElementById("roleTag").innerText = roleLabels[this.currentUser.role] || "👷 Campo";

    // Permissões das abas
    const role = this.currentUser.role;
    document.getElementById("tabSuppliers").style.display = (role === "campo") ? "none" : "block";
    document.getElementById("tabFinancial").style.display = (role === "admin" || role === "engenharia") ? "block" : "none";
    document.getElementById("tabExport").style.display = (role === "admin" || role === "engenharia") ? "block" : "none";
    document.getElementById("tabTeam").style.display = (role === "admin") ? "block" : "none";

    this.setModule("week");
  },

  setModule(mod) {
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

    if (mod === "week") this.loadWeek();
    if (mod === "month") this.loadMonth();
    if (mod === "search") this.loadCatalogAZ();
    if (mod === "groups") this.loadGroups();
    if (mod === "recent") this.loadRecent();
    if (mod === "suppliers") this.loadSuppliers();
    if (mod === "financial") this.loadFinancial();
    if (mod === "team") this.loadTeam();
    if (mod === "excel") this.loadExcelViewer();
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
    // Se já estiver em cache, renderiza imediatamente sem delay
    if (this.orderDetailCache[pc]) {
      this.renderOrderModal(this.orderDetailCache[pc]);
      return;
    }

    try {
      const res = await fetch(`/api/order/${pc}?role=${this.currentUser.role}`);
      const data = await res.json();
      this.orderDetailCache[pc] = data;
      this.renderOrderModal(data);
    } catch(e) {
      alert("Erro ao abrir detalhes do pedido.");
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
      ${contactHtml}
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
    document.getElementById("orderModal").classList.remove("show"); document.body.style.overflow = "";
  },

  currentLetter: "TODOS",
  catalogQuery: "",

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
    this.loadCatalogAZ();
  },

  filterCatalog(val) {
    this.catalogQuery = val.trim();
    clearTimeout(this.filterCatalogTimer);
    this.filterCatalogTimer = setTimeout(() => {
      this.loadCatalogAZ();
    }, 250);
  },

  async loadCatalogAZ() {

    this.renderLettersBar();
    const list = document.getElementById("materialsLeanList");
    list.innerHTML = '<div style="padding:24px;text-align:center;color:#94a3b8">⏳ Carregando insumos...</div>';
    
    try {
      const qP = this.catalogQuery ? `&q=${encodeURIComponent(this.catalogQuery)}` : '';
      const letP = this.currentLetter ? `&letter=${encodeURIComponent(this.currentLetter)}` : '';
      const res = await fetch(`/api/materials/catalog?role=${this.currentUser.role}${qP}${letP}`);
      const data = await res.json();
      
      document.getElementById("catalogMetrics").innerHTML = `📋 <b>${data.total_filtrados}</b> de <b>${data.total_cadastrados}</b> insumos cadastrados`;

      if (!data.insumos || data.insumos.length === 0) {
        list.innerHTML = '<div style="padding:24px;text-align:center;color:#94a3b8">Nenhum insumo localizado com este filtro.</div>';
        return;
      }

      list.innerHTML = data.insumos.map(m => `
        <div class="material-lean-row" onclick="app.openMaterialOrders('${encodeURIComponent(m.nome)}')">
          <div class="mat-lean-name">${m.nome}</div>
          <div class="mat-lean-badge">${m.qtd_formatada} • ${m.pedidos_count} PC</div>
        </div>
      `).join("");

    } catch(e) {
      list.innerHTML = '<div style="padding:20px;text-align:center;color:#ef4444">Erro ao carregar catálogo de insumos.</div>';
    }
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
    grid.innerHTML = '<div style="grid-column:span 2;padding:20px;text-align:center;color:#94a3b8">⏳ Carregando Macro-Grupos da obra...</div>';
    try {
      const res = await fetch('/api/groups');
      const data = await res.json();
      
      const macroMap = {
        "🏗️ Obra Grossa & Estrutura": ["BLOCOS", "PRODUTOS METÁLICOS", "AGREGADOS", "ARGAMASSAS", "MADEIRAS", "PRÉ-MOLDADOS", "ESTRUTURA"],
        "⚡ Instalações Prediais": ["ELÉTRICAS", "HIDRÁULICAS", "INCÊNDIO", "GÁS", "TUBOS", "CONEXÕES", "FIAÇÃO"],
        "🛡️ Acabamentos & Pintura": ["IMPERMEABILIZANTES", "TINTAS", "VERNIZES", "LOUÇAS", "METAIS", "PAVIMENTAÇÃO", "DRENAGEM"],
        "🦺 Segurança, EPIs & Apoio": ["EPI", "EPC", "FERRAMENTAS", "EQUIPAMENTOS", "AUXILIARES", "LIMPEZA", "EXPEDIENTE"],
        "🚜 Serviços & Esquadrias": ["ESQUADRIAS", "VIDROS", "SERVIÇOS", "LOCAÇÃO", "MÁQUINAS", "EMPREITADOS", "DIVERSOS"]
      };

      const groups = data.groups || [];
      const macroCards = [];

      for (const [macroName, keywords] of Object.entries(macroMap)) {
        const subList = groups.filter(g => keywords.some(k => g.familia.toUpperCase().includes(k)));
        const totOrders = subList.reduce((acc, curr) => acc + (curr.orders_count || 0), 0);
        const totItems = subList.reduce((acc, curr) => acc + (curr.items_count || 0), 0);

        macroCards.push({
          title: macroName,
          orders: totOrders,
          items: totItems,
          subs: subList
        });
      }

      grid.innerHTML = macroCards.map((m, idx) => `
        <div class="macro-group-card" onclick="app.toggleMacro(${idx})">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <div class="macro-title">${m.title}</div>
            <div class="macro-badge">${m.orders} pedidos</div>
          </div>
          <div class="macro-sub-info">📦 ${m.items} itens cadastrados • ${m.subs.length} subfamílias</div>
          <div id="macroSubs_${idx}" class="macro-subs-container" style="display:none;margin-top:12px;border-top:1px solid rgba(255,255,255,0.08);padding-top:10px;">
            ${m.subs.map(s => `
              <div class="macro-sub-item" onclick="event.stopPropagation(); app.openGroupOrders('${s.familia}')">
                <span>📁 ${s.familia}</span>
                <span style="color:#60a5fa;font-weight:700">${s.orders_count} peds</span>
              </div>
            `).join("")}
          </div>
        </div>
      `).join("");

    } catch(e) {
      grid.innerHTML = '<div style="grid-column:span 2;padding:20px;text-align:center;color:#ef4444">Erro ao carregar grupos.</div>';
    }
  },

  toggleMacro(idx) {
    const el = document.getElementById(`macroSubs_${idx}`);
    if (el) {
      el.style.display = (el.style.display === "none") ? "block" : "none";
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

  async loadSuppliers() {
    const list = document.getElementById("suppliersCards");
    list.innerHTML = '<div style="padding:20px;text-align:center;color:#94a3b8">⏳ Carregando contatos estruturados...</div>';
    try {
      const res = await fetch(`/api/suppliers?role=${this.currentUser.role}`);
      const data = await res.json();
      list.innerHTML = data.suppliers.map(s => {
        const v = s.vendedor || {};
        const emp = s.empresa || {};
        
        return `
          <div class="supplier-card">
            <div class="sup-name">${s.razao_social}</div>
            
            <!-- BLOCO 1: VENDEDOR DIRETO -->
            <div class="contact-sub-box">
              <div class="contact-box-header">👤 <b>Vendedor Responsável:</b> ${v.nome}</div>
              ${v.telefone ? `<div class="contact-box-line">📱 Celular: <b>${v.telefone}</b></div>` : ''}
              <div class="sup-actions">
                ${v.telefone_clean ? `<button onclick="app.promptCall('${v.nome || 'Vendedor'}', '${v.telefone || v.telefone_clean}')" class="btn-call" style="border:none;cursor:pointer;">📞 Ligar Vendedor</button>` : ''}
                ${v.telefone_clean ? `<a href="https://wa.me/55${v.telefone_clean}?text=Ol%C3%A1%20${encodeURIComponent(v.nome)}%2C%20sou%20da%20obra%20Residencial%20Maison%20Plage..." target="_blank" class="btn-wpp">💬 WhatsApp</a>` : ''}
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
    } catch(e) {
      list.innerHTML = '<div style="padding:20px;text-align:center;color:#ef4444">Erro ao carregar fornecedores.</div>';
    }
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

      box.innerHTML = `
        <!-- 1. CARDS DE INDICADORES (KPIS DE PREVISÃO) -->
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px;">
          <div class="fin-kpi-card" style="grid-column:span 2;border-left:4px solid #3b82f6;padding:10px 14px;">
            <div class="fin-kpi-label" style="font-size:11px;">💰 Previsão Total de Desembolso (Jul a Dez/26)</div>
            <div class="fin-kpi-value" style="color:#60a5fa;font-size:20px;">${kpis.total_desembolso}</div>
          </div>
          <div class="fin-kpi-card" style="border-left:4px solid #f59e0b;padding:10px 14px;">
            <div class="fin-kpi-label" style="font-size:11px;">📅 Previsão em Agosto (Mês Atual)</div>
            <div class="fin-kpi-value" style="color:#fbbf24;font-size:17px;">${kpis.mes_atual}</div>
          </div>
          <div class="fin-kpi-card" style="border-left:4px solid #10b981;padding:10px 14px;">
            <div class="fin-kpi-label" style="font-size:11px;">⏳ Previsão Futura (Setembro+)</div>
            <div class="fin-kpi-value" style="color:#34d399;font-size:17px;">${kpis.futuro}</div>
          </div>
        </div>

        <!-- 2. PAINEL COMPACTO EM BARRAS HORIZONTAIS NEON (PINTADAS NO SAFARI/IOS) -->
        <div class="fin-section-box" style="padding:12px 14px;margin-bottom:12px;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
            <div class="fin-section-title" style="font-size:13px;">📈 Previsão de Desembolso Mensal</div>
            <div style="font-size:10px;color:#94a3b8;font-weight:700;background:rgba(255,255,255,0.06);padding:2px 6px;border-radius:4px;">Base: Entrega</div>
          </div>
          
          <div style="display:flex;flex-direction:column;gap:8px;">
            ${bars.map(b => `
              <div class="fin-compact-row ${b.is_current ? 'compact-current-row' : ''}">
                <div style="display:flex;justify-content:space-between;align-items:center;font-size:11px;font-weight:700;margin-bottom:4px;">
                  <span style="${b.is_current ? 'color:#fbbf24;font-size:12px;font-weight:800;' : 'color:#e2e8f0;'}">
                    ${b.is_current ? '🟡 ' : '🟢 '}${b.mes_nome}/2026${b.is_current ? ' ⭐ (Mês Atual)' : ''}
                  </span>
                  <span style="${b.is_current ? 'color:#fbbf24;font-weight:800;' : 'color:#10b981;font-weight:700;'}">
                    ${b.valor_fmt} <span style="color:#94a3b8;font-size:10px;font-weight:500;">(${b.pct}%)</span>
                  </span>
                </div>
                <div class="fin-compact-track">
                  <div class="fin-compact-fill ${b.is_current ? 'fill-gold' : 'fill-cyan'}" style="width:${Math.max(b.pct, 4)}%;"></div>
                </div>
              </div>
            `).join("")}
          </div>
        </div>

        <!-- 3. DISTRIBUIÇÃO POR MACRO-GRUPOS DA OBRA -->
        <div class="fin-section-box" style="padding:12px 14px;">
          <div class="fin-section-title" style="font-size:13px;">🏢 Onde está o Investimento da Obra (Macro-Grupos)</div>
          <div style="display:flex;flex-direction:column;gap:10px;margin-top:10px;">
            ${groups.map(g => `
              <div>
                <div style="display:flex;justify-content:space-between;font-size:11px;font-weight:700;margin-bottom:4px;">
                  <span>${g.icon} ${g.name}</span>
                  <span style="color:#fff;">${g.pct}% <span style="color:var(--text-muted);font-weight:400;font-size:10px;">(${g.valor_fmt})</span></span>
                </div>
                <div class="fin-progress-track" style="height:8px;">
                  <div class="fin-progress-fill" style="width:${g.pct}%;background:${g.color};height:8px;"></div>
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

  currentInviteToken: "",

  async handleInviteEntry(token) {
    this.currentInviteToken = token;
    document.getElementById("loginScreen").style.display = "none";
    document.getElementById("appContainer").style.display = "none";
    document.getElementById("inviteScreen").style.display = "flex";

    try {
      const res = await fetch(`/api/invites/validate?token=${token}`);
      const data = await res.json();
      if (data.valid) {
        document.getElementById("inviteValidBox").style.display = "block";
        document.getElementById("inviteExpiredBox").style.display = "none";
        document.getElementById("invitePendingBox").style.display = "none";
      } else {
        document.getElementById("inviteValidBox").style.display = "none";
        document.getElementById("inviteExpiredBox").style.display = "block";
        document.getElementById("invitePendingBox").style.display = "none";
      }
    } catch(e) {
      alert("Erro ao validar link de convite.");
    }
  },

  async submitInviteRegistration() {
    const nome = document.getElementById("invNomeInput").value.trim();
    const contato = document.getElementById("invContatoInput").value.trim();

    if (!nome || !contato) {
      alert("Por favor, preencha seu Nome Completo e Contato.");
      return;
    }

    try {
      const res = await fetch('/api/invites/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: this.currentInviteToken, nome: nome, contato: contato })
      });
      const data = await res.json();
      if (data.success) {
        localStorage.setItem("mp_pending_req_id", data.req_id);
        document.getElementById("inviteValidBox").style.display = "none";
        document.getElementById("invitePendingBox").style.display = "block";
      } else {
        alert(data.detail || "Erro ao enviar solicitação.");
      }
    } catch(e) {
      alert("Falha ao registrar convite.");
    }
  },

  showPendingInviteScreen(reqId) {
    document.getElementById("loginScreen").style.display = "none";
    document.getElementById("appContainer").style.display = "none";
    document.getElementById("inviteScreen").style.display = "flex";
    document.getElementById("inviteValidBox").style.display = "none";
    document.getElementById("inviteExpiredBox").style.display = "none";
    document.getElementById("invitePendingBox").style.display = "block";
  },

  async checkPendingStatus() {
    const reqId = localStorage.getItem("mp_pending_req_id");
    if (!reqId) {
      window.location.href = "/";
      return;
    }
    try {
      const res = await fetch(`/api/users/check_status?req_id=${reqId}`);
      const data = await res.json();
      if (data.status === "approved") {
        // Autentica e entra direto sem pedir senha
        const userObj = {
          id: reqId,
          nome: "Membro Autorizado",
          role: data.role || "engenharia",
          pin: data.pin
        };
        localStorage.setItem("mp_auth_user", JSON.stringify(userObj));
        localStorage.removeItem("mp_pending_req_id");
        this.currentUser = userObj;
        alert("🎉 Acesso Aprovado pelo Administrador Paulo!

Entrando diretamente no App da Obra...");
        this.showApp();
      } else if (data.status === "rejected") {
        alert("Sua solicitação de acesso não foi aprovada pelo Administrador.");
        localStorage.removeItem("mp_pending_req_id");
        window.location.href = "/";
      } else {
        alert("Sua solicitação ainda está em análise pelo Administrador Paulo. Aguarde a aprovação.");
      }
    } catch(e) {
      alert("Erro ao verificar status.");
    }
  },

  async openGenerateInviteModal() {
    try {
      const res = await fetch(`/api/invites/generate?role=${this.currentUser.role}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role_sugerido: "engenharia" })
      });
      const data = await res.json();
      document.getElementById("generatedInviteLinkInput").value = data.link;
      document.getElementById("inviteGeneratedModal").classList.add("show");
    } catch(e) {
      alert("Erro ao gerar link de convite.");
    }
  },

  closeInviteModal(e) {
    if (e && e.target && e.target.id !== "inviteGeneratedModal" && !e.target.classList.contains("btn-close")) return;
    document.getElementById("inviteGeneratedModal").classList.remove("show");
  },

  copyInviteLink() {
    const input = document.getElementById("generatedInviteLinkInput");
    input.select();
    input.setSelectionRange(0, 99999);
    navigator.clipboard.writeText(input.value);
    alert("✅ Link copiado para a área de transferência!");
  },

  shareInviteLink() {
    const link = document.getElementById("generatedInviteLinkInput").value;
    const txt = `Olá! Segue o link de acesso exclusivo para instalar e entrar no App de Pedidos da obra Residencial Maison Plage:

${link}`;
    window.open(`https://wa.me/?text=${encodeURIComponent(txt)}`, '_blank');
  },

  async loadTeam() {
    const list = document.getElementById("teamCards");
    list.innerHTML = '<div style="padding:20px;text-align:center;color:#94a3b8">Carregando membros da equipe...</div>';
    try {
      const res = await fetch(`/api/users?role=${this.currentUser.role}`);
      const data = await res.json();
      list.innerHTML = data.users.map(u => `
        <div class="user-card">
          <div>
            <div class="user-meta-name">${u.nome}</div>
            <div class="user-meta-role">PIN: <b>${u.pin}</b> • Cadastrado em: ${u.data_autorizacao}</div>
          </div>
          <div class="user-actions">
            <select class="role-select" onchange="app.updateUserRole('${u.id}', this.value)">
              <option value="campo" ${u.role==='campo'?'selected':''}>👷 Campo</option>
              <option value="administracao" ${u.role==='administracao'?'selected':''}>📦 Administração</option>
              <option value="engenharia" ${u.role==='engenharia'?'selected':''}>🏗️ Engenharia</option>
              <option value="admin" ${u.role==='admin'?'selected':''}>👑 Admin</option>
            </select>
            ${u.role !== 'admin' ? `<button class="btn-del-user" onclick="app.deleteUser('${u.id}')">✕</button>` : ''}
          </div>
        </div>
      `).join("");
    } catch(e) {
      list.innerHTML = '<div style="padding:20px;text-align:center;color:#ef4444">Erro ao carregar equipe.</div>';
    }
  },
};

window.onload = () => app.init();
