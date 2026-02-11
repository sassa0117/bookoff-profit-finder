/**
 * Main application controller
 */
(async () => {
  // Register Service Worker
  if ('serviceWorker' in navigator) {
    try {
      await navigator.serviceWorker.register('./sw.js');
    } catch (e) {
      console.warn('SW registration failed:', e);
    }
  }

  // Tab navigation
  const tabs = document.querySelectorAll('.tab');
  const views = document.querySelectorAll('.view');
  let currentView = 'dashboard';

  function switchView(name) {
    currentView = name;
    tabs.forEach(t => t.classList.toggle('active', t.dataset.view === name));
    views.forEach(v => v.classList.toggle('active', v.id === `view-${name}`));
    renderCurrentView();
  }

  tabs.forEach(tab => {
    tab.addEventListener('click', () => switchView(tab.dataset.view));
  });

  // Overlay close
  document.getElementById('overlay-close').addEventListener('click', Views.hideDetail);
  document.getElementById('overlay').addEventListener('click', e => {
    if (e.target === e.currentTarget) Views.hideDetail();
  });

  // Filter controls
  const filterStatus = document.getElementById('filter-status');
  const filterRegion = document.getElementById('filter-region');
  const filterSort = document.getElementById('filter-sort');

  function onFilterChange() {
    Views.renderProducts(filterStatus.value, filterRegion.value, filterSort.value);
  }

  filterStatus.addEventListener('change', onFilterChange);
  filterRegion.addEventListener('change', onFilterChange);
  filterSort.addEventListener('change', onFilterChange);

  function renderCurrentView() {
    switch (currentView) {
      case 'dashboard':
        Views.renderDashboard();
        break;
      case 'products':
        Views.renderProducts(filterStatus.value, filterRegion.value, filterSort.value);
        break;
      case 'history':
        Views.renderHistory();
        break;
    }
  }

  // Initial load
  await DataStore.loadData();
  renderCurrentView();

  // Auto-refresh every 5 minutes
  setInterval(async () => {
    await DataStore.loadData(true);
    renderCurrentView();
  }, 5 * 60 * 1000);
})();
