/**
 * Data fetching and caching module
 */
const DataStore = (() => {
  const BASE_URL = (() => {
    const loc = window.location;
    // GitHub Pages or local server
    if (loc.hostname === 'localhost' || loc.hostname === '127.0.0.1') {
      return loc.origin + loc.pathname.replace(/\/[^/]*$/, '/');
    }
    return loc.origin + loc.pathname.replace(/\/[^/]*$/, '/');
  })();

  let _index = [];
  let _runs = {};
  let _allItems = [];
  let _lastFetch = 0;

  async function fetchJSON(url) {
    const fullUrl = BASE_URL + url;
    const response = await fetch(fullUrl, { cache: 'no-cache' });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  /** Load index.json and recent run files */
  async function loadData(forceRefresh = false) {
    const now = Date.now();
    // Throttle: don't refetch within 30 seconds unless forced
    if (!forceRefresh && _index.length > 0 && (now - _lastFetch) < 30000) {
      return;
    }

    try {
      _index = await fetchJSON('data/index.json');
      _lastFetch = now;

      // Load up to last 24 runs for product aggregation
      const recentRuns = _index.slice(0, 24);
      const fetchPromises = recentRuns
        .filter(entry => !_runs[entry.file])
        .map(async entry => {
          try {
            const data = await fetchJSON(entry.file);
            _runs[entry.file] = data;
          } catch (e) {
            console.warn(`Failed to load ${entry.file}:`, e);
          }
        });

      await Promise.all(fetchPromises);

      // Aggregate items from recent runs (deduplicate by product ID)
      _rebuildAllItems(recentRuns);
    } catch (e) {
      console.error('Data load error:', e);
    }
  }

  function _rebuildAllItems(recentRuns) {
    const seen = new Set();
    _allItems = [];

    for (const entry of recentRuns) {
      const runData = _runs[entry.file];
      if (!runData || !runData.items) continue;

      for (const item of runData.items) {
        if (!seen.has(item.id)) {
          seen.add(item.id);
          _allItems.push({ ...item, run_time: entry.timestamp });
        }
      }
    }
  }

  function getIndex() {
    return _index;
  }

  function getAllItems() {
    return _allItems;
  }

  function getRunData(file) {
    return _runs[file] || null;
  }

  function getLatestRun() {
    if (_index.length === 0) return null;
    const latest = _index[0];
    return _runs[latest.file] || null;
  }

  function getStats() {
    const latest = getLatestRun();
    const profitItems = _allItems.filter(i => i.status === '利益あり');
    const localItems = _allItems.filter(i => i.has_local);
    const localProfitItems = profitItems.filter(i => i.has_local);

    return {
      profitCount: profitItems.length,
      localCount: localProfitItems.length,
      lastRun: latest ? latest.timestamp : null,
      tokensLeft: latest ? latest.tokens_left : null,
      totalItems: _allItems.length
    };
  }

  return {
    loadData,
    getIndex,
    getAllItems,
    getRunData,
    getLatestRun,
    getStats
  };
})();
