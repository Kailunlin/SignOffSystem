/* ═══════════════════════════════════════════════
   SignOff System — App Logic (Vanilla JS SPA)
   ═══════════════════════════════════════════════ */

const API_BASE = '';

/* ── State ── */
let state = {
  token: null,
  currentUserId: null,
  currentUser: null,
  bomAction: 'submit',
  transferAction: 'submit',
  currentDocType: null,
  currentDocId: null,
  pendingActionType: null,
};

/* ══════════════════════════════════════════════════════════════
   AUTH
══════════════════════════════════════════════════════════════ */
async function quickLogin(userId) {
  await doLogin(userId);
}

async function handleLogin(e) {
  e.preventDefault();
  const username = document.getElementById('username-input').value.trim();
  if (!username) return;
  await doLogin(username);
}

async function doLogin(username) {
  const errEl = document.getElementById('login-error');
  errEl.classList.add('hidden');
  
  // Show loading state on all quick buttons and submit button
  document.querySelectorAll('.quick-btn, .btn-primary').forEach(btn => btn.classList.add('loading'));

  try {
    const res = await fetch(`${API_BASE}/api/token/`, { 
      method: 'POST', 
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: username, password: 'password123' }) 
    });
    if (!res.ok) { 
      const d = await res.json(); 
      showLoginError(d.detail || '登入失敗'); 
      document.querySelectorAll('.quick-btn, .btn-primary').forEach(btn => btn.classList.remove('loading'));
      return; 
    }
    const data = await res.json();
    state.token = data.access;
    state.currentUserId = username;

    // Map known users for display
    const userMap = {
      'EMP_TPE': { name: '台北員工', position: '財務專員', site: '台北廠', site_code: 'TPE' },
      'EMP_TNN': { name: '台南員工', position: '生產專員', site: '台南廠', site_code: 'TNN' },
      'EMP_KHH': { name: '高雄員工', position: '倉管專員', site: '高雄廠', site_code: 'KHH' },
      'MGR_TPE': { name: '台北主管', position: '台北財務', site: '總公司', site_code: 'TPE' },
      'MGR_TNN': { name: '台南主管', position: '生產主管', site: '台南廠', site_code: 'TNN' },
      'MGR_KHH': { name: '高雄主管', position: '倉庫主管', site: '高雄廠', site_code: 'KHH' },
    };
    state.currentUser = userMap[username] || { name: username, position: '使用者', site: '', site_code: '' };

    document.getElementById('sidebar-username').textContent = state.currentUser.name;
    document.getElementById('sidebar-role').textContent = `${state.currentUser.position}・${state.currentUser.site}`;
    document.getElementById('sidebar-avatar').textContent = state.currentUser.name.charAt(0);

    const hour = new Date().getHours();
    const greeting = hour < 12 ? '早安' : hour < 18 ? '午安' : '晚安';
    document.getElementById('dashboard-greeting').textContent = `${greeting}，${state.currentUser.name}！歡迎回來`;

    document.getElementById('page-login').classList.add('hidden');
    document.getElementById('app-shell').classList.remove('hidden');
    
    // Remove loading
    document.querySelectorAll('.quick-btn, .btn-primary').forEach(btn => btn.classList.remove('loading'));

    navigate('dashboard');
  } catch (err) {
    showLoginError('連線錯誤，請確認後端伺服器是否已啟動。');
    document.querySelectorAll('.quick-btn, .btn-primary').forEach(btn => btn.classList.remove('loading'));
  }
}

function showLoginError(msg) {
  const el = document.getElementById('login-error');
  el.textContent = msg;
  el.classList.remove('hidden');
}

function logout() {
  state.token = null;
  state.currentUserId = null;
  state.currentUser = null;
  document.getElementById('app-shell').classList.add('hidden');
  document.getElementById('page-login').classList.remove('hidden');
  document.getElementById('username-input').value = '';
}

/* ══════════════════════════════════════════════════════════════
   NAVIGATION
══════════════════════════════════════════════════════════════ */
function navigate(page, el) {
  if (el) {
    document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
    el.classList.add('active');
  } else {
    document.querySelectorAll('.nav-item').forEach(i => {
      i.classList.toggle('active', i.dataset.page === page);
    });
  }

  document.querySelectorAll('.content-page').forEach(p => p.classList.add('hidden'));
  const target = document.getElementById(`page-${page}`);
  if (target) target.classList.remove('hidden');

  if (page === 'dashboard') loadDashboard();
  if (page === 'pending') loadPendingList();
  if (page === 'search') resetSearch();
}

/* ══════════════════════════════════════════════════════════════
   API HELPERS
══════════════════════════════════════════════════════════════ */
async function apiGet(path) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Authorization': `Bearer ${state.token}` }
  });
  if (!res.ok) { const d = await res.json(); throw new Error(d.detail || `HTTP ${res.status}`); }
  return res.json();
}

async function apiPost(path, body = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${state.token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const d = await res.json();
  if (!res.ok) throw new Error(d.detail || `HTTP ${res.status}`);
  return d;
}

function docDetailPath(docType, id) {
  return docType === 'BOM' ? `/api/boms/${id}/` : `/api/transfers/${id}/`;
}

function docActionPath(id, action) {
  return `/api/documents/${id}/${action}/`;
}

/* ══════════════════════════════════════════════════════════════
   DASHBOARD
══════════════════════════════════════════════════════════════ */
let dashboardDocs = { pending: [], approved: [], draft: [], rejected: [] };
let currentDashboardCategory = 'pending';

async function loadDashboard() {
  try {
    // Fetch all BOM + Transfer documents and summarise stats
    const [bomsRaw, transfersRaw] = await Promise.allSettled([
      fetchAllDocs('bom'),
      fetchAllDocs('transfer'),
    ]);

    const boms = bomsRaw.status === 'fulfilled' ? bomsRaw.value : [];
    const transfers = transfersRaw.status === 'fulfilled' ? transfersRaw.value : [];
    const all = [...boms, ...transfers];

    const mine = all.filter(d => d.created_by === state.currentUserId);
    dashboardDocs = { pending: [], approved: [], draft: [], rejected: [] };
    
    dashboardDocs.pending = all.filter(d => isPendingForMe(d));
    mine.forEach(d => {
      if (d.status === 'DRAFT') dashboardDocs.draft.push(d);
      else if (d.status === 'APPROVED' || d.status === 'CLOSED') dashboardDocs.approved.push(d);
      else if (d.status === 'REJECTED') dashboardDocs.rejected.push(d);
    });

    document.getElementById('stat-pending').textContent = dashboardDocs.pending.length;
    document.getElementById('stat-approved').textContent = dashboardDocs.approved.length;
    document.getElementById('stat-draft').textContent = dashboardDocs.draft.length;
    document.getElementById('stat-rejected').textContent = dashboardDocs.rejected.length;

    // Update badge
    const badge = document.getElementById('pending-badge');
    if (dashboardDocs.pending.length > 0) { badge.textContent = dashboardDocs.pending.length; badge.style.display = 'inline-block'; }
    else { badge.style.display = 'none'; }

    selectDashboardCategory(currentDashboardCategory);
  } catch (err) {
    document.getElementById('dashboard-table-body').innerHTML = `<tr><td colspan="7" class="empty-row">載入失敗：${err.message}</td></tr>`;
  }
}

function selectDashboardCategory(category) {
  currentDashboardCategory = category;
  
  // Highlight card visually
  document.querySelectorAll('.stat-card').forEach(c => c.style.opacity = '0.5');
  document.getElementById(`card-${category}`).style.opacity = '1';

  // Update title
  const titles = {
    pending: '待我簽核',
    approved: '已核准',
    draft: '我的草稿',
    rejected: '遭駁回'
  };
  document.getElementById('dashboard-table-title').textContent = titles[category];

  // Render table
  const list = dashboardDocs[category].sort((a, b) => b.id - a.id);
  renderDocTable('dashboard-table-body', list, true);
}

function isDocVisibleToUser(doc, user) {
  if (!user || !user.site_code) return true;
  // 如果是自己建立的單據，永遠可見
  if (doc.created_by === state.currentUserId) return true;
  
  if (user.site_code === 'TPE') {
    if (doc.document_type === 'BOM') {
      return doc.site_code === 'TPE' || doc.cost_impact_high || doc.high_risk;
    } else {
      return true;
    }
  } else {
    // TNN 或 KHH
    if (doc.document_type === 'BOM') {
      return doc.site_code === user.site_code;
    } else {
      return doc.source_site === user.site_code || doc.target_site === user.site_code;
    }
  }
}

async function fetchAllDocs(type) {
  const endpoint = type === 'bom' ? '/api/boms/' : '/api/transfers/';
  const data = await apiGet(endpoint);
  return data.filter(d => isDocVisibleToUser(d, state.currentUser));
}

function isPendingForMe(doc) {
  if (doc.status !== 'APPROVING' && doc.status !== 'SUBMITTED') return false;
  
  // Find the current pending step
  const step = doc.approval_steps ? doc.approval_steps.find(s => s.status === 'PENDING') : null;
  if (!step) return false;
  
  const user = state.currentUser;
  if (!user) return false;
  
  // Require both role and site_code to match
  return user.position === step.role && (!step.site_code || user.site_code === step.site_code);
}

/* ══════════════════════════════════════════════════════════════
   PENDING LIST
══════════════════════════════════════════════════════════════ */
async function loadPendingList() {
  const tbody = document.getElementById('pending-table-body');
  tbody.innerHTML = '<tr><td colspan="8" class="empty-row">載入中...</td></tr>';
  try {
    const typeFilter = document.getElementById('pending-type-filter').value;
    const [bomsRaw, transfersRaw] = await Promise.allSettled([
      fetchAllDocs('bom'),
      fetchAllDocs('transfer'),
    ]);
    let all = [
      ...(bomsRaw.status === 'fulfilled' ? bomsRaw.value : []),
      ...(transfersRaw.status === 'fulfilled' ? transfersRaw.value : []),
    ];

    let pending = all.filter(d => isPendingForMe(d));
    if (typeFilter !== 'all') pending = pending.filter(d => d.document_type === typeFilter);
    pending.sort((a, b) => b.id - a.id);

    if (pending.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" class="empty-row"><div class="empty-state-content"><div class="empty-state-icon">🎉</div><div class="empty-state-text">目前沒有待簽核的單據</div></div></td></tr>';
      return;
    }
    renderPendingTable(tbody, pending);
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty-row">載入失敗：${err.message}</td></tr>`;
  }
}

function renderPendingTable(tbody, docs) {
  tbody.innerHTML = docs.map(d => {
    const step = d.approval_steps ? d.approval_steps.find(s => s.status === 'PENDING') : null;
    return `<tr>
      <td><span class="doc-id">#${d.id}</span></td>
      <td>${docTypeLabel(d.document_type)}</td>
      <td><code>${d.document_type === 'BOM' ? (d.bom_detail?.items?.[0]?.material_id || '—') : (d.transfer_detail?.material_id || '—')}</code></td>
      <td>${d.document_type === 'BOM' ? '—' : d.transfer_detail?.quantity || '—'}</td>
      <td>${d.created_by_display?.name || d.created_by}</td>
      <td>${step ? `<span style="font-size:13px">${step.role}<br><span style="color:var(--text-muted);font-size:11px">${step.site_code}</span></span>` : '—'}</td>
      <td>${statusBadge(d.status)}</td>
      <td>
        <div class="table-actions">
          <button class="btn btn-sm btn-success" onclick="openApproveModal('${d.document_type}', ${d.id})" id="btn-approve-${d.document_type}-${d.id}">✓ 同意</button>
          <button class="btn btn-sm btn-danger" onclick="openRejectModal('${d.document_type}', ${d.id})" id="btn-reject-${d.document_type}-${d.id}">✗ 駁回</button>
          <button class="btn btn-sm btn-secondary" onclick="openDetailModal('${d.document_type}', ${d.id})" id="btn-detail-pending-${d.document_type}-${d.id}">詳情</button>
        </div>
      </td>
    </tr>`;
  }).join('');
}

/* ══════════════════════════════════════════════════════════════
   DASHBOARD TABLE RENDER
══════════════════════════════════════════════════════════════ */
function renderDocTable(tbodyId, docs, includeDetail = false) {
  const tbody = document.getElementById(tbodyId);
  if (docs.length === 0) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty-row"><div class="empty-state-content"><div class="empty-state-icon">📄</div><div class="empty-state-text">暫無資料</div></div></td></tr>';
    return;
  }
  tbody.innerHTML = docs.map(d => {
    const date = d.created_at ? new Date(d.created_at).toLocaleDateString('zh-TW') : '—';
    return `<tr>
      <td><span class="doc-id">#${d.id}</span></td>
      <td>${docTypeLabel(d.document_type)}</td>
      <td>${d.document_type === 'BOM' ? (d.bom_detail?.items?.length > 0 ? `<code>${d.bom_detail.items[0].material_id}</code>${d.bom_detail.items.length > 1 ? ` <span style="font-size:11px;color:var(--text-muted)">(+${d.bom_detail.items.length - 1}項)</span>` : ''}` : '—') : `<code>${d.transfer_detail?.material_id || '—'}</code>`}</td>
      <td>${d.document_type === 'BOM' ? (d.bom_detail?.items ? d.bom_detail.items.reduce((s,i) => s + i.quantity, 0) + ' (合計)' : '—') : (d.transfer_detail?.quantity || '—')}</td>
      <td>${statusBadge(d.status)}</td>
      <td>${date}</td>
      <td>
        <div class="table-actions">
          <button class="btn btn-sm btn-secondary" onclick="openDetailModal('${d.document_type}', ${d.id})" id="btn-detail-${d.document_type}-${d.id}">詳情</button>
          ${d.status === 'DRAFT' ? `<button class="btn btn-sm btn-primary" onclick="submitDoc('${d.document_type}', ${d.id})" id="btn-submit-${d.document_type}-${d.id}">提交</button>` : ''}
          ${d.status === 'REJECTED' && d.created_by === state.currentUserId ? `<button class="btn btn-sm btn-primary" onclick="openReviseModal('${d.document_type}', ${d.id})" id="btn-revise-${d.document_type}-${d.id}">修改重提</button>` : ''}
          ${(d.status === 'SUBMITTED' || d.status === 'APPROVING') && d.created_by === state.currentUserId ?
            `<button class="btn btn-sm btn-danger" onclick="cancelDoc('${d.document_type}', ${d.id})" id="btn-cancel-${d.document_type}-${d.id}">撤回</button>` : ''}
        </div>
      </td>
    </tr>`;
  }).join('');
}

/* ══════════════════════════════════════════════════════════════
   CREATE BOM
══════════════════════════════════════════════════════════════ */
function setBOMAction(action) { state.bomAction = action; }

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('bom-site').addEventListener('change', updateBOMHint);
  document.getElementById('bom-high-risk').addEventListener('change', updateBOMHint);
  document.getElementById('bom-cost-impact').addEventListener('change', updateBOMHint);
});

function updateBOMHint() {
  const site = document.getElementById('bom-site').value;
  const highRisk = document.getElementById('bom-high-risk').checked;
  const costImpact = document.getElementById('bom-cost-impact').checked;
  const textEl = document.getElementById('bom-path-text');
  if (!site) { textEl.textContent = '選擇廠區後，系統將自動顯示預估的簽核路徑。'; return; }
  const siteLabel = { TPE: '台北場', TNN: '台南廠', KHH: '高雄廠' }[site] || site;
  if (highRisk || costImpact || site === 'TPE') {
    const extra = site !== 'TPE' ? ` → ${siteLabel}廠區主管` : '';
    textEl.textContent = `預估路徑：您 → ${siteLabel}生產主管${extra} → 台北財務 → 會計同步`;
  } else {
    textEl.textContent = `預估路徑：您 → ${siteLabel}生產主管 → 會計同步`;
  }
}

function addBOMItem() {
  const container = document.getElementById('bom-items-container');
  const row = document.createElement('div');
  row.className = 'bom-item-row';
  row.style.cssText = 'display:flex; gap:10px; align-items:flex-end;';
  row.innerHTML = `
    <div class="form-group" style="flex:2">
      <label>物料 ID <span class="required">*</span></label>
      <input type="text" class="bom-item-material" placeholder="例如：M001" required />
    </div>
    <div class="form-group" style="flex:1">
      <label>數量 <span class="required">*</span></label>
      <input type="number" class="bom-item-quantity" placeholder="正整數" min="1" step="1" required />
    </div>
    <div class="form-group" style="flex:1">
      <label>狀態</label>
      <select class="bom-item-status">
        <option value="ACTIVE">啟用</option>
        <option value="DISABLED">停用</option>
      </select>
    </div>
    <button type="button" class="btn btn-sm btn-danger" onclick="removeBOMItem(this)" style="padding: 10px 14px;">✕</button>
  `;
  container.appendChild(row);
}

function removeBOMItem(btn) {
  const container = document.getElementById('bom-items-container');
  if (container.querySelectorAll('.bom-item-row').length <= 1) {
    showToast('error', 'BOM 至少需要一項物料。');
    return;
  }
  btn.closest('.bom-item-row').remove();
}

async function submitBOMForm(e) {
  e.preventDefault();
  const site = document.getElementById('bom-site').value;
  const product = document.getElementById('bom-product').value.trim();
  const highRisk = document.getElementById('bom-high-risk').checked;
  const costImpact = document.getElementById('bom-cost-impact').checked;
  const reason = document.getElementById('bom-reason').value.trim();
  const attachments = document.getElementById('bom-attachments').value.trim();

  // 收集所有物料列
  const itemRows = document.querySelectorAll('#bom-items-container .bom-item-row');
  const items = [];
  let hasError = false;
  itemRows.forEach(row => {
    const material_id = row.querySelector('.bom-item-material').value.trim();
    const quantity = parseInt(row.querySelector('.bom-item-quantity').value, 10);
    const material_status = row.querySelector('.bom-item-status').value;
    if (!material_id || !quantity || quantity < 1) { hasError = true; return; }
    items.push({ material_id, quantity, material_status });
  });

  if (!site || !product || hasError || items.length === 0) {
    showToast('error', '請填寫所有必填欄位，數量須為正整數，且至少需要一項物料。'); return;
  }

  const submitBtn = e.target.querySelector('button[type="submit"]');
  submitBtn.classList.add('loading');

  try {
    const doc = await apiPost('/api/boms/', {
      bom_detail: {
        site_code: site, product_id: product, items,
        high_risk: highRisk, cost_impact_high: costImpact,
        reason,
      },
    });

    if (state.bomAction === 'submit') {
      await apiPost(docActionPath(doc.id, 'submit'), { comment: '', version: doc.version });
      showToast('success', `BOM #${doc.id} 已建立並提交簽核！`);
    } else {
      showToast('success', `BOM #${doc.id} 已儲存為草稿。`);
    }
    e.target.reset();
    // 清除多餘物料列，保留第一列
    const container = document.getElementById('bom-items-container');
    const allRows = container.querySelectorAll('.bom-item-row');
    allRows.forEach((r, idx) => { if (idx > 0) r.remove(); });
    navigate('dashboard');
  } catch (err) {
    showToast('error', `操作失敗：${err.message}`);
  } finally {
    submitBtn.classList.remove('loading');
  }
}

/* ══════════════════════════════════════════════════════════════
   CREATE TRANSFER
══════════════════════════════════════════════════════════════ */
function setTransferAction(action) { state.transferAction = action; }

function updateTransferHint() {
  const src = document.getElementById('tr-source-site').value;
  const tgt = document.getElementById('tr-target-site').value;
  const textEl = document.getElementById('transfer-path-text');
  if (!src || !tgt) { textEl.textContent = '選擇廠區後，系統將自動顯示預估的簽核路徑。'; return; }
  const srcLabel = { TPE: '台北場', TNN: '台南廠', KHH: '高雄廠' }[src] || src;
  const tgtLabel = { TPE: '台北場', TNN: '台南廠', KHH: '高雄廠' }[tgt] || tgt;
  if (src === tgt) {
    textEl.textContent = `預估路徑（同廠）：您 → ${srcLabel}倉庫主管 → 會計同步`;
  } else {
    const crossFinance = tgt !== 'TPE' ? ` → ${tgtLabel}倉庫主管 → 台北財務` : ' → 台北財務';
    textEl.textContent = `預估路徑（跨廠）：您 → ${srcLabel}倉庫主管${crossFinance} → 會計同步`;
  }
}

async function submitTransferForm(e) {
  e.preventDefault();
  const srcSite = document.getElementById('tr-source-site').value;
  const tgtSite = document.getElementById('tr-target-site').value;
  const fromWh = document.getElementById('tr-from-warehouse').value.trim();
  const toWh = document.getElementById('tr-to-warehouse').value.trim();
  const material = document.getElementById('tr-material').value.trim();
  const quantity = parseInt(document.getElementById('tr-quantity').value, 10);
  const matStatus = document.getElementById('tr-status').value;
  const urgent = document.getElementById('tr-urgent').checked;
  const reason = document.getElementById('tr-reason').value.trim();

  if (!srcSite || !tgtSite || !fromWh || !toWh || !material || !quantity || quantity < 1) {
    showToast('error', '請填寫所有必填欄位，數量須為正整數。'); return;
  }

  const submitBtn = e.target.querySelector('button[type="submit"]');
  submitBtn.classList.add('loading');

  try {
    const doc = await apiPost('/api/transfers/', {
      transfer_detail: {
        source_site: srcSite, target_site: tgtSite, from_warehouse: fromWh,
        to_warehouse: toWh, material_id: material, quantity, urgent,
      },
    });
    if (state.transferAction === 'submit') {
      await apiPost(docActionPath(doc.id, 'submit'), { comment: '', version: doc.version });
      showToast('success', `物料轉移 #${doc.id} 已建立並提交簽核！`);
    } else {
      showToast('success', `物料轉移 #${doc.id} 已儲存為草稿。`);
    }
    e.target.reset();
    navigate('dashboard');
  } catch (err) {
    showToast('error', `操作失敗：${err.message}`);
  } finally {
    submitBtn.classList.remove('loading');
  }
}

/* ══════════════════════════════════════════════════════════════
   SEARCH
══════════════════════════════════════════════════════════════ */
function resetSearch() {
  document.getElementById('search-table-body').innerHTML = '<tr><td colspan="8" class="empty-row">請輸入查詢條件</td></tr>';
}

async function doSearch() {
  const type = document.getElementById('search-type').value;
  const id = document.getElementById('search-id').value.trim();
  const tbody = document.getElementById('search-table-body');

  if (!id) {
    // Search all (fetch up to 50 docs of that type)
    tbody.innerHTML = '<tr><td colspan="8" class="empty-row">載入中...</td></tr>';
    const docs = await fetchAllDocs(type);
    docs.sort((a, b) => b.id - a.id);
    renderSearchTable(tbody, docs, type);
    return;
  }

  tbody.innerHTML = '<tr><td colspan="8" class="empty-row">查詢中...</td></tr>';
  try {
    const endpoint = type === 'bom' ? `/api/boms/${id}/` : `/api/transfers/${id}/`;
    const doc = await apiGet(endpoint);
    if (!isDocVisibleToUser(doc, state.currentUser)) {
      throw new Error('Not visible');
    }
    renderSearchTable(tbody, [doc], type);
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty-row">找不到單據 #${id}</td></tr>`;
  }
}

function renderSearchTable(tbody, docs, type) {
  if (docs.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" class="empty-row"><div class="empty-state-content"><div class="empty-state-icon">🔍</div><div class="empty-state-text">查無資料</div></div></td></tr>';
    return;
  }
  const docType = type === 'bom' ? 'BOM' : 'MATERIAL_TRANSFER';
  tbody.innerHTML = docs.map(d => {
    const isBOM = d.document_type === 'BOM';
    const matCell = isBOM
      ? (d.items && d.items.length > 0 ? `<code>${d.items[0].material_id}</code>${d.items.length > 1 ? ` <span style="font-size:11px;color:var(--text-muted)">(+${d.items.length - 1}項)</span>` : ''}` : '—')
      : `<code>${d.material_id || '—'}</code>`;
    const qtyCell = isBOM
      ? (d.items ? d.items.reduce((s, i) => s + i.quantity, 0) + ' (合計)' : '—')
      : (d.quantity || '—');
    return `<tr>
      <td><span class="doc-id">#${d.id}</span></td>
      <td>${docTypeLabel(d.document_type)}</td>
      <td>${matCell}</td>
      <td>${qtyCell}</td>
      <td>${d.created_by}</td>
      <td>${statusBadge(d.status)}</td>
      <td>${d.created_at ? new Date(d.created_at).toLocaleDateString('zh-TW') : '—'}</td>
      <td>
        <div class="table-actions">
          <button class="btn btn-sm btn-secondary" onclick="openDetailModal('${d.document_type}', ${d.id})" id="btn-search-detail-${d.document_type}-${d.id}">詳情</button>
        </div>
      </td>
    </tr>`;
  }).join('');
}

/* ══════════════════════════════════════════════════════════════
   DOCUMENT ACTIONS (submit, cancel, approve, reject)
══════════════════════════════════════════════════════════════ */
async function submitDoc(docType, id) {
  try {
    const doc = await apiGet(docDetailPath(docType, id));
    await apiPost(docActionPath(id, 'submit'), { comment: '', version: doc.version });
    showToast('success', `單據 #${id} 已提交簽核！`);
    loadDashboard();
  } catch (err) { showToast('error', `提交失敗：${err.message}`); }
}

async function cancelDoc(docType, id) {
  if (!confirm(`確定要撤回單據 #${id} 嗎？撤回後無法重新提交。`)) return;
  try {
    const doc = await apiGet(docDetailPath(docType, id));
    await apiPost(docActionPath(id, 'cancel'), { version: doc.version });
    showToast('success', `單據 #${id} 已撤回。`);
    loadDashboard();
  } catch (err) { showToast('error', `撤回失敗：${err.message}`); }
}

async function openReviseModal(docType, id) {
  if (!confirm(`確定要修改重提單據 #${id} 嗎？單據將恢復為草稿狀態。`)) return;
  try {
    const doc = await apiGet(docDetailPath(docType, id));
    await apiPost(docActionPath(id, 'revise'), { version: doc.version });
    showToast('success', `單據 #${id} 已恢復為草稿，可重新提交。`);
    loadDashboard();
  } catch (err) { showToast('error', `操作失敗：${err.message}`); }
}

function openApproveModal(docType, id) {
  state.currentDocType = docType;
  state.currentDocId = id;
  state.pendingActionType = 'approve';
  document.getElementById('action-modal-title').textContent = `確認同意 — 單據 #${id}`;
  document.getElementById('action-comment-label').textContent = '簽核意見（選填）';
  document.getElementById('btn-action-confirm').className = 'btn btn-success';
  document.getElementById('btn-action-confirm').textContent = '✓ 確認同意';
  document.getElementById('action-comment-input').value = '';
  document.getElementById('action-modal-overlay').classList.remove('hidden');
}

function openRejectModal(docType, id) {
  state.currentDocType = docType;
  state.currentDocId = id;
  state.pendingActionType = 'reject';
  document.getElementById('action-modal-title').textContent = `確認駁回 — 單據 #${id}`;
  document.getElementById('action-comment-label').textContent = '駁回原因（必填）';
  document.getElementById('btn-action-confirm').className = 'btn btn-danger';
  document.getElementById('btn-action-confirm').textContent = '✗ 確認駁回';
  document.getElementById('action-comment-input').value = '';
  document.getElementById('action-modal-overlay').classList.remove('hidden');
}

function closeActionModal() {
  document.getElementById('action-modal-overlay').classList.add('hidden');
}

async function confirmAction() {
  const confirmBtn = document.getElementById('btn-action-confirm');
  confirmBtn.classList.add('loading');

  const { currentDocType, currentDocId, pendingActionType } = state;
  const comment = document.getElementById('action-comment-input').value.trim();
  if (pendingActionType === 'reject' && !comment) {
    showToast('error', '駁回原因為必填。'); 
    confirmBtn.classList.remove('loading');
    return;
  }
  try {
    const base = docDetailPath(currentDocType, currentDocId);
    
    // 取得單據詳細資料以獲取 current version
    const doc = await apiGet(base);
    const version = doc.version;

    if (pendingActionType === 'approve') {
      await apiPost(docActionPath(currentDocId, 'approve'), { comment, version });
      showToast('success', `單據 #${currentDocId} 已核准！`);
    } else {
      await apiPost(docActionPath(currentDocId, 'reject'), { comment: comment, version });
      showToast('success', `單據 #${currentDocId} 已駁回。`);
    }
    closeActionModal();
    closeModal();
    loadDashboard();
    if (document.getElementById('page-pending') && !document.getElementById('page-pending').classList.contains('hidden')) {
      loadPendingList();
    }
  } catch (err) { 
    showToast('error', `操作失敗：${err.message}`); 
  } finally {
    confirmBtn.classList.remove('loading');
  }
}

/* ══════════════════════════════════════════════════════════════
   DETAIL MODAL
══════════════════════════════════════════════════════════════ */
async function openDetailModal(docType, id) {
  state.currentDocType = docType;
  state.currentDocId = id;
  try {
    const isTransfer = docType === 'MATERIAL_TRANSFER';
    const [doc, logs] = await Promise.all([
      apiGet(docDetailPath(docType, id)),
      apiGet(`/api/documents/${id}/logs/`),
    ]);
    renderDetailModal(doc, logs);
    document.getElementById('detail-modal-overlay').classList.remove('hidden');
  } catch (err) {
    showToast('error', `載入詳情失敗：${err.message}`);
  }
}

function renderDetailModal(doc, logs) {
  const isTransfer = doc.document_type === 'MATERIAL_TRANSFER';
  document.getElementById('modal-title').textContent = `${docTypeLabel(doc.document_type)} #${doc.id}`;
  document.getElementById('modal-subtitle').textContent = statusBadge(doc.status);

  // Meta
  const metaItems = [
    { label: '單據類型', value: docTypeLabel(doc.document_type) },
    { label: '狀態', value: statusBadge(doc.status) },
    { label: '申請人', value: doc.created_by_display?.name || doc.created_by },
    ...(doc.bom_detail?.product_id ? [{ label: '產品 ID', value: `<code>${doc.bom_detail.product_id}</code>` }] : []),
    ...(doc.bom_detail?.site_code ? [{ label: '廠區', value: doc.bom_detail.site_code }] : []),
    ...(isTransfer ? [
      { label: '物料 ID', value: `<code>${doc.transfer_detail?.material_id || '—'}</code>` },
      { label: '數量', value: doc.transfer_detail?.quantity ?? '—' },
      { label: '來源廠', value: doc.transfer_detail?.source_site || '—' },
      { label: '目標廠', value: doc.transfer_detail?.target_site || '—' },
      { label: '是否急件', value: doc.transfer_detail?.urgent ? '<span style="color:var(--red);font-weight:600">✔ 急件</span>' : '否' },
    ] : [
      { label: '高風險', value: doc.bom_detail?.high_risk ? '是' : '否' },
      { label: '高成本影響', value: doc.bom_detail?.cost_impact_high ? '是' : '否' },
    ]),
    ...(doc.bom_detail?.reason ? [{ label: '原因', value: doc.bom_detail.reason }] : []),
    ...(doc.transfer_detail?.reason ? [{ label: '原因', value: doc.transfer_detail.reason }] : []),
    { label: '建立時間', value: doc.created_at ? new Date(doc.created_at).toLocaleString('zh-TW') : '—' },
    { label: '最後更新', value: doc.updated_at ? new Date(doc.updated_at).toLocaleString('zh-TW') : '—' },
    ...(doc.sync_retries > 0 ? [{ label: '同步重試次數', value: `<span style="color:var(--red)">${doc.sync_retries} 次</span>` }] : []),
  ];
  document.getElementById('detail-meta').innerHTML = metaItems.map(i =>
    `<div class="meta-item"><span class="meta-label">${i.label}</span><span class="meta-value">${i.value}</span></div>`
  ).join('');

  // BOM 物料清單區塊
  const itemsSection = document.getElementById('detail-bom-items');
  if (!isTransfer && doc.bom_detail?.items && doc.bom_detail.items.length > 0) {
    itemsSection.style.display = 'block';
    document.getElementById('detail-bom-items-table').innerHTML = doc.bom_detail.items.map((item, idx) => `
      <tr>
        <td>${idx + 1}</td>
        <td><code>${item.material_id}</code></td>
        <td>${item.quantity}</td>
        <td><span class="status-badge ${item.material_status === 'ACTIVE' ? 'badge-approved' : 'badge-rejected'}">${item.material_status}</span></td>
      </tr>
    `).join('');
  } else {
    if (itemsSection) itemsSection.style.display = 'none';
  }

  // Steps
  const stepsEl = document.getElementById('detail-steps');
  if (doc.approval_steps && doc.approval_steps.length > 0) {
    stepsEl.innerHTML = doc.approval_steps.map(s => {
      const cls = s.status === 'APPROVED' ? 'step-approved' : s.status === 'REJECTED' ? 'step-rejected' : s.status === 'PENDING' ? 'step-pending' : 'step-waiting';
      const icon = s.status === 'APPROVED' ? '✓' : s.status === 'REJECTED' ? '✗' : s.status === 'PENDING' ? '⏳' : '○';
      const delegationBadge = s.delegated_from ? `<span style="font-size:10px;background:#fef3c7;color:#92400e;padding:1px 5px;border-radius:4px;">代理: ${s.delegated_from}</span>` : '';
      return `<div class="step-item ${cls}">
        <div class="step-num">${icon}</div>
        <div class="step-info">
          <div class="step-role">${s.role} <span style="font-size:11px;color:var(--text-muted)">${s.site_code}</span> ${delegationBadge}</div>
          <div class="step-detail">${s.approver_id ? `由 ${s.approver_id} 處理` : '等待處理中'}${s.comment ? ` · ${s.comment}` : ''}</div>
        </div>
        <div class="step-status">${statusBadge(s.status)}</div>
      </div>`;
    }).join('');
  } else {
    stepsEl.innerHTML = '<div style="color:var(--text-muted);font-size:13px">尚未產生簽核路徑</div>';
  }

  // Logs
  const logsEl = document.getElementById('detail-logs');
  if (logs && logs.length > 0) {
    logsEl.innerHTML = logs.map(l => {
      const actionMap = {
        SUBMIT: '提交', APPROVE: '核准', REJECT: '駁回', AUTO_REJECT: '自動駁回',
        CANCEL: '撤回', CLOSE: '結案', REVISE: '修改重提',
        SYNC_RETRY: '同步重試', SYNC_RETRY_SUCCESS: '同步重試成功', SYNC_FAILED: '同步永久失敗',
        DELEGATION: '代理人接管',
      };
      return `<div class="log-item">
        <div class="log-dot"></div>
        <div class="log-content">
          <div class="log-action">${actionMap[l.action] || l.action}</div>
          <div class="log-meta">操作者：${l.actor_display?.name || l.actor_id}・${new Date(l.created_at).toLocaleString('zh-TW')}</div>
          ${l.comment ? `<div class="log-comment">"${l.comment}"</div>` : ''}
        </div>
      </div>`;
    }).join('');
  } else {
    logsEl.innerHTML = '<div class="log-empty">暫無操作紀錄</div>';
  }

  // Footer Actions
  const footer = document.getElementById('modal-actions');
  const isMine = doc.created_by === state.currentUserId;
  const isCancelable = (doc.status === 'SUBMITTED' || doc.status === 'APPROVING') && isMine;
  const isApprovable = isPendingForMe(doc);
  const isSyncFailed = doc.status === 'APPROVED' || doc.status === 'SYNC_FAILED';
  const canRetrySync = isSyncFailed && (state.currentUser?.position === '台北財務' || state.currentUser?.position === '系統管理員');

  footer.innerHTML = `
    ${isCancelable ? `<button class="btn btn-danger" onclick="cancelDoc('${doc.document_type}', ${doc.id}); closeModal();" id="btn-modal-cancel">撤回單據</button>` : ''}
    ${isApprovable ? `
      <button class="btn btn-danger" onclick="openRejectModal('${doc.document_type}', ${doc.id})" id="btn-modal-reject">✗ 駁回</button>
      <button class="btn btn-success" onclick="openApproveModal('${doc.document_type}', ${doc.id})" id="btn-modal-approve">✓ 同意</button>
    ` : ''}
    ${canRetrySync ? `<button class="btn btn-secondary" onclick="retrySyncDoc('${doc.document_type}', ${doc.id})" id="btn-modal-retry-sync">🔄 重試會計同步</button>` : ''}
    <button class="btn btn-secondary" onclick="closeModal()" id="btn-modal-done">關閉</button>
  `;
}

function closeModal() {
  document.getElementById('detail-modal-overlay').classList.add('hidden');
}

function closeDetailModal(e) {
  if (e.target === document.getElementById('detail-modal-overlay')) closeModal();
}

/* ══════════════════════════════════════════════════════════════
   TOAST
══════════════════════════════════════════════════════════════ */
function showToast(type, msg) {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  const icon = { success: '✓', error: '✗', info: 'ℹ' }[type] || '';
  toast.innerHTML = `<span>${icon}</span><span>${msg}</span>`;
  container.appendChild(toast);
  setTimeout(() => { toast.style.opacity = '0'; toast.style.transition = 'opacity 300ms'; setTimeout(() => toast.remove(), 300); }, 3500);
}

/* ══════════════════════════════════════════════════════════════
   HELPERS
══════════════════════════════════════════════════════════════ */
function docTypeLabel(type) {
  return type === 'BOM' ? '<span style="font-weight:600;color:#7c3aed">BOM</span>' : '<span style="font-weight:600;color:#0369a1">物料轉移</span>';
}

function statusBadge(status) {
  const map = {
    DRAFT: ['draft', '草稿'],
    SUBMITTED: ['submitted', '已提交'],
    APPROVING: ['approving', '簽核中'],
    APPROVED: ['approved', '已核准'],
    REJECTED: ['rejected', '已駁回'],
    CLOSED: ['closed', '已結案'],
    CANCELED: ['canceled', '已撤回'],
    SYNC_FAILED: ['rejected', '同步失敗'],  // SA: 新增狀態
  };
  const [cls, label] = map[status] || ['draft', status];
  return `<span class="status-badge badge-${cls}">${label}</span>`;
}

/* ══════════════════════════════════════════════════════════════
   SA: 會計同步重試 API 呼叫
══════════════════════════════════════════════════════════════ */
async function retrySyncDoc(docType, id) {
  if (!confirm(`確定要重試單據 #${id} 的會計同步嗎？`)) return;
  try {
    const doc = await apiGet(docDetailPath(docType, id));
    await apiPost(docActionPath(id, 'retry-sync'), { version: doc.version });
    showToast('success', `單據 #${id} 會計同步重試已執行，請查看狀態。`);
    closeModal();
    loadDashboard();
  } catch (err) { showToast('error', `同步重試失敗：${err.message}`); }
}

/* ══════════════════════════════════════════════════════════════
   SA: 代理人設定 (Personal Setting)
══════════════════════════════════════════════════════════════ */
function openDelegationModal() {
  document.getElementById('delegation-modal-overlay').classList.remove('hidden');
}

function closeDelegationModal() {
  document.getElementById('delegation-modal-overlay').classList.add('hidden');
}

async function saveDelegation() {
  const delegateId = document.getElementById('delegation-delegate-id').value.trim();
  const startAt = document.getElementById('delegation-start').value;
  const endAt = document.getElementById('delegation-end').value;
  if (!delegateId || !startAt || !endAt) {
    showToast('error', '請填寫全部代理人資訊。'); return;
  }
  try {
    await apiPost('/api/users/me/delegation/', {
      delegate: delegateId,
      start_at: new Date(startAt).toISOString(),
      end_at: new Date(endAt).toISOString(),
    });
    showToast('success', `代理人已設定為 ${delegateId}，區間：${startAt} ~ ${endAt}`);
    closeDelegationModal();
  } catch (err) { showToast('error', `設定失敗：${err.message}`); }
}

async function clearDelegation() {
  if (!confirm('確定要清除代理人設定嗎？')) return;
  try {
    const res = await fetch(`${API_BASE}/api/users/me/delegation/`, {
      method: 'DELETE',
      headers: { 'Authorization': `Bearer ${state.token}` },
    });
    if (!res.ok) throw new Error((await res.json()).detail);
    showToast('success', '代理人設定已清除。');
    closeDelegationModal();
  } catch (err) { showToast('error', `清除失敗：${err.message}`); }
}

/* SA: 觸發 SLA 逸期檢查 */
async function triggerSlaCheck() {
  try {
    const data = await apiPost('/api/admin/trigger-sla-check/?sla_days=3');
    if (data.checked === 0) {
      showToast('info', '目前沒有逾期未簽核的單據。');
    } else {
      showToast('info', `已發送催辦通知：${data.checked} 張單據逾期`);
    }
  } catch (err) { showToast('error', `SLA 檢查失敗：${err.message}`); }
}
