# 📈 Investment Decision Support System

一個整合 Telegram Bot、Notion API 與規則式 AI 分析的股票投資決策輔助系統。
支援美股與台股，自動追蹤持倉、記錄交易、分析技術指標與行為偏誤。

---

## 功能概覽

- **股票查詢**：即時價格 + MA20/MA50/RSI 技術分析 + 趨勢判斷
- **交易記錄**：買賣紀錄自動存入 Notion
- **價格警報**：設定目標價，達標時自動通知
- **持倉追蹤**：損益計算，每日自動更新
- **AI 決策建議**：規則式分析，輸出建議（BUY/SELL/HOLD/WAIT）與風險等級
- **行為偏誤分析**：偵測恐慌賣出、頻繁交易等不良習慣
- **每日報告**：定時自動推送 Telegram 摘要

---

## 系統架構

```
┌─────────────────────────────────────────────┐
│              Interface Layer                │
│         Telegram Bot (使用者互動)            │
└────────────────────┬────────────────────────┘
                     │
┌────────────────────▼────────────────────────┐
│               Logic Layer                   │
│  data_fetcher │ indicators │ decision_engine │
│  behavior_analysis │ scheduler               │
└────────────────────┬────────────────────────┘
                     │
┌────────────────────▼────────────────────────┐
│               Data Layer                    │
│     Yahoo Finance API │ Notion API           │
└─────────────────────────────────────────────┘
```

---

## 專案結構

```
.
├── main.py               # 主入口（Bot + Scheduler 同時啟動）
├── config.py             # 環境變數讀取
├── logger.py             # 日誌系統（檔案 + Console）
├── data_fetcher.py       # Yahoo Finance 股價抓取
├── indicators.py         # 技術指標（MA20, MA50, RSI14, 趨勢）
├── behavior_analysis.py  # 行為偏誤分析
├── decision_engine.py    # 規則式決策引擎
├── notion_client.py      # Notion 四大資料庫 CRUD
├── telegram_bot.py       # Bot 指令處理
├── scheduler.py          # 每日定時任務
├── Dockerfile            # 容器化設定
├── railway.toml          # Railway 部署設定
├── requirements.txt      # Python 依賴
└── .env.example          # 環境變數範本
```

---

## Notion 資料庫結構

建立以下 4 個 Database，欄位名稱須完全一致：

### Portfolio（持倉）
| 欄位 | 類型 |
|---|---|
| stock | Title |
| cost | Number |
| shares | Number |
| current_price | Number |

### Trades（交易紀錄）
| 欄位 | 類型 |
|---|---|
| stock | Title |
| date | Date |
| action | Select（buy / sell）|
| price | Number |
| reason | Text |
| emotion | Select（fear / greed / neutral）|

### Watchlist（價格警報）
| 欄位 | 類型 |
|---|---|
| stock | Title |
| target_price | Number |
| condition | Select（above / below）|
| status | Select（active / triggered）|

### Decision Log（決策紀錄）
| 欄位 | 類型 |
|---|---|
| decision | Title |
| date | Date |
| rationale | Text |
| outcome | Text |
| reflection | Text |

---

## 環境需求

- Python 3.11+
- 網路可連線至 Telegram、Yahoo Finance、Notion

---

## 本機安裝與執行

```bash
# 1. 複製專案
git clone https://github.com/你的帳號/你的repo.git
cd 你的repo

# 2. 安裝依賴
pip install -r requirements.txt

# 3. 設定環境變數
cp .env.example .env
# 用編輯器打開 .env，填入所有 token 和 ID

# 4. 啟動
python main.py
```

---

## 雲端部署（Railway）

### 步驟一：推上 GitHub
```bash
git init
git add .
git commit -m "init"
git remote add origin https://github.com/你的帳號/repo.git
git push -u origin master
```

### 步驟二：Railway 設定
1. 前往 [railway.app](https://railway.app)，用 GitHub 登入
2. **New Project** → **Deploy from GitHub repo** → 選你的 repo
3. 進入專案 → **Variables** → 新增以下所有變數：

| 變數名稱 | 說明 |
|---|---|
| `TELEGRAM_BOT_TOKEN` | 從 @BotFather 取得 |
| `TELEGRAM_CHAT_ID` | 從 @userinfobot 取得 |
| `NOTION_TOKEN` | 從 notion.so/my-integrations 取得 |
| `NOTION_PORTFOLIO_DB_ID` | Portfolio DB 的 URL ID |
| `NOTION_TRADES_DB_ID` | Trades DB 的 URL ID |
| `NOTION_WATCHLIST_DB_ID` | Watchlist DB 的 URL ID |
| `NOTION_DECISION_LOG_DB_ID` | Decision Log DB 的 URL ID |
| `DAILY_REPORT_HOUR` | 每日報告時間（小時，預設 `8`）|
| `DAILY_REPORT_MINUTE` | 每日報告時間（分鐘，預設 `0`）|

4. 設定完成後 Railway 自動重新部署
5. 查看 **Logs** 出現 `Starting Telegram bot...` 即代表成功

> **注意**：`.env` 檔案不要上傳 GitHub。所有密鑰只放在 Railway Variables。

---

## 如何取得各項 Token

### Telegram Bot Token
1. 打開 Telegram，搜尋 `@BotFather`
2. 發送 `/newbot`，依指示設定名稱與帳號
3. 取得 token（格式：`123456789:AAFxxx...`）

### Telegram Chat ID
1. 搜尋 `@userinfobot`，發送任意訊息
2. 回傳的 `Id` 即為你的 Chat ID

### Notion Token
1. 前往 [notion.so/my-integrations](https://www.notion.so/my-integrations)
2. **New integration** → 填名稱 → Submit
3. 複製 Internal Integration Token（格式：`secret_xxx...`）
4. 每個 Database 頁面右上角 `...` → **Connections** → 連接你的 integration

### Notion Database ID
- 在瀏覽器開啟 Database 頁面
- URL 格式：`https://www.notion.so/workspace/`**`這段32位ID`**`?v=...`
- 複製那段 32 位英數字即可

---

## Bot 指令說明

| 指令 | 說明 | 範例 |
|---|---|---|
| `/start` | 歡迎訊息 | `/start` |
| `/help` | 指令列表 | `/help` |
| `/stock <代號>` | 查詢股價與趨勢 | `/stock AAPL` `/stock 2330` |
| `/analyze <代號>` | 完整 AI 決策報告 | `/analyze TSLA` |
| `/buy <代號> <價格>` | 記錄買入 | `/buy AAPL 185.5` |
| `/sell <代號> <價格>` | 記錄賣出 | `/sell 2330 850` |
| `/alert <代號> <目標價>` | 設定價格警報 | `/alert NVDA 900` |
| `/portfolio` | 查看持倉與損益 | `/portfolio` |
| `/behavior` | 行為偏誤分析 | `/behavior` |
| `/summary` | 手動觸發每日報告 | `/summary` |

> 台股直接輸入股票代號即可（如 `2330`），系統自動加上 `.TW`

---

## AI 決策邏輯說明

本系統採用**規則式分析**，邏輯透明可追溯，非黑箱模型：

| 指標 | 規則 | 影響 |
|---|---|---|
| 趨勢 | 價格 > MA20 > MA50 | 加分（看漲）|
| 趨勢 | 價格 < MA20 < MA50 | 扣分（看跌）|
| RSI < 30 | 超賣區間 | 加分（潛在反彈）|
| RSI > 70 | 超買區間 | 扣分（反轉風險）|
| 行為偏誤 | 恐慌賣出 / 頻繁交易 | 額外扣分 |

**輸出結果：**
- 建議：`BUY` / `SELL` / `HOLD` / `WAIT`
- 風險等級：`LOW` / `MEDIUM` / `HIGH`
- 信心分數：0–100
- 文字說明每一條判斷依據

---

## 每日自動報告範例

```
Daily Market Summary — 2026-04-18
────────────────────────
▲ AAPL: 189.5000 (+1.2%)
▼ 2330.TW: 820.0000 (-0.8%)
▲ TSLA: 175.3000 (+3.1%)

Price Alerts Triggered
ALERT: NVDA hit 902.0000 (target 900.0000)
```

---

## 日誌

系統日誌儲存於 `logs/system.log`，自動每日輪替，保留 7 天。

---

## License

MIT
