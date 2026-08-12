# ResumeAgent 双轨架构重构执行方案

## 目标

在**完整保留当前 PyQt6 稳定版本**的前提下，执行未来重构架构：

React + TypeScript + Tailwind + shadcn/ui + FastAPI + Python + Playwright，最后再接入 Tauri 打包为 EXE。

核心原则：

> **迁移 UI，不重写已经稳定的自动化核心；新旧版本并行，任何阶段都可以回滚。**

---

## 1. 最终目标架构

```text
                    ResumeAgent
                         │
             ┌───────────┴───────────┐
             │                       │
       Legacy / Stable          New Architecture
             │                       │
           PyQt6                React + FastAPI
             │                       │
       Python Core ←────────→ Python Core
                                     │
                                 Playwright
                                     │
                                   Chrome

最终：
React + FastAPI
      ↓
    Tauri
      ↓
ResumeAgent.exe
```

技术栈：

- 前端：React + TypeScript + Vite
- UI：Linear + Raycast + shadcn/ui + AI Agent
  - ResumeAgent

┌─────────────────────┐
│ 🏠 工作台           │
│                     │
│ 💼 岗位             │ 
│                     │
│ ⚡ 任务             │
│                     │
│ 👤 候选人           │
│                     │
│ 📊 数据             │
│                     │
│ ─────────────       │
│                     │
│ ⚙ 设置              │
└─────────────────────┘
  - ┌─────────────────────────────────────────────┐
│ 售前咨询工程师                    ● Chrome   │
│                                             │
│ 416 位候选人                                │
│                                             │
│ █████████████████░░░  137 / 416             │
│                                             │
│ ┌────────┐ ┌────────┐ ┌────────┐            │
│ │ 416    │ │ 32     │ │ 105    │            │
│ │候选人  │ │AI通过  │ │AI淘汰  │            │
│ └────────┘ └────────┘ └────────┘            │
│                                             │
│ 当前候选人                                  │
│                                             │
│ 张三     本科     5年经验      ✓ AI通过      │
│ 李四     本科     2年经验      × 不符合      │
│ 王五     硕士     6年经验      ✓ AI通过      │
└─────────────────────────────────────────────┘
- 后端：Python + FastAPI
- 自动化：Playwright
- 数据库：继续使用当前 SQLite，除非确有迁移需求
- 桌面壳：Tauri v2
- Python 打包：PyInstaller sidecar

---

# 2. 总体迁移策略

不要直接：

```text
PyQt6 → React
```

而采用：

```text
                    Python Core
                         │
                ┌────────┴────────┐
                ↓                 ↓
              PyQt6            FastAPI
                │                 │
                │               React
                │                 │
                ↓                 ↓
             旧版本            新版本
```

当前 PyQt6 作为稳定生产基线，直到 React + FastAPI + Tauri 完整验收后才考虑退役。

---

# 3. Phase 0：建立稳定回滚点

在任何重构开始之前：

```bash
git tag pyqt6-stable
```

同时保留当前：

```text
ResumeAgent-PyQt6.exe
```

必须验证当前版本：

- Chrome 调试窗口检测
- Chrome 自动启动
- Playwright 连接
- 前程无忧岗位获取
- 岗位选择
- 候选人获取
- 自动滚动到底
- 自动翻页
- 简历附件弹窗
- LLM 简历判断
- 符合条件自动下载
- 不符合条件记录理由
- Excel 结果生成
- SQLite 任务状态
- 暂停
- 继续
- 中断
- 关闭软件后恢复
- Chrome 异常处理
- 登录异常处理

如果当前版本有问题，先记录，不要在重构阶段顺便大规模修改。

---

# 4. Phase 1：Python Core 解耦

这是最重要的阶段。

目标：

```text
             Python Core
                  │
        ┌─────────┴─────────┐
        ↓                   ↓
      PyQt6              FastAPI
```

Core 必须与 PyQt6 解耦。

以下模块不能依赖 PyQt6：

- BrowserManager
- TaskManager
- CandidateProcessor
- LLMService
- DownloadService
- ExcelService
- DatabaseService
- JobService
- CandidateService

禁止 Core 出现：

```python
from PyQt6...
QObject
QTimer
pyqtSignal
QWidget
QApplication
```

如果现有代码高度耦合，不要大面积重写，增加 Adapter：

```text
PyQt6
  ↓
LegacyAdapter
  ↓
Python Core
```

新架构：

```text
React
  ↓
FastAPI
  ↓
Python Core
```

建议 Core 提供清晰的业务接口：

```python
class BrowserManager:
    start()
    connect()
    disconnect()
    health_check()

class TaskManager:
    create_task()
    start_task()
    pause_task()
    resume_task()
    cancel_task()

class CandidateProcessor:
    process_candidate()

class LLMService:
    analyze_resume()

class DownloadService:
    download_resume()
```

具体方法名以现有项目实际代码为准。

---

# 5. Phase 2：建立 FastAPI

新增 FastAPI，但不得破坏 PyQt6。

推荐：

```text
backend/
├── app.py
├── api/
│   ├── jobs.py
│   ├── candidates.py
│   ├── tasks.py
│   ├── browser.py
│   ├── settings.py
│   └── websocket.py
├── services/
├── core/
└── schemas/
```

初始 API：

```text
GET  /api/jobs
GET  /api/candidates
POST /api/tasks
GET  /api/tasks
GET  /api/tasks/{id}
POST /api/tasks/{id}/start
POST /api/tasks/{id}/pause
POST /api/tasks/{id}/resume
POST /api/tasks/{id}/cancel
GET  /api/tasks/{id}/stats
GET  /api/browser/status
POST /api/browser/connect
POST /api/browser/disconnect
GET  /api/settings
PUT  /api/settings
WS   /api/ws
```

API 只负责：

```text
HTTP/WebSocket
 ↓
Service / Manager
 ↓
Python Core
```

禁止在 FastAPI 路由中直接写 Playwright 业务。

---

# 6. Phase 3：建立 React 前端

技术栈：

```text
React
TypeScript
Vite
Tailwind CSS
shadcn/ui
```

不要把 PyQt6 UI 1:1 搬到 React，要重新设计现代桌面软件 UI。

推荐导航：

```text
ResumeAgent

🏠 工作台
💼 岗位
⚡ 任务
👤 候选人
📊 数据
⚙ 设置
```

第一版 UI 至少包含：

### 工作台

- 当前岗位
- 当前任务
- 候选人数
- AI 通过
- AI 淘汰
- 下载数量
- 当前进度
- Chrome 状态

### 岗位

- 岗位列表
- 刷新岗位
- 选择岗位
- 岗位状态

### 任务

- 创建任务
- 开始
- 暂停
- 继续
- 取消
- 任务进度
- 任务状态
- 任务历史

### 候选人

- 候选人列表
- AI 判断结果
- AI 判断理由
- 下载状态

### 日志

- 实时日志
- 错误日志
- 当前操作

### 设置

- LLM 配置
- 浏览器配置
- 下载目录
- 系统配置

---

# 7. Phase 4：实时通信

当前 PyQt6 如果使用：

```text
Worker
 ↓
multiprocessing Queue
 ↓
QTimer
 ↓
UI
```

新架构逐步改成：

```text
Python Core
 ↓
Event / WebSocket
 ↓
React
```

例如：

```json
{
  "type": "candidate_processed",
  "task_id": 12,
  "processed": 137,
  "total": 416,
  "downloaded": 32,
  "rejected": 105
}
```

迁移期间不要立即删除 Queue：

```text
Core
 ├── Legacy Event → PyQt6
 └── New Event → WebSocket
```

React 稳定后再删除 PyQt6 专用通信代码。

---

# 8. Phase 5：新旧 UI 并行

最终：

```text
                  Python Core
                       │
              ┌────────┴────────┐
              │                 │
            PyQt6             FastAPI
              │                 │
           Legacy UI          React
              │                 │
              ↓                 ↓
           旧版本              新版本
```

要求：

- PyQt6 可以独立启动
- React + FastAPI 可以独立启动
- 两者不能同时控制同一个自动化任务
- 两者不能同时控制同一个 Chrome Session

---

# 9. 应用实例锁

避免：

```text
PyQt6
+
React/Tauri
```

同时执行自动化。

可以使用：

```text
runtime.lock
```

检测到已有实例时：

```text
ResumeAgent 已经运行

[打开现有实例]
[退出]
```

生产环境建议同一时间只允许一个 ResumeAgent 实例执行自动化任务。

---

# 10. Phase 6：功能对齐

React 版本必须逐项对齐 PyQt6：

| 功能 | PyQt6 | React | 状态 |
|---|---:|---:|---|
| Chrome 检测 | ✅ | ⬜ | |
| Chrome 启动 | ✅ | ⬜ | |
| 岗位刷新 | ✅ | ⬜ | |
| 岗位选择 | ✅ | ⬜ | |
| 候选人获取 | ✅ | ⬜ | |
| 自动滚动 | ✅ | ⬜ | |
| 自动翻页 | ✅ | ⬜ | |
| 简历打开 | ✅ | ⬜ | |
| LLM 判断 | ✅ | ⬜ | |
| AI 判断理由 | ✅ | ⬜ | |
| 简历下载 | ✅ | ⬜ | |
| Excel | ✅ | ⬜ | |
| SQLite | ✅ | ⬜ | |
| 暂停 | ✅ | ⬜ | |
| 恢复 | ✅ | ⬜ | |
| 中断 | ✅ | ⬜ | |
| 任务恢复 | ✅ | ⬜ | |
| Chrome 异常 | ✅ | ⬜ | |
| 登录异常 | ✅ | ⬜ | |

**所有核心功能通过后，才能进入 Tauri。**

---

# 11. Phase 7：Tauri

React + FastAPI 版本稳定后再接入 Tauri。

```text
Tauri v2
+
React
+
FastAPI
+
PyInstaller
```

目标：

```text
┌─────────────────────────────┐
│           Tauri             │
│      React + shadcn/ui      │
└──────────────┬──────────────┘
               │
               ↓
        Python sidecar
               │
        ┌──────┼───────┐
        ↓      ↓       ↓
     FastAPI  LLM   SQLite
        │
        ↓
    Playwright
        │
        ↓
      Chrome
```

Tauri 只负责：

- 创建窗口
- React UI
- 启动 Python
- 传递端口/token
- 检测 Python 启动状态
- Python 生命周期管理
- 崩溃处理
- 系统托盘
- 应用退出
- 打包

不要把业务逻辑迁移到 Rust。

---

# 12. Phase 8：Python Sidecar

生产环境：

```text
Python
 ↓
PyInstaller
 ↓
backend.exe
```

Tauri：

```text
ResumeAgent.exe
       │
       └── backend.exe
```

开发环境仍然：

```text
React dev server
+
FastAPI
```

不要为了 Tauri 提前改变开发流程。

---

# 13. FastAPI 本地安全

生产版本必须：

- 只绑定 `127.0.0.1`
- 启动时使用随机可用端口
- 生成随机 session token
- API 请求必须携带 token
- 禁止无 token 访问任务/下载接口
- Tauri 负责把 token 安全传给 React
- 禁止绑定 `0.0.0.0`

目标：

```text
React
 ↓
127.0.0.1:随机端口
 + Authorization Token
 ↓
FastAPI
```

---

# 14. Chromium 独立管理

不要把 Chromium 与主 EXE 强绑定。

推荐：

```text
ResumeAgent/
│
├── ResumeAgent.exe
├── runtime/
│   └── backend.exe
├── browsers/
│   └── chromium/
├── data/
│   └── resume_agent.db
├── chrome-profile/
└── logs/
```

原则：

- UI 更新不重新下载 Chromium
- Python 更新不影响 Chromium
- Chromium 独立处理
- SQLite 用户数据独立保存
- 日志独立保存

如果当前项目已经有浏览器路径管理机制，优先复用。

---

# 15. 用户数据目录

用户数据不要放在 EXE 内。

建议：

```text
%LOCALAPPDATA%\ResumeAgent│
├── data│   └── resume_agent.db
├── browsers├── chrome-profile├── downloads└── logs```

升级 EXE 不得覆盖用户数据。

---

# 16. 回滚策略

## React 阶段失败

继续使用：

```text
PyQt6 EXE
```

## FastAPI 阶段失败

继续：

```text
PyQt6
 ↓
LegacyAdapter
 ↓
Python Core
```

## Tauri 阶段失败

可以继续使用：

```text
React + FastAPI
```

或者：

```text
PyQt6 EXE
```

## 新架构整体失败

恢复：

```bash
git checkout pyqt6-stable
```

---

# 17. Git 分支策略

建议：

```text
main
 │
 ├── stable-pyqt6
 │
 └── refactor/react-architecture
```

重构期间：

- `main` 保持稳定
- 新架构在 `refactor/react-architecture`
- 每个 Phase 完成后提交
- 每个关键节点创建 tag
- 禁止一次性大提交

---

# 18. 版本规划

```text
v0.1.x
PyQt6 稳定版

v0.2.x
Python Core 解耦

v0.3.x
FastAPI

v0.4.x
React Beta

v0.5.x
React 完整版

v0.6.x
Tauri Beta

v1.0.0
React + FastAPI + Tauri 正式版
```

PyQt6 在 v0.x 阶段持续保留。

只有 v1.0.0 新架构经过完整验证后，才考虑退役 PyQt6。

---

# 19. Agent 硬性执行规则

1. 禁止删除当前 PyQt6 入口。
2. 禁止覆盖当前稳定 EXE。
3. 禁止第一阶段引入 Tauri。
4. 禁止重写现有 Playwright 自动化核心。
5. 禁止重写现有 LLM 简历判断逻辑。
6. 禁止重写现有简历下载逻辑。
7. 禁止重写现有 Excel 逻辑。
8. 禁止无必要修改现有 SQLite 数据结构。
9. Core 层禁止依赖 PyQt6。
10. FastAPI 只能调用 Core，不直接实现 Playwright 业务。
11. React 不允许直接操作 Playwright。
12. 不为了“架构漂亮”重写已经稳定的代码。
13. 发现现有代码与 UI 高度耦合时，优先使用 Adapter。
14. 每完成一个 Phase 都必须确保 PyQt6 可以正常启动。
15. 每完成一个 Phase 必须可以 Git 回滚。
16. Tauri 必须最后实施。
17. 新旧 UI 不允许同时控制同一个自动化任务。
18. 用户数据库不能放在 EXE 内部。
19. FastAPI 不允许绑定 `0.0.0.0`。
20. 生产版 FastAPI 必须使用随机端口 + token。
21. Chromium 与主 EXE 解耦。
22. 任何会影响现有自动化稳定性的改动，都必须先保留旧实现再尝试。
23. 每个阶段完成后必须输出：修改内容、启动方式、测试结果、已知问题、回滚方式。
24. 如果发现当前代码结构与本方案冲突，不要擅自大改，先选择最小侵入式 Adapter 方案。
25. 不允许因为重构而改变现有业务规则、AI 判断规则、下载规则和任务恢复规则。

---

# 20. 每个 Phase 的完成标准

## Phase 0

```text
[ ] PyQt6 稳定版本已打 Tag
[ ] 当前 EXE 已备份
[ ] 当前核心功能全部验证
```

## Phase 1

```text
[ ] Python Core 独立
[ ] Core 不依赖 PyQt6
[ ] PyQt6 仍可运行
```

## Phase 2

```text
[ ] FastAPI 启动
[ ] API 可以调用 Core
[ ] PyQt6 仍可运行
```

## Phase 3

```text
[ ] React 启动
[ ] 岗位页面
[ ] 任务页面
[ ] 候选人页面
[ ] 设置页面
```

## Phase 4

```text
[ ] WebSocket
[ ] 实时任务进度
[ ] 实时日志
```

## Phase 5

```text
[ ] React 可以创建任务
[ ] React 可以执行任务
[ ] React 可以暂停/恢复
[ ] React 可以查看 AI 结果
[ ] React 可以查看下载结果
```

## Phase 6

```text
[ ] 新旧功能矩阵全部通过
[ ] React 版本稳定运行
[ ] PyQt6 仍然可用
```

## Phase 7

```text
[ ] Tauri 启动 React
[ ] Tauri 启动 Python
[ ] Python 生命周期正常
[ ] Python 崩溃处理正常
[ ] 本地 API 安全
[ ] EXE 可以正常运行
```

## Phase 8

```text
[ ] 安装包生成
[ ] 用户数据不丢失
[ ] Chromium 独立管理
[ ] 升级不覆盖数据
[ ] PyQt6 仍作为回滚版本保留
```

---

# 21. 最终架构

```text
                         ResumeAgent
                              │
              ┌───────────────┴────────────────┐
              │                                │
       Legacy Stable                     New Architecture
              │                                │
            PyQt6                            Tauri
              │                                │
              │                         React + shadcn
              │                                │
              │                            FastAPI
              │                                │
              └──────────────┬─────────────────┘
                             │
                        Python Core
                             │
              ┌──────────────┼──────────────┐
              ↓              ↓              ↓
        BrowserManager   TaskManager     LLMService
              │              │              │
              └──────────────┼──────────────┘
                             ↓
                         Playwright
                             ↓
                           Chrome
                             │
              ┌──────────────┼──────────────┐
              ↓              ↓              ↓
           SQLite          下载文件         Excel
```

---

# 22. 最终执行原则

这次重构不是“重写 ResumeAgent”。

而是：

> **保留已经验证成功的 Python 自动化能力，只替换 UI 层，并逐步增加 API 与桌面壳。**

最终：

```text
旧：
PyQt6 → Python Core

新：
React → FastAPI → Python Core
                     ↓
                 Playwright
                     ↓
                   Chrome
```

最后：

```text
React
 ↓
Tauri
 ↓
Python sidecar
 ↓
Playwright
```

等新架构完全稳定后，才退役 PyQt6。

**任何阶段如果新架构失败，都必须能够退回当前 PyQt6 稳定版本继续工作。**
