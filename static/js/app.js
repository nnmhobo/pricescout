// ── State ────────────────────────────────────────────────────
  let allItems  = [];
  let activeItemId = null;
  let importItems   = [];
  let selectedNames = new Set();
  let allItemsData  = [];
  let monitorQueue  = [];
  let monitorDone   = 0;
  let monitorMode   = 'single';
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

  function toggleAllSuppliers() {
    const checkboxes = [...document.querySelectorAll('[id^="chk-"]:not(:disabled)')];
    const anyOn = checkboxes.some(c => c.checked);
    checkboxes.forEach(c => { c.checked = !anyOn; });
    const btn = document.getElementById('btn-sup-all');
    if (btn) btn.textContent = anyOn ? 'Увімкнути всі' : 'Вимкнути всі';
    if (document.getElementById('queue-count')) renderMonitorTab();
  }

  loadItems();

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
    selectedNames = new Set(d.items.map(i => i.name));
    document.getElementById('imp-total').textContent  = d.total;
    document.getElementById('imp-retail').textContent = d.retail;
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

    // Show item banner in Журнал panel
    const logBanner = document.getElementById('log-item-banner');
    const logLabel  = document.getElementById('log-item-label');
    const logStatus = document.getElementById('log-item-status');
    if (logBanner) { logLabel.textContent = label; logStatus.textContent = 'Виконується…'; logBanner.style.display = 'flex'; }

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
      document.getElementById('run-btn').disabled = true;
      document.getElementById('stop-btn').style.display = '';
      document.getElementById('stop-btn').disabled = false;
      document.getElementById('stop-btn').textContent = '◼ Зупинити';
      setExcelBtn(false);
      showPanel('log', document.querySelector('.nav-btn'));
      poll();
    });
  }

  // ── Poll ─────────────────────────────────────────────────────
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
        document.getElementById('run-btn').disabled = false;
        document.getElementById('stop-btn').style.display = 'none';
        // Update banners with result count
        const statusText = d.count > 0 ? d.count + ' результатів' : 'Не знайдено';
        const logStatus = document.getElementById('log-item-status');
        const monStatus = document.getElementById('single-item-status');
        if (logStatus) logStatus.textContent = statusText;
        if (monStatus) monStatus.textContent = statusText;
        // Always load results (covers manual stop with partial results)
        if (d.count > 0) { loadResults(); setExcelBtn(true); }
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
      // Stash for the comment editor (needs current comment as default).
      window._currentResults = items;
      document.getElementById('cnt-badge').textContent = ' (' + items.length + ')';
      const badgeTotal = document.getElementById('badge-total');
      if (badgeTotal) badgeTotal.textContent = items.length + ' постачальників';
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
          <td colspan="9" style="background:var(--paper2);font-weight:600;color:var(--ink);padding:8px 12px;font-size:12px;border-top:2px solid var(--border2)">
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
          const priceStyle = medal ? ` style="font-weight:600;color:${medal.text}"` : '';
          const medalBadge = medal ? `<span title="${medal.label}" style="margin-right:6px;font-size:14px">${medal.medal}</span>` : '';
          const itemId = esc(i.item_id || '');
          const supplierId = esc(i.supplier_id || '');
          const canEdit = itemId && supplierId;
          // Manual-price indicator: italic + tooltip carries the original.
          const manualMark = i.manual_price != null
            ? `<span title="${esc('Виправлено вручну. Оригінал: ' + (i.original_price != null ? Number(i.original_price).toLocaleString('uk-UA') + ' ₴' : '—'))}" style="margin-left:4px;font-size:10px;color:var(--ink3);font-style:italic">✎</span>`
            : '';
          const commentMark = i.comment
            ? `<span title="${esc(i.comment)}" style="margin-left:6px;font-size:13px">💬</span>`
            : '';
          const priceCell = canEdit
            ? `<a href="#" onclick="return editResultPrice('${itemId}','${supplierId}',${i.manual_price != null ? Number(i.manual_price) : (i.price != null ? Number(i.price) : 'null')})" style="text-decoration:none;color:inherit;border-bottom:1px dotted var(--border2)" title="Натисніть, щоб виправити ціну">${i.price ? Number(i.price).toLocaleString('uk-UA')+'<span class="curr">₴</span>' : '—'}</a>${manualMark}`
            : `${i.price ? Number(i.price).toLocaleString('uk-UA')+'<span class="curr">₴</span>' : '—'}${manualMark}`;
          const commentBtn = canEdit
            ? `<button onclick="editResultComment('${itemId}','${supplierId}')" style="background:transparent;border:none;cursor:pointer;padding:2px 4px;font-size:13px;color:var(--ink3)" title="${i.comment ? 'Редагувати коментар' : 'Додати коментар'}">${i.comment ? '💬' : '🗨️'}</button>`
            : commentMark;
          rows.push(`<tr${rowStyle}>
              <td class="td-name">${medalBadge}<a href="${esc(i.url||'#')}" target="_blank" rel="noopener">${esc(i.name||'—')}</a>${commentMark}</td>
              <td class="td-price"${priceStyle}>${priceCell}</td>
              <td class="td-unit">${esc(i.unit||'—')}</td>
              <td class="td-qty" style="font-family:var(--mono);font-size:11px">${i.qty != null ? Number(i.qty).toLocaleString('uk-UA') : '—'}</td>
              <td class="td-unit-est" style="font-family:var(--mono);font-size:11px;color:var(--ink3)">${esc(i.unit_estimate||'—')}</td>
              <td class="td-total" style="font-family:var(--mono);font-size:12px;font-weight:600;color:var(--teal)">${i.total_price != null ? Number(i.total_price).toLocaleString('uk-UA')+' ₴' : '—'}</td>
              <td class="td-brand">${esc(i.brand||'—')}</td>
              <td class="td-sup">${i.url ? `<a href="${esc(i.url)}" target="_blank" rel="noopener" style="color:var(--ink2);text-decoration:none;border-bottom:1px solid var(--border2)">${esc(i.supplier||'—')}</a>` : `<span>${esc(i.supplier||'—')}</span>`}${i.seller_note ? `<span style="font-size:10px;color:var(--ink3);margin-left:5px;font-family:var(--mono)">${esc(i.seller_note)}</span>` : ''}</td>
              <td class="td-sku">${esc(i.sku||'—')}</td>
              <td class="td-actions" style="text-align:center;width:36px">${commentBtn}</td>
            </tr>`);
        });
      });
      document.getElementById('tbl-wrap').innerHTML = `
        <table>
          <thead><tr>
            <th>Назва товару</th><th>Ціна за од.</th><th>Од.</th>
            <th>К-сть</th><th>Од. кошт.</th><th>Загальна</th>
            <th>Бренд</th><th>Постачальник</th><th>Артикул</th><th></th>
          </tr></thead>
          <tbody>${rows.join('')}</tbody>
        </table>`;
    });
  }

  // ── Result hand-edits ────────────────────────────────────────
  // Two endpoints user can hit on any result row:
  //   - editResultPrice — corrects a misparsed unit price (or clears the
  //     override with an empty input).
  //   - editResultComment — attaches a free-form note that rides along
  //     into the Excel export.
  function editResultPrice(itemId, supplierId, currentPrice) {
    const current = (currentPrice == null || Number.isNaN(currentPrice)) ? '' : String(currentPrice);
    const next = window.prompt(
      'Введіть виправлену ціну в грн.\nПорожньо — відновити автоматичну ціну.',
      current
    );
    if (next === null) return false;  // cancelled
    const trimmed = next.trim();
    let payload;
    if (trimmed === '') {
      payload = { manual_price: null };
    } else {
      const num = Number(trimmed.replace(',', '.'));
      if (!Number.isFinite(num) || num <= 0) {
        alert('Невалідна ціна — введіть число більше нуля.');
        return false;
      }
      payload = { manual_price: num };
    }
    _patchResult(itemId, supplierId, payload);
    return false;
  }

  function editResultComment(itemId, supplierId) {
    const row = (window._currentResults || []).find(r =>
      String(r.item_id) === String(itemId) && String(r.supplier_id) === String(supplierId)
    );
    const current = (row && row.comment) || '';
    const next = window.prompt(
      'Коментар до позиції (буде експортований у Excel).\nПорожньо — видалити коментар.',
      current
    );
    if (next === null) return;
    _patchResult(itemId, supplierId, { comment: next.trim() || null });
  }

  function _patchResult(itemId, supplierId, payload) {
    fetch(`/api/results/${encodeURIComponent(itemId)}/${encodeURIComponent(supplierId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then(r => r.json())
      .then(d => {
        if (d.error) { alert(d.error); return; }
        loadResults();  // re-render with the spliced override
      })
      .catch(() => alert('Не вдалося оновити рядок.'));
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
        selectedNames = new Set(importItems.map(i => i.name));
        document.getElementById('imp-total').textContent = d.total;
        document.getElementById('imp-retail').textContent = d.retail;
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
        <td style="font-family:var(--mono);font-size:11px">${i.qty||''}</td>
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
    const project_id = projectSel ? (projectSel.value || null) : null;
    const d = await fetch('/api/kostoris/import', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ items, project_id })
    }).then(r => r.json());

    const skippedMsg = d.skipped ? `, вже існує: ${d.skipped}` : '';
    const projMsg    = d.project_id ? ' → проект' : '';
    document.getElementById('import-result').textContent = `Додано: ${d.added}${skippedMsg}${projMsg}`;
    loadItems();
    if (d.added > 0) { loadItemsTab(); loadProjects(); }
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
    if (chkAll) chkAll.checked = allItemsData.length > 0 && selectedItemIds.size === allItemsData.length;
  }

  function toggleItemSelection(id, checked) {
    if (checked) selectedItemIds.add(id); else selectedItemIds.delete(id);
    updateItemsBatchBar();
  }

  function toggleAllItemsSelection(checked) {
    const search = document.getElementById('items-search').value.trim().toLowerCase();
    const srcFilter = document.getElementById('items-filter-source').value;
    const catFilter = document.getElementById('items-filter-cat').value;
    allItemsData
      .filter(i => {
        if (search && !i.label.toLowerCase().includes(search)) return false;
        if (srcFilter && i.source !== srcFilter) return false;
        if (catFilter && i.category !== catFilter) return false;
        return true;
      })
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

  function renderItemsTab() {
    const search = document.getElementById('items-search').value.trim().toLowerCase();
    const srcFilter = document.getElementById('items-filter-source').value;
    const catFilter = document.getElementById('items-filter-cat').value;

    const monFilter = document.getElementById('items-filter-mon')?.value || '';
    const filtered = allItemsData.filter(i => {
      if (search && !i.label.toLowerCase().includes(search)) return false;
      if (srcFilter && i.source !== srcFilter) return false;
      if (catFilter && i.category !== catFilter) return false;
      if (monFilter === 'yes' && !i.monitorable) return false;
      if (monFilter === 'no'  &&  i.monitorable) return false;
      return true;
    });

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
      const chip = document.getElementById('log-item-label');
      if (chip) { chip.textContent = label; chip.style.display = ''; }
      const logBtn = [...document.querySelectorAll('.nav-btn')].find(b => b.textContent.includes('Журнал'));
      showPanel('log', logBtn);
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
    const label = input.value.trim();
    if (!label) return;
    fetch('/api/items', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ label })
    }).then(r => r.json()).then(d => {
      if (d.error) {
        msg.style.color = 'var(--danger)';
        msg.textContent = d.error;
      } else {
        msg.style.color = 'var(--teal)';
        msg.textContent = '✓ Додано: ' + d.label;
        input.value = '';
        loadItemsTab();
        loadItems();
      }
      setTimeout(() => msg.textContent = '', 3000);
    });
  }

  // ── Monitoring ───────────────────────────────────────────────

  function setMonitorMode(mode) {
    if (mode === 'single') {
      const logBtn = [...document.querySelectorAll('.nav-btn')].find(b => b.textContent.includes('Журнал'));
      showPanel('log', logBtn);
      return;
    }
    monitorMode = 'batch';
    document.getElementById('monitor-single').style.display = 'none';
    document.getElementById('monitor-batch').style.display = 'flex';
    document.getElementById('mode-single').style.background = 'transparent';
    document.getElementById('mode-single').style.color = 'var(--ink3)';
    document.getElementById('mode-batch').style.background = 'var(--gold)';
    document.getElementById('mode-batch').style.color = '#fff';
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
    renderMonitorTab();
  }

  function onBatchCountCustomInput() {
    // Re-render on every keystroke so the time estimate tracks the live value.
    renderMonitorTab();
  }

  function renderMonitorTab() {
    const search = (document.getElementById('monitor-search')?.value || '').trim().toLowerCase();
    const filtered = monitorQueue.filter(i => !search || i.label.toLowerCase().includes(search));
    const el = id => document.getElementById(id);

    if (!el('queue-count')) return;
    const qLen   = monitorQueue.length;
    const supCnt = getEnabledIds().length;
    el('queue-count').textContent = qLen;
    el('queue-done').textContent  = monitorDone;
    if (el('queue-sups')) el('queue-sups').textContent = supCnt || '—';

    // Category-aware estimate: categories with HVAC/automation/electrical get fewer suppliers
    // Mirrors category_routing.py logic on the frontend
    const SKIP_CATS = new Set([
      'Теплопостачання та опалення','Вентиляція та кондиціонування',
      'Теплотехнічне устаткування','Автоматизація (КВП)',
      'Енергоносії','Спеціальні роботи',
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
      if (SKIP_CATS.has(cat))          sups = 0;
      else if (REDUCED_CATS.has(cat))  sups = Math.min(supCnt, 3);
      else if (PLUMBING_CATS.has(cat)) sups = Math.min(supCnt, 6);
      else                              sups = supCnt;
      if (sups > 0) totalSecs += 35 + Math.max(0, sups - 3) * 12;
    }

    const mins = Math.ceil(totalSecs / 60 / Math.max(1, parallel));
    el('queue-time').textContent = itemsToRun.length ? `~${mins}` : '—';

    el('btn-run-batch').disabled = qLen === 0 || itemsToRun.length === 0;

    el('monitor-tbody').innerHTML = filtered.map((item, idx) => {
      const prices  = Object.values(item.suppliers || {}).filter(s => s.found && s.last_price).map(s => s.last_price);
      const best    = prices.length ? Math.min(...prices).toLocaleString('uk-UA') + ' ₴' : '—';
      const checked = Object.values(item.suppliers || {}).map(s => s.last_checked).filter(Boolean).sort().reverse()[0] || '—';
      const done    = item._done;
      const SKIP_CATS_ROW = new Set(['Теплопостачання та опалення','Вентиляція та кондиціонування','Теплотехнічне устаткування','Автоматизація (КВП)','Енергоносії','Спеціальні роботи','Вантажопідйомне устаткування','Інше устаткування']);
      const willSearch = item.monitorable !== false && !SKIP_CATS_ROW.has(item.category || '');
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
  }

  function addToQueue(item, skipRender = false) {
    if (monitorQueue.find(i => i.id === item.id)) return;
    monitorQueue.push(item);
    if (!skipRender) renderMonitorTab();
  }

  function removeFromQueue(id) {
    monitorQueue = monitorQueue.filter(i => i.id !== id);
    renderMonitorTab();
  }

  async function addAllToQueue() {
    const items = await fetch('/api/items').then(r => r.json());
    items.forEach(i => addToQueue(i, true));
    renderMonitorTab();
  }

  function clearQueue() {
    monitorQueue = [];
    monitorDone = 0;
    renderMonitorTab();
  }

  let batchRunning = false;
  let batchStopped = false;

  function stopBatch() {
    batchStopped = true;
    fetch('/api/stop', { method: 'POST' }).then(() => {
      const waitAndLoad = () => fetch('/api/status').then(r => r.json()).then(s => {
        if (s.running) { setTimeout(waitAndLoad, 800); return; }
        if (s.count > 0) { loadResults(); setExcelBtn(true); document.getElementById('cnt-badge').textContent = ' (' + s.count + ')'; }
      });
      setTimeout(waitAndLoad, 800);
    });
    document.getElementById('btn-stop-batch').textContent = '◼ Зупиняємо…';
    document.getElementById('btn-stop-batch').disabled = true;
  }

  async function runBatch() {
    if (!monitorQueue.length) return;
    if (batchRunning) return;
    const activeSups = getEnabledIds().map(id => ({id, enabled: true}));
    if (!activeSups.length) { alert('Оберіть постачальників у лівій панелі'); return; }

    batchRunning = true;
    batchStopped = false;
    document.getElementById('btn-run-batch').disabled = true;
    document.getElementById('btn-stop-batch').style.display = '';
    document.getElementById('btn-stop-batch').disabled = false;
    document.getElementById('btn-stop-batch').textContent = '◼ Зупинити';
    document.getElementById('batch-log-wrap').style.display = 'flex';
    document.getElementById('batch-log-body').innerHTML = '';
    monitorDone = 0;
    monitorQueue.forEach(i => i._done = false);

    const logEl = document.getElementById('batch-log-body');
    // Cap how many log <div>s live in the DOM at once. A full 603-item
    // batch emits tens of thousands of lines; keeping them all (plus a
    // forced reflow per line) freezes the page. Old lines scroll off the
    // top and are dropped — the viewer keeps a bounded scrollback buffer.
    const MAX_LOG_LINES = 800;
    let lastLogLen = 0;
    function appendBatchLog(lines) {
      if (!lines || !lines.length) return;
      // A single poll can return more lines than we'd ever keep on screen —
      // only the tail is worth rendering.
      if (lines.length > MAX_LOG_LINES) lines = lines.slice(-MAX_LOG_LINES);
      const frag = document.createDocumentFragment();
      for (const msg of lines) {
        const div = document.createElement('div');
        div.className = 'tl';
        div.textContent = msg;
        frag.appendChild(div);
      }
      logEl.appendChild(frag);
      // Trim from the top so the node count stays bounded.
      while (logEl.childElementCount > MAX_LOG_LINES) {
        logEl.removeChild(logEl.firstChild);
      }
      // One reflow per batch instead of one per line.
      logEl.scrollTop = logEl.scrollHeight;
    }
    function batchLog(msg) { appendBatchLog([msg]); }

    const limit    = getBatchLimit();
    const parallel = getBatchParallel();
    const payload = {
      item_ids: monitorQueue.map(i => i.id),
      suppliers: activeSups,
      parallel_items: parallel,
    };
    if (limit > 0) payload.limit = limit;

    const resp = await fetch('/api/scrape/batch', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    }).then(r => r.json());

    if (resp.error) {
      batchLog(`⚠ ${resp.error}`);
      batchRunning = false;
      batchStopped = false;
      document.getElementById('btn-run-batch').disabled = false;
      document.getElementById('btn-stop-batch').style.display = 'none';
      return;
    }

    const requested = resp.requested_count ?? resp.item_count;
    const slicedNote = (requested && requested !== resp.item_count)
      ? ` (з ${requested})` : '';
    batchLog(`Запущено: ${resp.item_count} матеріалів${slicedNote} | ${resp.supplier_count} постачальників | паралельно: ${resp.parallel_items}`);
    await new Promise(r => setTimeout(r, 2000));

    lastLogLen = 0;
    while (true) {
      // Incremental fetch: ask only for log lines we haven't seen yet.
      // The backend log grows past 100 lines on big batches, so slicing
      // a capped response client-side used to freeze the log view.
      const s = await fetch('/api/status?log_offset=' + lastLogLen).then(r => r.json());
      appendBatchLog(s.log);
      lastLogLen = s.log_total ?? (lastLogLen + s.log.length);
      if (s.error) { batchLog(`⚠ ${s.error}`); break; }
      if (!s.running) break;
      if (batchStopped) break;
      await new Promise(r => setTimeout(r, 1500));
    }

    const updated = await fetch('/api/items').then(r => r.json());
    monitorQueue = monitorQueue.map(q => ({...(updated.find(u => u.id === q.id) || q), _done: true}));
    batchRunning = false;
    batchStopped = false;
    document.getElementById('btn-run-batch').disabled = false;
    document.getElementById('btn-stop-batch').style.display = 'none';
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
      renderAvailabilityCoverage(data.coverage);
      renderAvailability();
    } catch(e) {
      console.error('loadAvailability error:', e);
    }
  }

  function renderAvailabilityCoverage(coverage) {
    const el = document.getElementById('avail-coverage');
    if (!el) return;
    const supIds = Object.keys(SUPPLIER_NAMES);
    el.innerHTML = supIds.map(sid => {
      const c = coverage[sid] || { checked: 0, found: 0 };
      const pct = c.checked > 0 ? Math.round(c.found / c.checked * 100) : 0;
      const color = pct >= 70 ? 'var(--teal)' : pct >= 30 ? 'var(--gold)' : 'var(--danger)';
      return `<div style="display:flex;flex-direction:column;align-items:center;padding:8px 12px;background:var(--white);border:1px solid var(--border);border-radius:var(--r-lg);min-width:90px">
        <span style="font-family:var(--serif);font-size:20px;line-height:1.1;color:${color}">${pct}%</span>
        <span style="font-size:10px;font-weight:500;color:var(--ink2);margin-top:2px">${SUPPLIER_NAMES[sid]}</span>
        <span style="font-size:9px;color:var(--ink3)">${c.found}/${c.checked} знайдено</span>
      </div>`;
    }).join('');
  }

  function renderAvailability() {
    const items = availabilityData.items || [];
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

    thead.innerHTML = `<tr>
      <th style="position:sticky;top:0;background:var(--paper);z-index:2;min-width:200px">Матеріал</th>
      <th style="position:sticky;top:0;background:var(--paper);z-index:2;width:100px">Категорія</th>
      ${supIds.map(sid => `<th style="position:sticky;top:0;background:var(--paper);z-index:2;text-align:center;font-size:10px;min-width:70px;writing-mode:vertical-lr;transform:rotate(180deg);padding:6px 2px">${esc(SUPPLIER_NAMES[sid])}</th>`).join('')}
      <th style="position:sticky;top:0;background:var(--paper);z-index:2;text-align:center;width:60px">Всього</th>
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
      allProjects.map(p => `<option value="${esc(p.id)}" ${p.id===cur?'selected':''}>${esc(p.name)} (${p.item_count} поз.)</option>`).join('');
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
    wrap.innerHTML = allProjects.map(p => `
      <div style="display:flex;align-items:center;gap:12px;padding:14px 16px;background:var(--white);border:1px solid var(--border);border-radius:var(--r-lg);cursor:pointer" onclick="viewProject('${p.id}')">
        <div style="flex:1;min-width:0">
          <div style="font-size:13px;font-weight:600;color:var(--ink)">${esc(p.name)}</div>
          ${p.description ? `<div style="font-size:11px;color:var(--ink3);margin-top:2px">${esc(p.description)}</div>` : ''}
          <div style="font-size:10px;color:var(--ink3);margin-top:4px">Створено: ${esc(p.created)} · ${p.item_count} матеріалів</div>
        </div>
        <div style="display:flex;gap:8px;flex-shrink:0">
          <a href="/api/projects/${esc(p.id)}/export" download style="padding:6px 12px;background:var(--teal-light);color:var(--teal);border:none;border-radius:var(--r);font-size:11px;font-weight:600;cursor:pointer;text-decoration:none;white-space:nowrap">↓ Excel</a>
          <button onclick="event.stopPropagation();deleteProject('${p.id}')" style="padding:6px 10px;background:transparent;color:var(--ink3);border:1px solid var(--border);border-radius:var(--r);font-size:11px;cursor:pointer">✕</button>
        </div>
      </div>`).join('');
  }

  async function viewProject(projectId) {
    activeProjectId = projectId;
    const listWrap   = document.getElementById('project-list-wrap');
    const detailWrap = document.getElementById('project-detail-wrap');
    listWrap.style.display   = 'none';
    detailWrap.style.display = 'flex';

    // Fetch project + items + summary
    const [project, items, summary] = await Promise.all([
      fetch(`/api/projects/${projectId}`).then(r => r.json()),
      fetch(`/api/projects/${projectId}/items`).then(r => r.json()),
      fetch(`/api/projects/${projectId}/summary`).then(r => r.json()),
    ]);

    const fmt = n => n != null ? Number(n).toLocaleString('uk-UA', {maximumFractionDigits:0}) : '—';

    detailWrap.innerHTML = `
      <div style="display:flex;align-items:center;gap:10px;flex-shrink:0">
        <button onclick="renderProjectsList();document.getElementById('project-list-wrap').style.display='flex';document.getElementById('project-detail-wrap').style.display='none'"
          style="padding:6px 12px;background:transparent;color:var(--ink3);border:1px solid var(--border);border-radius:var(--r);font-size:11px;cursor:pointer">← Назад</button>
        <div style="flex:1">
          <div style="font-size:15px;font-weight:600">${esc(project.name)}</div>
          ${project.description ? `<div style="font-size:11px;color:var(--ink3)">${esc(project.description)}</div>` : ''}
        </div>
        <a href="/api/projects/${esc(projectId)}/export" download style="padding:7px 14px;background:var(--teal);color:#fff;border:none;border-radius:var(--r);font-size:12px;font-weight:600;cursor:pointer;text-decoration:none;white-space:nowrap">↓ Експорт Excel</a>
      </div>

      <!-- Summary KPIs -->
      <div style="display:flex;gap:8px;flex-wrap:wrap;flex-shrink:0">
        <div style="flex:1;min-width:120px;padding:10px 14px;background:var(--white);border:1px solid var(--border);border-radius:var(--r-lg)">
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:0.08em;color:var(--ink3)">Матеріалів</div>
          <div style="font-family:var(--serif);font-size:22px;line-height:1.2">${summary.item_count}</div>
          <div style="font-size:10px;color:var(--ink3)">${summary.items_with_price} з цінами</div>
        </div>
        <div style="flex:1;min-width:120px;padding:10px 14px;background:var(--white);border:1px solid var(--border);border-radius:var(--r-lg)">
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:0.08em;color:var(--ink3)">Сума кошторис</div>
          <div style="font-family:var(--serif);font-size:22px;line-height:1.2">${fmt(summary.total_estimate)}</div>
          <div style="font-size:10px;color:var(--ink3)">грн</div>
        </div>
        <div style="flex:1;min-width:120px;padding:10px 14px;background:var(--white);border:1px solid var(--border);border-radius:var(--r-lg)">
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:0.08em;color:var(--ink3)">Сума за мін. цінами</div>
          <div style="font-family:var(--serif);font-size:22px;line-height:1.2;color:var(--teal)">${fmt(summary.total_best)}</div>
          <div style="font-size:10px;color:var(--ink3)">грн</div>
        </div>
        <div style="flex:1;min-width:120px;padding:10px 14px;background:${summary.saving>0?'var(--teal-light)':'var(--white)'};border:1px solid var(--border);border-radius:var(--r-lg)">
          <div style="font-size:10px;text-transform:uppercase;letter-spacing:0.08em;color:var(--ink3)">Економія</div>
          <div style="font-family:var(--serif);font-size:22px;line-height:1.2;color:${summary.saving>0?'var(--teal)':'var(--ink3)'}">${fmt(summary.saving)}</div>
          <div style="font-size:10px;color:var(--ink3)">${summary.saving_pct}%</div>
        </div>
      </div>

      <!-- Items table -->
      <div style="flex:1;min-height:0;border:1px solid var(--border);border-radius:var(--r-lg);overflow-y:auto;background:var(--white)">
        <table style="width:100%;border-collapse:collapse">
          <thead><tr style="position:sticky;top:0;background:var(--paper);z-index:1">
            <th style="text-align:left;padding:8px 12px;font-size:10px;text-transform:uppercase;letter-spacing:0.08em;font-weight:600">Матеріал</th>
            <th style="text-align:center;padding:8px 6px;font-size:10px;text-transform:uppercase;letter-spacing:0.08em">Од.</th>
            <th style="text-align:right;padding:8px 10px;font-size:10px;text-transform:uppercase;letter-spacing:0.08em">К-сть</th>
            <th style="text-align:right;padding:8px 10px;font-size:10px;text-transform:uppercase;letter-spacing:0.08em">Ціна кошт.</th>
            <th style="text-align:right;padding:8px 10px;font-size:10px;text-transform:uppercase;letter-spacing:0.08em">Сума кошт.</th>
            <th style="text-align:right;padding:8px 10px;font-size:10px;text-transform:uppercase;letter-spacing:0.08em">Мін. ціна</th>
            <th style="text-align:right;padding:8px 10px;font-size:10px;text-transform:uppercase;letter-spacing:0.08em">Сума мін.</th>
            <th style="text-align:center;padding:8px 6px;font-size:10px;text-transform:uppercase;letter-spacing:0.08em">Де знайдено</th>
            <th style="text-align:center;padding:8px 6px;font-size:10px;text-transform:uppercase;letter-spacing:0.08em">Економія</th>
          </tr></thead>
          <tbody>${items.map(item => {
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
              <td style="text-align:center;padding:8px 6px;font-size:10px">${sup ? (supUrl ? `<a href="${esc(supUrl)}" target="_blank" rel="noopener" style="color:var(--ink2);text-decoration:none;border-bottom:1px solid var(--border)">${esc(sup)}</a>` : esc(sup)) : '—'}</td>
              <td style="text-align:center;padding:8px 6px;font-size:11px;font-weight:600;color:${savingColor}">${saving != null ? (saving > 0 ? '+' : '') + saving + '%' : '—'}</td>
            </tr>`;
          }).join('')}</tbody>
        </table>
      </div>`;
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

    // Build simple overlay modal
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
