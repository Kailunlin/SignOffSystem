# SIT 文件：系統整合測試 (System Integration Test)

本文件定義三廠區物流暨物料簽核系統的整合測試範圍。系統目前採用 Django REST Framework 作為 API 層，Celery 處理外部同步與 SLA 背景任務。

---

## 1. 測試目標

1. 驗證前端可透過 JWT Token 正確呼叫 `/api/`。
2. 驗證 WorkflowBuilder 可依廠區、風險、跨廠條件產生簽核關卡。
3. 驗證 ERP Mock 的庫存檢查、自動駁回與同步流程。
4. 驗證樂觀鎖可防止多人同時簽核。
5. 驗證代理人、撤回、修改重提、同步重試等例外流程。

---

## 2. 測試環境

| 元件 | 技術 |
| --- | --- |
| API | Django REST Framework |
| DB | SQLite (`backend/db.sqlite3`) |
| 背景任務 | Celery + Redis |
| 前端 | Vanilla JS SPA |

啟動指令：

```bash
cd backend
python manage.py runserver 8000
celery -A config worker --loglevel=info
```

---

## 3. 測試案例

### 3.1 身分與資料權限

| 案例 | 情境 | 預期 |
| --- | --- | --- |
| AUTH-01 | 一般員工查詢單據 | 只能看到自己或所屬廠區相關單據 |
| AUTH-02 | 台北財務查詢單據 | 可看到跨廠、高風險、高成本與同步失敗單據 |
| AUTH-03 | 非目前關卡簽核人嘗試簽核 | 回傳 403 |

### 3.2 BOM 流程

| 案例 | 情境 | 預期 |
| --- | --- | --- |
| BOM-01 | 台南一般 BOM | 生產主管簽核後進入 APPROVED，背景同步成功後 CLOSED |
| BOM-02 | 高風險 BOM | 生產主管 → 廠區主管 → 台北財務 |
| BOM-03 | TPE 建立 BOM | 驗證失敗，不允許建立 |
| BOM-04 | 物料停用或數量超限 | 提交後 AUTO_REJECT，狀態 REJECTED |

### 3.3 物料轉移流程

| 案例 | 情境 | 預期 |
| --- | --- | --- |
| TRF-01 | 同廠轉移 | 來源廠倉庫主管 → 台北財務 |
| TRF-02 | 台南轉高雄 | 台南倉庫主管 → 高雄倉庫主管 → 台北財務 |
| TRF-03 | 庫存不足 | 提交後 AUTO_REJECT，駁回原因包含庫存不足 |
| TRF-04 | 撤回 | 狀態 CANCELED，寫入稽核紀錄 |

### 3.4 背景同步與例外

| 案例 | 情境 | 預期 |
| --- | --- | --- |
| ADV-01 | 外部同步成功 | 狀態 CLOSED，新增 CLOSE log |
| ADV-02 | 外部同步失敗達上限 | 狀態 SYNC_FAILED |
| ADV-03 | 台北財務手動重試 | 呼叫 retry-sync 後重新排入 Celery |
| ADV-04 | SLA 逾期掃描 | 產生 SLA_REMIND log |

---

## 4. 驗收標準

- `pytest -v` 全數通過。
- `python backend/manage.py check` 無錯誤。
- `node --check frontend/app.js` 無語法錯誤。
- 前端提交、簽核、駁回、撤回、修改重提、重試同步都呼叫 `/api/documents/{id}/{action}/`。
