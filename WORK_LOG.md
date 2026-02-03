# 作業ログ

## 2026-02-03: 除外リストをSQLite化

### 変更内容

1. **exclusion_db.py 新規作成**
   - SQLiteベースの除外リスト管理
   - 除外JAN、除外キーワード、除外商品IDを管理
   - 10万件以上でも高速検索可能（インデックス付き）

2. **main.py 修正**
   - GAS APIから除外リストを取得する処理を削除
   - SQLite（exclusion_db）を使用するよう変更
   - 赤字商品・ゴミ価格商品を自動で除外DBに追加

3. **run-finder.yml 修正**
   - exclusions.db をgit commitに追加

### 自動除外の条件
- **赤字**: 利益がマイナスの商品 → JANを除外DBに追加
- **ゴミ価格**: Amazon中古価格が500円以下 → JANを除外DBに追加

### 除外DBの構造
```
exclusions.db
├── excluded_jan (JAN, 理由, Amazon価格, 作成日時)
├── excluded_keywords (キーワード, 理由, 作成日時)
└── excluded_products (商品ID, 理由, 作成日時)
```

### GASとの関係
- GASの除外リスト（スプレッドシート）は今後使用しない
- 除外管理はGitHub上のexclusions.dbに一本化
