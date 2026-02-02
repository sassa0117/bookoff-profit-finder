#!/usr/bin/env python3
"""
ブックオフ利益商品ファインダー（秋田県フィルター付き）
- ブックオフの新着/カテゴリ商品をスクレイピング
- Keepa APIでAmazon相場を取得
- 秋田県の店舗で受取可能なものだけ抽出
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import requests
import re
import time
import csv
import os
import json
from datetime import datetime

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
    """処理済み商品データを読み込む

    Returns:
        dict: {
            'all': set(全処理済みID),
            'frontier': {category: [先頭10件のID]}
        }
    """
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # 旧形式（リスト）との互換性
                if isinstance(data, list):
                    return {'all': set(data), 'frontier': {}}
                return {
                    'all': set(data.get('all', [])),
                    'frontier': data.get('frontier', {})
                }
        except:
            return {'all': set(), 'frontier': {}}
    return {'all': set(), 'frontier': {}}


def save_seen_products(seen_data):
    """処理済み商品データを保存"""
    with open(SEEN_FILE, 'w', encoding='utf-8') as f:
        json.dump({
            'all': list(seen_data['all']),
            'frontier': seen_data['frontier']
        }, f)


def is_garbage_jan(jan, cache):
    """キャッシュ済みのゴミJANかチェック"""
    if jan in cache:
        cached_price = cache[jan].get('price', 0)
        if cached_price and cached_price <= MIN_AMAZON_PRICE:
            return True, cached_price
    return False, None


def get_product_ids(category_url, limit=50):
    """カテゴリページから商品IDを取得"""
    try:
        r = requests.get(category_url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        product_ids = re.findall(r'href="/used/(\d+)"', r.text)
        unique_ids = list(dict.fromkeys(product_ids))
        return unique_ids[:limit]
    except Exception as e:
        print(f"  エラー: カテゴリ取得失敗 - {e}")
        return []


def get_new_arrivals(tab="cd", limit=50):
    """新着ページからPlaywrightで商品IDを取得

    Args:
        tab: タブ名 (cd, dvd, game, book, comic)
        limit: 取得上限
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

    try:
        print(f"  Playwright起動中...")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=90000)

            # ページ読み込み完了待機
            page.wait_for_load_state("domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)

            # タブをクリック（タイムアウト延長・リトライ付き）
            selector = tab_selector.get(tab, tab_selector["cd"])
            print(f"  {tab.upper()}タブをクリック...")

            # セレクタが見つかるまで待機
            page.wait_for_selector(selector, state="visible", timeout=60000)
            page.click(selector, timeout=60000)

            # タブ切り替え後の読み込み待機
            page.wait_for_timeout(5000)

            # HTMLを取得
            html = page.content()
            browser.close()

        # 商品IDを抽出
        product_ids = re.findall(r'href="/used/(\d+)"', html)
        unique_ids = list(dict.fromkeys(product_ids))
        print(f"  新着取得完了: {len(unique_ids)}件")
        return unique_ids[:limit]

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

        # 価格
        price_match = re.search(r'(\d{1,3}(?:,\d{3})*)\s*円', html)
        price = int(price_match.group(1).replace(',', '')) if price_match else 0

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
        embed = {
            "title": item.get('title', '不明')[:100],
            "url": item.get('url', ''),
            "color": 0x00ff00,  # 緑
            "fields": [
                {"name": "ブックオフ", "value": f"{item.get('price', 0):,}円", "inline": True},
                {"name": "Amazon中古", "value": f"{item.get('amazon_used', 0) or 0:,}円", "inline": True},
                {"name": "利益概算", "value": f"{item.get('profit', 0) or 0:,}円", "inline": True},
                {"name": "在庫ランク", "value": item.get('stock_rank', '-'), "inline": True},
                {"name": "全国在庫", "value": f"{item.get('total_stock', 0)}店舗", "inline": True},
                {"name": "秋田店舗", "value": item.get('local_stores', '-')[:100], "inline": False},
            ]
        }
        if item.get('keepa_url'):
            embed["fields"].append({"name": "Keepa", "value": f"[グラフを見る]({item['keepa_url']})", "inline": False})
        embeds.append(embed)

    # Amazon未登録商品の通知
    for item in unregistered_items[:5]:  # 最大5件
        embed = {
            "title": f"📦 {item.get('title', '不明')[:100]}",
            "url": item.get('url', ''),
            "color": 0xffaa00,  # オレンジ
            "fields": [
                {"name": "ブックオフ", "value": f"{item.get('price', 0):,}円", "inline": True},
                {"name": "ステータス", "value": "Amazon未登録", "inline": True},
                {"name": "在庫ランク", "value": item.get('stock_rank', '-'), "inline": True},
                {"name": "全国在庫", "value": f"{item.get('total_stock', 0)}店舗", "inline": True},
                {"name": "秋田店舗", "value": item.get('local_stores', '-')[:100], "inline": False},
            ]
        }
        embeds.append(embed)

    # サマリー作成
    stats = stats or {}
    summary_parts = []
    if stats.get('checked'):
        summary_parts.append(f"チェック: {stats['checked']}件")
    if stats.get('skipped'):
        summary_parts.append(f"スキップ: {stats['skipped']}件")

    content_parts = []
    if profit_items:
        content_parts.append(f"🎯 利益商品: {len(profit_items)}件")
    if unregistered_items:
        content_parts.append(f"📦 Amazon未登録: {len(unregistered_items)}件")

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


def run_finder(categories=None, limit_per_category=20, output_file=None, target_prefecture="秋田県", use_new_arrivals=False, discord_webhook=None):
    """メイン処理

    Args:
        use_new_arrivals: Trueなら新着ページから取得（Playwright使用）
        discord_webhook: Discord Webhook URL（指定すると利益商品を通知）
    """
    if categories is None:
        categories = ["dvd"]

    if output_file is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"profit_akita_{timestamp}.csv"

    results = []
    tokens_left = 300
    price_cache = load_price_cache()
    seen_data = load_seen_products()
    seen_products = seen_data['all']
    frontier = seen_data['frontier']
    cache_hits = 0
    seen_skips = 0
    frontier_stops = 0

    mode_str = "新着" if use_new_arrivals else "カテゴリ"
    print(f"=== ブックオフ利益商品ファインダー ===")
    print(f"モード: {mode_str}")
    print(f"対象地域: {target_prefecture}")
    print(f"カテゴリ: {', '.join(categories)}")
    print(f"各カテゴリ上限: {limit_per_category}件")
    print(f"[DEBUG] 処理済み読込: {len(seen_products)}件, frontier: {list(frontier.keys())}\n")

    for cat_name in categories:
        if not use_new_arrivals and cat_name not in CATEGORIES:
            print(f"不明なカテゴリ: {cat_name}")
            continue

        print(f"\n=== {cat_name.upper()} {'新着' if use_new_arrivals else 'カテゴリ'} ===")

        # 商品ID取得
        if use_new_arrivals:
            product_ids = get_new_arrivals(tab=cat_name, limit=limit_per_category)
        else:
            cat_url = CATEGORIES[cat_name]
            product_ids = get_product_ids(cat_url, limit=limit_per_category)
        print(f"商品数: {len(product_ids)}")

        # 差分チェック: 新着確認 → なければ続きを処理
        cat_frontier = frontier.get(cat_name, [])
        new_at_top = []  # 前回より上に追加された新着
        continue_from_last = []  # 前回の続き（未処理分）

        frontier_hit = False
        for pid in product_ids:
            if pid in cat_frontier:
                frontier_hit = True
                continue  # frontierに到達しても止まらず続行

            if pid not in seen_products:
                if not frontier_hit:
                    new_at_top.append(pid)
                else:
                    continue_from_last.append(pid)
            else:
                seen_skips += 1

        # 新着があれば新着を処理、なければ続きを処理
        if new_at_top:
            print(f"新着発見: {len(new_at_top)}件")
            new_product_ids = new_at_top
        elif continue_from_last:
            print(f"新着なし → 続きから処理: {len(continue_from_last)}件")
            new_product_ids = continue_from_last
            frontier_stops += 1
        else:
            print(f"全て処理済み")
            new_product_ids = []
            frontier_stops += 1

        # 今回の先頭10件をフロンティアとして保存
        frontier[cat_name] = product_ids[:10]

        for i, pid in enumerate(new_product_ids):
            print(f"\n[{i+1}/{len(new_product_ids)}] 商品ID: {pid}")
            seen_products.add(pid)  # 処理済みとしてマーク

            # 商品詳細取得
            product = get_product_details(pid)
            if not product:
                continue

            print(f"  {product['title'][:40]}...")
            print(f"  ブックオフ: {product['price']:,}円")

            # 店舗在庫チェック
            total_stock, local_stores = get_store_stock(product['html'], target_prefecture)

            if not local_stores:
                print(f"  → {target_prefecture}在庫なし、スキップ")
                continue

            # 在庫ランク判定（30店舗以下のみ処理）
            if total_stock <= 10:
                stock_rank = "S"  # 希少
            elif total_stock <= 30:
                stock_rank = "A"  # やや希少
            else:
                print(f"  → 全国在庫: {total_stock}店舗 → 大量在庫、スキップ")
                continue

            print(f"  → 全国在庫: {total_stock}店舗 [ランク{stock_rank}]")
            print(f"  → {target_prefecture}: {len(local_stores)}店舗")
            for store in local_stores:
                print(f"     - {store['name']} ({store['city']})")

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
                    "local_stores": ", ".join([s['name'] for s in local_stores]),
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

            # Keepa API（レート制限対策で間隔を空ける）
            time.sleep(KEEPA_DELAY)
            keepa = get_keepa_data(product['jan'])

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
                    "local_stores": ", ".join([s['name'] for s in local_stores]),
                    "status": "Amazon未登録"
                })
                continue

            tokens_left = keepa['tokens_left']

            # キャッシュに保存
            price_cache[product['jan']] = {
                'price': keepa['used_price'],
                'asin': keepa['asin'],
                'updated': datetime.now().strftime("%Y-%m-%d")
            }

            # 価格表示（現在価格とavg90両方）
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

            # Keepaグラフ URL
            keepa_url = f"https://keepa.com/#!product/5-{keepa['asin']}" if keepa['asin'] else None

            # ステータス判定
            if profit and profit >= MIN_PROFIT:
                status = "利益あり"
                print(f"  ★★★ 利益あり！ ★★★")
            elif profit and profit > 0:
                status = "薄利"
            elif profit is not None:
                status = "赤字"
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
                "local_stores": ", ".join([s['name'] for s in local_stores]),
                "status": status
            })

    # CSV出力
    print(f"\n\n=== 結果出力: {output_file} ===")

    fieldnames = ["stock_rank", "status", "title", "price", "amazon_used_avg90", "amazon_used_current", "profit", "rank", "total_stock", "local_stores", "url", "keepa_url", "jan", "asin", "id"]
    with open(output_file, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()

        # 利益順にソート（利益あり・薄利・Amazon未登録のみ）
        filtered = [r for r in results if r['status'] in ('利益あり', '薄利', 'Amazon未登録')]
        sorted_results = sorted(filtered, key=lambda x: x['profit'] if x['profit'] else -99999, reverse=True)
        writer.writerows(sorted_results)

    # キャッシュ保存
    save_price_cache(price_cache)
    save_seen_products({'all': seen_products, 'frontier': frontier})

    # サマリー
    profit_items = [r for r in results if r['status'] == '利益あり']
    print(f"\n{target_prefecture}在庫あり: {len(results)}件")
    print(f"利益あり: {len(profit_items)}件")
    print(f"残りトークン: {tokens_left}")
    print(f"差分チェック停止: {frontier_stops}回")
    print(f"処理済みスキップ: {seen_skips}件")
    print(f"キャッシュヒット: {cache_hits}件（トークン節約）")
    print(f"キャッシュ総数: {len(price_cache)}件")
    print(f"処理済み総数: {len(seen_products)}件")

    # Discord通知（結果あるなしに関わらず送信）
    webhook_url = discord_webhook or os.environ.get("DISCORD_WEBHOOK_URL")
    if webhook_url:
        stats = {
            'checked': len(results),
            'skipped': seen_skips + cache_hits
        }
        send_discord_notification(webhook_url, results, stats)

    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="ブックオフ利益商品ファインダー（秋田県フィルター付き）")
    parser.add_argument("--categories", nargs="+", default=["dvd"], help="カテゴリ (dvd, cd, game)")
    parser.add_argument("--limit", type=int, default=200, help="カテゴリあたりの商品数")
    parser.add_argument("--output", type=str, help="出力ファイル名")
    parser.add_argument("--prefecture", type=str, default="秋田県", help="対象都道府県")
    parser.add_argument("--new", action="store_true", help="新着モード（Playwright使用）")
    parser.add_argument("--discord", type=str, help="Discord Webhook URL")
    args = parser.parse_args()

    run_finder(
        categories=args.categories,
        limit_per_category=args.limit,
        output_file=args.output,
        target_prefecture=args.prefecture,
        use_new_arrivals=args.new,
        discord_webhook=args.discord
    )
