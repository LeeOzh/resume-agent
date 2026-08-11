# GUI改造进度说明

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
