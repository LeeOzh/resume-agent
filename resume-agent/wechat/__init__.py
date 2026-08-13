# -*- coding: utf-8 -*-
"""
微信简历监听模块（V1 极简功能）

- 使用 pywechat127（pyweixin）监听微信群消息（微信 4.1.6+）
- 发现 pdf 文件 -> 下载 -> 解析文件名中的姓名 -> 存入 SQLite -> 导出 Excel

约束：不引入 LLM、不修改前程无忧任务逻辑、不复用 task_candidates，
仅使用独立的 wechat_resume_records 表。
"""
