# HR简历自动下载助手

## 项目简介

基于 Python + Playwright 的浏览器自动化工具，用于从前程无忧（51job）网页版自动下载候选人简历。

## 当前开发进度

### 已完成功能

| 功能 | 状态 | 说明 |
|------|------|------|
| Chrome CDP 连接 | ✅ 完成 | 通过 Remote Debugging 接管已登录的浏览器 |
| 候选人列表解析 | ✅ 完成 | 解析 `.item.virtual_list` 元素获取候选人信息 |
| 虚拟滚动处理 | ✅ 完成 | 使用 Page Down 键盘事件触发虚拟滚动加载 |
| 详情页打开 | ✅ 完成 | 点击候选人进入新标签页详情 |
| 附件简历下载 | ✅ 完成 | 点击"附件个人信息" → 点击"下载"按钮 |
| 结果统计 | ✅ 完成 | 显示成功/失败数量和详细信息 |

### 待开发功能

| 功能 | 状态 | 说明 |
|------|------|------|
| 分页处理 | ⏳ 待开发 | 下载完当前页后自动翻到下一页继续 |
| 结果导出 Excel | ⏳ 待开发 | 输出下载结果到 result.xlsx |
| 日志记录 | ⏳ 待开发 | 记录运行日志到 logs/app.log |
| 配置化 | ⏳ 待开发 | 支持自定义下载路径、最大数量等 |

## 技术架构

### 技术栈

- Python 3.11+
- Playwright (浏览器自动化)
- pandas + openpyxl (Excel 输出)
- PyInstaller (打包为 exe)

### 项目结构

```
resume-agent/
├── main.py              # 主程序
├── browser/
│   └── chrome.py        # Chrome CDP 连接
├── crawler/
│   └── candidate.py     # 候选人解析
├── downloader/
│   └── file.py          # 文件下载
├── output/
│   ├── resumes/         # 简历存放目录
│   └── result.xlsx      # 结果输出
├── logs/
│   └── app.log          # 运行日志
├── config.py            # 配置文件
├── requirements.txt     # 依赖列表
└── README.md            # 项目说明
```

## 核心实现

### 虚拟滚动处理

前程无忧页面使用虚拟滚动，DOM中只有可见区域的元素有实际内容。解决方案：

```python
def collect_all_candidates_with_scroll(page):
    """通过滚动收集所有候选人"""
    # 点击页面获取焦点
    page.click('body')
    
    # 使用 Page Down 键盘事件滚动
    page.keyboard.press('PageDown')
    
    # 每次滚动后获取新出现的候选人
    # 重复直到没有新候选人
```

### 简历下载流程

```
1. 点击候选人 → 新标签页打开详情
2. 点击"附件个人信息"按钮
3. 等待附件简历页面打开
4. 点击"下载"按钮
5. 保存文件到本地
6. 关闭标签页，继续下一个
```

## 使用方法

### 开发环境

```bash
# 安装依赖
pip install -r requirements.txt

# 安装 Playwright 浏览器
playwright install chromium

# 运行程序
python main.py
```

### 打包为 exe

```bash
# 使用 PyInstaller 打包
pyinstaller --onefile --console --name resume-agent main.py
```

### 使用步骤

1. 启动 Chrome 调试模式：
   ```
   chrome.exe --remote-debugging-port=9222 --user-data-dir=C:\chrome-agent
   ```

2. 在 Chrome 中登录前程无忧，进入候选人列表页面

3. 运行程序，选择操作：
   - `1` - 自动下载所有简历
   - `2` - 下载指定简历
   - `0` - 测试滚动功能（调试用）

## 已知问题

1. **虚拟滚动** - 页面使用虚拟滚动，需要通过键盘事件触发加载
2. **下载按钮** - 部分候选人可能没有附件简历或下载按钮
3. **分页** - 当前只能下载单页，需要开发分页功能

## 下一步计划

1. 实现分页处理 - 自动翻到下一页继续下载
2. 添加结果导出 - 输出 Excel 格式的下载结果
3. 添加日志记录 - 记录运行过程和错误信息
4. 优化错误处理 - 处理网络异常、页面加载失败等情况

## 更新日志

### 2026-08-07

- 完成基础功能：Chrome连接、候选人解析、简历下载
- 解决虚拟滚动问题：使用 Page Down 键盘事件触发加载
- 实现单页50个候选人的自动下载
- 打包为 exe 可执行文件
