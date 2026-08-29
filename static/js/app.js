
const app = {
  currentPin: "",
  currentUser: null,
  activeModule: "week",
  weekOffset: 0,
  currentMonth: 8,

  init() {
    const saved = localStorage.getItem("mp_auth_user");
    if (saved) {
      this.currentUser = JSON.parse(saved);
      this.showApp();
    } else {
      this.showLogin();
    }

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

  async submitPin() {
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin: this.currentPin })
      });
      const data = await res.json();
      if (data.success) {
        this.currentUser = data.user;
        localStorage.setItem("mp_auth_user", JSON.stringify(data.user));
        this.showApp();
      } else {
        alert(data.detail || "PIN incorreto.");
        this.clearPin();
      }
    } catch(e) {
      alert("Erro ao validar PIN.");
      this.clearPin();
    }
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
    document.querySelectorAll(".month-pill").forEach((p, idx) => {
      if (idx + 1 === m) p.classList.add("active");
      else p.classList.remove("active");
    });
    this.loadMonth();
  },

  renderOrderCard(c) {
    return `
      <div class="item-card" onclick="app.openOrder('${c.pc}')">
        <div class="card-header-row">
          <span class="card-tag-pc">PC ${c.pc}</span>
          <span class="card-tag-date">🚚 ${c.data_entrega}</span>
        </div>
        <div class="card-supplier-name">${c.fornecedor}</div>
        <div class="card-summary-desc">${c.descricao_resumo} (+${c.total_itens - 1} itens)</div>
        <div class="card-footer-row">
          <span>📦 ${c.total_itens} ${c.total_itens > 1 ? 'itens' : 'item'}</span>
          ${c.valor_total_formatado ? `<span class="card-money-val">${c.valor_total_formatado}</span>` : ''}
        </div>
      </div>
    `;
  },

  async openOrder(pc) {
    try {
      const res = await fetch(`/api/order/${pc}?role=${this.currentUser.role}`);
      const data = await res.json();

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
      document.getElementById("orderModal").classList.add("show"); document.body.style.overflow = "hidden";
    } catch(e) {
      alert("Erro ao abrir detalhes do pedido.");
    }
  },

  closeModal() {
    document.getElementById("orderModal").classList.remove("show"); document.body.style.overflow = "";
  },

  async handleSearch(val) {
    const q = val.trim();
    document.getElementById("clearSearchBtn").style.display = q ? "block" : "none";
    if (q.length < 2) return;
    this.setModule("search");

    const list = document.getElementById("searchResults");
    list.innerHTML = '<div style="padding:20px;text-align:center;color:#94a3b8">🔍 Buscando insumos...</div>';

    try {
      const res = await fetch(`/api/materials/search?q=${encodeURIComponent(q)}&role=${this.currentUser.role}`);
      const data = await res.json();
      if (!data.results || data.results.length === 0) {
        list.innerHTML = `<div style="padding:20px;text-align:center;color:#94a3b8">Nenhum resultado para "${q}".</div>`;
        return;
      }
      list.innerHTML = data.results.map(c => `
        <div class="item-card" onclick="app.openOrder('${c.pc}')">
          <div class="card-header-row">
            <span class="card-tag-pc">PC ${c.pc}</span>
            <span class="card-tag-date">🚚 ${c.data_entrega}</span>
          </div>
          <div class="card-supplier-name">${c.fornecedor}</div>
          <div class="card-summary-desc">${c.matched_items.join("<br>")}</div>
        </div>
      `).join("");
    } catch(e) {
      list.innerHTML = '<div style="padding:20px;text-align:center;color:#ef4444">Erro na busca.</div>';
    }
  },

  quickSearch(t) {
    document.getElementById("searchInput").value = t;
    this.handleSearch(t);
  },

  clearSearch() {
    document.getElementById("searchInput").value = "";
    document.getElementById("clearSearchBtn").style.display = "none";
    document.getElementById("searchResults").innerHTML = "";
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
    this.setModule("search");
    document.getElementById("searchInput").value = fam;
    this.handleSearch(fam);
  },

  async loadRecent() {
    const list = document.getElementById("recentCards");
    list.innerHTML = '<div style="padding:20px;text-align:center;color:#94a3b8">Carregando compras recentes...</div>';
    try {
      const res = await fetch(`/api/orders/recent?role=${this.currentUser.role}`);
      const data = await res.json();
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
    box.innerHTML = '<div style="padding:20px;text-align:center;color:#94a3b8">Calculando cronograma de desembolso...</div>';
    try {
      const res = await fetch(`/api/financial/summary?role=${this.currentUser.role}`);
      const data = await res.json();
      box.innerText = data.summary_text;
    } catch(e) {
      box.innerText = "Erro ao calcular fluxo financeiro.";
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
  }, 300);
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

  async updateUserRole(uid, r) {
    try {
      await fetch('/api/users/update_role?role=admin', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: uid, role: r })
      });
      alert("Perfil do membro atualizado com sucesso!");
    } catch(e) {
      alert("Erro ao atualizar perfil.");
    }
  },

  async deleteUser(uid) {
    if (!confirm("Deseja realmente remover o acesso deste membro?")) return;
    try {
      await fetch(`/api/users/${uid}?role=admin`, { method: 'DELETE' });
      this.loadTeam();
    } catch(e) {
      alert("Erro ao remover usuário.");
    }
  },

  openAddUserModal() {
    document.getElementById("addUserModal").classList.add("show");
  },

  closeAddUserModal() {
    document.getElementById("addUserModal").classList.remove("show");
  },

  async saveNewUser() {
    const nome = document.getElementById("newUserName").value.trim();
    const pin = document.getElementById("newUserPin").value.trim();
    const role = document.getElementById("newUserRole").value;

    if (!nome || pin.length !== 4) {
      alert("Preencha o nome e um PIN de exatamente 4 dígitos.");
      return;
    }

    try {
      const res = await fetch('/api/users/add?role=admin', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ nome, pin, role })
      });
      const data = await res.json();
      if (data.success) {
        this.closeAddUserModal();
        this.loadTeam();
        alert("Novo membro cadastrado com sucesso!");
      }
    } catch(e) {
      alert("Erro ao salvar novo membro.");
    }
  }
};

window.onload = () => app.init();
