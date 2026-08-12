# ResumeAgent FluentUI 重构方案（PyQt6）

> 2026-08-12 · 目标：用微软 Fluent Design（Win11 风格）重构当前 GUI，
> **业务逻辑零改动**，本阶段不打包。

## 1. 技术选型

采用 **PyQt-Fluent-Widgets**（zhiyiYo，PyQt6 生态最成熟的 Fluent 实现）：

- FluentWindow 窗口框架：导航侧栏 + 自定义标题栏 + 深浅主题自动切换 + 原生缩放
- FluentIcon：微软风格官方图标集
- 组件：CardWidget / InfoBadge / TableWidget / ComboBox / ProgressBar /
  SwitchButton / Messagebox 等
- Acrylic 亚克力、圆角、hover 动效

备选方案 B（兜底）：若 PyQt-Fluent-Widgets 与 PyQt6.11 存在兼容问题，
回退为“手写 Fluent 风格 QSS”（不新增依赖，视觉接近但无 Acrylic/动效）。

## 2. 硬约束：不动的部分

- browser/、task/、db/、crawler/、config.py
- browser_worker.py、download_worker.py、main.py（CLI）
- 下载、分页、AI 筛选、任务恢复、数据库、Excel 全部业务逻辑
- 信号槽的业务回调不变，只替换控件外观与布局容器

## 3. 动的范围

```
resume-agent/
├── gui/
│   ├── main_window.py          # 布局/控件替换（FluentWindow + Fluent 组件）
│   ├── widgets/                # Fluent 组件封装（当前 title_bar 弃用）
│   └── resources/styles/       # QSS 替换为 Fluent 主题（含深浅色）
└── requirements.txt            # 新增 PyQt-Fluent-Widgets
```

## 4. 分阶段实施

### 阶段 1：依赖与窗口骨架
- 安装 PyQt-Fluent-Widgets
- 用 FluentWindow 搭建主框架：导航（工作台/任务/数据/设置）+ 标题栏 +
  深浅主题切换 + 原生缩放
- 迁移现有 setup_ui 的内容区进 Fluent 页面容器
- 验收：主窗口可启动，导航可切换，业务回调不报错

### 阶段 2：组件替换（保持业务信号不变）
- 按钮：PrimaryButton / OutlineButton / 图标按钮（替换开始/中断/暂停/继续/刷新）
- 下载控制：CardWidget 卡片化
- 候选人表格：TableWidget + 状态 InfoBadge（已下载/失败/AI淘汰）
- 日志：保留 QTextEdit 逻辑，套 Fluent 样式与字体
- 下拉框（职位/匹配描述）、勾选框（下载所有页/学校筛选/启用AI）→ Fluent 组件
- 状态栏 → 顶部/侧栏状态胶囊（Chrome/AI/任务）

### 阶段 3：对话框
- AI 配置对话框：Fluent 表单 + 保留“测试连接 / AI 生成描述”功能
- 学校名单载入、恢复任务确认、退出确认 → Fluent Messagebox

### 阶段 4：视觉打磨
- FluentIcon 图标统一
- 间距/圆角/明暗色规范
- 空状态、进度动画、hover 动效

### 阶段 5：回归验证（不打包）
- 全流程：启动 → Chrome 连接 → 刷新岗位/候选人 → 下载 → 暂停/恢复/中断 →
  任务恢复 → AI 配置（测试连接/生成描述）→ 学校筛选 → Excel
- 截图对比 + 语法/导入检查
- 更新 PROGRESS.md

## 5. 风险与兼容

- 新增一个第三方依赖；PyQt6.11 兼容性需在阶段 1 先行验证（有兜底方案 B）
- FluentWindow 基于 QMainWindow，与当前原生边框方案可平滑过渡
- 深浅主题由 FluentWindow 管理，替换现有 default.qss/dark.qss 的切换逻辑
- 只动 GUI 层，业务回归风险低；每阶段结束 PyQt6 仍可运行

## 6. 回滚

- 重构前检查点：commit `e5a957f`（原生边框 + 黑缝修复后的稳定态）
- 任意阶段失败：`git checkout e5a957f` 恢复当前 UI
