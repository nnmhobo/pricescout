// ── Theme ────────────────────────────────────────────────────
  function initTheme() {
    const saved = localStorage.getItem('theme') || 'light';
    document.documentElement.setAttribute('data-theme', saved);
    const btn = document.getElementById('theme-toggle');
    if (btn) btn.textContent = saved === 'dark' ? '☀️' : '🌙';
  }

  function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') || 'light';
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
    const btn = document.getElementById('theme-toggle');
    if (btn) btn.textContent = next === 'dark' ? '☀️' : '🌙';
  }

// ── State ────────────────────────────────────────────────────
  let allItems  = [];
  let activeItemId = null;
  let importItems   = [];
  let selectedNames = new Set();
  let allItemsData  = [];
  let monitorQueue  = [];
  let monitorDone   = 0;
  let monitorMode   = 'single';
  let monitorProjectId = null;   // selected project in the "Проекти" monitor mode
  let importFilename   = '';     // name of the last parsed кошторис file
  // User-arranged supplier priority for the single-price mode (persisted).
  let supplierOrder = [];
  try { supplierOrder = JSON.parse(localStorage.getItem('supplierOrder') || '[]'); } catch (e) {}
  // Черга and Проекти keep SEPARATE queues; monitorQueue always points at the
  // active mode's array (swapped in setMonitorMode). runningMode = the mode
  // that owns the active/last batch run — only it shows the log/progress/stop.
  let modeQueues = { batch: monitorQueue, project: [] };
  let runningMode = null;
  let singleRunning = false;
  let batchRunning  = false;
  let batchStopped  = false;
  let batchStartTime = 0;
  // Server-reported absolute caps for batch parallelism. Fetched at boot.
  let serverConfig  = { max_parallel_items: 5, default_parallel_items: 3 };
  // Availability data cache
  let availabilityData = { coverage: {}, items: [] };

  // ── Items (material library) ─────────────────────────────────
  function loadItems() {
    fetch('/api/items').then(r => r.json()).then(items => {
      allItems = items;
      document.getElementById('items-count').textContent = items.length ? `(${items.length})` : '';
      renderDropdown(items, '');
    });
  }

  function supStatusChips(item) {
    const sups = item.suppliers || {};
    const entries = Object.entries(SUPPLIER_NAMES);
    const foundCount = entries.filter(([id]) => sups[id]?.found).length;
    const checkedCount = entries.filter(([id]) => sups[id]).length;
    const summary = checkedCount > 0
      ? `<span class="ci-sup-summary" style="font-size:9px;padding:1px 6px;background:${foundCount > 0 ? 'var(--teal-light)' : 'var(--paper2)'};color:${foundCount > 0 ? 'var(--teal)' : 'var(--ink3)'};border-radius:3px;margin-right:4px;font-weight:600">${foundCount}/${checkedCount} сайтів</span>`
      : '';
    return summary + entries.map(([id, name]) => {
      const entry = sups[id];
      if (!entry) return `<span class="ci-sup missing"><span class="sup-dot"></span>${name}</span>`;
      if (entry.found) {
        const price = entry.last_price ? ` ${Number(entry.last_price).toLocaleString('uk-UA')}₴` : '';
        return `<span class="ci-sup found"><span class="sup-dot"></span>${name}${price}</span>`;
      }
      return `<span class="ci-sup missing"><span class="sup-dot"></span>${name}</span>`;
    }).join('');
  }

  function highlight(text, term) {
    if (!term) return esc(text);
    const idx = text.toLowerCase().indexOf(term.toLowerCase());
    if (idx < 0) return esc(text);
    return esc(text.slice(0, idx))
      + '<mark>' + esc(text.slice(idx, idx + term.length)) + '</mark>'
      + esc(text.slice(idx + term.length));
  }

  function renderDropdown(items, term) {
    const el = document.getElementById('combo-dropdown');
    if (!items.length) {
      el.innerHTML = `<div class="combo-empty">${term ? 'Нічого не знайдено' : 'Немає збережених матеріалів'}</div>`;
      return;
    }
    el.innerHTML = items.map(item => `
      <div class="combo-item" onclick="useItem('${item.id}','${esc(item.label)}')">
        <div class="ci-top">
          <span class="ci-label" title="${esc(item.label)}">${highlight(item.label, term)}</span>
          <span class="ci-date">${esc(item.created)}</span>
          <button class="ci-del" onclick="deleteItem(event,'${item.id}')" title="Видалити">×</button>
        </div>
        <div class="ci-sups">${supStatusChips(item)}</div>
      </div>`).join('');
  }

  function filterItems(term) {
    const filtered = term
      ? allItems.filter(i => i.label.toLowerCase().includes(term.toLowerCase()))
      : allItems;
    renderDropdown(filtered, term);
    openDropdown();
  }

  function openDropdown()  { document.getElementById('combo-dropdown').classList.add('open'); }
  function closeDropdown() {
    document.getElementById('combo-dropdown').classList.remove('open');
    document.getElementById('combo-input').value = '';
  }
  document.addEventListener('click', e => {
    if (!document.getElementById('combo-wrap').contains(e.target)) closeDropdown();
  });

  function saveItem() {
    const label = document.getElementById('cat-input').value.trim();
    if (!label) { shake('cat-input'); return; }
    fetch('/api/items', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({label})
    }).then(r => r.json()).then(d => {
      if (d.error) { alert(d.error); return; }
      activeItemId = d.id;
      loadItems();
    });
  }

  function useItem(id, label) {
    activeItemId = id;
    document.getElementById('cat-input').value = label;
    closeDropdown();
    highlightSuppliersForItem(id);
  }

  function deleteItem(e, id) {
    e.stopPropagation();
    if (id === activeItemId) activeItemId = null;
    fetch(`/api/items/${id}`, {method:'DELETE'}).then(() => loadItems());
  }

  // ── Navigation ───────────────────────────────────────────────
  function showPanel(name, btn) {
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('panel-' + name).classList.add('active');
    if (btn) btn.classList.add('active');
    // restore import tab state if data exists
    if (name === 'import' && importItems.length > 0) {
      setTimeout(() => {
        document.getElementById('import-stats-row').style.display = '';
        document.getElementById('import-table-wrap').style.display = 'flex';
        document.getElementById('btn-do-import').disabled = selectedNames.size === 0;
        if (document.getElementById('import-tbody').innerHTML === '') {
          buildCategoryFilters();
          renderImportTable();
        }
      }, 50);
    }
    // restore items tab
    if (name === 'items' && allItemsData.length === 0) loadItemsTab();
    if (name === 'monitor') renderMonitorTab();
  }

  // ── Suppliers ────────────────────────────────────────────────
  function getEnabledIds() {
    return [...document.querySelectorAll('[id^="chk-"]')]
      .filter(c => c.checked && !c.disabled && c.id !== 'chk-all')
      .map(c => c.id.replace('chk-', ''));
  }

  // Sidebar supplier toggle — locked while any monitoring is active, because
  // the enabled set feeds the routing AND the supplier-order box.
  function onSupplierToggle(cb) {
    if (batchRunning || singleRunning) { cb.checked = !cb.checked; return; }
    saveSupplierSelection();
    renderMonitorTab();
  }

  function toggleAllSuppliers() {
    if (batchRunning || singleRunning) return;   // locked during a run
    const checkboxes = [...document.querySelectorAll('[id^="chk-"]:not(:disabled)')];
    const anyOn = checkboxes.some(c => c.checked);
    checkboxes.forEach(c => { c.checked = !anyOn; });
    const btn = document.getElementById('btn-sup-all');
    if (btn) btn.textContent = anyOn ? 'Увімкнути всі' : 'Вимкнути всі';
    saveSupplierSelection();
    if (document.getElementById('queue-count')) renderMonitorTab();
  }

  // ── Supplier selection persistence ────────────────────────────
  // The sidebar is rendered all-checked by the template on every page load;
  // persist the user's actual selection so a reload doesn't reset it (and
  // with it, the supplier-order box).
  function saveSupplierSelection() {
    try { localStorage.setItem('activeSuppliers', JSON.stringify(getEnabledIds())); } catch (e) {}
  }

  function _applySupplierSelection(ids) {
    if (!Array.isArray(ids)) return;
    document.querySelectorAll('[id^="chk-"]').forEach(c => {
      if (c.id === 'chk-all' || c.disabled) return;
      c.checked = ids.includes(c.id.replace('chk-', ''));
    });
  }

  function restoreSupplierSelection() {
    let ids = null;
    try { ids = JSON.parse(localStorage.getItem('activeSuppliers') || 'null'); } catch (e) {}
    if (Array.isArray(ids)) _applySupplierSelection(ids);
  }

  initTheme();
  loadItems();
  restoreSearchOpts();        // search-mode checkboxes persist across reloads
  restoreSupplierSelection(); // sidebar supplier toggles persist across reloads

  // Fetch the server's parallelism caps and rebuild the "Паралельно" select
  // so the user can pick up to MAX_PARALLEL_ITEMS items at once.
  fetch('/api/config').then(r => r.json()).then(cfg => {
    serverConfig = cfg;
    const sel = document.getElementById('batch-parallel');
    if (!sel) return;
    const def = Math.max(1, Math.min(cfg.max_parallel_items, cfg.default_parallel_items || 3));
    sel.innerHTML = '';
    for (let n = 1; n <= cfg.max_parallel_items; n++) {
      const opt = document.createElement('option');
      opt.value = String(n);
      opt.textContent = n === 1 ? '1 (послідовно)' : `${n} одночасно`;
      if (n === def) opt.selected = true;
      sel.appendChild(opt);
    }
    // The rebuild above resets the selection to the default — re-apply the
    // saved preference (or the active run's values, whichever is pending).
    applyBatchControls();
  }).catch(() => {});

  // ── Resume active run on page reload ─────────────────────────
  fetch('/api/status').then(r => r.json()).then(d => {
    updateDot(d);
    if (d.last_run) {
      document.getElementById('last-run').textContent   = 'Останній запуск: ' + d.last_run;
      document.getElementById('badge-date').textContent = d.last_run;
      document.getElementById('log-sub').textContent    = d.last_run;
    }
    if (d.label) {
      const bl = document.getElementById('badge-label');
      bl.textContent = d.label; bl.style.display = '';
    }
    if (d.running) {
      const isBatch = d.parallel_items && d.total_items > 1;
      if (isBatch) {
        // ── Reconnect to a running batch run ──────────────────────────
        batchRunning = true;
        batchStopped = false;
        const monBtn = Array.from(document.querySelectorAll('.nav-btn'))
          .find(b => b.textContent.trim() === 'Моніторинг');
        showPanel('monitor', monBtn);
        if (d.project_id) monitorProjectId = d.project_id;
        runningMode = d.project_id ? 'project' : 'batch';
        setMonitorMode(runningMode);   // sets correct tab highlight + shows batch panel
        // Restore + lock the run's options (they live server-side for the
        // duration of the run, so a reload can't lose them).
        if (d.run_options) {
          const o = d.run_options;
          const se = document.getElementById('opt-single-price');  if (se) se.checked = !!o.single_price;
          const be = document.getElementById('opt-best-price');    if (be) be.checked = !!o.best_price;
          const fe = document.getElementById('opt-fill-missing');  if (fe) fe.checked = !!o.fill_missing;
          // The run's supplier set wins over localStorage — the sidebar must
          // show exactly what this run is using (and stays locked).
          if (Array.isArray(o.active_suppliers) && o.active_suppliers.length) {
            _applySupplierSelection(o.active_suppliers);
          }
          onSearchOptsChange();
        }
        // Show the run's parallel/limit values in the (locked) controls.
        pendingRunControls = { parallel: d.parallel_items, limit: d.limit, total: d.total_items };
        applyBatchControls();
        updateRunLockUI();
        document.getElementById('batch-log-wrap').style.display = 'flex';
        document.getElementById('btn-run-batch').disabled = true;
        const stopBtn = document.getElementById('btn-stop-batch');
        document.getElementById('btn-stop-batch-wrap').style.display = ''; stopBtn.disabled = false;
        stopBtn.textContent = '◼ Зупинити';
        // Call AFTER setMonitorMode so renderMonitorTab() doesn't overwrite it
        updateBatchProgress(d.done_items ?? 0, d.total_items, d.batch_started_at);
        _startElapsedTick(d.batch_started_at);
        // Restore monitorQueue from the item_ids the server still knows about
        if (d.item_ids && d.item_ids.length) {
          fetch('/api/items').then(r => r.json()).then(allItems => {
            const byId = new Map(allItems.map(i => [i.id, i]));
            // Preserve the run's item order (matters for project runs).
            const q = d.item_ids.map(id => byId.get(id)).filter(Boolean);
            modeQueues[runningMode] = q;
            if (monitorMode === runningMode) monitorQueue = q;
            monitorDone  = d.done_items ?? 0;
            renderMonitorTab();
          }).catch(() => {});
        }
        // Lightweight poll — updates progress bar until the run ends
        (async function reconnectBatchPoll() {
          let lastLogLen = 0;
          while (true) {
            await new Promise(r => setTimeout(r, 1500));
            const s = await fetch('/api/status?log_offset=' + lastLogLen).then(r => r.json());
            updateDot(s);
            updateRunBadges(s);
            if (s.log && s.log.length) appendBatchLog(s.log);
            if (s.total_items) updateBatchProgress(s.done_items ?? 0, s.total_items, s.batch_started_at);
            _updateQueueDoneCounter(s.done_items ?? 0);
            lastLogLen = s.log_total ?? (lastLogLen + (s.log || []).length);
            if (!s.running) break;   // wait for server to confirm fully stopped
          }
          batchRunning = false;
          batchStopped = false;
          pendingRunControls = null;
          updateRunLockUI();
          _stopElapsedTick();
          document.getElementById('btn-run-batch').disabled = false;
          document.getElementById('btn-stop-batch-wrap').style.display = 'none';
          // Refresh THE RUN'S queue with final state (prices, last_checked).
          const updatedItems = await fetch('/api/items').then(r => r.json());
          const doneQ = (modeQueues[runningMode] || monitorQueue)
            .map(q => ({...(updatedItems.find(u => u.id === q.id) || q), _done: true}));
          modeQueues[runningMode] = doneQ;
          if (monitorMode === runningMode) monitorQueue = doneQ;
          const finalResults = await fetch('/api/results').then(r => r.json());
          if (finalResults && finalResults.length > 0) {
            loadResults(); setExcelBtn(true);
            document.getElementById('cnt-badge').textContent = ' (' + finalResults.length + ')';
            const resBtn = [...document.querySelectorAll('.nav-btn')].find(b => b.textContent.includes('Результати'));
            if (resBtn) showPanel('results', resBtn);
          }
          renderMonitorTab();
        })();
      } else {
        // ── Reconnect to a running single-item scrape ─────────────────
        singleRunning = true;
        if (d.run_options && Array.isArray(d.run_options.active_suppliers)
            && d.run_options.active_suppliers.length) {
          _applySupplierSelection(d.run_options.active_suppliers);
        }
        updateRunLockUI();
        document.getElementById('run-btn').disabled = true;
        document.getElementById('stop-btn').style.display = '';
        const monBtn2 = [...document.querySelectorAll('.nav-btn')].find(b => b.textContent.includes('Моніторинг'));
        showPanel('monitor', monBtn2);
        setMonitorMode('single');
        poll();
      }
    }
  }).catch(() => {});

  // ── Load persisted state on startup ──────────────────────────
  // last run results
  fetch('/api/results').then(r => r.json()).then(items => {
    if (items && items.length > 0) {
      loadResults();
      setExcelBtn(true);
      document.getElementById('cnt-badge').textContent = ' (' + items.length + ')';
    }
  }).catch(() => {});

  // last import — streamed in chunks for large files (1000+ items)
  fetch('/api/kostoris/last').then(r => r.json()).then(d => {
    if (!d || !d.items || !d.items.length) return;
    importItems = d.items;
    importFilename = d.filename || '';
    selectedNames = new Set(d.items.map(i => i.name));
    document.getElementById('imp-total').textContent  = d.total;
    _showMergedNote(d);
    document.getElementById('imp-sel').textContent    = selectedNames.size;
    document.getElementById('import-stats-row').style.display = '';
    document.getElementById('import-table-wrap').style.display = 'flex';
    document.getElementById('btn-do-import').disabled = false;
    const drop = document.getElementById('import-drop');
    drop.querySelector('.import-drop-txt').textContent = '✓ ' + (d.filename || 'останній імпорт');
    drop.querySelector('.import-drop-icon').style.display = 'none';
    drop.querySelector('.import-drop-sub').style.display  = 'none';
    drop.style.padding = '8px 20px';
    buildCategoryFilters();
    renderImportTable();
  }).catch(() => {});

  // ── Scrape ───────────────────────────────────────────────────
  function startScrape() {
    // One monitoring at a time — a batch/project run blocks single scrapes.
    if (batchRunning) { alert('Дочекайтеся завершення поточного моніторингу'); return; }
    if (singleRunning) return;
    const label = document.getElementById('cat-input').value.trim();
    if (!label) { shake('cat-input'); return; }

    const ids = getEnabledIds();
    if (!ids.length) { alert('Оберіть хоча б одного постачальника'); return; }

    const body = {
      suppliers: ids.map(id => ({id, enabled:true})),
      label,
    };
    if (activeItemId) body.item_id = activeItemId;

    // Clear log window
    document.getElementById('t-body').innerHTML = '';

    // Show item banner in Моніторинг > Один матеріал panel
    const monBanner  = document.getElementById('single-item-banner');
    const monLabel   = document.getElementById('single-item-label');
    const monStatus  = document.getElementById('single-item-status');
    const idleHint   = document.getElementById('single-idle-hint');
    if (monBanner) { monLabel.textContent = label; monStatus.textContent = 'Виконується…'; monBanner.style.display = 'flex'; }
    if (idleHint)  idleHint.style.display = 'none';

    fetch('/api/scrape', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(body)
    }).then(r => r.json()).then(d => {
      if (d.error) { alert(d.error); return; }
      if (d.item_id) activeItemId = d.item_id;
      singleRunning = true;
      updateRunLockUI();
      document.getElementById('run-btn').disabled = true;
      document.getElementById('stop-btn').style.display = '';
      document.getElementById('stop-btn').disabled = false;
      document.getElementById('stop-btn').textContent = '◼ Зупинити';
      setExcelBtn(false);
      const monBtn = [...document.querySelectorAll('.nav-btn')].find(b => b.textContent.includes('Моніторинг'));
      showPanel('monitor', monBtn);
      setMonitorMode('single');
      poll();
    });
  }

  // ── Poll ─────────────────────────────────────────────────────
  // Mirror the run-label / last-run date chips from an /api/status payload.
  // poll() does this inline for single runs; the batch poll loops call this
  // so the Results-tab badges and the sidebar "Останній запуск" don't keep
  // showing the previous run until a page refresh.
  function updateRunBadges(d) {
    if (d.last_run) {
      document.getElementById('last-run').textContent   = 'Останній запуск: ' + d.last_run;
      document.getElementById('badge-date').textContent = d.last_run;
      document.getElementById('log-sub').textContent    = d.last_run;
    }
    if (d.label) {
      const bl = document.getElementById('badge-label');
      bl.textContent = d.label; bl.style.display = '';
    }
  }

  // Live "Перевірено" counter — called on every batch poll tick so the
  // toolbar count moves during the run, not only after a reload.
  // Cheap direct write; a full renderMonitorTab() per tick would rebuild
  // the whole queue table (hundreds of rows) every 1.5 s.
  function _updateQueueDoneCounter(done) {
    monitorDone = done;
    if (monitorMode === runningMode) {
      const c = document.getElementById('queue-done');
      if (c) c.textContent = done;
    }
  }

  function poll() {
    fetch('/api/status').then(r => r.json()).then(d => {
      renderLog(d.log);
      updateDot(d);
      if (d.last_run) {
        document.getElementById('last-run').textContent   = 'Останній запуск: ' + d.last_run;
        document.getElementById('badge-date').textContent = d.last_run;
        document.getElementById('log-sub').textContent    = d.last_run;
      }
      if (d.label) {
        const bl = document.getElementById('badge-label');
        bl.textContent = d.label; bl.style.display = '';
      }
      if (d.count > 0) {
        document.getElementById('badge-total').textContent = d.count + ' постачальників';
        document.getElementById('cnt-badge').textContent   = ' (' + d.count + ')';
      }
      if (d.running) {
        setTimeout(poll, 1200);
      } else {
        singleRunning = false;
        updateRunLockUI();
        document.getElementById('run-btn').disabled = false;
        document.getElementById('stop-btn').style.display = 'none';
        // Update banner with result count
        const statusText = d.count > 0 ? d.count + ' результатів' : 'Не знайдено';
        const monStatus = document.getElementById('single-item-status');
        if (monStatus) monStatus.textContent = statusText;
        // Always load results (covers manual stop with partial results)
        if (d.count > 0) {
          loadResults(); setExcelBtn(true);
          const resBtn = [...document.querySelectorAll('.nav-btn')].find(b => b.textContent.includes('Результати'));
          if (resBtn) showPanel('results', resBtn);
        }
        loadItems(); // refresh supplier status in dropdown
      }
    });
  }

  // ── Log ──────────────────────────────────────────────────────
  function renderLog(lines) {
    if (!lines || !lines.length) return;
    const b = document.getElementById('t-body');
    b.innerHTML = lines.map(l => {
      const isErr  = /ПОМИЛКА|FAILED|Критична/.test(l);
      const isOk   = /✓|Знайдено|Готово|актуальне|оновлено/.test(l);
      const isInfo = /Рівень|Навігація|Stealth|символів|обрано|Пряме|Матеріал/.test(l);
      const cls = isErr ? 'log-err' : isOk ? 'log-ok' : isInfo ? 'log-info' : '';
      const m = l.match(/^\[(\d{2}:\d{2}:\d{2})\] (.+)$/);
      return m
        ? `<div class="log-line ${cls}"><span class="log-ts">${m[1]}</span><span class="log-msg">${esc(m[2])}</span></div>`
        : `<div class="log-line ${cls}"><span class="log-msg">${esc(l)}</span></div>`;
    }).join('');
    b.scrollTop = b.scrollHeight;
  }

  // ── Dot ──────────────────────────────────────────────────────
  function updateDot(d) {
    const dot = document.getElementById('hdr-dot');
    const lbl = document.getElementById('hdr-status');
    dot.className = 'hdr-dot';
    if (d.running)    { dot.classList.add('running'); lbl.textContent = 'Виконується…'; }
    else if (d.error) { dot.classList.add('error');   lbl.textContent = 'Помилка'; }
    else if (d.count) { dot.classList.add('done');    lbl.textContent = 'Завершено'; }
    else              { lbl.textContent = 'Очікування'; }
  }

  // ── Results ───────────────────────────────────────────────────
  function loadResults() {
    fetch('/api/results').then(r => r.json()).then(items => {
      if (!items.length) return;
      // Stash for the comment editor + search filter.
      window._currentResults = items;
      document.getElementById('cnt-badge').textContent = ' (' + items.length + ')';
      const badgeTotal = document.getElementById('badge-total');
      if (badgeTotal) badgeTotal.textContent = items.length + ' результатів';
      const q = (document.getElementById('results-search') || {}).value || '';
      renderResults(items, q);
    });
  }

  function filterResults(query) {
    if (window._currentResults) renderResults(window._currentResults, query);
  }

  function renderResults(items, query) {
      // Group rendering: backend already orders results by item_label then
      // supplier. We emit a single sticky-style header row each time the
      // item_label changes, so the reader sees блоки матеріалів замість
      // суцільної простиняти. Best price inside the group is highlighted.
      const groups = new Map();
      items.forEach(i => {
        const key = i.item_label || i.name || '—';
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(i);
      });
      // Apply search filter — case-insensitive substring on the group label.
      const q = (query || '').trim().toLowerCase();
      // Filter groups by search query
      if (q) {
        for (const [label] of [...groups]) {
          if (!label.toLowerCase().includes(q)) groups.delete(label);
        }
      }
      // Sort each group's suppliers by price ascending (nulls last)
      groups.forEach(sups => sups.sort((a, b) => {
        if (a.price == null && b.price == null) return 0;
        if (a.price == null) return 1;
        if (b.price == null) return -1;
        return a.price - b.price;
      }));
      // Per-group: rank distinct prices (1=cheapest, 2=second, 3=third).
      // Suppliers tied on the same price share the same rank so two stores
      // both at 100 ₴ both get the gold medal. Ranks past 3 get no medal.
      // Style: gold/silver/bronze background + medal emoji bullet on the
      // supplier cell. Best (rank 1) also bolds the price in teal.
      const MEDAL_STYLES = {
        1: { bg: 'rgba(255,215,0,0.18)',   text: '#a8800f', medal: '🥇', label: '1 місце' },
        2: { bg: 'rgba(192,192,192,0.22)', text: '#5e6770', medal: '🥈', label: '2 місце' },
        3: { bg: 'rgba(205,127,50,0.18)',  text: '#a05a1f', medal: '🥉', label: '3 місце' },
      };
      const rows = [];
      groups.forEach((sups, label) => {
        const prices = sups.map(s => s.price).filter(p => p != null);
        // Distinct sorted prices → rank index. Lookup with .indexOf.
        const ranked = Array.from(new Set(prices)).sort((a, b) => a - b);
        const rankOf = p => (p == null ? null : ranked.indexOf(p) + 1);
        const top3 = ranked.slice(0, 3);
        const topLine = top3.length
          ? top3.map((p, i) => `${MEDAL_STYLES[i + 1].medal} ${Number(p).toLocaleString('uk-UA')} ₴`).join(' · ')
          : '';
        rows.push(`<tr class="result-group-header">
          <td colspan="10" style="background:var(--paper2);font-weight:600;color:var(--ink);padding:8px 12px;font-size:12px;border-top:2px solid var(--border2)">
            ${esc(label)}
            <span style="font-size:10px;color:var(--ink3);margin-left:8px;font-weight:400">
              ${sups.length} ${sups.length === 1 ? 'постачальник' : 'постачальників'}${topLine ? ' · ' + topLine : ''}
            </span>
          </td>
        </tr>`);
        sups.forEach(i => {
          const rank = rankOf(i.price);
          const medal = rank && rank <= 3 ? MEDAL_STYLES[rank] : null;
          const rowStyle = medal ? ` style="background:${medal.bg}"` : '';
          const priceColor = medal ? medal.text : 'inherit';
          const medalBadge = medal ? `<span title="${medal.label}" style="margin-right:6px;font-size:14px">${medal.medal}</span>` : '';
          const itemId = esc(i.item_id || '');
          const supplierId = esc(i.supplier_id || '');
          const canEdit = itemId && supplierId;
          // Manual-price indicator: tooltip carries the original.
          const manualMark = i.manual_price != null
            ? `<span title="${esc('Виправлено вручну. Оригінал: ' + (i.original_price != null ? Number(i.original_price).toLocaleString('uk-UA') + ' ₴' : '—'))}" style="margin-left:4px;font-size:10px;color:var(--ink3)">✎</span>`
            : '';
          // Inline-editable price: just the digits, currency stays outside
          // the contenteditable span so the user can't accidentally delete
          // the ₴ glyph. Blur saves; Enter blurs; Esc reverts.
          const priceText = i.price != null ? Number(i.price).toLocaleString('uk-UA') : '';
          const priceCell = canEdit
            ? `<span class="cell-edit cell-edit-price"
                contenteditable="true" spellcheck="false"
                data-item-id="${itemId}" data-supplier-id="${supplierId}"
                data-field="price" data-original="${priceText}"
                style="display:inline-block;min-width:42px;padding:1px 4px;border-radius:3px;border-bottom:1px dashed var(--border2);font-weight:600;color:${priceColor};font-family:var(--mono)"
                title="Натисніть, щоб виправити ціну (Enter — зберегти, Esc — скасувати)">${priceText || '—'}</span><span class="curr" style="margin-left:2px">${priceText ? '₴' : ''}</span>${manualMark}`
            : `<span style="font-weight:600;color:${priceColor}">${priceText || '—'}</span><span class="curr">${priceText ? '₴' : ''}</span>${manualMark}`;
          // Inline-editable comment: empty cell shows muted placeholder
          // via :empty::before CSS. Same blur/Enter/Esc behaviour as price.
          const commentText = i.comment ? esc(i.comment) : '';
          const commentCell = canEdit
            ? `<span class="cell-edit cell-edit-comment"
                contenteditable="true" spellcheck="true"
                data-item-id="${itemId}" data-supplier-id="${supplierId}"
                data-field="comment" data-original="${commentText}"
                style="display:block;min-height:18px;padding:2px 6px;border-radius:3px;border-bottom:1px dashed var(--border2);font-size:11px;color:var(--ink)"
                title="Натисніть, щоб додати/змінити коментар (Enter — зберегти, Esc — скасувати)">${commentText}</span>`
            : (i.comment ? `<span style="font-size:11px;color:var(--ink2)">${esc(i.comment)}</span>` : '');
          rows.push(`<tr${rowStyle}>
              <td class="td-name">${medalBadge}<a href="${esc(i.url||'#')}" target="_blank" rel="noopener">${esc(i.name||'—')}</a></td>
              <td class="td-price">${priceCell}</td>
              <td class="td-unit">${esc(i.unit||'—')}</td>
              <td class="td-qty" style="font-family:var(--mono);font-size:11px">${i.qty != null ? Number(i.qty).toLocaleString('uk-UA') : '—'}</td>
              <td class="td-unit-est" style="font-family:var(--mono);font-size:11px;color:var(--ink3)">${esc(i.unit_estimate||'—')}</td>
              <td class="td-total" style="font-family:var(--mono);font-size:12px;font-weight:600;color:var(--teal)">${i.total_price != null ? Number(i.total_price).toLocaleString('uk-UA')+' ₴' : '—'}</td>
              <td class="td-brand">${esc(i.brand||'—')}</td>
              <td class="td-sup">${i.url ? `<a href="${esc(i.url)}" target="_blank" rel="noopener" style="color:var(--ink2);text-decoration:none;border-bottom:1px solid var(--border2)">${esc(i.supplier||'—')}</a>` : `<span>${esc(i.supplier||'—')}</span>`}${i.seller_note ? `<span style="font-size:10px;color:var(--ink3);margin-left:5px;font-family:var(--mono)">${esc(i.seller_note)}</span>` : ''}</td>
              <td class="td-sku">${esc(i.sku||'—')}</td>
              <td class="td-comment" style="min-width:140px;max-width:220px">${commentCell}</td>
            </tr>`);
        });
      });
      const visibleCount = [...groups.values()].reduce((s, g) => s + g.length, 0);
      const badgeTotal = document.getElementById('badge-total');
      if (badgeTotal) badgeTotal.textContent = (q ? visibleCount + ' з ' + items.length : items.length) + ' результатів';
      document.getElementById('tbl-wrap').innerHTML = groups.size === 0
        ? '<div class="empty-state"><div class="empty-mark">—</div><div class="empty-h">Нічого не знайдено</div><div class="empty-p">Спробуйте інший запит.</div></div>'
        : `<table>
          <thead><tr>
            <th>Назва товару</th><th>Ціна за од.</th><th>Од.</th>
            <th>К-сть</th><th>Од. кошт.</th><th>Загальна</th>
            <th>Бренд</th><th>Постачальник</th><th>Артикул</th>
            <th title="Натисніть, щоб додати коментар">Коментар</th>
          </tr></thead>
          <tbody>${rows.join('')}</tbody>
        </table>`;
      // Wire inline editors once the table is in the DOM. Using event
      // delegation would also work, but a small per-render binding keeps
      // the contract local.
      document.querySelectorAll('.cell-edit').forEach(_attachCellEditor);
  }

  // ── Inline-editable result cells ─────────────────────────────
  // The price + comment cells in the Results tab are `contenteditable`
  // spans. Saving is on blur (clicking away) or Enter; Esc reverts to the
  // value the cell had on render. Validation rejects non-numeric prices.
  function _attachCellEditor(el) {
    if (el.dataset.editorBound === '1') return;
    el.dataset.editorBound = '1';
    el.addEventListener('focus', () => {
      // Stash the value at focus time so Esc / equality-check sees the
      // most recent rendered state (matters after a previous save).
      el.dataset.original = el.textContent.trim();
      // Select all so a click-then-type replaces the whole value.
      const range = document.createRange();
      range.selectNodeContents(el);
      const sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    });
    el.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter') {
        ev.preventDefault();
        el.blur();
      } else if (ev.key === 'Escape') {
        ev.preventDefault();
        el.textContent = el.dataset.original || '';
        el.blur();
      }
    });
    el.addEventListener('blur', () => _saveCell(el));
  }

  function _saveCell(el) {
    const next = el.textContent.trim();
    const original = (el.dataset.original || '').trim();
    if (next === original) return;  // no-op
    const field = el.dataset.field;
    const itemId = el.dataset.itemId;
    const supplierId = el.dataset.supplierId;

    let payload;
    if (field === 'price') {
      if (next === '' || next === '—') {
        payload = { manual_price: null };
      } else {
        const num = Number(next.replace(/\s/g, '').replace(',', '.'));
        if (!Number.isFinite(num) || num <= 0) {
          el.textContent = original;
          alert('Невалідна ціна — введіть число більше нуля.');
          return;
        }
        payload = { manual_price: num };
      }
    } else if (field === 'comment') {
      payload = { comment: next === '' ? null : next };
    } else {
      return;
    }

    fetch(`/api/results/${encodeURIComponent(itemId)}/${encodeURIComponent(supplierId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then(r => r.json())
      .then(d => {
        if (d.error) {
          el.textContent = original;
          alert(d.error);
          return;
        }
        // Re-render so medal ranking / totals update if a price changed.
        loadResults();
      })
      .catch(() => {
        el.textContent = original;
        alert('Не вдалося оновити рядок.');
      });
  }

  // ── Exports ───────────────────────────────────────────────────
  function loadExports() {
    fetch('/api/exports').then(r => r.json()).then(files => {
      const el = document.getElementById('exports-container');
      if (!files.length) { el.innerHTML = '<div class="exports-empty">Немає збережених експортів</div>'; return; }
      el.innerHTML = `
        <div class="exports-table">
          <div class="et-head"><span>Файл</span><span>Розмір</span><span>Дата</span><span></span></div>
          ${files.map(f => `
            <div class="et-row">
              <div class="et-name"><a href="/api/exports/${esc(f.filename)}" download="${esc(f.filename)}">${esc(f.filename)}</a></div>
              <div class="et-size">${f.size_kb} КБ</div>
              <div class="et-date">${esc(f.created)}</div>
              <div class="et-del"><button onclick="deleteExport('${esc(f.filename)}')" title="Видалити">×</button></div>
            </div>`).join('')}
        </div>`;
    });
  }

  function deleteExport(filename) {
    if (!confirm(`Видалити ${filename}?`)) return;
    fetch(`/api/exports/${encodeURIComponent(filename)}`, {method:'DELETE'})
      .then(() => loadExports());
  }

  // ── Helpers ───────────────────────────────────────────────────
  function setExcelBtn(enabled) {
    const btn = document.getElementById('excel-btn');
    btn.style.pointerEvents = enabled ? '' : 'none';
    btn.style.opacity = enabled ? '' : '0.4';
  }

  function shake(id) {
    const el = document.getElementById(id);
    el.classList.add('shake');
    el.focus();
    setTimeout(() => el.classList.remove('shake'), 400);
  }

  function esc(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  // ── Кошторис import ──────────────────────────────────────────

  function handleDrop(e) {
    e.preventDefault();
    document.getElementById('import-drop').classList.remove('over');
    const f = e.dataTransfer.files[0];
    if (f) parseKostoris(f);
  }

  // "544 рядків → 487 матеріалів (57 повторів об'єднано)" note — the same
  // material appears under several work sections in АВК-5 files; the parser
  // merges them and SUMS the quantities.
  function _showMergedNote(d) {
    const mrg = document.getElementById('imp-merged');
    if (!mrg) return;
    if (d && d.merged > 0) {
      mrg.textContent = `${d.rows_total} рядків у файлі → ${d.total} матеріалів ` +
                        `(${d.merged} повторів об'єднано, кількості підсумовано)`;
      mrg.style.display = '';
    } else {
      mrg.style.display = 'none';
    }
  }

  function parseKostoris(file) {
    if (!file) return;
    const drop = document.getElementById('import-drop');
    drop.querySelector('.import-drop-txt').textContent = 'Обробляємо ' + file.name + '…';
    const fd = new FormData();
    fd.append('file', file);
    fetch('/api/kostoris/parse', { method: 'POST', body: fd })
      .then(r => r.json())
      .then(d => {
        if (d.error) {
          drop.querySelector('.import-drop-txt').textContent = '⚠ ' + d.error;
          drop.querySelector('.import-drop-txt').style.color = 'var(--danger)';
          drop.querySelector('.import-drop-icon').textContent = '❌';
          drop.style.borderColor = 'var(--danger)';
          return;
        }
        importItems = d.items;
        importFilename = file.name;
        selectedNames = new Set(importItems.map(i => i.name));
        document.getElementById('imp-total').textContent = d.total;
        _showMergedNote(d);
        document.getElementById('import-stats-row').style.display = '';
        document.getElementById('import-table-wrap').style.display = 'flex';
        drop.querySelector('.import-drop-txt').textContent = '✓ ' + file.name;
        document.getElementById('import-drop').style.padding = '8px 20px';
        document.getElementById('import-drop').querySelector('.import-drop-icon').style.display = 'none';
        document.getElementById('import-drop').querySelector('.import-drop-sub').style.display = 'none';
        buildCategoryFilters();
        renderImportTable();
      })
      .catch(e => { alert('Помилка: ' + e); });
  }

  function toggleAll(cb) {
    document.getElementById('filter-retail').checked = cb.checked;
    document.getElementById('filter-equipment').checked = cb.checked;
    renderImportTable();
  }

  function buildCategoryFilters() {
    const cats = [...new Set(importItems.map(i => i.category))].sort();
    const el = document.getElementById('category-filters');
    el.innerHTML = cats.map(c => {
      const count = importItems.filter(i => i.category === c).length;
      return `<label class="cat-chip"><input type="checkbox" data-cat="${esc(c)}" checked onchange="syncCategoryFilter(this)"> ${esc(c)} <span style="color:var(--border2);margin-left:2px">(${count})</span></label>`;
    }).join('');
  }

  function toggleAllFilters(checked) {
    document.querySelectorAll('#category-filters input[type=checkbox]').forEach(cb => {
      if (cb.checked !== checked) {
        cb.checked = checked;
        syncCategoryFilter(cb);
      }
    });
  }

  function syncCategoryFilter(cb) {
    const cat = cb.dataset.cat;
    if (!cb.checked) {
      importItems.filter(i => i.category === cat).forEach(i => selectedNames.delete(i.name));
    } else {
      importItems.filter(i => i.category === cat).forEach(i => selectedNames.add(i.name));
    }
    renderImportTable();
  }

  function getActiveCats() {
    return new Set([...document.querySelectorAll('#category-filters input[type=checkbox]')]
      .filter(cb => cb.checked).map(cb => cb.dataset.cat));
  }

  function renderImportTable() {
    const activeCats = getActiveCats();
    const search = document.getElementById('import-search').value.trim().toLowerCase();
    const filtered = importItems.filter(i => {
      if (!activeCats.has(i.category)) return false;
      if (search && !i.name.toLowerCase().includes(search)) return false;
      return true;
    });
    const tbody = document.getElementById('import-tbody');
    tbody.innerHTML = filtered.map(i => `
      <tr>
        <td><input type="checkbox" ${selectedNames.has(i.name)?'checked':''} onchange="toggleItem(this,'${esc(i.name)}')" /></td>
        <td>${esc(i.name)}</td>
        <td style="font-family:var(--mono);font-size:10px;color:var(--ink3)">${esc(i.code)}</td>
        <td style="font-family:var(--mono);font-size:11px">${esc(i.unit||'')}</td>
        <td style="font-family:var(--mono);font-size:11px">${i.qty||''}${i.rows > 1 ? ` <span style="font-size:9px;padding:0 4px;background:var(--paper2);color:var(--ink3);border-radius:3px" title="Кількість підсумовано з ${i.rows} рядків файлу">×${i.rows}</span>` : ''}</td>
        <td style="font-family:var(--mono);font-size:11px">${i.unit_price ? Number(i.unit_price).toLocaleString('uk-UA') + ' ₴' : '—'}</td>
        <td><span style="display:inline-block;padding:1px 5px;background:var(--paper2);color:var(--ink3);border-radius:3px;font-size:9px">${esc(i.category)}</span></td>
      </tr>`).join('');
    document.getElementById('imp-sel').textContent = selectedNames.size;
    document.getElementById('btn-do-import').disabled = selectedNames.size === 0;
    const chkAll = document.getElementById('chk-all');
    if (chkAll) {
      const allChecked = filtered.length > 0 && filtered.every(i => selectedNames.has(i.name));
      const someChecked = filtered.some(i => selectedNames.has(i.name));
      chkAll.checked = allChecked;
      chkAll.indeterminate = !allChecked && someChecked;
    }
  }

  function toggleItem(cb, name) {
    if (cb.checked) selectedNames.add(name);
    else selectedNames.delete(name);
    document.getElementById('imp-sel').textContent = selectedNames.size;
    document.getElementById('btn-do-import').disabled = selectedNames.size === 0;
  }

  function selectAll(checked) {
    if (!checked) {
      selectedNames.clear();
    } else {
      const activeCats = getActiveCats();
      const search = document.getElementById('import-search').value.toLowerCase();
      importItems
        .filter(i => activeCats.has(i.category) && (!search || i.name.toLowerCase().includes(search)))
        .forEach(i => selectedNames.add(i.name));
    }
    renderImportTable();
  }

  async function doImport() {
    const items = importItems
      .filter(i => selectedNames.has(i.name))
      .map(i => ({
        name:       i.name,
        code:       i.code,
        category:   i.category,
        qty:        i.qty,
        unit:       i.unit,
        unit_price: i.unit_price,
      }));
    const projectSel = document.getElementById('import-project-select');
    const selVal = projectSel ? projectSel.value : '';
    const body = { items, filename: importFilename || null };
    if (selVal === '__new__') {
      const name = (document.getElementById('import-new-project-name')?.value || '').trim();
      if (!name) { shake('import-new-project-name'); return; }
      body.new_project_name = name;
    } else if (selVal) {
      body.project_id = selVal;
    }

    const d = await fetch('/api/kostoris/import', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)
    }).then(r => r.json());
    if (d.error) { alert(d.error); return; }

    // linked = rows tied to the project (new AND already-existing items);
    // skipped = empty / in-file duplicated rows.
    const linkedMsg  = d.linked ? `, у проект: ${d.linked}` : '';
    const skippedMsg = d.skipped ? `, пропущено: ${d.skipped}` : '';
    const projMsg    = d.project_name ? ` → «${d.project_name}»` : (d.project_id ? ' → проект' : '');
    document.getElementById('import-result').textContent = `Додано нових: ${d.added}${linkedMsg}${skippedMsg}${projMsg}`;
    loadItems();
    loadItemsTab();
    await loadProjects();
    if (d.project_id && projectSel) {
      projectSel.value = d.project_id;           // freshly created project stays selected
      const inp = document.getElementById('import-new-project-name');
      if (inp) { inp.style.display = 'none'; inp.value = ''; }
    }
  }

  // ── Items DB tab ─────────────────────────────────────────────

  async function loadItemsTab() {
    try {
      const res = await fetch('/api/items');
      allItemsData = await res.json();
    } catch(e) {
      console.error('loadItemsTab error:', e);
      return;
    }
    const cats = [...new Set(allItemsData.map(i => i.category).filter(Boolean))].sort();
    const sel = document.getElementById('items-filter-cat');
    if (sel) {
      sel.innerHTML = '<option value="">Всі категорії</option>' +
        cats.map(c => `<option value="${esc(c)}">${esc(c)}</option>`).join('');
    }
    renderItemsTab();
  }

  let selectedItemIds = new Set();

  function updateItemsBatchBar() {
    const bar = document.getElementById('items-batch-bar');
    const cnt = document.getElementById('items-sel-count');
    if (!bar) return;
    if (selectedItemIds.size > 0) {
      bar.style.display = 'flex';
      cnt.textContent = `Вибрано: ${selectedItemIds.size}`;
    } else {
      bar.style.display = 'none';
    }
    const chkAll = document.getElementById('items-chk-all');
    const _f = getFilteredItems().filter(i => i.monitorable);
    if (chkAll) chkAll.checked = _f.length > 0 && _f.every(i => selectedItemIds.has(i.id));
  }

  function toggleItemSelection(id, checked) {
    if (checked) selectedItemIds.add(id); else selectedItemIds.delete(id);
    updateItemsBatchBar();
  }

  function toggleAllItemsSelection(checked) {
    getFilteredItems()
      .filter(i => i.monitorable)
      .forEach(i => { if (checked) selectedItemIds.add(i.id); else selectedItemIds.delete(i.id); });
    renderItemsTab();
    updateItemsBatchBar();
  }

  function clearItemsSelection() {
    selectedItemIds.clear();
    renderItemsTab();
    updateItemsBatchBar();
  }

  function addSelectedToQueue() {
    const toAdd = allItemsData.filter(i => selectedItemIds.has(i.id));
    toAdd.forEach(i => addToQueue(i, true));
    renderMonitorTab();
    clearItemsSelection();
    const msg = document.createElement('div');
    msg.style.cssText = 'position:fixed;bottom:20px;right:20px;background:var(--teal);color:#fff;padding:10px 18px;border-radius:8px;font-size:12px;z-index:9999';
    msg.textContent = `✓ ${toAdd.length} матеріалів додано до черги моніторингу`;
    document.body.appendChild(msg);
    setTimeout(() => msg.remove(), 3000);
    const monBtn = [...document.querySelectorAll('.nav-btn')].find(b => b.textContent.includes('Моніторинг'));
    showPanel('monitor', monBtn);
    setMonitorMode('batch');
  }

  function getFilteredItems() {
    const search      = (document.getElementById('items-search')?.value || '').trim().toLowerCase();
    const srcFilter   = document.getElementById('items-filter-source')?.value || '';
    const catFilter   = document.getElementById('items-filter-cat')?.value    || '';
    const monFilter   = document.getElementById('items-filter-mon')?.value    || '';
    const priceFilter = document.getElementById('items-filter-price')?.value  || '';
    return allItemsData.filter(i => {
      if (search      && !i.label.toLowerCase().includes(search)) return false;
      if (srcFilter   && i.source   !== srcFilter)               return false;
      if (catFilter   && i.category !== catFilter)               return false;
      if (monFilter === 'yes' && !i.monitorable) return false;
      if (monFilter === 'no'  &&  i.monitorable) return false;
      const hasPrice = Object.values(i.suppliers || {}).some(s => s.found && s.last_price)
                       || i.manual_price != null;
      // "З ціною"  — monitorable items that have a scraped or manual price
      // "Без ціни" — monitorable items that have been (or should be) searched
      //              but haven't returned a price yet.
      //              Non-monitorable items are excluded from both buckets:
      //              they're priceless by design, not by absence of search.
      if (priceFilter === 'with'    && !hasPrice) return false;
      if (priceFilter === 'without' && (hasPrice || !i.monitorable)) return false;
      return true;
    });
  }

  function renderItemsTab() {
    const filtered = getFilteredItems();

    // Sort: monitorable first, then alphabetical
    filtered.sort((a, b) => {
      if (!!b.monitorable !== !!a.monitorable) return b.monitorable ? 1 : -1;
      return (a.label || '').localeCompare(b.label || '', 'uk');
    });

    document.getElementById('items-count').textContent = `${filtered.length} з ${allItemsData.length} матеріалів`;

    const tbody = document.getElementById('items-tbody');
    if (!tbody) return;
    tbody.innerHTML = filtered.map(item => {
      const prices = Object.values(item.suppliers || {})
        .filter(s => s.found && s.last_price)
        .map(s => ({ price: s.last_price, sid: Object.keys(item.suppliers).find(k => item.suppliers[k] === s) }));
      const best = prices.sort((a,b) => a.price - b.price)[0];
      const priceCell = best
        ? `<span style="font-family:var(--mono);font-size:12px;font-weight:600;color:var(--teal)">${Number(best.price).toLocaleString('uk-UA')} ₴</span>
           <span style="font-size:10px;color:var(--ink3);margin-left:4px">${SUPPLIER_NAMES[best.sid]||best.sid}</span>`
        : '<span style="color:var(--ink3);font-size:11px">—</span>';

      const srcBadge = (item.source || 'manual') === 'kostoris'
        ? '<span style="font-size:9px;padding:1px 5px;background:#e0f0ff;color:#1a5a8a;border-radius:3px">кошторис</span>'
        : '<span style="font-size:9px;padding:1px 5px;background:var(--paper2);color:var(--ink3);border-radius:3px">вручну</span>';

      const monBadge = item.monitorable
        ? '<span style="font-size:9px;padding:1px 5px;background:var(--teal-light);color:var(--teal);border-radius:3px">моніторинг</span>'
        : '<span style="font-size:9px;padding:1px 5px;background:var(--paper2);color:var(--ink3);border-radius:3px">без пошуку</span>';

      // Best price: scraped or manual
      const bestSupUrl = best ? (Object.values(item.suppliers||{}).find(s=>s.last_price===best.price)?.url||'') : '';
      const manualPriceVal = item.manual_price != null ? Number(item.manual_price).toLocaleString('uk-UA') : '';
      const priceDisplay = best
        ? `${bestSupUrl ? `<a href="${esc(bestSupUrl)}" target="_blank" rel="noopener" style="color:var(--teal);text-decoration:none;font-family:var(--mono);font-size:12px;font-weight:600">${Number(best.price).toLocaleString('uk-UA')} ₴ ↗</a>` : `<span style="font-family:var(--mono);font-size:12px;font-weight:600;color:var(--teal)">${Number(best.price).toLocaleString('uk-UA')} ₴</span>`}
           <span style="font-size:10px;color:var(--ink3);margin-left:4px">${SUPPLIER_NAMES[best.sid]||best.sid}</span>`
        : item.manual_price != null
          ? `<span style="font-family:var(--mono);font-size:12px;color:var(--gold)">~${manualPriceVal} ₴</span><span style="font-size:9px;color:var(--ink3);margin-left:4px">вручну</span>`
          : '<span style="color:var(--ink3);font-size:11px">—</span>';

      // Availability mini-chips
      const supEntries = item.suppliers || {};
      const supFound = Object.values(supEntries).filter(s => s.found).length;
      const supChecked = Object.keys(supEntries).length;
      const availBadge = supChecked > 0
        ? `<span style="font-size:9px;padding:1px 5px;border-radius:3px;background:${supFound > 0 ? 'var(--teal-light)' : 'var(--danger-bg)'};color:${supFound > 0 ? 'var(--teal)' : 'var(--danger)'};font-weight:600;cursor:pointer" onclick="highlightSuppliersForItem('${item.id}')" title="Натисніть щоб побачити на яких сайтах">${supFound}/${supChecked}</span>`
        : '<span style="font-size:9px;color:var(--ink3)">—</span>';

      return `<tr style="opacity:${item.monitorable ? 1 : 0.65}">
        <td style="width:32px"><input type="checkbox" ${selectedItemIds.has(item.id)?'checked':''} onchange="toggleItemSelection('${item.id}',this.checked)" ${!item.monitorable?'disabled title="Не моніториться"':''}></td>
        <td style="font-size:12px;font-weight:500;width:26%">${esc(item.label||'')}</td>
        <td style="font-size:11px;color:var(--ink3);width:14%">${esc(item.category||'—')}</td>
        <td style="font-family:var(--mono);font-size:10px;color:var(--ink3);width:12%">${esc(item.avk_code||'')}</td>
        <td style="width:6%">${srcBadge}</td>
        <td style="width:6%">${monBadge}</td>
        <td style="width:5%;text-align:center">${availBadge}</td>
        <td style="width:18%">${priceDisplay}</td>
        <td style="width:12%;text-align:right;white-space:nowrap">
          <input type="number" placeholder="Своя ціна" value="${item.manual_price != null ? item.manual_price : ''}"
            style="width:80px;padding:3px 5px;border:1px solid var(--border);border-radius:var(--r);font-size:11px;font-family:var(--mono);background:var(--paper)"
            onchange="setManualPrice('${item.id}', this.value)"
            title="Зафіксована ціна">
          ${item.monitorable ? `<button onclick="selectItemForMonitoring('${item.id}','${esc(item.label)}')"
            style="padding:4px 8px;background:var(--teal);color:#fff;border:none;border-radius:var(--r);font-size:11px;cursor:pointer;font-family:var(--sans);margin-left:3px"
            title="Запустити моніторинг">▶</button>` : ''}
          ${Object.keys(item.suppliers||{}).length > 0 ? `<button onclick="showPriceHistory('${item.id}','${esc(item.label)}')"
            style="padding:4px 6px;background:transparent;color:var(--ink2);border:1px solid var(--border);border-radius:var(--r);font-size:11px;cursor:pointer;margin-left:3px;font-family:var(--sans)"
            title="Історія цін">📈</button>` : ''}
          <button onclick="deleteItem('${item.id}')"
            style="padding:4px 6px;background:transparent;color:var(--ink3);border:1px solid var(--border);border-radius:var(--r);font-size:11px;cursor:pointer;margin-left:3px;font-family:var(--sans)"
            title="Видалити">✕</button>
        </td>
      </tr>`;
    }).join('');
  }

  function selectItemForMonitoring(id, label) {
    const item = allItemsData.find(i => i.id === id);
    if (item) {
      document.getElementById('cat-input').value = label;
      activeItemId = id;
      const monBtn = [...document.querySelectorAll('.nav-btn')].find(b => b.textContent.includes('Моніторинг'));
      showPanel('monitor', monBtn);
      setMonitorMode('single');
    }
  }

  function deleteItem(id) {
    if (!confirm('Видалити матеріал?')) return;
    fetch('/api/items/' + id, { method: 'DELETE' })
      .then(() => { loadItemsTab(); loadItems(); });
  }

  function setManualPrice(id, value) {
    const price = value === '' ? null : parseFloat(value);
    fetch('/api/items/' + id, {
      method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ manual_price: price })
    }).then(() => loadItemsTab());
  }

  function addManualItem() {
    const input = document.getElementById('manual-add-input');
    const msg   = document.getElementById('manual-add-msg');
    const label = (input ? input.value : '').trim();
    if (!label) { if (input) input.focus(); return; }
    fetch('/api/items', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ label })
    }).then(r => r.json()).then(d => {
      if (d.error) {
        if (msg) { msg.style.color = 'var(--danger)'; msg.textContent = d.error; }
      } else {
        if (msg) { msg.style.color = 'var(--teal)'; msg.textContent = '✓ Додано: ' + d.label; }
        if (input) input.value = ''; 
        loadItemsTab();
        loadItems();
        setTimeout(() => { if (msg) msg.textContent = ''; }, 3000);
      }
    });
  }

  // ── Monitoring ───────────────────────────────────────────────

  function setMonitorMode(mode) {
    const paint = (id, active) => {
      const b = document.getElementById(id);
      if (!b) return;
      b.style.background = active ? 'var(--gold)' : 'transparent';
      b.style.color = active ? '#fff' : 'var(--ink3)';
    };
    const projBar = document.getElementById('monitor-project-bar');

    if (mode === 'single') {
      // Single mode hosts the execution journal (the former Журнал nav tab
      // was removed) — swap sub-panels, no navigation.
      monitorMode = 'single';
      document.getElementById('monitor-single').style.display = 'flex';
      document.getElementById('monitor-batch').style.display = 'none';
      paint('mode-single', true);
      paint('mode-batch', false);
      paint('mode-project', false);
      if (projBar) projBar.style.display = 'none';
      return;
    }

    // 'batch' (ad-hoc queue) and 'project' (queue = one project's items in
    // imported-file order) share the same batch panel BUT have separate
    // queues — save the leaving mode's queue, load the target mode's own.
    const prevMode = monitorMode;
    monitorMode = mode === 'project' ? 'project' : 'batch';
    if (prevMode === 'batch' || prevMode === 'project') modeQueues[prevMode] = monitorQueue;
    monitorQueue = modeQueues[monitorMode] || [];

    document.getElementById('monitor-single').style.display = 'none';
    document.getElementById('monitor-batch').style.display = 'flex';
    paint('mode-single', false);
    paint('mode-batch', monitorMode === 'batch');
    paint('mode-project', monitorMode === 'project');
    if (projBar) projBar.style.display = monitorMode === 'project' ? 'flex' : 'none';

    // The run's log / progress / stop button belong ONLY to the mode that
    // started it — the other mode shows its own (idle) queue.
    const ownsRun = runningMode === monitorMode;
    const logWrap = document.getElementById('batch-log-wrap');
    const hasLog  = (document.getElementById('batch-log-body')?.childElementCount || 0) > 0;
    if (logWrap) logWrap.style.display = (ownsRun && (batchRunning || hasLog)) ? 'flex' : 'none';
    const stopWrap = document.getElementById('btn-stop-batch-wrap');
    if (stopWrap) stopWrap.style.display = (ownsRun && batchRunning) ? '' : 'none';
    updateRunLockUI();

    if (monitorMode === 'project') populateMonitorProjectSelect();
    renderMonitorTab();
  }

  async function populateMonitorProjectSelect() {
    const sel = document.getElementById('monitor-project-select');
    if (!sel) return;
    if (!allProjects.length) {
      try { allProjects = await fetch('/api/projects').then(r => r.json()); } catch (e) {}
    }
    const cur = monitorProjectId || sel.value;
    sel.innerHTML = '<option value="">— оберіть проект —</option>' +
      allProjects.map(p => `<option value="${esc(p.id)}" ${p.id === cur ? 'selected' : ''}>${esc(p.name)} (${p.item_count} поз.)</option>`).join('');
    // Auto-load the queue for the pre-selected project — but never while a
    // batch is running/reconnecting (the reconnect path restores the queue
    // from the server's item_ids, which respects the run's limit).
    if (cur && sel.value === cur && !monitorQueue.length && !batchRunning) onMonitorProjectChange();
  }

  async function onMonitorProjectChange() {
    const sel = document.getElementById('monitor-project-select');
    monitorProjectId = (sel && sel.value) || null;
    const info = document.getElementById('monitor-project-info');
    if (!monitorProjectId) {
      _setActiveQueue([]);
      monitorDone = 0;
      if (info) info.textContent = '';
      renderMonitorTab();
      return;
    }
    try {
      // Backend returns items in the imported file's row order (position).
      const items = await fetch(`/api/projects/${monitorProjectId}/items`).then(r => r.json());
      _setActiveQueue(Array.isArray(items) ? items : []);
      monitorDone = 0;
      if (info) info.textContent = `${monitorQueue.length} матеріалів у порядку кошторису`;
    } catch (e) {
      if (info) info.textContent = 'Не вдалося завантажити проект';
    }
    renderMonitorTab();
  }

  function loadMonitorTab() { renderMonitorTab(); }

  // ── Batch run controls (count + parallelism) ────────────────
  function getBatchLimit() {
    // Returns 0 to mean "no limit / all items", else a positive count.
    const mode = document.getElementById('batch-count-mode');
    if (!mode) return 0;
    if (mode.value === 'all') return 0;
    if (mode.value === 'custom') {
      const n = parseInt(document.getElementById('batch-count-custom').value, 10);
      return Number.isFinite(n) && n > 0 ? n : 0;
    }
    const n = parseInt(mode.value, 10);
    return Number.isFinite(n) && n > 0 ? n : 0;
  }

  function getBatchParallel() {
    const sel = document.getElementById('batch-parallel');
    const fallback = serverConfig.default_parallel_items || 3;
    if (!sel) return fallback;
    const n = parseInt(sel.value, 10);
    return Number.isFinite(n) && n > 0 ? n : fallback;
  }

  function onBatchCountModeChange() {
    const mode = document.getElementById('batch-count-mode').value;
    const custom = document.getElementById('batch-count-custom');
    custom.style.display = mode === 'custom' ? '' : 'none';
    saveBatchControls();
    renderMonitorTab();
  }

  function onBatchCountCustomInput() {
    // Re-render on every keystroke so the time estimate tracks the live value.
    saveBatchControls();
    renderMonitorTab();
  }

  function onBatchParallelChange() {
    saveBatchControls();
    renderMonitorTab();
  }

  // ── Batch controls persistence (Паралельно + К-сть товарів) ──
  // Saved ONLY from the explicit change handlers above — never from
  // render passes, which would overwrite the stored value with the
  // template default before restoration happens.
  function saveBatchControls() {
    try {
      const sel = document.getElementById('batch-parallel');
      if (sel) localStorage.setItem('batchParallel', sel.value);
      const modeSel = document.getElementById('batch-count-mode');
      const custom  = document.getElementById('batch-count-custom');
      if (modeSel) localStorage.setItem('batchLimit', JSON.stringify({
        mode: modeSel.value, custom: custom ? custom.value : '',
      }));
    } catch (e) {}
  }

  // Values reported by /api/status for an ACTIVE run — they win over the
  // saved preferences until the run ends.
  let pendingRunControls = null;

  function applyBatchControls() {
    const sel     = document.getElementById('batch-parallel');
    const modeSel = document.getElementById('batch-count-mode');
    const custom  = document.getElementById('batch-count-custom');
    if (pendingRunControls) {
      const p = String(pendingRunControls.parallel || '');
      if (sel && p && [...sel.options].some(o => o.value === p)) sel.value = p;
      if (modeSel && pendingRunControls.limit && pendingRunControls.total
          && pendingRunControls.limit < pendingRunControls.total) {
        modeSel.value = 'custom';
        if (custom) { custom.value = pendingRunControls.limit; custom.style.display = ''; }
      }
    } else {
      try {
        const p = localStorage.getItem('batchParallel');
        if (p && sel && [...sel.options].some(o => o.value === p)) sel.value = p;
        const lm = JSON.parse(localStorage.getItem('batchLimit') || 'null');
        if (lm && modeSel) {
          if ([...modeSel.options].some(o => o.value === lm.mode)) modeSel.value = lm.mode;
          if (custom) {
            if (lm.custom) custom.value = lm.custom;
            custom.style.display = modeSel.value === 'custom' ? '' : 'none';
          }
        }
      } catch (e) {}
    }
    renderMonitorTab();
  }

  // ── Search-mode options (одна ціна / найменша / ціна 0) ──────
  function onSearchOptsChange() {
    const single    = document.getElementById('opt-single-price')?.checked || false;
    const bestEl    = document.getElementById('opt-best-price');
    const bestLabel = document.getElementById('opt-best-price-label');
    if (bestEl) {
      bestEl.disabled = batchRunning || !single;
      if (!single) bestEl.checked = false;   // "найменша" only makes sense for one price
    }
    if (bestLabel) bestLabel.style.opacity = single ? '1' : '0.4';
    saveSearchOpts();
    renderSupplierOrderBox();
  }

  // Active suppliers (sidebar toggles) arranged by the user's saved priority;
  // newly enabled suppliers append at the end in sidebar order.
  function getOrderedActiveSuppliers() {
    const enabled = getEnabledIds();
    const known = supplierOrder.filter(id => enabled.includes(id));
    const rest  = enabled.filter(id => !known.includes(id));
    return known.concat(rest);
  }

  function renderSupplierOrderBox() {
    const box = document.getElementById('supplier-order-box');
    if (!box) return;
    const single = document.getElementById('opt-single-price')?.checked || false;
    const best   = document.getElementById('opt-best-price')?.checked || false;
    // Visible only when we need ONE price WITHOUT best-price comparison —
    // then the probing order decides which supplier's price wins.
    const show = single && !best;
    box.style.display = show ? 'flex' : 'none';
    if (!show) return;
    const ordered = getOrderedActiveSuppliers();
    const list = document.getElementById('supplier-order-list');
    if (!list) return;
    list.innerHTML = ordered.map((id, i) => `
      <div style="display:flex;align-items:center;gap:5px;padding:3px 6px;background:var(--paper);border:1px solid var(--border);border-radius:var(--r)">
        <span style="font-family:var(--mono);font-size:10px;color:var(--ink3)">${i + 1}.</span>
        <span style="font-size:11px">${esc(SUPPLIER_NAMES[id] || id)}</span>
        <button onclick="moveSupplierOrder('${id}',-1)" ${(batchRunning || singleRunning || i === 0) ? 'disabled' : ''}
                style="background:none;border:none;cursor:pointer;color:var(--ink3);font-size:11px;padding:0 2px" title="Раніше">◀</button>
        <button onclick="moveSupplierOrder('${id}',1)" ${(batchRunning || singleRunning || i === ordered.length - 1) ? 'disabled' : ''}
                style="background:none;border:none;cursor:pointer;color:var(--ink3);font-size:11px;padding:0 2px" title="Пізніше">▶</button>
      </div>`).join('') ||
      '<span style="font-size:11px;color:var(--ink3)">Немає активних постачальників — увімкніть їх у лівій панелі</span>';
  }

  function moveSupplierOrder(id, dir) {
    if (batchRunning || singleRunning) return;   // order is locked during a run
    const ordered = getOrderedActiveSuppliers();
    const i = ordered.indexOf(id);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= ordered.length) return;
    [ordered[i], ordered[j]] = [ordered[j], ordered[i]];
    supplierOrder = ordered;
    try { localStorage.setItem('supplierOrder', JSON.stringify(supplierOrder)); } catch (e) {}
    renderSupplierOrderBox();
  }

  // ── Run lock + option persistence ─────────────────────────────
  function _setActiveQueue(arr) {
    monitorQueue = arr;
    if (monitorMode === 'project') modeQueues.project = arr;
    else modeQueues.batch = arr;
  }

  function saveSearchOpts() {
    try {
      localStorage.setItem('searchOpts', JSON.stringify({
        single: document.getElementById('opt-single-price')?.checked || false,
        best:   document.getElementById('opt-best-price')?.checked || false,
        fill:   document.getElementById('opt-fill-missing')?.checked || false,
      }));
    } catch (e) {}
  }

  function restoreSearchOpts() {
    let o = null;
    try { o = JSON.parse(localStorage.getItem('searchOpts') || 'null'); } catch (e) {}
    if (!o) return;
    const se = document.getElementById('opt-single-price');
    const be = document.getElementById('opt-best-price');
    const fe = document.getElementById('opt-fill-missing');
    if (se) se.checked = !!o.single;
    if (be) be.checked = !!o.best;
    if (fe) fe.checked = !!o.fill;
    onSearchOptsChange();
  }

  // Disable everything that must not change while a run is active:
  // the option checkboxes, the project selector, the supplier order and
  // the run buttons of ALL modes (one monitoring at a time).
  function updateRunLockUI() {
    const lock = batchRunning || singleRunning;
    const single = document.getElementById('opt-single-price');
    const best   = document.getElementById('opt-best-price');
    const fill   = document.getElementById('opt-fill-missing');
    if (single) single.disabled = lock;
    if (best)   best.disabled = lock || !(single && single.checked);
    if (fill)   fill.disabled = lock;
    const projSel = document.getElementById('monitor-project-select');
    if (projSel) projSel.disabled = lock;
    ['batch-parallel', 'batch-count-mode', 'batch-count-custom'].forEach(cid => {
      const c = document.getElementById(cid);
      if (c) c.disabled = lock;
    });
    const sideBtn = document.getElementById('run-btn');
    if (sideBtn) sideBtn.disabled = lock;
    // Sidebar supplier toggles: NOT via `disabled` (that flag marks
    // not-implemented suppliers and getEnabledIds() filters on it) —
    // pointer-events + the onSupplierToggle() guard do the locking.
    const supSection = document.getElementById('suppliers-section');
    if (supSection) {
      supSection.style.pointerEvents = lock ? 'none' : '';
      supSection.style.opacity = lock ? '0.55' : '';
    }
    renderSupplierOrderBox();
  }

  function renderMonitorTab() {
    const search = (document.getElementById('monitor-search')?.value || '').trim().toLowerCase();
    const filtered = monitorQueue.filter(i => !search || i.label.toLowerCase().includes(search));
    const el = id => document.getElementById(id);

    if (!el('queue-count')) return;
    const qLen   = monitorQueue.length;
    const supCnt = getEnabledIds().length;
    el('queue-count').textContent = qLen;
    // "Перевірено" shows the live counter only in the mode that owns the
    // run; the other mode counts its own queue's _done flags.
    el('queue-done').textContent  = (runningMode && monitorMode !== runningMode)
      ? monitorQueue.filter(i => i._done).length
      : monitorDone;
    if (el('queue-sups')) el('queue-sups').textContent = supCnt || '—';

    // Category-aware estimate: categories with HVAC/automation/electrical get fewer suppliers
    // Mirrors category_routing.py logic on the frontend
    const monitorAll = !!serverConfig.monitor_all_items;
    // HVAC categories route to ТеплоДім (+ marketplaces) — they ARE searched.
    const HVAC_CATS = new Set([
      'Теплопостачання та опалення','Вентиляція та кондиціонування',
      'Теплотехнічне устаткування'
    ]);
    // Explicit-skip categories: no retail supplier carries them. With
    // MONITOR_ALL_ITEMS the backend falls back to all general suppliers.
    const SKIP_CATS = new Set([
      'Автоматизація (КВП)','Енергоносії','Спеціальні роботи',
      'Вантажопідйомне устаткування','Інше устаткування'
    ]);
    const REDUCED_CATS = new Set([
      'Кабельні системи','Електрообладнання','Охорона та сигналізація'
    ]);
    const PLUMBING_CATS = new Set(['Трубопроводи та фітинги','Мережі (водопостачання, газ)','Санітарно-технічне устаткування']);

    // User-selected limit: 0 = "all". The slice mirrors what the backend
    // will actually process so the time/cost estimate is honest.
    const limit       = getBatchLimit();
    const parallel    = getBatchParallel();
    const itemsToRun  = limit > 0 ? monitorQueue.slice(0, limit) : monitorQueue;
    const willRunIds  = new Set(itemsToRun.map(i => i.id));

    let totalSecs = 0;
    for (const item of itemsToRun) {
      const cat = item.category || '';
      let sups;
      if (HVAC_CATS.has(cat))          sups = Math.min(supCnt, 3);
      else if (SKIP_CATS.has(cat))     sups = monitorAll ? supCnt : 0;
      else if (REDUCED_CATS.has(cat))  sups = Math.min(supCnt, 3);
      else if (PLUMBING_CATS.has(cat)) sups = Math.min(supCnt, 6);
      else                              sups = supCnt;
      if (sups > 0) totalSecs += 35 + Math.max(0, sups - 3) * 12;
    }

    const mins = Math.ceil(totalSecs / 60 / Math.max(1, parallel));
    el('queue-time').textContent = itemsToRun.length ? `~${mins}` : '—';

    // One monitoring at a time: any active run (batch, project or single)
    // disables the Run button in every mode.
    el('btn-run-batch').disabled = batchRunning || singleRunning || qLen === 0 || itemsToRun.length === 0;

    el('monitor-tbody').innerHTML = filtered.map((item, idx) => {
      const prices  = Object.values(item.suppliers || {}).filter(s => s.found && s.last_price).map(s => s.last_price);
      const best    = prices.length ? Math.min(...prices).toLocaleString('uk-UA') + ' ₴' : '—';
      const checked = Object.values(item.suppliers || {}).map(s => s.last_checked).filter(Boolean).sort().reverse()[0] || '—';
      const done    = item._done;
      // HVAC categories are NOT listed — they route to ТеплоДім and are
      // searched. With MONITOR_ALL_ITEMS on, nothing is category-skipped
      // (the backend falls back to all general suppliers).
      const SKIP_CATS_ROW = new Set(['Автоматизація (КВП)','Енергоносії','Спеціальні роботи','Вантажопідйомне устаткування','Інше устаткування']);
      const willSearch = item.monitorable !== false && (monitorAll || !SKIP_CATS_ROW.has(item.category || ''));
      const inLimit    = willRunIds.has(item.id);
      const monBadge = !inLimit
        ? '<span style="font-size:9px;padding:1px 5px;background:#f0ede8;color:var(--ink3);border-radius:3px" title="Поза межами обраної к-сті">поза лімітом</span>'
        : willSearch
        ? '<span style="font-size:9px;padding:1px 5px;background:#e6f4f1;color:var(--teal);border-radius:3px">пошук</span>'
        : '<span style="font-size:9px;padding:1px 5px;background:#f0ede8;color:var(--ink3);border-radius:3px">пропуск</span>';
      const rowOpacity = done ? 0.55 : !inLimit ? 0.35 : !willSearch ? 0.5 : 1;
      return `<tr style="opacity:${rowOpacity}">
        <td style="font-size:10px;color:var(--ink3);text-align:center;padding:6px 4px">${done ? '✓' : idx+1}</td>
        <td style="font-size:12px">${esc(item.label)}</td>
        <td style="font-size:10px;color:var(--ink3)">${esc(item.category||'—')}</td>
        <td>${monBadge}</td>
        <td style="font-family:var(--mono);font-size:12px;color:var(--teal);font-weight:500">${best}</td>
        <td style="font-size:10px;color:var(--ink3)">${esc(checked)}</td>
        <td><button onclick="removeFromQueue('${item.id}')" style="background:none;border:none;cursor:pointer;color:var(--ink3);font-size:12px;padding:2px 4px" title="Видалити">✕</button></td>
      </tr>`;
    }).join('') || '<tr><td colspan="6" style="text-align:center;color:var(--ink3);padding:32px;font-size:13px">Черга порожня — додайте матеріали з Бази матеріалів</td></tr>';
    // Keep the supplier-priority box in sync with the sidebar toggles.
    renderSupplierOrderBox();
  }

  function addToQueue(item, skipRender = false) {
    // Items-tab additions always target the Черга queue (not Проекти).
    if (modeQueues.batch.find(i => i.id === item.id)) return;
    modeQueues.batch.push(item);
    if (monitorMode === 'batch') monitorQueue = modeQueues.batch;
    if (!skipRender) renderMonitorTab();
  }

  function removeFromQueue(id) {
    if (batchRunning && runningMode === monitorMode) return;  // locked during its run
    _setActiveQueue(monitorQueue.filter(i => i.id !== id));
    renderMonitorTab();
  }

  async function addAllToQueue() {
    const items = await fetch('/api/items').then(r => r.json());
    items.forEach(i => addToQueue(i, true));
    renderMonitorTab();
  }

  function clearQueue() {
    if (batchRunning && runningMode === monitorMode) return;  // locked during its run
    _setActiveQueue([]);
    monitorDone = 0;
    renderMonitorTab();
  }

  // (batchRunning / batchStopped / batchStartTime are declared with the
  // top-level globals — restoreSearchOpts() reads them during boot.)
  let _elapsedTimer  = null;

  function clearBatchLog() {
    const logEl = document.getElementById('batch-log-body');
    if (logEl) logEl.innerHTML = '';
    const scrollBtn = document.getElementById('log-scroll-btn');
    if (scrollBtn) scrollBtn.style.display = 'none';
  }

  function scrollBatchLogToBottom() {
    const logEl = document.getElementById('batch-log-body');
    if (logEl) logEl.scrollTop = logEl.scrollHeight;
  }

  function stopBatch() {
    batchStopped = true;
    fetch('/api/stop', { method: 'POST' });
    document.getElementById('btn-stop-batch').textContent = '⏳ Зупиняємо…';
    document.getElementById('btn-stop-batch').disabled = true;
    batchLog('⏳ Зупиняємо — очікуємо завершення поточних запитів…');
    // The main poll loop keeps running until s.running===false,
    // then loads results and redirects — do NOT break early on batchStopped.
  }


  function _fmtElapsed(ms) {
    const s = Math.floor(ms / 1000);
    const m = Math.floor(s / 60);
    return m > 0 ? m + 'хв ' + (s % 60) + 'с' : s + 'с';
  }

  function updateBatchProgress(done, total, startedAt) {
    const bar  = document.getElementById('batch-progress-bar');
    const txt  = document.getElementById('batch-progress-text');
    const elEl = document.getElementById('batch-elapsed');
    if (!bar) return;
    const pct = (total > 0) ? Math.round((done / total) * 100) : 0;
    bar.style.width = pct + '%';
    txt.textContent = total > 0 ? done + ' / ' + total + ' (' + pct + '%)' : '';
    // elapsed time — prefer server timestamp, fall back to local
    const base = startedAt ? new Date(startedAt).getTime() : batchStartTime;
    if (base > 0 && elEl) elEl.textContent = _fmtElapsed(Date.now() - base);
  }

  function _startElapsedTick(startedAt) {
    if (_elapsedTimer) clearInterval(_elapsedTimer);
    _elapsedTimer = setInterval(() => {
      const elEl = document.getElementById('batch-elapsed');
      if (!elEl) return;
      const base = startedAt ? new Date(startedAt).getTime() : batchStartTime;
      if (base > 0) elEl.textContent = _fmtElapsed(Date.now() - base);
    }, 1000);
  }

  function _stopElapsedTick() {
    if (_elapsedTimer) { clearInterval(_elapsedTimer); _elapsedTimer = null; }
  }
  // ── Batch log helpers (module-scope so reconnect can use them) ──
  const MAX_LOG_LINES = 800;
  function appendBatchLog(lines) {
    if (!lines || !lines.length) return;
    const logEl = document.getElementById('batch-log-body');
    if (!logEl) return;
    if (lines.length > MAX_LOG_LINES) lines = lines.slice(-MAX_LOG_LINES);
    const atBottom = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 40;
    const frag = document.createDocumentFragment();
    for (const msg of lines) {
      const div = document.createElement('div');
      div.className = 'tl';
      div.textContent = msg;
      frag.appendChild(div);
    }
    logEl.appendChild(frag);
    while (logEl.childElementCount > MAX_LOG_LINES) logEl.removeChild(logEl.firstChild);
    if (atBottom) logEl.scrollTop = logEl.scrollHeight;
  }
  function batchLog(msg) { appendBatchLog([msg]); }

  async function runBatch() {
    if (!monitorQueue.length) return;
    if (batchRunning) return;
    if (singleRunning) { alert('Дочекайтеся завершення поточного моніторингу'); return; }
    const activeSups = getEnabledIds().map(id => ({id, enabled: true}));
    if (!activeSups.length) { alert('Оберіть постачальників у лівій панелі'); return; }

    batchRunning = true;
    batchStopped = false;
    runningMode  = monitorMode === 'project' ? 'project' : 'batch';
    updateRunLockUI();
    batchStartTime = Date.now();
    document.getElementById('btn-run-batch').disabled = true;
    document.getElementById('btn-stop-batch-wrap').style.display = '';
    document.getElementById('btn-stop-batch').disabled = false;
    document.getElementById('btn-stop-batch').textContent = '◼ Зупинити';
    document.getElementById('batch-log-wrap').style.display = 'flex';
    document.getElementById('batch-log-body').innerHTML = '';
    updateBatchProgress(0, 0, null);
    _startElapsedTick(null);
    monitorDone = 0;
    monitorQueue.forEach(i => i._done = false);

    const logEl = document.getElementById('batch-log-body');
    const scrollBtn = document.getElementById('log-scroll-btn');
    // Show ↓ button when user scrolls up; hide when near bottom.
    logEl.addEventListener('scroll', () => {
      const atBottom = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 40;
      if (scrollBtn) scrollBtn.style.display = atBottom ? 'none' : '';
    });
    // Cap how many log <div>s live in the DOM at once. A full 603-item
    // batch emits tens of thousands of lines; keeping them all (plus a
    // forced reflow per line) freezes the page. Old lines scroll off the
    // top and are dropped — the viewer keeps a bounded scrollback buffer.
    let lastLogLen = 0;

    const limit    = getBatchLimit();
    const parallel = getBatchParallel();
    const payload = {
      item_ids: monitorQueue.map(i => i.id),
      suppliers: activeSups,
      parallel_items: parallel,
    };
    if (limit > 0) payload.limit = limit;
    // Project runs: backend keeps results in the file order and uses the
    // project's per-item quantities for totals.
    if (monitorMode === 'project' && monitorProjectId) {
      payload.project_id = monitorProjectId;
      const p = allProjects.find(pr => pr.id === monitorProjectId);
      if (p) payload.label = `Проект: ${p.name}`;
    }
    // Search-mode options (одна ціна / найменша / ціна 0 для не знайдених).
    const singlePrice = document.getElementById('opt-single-price')?.checked || false;
    const bestPrice   = document.getElementById('opt-best-price')?.checked || false;
    const fillMissing = document.getElementById('opt-fill-missing')?.checked || false;
    if (singlePrice) {
      payload.single_price = true;
      if (bestPrice) payload.best_price = true;
      else payload.supplier_order = getOrderedActiveSuppliers();
    }
    if (fillMissing) payload.fill_missing = true;

    const resp = await fetch('/api/scrape/batch', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    }).then(r => r.json());

    if (resp.error) {
      batchLog(`⚠ ${resp.error}`);
      batchRunning = false;
      batchStopped = false;
      updateRunLockUI();
      document.getElementById('btn-run-batch').disabled = false;
      document.getElementById('btn-stop-batch-wrap').style.display = 'none';
      return;
    }

    const requested = resp.requested_count ?? resp.item_count;
    const slicedNote = (requested && requested !== resp.item_count)
      ? ` (з ${requested})` : '';
    batchLog(`Запущено: ${resp.item_count} матеріалів${slicedNote} | ${resp.supplier_count} постачальників | паралельно: ${resp.parallel_items}`);
    // Show 0/N immediately so the counter doesn't sit blank then jump to 100%
    updateBatchProgress(0, resp.item_count ?? 0, null);
    await new Promise(r => setTimeout(r, 2000));

    lastLogLen = 0;
    let lastTotal = resp.item_count ?? 0;
    while (true) {
      // Incremental fetch: ask only for log lines we haven't seen yet.
      // The backend log grows past 100 lines on big batches, so slicing
      // a capped response client-side used to freeze the log view.
      const s = await fetch('/api/status?log_offset=' + lastLogLen).then(r => r.json());
      updateDot(s);
      updateRunBadges(s);
      appendBatchLog(s.log);
      if (s.total_items) { lastTotal = s.total_items; updateBatchProgress(s.done_items ?? 0, s.total_items, s.batch_started_at); }
      _updateQueueDoneCounter(s.done_items ?? 0);
      lastLogLen = s.log_total ?? (lastLogLen + s.log.length);
      if (s.error) { batchLog(`⚠ ${s.error}`); break; }
      if (!s.running) break;   // wait for server to confirm fully stopped
      await new Promise(r => setTimeout(r, 1500));
    }

    const updated = await fetch('/api/items').then(r => r.json());
    // Refresh THE RUN'S queue (the user may have switched modes mid-run).
    const doneQ = (modeQueues[runningMode] || monitorQueue)
      .map(q => ({...(updated.find(u => u.id === q.id) || q), _done: true}));
    modeQueues[runningMode] = doneQ;
    if (monitorMode === runningMode) monitorQueue = doneQ;
    batchRunning = false;
    batchStopped = false;
    pendingRunControls = null;
    updateRunLockUI();
    _stopElapsedTick();
    document.getElementById('btn-run-batch').disabled = false;
    document.getElementById('btn-stop-batch-wrap').style.display = 'none';
    updateBatchProgress(lastTotal, lastTotal, null);
    batchLog('✅ Всі матеріали перевірено!');
    renderMonitorTab();

    const lastResults = await fetch('/api/results').then(r => r.json());
    if (lastResults && lastResults.length > 0) {
      loadResults();
      setExcelBtn(true);
      document.getElementById('cnt-badge').textContent = ' (' + lastResults.length + ')';
      const resBtn = [...document.querySelectorAll('.nav-btn')].find(b => b.textContent.includes('Результати'));
      if (resBtn) showPanel('results', resBtn);
    }
  }

  // ── Availability / Coverage ─────────────────────────────────

  async function loadAvailability() {
    try {
      const data = await fetch('/api/availability').then(r => r.json());
      availabilityData = data;
      renderAvailability();
    } catch(e) {
      console.error('loadAvailability error:', e);
    }
  }

  function renderAvailability() {
    const items = availabilityData.items || [];
    const coverage = availabilityData.coverage || {};
    const supIds = Object.keys(SUPPLIER_NAMES);
    const search = (document.getElementById('avail-search')?.value || '').trim().toLowerCase();
    const filter = document.getElementById('avail-filter')?.value || '';

    const filtered = items.filter(item => {
      if (search && !item.label.toLowerCase().includes(search)) return false;
      if (filter) {
        const sups = item.suppliers || {};
        const foundCount = Object.values(sups).filter(s => s.found).length;
        const checkedCount = Object.keys(sups).length;
        if (filter === 'full' && foundCount < checkedCount) return false;
        if (filter === 'partial' && (foundCount === 0 || foundCount >= checkedCount)) return false;
        if (filter === 'none' && foundCount > 0) return false;
      }
      return true;
    });

    const thead = document.getElementById('avail-thead');
    const tbody = document.getElementById('avail-tbody');
    if (!thead || !tbody) return;

    const S = 'position:sticky;background:var(--paper);z-index:2';
    thead.innerHTML = `
      <tr>
        <th style="${S};top:0;min-width:200px;border-bottom:none"></th>
        <th style="${S};top:0;width:100px;border-bottom:none"></th>
        ${supIds.map(sid => {
          const c = coverage[sid] || { checked: 0, found: 0 };
          const pct = c.checked > 0 ? Math.round(c.found / c.checked * 100) : 0;
          const col = pct >= 70 ? 'var(--teal)' : pct >= 30 ? 'var(--gold)' : 'var(--danger)';
          return `<th style="${S};top:0;text-align:center;min-width:70px;padding:5px 2px 3px;border-bottom:none">
            <span style="font-family:var(--serif);font-size:15px;font-weight:700;color:${col};display:block;line-height:1">${pct}%</span>
            <span style="font-size:9px;color:var(--ink3);display:block;margin-top:1px">${c.found}/${c.checked}</span>
          </th>`;
        }).join('')}
        <th style="${S};top:0;width:60px;border-bottom:none"></th>
      </tr>
      <tr>
        <th style="${S};top:40px;min-width:200px">Матеріал</th>
        <th style="${S};top:40px;width:100px">Категорія</th>
        ${supIds.map(sid => `<th style="${S};top:40px;text-align:center;font-size:10px;min-width:70px;writing-mode:vertical-lr;transform:rotate(180deg);padding:6px 2px">${esc(SUPPLIER_NAMES[sid])}</th>`).join('')}
        <th style="${S};top:40px;text-align:center;width:60px">Всього</th>
      </tr>`;

    if (!filtered.length) {
      tbody.innerHTML = `<tr><td colspan="${supIds.length + 3}" style="text-align:center;padding:32px;color:var(--ink3);font-size:13px">
        ${items.length === 0 ? 'Немає даних — запустіть моніторинг, щоб побачити наявність' : 'Нічого не знайдено за фільтром'}
      </td></tr>`;
      return;
    }

    tbody.innerHTML = filtered.map(item => {
      const sups = item.suppliers || {};
      const foundCount = Object.values(sups).filter(s => s.found).length;
      const total = supIds.length;
      return `<tr>
        <td style="font-size:12px;font-weight:500;max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(item.label)}">${esc(item.label)}</td>
        <td style="font-size:10px;color:var(--ink3)">${esc(item.category || '—')}</td>
        ${supIds.map(sid => {
          const entry = sups[sid];
          if (!entry) return `<td style="text-align:center"><span class="avail-dot avail-unchecked" title="Не перевірено">—</span></td>`;
          if (entry.found) {
            const price = entry.last_price ? Number(entry.last_price).toLocaleString('uk-UA') + '₴' : '';
            return `<td style="text-align:center" title="${SUPPLIER_NAMES[sid]}: ${price}"><span class="avail-dot avail-found">✓</span></td>`;
          }
          return `<td style="text-align:center" title="${SUPPLIER_NAMES[sid]}: не знайдено"><span class="avail-dot avail-missing">✗</span></td>`;
        }).join('')}
        <td style="text-align:center;font-family:var(--mono);font-size:11px;font-weight:600;color:${foundCount > 0 ? 'var(--teal)' : 'var(--ink3)'}">${foundCount}/${total}</td>
      </tr>`;
    }).join('');
  }

  function highlightSuppliersForItem(itemId) {
    const item = allItems.find(i => i.id === itemId);
    if (!item) { clearSupplierHighlights(); return; }
    const sups = item.suppliers || {};
    const supIds = Object.keys(SUPPLIER_NAMES);
    supIds.forEach(sid => {
      const row = document.getElementById('sup-row-' + sid);
      const badge = document.getElementById('sup-avail-' + sid);
      if (!row || !badge) return;
      const entry = sups[sid];
      if (entry && entry.found) {
        badge.textContent = entry.last_price ? Number(entry.last_price).toLocaleString('uk-UA') + '₴' : '✓ є';
        badge.style.display = '';
        badge.style.background = 'var(--teal-light)';
        badge.style.color = 'var(--teal)';
        row.style.background = 'rgba(26,107,90,0.06)';
        row.style.borderRadius = '6px';
      } else if (entry && !entry.found) {
        badge.textContent = '✗ немає';
        badge.style.display = '';
        badge.style.background = 'var(--danger-bg)';
        badge.style.color = 'var(--danger)';
        row.style.background = 'rgba(192,57,43,0.04)';
        row.style.borderRadius = '6px';
      } else {
        badge.textContent = '? не перевірено';
        badge.style.display = '';
        badge.style.background = 'var(--paper2)';
        badge.style.color = 'var(--ink3)';
        row.style.background = '';
      }
    });
  }

  function clearSupplierHighlights() {
    const supIds = Object.keys(SUPPLIER_NAMES);
    supIds.forEach(sid => {
      const row = document.getElementById('sup-row-' + sid);
      const badge = document.getElementById('sup-avail-' + sid);
      if (row) row.style.background = '';
      if (badge) badge.style.display = 'none';
    });
  }

  // Load coverage on startup for sidebar badges
  fetch('/api/availability/coverage').then(r => r.json()).then(coverage => {
    const supIds = Object.keys(SUPPLIER_NAMES);
    supIds.forEach(sid => {
      const badge = document.getElementById('sup-avail-' + sid);
      if (!badge) return;
      const c = coverage[sid];
      if (!c || c.checked === 0) return;
      const pct = Math.round(c.found / c.checked * 100);
      badge.textContent = `${c.found}/${c.checked}`;
      badge.style.display = '';
      badge.style.background = pct >= 50 ? 'var(--teal-light)' : 'var(--paper2)';
      badge.style.color = pct >= 50 ? 'var(--teal)' : 'var(--ink3)';
    });
  }).catch(() => {});

  // ── Projects ─────────────────────────────────────────────────

  let allProjects = [];
  let activeProjectId = null;

  async function loadProjects() {
    try {
      allProjects = await fetch('/api/projects').then(r => r.json());
    } catch(e) { return; }
    renderProjectsList();
    populateImportProjectSelect();
  }

  function populateImportProjectSelect() {
    const sel = document.getElementById('import-project-select');
    if (!sel) return;
    const cur = sel.value;
    sel.innerHTML = '<option value="">— без проекту —</option>' +
      '<option value="__new__"' + (cur === '__new__' ? ' selected' : '') + '>+ Новий проект…</option>' +
      allProjects.map(p => `<option value="${esc(p.id)}" ${p.id===cur?'selected':''}>${esc(p.name)} (${p.item_count} поз.)</option>`).join('');
  }

  function onImportProjectChange() {
    const sel = document.getElementById('import-project-select');
    const inp = document.getElementById('import-new-project-name');
    if (!sel || !inp) return;
    if (sel.value === '__new__') {
      inp.style.display = '';
      if (!inp.value) inp.value = (importFilename || '').replace(/\.(xls|xlsx)$/i, '');
      inp.focus();
    } else {
      inp.style.display = 'none';
    }
  }

  function showCreateProject() {
    const form = document.getElementById('project-create-form');
    form.style.display = form.style.display === 'none' ? '' : 'none';
    if (form.style.display !== 'none') document.getElementById('proj-name').focus();
  }

  async function createProject() {
    const name = document.getElementById('proj-name').value.trim();
    const desc = document.getElementById('proj-desc').value.trim();
    if (!name) { shake('proj-name'); return; }
    const p = await fetch('/api/projects', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ name, description: desc || null })
    }).then(r => r.json());
    if (p.error) { alert(p.error); return; }
    document.getElementById('proj-name').value = '';
    document.getElementById('proj-desc').value = '';
    document.getElementById('project-create-form').style.display = 'none';
    await loadProjects();
    viewProject(p.id);
  }

  function renderProjectsList() {
    const wrap = document.getElementById('project-list-wrap');
    if (!wrap) return;
    document.getElementById('project-detail-wrap').style.display = 'none';
    wrap.style.display = 'flex';
    if (!allProjects.length) {
      wrap.innerHTML = `<div style="text-align:center;padding:48px 20px;color:var(--ink3);font-size:13px">
        <div style="font-size:32px;margin-bottom:12px">📁</div>
        <div style="font-weight:500;margin-bottom:6px">Проектів немає</div>
        <div style="font-size:12px">Натисніть "+ Новий проект" щоб розпочати</div>
      </div>`;
      return;
    }
    wrap.innerHTML = allProjects.map(p => {
      const pricedPct = p.item_count > 0
        ? Math.round((p.items_with_price || 0) / p.item_count * 100) : 0;
      return `
      <div style="display:flex;align-items:center;gap:14px;padding:16px 18px;background:var(--white);border:1px solid var(--border);border-radius:var(--r-lg);cursor:pointer;transition:box-shadow 0.15s"
           onmouseenter="this.style.boxShadow='0 2px 12px rgba(0,0,0,0.08)'" onmouseleave="this.style.boxShadow=''"
           onclick="viewProject('${p.id}')">
        <div style="width:42px;height:42px;background:var(--teal-light);border-radius:var(--r-lg);display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0">📋</div>
        <div style="flex:1;min-width:0">
          <div style="font-size:13px;font-weight:600;color:var(--ink)">${esc(p.name)}</div>
          ${p.description ? `<div style="font-size:11px;color:var(--ink3);margin-top:1px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(p.description)}</div>` : ''}
          <div style="display:flex;align-items:center;gap:10px;margin-top:5px">
            <span style="font-size:10px;color:var(--ink3)">📅 ${esc(p.created)}</span>
            <span style="font-size:10px;color:var(--ink2);font-weight:500">${p.item_count} матеріалів</span>
            ${p.item_count > 0 ? `<span style="font-size:10px;color:var(--teal)">${pricedPct}% з цінами</span>` : ''}
          </div>
        </div>
        <div style="display:flex;gap:8px;flex-shrink:0" onclick="event.stopPropagation()">
          <a href="/api/projects/${esc(p.id)}/export" download
             style="padding:6px 12px;background:var(--teal-light);color:var(--teal);border:none;border-radius:var(--r);font-size:11px;font-weight:600;cursor:pointer;text-decoration:none;white-space:nowrap">↓ Excel</a>
          <button onclick="deleteProject('${p.id}')"
            style="padding:6px 10px;background:transparent;color:var(--ink3);border:1px solid var(--border);border-radius:var(--r);font-size:11px;cursor:pointer">✕</button>
        </div>
      </div>`;
    }).join('');
  }

  // ── Project detail ────────────────────────────────────────────

  let _projItems = [];   // current project's enriched items (for add-item filtering)
  let _projAddOpen = false;

  async function viewProject(projectId) {
    activeProjectId = projectId;
    document.getElementById('project-list-wrap').style.display   = 'none';
    document.getElementById('project-detail-wrap').style.display = 'flex';
    await _renderProjectDetail(projectId);
  }

  async function _renderProjectDetail(projectId) {
    const detailWrap = document.getElementById('project-detail-wrap');
    detailWrap.innerHTML = `<div style="padding:32px;color:var(--ink3);font-size:13px;text-align:center">Завантаження…</div>`;

    const [project, items, summary] = await Promise.all([
      fetch(`/api/projects/${projectId}`).then(r => r.json()),
      fetch(`/api/projects/${projectId}/items`).then(r => r.json()),
      fetch(`/api/projects/${projectId}/summary`).then(r => r.json()),
    ]);
    _projItems = items;

    const fmt = n => n != null ? Number(n).toLocaleString('uk-UA', {maximumFractionDigits:0}) : '—';
    const inProjectIds = new Set(items.map(i => i.id));

    detailWrap.innerHTML = `
      <!-- Header row -->
      <div style="display:flex;align-items:center;gap:10px;flex-shrink:0">
        <button onclick="renderProjectsList();document.getElementById('project-list-wrap').style.display='flex';document.getElementById('project-detail-wrap').style.display='none'"
          style="padding:6px 12px;background:transparent;color:var(--ink3);border:1px solid var(--border);border-radius:var(--r);font-size:11px;cursor:pointer">← Назад</button>
        <div style="flex:1">
          <div style="font-size:15px;font-weight:600">${esc(project.name)}</div>
          ${project.description ? `<div style="font-size:11px;color:var(--ink3)">${esc(project.description)}</div>` : ''}
        </div>
        <button onclick="_queueProjectItems('${projectId}')"
          style="padding:7px 14px;background:var(--paper2);color:var(--ink2);border:1px solid var(--border);border-radius:var(--r);font-size:12px;font-weight:500;cursor:pointer;white-space:nowrap">▶ Моніторинг</button>
        <a href="/api/projects/${esc(projectId)}/export" download
          style="padding:7px 14px;background:var(--teal);color:#fff;border:none;border-radius:var(--r);font-size:12px;font-weight:600;cursor:pointer;text-decoration:none;white-space:nowrap">↓ Excel</a>
      </div>

      <!-- KPI cards -->
      <div style="display:flex;gap:8px;flex-wrap:wrap;flex-shrink:0">
        <div style="flex:1;min-width:110px;padding:10px 14px;background:var(--white);border:1px solid var(--border);border-radius:var(--r-lg)">
          <div style="font-size:9px;text-transform:uppercase;letter-spacing:0.08em;color:var(--ink3)">Матеріалів</div>
          <div style="font-family:var(--serif);font-size:22px;line-height:1.2">${summary.item_count}</div>
          <div style="font-size:10px;color:var(--ink3)">${summary.items_with_price} з цінами</div>
        </div>
        <div style="flex:1;min-width:110px;padding:10px 14px;background:var(--white);border:1px solid var(--border);border-radius:var(--r-lg)">
          <div style="font-size:9px;text-transform:uppercase;letter-spacing:0.08em;color:var(--ink3)">Кошторис</div>
          <div style="font-family:var(--serif);font-size:22px;line-height:1.2">${fmt(summary.total_estimate)}</div>
          <div style="font-size:10px;color:var(--ink3)">грн</div>
        </div>
        <div style="flex:1;min-width:110px;padding:10px 14px;background:var(--white);border:1px solid var(--border);border-radius:var(--r-lg)">
          <div style="font-size:9px;text-transform:uppercase;letter-spacing:0.08em;color:var(--ink3)">Мін. ціни</div>
          <div style="font-family:var(--serif);font-size:22px;line-height:1.2;color:var(--teal)">${fmt(summary.total_best)}</div>
          <div style="font-size:10px;color:var(--ink3)">грн</div>
        </div>
        <div style="flex:1;min-width:110px;padding:10px 14px;background:${summary.saving>0?'var(--teal-light)':'var(--white)'};border:1px solid var(--border);border-radius:var(--r-lg)">
          <div style="font-size:9px;text-transform:uppercase;letter-spacing:0.08em;color:var(--ink3)">Економія</div>
          <div style="font-family:var(--serif);font-size:22px;line-height:1.2;color:${summary.saving>0?'var(--teal)':'var(--ink3)'}">${fmt(summary.saving)}</div>
          <div style="font-size:10px;color:var(--ink3)">${summary.saving_pct}%</div>
        </div>
      </div>

      <!-- Items table with add-item panel -->
      <div style="flex:1;min-height:0;display:flex;flex-direction:column;border:1px solid var(--border);border-radius:var(--r-lg);overflow:hidden;background:var(--white)">

        <!-- Table toolbar -->
        <div style="display:flex;align-items:center;gap:8px;padding:8px 12px;border-bottom:1px solid var(--border);flex-shrink:0;background:var(--paper)">
          <span style="font-size:12px;font-weight:500;flex:1">${summary.item_count} матеріалів у проекті</span>
          <button id="proj-add-btn" onclick="_toggleProjAdd('${projectId}')"
            style="padding:5px 12px;background:var(--teal);color:#fff;border:none;border-radius:var(--r);font-size:11px;font-weight:600;cursor:pointer">＋ Додати матеріал</button>
        </div>

        <!-- Add-item search panel (hidden by default) -->
        <div id="proj-add-panel" style="display:none;padding:10px 12px;border-bottom:1px solid var(--border);background:var(--paper2);flex-shrink:0">
          <div style="display:flex;gap:8px;align-items:center">
            <input id="proj-add-search" type="text" placeholder="Пошук матеріалу зі бази…"
              oninput="_renderProjAddResults('${projectId}')"
              style="flex:1;padding:6px 10px;border:1px solid var(--border);border-radius:var(--r);font-size:12px;font-family:var(--sans);background:var(--white)"
              autocomplete="off">
            <button onclick="_toggleProjAdd('${projectId}')"
              style="padding:5px 10px;background:transparent;color:var(--ink3);border:1px solid var(--border);border-radius:var(--r);font-size:12px;cursor:pointer">✕</button>
          </div>
          <div id="proj-add-results" style="margin-top:8px;max-height:180px;overflow-y:auto"></div>
        </div>

        <!-- Scrollable table -->
        <div style="flex:1;overflow-y:auto">
          <table style="width:100%;border-collapse:collapse">
            <thead><tr style="position:sticky;top:0;background:var(--paper);z-index:1">
              <th style="text-align:left;padding:8px 12px;font-size:10px;text-transform:uppercase;letter-spacing:0.07em;font-weight:600;white-space:nowrap">Матеріал</th>
              <th style="text-align:center;padding:8px 6px;font-size:10px;text-transform:uppercase;letter-spacing:0.07em;white-space:nowrap">Од.</th>
              <th style="text-align:right;padding:8px 10px;font-size:10px;text-transform:uppercase;letter-spacing:0.07em;white-space:nowrap">К-сть</th>
              <th style="text-align:right;padding:8px 10px;font-size:10px;text-transform:uppercase;letter-spacing:0.07em;white-space:nowrap">Ціна кошт.</th>
              <th style="text-align:right;padding:8px 10px;font-size:10px;text-transform:uppercase;letter-spacing:0.07em;white-space:nowrap">Сума кошт.</th>
              <th style="text-align:right;padding:8px 10px;font-size:10px;text-transform:uppercase;letter-spacing:0.07em;white-space:nowrap">Мін. ціна</th>
              <th style="text-align:right;padding:8px 10px;font-size:10px;text-transform:uppercase;letter-spacing:0.07em;white-space:nowrap">Сума мін.</th>
              <th style="text-align:center;padding:8px 8px;font-size:10px;text-transform:uppercase;letter-spacing:0.07em;white-space:nowrap">Де знайдено</th>
              <th style="text-align:center;padding:8px 6px;font-size:10px;text-transform:uppercase;letter-spacing:0.07em;white-space:nowrap">Економія</th>
              <th style="width:32px"></th>
            </tr></thead>
            <tbody id="proj-items-tbody">${_buildProjItemsRows(items, projectId)}</tbody>
          </table>
        </div>
      </div>`;
  }

  function _buildProjItemsRows(items, projectId) {
    if (!items.length) {
      return `<tr><td colspan="10" style="text-align:center;padding:32px;color:var(--ink3);font-size:13px">
        Немає матеріалів — натисніть "＋ Додати матеріал"
      </td></tr>`;
    }
    return items.map(item => {
      const best  = item.best_price;
      const sup   = item.best_supplier ? (SUPPLIER_NAMES[item.best_supplier] || item.best_supplier) : '';
      const supUrl = item.suppliers?.[item.best_supplier]?.url || '';
      const saving = item.saving_pct;
      const savingColor = saving > 0 ? 'var(--teal)' : saving < 0 ? 'var(--danger)' : 'var(--ink3)';
      return `<tr style="border-top:1px solid var(--border)">
        <td style="padding:8px 12px;font-size:12px;font-weight:500;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(item.label)}">${esc(item.label)}</td>
        <td style="text-align:center;padding:8px 6px;font-size:11px;color:var(--ink3)">${esc(item.unit||'')}</td>
        <td style="text-align:right;padding:8px 10px;font-family:var(--mono);font-size:11px">${item.qty != null ? Number(item.qty).toLocaleString('uk-UA') : '—'}</td>
        <td style="text-align:right;padding:8px 10px;font-family:var(--mono);font-size:11px;color:var(--ink3)">${item.estimate_unit_price != null ? Number(item.estimate_unit_price).toLocaleString('uk-UA') : '—'}</td>
        <td style="text-align:right;padding:8px 10px;font-family:var(--mono);font-size:12px">${item.total_estimate != null ? Number(item.total_estimate).toLocaleString('uk-UA') : '—'}</td>
        <td style="text-align:right;padding:8px 10px;font-family:var(--mono);font-size:12px;font-weight:600;color:${best?'var(--teal)':'var(--ink3)'}">${best ? Number(best).toLocaleString('uk-UA') : '—'}</td>
        <td style="text-align:right;padding:8px 10px;font-family:var(--mono);font-size:12px;font-weight:600;color:var(--teal)">${item.total_best != null ? Number(item.total_best).toLocaleString('uk-UA') : '—'}</td>
        <td style="text-align:center;padding:8px 8px;font-size:10px">${sup ? (supUrl ? `<a href="${esc(supUrl)}" target="_blank" rel="noopener" style="color:var(--ink2);text-decoration:none;border-bottom:1px solid var(--border)">${esc(sup)}</a>` : esc(sup)) : '—'}</td>
        <td style="text-align:center;padding:8px 6px;font-size:11px;font-weight:600;color:${savingColor}">${saving != null ? (saving > 0 ? '+' : '') + saving + '%' : '—'}</td>
        <td style="text-align:center;padding:4px">
          <button onclick="_removeFromProject('${projectId}','${item.id}')"
            style="padding:3px 7px;background:transparent;color:var(--ink3);border:1px solid var(--border);border-radius:var(--r);font-size:10px;cursor:pointer;opacity:0.6"
            onmouseenter="this.style.opacity='1';this.style.color='var(--danger)';this.style.borderColor='var(--danger)'"
            onmouseleave="this.style.opacity='0.6';this.style.color='var(--ink3)';this.style.borderColor='var(--border)'"
            title="Видалити з проекту">✕</button>
        </td>
      </tr>`;
    }).join('');
  }

  function _toggleProjAdd(projectId) {
    const panel = document.getElementById('proj-add-panel');
    if (!panel) return;
    _projAddOpen = !_projAddOpen;
    panel.style.display = _projAddOpen ? 'block' : 'none';
    if (_projAddOpen) {
      const inp = document.getElementById('proj-add-search');
      if (inp) { inp.value = ''; inp.focus(); }
      _renderProjAddResults(projectId);
    }
  }

  function _renderProjAddResults(projectId) {
    const container = document.getElementById('proj-add-results');
    if (!container) return;
    const q = (document.getElementById('proj-add-search')?.value || '').trim().toLowerCase();
    const inProject = new Set(_projItems.map(i => i.id));

    let candidates = allItemsData.filter(i => i.monitorable);
    if (q) candidates = candidates.filter(i => i.label.toLowerCase().includes(q));
    candidates = candidates.slice(0, 40);

    if (!candidates.length) {
      container.innerHTML = `<div style="font-size:12px;color:var(--ink3);padding:8px 0">Нічого не знайдено</div>`;
      return;
    }

    container.innerHTML = candidates.map(item => {
      const already = inProject.has(item.id);
      return `<div style="display:flex;align-items:center;gap:8px;padding:5px 8px;border-radius:var(--r);${already?'opacity:0.45':''}">
        <span style="flex:1;font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(item.label)}">${esc(item.label)}</span>
        ${item.category ? `<span style="font-size:10px;color:var(--ink3);flex-shrink:0">${esc(item.category)}</span>` : ''}
        ${already
          ? `<span style="font-size:10px;color:var(--ink3);padding:3px 8px;border:1px solid var(--border);border-radius:var(--r)">вже є</span>`
          : `<button onclick="_addToProject('${projectId}','${item.id}',this)"
               style="padding:3px 10px;background:var(--teal);color:#fff;border:none;border-radius:var(--r);font-size:11px;cursor:pointer;flex-shrink:0">＋</button>`
        }
      </div>`;
    }).join('');
  }

  async function _addToProject(projectId, itemId, btn) {
    btn.disabled = true;
    btn.textContent = '…';
    await fetch(`/api/projects/${projectId}/items`, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ item_id: itemId })
    });
    const [items, summary] = await Promise.all([
      fetch(`/api/projects/${projectId}/items`).then(r => r.json()),
      fetch(`/api/projects/${projectId}/summary`).then(r => r.json()),
    ]);
    _projItems = items;
    const tbody = document.getElementById('proj-items-tbody');
    if (tbody) tbody.innerHTML = _buildProjItemsRows(items, projectId);
    _renderProjAddResults(projectId);
  }

  async function _removeFromProject(projectId, itemId) {
    await fetch(`/api/projects/${projectId}/items/${itemId}`, { method: 'DELETE' });
    const items = await fetch(`/api/projects/${projectId}/items`).then(r => r.json());
    _projItems = items;
    const tbody = document.getElementById('proj-items-tbody');
    if (tbody) tbody.innerHTML = _buildProjItemsRows(items, projectId);
  }

  function _queueProjectItems(projectId) {
    const ids = _projItems.filter(i => i.monitorable).map(i => i.id);
    if (!ids.length) { alert('У проекті немає матеріалів для моніторингу'); return; }
    // Open the "Проекти" monitor mode with this project preselected — the
    // queue loads in the imported file's order.
    monitorProjectId = projectId;
    modeQueues.project = [];   // force a fresh load for THIS project
    if (monitorMode === 'project') monitorQueue = modeQueues.project;
    const monBtn = [...document.querySelectorAll('.nav-btn')].find(b => b.textContent.includes('Моніторинг'));
    showPanel('monitor', monBtn);
    setMonitorMode('project');
  }

  async function deleteProject(id) {
    if (!confirm('Видалити проект? Матеріали залишаться у базі.')) return;
    await fetch(`/api/projects/${id}`, { method: 'DELETE' });
    if (activeProjectId === id) activeProjectId = null;
    await loadProjects();
  }

  // Populate project select when import tab is shown
  const origShowPanel = showPanel;

  // ── Price History ─────────────────────────────────────────────

  let priceHistoryCache = {};

  async function showPriceHistory(itemId, itemLabel) {
    let history;
    if (priceHistoryCache[itemId]) {
      history = priceHistoryCache[itemId];
    } else {
      history = await fetch(`/api/items/${itemId}/price-history`).then(r => r.json());
      priceHistoryCache[itemId] = history;
    }

    const supIds = Object.keys(history);
    if (!supIds.length) {
      alert('Історія цін порожня — запустіть моніторинг декілька разів');
      return;
    }

    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.45);z-index:9000;display:flex;align-items:center;justify-content:center';
    overlay.onclick = e => { if (e.target === overlay) overlay.remove(); };

    const modal = document.createElement('div');
    modal.style.cssText = 'background:var(--white,#fff);border-radius:12px;padding:24px;width:min(680px,90vw);max-height:80vh;overflow-y:auto;position:relative';

    const rows = supIds.map(sid => {
      const points = history[sid];
      if (!points || !points.length) return '';
      const prices = points.map(p => p.price);
      const minP   = Math.min(...prices);
      const maxP   = Math.max(...prices);
      const latest = prices[prices.length - 1];
      const spark  = sparkline(prices, 160, 36);
      const supName = SUPPLIER_NAMES[sid] || sid;
      const trend   = prices.length >= 2 ? prices[prices.length-1] - prices[prices.length-2] : 0;
      const trendStr = trend > 0 ? `<span style="color:#c0392b">▲${Number(Math.abs(trend)).toLocaleString('uk-UA')}</span>`
                     : trend < 0 ? `<span style="color:#1a6b5a">▼${Number(Math.abs(trend)).toLocaleString('uk-UA')}</span>`
                     : '<span style="color:#999">—</span>';
      return `<div style="display:flex;align-items:center;gap:14px;padding:10px 0;border-bottom:1px solid #eee">
        <div style="min-width:110px;font-size:12px;font-weight:600">${esc(supName)}</div>
        <div style="flex:0 0 160px">${spark}</div>
        <div style="font-size:11px;color:#666;min-width:80px">${minP.toLocaleString('uk-UA')} – ${maxP.toLocaleString('uk-UA')} ₴</div>
        <div style="font-family:monospace;font-size:13px;font-weight:700;min-width:80px">${latest.toLocaleString('uk-UA')} ₴</div>
        <div style="font-size:11px;min-width:60px">${trendStr}</div>
        <div style="font-size:10px;color:#999">${points.length} замірів</div>
      </div>`;
    }).filter(Boolean).join('');

    modal.innerHTML = `
      <button onclick="this.closest('[style*=fixed]').remove()" style="position:absolute;top:12px;right:14px;background:none;border:none;font-size:18px;cursor:pointer;color:#999">×</button>
      <div style="font-size:15px;font-weight:600;margin-bottom:16px">Історія цін: ${esc(itemLabel)}</div>
      ${rows || '<div style="color:#999;text-align:center;padding:24px">Немає даних</div>'}`;

    overlay.appendChild(modal);
    document.body.appendChild(overlay);
  }

  function sparkline(values, width, height) {
    if (!values || values.length < 2) {
      return `<svg width="${width}" height="${height}" style="display:block"><line x1="0" y1="${height/2}" x2="${width}" y2="${height/2}" stroke="#ddd" stroke-width="1.5"/></svg>`;
    }
    const mn = Math.min(...values);
    const mx = Math.max(...values);
    const range = mx - mn || 1;
    const pad = 4;
    const pts = values.map((v, i) => {
      const x = pad + (i / (values.length - 1)) * (width - pad * 2);
      const y = height - pad - ((v - mn) / range) * (height - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    const lastX = parseFloat(pts.split(' ').pop().split(',')[0]);
    const lastY = parseFloat(pts.split(' ').pop().split(',')[1]);
    const color = values[values.length-1] <= values[0] ? '#1a6b5a' : '#c0392b';
    return `<svg width="${width}" height="${height}" style="display:block">
      <polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"/>
      <circle cx="${lastX}" cy="${lastY}" r="3" fill="${color}"/>
    </svg>`;
  }

  // Load projects on startup (for import select)
  loadProjects();
