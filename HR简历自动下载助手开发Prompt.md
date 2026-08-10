# HR简历自动下载助手（Resume Automation Assistant）

## 项目目标

开发一个基于 Python + Playwright 的浏览器自动化工具。

目标场景：

HR 登录前程无忧（51job）网页版后，打开候选人列表页面，由程序接管当前 Chrome 浏览器：

1. 自动读取候选人列表
2. 逐个进入候选人简历详情页
3. 点击下载附件简历
4. 自动保存简历文件
5. 自动记录候选人基础信息
6. 输出下载结果 Excel

第一阶段只实现自动下载，不做 AI 筛选。

---

## 技术要求

技术栈：

- Python 3.11+
- Playwright
- Chromium
- pandas
- openpyxl
- pypdf

项目结构：

```
resume-agent/

├── main.py
├── config.py
├── browser/
│   └── chrome.py
├── crawler/
│   ├── candidate.py
│   └── resume.py
├── downloader/
│   └── file.py
├── output/
│   ├── resumes/
│   └── result.xlsx
├── requirements.txt
└── README.md
```

---

# 第一阶段：浏览器接管

不要自动登录网站。

采用 Chrome Remote Debugging。

用户流程：

1. 启动 Chrome：

```
chrome.exe --remote-debugging-port=9222 --user-data-dir=C:\chrome-agent
```

2. 手动登录前程无忧

3. Python 连接当前 Chrome

实现：

```python
connect_over_cdp("http://localhost:9222")
```

启动后输出：

```
当前浏览器连接成功
当前页面:
title:
url:
```

---

# 第二阶段：候选人列表读取

设计 CandidateParser。

返回：

```python
[
 {
   "name":"",
   "url":"",
   "id":""
 }
]
```

如果 selector 不确定：

增加 debug 模式：

- 输出 HTML
- 输出可点击元素
- 输出链接信息

---

# 第三阶段：自动进入简历详情

流程：

```
列表页
 ↓
点击候选人
 ↓
等待页面加载
 ↓
获取候选人信息
 ↓
下载附件简历
 ↓
返回列表
```

要求：

- 超时处理
- 页面异常恢复
- 下载失败重试

---

# 第四阶段：附件下载

使用：

```python
page.expect_download()
```

保存：

```
output/resumes/
```

命名：

```
姓名_日期_序号.pdf
```

例如：

```
张三_20260807_001.pdf
```

保留原格式：

- pdf
- doc
- docx

---

# 第五阶段：结果记录

生成：

```
output/result.xlsx
```

字段：

|字段|说明|
|-|-|
|姓名|候选人姓名|
|简历地址|详情页|
|文件路径|下载位置|
|下载时间|时间|
|状态|成功/失败|
|错误信息|异常|

---

# 第六阶段：稳定性

日志：

```
logs/app.log
```

记录：

- 页面访问
- 下载成功
- 下载失败

异常处理：

1. 页面加载失败

刷新重试。

2. 下载失败

重新点击。

3. 登录失效

检测登录页并提示重新登录。

---

# 第七阶段：配置化

config.py：

```python
DOWNLOAD_PATH="./output/resumes"

MAX_DOWNLOAD=100

WAIT_TIME=3
```

---

# 第八阶段：运行方式

安装：

```bash
pip install -r requirements.txt

playwright install chromium
```

运行：

```bash
python main.py
```

---

# 后续扩展

## AI简历分析

未来流程：

```
下载简历

↓

PDF解析

↓

GPT分析

↓

岗位匹配评分

↓

Excel输出
```

预留：

```
analyzer/

ai/

report/
```

---

# 开发要求

1. 不要一次性实现所有功能。
2. 每完成一个阶段先运行验证。
3. 遇到网页结构不确定时，不允许硬编码大量 selector。
4. 优先增加 debug 工具辅助定位页面结构。
5. 所有代码必须可运行。
6. 输出详细 README。
7. 第一目标：成功自动下载一份简历。
