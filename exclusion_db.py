"""
除外リスト管理（SQLite）
- JANコード除外
- キーワード除外
- 商品ID除外
"""
import sqlite3
import os
from datetime import datetime

DB_FILE = os.path.join(os.path.dirname(__file__), "exclusions.db")


def get_connection():
    """DB接続を取得"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """テーブル初期化"""
    conn = get_connection()
    c = conn.cursor()

    # 除外JANテーブル
    c.execute('''
        CREATE TABLE IF NOT EXISTS excluded_jan (
            jan TEXT PRIMARY KEY,
            reason TEXT,
            amazon_price INTEGER,
            created_at TEXT
        )
    ''')

    # 除外キーワードテーブル
    c.execute('''
        CREATE TABLE IF NOT EXISTS excluded_keywords (
            keyword TEXT PRIMARY KEY,
            reason TEXT,
            created_at TEXT
        )
    ''')

    # 除外商品IDテーブル（JANがない商品用）
    c.execute('''
        CREATE TABLE IF NOT EXISTS excluded_products (
            product_id TEXT PRIMARY KEY,
            reason TEXT,
            created_at TEXT
        )
    ''')

    # インデックス作成
    c.execute('CREATE INDEX IF NOT EXISTS idx_jan ON excluded_jan(jan)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_keyword ON excluded_keywords(keyword)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_product ON excluded_products(product_id)')

    conn.commit()
    conn.close()


def add_excluded_jan(jan, reason="利益なし", amazon_price=None):
    """除外JANを追加"""
    if not jan:
        return False

    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute('''
            INSERT OR REPLACE INTO excluded_jan (jan, reason, amazon_price, created_at)
            VALUES (?, ?, ?, ?)
        ''', (jan, reason, amazon_price, datetime.now().isoformat()))
        conn.commit()
        return True
    except Exception as e:
        print(f"除外JAN追加エラー: {e}")
        return False
    finally:
        conn.close()


def add_excluded_keyword(keyword, reason="手動追加"):
    """除外キーワードを追加"""
    if not keyword:
        return False

    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute('''
            INSERT OR REPLACE INTO excluded_keywords (keyword, reason, created_at)
            VALUES (?, ?, ?)
        ''', (keyword, reason, datetime.now().isoformat()))
        conn.commit()
        return True
    except Exception as e:
        print(f"除外キーワード追加エラー: {e}")
        return False
    finally:
        conn.close()


def add_excluded_product(product_id, reason="利益なし"):
    """除外商品IDを追加"""
    if not product_id:
        return False

    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute('''
            INSERT OR REPLACE INTO excluded_products (product_id, reason, created_at)
            VALUES (?, ?, ?)
        ''', (product_id, reason, datetime.now().isoformat()))
        conn.commit()
        return True
    except Exception as e:
        print(f"除外商品ID追加エラー: {e}")
        return False
    finally:
        conn.close()


def is_excluded_jan(jan):
    """JANが除外対象か確認"""
    if not jan:
        return False, None

    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT reason FROM excluded_jan WHERE jan = ?', (jan,))
    row = c.fetchone()
    conn.close()

    if row:
        return True, row['reason']
    return False, None


def is_excluded_keyword(title):
    """タイトルに除外キーワードが含まれるか確認"""
    if not title:
        return False, None

    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT keyword FROM excluded_keywords')
    rows = c.fetchall()
    conn.close()

    for row in rows:
        if row['keyword'] in title:
            return True, row['keyword']
    return False, None


def is_excluded_product(product_id):
    """商品IDが除外対象か確認"""
    if not product_id:
        return False, None

    conn = get_connection()
    c = conn.cursor()
    c.execute('SELECT reason FROM excluded_products WHERE product_id = ?', (product_id,))
    row = c.fetchone()
    conn.close()

    if row:
        return True, row['reason']
    return False, None


def is_excluded(product):
    """商品が除外対象か総合チェック

    Args:
        product: {'id': ..., 'jan': ..., 'title': ...}

    Returns:
        tuple: (除外対象か, 理由)
    """
    # 商品ID除外
    excluded, reason = is_excluded_product(product.get('id'))
    if excluded:
        return True, f"除外商品ID: {reason}"

    # JAN除外
    excluded, reason = is_excluded_jan(product.get('jan'))
    if excluded:
        return True, f"除外JAN: {reason}"

    # キーワード除外
    excluded, keyword = is_excluded_keyword(product.get('title'))
    if excluded:
        return True, f"除外キーワード: {keyword}"

    return False, None


def get_stats():
    """除外リストの統計"""
    conn = get_connection()
    c = conn.cursor()

    c.execute('SELECT COUNT(*) FROM excluded_jan')
    jan_count = c.fetchone()[0]

    c.execute('SELECT COUNT(*) FROM excluded_keywords')
    keyword_count = c.fetchone()[0]

    c.execute('SELECT COUNT(*) FROM excluded_products')
    product_count = c.fetchone()[0]

    conn.close()

    return {
        'jan': jan_count,
        'keywords': keyword_count,
        'products': product_count
    }


def load_exclude_list():
    """GAS API互換のdict形式で返す（後方互換性用）"""
    conn = get_connection()
    c = conn.cursor()

    c.execute('SELECT jan FROM excluded_jan')
    jan_set = set(row[0] for row in c.fetchall())

    c.execute('SELECT keyword FROM excluded_keywords')
    keywords = [row[0] for row in c.fetchall()]

    conn.close()

    return {'jan': jan_set, 'keywords': keywords}


# 初期化
init_db()
