# DEV 文件：開發者指南 (Developer Guide)

本文件說明目前專案的實際開發方式。系統已收斂為 **Django + Django REST Framework + Celery + Vanilla JS SPA** 架構。

---

## 1. 專案架構

| 路徑 | 說明 |
| --- | --- |
| `backend/` | Django 專案根目錄 |
| `backend/config/` | Django settings、urls、Celery 設定 |
| `backend/signoff/` | 簽核系統 app，包含 models、serializers、views、services、tasks |
| `backend/tests/` | 服務層自動化測試 |
| `frontend/` | Vanilla JS SPA |
| `docs/` | SA、SD、SIT、UI/UX、操作手冊等文件 |

核心原則：

- 資料模型以 `backend/signoff/models.py` 為唯一來源。
- 業務規則集中在 `backend/signoff/services.py`。
- 外部同步與 SLA 掃描放在 `backend/signoff/tasks.py`。
- 前端透過 `/api/` 呼叫 Django REST Framework API。

---

## 2. 環境準備

建議使用 `backend/.venv` 或自行建立 virtualenv。

```bash
cd backend
pip install -r requirements.txt
```

---

## 3. 資料庫流程

新增或修改欄位時：

```bash
cd backend
python manage.py makemigrations
python manage.py migrate
```

建立測試資料：

```bash
cd backend
python manage.py seed_data
```

或在專案根目錄執行：

```bash
python seed_db.py
```

---

## 4. 本地啟動

啟動 Django/DRF API：

```bash
cd backend
python manage.py runserver 8000
```

API 文件：

- `http://127.0.0.1:8000/swagger/`
- `http://127.0.0.1:8000/redoc/`

啟動 Celery Worker：

```bash
cd backend
celery -A config worker --loglevel=info
```

Celery 需要 Redis，預設為 `redis://localhost:6379/0`。

前端可直接開啟 `frontend/index.html`，或透過 `docker compose up --build` 由 Nginx 提供。

---

## 5. 測試

在專案根目錄執行：

```bash
pytest -v
```

目前根目錄 `pytest.ini` 會指向 `backend/tests`。

也可以在 backend 目錄執行：

```bash
cd backend
python -m pytest -v
python manage.py check
```

---

## 6. API 規則

- 建立 BOM：`POST /api/boms/`
- 建立物料轉移：`POST /api/transfers/`
- 工作流 action：`POST /api/documents/{id}/{action}/`
- 支援 action：`submit`、`approve`、`reject`、`cancel`、`revise`、`retry-sync`
- 所有 action payload 都需要帶 `version`，用於樂觀鎖。
- 簽核權限需同時符合目前關卡的 `role` 與 `site_code`。
