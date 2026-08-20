# GUI改造进度说明

## 2026-08-14 浏览器自动化架构重构（Phase 1 ~ 4B，分支 codex/browser-actions-refactor）

### 重构目标与成果
- 把 51job 浏览器自动化从"巨型页面 + 硬编码"重构为分层架构
- 完整架构见 `docs/ARCHITECTURE.md`

### 分层落地
- **Controller 层**：BrowserController / TaskController / DownloadController（页面只做 UI + QTimer + 编排）
- **Service 层**：CandidateService（历史/external_id 去重/学校过滤/导出）
- **Workflow 层**（bizflow/）：ResumeCollectionWorkflow（采集）/ ResumeDownloadWorkflow（下载）
- **站点层**：SiteAdapter（Site51Job 真实 / SiteBoss 骨架验证跨站点复用）
- **浏览器底座**：BrowserDriver / Actions / TargetResolver（8 个原子动作）
- download_worker.py：1104 → 86 行薄壳；browser_worker.py 薄壳化

### 关键验收
- automation_page 51job 知识清零（PageDetector/selector/JS = 0）
- 页面 Task DB 直连清零（self.db.get_task 等 = 0）
- 张婉婷真实下载黄金回归：704627 字节与重构前逐字节一致
- 带 AI 真实回归：AI 通过 → 下载成功（张婉婷 ai_pass=True）
- SiteBoss 骨架 Contract Test：同一 Workflow 驱动两个站点，源码零站点判断

### 打包相关
- 修复 `workflow/` 模块名与 PyInstaller `hook-workflow.py` 冲突 → 重命名 `bizflow/`
- 新增 onedir 打包配置 `build_gui_onedir.spec`（解决单文件自解压慢/安全软件拦截）
- onedir 输出 `dist/林林专属助手/`（19MB 启动器 + _internal 依赖，约 433MB）

### 用户环境排查（已解决）
- 对方 Win10 1511（2015 版），Windows 更新被公司锁死，无法升级
- 根因：Qt 6.11 + Python 3.12 的视图层最低要求 Win10 1809，1511 无法加载 QtWidgets
- 方案：PyQt5 兼容版（Qt 5.15 支持 Win7+），分支 codex/pyqt5-compat
- 验证：对方 Win10 1511 已能正常打开使用
- 结论：整个技术栈（PyQt5 + Python 3.12 + numpy/pandas/playwright）在 1511 上均兼容

### 双版本维护说明
- **PyQt6 主版**（分支 codex/browser-actions-refactor）：面向新系统（Win10 1809+）
- **PyQt5 兼容版**（分支 codex/pyqt5-compat）：面向旧系统（Win7 / Win10 1511）
- 两版本**核心逻辑完全一致**（bizflow/sites/browser/task/db/crawler 零差异），仅 GUI 层 API 不同
- 维护约定：
  - 业务逻辑改动（Workflow / SiteAdapter / Controller / Service / DB）→ 两个分支都要同步
  - GUI 改动 → 分别适配 PyQt6 与 PyQt5 的 API 差异
  - 核心 bug 修复 → cherry-pick 同步两个分支

## 已完成功能

### 1. 基础GUI框架 (PyQt6)
- 主窗口布局：左侧候选人表格 + 右侧控制面板和日志
- 菜单栏、工具栏、状态栏
- 样式表美化

### 2. 浏览器连接
- 自动检测Chrome调试端口
- 自动启动Chrome调试模式（程序启动/刷新时端口未开则自动拉起 Chrome，使用 C:\chrome-agent 配置目录保留登录会话）
- 自动连接并获取候选人列表

### 3. 候选人管理
- 表格显示候选人（姓名、学校、专业、学历）
- 全选/取消全选
- 学校名单过滤功能（可载入Excel学校名单）

### 4. 职位切换
- 自动获取职位列表
- 下拉框切换职位

### 5. 下载功能
- 开始下载/中断下载
- 分页下载支持
- 结果导出Excel

### 6. 数据库持久化 (SQLite)
- jobs表 - 岗位同步
- tasks表 - 任务记录
- task_candidates表 - 候选人记录
- task_logs表 - 任务日志
- 异步数据库操作（不阻塞UI）

### 7. 中断下载
- 使用multiprocessing.Event跨进程中断

## 待修复问题

### 1. ✅ 程序启动稳定（2026-08-11）
- 重新启用启动自动刷新，但先检测 Chrome 调试端口，未启动则跳过
- 结果回调整体 try/except 防护，异常不再导致崩溃
- 刷新任务增加 90 秒看门狗，超时自动终止并恢复界面

### 2. ✅ 数据库任务恢复（2026-08-11）
- 启动检测到未完成任务时，可从数据库恢复待处理候选人继续下载
- 恢复时自动还原职位、下载目录、AI 配置快照
- 提示用户确保浏览器停留在原任务中断时的页面

### 3. ✅ 候选人状态持久化（2026-08-11）
- 下载子进程实时写入候选人 AI 评估结果与下载状态到 task_candidates
- 任务进度（processed/success/failed/ai_pass/ai_fail/页码）实时更新
- 修复 create_task 嵌套事务导致的 database is locked，任务创建一直失败的问题
- 修复 GUI 下载时 AI 匹配描述未按职位传入（job_descriptions 未映射到 match_description）

### 4. ✅ 学校名单路径可配置（2026-08-11）
- 新增 `school_filter_config.json` 统一配置，兼容旧的 `school_list_path.txt`
- 无配置时回退到 `config.py` 默认路径

## 文件结构

```
resume-agent/
├── gui/
│   ├── __init__.py
│   ├── main_window.py      # 主窗口
│   └── resources/styles/   # 样式表
├── db/
│   ├── __init__.py
│   ├── models.py           # 数据模型
│   └── database.py         # 数据库操作
├── browser_worker.py       # 浏览器操作子进程
├── download_worker.py      # 下载操作子进程
├── main_gui.py             # GUI入口
└── build_gui.spec          # 打包配置
```

## 更新日志

### 2026-08-12（FluentUI 重构 · PyQt6-Fluent-Widgets）

按《FluentUI重构方案.md》实施，业务逻辑零改动：

- **Phase 1**：接入 PyQt6-Fluent-Widgets 1.11.3；主窗口按钮
  （PrimaryPushButton/PushButton + FluentIcon）、下拉框（ComboBox）、
  候选人表格（TableWidget）、勾选框、输入框全部替换为 Fluent 组件；
  主题接入 setTheme/setThemeColor
- **Phase 2**：状态栏改为 InfoBadge 徽标（浏览器/AI/任务三级颜色）；
  QSS 对齐 Fluent 调色板（浅色 #F3F3F3 + 白色卡片，暗色 #202020 + #2B2B2B）
- **Phase 3/4**：AI 配置对话框组件同步 Fluent 化（测试连接/生成描述保留）；
  图标统一 FluentIcon
- **Phase 5**：回归验证（用户实测），本阶段不打包

### 2026-08-12（UI 现代化改造 · PyQt6 深度美化）

按《UI现代化改造方案.md》分阶段实施：

#### 阶段1：视觉基础
- 全新亮色主题（default.qss）+ 暗色主题（dark.qss），统一设计令牌
- 主色蓝 #2563EB、成功绿、危险红、警告橙、圆角/间距规范
- 所有控件状态全覆盖：hover/pressed/disabled/focus、表格选中/悬停、滚动条、菜单、提示

#### 阶段2：无边框窗口 + 自定义标题栏
- 新增 gui/widgets/title_bar.py：标题栏拖拽、双击最大化、最小化/最大化/关闭（MDL2 图标）
- 窗口圆角 + 投影阴影，最大化时自动去圆角/阴影/边距
- Windows 边缘拖拽缩放（WM_NCHITTEST）
- 菜单栏/工具栏/状态栏移入圆角容器
- 设置菜单新增“暗色主题”切换
- **修复 PyQt6 6.11 崩溃坑**：覆写 nativeEvent 后调用 super().nativeEvent() 触发
  QtCore.pyd 访问违例；改为不调用 super、未处理消息返回 (False, 0)

#### 阶段3：组件精细化
- 表格新增“处理记录”徽标列（●已下载绿 / ●失败红 / ●AI淘汰橙 + 悬浮详情）
- 表格空状态提示
- SVG 图标集（刷新/下载/中断/暂停/继续）接入工具栏与下载按钮
- 操作日志按级别/关键词着色（错误红/成功绿/警告橙/时间灰）
- 任务进度条平滑动画（QPropertyAnimation），下载中实时更新

#### 阶段4：布局与交互
- 状态栏升级为状态条：浏览器/任务/AI 状态带彩色圆点
- 快捷键：F5 刷新、Ctrl+Enter 开始下载
- 卡片化面板（QGroupBox 统一圆角/留白）

#### 阶段5：验收与打包
- 亮/暗主题截图验证、主程序启动冒烟通过
- 重新打包 exe

### 2026-08-12（浏览器状态管理与任务恢复改造）

按照《ResumeAgent_浏览器状态管理与任务恢复改造方案》完成改造：

#### 第一阶段：SQLite 表结构对齐（含旧库自动迁移）
- jobs 增加 external_job_id / company_name / job_url / status
- tasks 增加 ai_config_snapshot / candidate_list_url / current_candidate_id / downloaded_count / rejected_count
- task_candidates 增加 status / sort_index / processed_at（状态机字段）
- task_logs 增加 event_type / candidate_id
- 旧数据库启动时自动 ALTER TABLE 补齐字段并回填状态，无需手动迁移

#### 第二阶段：TaskManager + 候选人状态机
- 新增 task/task_manager.py / task_state.py：任务创建/暂停/恢复/完成/取消 + 候选人状态流转
- 候选人状态：pending -> processing -> ai_rejected/downloading -> downloaded/failed
- 每个候选人处理完立即写库（禁止最后一次性保存）
- AI 配置快照：任务创建时保存，运行期间不受全局配置修改影响
- 恢复任务时计数从数据库累计，不归零

#### 第三阶段：BrowserManager
- 新增 browser/browser_manager.py（状态机 DISCONNECTED/STARTING/CONNECTING/CONNECTED/READY/RECONNECTING/ERROR）
- Chrome 启动/连接/健康检查/自动重连（3次，等待3/5/10秒）统一收口
- 独立 Profile：%LOCALAPPDATA%\ResumeAgent\chrome-profile（不再用 C:/chrome-agent）
- browser_worker / download_worker 不再各自 connect_over_cdp，统一走 BrowserManager

#### 第四阶段：PageDetector 页面/登录检测
- 新增 browser/page_detector.py：URL + DOM 特征组合判断
- 页面类型：LOGIN_PAGE / JOB_LIST_PAGE / CANDIDATE_LIST_PAGE / RESUME_DETAIL 等
- 登录状态：logged_in / expired / unknown（登录页特征来自 51job 登录页 HTML 分析）
- 登录失效时禁止候选人自动化操作，任务自动暂停

#### 第五阶段：启动与任务恢复
- 启动时（不依赖刷新成功）检测未完成任务，显示进度/当前页/已下载/AI淘汰/浏览器/登录状态
- 恢复前按序校验：浏览器 -> 登录状态 -> 页面类型 -> 岗位匹配 -> 定位当前页
- 岗位不匹配时禁止继续，提示并可一键切换
- 恢复只处理 pending/processing/failed 候选人，已下载/已淘汰自动跳过

#### 第六阶段：暂停/继续/异常恢复/重试
- GUI 新增 暂停下载 / 继续任务 按钮；暂停在当前候选人完成后生效
- 下载过程中每 5 秒浏览器健康检查，断开自动重连
- 登录失效自动暂停并提示重新登录
- 非 AI 淘汰的失败自动重试一次
- 状态栏新增 浏览器状态 与 任务状态 显示
- 刷新列表自动过滤已下载/AI淘汰候选人，下载失败保留并显示“处理记录”
- 附件入口检测增强：等待放宽至12秒、多选择器、tooltip 图标兜底、失败保存诊断日志

### 2026-08-11

- 候选人状态实时持久化到 SQLite（AI结果、下载状态、任务进度）
- 实现未完成任务恢复（从数据库待处理候选人继续下载）
- 学校名单路径改为可配置（school_filter_config.json）
- 启动自动刷新加端口检测/异常防护/看门狗，重新启用
- 修复 create_task 数据库锁问题
- 修复 GUI 模式 AI 匹配描述未按职位传入的问题
- 已用 Python 3.14.7 + PyInstaller 6.22 打包 GUI exe（dist\AI简历批量初筛与下载助手.exe），启动冒烟测试通过
- 启动助手.bat 已更新为优先加载 dist 下打包的 exe
- Chrome 调试模式改为程序自动启动：无需手动运行 启动Chrome.bat，冒烟测试验证端口自动开启
