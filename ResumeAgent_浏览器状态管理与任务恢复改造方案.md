# ResumeAgent 浏览器状态管理与任务恢复改造方案

## 1. 改造目标

当前项目已经实现：

- 自动检测 Chrome 调试模式
- Chrome 不存在时自动启动
- Playwright 连接 Chrome
- 获取前程无忧岗位
- 选择岗位并获取候选人
- `.main_container` 候选人列表滚动
- 自动翻页
- 打开候选人简历弹窗
- LLM 判断简历是否符合岗位要求
- 符合条件自动下载附件
- 不符合条件记录 AI 判断理由
- 最终生成 Excel
- 使用 SQLite 保存任务状态： 需确认是否可用

本次改造目标：

> 增加独立的 BrowserManager 浏览器生命周期管理，并与 TaskManager 任务状态结合，实现浏览器异常恢复、登录状态检测、页面状态检测、任务恢复。

### 非目标

不要重写现有核心业务流程：

- 不重写候选人滚动逻辑
- 不重写分页逻辑
- 不重写 LLM 判断逻辑
- 不重写简历下载逻辑
- 不重写 Excel 生成逻辑

只在现有流程关键节点增加状态管理。

---

## 2. 新增核心模块

建议增加：

```text
src/
├── browser/
│   ├── browser_manager.py
│   ├── browser_config.py
│   ├── browser_state.py
│   └── page_detector.py
│
├── task/
│   ├── task_manager.py
│   ├── task_state.py
│   └── task_recovery.py
│
├── database/
│   ├── database.py
│   ├── models/
│   │   ├── job.py
│   │   ├── task.py
│   │   ├── task_candidate.py
│   │   └── task_log.py
│   └── migrations/
└── ...
```

如果当前项目已有类似模块，应整合到现有架构，不要重复创建。

---

## 3. BrowserManager

`BrowserManager` 统一负责：

- Chrome 启动
- Chrome 进程检测
- Chrome 调试端口检测
- Playwright 连接
- Browser Context / Page 获取
- 浏览器健康检查
- 浏览器断线重连
- 登录状态检测
- 当前页面检测
- 当前岗位检测
- 当前候选人页面检测

现有业务代码不要到处出现：

```python
connect_over_cdp(...)
```

或：

```python
subprocess.Popen(...)
```

这些逻辑统一收口到 `BrowserManager`。

---

## 4. Chrome 独立 Profile

不要使用用户日常 Chrome Profile。

使用：

```text
%LOCALAPPDATA%\ResumeAgent\chrome-profile\
```

例如：

```text
C:\Users\xxx\AppData\Local\ResumeAgent\chrome-profile\
```

Chrome 启动参数：

```text
--remote-debugging-port=9222
--user-data-dir=<ResumeAgent chrome-profile>
```

目的：

- 保存前程无忧登录 Cookie
- 保存 LocalStorage / Session
- 保存网站设置
- 避免接管用户日常 Chrome

用户第一次登录后，后续启动助手应尽量保持登录状态。

---

## 5. Chrome 启动流程

```text
启动 ResumeAgent
        ↓
BrowserManager.initialize()
        ↓
检测 Chrome 调试端口
        ↓
┌───────────────────┐
│                   │
存在                不存在
│                   │
↓                   ↓
连接 Chrome       启动 Chrome
                    ↓
                等待调试端口
                    ↓
                连接 Chrome
        ↓
获取 Playwright Browser
        ↓
获取 Page
        ↓
执行浏览器健康检查
```

启动失败必须向 UI 提供明确错误。

---

## 6. Browser 状态

定义：

```text
DISCONNECTED
STARTING
CONNECTING
CONNECTED
READY
RECONNECTING
ERROR
```

正常：

```text
DISCONNECTED
      ↓
STARTING
      ↓
CONNECTING
      ↓
CONNECTED
      ↓
READY
```

异常：

```text
READY
 ↓
检测 Chrome 断开
 ↓
RECONNECTING
 ↓
CONNECTED
 ↓
READY
```

---

## 7. 浏览器健康检查

增加：

```python
browser_manager.health_check()
```

至少检查：

1. Chrome 进程是否存在
2. 调试端口是否可用
3. Playwright 是否连接
4. Browser 是否可用
5. Page 是否可用

任务运行期间可每 3～5 秒检查一次，也可以在关键操作前检查。

---

## 8. 前程无忧页面状态检测

增加：

```python
page_detector.detect()
```

返回：

```text
UNKNOWN
LOGIN_PAGE
HOME_PAGE
JOB_LIST_PAGE
CANDIDATE_LIST_PAGE
RESUME_DETAIL
OTHER_PAGE
```

判断依据可以组合：

- URL
- 页面标题
- DOM 特征
- 前程无忧页面特征元素

不要只依赖 URL。

---

## 9. 登录状态检测

增加：

```python
page_detector.is_logged_in()
```

状态：

```text
已登录
登录失效
未知
```

发现登录失效：

```text
任务自动暂停
 ↓
提示“前程无忧登录状态已失效，请重新登录”
 ↓
用户在 Chrome 中完成登录
 ↓
点击“继续任务”
 ↓
重新检测登录状态
 ↓
成功后恢复任务
```

登录失效时禁止继续候选人自动化操作。

---

## 10. 页面 / 岗位匹配检测

任务中保存：

```text
job_id
job_external_id
job_name
candidate_list_url
```

恢复任务前：

```text
当前 Chrome
      ↓
当前页面
      ↓
是否前程无忧？
      ↓
是否已登录？
      ↓
是否候选人列表？
      ↓
当前岗位是否匹配？
```

任何关键条件不满足时，不要直接执行任务，应提示用户。

---

## 11. TaskManager

新增 `TaskManager`，负责：

- 创建任务
- 查询任务
- 更新任务状态
- 暂停任务
- 恢复任务
- 完成任务
- 取消任务
- 查询未完成任务
- 查询候选人状态
- 更新候选人状态
- 任务统计

---

## 12. SQLite

使用 SQLite 作为任务状态数据库。

数据库位置：

```text
%LOCALAPPDATA%\ResumeAgent\data\resume_agent.db
```

不要放到 PyInstaller 的：

```text
_MEIxxxx
```

临时目录。

Excel 继续作为最终 HR 结果文件，不替代 SQLite。

---

## 13. jobs 表

```sql
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_job_id TEXT NOT NULL UNIQUE,
    job_name TEXT NOT NULL,
    company_name TEXT,
    job_url TEXT,
    status TEXT DEFAULT 'active',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

刷新岗位时：

```text
前程无忧岗位
      ↓
提取岗位信息
      ↓
UPSERT jobs
```

不要重复插入相同岗位。

---

## 14. tasks 表

```sql
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    job_id INTEGER NOT NULL,

    status TEXT NOT NULL DEFAULT 'pending',

    current_page INTEGER DEFAULT 1,
    total_pages INTEGER DEFAULT 0,

    current_candidate_id TEXT,

    total_candidates INTEGER DEFAULT 0,
    processed_count INTEGER DEFAULT 0,
    downloaded_count INTEGER DEFAULT 0,
    rejected_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,

    download_dir TEXT,
    excel_path TEXT,

    ai_enabled INTEGER DEFAULT 0,
    ai_config_snapshot TEXT,

    candidate_list_url TEXT,

    started_at DATETIME,
    updated_at DATETIME,
    completed_at DATETIME,

    FOREIGN KEY (job_id) REFERENCES jobs(id)
);
```

Task 状态：

```text
pending
running
paused
completed
failed
cancelled
```

---

## 15. task_candidates 表

```sql
CREATE TABLE task_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    task_id INTEGER NOT NULL,

    candidate_external_id TEXT NOT NULL,

    name TEXT,
    school TEXT,
    major TEXT,
    education TEXT,

    page_no INTEGER,
    sort_index INTEGER,

    status TEXT NOT NULL DEFAULT 'pending',

    ai_match INTEGER,
    ai_score REAL,
    ai_reason TEXT,

    download_status TEXT,
    download_path TEXT,

    error_message TEXT,

    processed_at DATETIME,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (task_id) REFERENCES tasks(id),

    UNIQUE(task_id, candidate_external_id)
);
```

---

## 16. 候选人唯一标识

必须优先使用前程无忧自己的候选人 ID。

不要使用：

```text
page_no + sort_index
```

作为唯一标识。

使用：

```text
candidate_external_id
```

并建立：

```sql
UNIQUE(task_id, candidate_external_id)
```

原因：候选人列表可能发生变化，页码和列表位置不是稳定 ID。

---

## 17. task_logs 表

```sql
CREATE TABLE task_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    task_id INTEGER NOT NULL,

    candidate_id INTEGER,

    event_type TEXT NOT NULL,

    message TEXT,

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (task_id) REFERENCES tasks(id)
);
```

建议事件：

```text
task_started
task_paused
task_resumed
task_completed
page_changed

candidate_found
candidate_processing
resume_opened

ai_analyzing
ai_matched
ai_rejected

download_started
download_success
download_failed

browser_disconnected
browser_reconnected

login_expired
login_restored
```

现有 UI 操作日志继续保留，并逐步接入 `task_logs`。

---

## 18. 创建任务

只有用户点击：

```text
开始下载
```

时才创建 Task。

流程：

```text
选择岗位
    ↓
获取候选人
    ↓
点击开始下载
    ↓
创建 Task
    ↓
保存：
    job_id
    candidate_list_url
    download_dir
    AI配置快照
    current_page = 1
    status = running
    ↓
开始处理
```

选择岗位本身不要创建 Task。

---

## 19. AI 配置快照

Task 创建时保存当前 AI 配置，例如：

```json
{
  "job_name": "售前咨询工程师",
  "match_description": "3年以上工作经验，本科以上学历，有售前经验",
  "model": "当前模型"
}
```

保存到：

```text
tasks.ai_config_snapshot
```

当前 Task 始终使用这个快照。

即使用户修改全局 AI 配置，也不能影响已经运行的 Task。

---

## 20. 接入现有候选人处理流程

不要重写当前流程。

原流程：

```text
获取候选人
 ↓
打开简历
 ↓
LLM判断
 ↓
符合 → 下载
不符合 → 记录
 ↓
下一个候选人
```

增加持久化：

```text
获取候选人
 ↓
UPSERT task_candidates
 ↓
status = processing
 ↓
打开简历
 ↓
LLM判断
 ↓
保存 ai_match
保存 ai_score
保存 ai_reason
 ↓
符合
 ↓
status = downloading
 ↓
下载
 ↓
status = downloaded
 ↓
保存 download_path
```

不符合：

```text
status = ai_rejected
```

失败：

```text
status = failed
error_message = ...
```

---

## 21. 每个候选人必须立即保存

禁止：

```text
处理100个人
 ↓
最后一次性保存数据库
```

必须：

```text
候选人1完成 → UPDATE
候选人2完成 → UPDATE
候选人3完成 → UPDATE
```

这样即使 Python 崩溃、Chrome 崩溃、Windows 重启或软件关闭，最多只影响当前正在处理的候选人。

---

## 22. 软件启动时检测未完成任务

启动：

```text
读取 SQLite
 ↓
查询：
status IN ('running', 'paused')
```

如果没有未完成任务：

```text
正常进入首页
```

如果存在：

```text
检测到未完成任务
```

UI 显示：

```text
岗位：售前咨询工程师

进度：137 / 416
当前页：第3页
已下载：32
AI淘汰：105

浏览器：已连接
登录状态：正常

[继续任务]
[放弃任务]
```

---

## 23. 恢复任务

用户点击：

```text
继续任务
```

必须：

```text
TaskManager
      ↓
BrowserManager
      ↓
检查 Chrome
      ↓
检查 Playwright
      ↓
检查前程无忧
      ↓
检查登录状态
      ↓
检查岗位
      ↓
检查候选人列表
      ↓
全部正常
      ↓
恢复任务
```

任何条件不满足时不要自动开始任务，向用户显示具体原因。

---

## 24. 浏览器断开自动恢复

任务运行：

```text
Task running
 ↓
Chrome被关闭
 ↓
BrowserManager检测断开
 ↓
Task保持 running
 ↓
暂停当前自动化动作
 ↓
尝试重新启动Chrome
 ↓
重新连接Playwright
 ↓
检查登录状态
 ↓
恢复页面
 ↓
继续任务
```

自动重连最多 3 次：

```text
第1次：等待3秒
第2次：等待5秒
第3次：等待10秒
```

全部失败：

```text
task.status = paused
```

并提示用户处理。

---

## 25. 不要盲目恢复当前候选人

例如 Chrome 在处理张三时断开。

恢复后根据 `task_candidates` 状态判断：

```text
张三 = processing
→ 重新处理

张三 = downloaded
→ 直接跳过

张三 = ai_rejected
→ 直接跳过
```

不要根据内存中的当前索引判断。

---

## 26. 当前页面恢复

恢复时：

```text
task.current_page = 3
```

先定位第 3 页候选人列表。

然后获取当前页面候选人，根据：

```text
candidate_external_id
```

判断：

```text
已经处理 → 跳过
pending → 处理
processing → 重新处理
failed → 根据重试策略处理
```

不要单纯依赖：

```text
第3页第27个
```

---

## 27. 任务暂停

增加：

```text
暂停
```

点击后：

```text
task.status = paused
```

如果当前候选人正在 LLM 请求或下载：

不要粗暴终止。

当前候选人完成后再暂停。

---

## 28. UI 增加浏览器状态

现有状态区域增加：

```text
浏览器：已连接
```

状态：

```text
浏览器：未连接
浏览器：连接中
浏览器：已连接
浏览器：重连中
浏览器：异常
```

---

## 29. UI 增加任务状态

下载区域显示：

```text
任务状态：空闲
```

运行：

```text
任务状态：运行中
第 3 / 8 页
137 / 416
```

暂停：

```text
任务状态：已暂停
```

完成：

```text
任务状态：已完成
```

---

## 30. Chrome 关闭保护

如果当前任务正在运行，而用户关闭 Chrome：

```text
检测到浏览器关闭
 ↓
暂停/挂起当前自动化操作
 ↓
BrowserManager尝试恢复
```

如果用户从软件主动关闭浏览器：

提示：

```text
当前任务正在运行。

关闭浏览器将暂停当前任务。

[取消] [关闭并暂停]
```

---

## 31. 严格区分 Browser 状态和 Task 状态

不要混淆：

```text
BrowserManager
    ↓
浏览器现在能不能操作

TaskManager
    ↓
任务现在做到哪里
```

例如：

```text
Browser = DISCONNECTED
Task = RUNNING
```

这是允许存在的。

BrowserManager 负责恢复浏览器。

TaskManager 负责保存任务进度。

---

## 32. 最终架构

```text
                    ResumeAgent
                        │
          ┌─────────────┴─────────────┐
          │                           │
    BrowserManager               TaskManager
          │                           │
          │                           ↓
          │                       SQLite
          │                    ┌──────┼──────┐
          │                    ↓      ↓      ↓
          │                   jobs   tasks  candidates
          │
          ↓
      Playwright
          ↓
      Chrome
          ↓
     前程无忧
          ↓
      候选人简历
          ↓
         LLM
          ↓
     下载 / 不下载
          ↓
        Excel
```

---

## 33. 开发顺序

Agent 必须按以下顺序实施，不要一次性重构所有代码。

### 第一阶段

实现：

```text
SQLite
jobs
tasks
task_candidates
task_logs
```

并确保现有功能正常。

### 第二阶段

接入：

```text
TaskManager
```

保存：

```text
任务创建
候选人处理
AI结果
下载结果
失败状态
```

### 第三阶段

实现：

```text
BrowserManager
```

统一管理：

```text
Chrome启动
Chrome连接
Playwright
健康检查
重连
```

### 第四阶段

实现：

```text
页面检测
登录检测
岗位检测
候选人页面检测
```

### 第五阶段

实现：

```text
启动恢复
任务恢复
浏览器校验
```

### 第六阶段

实现：

```text
暂停
继续
浏览器异常自动恢复
登录失效自动暂停
失败重试
```

---

## 34. 现有功能兼容要求

改造过程中必须保证：

```text
✓ 刷新岗位正常
✓ 选择岗位正常
✓ 获取候选人正常
✓ 候选人滚动正常
✓ 自动翻页正常
✓ 打开简历正常
✓ LLM判断正常
✓ 符合条件下载正常
✓ 不符合条件记录理由正常
✓ Excel正常生成
```

任何现有功能被破坏，都应该优先修复，而不是继续增加新功能。

---

## 35. 最终验收标准

### 场景1：正常启动

```text
启动软件
→ 自动启动 Chrome
→ 自动连接
→ 前程无忧正常
```

### 场景2：Chrome 已经启动

```text
启动软件
→ 检测到 Chrome
→ 直接连接
```

### 场景3：Chrome 被关闭

```text
任务运行
→ Chrome关闭
→ 自动检测
→ 自动重启
→ 自动连接
→ 继续任务
```

### 场景4：登录过期

```text
任务运行
→ 前程无忧登录失效
→ 自动暂停
→ 提示重新登录
→ 登录完成
→ 点击继续
→ 恢复任务
```

### 场景5：软件关闭

```text
处理到 137/416
→ 关闭软件
→ SQLite保存状态
```

重新打开：

```text
检测到未完成任务
→ 连接 Chrome
→ 检查岗位
→ 检查登录
→ 点击继续
→ 从未完成候选人继续
```

### 场景6：候选人已经处理

```text
SQLite：
candidate 123 = downloaded

网页再次出现：
candidate 123

→ 自动跳过
```

### 场景7：Chrome 与任务岗位不一致

```text
任务：
售前咨询工程师

当前Chrome：
Java开发工程师

→ 禁止继续
→ 提示用户切换岗位
```

---

## 最重要的设计原则

> 这次改造的核心不是增加更多“AI Agent”，而是建立 BrowserManager + TaskManager 两个稳定的基础设施。

职责必须保持清晰：

- **LLM**：只负责判断简历是否符合岗位要求
- **Playwright**：负责确定性的浏览器操作
- **SQLite**：负责持久化任务状态
- **TaskManager**：负责任务生命周期和断点恢复
- **BrowserManager**：负责 Chrome 生命周期、连接、健康检查和重连
- **PageDetector**：负责识别当前网站、页面、登录状态和岗位状态

不要让 LLM 参与 Chrome 生命周期控制。

最终目标是把当前“自动化脚本”升级为一个具备：

- 浏览器自动管理
- 任务持久化
- 断点恢复
- 登录失效暂停
- Chrome 异常恢复
- 候选人去重
- AI 筛选
- 自动下载
- Excel 输出

能力的稳定桌面 RPA 工具。
