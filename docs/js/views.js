/**
 * View rendering module
 */
const Views = (() => {

  function formatPrice(val) {
    if (val == null) return '-';
    return val.toLocaleString() + '円';
  }

  function formatTime(isoStr) {
    if (!isoStr) return '-';
    const d = new Date(isoStr);
    const mo = d.getMonth() + 1;
    const da = d.getDate();
    const h = String(d.getHours()).padStart(2, '0');
    const m = String(d.getMinutes()).padStart(2, '0');
    return `${mo}/${da} ${h}:${m}`;
  }

  function formatTimeShort(isoStr) {
    if (!isoStr) return '-';
    const d = new Date(isoStr);
    const h = String(d.getHours()).padStart(2, '0');
    const m = String(d.getMinutes()).padStart(2, '0');
    return `${h}:${m}`;
  }

  function badgeClass(status) {
    switch (status) {
      case '利益あり': return 'badge-profit';
      case '薄利': return 'badge-marginal';
      case 'Amazon未登録': return 'badge-unregistered';
      default: return '';
    }
  }

  function rankClass(rank) {
    return rank ? `rank-${rank}` : '';
  }

  /** Render a single product card */
  function renderItemCard(item) {
    const localClass = item.has_local ? ' local' : '';
    const badge = badgeClass(item.status);
    const profitDisplay = item.profit != null
      ? `<span class="item-profit">+${formatPrice(item.profit)}</span>`
      : '';
    const localFlag = item.has_local
      ? `<div class="item-local-flag">秋田在庫あり${item.local_stores ? ': ' + item.local_stores : ''}</div>`
      : '';
    const stockRank = item.stock_rank
      ? `<span class="stock-rank ${rankClass(item.stock_rank)}">${item.stock_rank}</span>`
      : '';

    return `
      <div class="item-card${localClass}" data-id="${item.id}">
        <div class="item-card-header">
          <div class="item-title">${escapeHtml(item.title || '不明')}</div>
          <span class="item-badge ${badge}">${escapeHtml(item.status)}</span>
        </div>
        <div class="item-meta">
          <span>BO: <span class="item-meta-value">${formatPrice(item.price)}</span></span>
          <span>Amazon: <span class="item-meta-value">${formatPrice(item.amazon_used)}</span></span>
          ${profitDisplay}
          <span>在庫: <span class="item-meta-value">${item.total_stock ?? '-'}店</span>${stockRank}</span>
        </div>
        ${localFlag}
      </div>
    `;
  }

  /** Render dashboard view */
  function renderDashboard() {
    const stats = DataStore.getStats();

    document.getElementById('stat-profit-count').textContent = stats.profitCount;
    document.getElementById('stat-local-count').textContent = stats.localCount;
    document.getElementById('stat-last-run').textContent = formatTimeShort(stats.lastRun);
    document.getElementById('stat-tokens').textContent = stats.tokensLeft ?? '-';

    const topItems = Filters.topProfitItems(DataStore.getAllItems(), 5);
    const container = document.getElementById('top-items');

    if (topItems.length === 0) {
      container.innerHTML = '<div class="empty-state">利益商品がまだありません</div>';
      return;
    }

    container.innerHTML = topItems.map(renderItemCard).join('');
    _bindCardClicks(container);
  }

  /** Render product list view */
  function renderProducts(status = 'all', region = 'all', sortBy = 'profit') {
    const items = DataStore.getAllItems();
    const filtered = Filters.filterItems(items, status, region);
    const sorted = Filters.sortItems(filtered, sortBy);
    const container = document.getElementById('product-list');

    if (sorted.length === 0) {
      container.innerHTML = '<div class="empty-state">条件に一致する商品がありません</div>';
      return;
    }

    container.innerHTML = sorted.map(renderItemCard).join('');
    _bindCardClicks(container);
  }

  /** Render history view */
  function renderHistory() {
    const index = DataStore.getIndex();
    const container = document.getElementById('history-list');

    if (index.length === 0) {
      container.innerHTML = '<div class="empty-state">実行履歴がありません</div>';
      return;
    }

    container.innerHTML = index.map(entry => {
      const profitClass = entry.profit_count > 0 ? 'history-stat-profit' : '';
      return `
        <div class="history-card">
          <div class="history-time">${formatTime(entry.timestamp)}</div>
          <div class="history-stats">
            <span>合計: <span class="history-stat-value">${entry.total_items}件</span></span>
            <span>利益: <span class="history-stat-value ${profitClass}">${entry.profit_count}件</span></span>
            <span>秋田: <span class="history-stat-value">${entry.local_count}件</span></span>
            ${entry.tokens_left != null ? `<span>トークン: <span class="history-stat-value">${entry.tokens_left}</span></span>` : ''}
          </div>
        </div>
      `;
    }).join('');
  }

  /** Show product detail overlay */
  function showDetail(item) {
    const overlay = document.getElementById('overlay');
    const body = document.getElementById('overlay-body');

    const amazonUsedInfo = [];
    if (item.amazon_used_avg90) amazonUsedInfo.push(`90日平均: ${formatPrice(item.amazon_used_avg90)}`);
    if (item.amazon_used_current) amazonUsedInfo.push(`現在: ${formatPrice(item.amazon_used_current)}`);

    const links = [];
    if (item.url) {
      links.push(`<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener" class="detail-link link-bookoff">BookOff</a>`);
    }
    if (item.keepa_url) {
      links.push(`<a href="${escapeHtml(item.keepa_url)}" target="_blank" rel="noopener" class="detail-link link-keepa">Keepa</a>`);
    }

    body.innerHTML = `
      <div class="detail-title">${escapeHtml(item.title || '不明')}</div>

      <div class="detail-section">
        <div class="detail-section-title">価格比較</div>
        <div class="detail-row">
          <span class="detail-row-label">ブックオフ</span>
          <span class="detail-row-value">${formatPrice(item.price)}</span>
        </div>
        <div class="detail-row">
          <span class="detail-row-label">Amazon中古</span>
          <span class="detail-row-value">${formatPrice(item.amazon_used)}</span>
        </div>
        ${amazonUsedInfo.length > 0 ? `<div class="detail-row"><span class="detail-row-label">参考</span><span class="detail-row-value" style="font-size:0.75rem">${amazonUsedInfo.join(' / ')}</span></div>` : ''}
        <div class="detail-row">
          <span class="detail-row-label">利益概算</span>
          <span class="detail-row-value" style="color:${item.profit > 0 ? 'var(--accent-green)' : 'var(--accent-red)'}">${item.profit != null ? (item.profit > 0 ? '+' : '') + formatPrice(item.profit) : '-'}</span>
        </div>
      </div>

      <div class="detail-section">
        <div class="detail-section-title">在庫情報</div>
        <div class="detail-row">
          <span class="detail-row-label">全国在庫</span>
          <span class="detail-row-value">${item.total_stock ?? '-'}店舗 <span class="stock-rank ${rankClass(item.stock_rank)}">${item.stock_rank || ''}</span></span>
        </div>
        <div class="detail-row">
          <span class="detail-row-label">秋田在庫</span>
          <span class="detail-row-value" style="color:${item.has_local ? 'var(--accent-green)' : 'var(--text-muted)'}">${item.has_local ? 'あり' : 'なし'}</span>
        </div>
        ${item.local_stores ? `<div class="detail-row"><span class="detail-row-label">店舗</span><span class="detail-row-value" style="font-size:0.75rem">${escapeHtml(item.local_stores)}</span></div>` : ''}
      </div>

      <div class="detail-section">
        <div class="detail-section-title">商品情報</div>
        <div class="detail-row">
          <span class="detail-row-label">JAN</span>
          <span class="detail-row-value">${item.jan || '-'}</span>
        </div>
        <div class="detail-row">
          <span class="detail-row-label">ASIN</span>
          <span class="detail-row-value">${item.asin || '-'}</span>
        </div>
        <div class="detail-row">
          <span class="detail-row-label">ランキング</span>
          <span class="detail-row-value">${item.rank ? item.rank.toLocaleString() : '-'}</span>
        </div>
        <div class="detail-row">
          <span class="detail-row-label">ステータス</span>
          <span class="detail-row-value">${escapeHtml(item.status)}</span>
        </div>
      </div>

      ${links.length > 0 ? `<div class="detail-links">${links.join('')}</div>` : ''}
    `;

    overlay.classList.remove('hidden');
  }

  function hideDetail() {
    document.getElementById('overlay').classList.add('hidden');
  }

  /** Bind card click events for detail overlay */
  function _bindCardClicks(container) {
    container.querySelectorAll('.item-card').forEach(card => {
      card.addEventListener('click', () => {
        const id = card.dataset.id;
        const item = DataStore.getAllItems().find(i => i.id === id);
        if (item) showDetail(item);
      });
    });
  }

  function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  return {
    renderDashboard,
    renderProducts,
    renderHistory,
    showDetail,
    hideDetail
  };
})();
