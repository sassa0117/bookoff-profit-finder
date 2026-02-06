#!/usr/bin/env python3
"""
ブックオフ利益商品ファインダー
- ブックオフのカテゴリ商品をページ単位でスクレイピング
- Keepa APIでAmazon相場を取得（全国在庫5店舗以下のみ）
- 利益商品を全国表示（秋田フラグ付き）
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import requests
import re
import time
import csv
import os
import json
from datetime import datetime, timezone, timedelta
import exclusion_db

# 日本時間
JST = timezone(timedelta(hours=9))

# 設定（環境変数優先）
KEEPA_API_KEY = os.environ.get("KEEPA_API_KEY", "1b2vuq9vbv5ejbagprfksl7ra5phbhlv3ngd65rp6gal6tu74uujvd5n2e5ate4a")
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

# カテゴリURL
CATEGORIES = {
    "dvd": "https://shopping.bookoff.co.jp/search/genre/71",
    "cd": "https://shopping.bookoff.co.jp/search/genre/31",
    "game": "https://shopping.bookoff.co.jp/search/genre/51",
    "comic": "https://shopping.bookoff.co.jp/search/genre/11",
    "book": "https://shopping.bookoff.co.jp/search/genre/12",
}

# 手数料設定（Amazon FBA想定）
FBA_FEE_RATE = 0.15  # 15%
FBA_SHIPPING = 200   # 送料（円）
MIN_PROFIT = 300     # 最低利益（円）

# キャッシュ設定
CACHE_FILE = os.path.join(os.path.dirname(__file__), "price_cache.json")
SEEN_FILE = os.path.join(os.path.dirname(__file__), "seen_products.json")
MIN_AMAZON_PRICE = 500  # この価格以下はゴミ扱い（円）
KEEPA_DELAY = 3  # Keepa API呼び出し間隔（秒）

# 除外リスト（SQLite）- exclusion_db.pyで管理

# 都道府県リスト
PREFECTURES = [
    '北海道', '青森県', '岩手県', '宮城県', '秋田県', '山形県', '福島県',
    '茨城県', '栃木県', '群馬県', '埼玉県', '千葉県', '東京都', '神奈川県',
    '新潟県', '富山県', '石川県', '福井県', '山梨県', '長野県', '岐阜県',
    '静岡県', '愛知県', '三重県', '滋賀県', '京都府', '大阪府', '兵庫県',
    '奈良県', '和歌山県', '鳥取県', '島根県', '岡山県', '広島県', '山口県',
    '徳島県', '香川県', '愛媛県', '高知県', '福岡県', '佐賀県', '長崎県',
    '熊本県', '大分県', '宮崎県', '鹿児島県', '沖縄県'
]


def load_price_cache():
    """価格キャッシュを読み込む"""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}


def save_price_cache(cache):
    """価格キャッシュを保存"""
    with open(CACHE_FILE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)







def load_seen_products():
    """処理済み商品データを読み込む"""
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return {'all': set(data), 'last_reset': None}
                return {
                    'all': set(data.get('all', [])),
                    'last_reset': data.get('last_reset')
                }
        except:
            return {'all': set(), 'last_reset': None}
    return {'all': set(), 'last_reset': None}


def save_seen_products(seen_data):
    """処理済み商品データを保存"""
    with open(SEEN_FILE, 'w', encoding='utf-8') as f:
        json.dump({
            'all': list(seen_data['all']),
            'last_reset': seen_data['last_reset']
        }, f)


def should_reset_daily(seen_data):
    """9時リセットが必要かチェック（日本時間9時以降、当日未リセットなら）"""
    now_jst = datetime.now(JST)
    today_str = now_jst.strftime("%Y-%m-%d")
    if now_jst.hour >= 9 and seen_data.get('last_reset') != today_str:
        return True, today_str
    return False, today_str


def is_garbage_jan(jan, cache):
    """キャッシュ済みのゴミJANかチェック"""
    if jan in cache:
        cached_price = cache[jan].get('price', 0)
        if cached_price and cached_price <= MIN_AMAZON_PRICE:
            return True, cached_price
    return False, None


def get_product_ids_by_page(category_url, start_page=1, max_pages=50, seen_products=None):
    """カテゴリページから商品IDをページ単位で取得

    Args:
        category_url: カテゴリURL
        start_page: 開始ページ番号
        max_pages: 最大処理ページ数
        seen_products: 処理済み商品IDのset

    Returns:
        tuple: (商品IDリスト, 最終ページ番号, 追いついたかフラグ)
    """
    all_product_ids = []
    page = start_page
    end_page = start_page + max_pages - 1
    caught_up = False
    consecutive_empty = 0  # 連続で未処理0件のページ数

    while page <= end_page:
        try:
            url = f"{category_url}?page={page}"
            print(f"  ページ {page}: {url}")

            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            product_ids = re.findall(r'href="/used/(\d+)"', r.text)

            if not product_ids:
                print(f"  → ページ終端、終了")
                break

            # このページの未処理をカウント
            new_on_page = [pid for pid in product_ids if pid not in seen_products] if seen_products else product_ids

            if seen_products and len(new_on_page) == 0:
                consecutive_empty += 1
                print(f"    → 全て処理済み（連続{consecutive_empty}ページ）")
                if consecutive_empty >= 3:
                    print(f"  → 連続3ページ空振り、追いつき完了")
                    caught_up = True
                    break
            else:
                consecutive_empty = 0  # リセット
                # 重複除去して追加
                for pid in product_ids:
                    if pid not in all_product_ids:
                        all_product_ids.append(pid)
                print(f"    → 取得: {len(product_ids)}件 (未処理: {len(new_on_page)}件)")

            page += 1
            time.sleep(1)

        except Exception as e:
            print(f"  エラー: ページ取得失敗 (page {page}) - {e}")
            break

    return all_product_ids, page - 1, caught_up


def get_new_arrivals(tab="cd", limit=50, seen_products=None):
    """新着ページからPlaywrightで商品IDを取得（無限スクロール対応）

    Args:
        tab: タブ名 (cd, dvd, game, book, comic)
        limit: 取得上限
        seen_products: 処理済み商品IDのset（指定すると未処理が見つかるまでスクロール）
    """
    from playwright.sync_api import sync_playwright

    # タブのセレクタ
    tab_selector = {
        "cd": 'a[href="#tabCD"]',
        "dvd": 'a[href="#tabMovie"]',
        "game": 'a[href="#tabGAME"]',
        "book": 'a[href="#tabBOOK"]',
        "comic": 'a[href="#tabCOMIC"]',
    }

    url = "https://shopping.bookoff.co.jp/list/arrival"
    max_scrolls = 20  # 最大スクロール回数（約1000件）
    min_unseen = 10   # 最低限見つけたい未処理件数

    try:
        print(f"  Playwright起動中...")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=90000)

            # ページ読み込み完了待機
            page.wait_for_load_state("domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)

            # タブをクリック
            selector = tab_selector.get(tab, tab_selector["cd"])
            print(f"  {tab.upper()}タブをクリック...")
            page.wait_for_selector(selector, state="visible", timeout=60000)
            page.click(selector, timeout=60000)
            page.wait_for_timeout(5000)

            # 「もっとみる」ボタンで商品を読み込む
            all_product_ids = []
            last_count = 0
            click_count = 0

            while click_count < max_scrolls:
                # HTMLから商品IDを抽出
                html = page.content()
                product_ids = re.findall(r'href="/used/(\d+)"', html)
                all_product_ids = list(dict.fromkeys(product_ids))

                print(f"  ページ {click_count + 1}: {len(all_product_ids)}件")

                # 未処理件数をチェック
                if seen_products:
                    unseen_count = sum(1 for pid in all_product_ids if pid not in seen_products)
                    print(f"    → 未処理: {unseen_count}件")
                    if unseen_count >= min_unseen:
                        print(f"  未処理 {unseen_count}件発見、読み込み終了")
                        break

                # 上限到達
                if len(all_product_ids) >= limit:
                    break

                # 新しい商品が読み込まれなくなったら終了
                if len(all_product_ids) == last_count and click_count > 0:
                    print(f"  これ以上読み込めない、終了")
                    break

                last_count = len(all_product_ids)

                # 「もっとみる」ボタンをクリック
                try:
                    more_button = page.locator('text=もっとみる').first
                    if more_button.is_visible():
                        print(f"  「もっとみる」クリック...")
                        more_button.click()
                        page.wait_for_timeout(3000)
                        click_count += 1
                    else:
                        print(f"  「もっとみる」ボタンなし、終了")
                        break
                except Exception as e:
                    print(f"  「もっとみる」クリック失敗: {e}")
                    break

            browser.close()

        print(f"  新着取得完了: {len(all_product_ids)}件")
        return all_product_ids[:limit]

    except Exception as e:
        print(f"  エラー: 新着取得失敗 - {e}")
        return []


def get_product_details(product_id):
    """商品詳細ページからJAN・価格・タイトルを取得"""
    url = f"https://shopping.bookoff.co.jp/used/{product_id}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        html = r.text

        # 商品名
        title_match = re.search(r'<h1[^>]*>([^<]+)</h1>', html)
        title = title_match.group(1).strip() if title_match else "不明"

        # 価格取得（優先順位）
        price = 0

        # 1. JSON-LD構造化データから取得（最も信頼性が高い）
        jsonld_price = re.search(r'"price"\s*:\s*(\d+)', html)
        if jsonld_price:
            price = int(jsonld_price.group(1))

        # 2. meta descriptionから取得（「中古価格 〇〇円」形式）
        if price == 0:
            meta_price = re.search(r'中古価格\s*(\d{1,3}(?:,\d{3})*|\d+)\s*円', html)
            if meta_price:
                price = int(meta_price.group(1).replace(',', ''))

        # 3. 一般的な価格パターン（フォールバック、全桁数対応）
        if price == 0:
            price_match = re.search(r'(\d{1,6}(?:,\d{3})*)\s*円\s*[（(]税込', html)
            if price_match:
                price = int(price_match.group(1).replace(',', ''))

        # 4. 最終フォールバック
        if price == 0:
            price_match = re.search(r'(\d{1,3}(?:,\d{3})+|\d{4,})\s*円', html)
            if price_match:
                price = int(price_match.group(1).replace(',', ''))

        # JANコード（13桁、タイムスタンプっぽいものを除外）
        jan_matches = re.findall(r'(\d{13})', html)
        jan_codes = [j for j in jan_matches if not j.startswith('166')]
        jan = jan_codes[0] if jan_codes else None

        return {
            "id": product_id,
            "title": title,
            "price": price,
            "jan": jan,
            "url": url,
            "html": html  # 店舗チェック用に保持
        }
    except Exception as e:
        print(f"  エラー: 商品詳細取得失敗 ({product_id}) - {e}")
        return None


def get_store_stock(html, target_prefecture="秋田県"):
    """商品ページHTMLから店舗在庫を取得し、指定県でフィルタ

    Returns:
        tuple: (全国店舗数, 対象県店舗リスト)
    """
    all_stores = []

    # 店舗リストを探す
    li_parts = html.split('<li')

    for i in range(1, len(li_parts)):
        li_content = li_parts[i]

        # bookoff.co.jp/shop/ リンクを含むかチェック
        shop_match = re.search(r'href="(https://www\.bookoff\.co\.jp/shop/[^"]+)"', li_content)
        if not shop_match:
            continue

        store_url = shop_match.group(1)

        # 店舗名を取得
        link_text_match = re.search(r'<a[^>]*href="https://www\.bookoff\.co\.jp/shop/[^"]*"[^>]*>([^<]*)', li_content)
        store_name = link_text_match.group(1).strip() if link_text_match else ''

        # 住所を取得
        small_match = re.search(r'<small[^>]*>([^<]*)</small>', li_content)
        address = small_match.group(1).strip() if small_match else ''

        # 都道府県を抽出
        prefecture = ''
        city = ''
        for pref in PREFECTURES:
            if pref in address:
                prefecture = pref
                city = address.replace(pref, '').strip()
                break

        if not prefecture and address:
            city = address

        all_stores.append({
            "name": store_name,
            "prefecture": prefecture,
            "city": city,
            "url": store_url
        })

    total_stock = len(all_stores)

    # 指定県でフィルタ
    if target_prefecture:
        filtered_stores = [s for s in all_stores if s['prefecture'] == target_prefecture]
    else:
        filtered_stores = all_stores

    return total_stock, filtered_stores


def get_keepa_data(jan_code):
    """Keepa APIでAmazon相場を取得"""
    if not jan_code:
        return None

    url = f"https://api.keepa.com/product?key={KEEPA_API_KEY}&domain=5&code={jan_code}&stats=1"
    try:
        r = requests.get(url, timeout=30)
        data = r.json()

        if 'error' in data:
            print(f"  Keepa APIエラー: {data['error']}")
            return {'error': data['error'], 'tokensLeft': data.get('tokensLeft', 0)}

        if 'products' not in data or not data['products']:
            return None

        p = data['products'][0]
        stats = p.get('stats', {})
        current = stats.get('current', [])
        avg90 = stats.get('avg90', [])

        # 現在価格
        current_used = current[2] if len(current) > 2 and current[2] and current[2] > 0 else None
        # 90日平均（在庫切れでも相場がわかる）
        avg90_used = avg90[2] if len(avg90) > 2 and avg90[2] and avg90[2] > 0 else None
        # 中古価格: avg90優先（プレミア品対応）、なければcurrent
        used_price = avg90_used or current_used

        amazon_price = current[0] if len(current) > 0 and current[0] and current[0] > 0 else None
        new_price = current[1] if len(current) > 1 and current[1] and current[1] > 0 else None
        rank = current[3] if len(current) > 3 and current[3] and current[3] > 0 else None

        return {
            "asin": p.get("asin"),
            "amazon_price": amazon_price,
            "new_price": new_price,
            "used_price": used_price,
            "current_used": current_used,
            "avg90_used": avg90_used,
            "rank": rank,
            "tokens_left": data.get("tokensLeft", 0)
        }
    except Exception as e:
        print(f"  Keepaエラー: {e}")
        return None


def send_to_spreadsheet(spreadsheet_url, results):
    """Google Spreadsheetに結果を送信"""
    if not spreadsheet_url or not results:
        return

    # 利益あり・薄利・Amazon未登録のみ送信
    items_to_send = [r for r in results if r.get('status') in ('利益あり', '薄利', 'Amazon未登録')]
    if not items_to_send:
        print("スプレッドシート: 送信対象なし")
        return

    payload = {
        'items': [{
            'has_local': '○' if item.get('has_local') else '',
            'status': item.get('status', ''),
            'title': item.get('title', '')[:100],
            'price': item.get('price', 0),
            'amazon_used': item.get('amazon_used') or '',
            'profit': item.get('profit') or '',
            'total_stock': item.get('total_stock', 0),
            'local_stores': item.get('local_stores', '')[:50],
            'url': item.get('url', ''),
            'keepa_url': item.get('keepa_url') or ''
        } for item in items_to_send]
    }

    try:
        r = requests.post(spreadsheet_url, json=payload, timeout=30)
        if r.status_code == 200:
            print(f"スプレッドシート送信完了: {len(items_to_send)}件")
        else:
            print(f"スプレッドシート送信失敗: {r.status_code}")
    except Exception as e:
        print(f"スプレッドシートエラー: {e}")


def send_discord_csv(webhook_url, csv_path):
    """Discord WebhookでCSVファイルを添付送信"""
    if not webhook_url or not os.path.exists(csv_path):
        return

    # ファイルサイズチェック（空ファイルやヘッダのみは送らない）
    if os.path.getsize(csv_path) < 100:
        print("Discord CSV: データなし、送信スキップ")
        return

    try:
        with open(csv_path, 'rb') as f:
            files = {'file': (os.path.basename(csv_path), f, 'text/csv')}
            payload = {'content': '📎 今回の結果CSV'}
            r = requests.post(webhook_url, data=payload, files=files, timeout=30)
        if r.status_code == 200:
            print(f"Discord CSV送信完了: {csv_path}")
        else:
            print(f"Discord CSV送信失敗: {r.status_code}")
    except Exception as e:
        print(f"Discord CSVエラー: {e}")


def send_discord_notification(webhook_url, results, stats=None):
    """Discord Webhookで結果サマリーと利益商品を通知"""
    if not webhook_url:
        return

    # 利益あり + Amazon未登録を通知対象に
    profit_items = [r for r in results if r.get('status') == '利益あり']
    unregistered_items = [r for r in results if r.get('status') == 'Amazon未登録']

    # 利益商品の通知
    embeds = []
    for item in profit_items[:5]:  # 最大5件
        # 秋田フラグ
        local_flag = "🏠" if item.get('has_local') else "🌐"
        embed = {
            "title": f"{local_flag} {item.get('title', '不明')[:95]}",
            "url": item.get('url', ''),
            "color": 0x00ff00 if item.get('has_local') else 0x3498db,  # 秋田=緑、他=青
            "fields": [
                {"name": "ブックオフ", "value": f"{item.get('price', 0):,}円", "inline": True},
                {"name": "Amazon中古", "value": f"{item.get('amazon_used', 0) or 0:,}円", "inline": True},
                {"name": "利益概算", "value": f"{item.get('profit', 0) or 0:,}円", "inline": True},
                {"name": "在庫ランク", "value": item.get('stock_rank', '-'), "inline": True},
                {"name": "全国在庫", "value": f"{item.get('total_stock', 0)}店舗", "inline": True},
            ]
        }
        if item.get('local_stores'):
            embed["fields"].append({"name": "秋田店舗", "value": item.get('local_stores', '-')[:100], "inline": False})
        if item.get('keepa_url'):
            embed["fields"].append({"name": "Keepa", "value": f"[グラフを見る]({item['keepa_url']})", "inline": False})
        embeds.append(embed)

    # Amazon未登録商品の通知（秋田のみ）
    for item in unregistered_items[:3]:  # 最大3件
        if not item.get('has_local'):
            continue
        embed = {
            "title": f"📦 {item.get('title', '不明')[:95]}",
            "url": item.get('url', ''),
            "color": 0xffaa00,  # オレンジ
            "fields": [
                {"name": "ブックオフ", "value": f"{item.get('price', 0):,}円", "inline": True},
                {"name": "ステータス", "value": "Amazon未登録", "inline": True},
                {"name": "全国在庫", "value": f"{item.get('total_stock', 0)}店舗", "inline": True},
            ]
        }
        if item.get('local_stores'):
            embed["fields"].append({"name": "秋田店舗", "value": item.get('local_stores', '-')[:100], "inline": False})
        embeds.append(embed)

    # サマリー作成
    stats = stats or {}
    local_profits = [r for r in profit_items if r.get('has_local')]

    summary_parts = []
    if stats.get('initial_tokens') is not None:
        summary_parts.append(f"開始トークン: {stats['initial_tokens']}")
    if stats.get('keepa_calls'):
        summary_parts.append(f"Keepa: {stats['keepa_calls']}回")
    if stats.get('skipped'):
        summary_parts.append(f"スキップ: {stats['skipped']}件")
    if stats.get('unregistered'):
        summary_parts.append(f"Amazon未登録: {stats['unregistered']}件")

    content_parts = []
    if profit_items:
        content_parts.append(f"🎯 利益商品: {len(profit_items)}件（秋田: {len(local_profits)}件）")

    # メッセージ作成
    if content_parts:
        content = f"**発見！** {' / '.join(content_parts)}"
    else:
        content = "**チェック完了** 見込み商品なし"

    if summary_parts:
        content += f"\n({' / '.join(summary_parts)})"

    payload = {
        "content": content,
        "embeds": embeds[:10] if embeds else []
    }

    try:
        r = requests.post(webhook_url, json=payload, timeout=10)
        if r.status_code == 204:
            print(f"Discord通知送信完了")
        else:
            print(f"Discord通知失敗: {r.status_code}")
    except Exception as e:
        print(f"Discord通知エラー: {e}")


def calculate_profit(bookoff_price, amazon_price):
    """利益を計算（FBA想定）"""
    if not amazon_price or amazon_price <= 0:
        return None

    fee = int(amazon_price * FBA_FEE_RATE)
    profit = amazon_price - bookoff_price - fee - FBA_SHIPPING
    return profit


def run_finder(categories=None, limit_per_category=20, output_file=None, target_prefecture="秋田県", use_new_arrivals=False, discord_webhook=None, max_pages_per_run=20, spreadsheet_url=None):
    """メイン処理

    Args:
        categories: 処理するカテゴリリスト
        limit_per_category: (互換性のため残す、現在未使用)
        output_file: 出力ファイル名
        target_prefecture: 優先表示する都道府県
        use_new_arrivals: (互換性のため残す、カテゴリモードのみ使用)
        discord_webhook: Discord Webhook URL
        max_pages_per_run: もっと見るクリック回数
        spreadsheet_url: Google Spreadsheet GAS Web App URL
    """
    if categories is None:
        categories = ["dvd"]

    if output_file is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"profit_{timestamp}.csv"

    results = []
    tokens_left = 300
    price_cache = load_price_cache()
    seen_data = load_seen_products()
    seen_products = seen_data['all']

    cache_hits = 0
    exclude_skips = 0
    auto_excluded = 0
    stock_skips = 0  # 在庫多すぎスキップ
    keepa_calls = 0  # Keepa API呼び出し回数
    initial_tokens = None  # 開始時トークン数（最初のKeepa応答で取得）

    # 9時リセットチェック
    need_reset, today_str = should_reset_daily(seen_data)
    if need_reset:
        print(f"★ 9時リセット実行（日本時間）")
        seen_products = set()
        seen_data['last_reset'] = today_str

    # 除外リスト統計
    exclude_stats = exclusion_db.get_stats()
    print(f"=== ブックオフ利益商品ファインダー ===")
    print(f"除外DB: JAN {exclude_stats['jan']}件, キーワード {exclude_stats['keywords']}件, 商品ID {exclude_stats['products']}件")
    print(f"モード: 新着ページ（毎時実行・トークン回復待ち）")
    print(f"優先地域: {target_prefecture}")
    print(f"カテゴリ: {', '.join(categories)}")
    print(f"処理済み商品: {len(seen_products)}件\n")

    for cat_name in categories:
        print(f"\n=== {cat_name.upper()} 新着 ===")

        # 新着ページから商品ID取得（Playwright）
        product_ids = get_new_arrivals(
            tab=cat_name,
            limit=max_pages_per_run * 50,
            seen_products=seen_products
        )

        print(f"取得商品数: {len(product_ids)}件")

        # 未処理のみ抽出
        new_product_ids = [pid for pid in product_ids if pid not in seen_products]
        print(f"未処理: {len(new_product_ids)}件")

        for i, pid in enumerate(new_product_ids):
            print(f"\n[{i+1}/{len(new_product_ids)}] 商品ID: {pid}")
            seen_products.add(pid)

            # 商品詳細取得
            product = get_product_details(pid)
            if not product:
                continue

            print(f"  {product['title'][:40]}...")
            print(f"  ブックオフ: {product['price']:,}円")

            # 除外リストチェック
            excluded, reason = exclusion_db.is_excluded(product)
            if excluded:
                print(f"  → {reason}、スキップ")
                exclude_skips += 1
                continue

            # 店舗在庫チェック（全国）
            total_stock, local_stores = get_store_stock(product['html'], target_prefecture)

            # 在庫ランク判定
            if total_stock <= 5:
                stock_rank = "S"  # 希少 → Keepa確認対象
            elif total_stock <= 10:
                stock_rank = "A"  # やや希少
            elif total_stock <= 30:
                stock_rank = "B"  # 普通
            else:
                stock_rank = "C"  # 多い

            print(f"  → 全国在庫: {total_stock}店舗 [ランク{stock_rank}]")

            # 秋田フラグ
            has_local = len(local_stores) > 0
            if has_local:
                print(f"  → {target_prefecture}: {len(local_stores)}店舗")
                for store in local_stores[:3]:  # 最大3店舗表示
                    print(f"     - {store['name']} ({store['city']})")

            # ★★★ 全国在庫15以下のみKeepa API呼び出し ★★★
            if total_stock > 15:
                print(f"  → 在庫{total_stock}店舗 > 15、Keepaスキップ")
                stock_skips += 1
                continue

            # JANがない場合
            if not product['jan']:
                print("  → JANなし")
                results.append({
                    **{k: v for k, v in product.items() if k != 'html'},
                    "asin": None,
                    "amazon_used": None,
                    "profit": None,
                    "rank": None,
                    "keepa_url": None,
                    "total_stock": total_stock,
                    "stock_rank": stock_rank,
                    "has_local": has_local,
                    "local_stores": ", ".join([s['name'] for s in local_stores]) if local_stores else "",
                    "status": "JANなし"
                })
                continue

            # ゴミキャッシュチェック
            is_garbage, cached_price = is_garbage_jan(product['jan'], price_cache)
            if is_garbage:
                print(f"  → キャッシュ済みゴミ（Amazon {cached_price}円）、スキップ")
                cache_hits += 1
                continue

            # トークン確認
            if tokens_left < 5:
                print("  → トークン不足、停止")
                break

            # Keepa API
            time.sleep(KEEPA_DELAY)
            keepa = get_keepa_data(product['jan'])
            keepa_calls += 1

            # Keepa APIエラーチェック
            if keepa and 'error' in keepa:
                print(f"  → Keepa APIエラー: {keepa['error'].get('type', '不明')}")
                print(f"  → 処理停止")
                break

            if not keepa:
                print("  → Amazon未登録")
                results.append({
                    **{k: v for k, v in product.items() if k != 'html'},
                    "asin": None,
                    "amazon_used": None,
                    "profit": None,
                    "rank": None,
                    "keepa_url": None,
                    "total_stock": total_stock,
                    "stock_rank": stock_rank,
                    "has_local": has_local,
                    "local_stores": ", ".join([s['name'] for s in local_stores]) if local_stores else "",
                    "status": "Amazon未登録"
                })
                continue

            tokens_left = keepa['tokens_left']
            if initial_tokens is None:
                initial_tokens = tokens_left + 1  # この呼び出し分を足す
                print(f"  → 開始時トークン: 約{initial_tokens}")

            # キャッシュに保存
            price_cache[product['jan']] = {
                'price': keepa['used_price'],
                'asin': keepa['asin'],
                'updated': datetime.now().strftime("%Y-%m-%d")
            }

            # ゴミ価格は除外DBに追加してスキップ
            if keepa['used_price'] and keepa['used_price'] <= MIN_AMAZON_PRICE:
                print(f"  → ゴミ価格（Amazon {keepa['used_price']}円）、除外DBに追加してスキップ")
                exclusion_db.add_excluded_jan(
                    product['jan'],
                    reason=f"ゴミ価格（Amazon {keepa['used_price']}円）",
                    amazon_price=keepa['used_price']
                )
                auto_excluded += 1
                continue

            # 価格表示
            if keepa['avg90_used']:
                print(f"  Amazon中古(90日平均): {keepa['avg90_used']:,}円")
            if keepa['current_used']:
                print(f"  Amazon中古(現在): {keepa['current_used']:,}円")
            if not keepa['used_price']:
                print("  Amazon中古: なし")

            # 利益計算
            profit = calculate_profit(product['price'], keepa['used_price'])
            if profit:
                print(f"  利益概算: {profit:,}円")

            keepa_url = f"https://keepa.com/#!product/5-{keepa['asin']}" if keepa['asin'] else None

            # ステータス判定
            if profit and profit >= MIN_PROFIT:
                status = "利益あり"
                print(f"  ★★★ 利益あり！ ★★★")
            elif profit and profit > 0:
                status = "薄利"
            elif profit is not None:
                status = "赤字"
                if product.get('jan'):
                    exclusion_db.add_excluded_jan(
                        product['jan'],
                        reason=f"赤字（Amazon {keepa['used_price']}円）",
                        amazon_price=keepa['used_price']
                    )
                    auto_excluded += 1
                    print(f"  → 除外DBに追加")
            else:
                status = "価格不明"

            results.append({
                **{k: v for k, v in product.items() if k != 'html'},
                "asin": keepa['asin'],
                "amazon_used": keepa['used_price'],
                "amazon_used_current": keepa['current_used'],
                "amazon_used_avg90": keepa['avg90_used'],
                "profit": profit,
                "rank": keepa['rank'],
                "keepa_url": keepa_url,
                "total_stock": total_stock,
                "stock_rank": stock_rank,
                "has_local": has_local,
                "local_stores": ", ".join([s['name'] for s in local_stores]) if local_stores else "",
                "status": status
            })

    # CSV出力
    print(f"\n\n=== 結果出力: {output_file} ===")

    fieldnames = ["stock_rank", "has_local", "status", "title", "price", "amazon_used_avg90", "amazon_used_current", "profit", "rank", "total_stock", "local_stores", "url", "keepa_url", "jan", "asin", "id"]
    with open(output_file, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()

        # 利益順にソート（利益あり・薄利・Amazon未登録のみ）
        filtered = [r for r in results if r['status'] in ('利益あり', '薄利', 'Amazon未登録')]
        sorted_results = sorted(filtered, key=lambda x: x['profit'] if x['profit'] else -99999, reverse=True)
        writer.writerows(sorted_results)

    # データ保存
    save_price_cache(price_cache)
    seen_data['all'] = seen_products
    save_seen_products(seen_data)

    # サマリー
    profit_items = [r for r in results if r['status'] == '利益あり']
    local_profits = [r for r in profit_items if r.get('has_local')]
    print(f"\n=== サマリー ===")
    print(f"Keepa API呼び出し: {keepa_calls}回")
    print(f"在庫多スキップ（>15店舗）: {stock_skips}件")
    print(f"利益あり: {len(profit_items)}件（うち{target_prefecture}: {len(local_profits)}件）")
    print(f"残りトークン: {tokens_left}")
    print(f"除外スキップ: {exclude_skips}件")
    print(f"自動除外追加: {auto_excluded}件")
    print(f"キャッシュヒット: {cache_hits}件")
    print(f"処理済み総数: {len(seen_products)}件")

    # Discord通知
    webhook_url = discord_webhook or os.environ.get("DISCORD_WEBHOOK_URL")
    if webhook_url:
        unregistered_count = len([r for r in results if r.get('status') == 'Amazon未登録'])
        stats = {
            'checked': len(results),
            'skipped': stock_skips + cache_hits + exclude_skips,
            'keepa_calls': keepa_calls,
            'initial_tokens': initial_tokens,
            'unregistered': unregistered_count
        }
        send_discord_notification(webhook_url, results, stats)
        # CSV添付送信
        send_discord_csv(webhook_url, output_file)

    # スプレッドシート送信
    sheet_url = spreadsheet_url or os.environ.get("SPREADSHEET_WEBHOOK_URL")
    if sheet_url:
        send_to_spreadsheet(sheet_url, results)

    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="ブックオフ利益商品ファインダー")
    parser.add_argument("--categories", nargs="+", default=["dvd"], help="カテゴリ (dvd, cd, game, comic, book)")
    parser.add_argument("--limit", type=int, default=200, help="(互換性のため残す)")
    parser.add_argument("--output", type=str, help="出力ファイル名")
    parser.add_argument("--prefecture", type=str, default="秋田県", help="優先表示する都道府県")
    parser.add_argument("--new", action="store_true", help="(互換性のため残す、カテゴリモードのみ使用)")
    parser.add_argument("--discord", type=str, help="Discord Webhook URL")
    parser.add_argument("--spreadsheet", type=str, help="Google Spreadsheet GAS URL")
    parser.add_argument("--max-pages", type=int, default=20, help="もっと見るクリック回数")
    args = parser.parse_args()

    run_finder(
        categories=args.categories,
        limit_per_category=args.limit,
        output_file=args.output,
        target_prefecture=args.prefecture,
        use_new_arrivals=args.new,
        discord_webhook=args.discord,
        max_pages_per_run=args.max_pages,
        spreadsheet_url=args.spreadsheet
    )
