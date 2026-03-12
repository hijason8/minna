# 部署到網上（Railway）

把「大家的日本語」後端 + 前端部署到 Railway，即可用手機在外用 HTTPS 網址連線。

---

## 一、事前準備

1. **程式碼放到 GitHub**
   - 在 GitHub 建立一個 repo，把專案 `L` 的程式碼 push 上去（不要 push `.venv`、`app_data.db`、`__pycache__`）。
   - 若還沒用 Git，可在專案目錄執行：
     ```bash
     git init
     git add .
     git commit -m "Initial commit"
     # 在 GitHub 建立 repo 後：
     git remote add origin https://github.com/你的帳號/你的repo名.git
     git branch -M main
     git push -u origin main
     ```
   - 建議在專案根目錄加 `.gitignore`，內容包含：
     ```
     .venv/
     __pycache__/
     *.pyc
     app_data.db
     .env
     ```

2. **註冊 Railway**
   - 打開 https://railway.app ，用 GitHub 登入。

---

## 二、在 Railway 建立專案

1. **New Project**
   - 點 **「New Project」**。

2. **先加 Postgres（資料庫）**
   - 選 **「Add Plugin」** 或 **「Database」** → 選 **「PostgreSQL」**。
   - Railway 會自動建立一個 Postgres，並產生 **DATABASE_URL**（之後給 Web Service 用）。

3. **加 Web Service（你的後端）**
   - 再點 **「New」** → **「GitHub Repo」**，選你剛 push 的 repo。
   - Railway 會偵測到這是 Python 專案，並讀取 `requirements.txt`。

4. **把 Web Service 連到 Postgres**
   - 點進你的 **Web Service** → **「Variables」** 分頁。
   - 應該會看到 **DATABASE_URL** 已經存在（若沒有，到 Postgres 那個服務 → **「Connect」** / **「Variables」**，把 `DATABASE_URL` 複製到 Web Service 的 Variables）。
   - 必要時在 Web Service 的 **「Variables」** 裡點 **「Add Reference」**，選擇 Postgres 的 `DATABASE_URL`，讓 Web Service 能用到。

5. **設定啟動指令（若沒自動抓到）**
   - 專案裡已有 **Procfile**，Railway 通常會自動用 `web: uvicorn app.main:app --host 0.0.0.0 --port $PORT`。
   - 若沒有，在 Web Service → **「Settings」** → **「Deploy」** 裡把 **Start Command** 設成：
     ```bash
     uvicorn app.main:app --host 0.0.0.0 --port $PORT
     ```

6. **部署**
   - 儲存後 Railway 會自動 build 並部署。
   - 部署完成後，在 Web Service 的 **「Settings」** → **「Networking」** 裡點 **「Generate Domain」**，會得到一個網址，例如：`https://你的專案名.up.railway.app`。

---

## 三、用手機／電腦連線

- 在瀏覽器打開：**`https://你的專案名.up.railway.app`**
- 若首頁會導向靜態檔，可直接開：**`https://你的專案名.up.railway.app/static/index.html`**

資料會存在 Railway 的 Postgres，出門在外用同一網址即可使用。

---

## 四、環境變數整理

| 變數 | 說明 |
|------|------|
| **DATABASE_URL** | 由 Railway 在加裝 Postgres 時自動注入，**不用手動填**。 |
| APP_AUDIO_CACHE_DIR | 選填，音檔快取目錄（雲端重啟可能清空）。 |
| APP_DAILY_PARSE_LIMIT | 選填，每日解析 URL 上限，預設 5。 |

---

## 五、本地開發

- 本機**不設** `DATABASE_URL` 時，會用 **SQLite**（`app_data.db`）。
- 要本機用 Postgres：在 `.env` 設 `DATABASE_URL=postgresql://user:pass@localhost:5432/dbname`。

---

## 六、常見問題

- **Build 失敗**：確認 `requirements.txt` 有被 push，且沒有漏掉 `sqlalchemy`、`psycopg2-binary`。
- **開網站 500 錯誤**：到 Railway Web Service 的 **「Deployments」** 點最新一次部署，看 **Logs**，多數是 `DATABASE_URL` 沒設好或連不到 Postgres。
- **免費額度**：Railway 有免費額度，用量不大時可不用綁卡；若超過會要求升級。
