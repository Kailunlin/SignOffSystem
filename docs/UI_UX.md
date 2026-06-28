# UI/UX 設計規格 (UI/UX Design Specification)

本文件記錄「三廠區物流暨物料簽核系統」前端介面的設計語言、色彩系統、元件規範與互動準則，供前端開發與設計迭代時參考。

---

## 1. 設計原則

| 原則 | 說明 |
| :--- | :--- |
| **清晰可讀** | 所有狀態與操作結果應以清楚的文字或色彩標示，不得依賴圖示作為唯一提示 |
| **角色感知** | 頁面應依據登入角色動態隱藏或禁用不可使用的操作按鈕 |
| **防呆優先** | 高風險操作（駁回、撤回）需二次確認 (Modal Dialog) |
| **即時回饋** | 所有 API 請求須顯示 Loading 指示器，成功或失敗皆須有 Toast 通知 |

---

## 2. 色彩系統 (Design Tokens)

### 主色調 (Dark Mode)
| Token | 色碼 | 用途 |
| :--- | :--- | :--- |
| `--bg` | `#0f1117` | 最底層背景 |
| `--surface` | `#1a1d27` | 卡片、表格背景 |
| `--surface-2` | `#21253a` | 表格 Header、次層背景 |
| `--border-subtle` | `rgba(255,255,255,0.07)` | 細邊框 |
| `--text-primary` | `#e2e8f0` | 主要文字 |
| `--text-muted` | `#8892a4` | 次要說明文字 |
| `--primary` | `#6366f1` | 主要按鈕、強調色 (Indigo) |
| `--primary-hover` | `#4f52d9` | 主按鈕 Hover 態 |

### 狀態色 (Status Colors)
| Token | 色碼 | 代表狀態 |
| :--- | :--- | :--- |
| `--green` | `#10b981` | CLOSED、APPROVED |
| `--blue` | `#3b82f6` | APPROVING |
| `--yellow` | `#f59e0b` | DRAFT、SUBMITTED |
| `--red` | `#ef4444` | REJECTED、SYNC_FAILED |
| `--gray` | `#64748b` | CANCELED |

---

## 3. 元件規範 (Component Spec)

### 3.1 狀態徽章 (Status Badge)
- 使用行內 Pill 形狀，`border-radius: 20px`，搭配對應狀態色的半透明背景 (`opacity: 0.15`)
- 字體大小：`11px`，字重：`600`，全部大寫

```
[ ● APPROVING ]  → 藍色
[ ● CLOSED    ]  → 綠色
[ ● REJECTED  ]  → 紅色
```

### 3.2 表單欄位 (Form Input)
- 高度：`40px`，`border-radius: 8px`
- 邊框：`1.5px solid var(--border-subtle)`
- 聚焦態：`border-color: var(--primary)`，`box-shadow: 0 0 0 3px rgba(99,102,241,0.15)`
- Placeholder 顏色：`var(--text-muted)`

### 3.3 操作按鈕 (Action Buttons)
- **主要按鈕 (同意/提交)**：`background: var(--primary)`，hover 有 `translateY(-1px)` 上移效果
- **危險按鈕 (駁回)**：`background: rgba(239,68,68,0.12)`，邊框 `var(--red)`
- **次要按鈕 (撤回/取消)**：`background: var(--surface-2)`

### 3.4 資料表格 (Data Table)
- 表格容器：`overflow-x: auto`，避免在小螢幕截斷
- 每行 hover：`background: rgba(99,102,241,0.04)`
- 操作列 (`<td>` 含按鈕) 置右對齊

### 3.5 Modal 對話框
- 背景遮罩：`rgba(0,0,0,0.6)`，模糊效果 `backdrop-filter: blur(4px)`
- 容器：`max-width: 540px`，`border-radius: 16px`
- 動畫：進場 `scaleY(0.95) + opacity(0)` → `scaleY(1) + opacity(1)`, 200ms ease-out

---

## 4. 頁面佈局 (Layout)

```
┌─────────────────────────────────────────────┐
│  Sidebar (240px)  │  Main Content Area       │
│  ┌─────────────┐  │  ┌─────────────────────┐ │
│  │  Logo       │  │  │  Page Header        │ │
│  │  Nav Items  │  │  │  (Title + Actions)  │ │
│  │             │  │  ├─────────────────────┤ │
│  │             │  │  │  Search / Filter    │ │
│  │             │  │  ├─────────────────────┤ │
│  │             │  │  │  Data Table / Form  │ │
│  ├─────────────┤  │  │                     │ │
│  │  User Info  │  │  │                     │ │
│  └─────────────┘  │  └─────────────────────┘ │
└─────────────────────────────────────────────┘
```

---

## 5. 響應式設計斷點 (RWD Breakpoints)

| 斷點 | 寬度 | 行為 |
| :--- | :--- | :--- |
| Desktop | > 1024px | 完整 Sidebar + 主內容並排 |
| Tablet | 768px ~ 1024px | Sidebar 縮小至 80px，只顯示圖示 |
| Mobile | < 768px | 搜尋列與表單欄位自動換行，統計卡片改為 2 欄 |
| Mobile SM | < 480px | 統計卡片改為 1 欄，padding 縮減 |

---

## 6. 微互動設計 (Micro Interactions)

| 元素 | 互動 | 動畫規格 |
| :--- | :--- | :--- |
| 頁面切換 | Fade In | `opacity 0→1, translateY 8px→0, 200ms ease` |
| 按鈕 Hover | 上移 | `translateY(-1px), 150ms ease` |
| Modal 開啟 | Scale In | `scale 0.95→1, opacity 0→1, 200ms ease-out` |
| Toast 通知 | Slide In | 從右側滑入，3秒後自動消失 |
| 表格行 Hover | 背景色 | `background rgba(99,102,241,0.04), 150ms` |
