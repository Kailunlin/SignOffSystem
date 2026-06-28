# DEV 文件：開發者指南 (Developer Guide)

本文件旨在協助新進開發者快速了解「三廠區物流暨物料簽核系統」的專案架構、環境設定、啟動方式以及日常開發流程。

---

## 1. 專案架構概述

本專案採用 **微服務解耦 (Microservices) 架構**，主要分為三個區塊：

* **`admin_service/` (資料與管理層)**：基於 Django。專門負責 SQLite 資料庫 Schema 的定義與自動產生 Migration，同時提供 Django Admin 作為系統管理員配置帳號與基礎設施的介面。
* **`api_service/` (核心業務層)**：基於 FastAPI。專門提供高效能、非同步的 RESTful API，並負責處理動態簽核工作流 (WorkflowBuilder)、狀態機轉換與外部系統 Mock (ERP, HR, 會計)。
* **`frontend/` (前端介面)**：基於純原生的 HTML / CSS (Vanilla JS) 構建的單頁應用程式 (SPA)，透過 Fetch API 與 FastAPI 溝通。

> **💡 核心設計哲學**：
> 所有資料庫的 Schema 變更 **必須且只能** 透過 Django (`admin_service/core/models.py`) 進行管理。FastAPI 僅透過 SQLAlchemy 進行唯讀映射與業務邏輯寫入，不得自行建立或修改資料表結構。

---

## 2. 環境準備與安裝

1. **Python 環境**：確保系統已安裝 Python 3.10 或以上版本。
2. **安裝相依套件**：
   在專案根目錄下執行以下指令以安裝所有必要的套件：
   ```bash
   pip install -r requirements.txt
   ```
   *(主要套件包含：`fastapi`, `uvicorn`, `django`, `sqlalchemy`, `pytest`, `pytest-django`, `pytest-asyncio` 等)*

---

## 3. 本地開發啟動方式

為了完整運行系統，您需要同時啟動後端資料庫層與 API 服務層：

### 步驟一：啟動 Django Admin 後台 (可選，用於管理資料)
這將會在 `http://127.0.0.1:8000` (預設) 啟動 Django 服務。
```bash
cd admin_service
python manage.py runserver 8080  # 建議改用 8080 避免與 FastAPI 衝突
```

### 步驟二：啟動 FastAPI 服務 (核心必要)
這將會在 `http://127.0.0.1:8000` 啟動 API 伺服器，並支援自動重載 (Hot Reload)。
```bash
# 請在專案根目錄執行
uvicorn signoff_system.api:app --reload --app-dir api_service
```

### 步驟三：開啟前端頁面
直接使用瀏覽器開啟 `frontend/index.html` 即可開始測試，無須額外編譯。
*(推薦使用 VSCode 的 Live Server 套件開啟以獲得最佳體驗)*

---

## 4. 日常開發流程 (Database Workflow)

當您需要新增欄位或修改資料庫結構時，請務必遵循以下流程：

1. **修改 Django Model**：
   編輯 `admin_service/core/models.py`，加入或修改您的欄位 (例如：`rejection_reason = models.TextField()`)。
2. **產生並套用 Migration**：
   ```bash
   cd admin_service
   python manage.py makemigrations
   python manage.py migrate
   ```
   *(註：此動作會更新專案根目錄下的 `signoff.db`)*
3. **對齊 FastAPI 的 SQLAlchemy Model**：
   編輯 `api_service/signoff_system/models.py`，將剛才新增的欄位同步映射到對應的 SQLAlchemy Class 中，確保欄位名稱與型別一致。

---

## 5. 執行自動化測試 (TDD)

本專案強烈建議採用 **測試驅動開發 (TDD)**。測試框架使用 `pytest`，並透過 `pytest.ini` 統一管理環境變數與路徑。

* **執行所有測試**：
  在專案根目錄下執行：
  ```bash
  pytest
  ```
* **執行特定測試檔案**：
  ```bash
  pytest tests/test_api.py
  ```

> **⚠️ 測試注意事項**：
> `test_api.py` 中使用了 `TestClient` 模擬 HTTP 請求，執行前系統會自動載入 SQLAlchemy 模型並使用根目錄的 `signoff.db` 進行整合測試，請確認資料庫已經是最新的 Migrate 狀態。

---

## 6. 目錄結構指引

```text
SignOffSystem/
├── admin_service/           # Django 微服務 (DB Migrations & Admin)
│   ├── admin_service/       # Django 設定檔
│   └── core/                # Django 核心應用程式 (models.py, admin.py)
├── api_service/             # FastAPI 微服務 (核心 API)
│   └── signoff_system/      # API 邏輯 (api.py, services.py, models.py, auth.py)
├── docs/                    # 系統開發與規格文件 (SA.md, SD.md, SIT.md, DEV.md)
├── frontend/                # 前端介面 (HTML, CSS, JS)
├── tests/                   # 測試腳本 (pytest)
├── pytest.ini               # Pytest 設定檔 (配置 pythonpath)
├── requirements.txt         # Python 依賴清單
└── signoff.db               # 共用的 SQLite 資料庫檔案
```
