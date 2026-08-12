# HR简历自动下载助手

## 项目简介

基于 Python + Playwright 的浏览器自动化工具，用于从前程无忧（51job）网页版自动下载候选人简历，支持 AI 简历筛选。

## 当前开发进度

### 已完成功能

| 功能 | 状态 | 说明 |
|------|------|------|
| Chrome CDP 连接 | ✅ 完成 | 通过 Remote Debugging 接接管已登录的浏览器 |
| 候选人列表解析 | ✅ 完成 | 解析 `.item.virtual_list` 元素获取候选人信息 |
| 虚拟滚动处理 | ✅ 完成 | 使用鼠标滚轮触发虚拟滚动加载 |
| 详情页打开 | ✅ 完成 | 点击候选人进入新标签页详情 |
| 附件简历下载 | ✅ 完成 | 点击"附件个人信息" → 点击"下载"按钮 |
| 结果统计 | ✅ 完成 | 显示成功/失败数量和详细信息 |
| 分页处理 | ✅ 完成 | 下载完当前页后自动检测分页控件并翻页继续 |
| 结果导出 Excel | ✅ 完成 | 输出下载结果到 `output/result_时间戳.xlsx` |
| 配置化 | ✅ 完成 | `config.py` 支持自定义下载路径、最大数量等 |
| 职位切换 | ✅ 完成 | 自动检测页面职位 tab，支持切换不同岗位下载 |
| AI 简历筛选 | ✅ 完成 | 接入 MiMo-V2.5-Pro，下载前 AI 评估简历是否匹配 |
| 岗位匹配描述 | ✅ 完成 | 支持多岗位独立配置匹配描述，持久化存储 |
| 下载可中断 | ✅ 完成 | Ctrl+C 中断下载，已处理数据保留并导出 Excel |
| 滚动调试工具 | ✅ 完成 | 菜单 `9` 测试分页控件，菜单 `0` 测试多种滚动方案 |
| PyQt6 GUI 界面 | ✅ 完成 | 候选人表格、控制面板、操作日志、学校名单过滤 |
| SQLite 持久化 | ✅ 完成 | 任务/候选人/日志入库，候选人状态实时写入，支持任务恢复 |
| 学校名单可配置 | ✅ 完成 | `school_filter_config.json` 统一配置，兼容旧路径文件 |
| 浏览器状态管理 | ✅ 完成 | BrowserManager 状态机/健康检查/断线自动重连（3次） |
| 页面/登录检测 | ✅ 完成 | PageDetector 识别登录页/候选人列表/岗位，登录失效自动暂停 |
| 候选人历史记录 | ✅ 完成 | 刷新时关联历史状态，已下载/AI淘汰自动过滤，失败显示记录 |
| 附件检测增强 | ✅ 完成 | 12秒轮询 + 多选择器 + 详情页同页跳转兼容 |
| FluentUI 重构 | ✅ 完成 | PyQt6-Fluent-Widgets，Fluent 组件/徽标/明暗主题 |
| AI 配置增强 | ✅ 完成 | 测试连接、AI 生成专业描述、下载时选择匹配描述 |
| Excel AI 理由 | ✅ 完成 | 导出表含 AI 评估结果与理由 |

## 技术架构

### 技术栈

- Python 3.11+
- PyQt6 (GUI)
- PyQt6-Fluent-Widgets (FluentUI 组件库)
- Playwright (浏览器自动化)
- pandas + openpyxl (Excel 输出)
- openai SDK (MiMo API 调用)
- PyInstaller (打包为 exe)

### 项目结构

```
resume-agent/
├── main_gui.py          # GUI 入口（推荐）
├── main.py              # CLI 入口
├── config.py            # 配置文件（含 AI 配置持久化）
├── browser_worker.py    # 浏览器操作子进程
├── download_worker.py   # 下载操作子进程
├── runtime_lock.py      # 实例锁（防止多实例同时自动化）
├── browser/
│   ├── browser_manager.py  # Chrome 生命周期管理（状态机/重连）
│   ├── page_detector.py    # 页面/登录状态检测
│   └── chrome.py           # 兼容层
├── crawler/
│   └── candidate.py     # 候选人解析
├── task/                # TaskManager（任务生命周期/候选人状态机）
├── db/                  # SQLite（jobs/tasks/task_candidates/task_logs）
├── gui/                 # PyQt6 FluentUI 界面
├── build_gui.spec       # PyInstaller 打包配置（GUI）
├── requirements.txt     # 依赖列表
└── README.md            # 项目说明
```

## 核心实现

### 虚拟滚动处理

前程无忧页面使用虚拟滚动，DOM中只有可见区域的元素有实际内容。解决方案：

```python
def collect_all_candidates_with_scroll(page):
    # 移动鼠标到页面中间
    page.mouse.move(600, 400)
    # 使用鼠标滚轮滚动
    page.mouse.wheel(0, 600)
    # 连续滚动直到无新增候选人（3轮无新增停止）
```

### 分页处理

前程无忧页面使用自定义分页组件 `.eh-pagination`：

```python
def has_next_page(page):
    # 检测 .eh-pagination__next.btn-next 是否 disabled

def go_to_next_page(page):
    # 点击下一页，等待页码变化或候选人列表刷新
```

### AI 简历筛选

接入小米 MiMo-V2.5-Pro 模型，下载前自动评估简历：

```python
def evaluate_resume(resume_text, match_description, api_key):
    # 使用 OpenAI SDK 调用 MiMo API
    # 从 attachment 预览页读取简历文本
    # AI 返回 {"match": true/false, "reason": "..."}
    # 匹配才下载，不匹配跳过
```

### 简历下载流程

```
1. 选择职位 tab → 切换到目标岗位
2. 选择 AI 匹配描述（多选一）
3. 滚动收集当前页所有候选人
4. 逐个处理：
   a. 点击候选人 → 新标签页打开详情
   b. 等待"附件个人信息"按钮出现
   c. 点击附件 → 等待下载按钮出现
   d. AI 评估简历（如启用）
   e. 匹配 → 下载；不匹配 → 跳过
   f. 保存为 51job-姓名_岗位.pdf
5. 检测分页 → 翻到下一页 → 重复
6. 导出 Excel 结果汇总
```

## 使用方法

### 开发环境

```bash
pip install -r requirements.txt
playwright install chromium
python main_gui.py
```

### 打包为 exe

```bash
pyinstaller build_gui.spec
```

### 使用步骤

1. 运行程序，程序会自动启动 Chrome 调试模式（独立用户数据目录
   `%LOCALAPPDATA%\ResumeAgent\chrome-profile`，保存登录会话）
   - 如需手动启动 Chrome 调试模式：
   ```
   chrome.exe --remote-debugging-port=9222 --user-data-dir=%LOCALAPPDATA%\ResumeAgent\chrome-profile
   ```

2. 在打开的 Chrome 中登录前程无忧，进入候选人列表页面

3. GUI 操作：
   - 顶部「刷新」：获取岗位/候选人（候选人默认读数据库，刷新才抓取最新）
   - 顶部「AI配置」：API Key、测试连接、岗位匹配描述、AI 生成专业描述
   - 顶部「暗色/亮色」：主题切换；「关于」：版本信息
   - 下载控制区：选择匹配描述（自动匹配/指定岗位/不使用AI）、开始/暂停/继续/中断下载
   - 快捷键：F5 刷新、Ctrl+Enter 开始下载

## 更新日志

### 2026-08-12

- FluentUI 重构：接入 PyQt6-Fluent-Widgets，按钮/下拉框/表格/徽标 Fluent 化，
  头部操作区替代菜单栏，明暗主题
- 修复 AI 评估静默失败（MiMo 推理模型 max_tokens 不足导致全部默认通过），
  加大额度 + 失败重试，评估理由落库并导出 Excel
- AI 配置增强：测试连接（loading 交互）、AI 生成专业描述（直接新增一条）、
  下载时选择岗位匹配描述
- 浏览器状态管理：BrowserManager 状态机/健康检查/断线重连，登录失效自动暂停
- 候选人历史记录：刷新自动过滤已下载/AI淘汰，失败保留并显示原因
- 附件检测增强：12 秒轮询、多选择器、详情页同页跳转兼容、失败诊断
- 实例锁 runtime.lock：防止多实例同时执行自动化
- 双轨架构（React+FastAPI）已存档到分支 `refactor/react-architecture`

### 2026-08-11

- 新增 PyQt6 GUI 界面：候选人表格、职位切换、学校名单过滤、操作日志
- 新增 SQLite 持久化：任务/候选人/日志入库，候选人 AI 结果与下载状态实时写入
- 新增任务恢复：中断后可恢复未完成候选人继续下载（自动还原职位、下载目录、AI 配置）
- Chrome 调试模式自动启动：端口未开时自动拉起 Chrome（`C:\chrome-agent`，保留登录会话）
- 启动稳定性优化：端口预检、结果回调异常防护、刷新看门狗
- 学校名单路径改为可配置（`school_filter_config.json`，兼容旧 `school_list_path.txt`）
- 修复 `create_task` 数据库锁问题、GUI 模式 AI 匹配描述未按职位传入的问题
- 使用 PyInstaller 打包 GUI 版 exe（`dist/AI简历批量初筛与下载助手.exe`）

### 2026-08-10

- 新增分页处理：自动检测 `.eh-pagination` 控件并翻页
- 新增结果导出 Excel：`output/result_时间戳.xlsx`
- 新增 AI 简历筛选：接入 MiMo-V2.5-Pro，下载前评估简历匹配度
- 新增职位切换：自动检测页面职位 tab，支持多岗位独立下载
- 新增岗位匹配描述管理：每个岗位独立配置筛选要求
- 新增下载可中断：Ctrl+C 中断后保留已处理数据
- 优化虚拟滚动：从 PageDown 改为鼠标滚轮方案
- 优化附件/下载按钮查找：使用轮询等待替代固定 sleep
- 简历命名规则：`51job-候选人姓名_岗位.pdf`

### 2026-08-07

- 完成基础功能：Chrome连接、候选人解析、简历下载
- 解决虚拟滚动问题：使用 Page Down 键盘事件触发加载
- 实现单页50个候选人的自动下载
- 打包为 exe 可执行文件
