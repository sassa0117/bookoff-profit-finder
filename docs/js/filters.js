/**
 * Filtering and sorting module
 */
const Filters = (() => {

  /**
   * Filter items by status and region
   * @param {Array} items
   * @param {string} status - 'all', '利益あり', '薄利', 'Amazon未登録'
   * @param {string} region - 'all', 'local'
   * @returns {Array}
   */
  function filterItems(items, status, region) {
    return items.filter(item => {
      if (status !== 'all' && item.status !== status) return false;
      if (region === 'local' && !item.has_local) return false;
      return true;
    });
  }

  /**
   * Sort items
   * @param {Array} items
   * @param {string} sortBy - 'profit', 'price', 'stock'
   * @returns {Array}
   */
  function sortItems(items, sortBy) {
    const sorted = [...items];
    switch (sortBy) {
      case 'profit':
        sorted.sort((a, b) => (b.profit || -99999) - (a.profit || -99999));
        break;
      case 'price':
        sorted.sort((a, b) => (a.price || 0) - (b.price || 0));
        break;
      case 'stock':
        sorted.sort((a, b) => (a.total_stock || 999) - (b.total_stock || 999));
        break;
    }
    return sorted;
  }

  /**
   * Get top N profit items
   * @param {Array} items
   * @param {number} n
   * @returns {Array}
   */
  function topProfitItems(items, n = 5) {
    return items
      .filter(i => i.status === '利益あり')
      .sort((a, b) => (b.profit || 0) - (a.profit || 0))
      .slice(0, n);
  }

  return { filterItems, sortItems, topProfitItems };
})();
