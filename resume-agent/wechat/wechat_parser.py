# -*- coding: utf-8 -*-
"""
文件名解析：广州海颐-xxxxx工程师-姓名.pdf -> 姓名

规则（纯规则，不引入 LLM）：
1. 去掉扩展名，统一分隔符（-、－、—、_、空格）
2. 去掉公司前缀（如 广州海颐 / 海颐）
3. 按 - 分段，去掉包含“工程师/岗位/职位/简历”等词的分段
4. 剩余分段中取最后一个符合中文姓名规则的段
5. 仍失败则用中文姓名正则兜底；解析不出返回空串（status=parse_failed）
"""
import re

# 职位/说明类关键词：包含这些词的段不视为姓名
_STRIP_SEGMENT_RE = re.compile(
    r'工程师|岗位|职位|开发|前端|后端|测试|运维|产品|设计|运营|'
    r'实习|招聘|简历|简历筛选|应聘|求职|海颐|公司|集团'
)

_NAME_RE = re.compile(r'[\u4e00-\u9fa5]{2,6}')


def normalize_filename(file_name: str) -> str:
    """去掉扩展名并统一分隔符"""
    name = (file_name or '').strip()
    if not name:
        return ''
    lower = name.lower()
    for ext in ('.pdf',):
        if lower.endswith(ext):
            name = name[:-len(ext)]
            break
    # 统一常见分隔符
    name = name.replace('－', '-').replace('—', '-').replace('―', '-') \
               .replace('_', '-').replace('　', '-').replace(' ', '-')
    name = re.sub(r'-+', '-', name).strip('-')
    return name


def _is_chinese_name(seg: str) -> bool:
    seg = seg.strip()
    return bool(seg) and 2 <= len(seg) <= 6 and bool(re.fullmatch(r'[\u4e00-\u9fa5]{2,6}', seg))


def _fallback_chinese_name(text: str) -> str:
    """兜底：从文本中提取第一段连续中文（2-6 字）"""
    m = _NAME_RE.search(text or '')
    return m.group(1) if m else ''


def parse_candidate_name(file_name: str, company_prefixes=None) -> str:
    """
    从文件名提取候选人姓名。

    示例：
        广州海颐-前端工程师-张三.pdf -> 张三
        海颐-测试工程师-李四.pdf      -> 李四
        张三-简历.pdf                 -> 张三
    """
    prefixes = company_prefixes or ["广州海颐", "海颐"]
    name = normalize_filename(file_name)
    if not name:
        return ''

    # 去掉公司前缀
    for prefix in prefixes:
        if prefix and name.startswith(prefix):
            name = name[len(prefix):].strip('-')
            break
    if not name:
        return ''

    segments = [seg.strip() for seg in name.split('-') if seg.strip()]
    candidates = [seg for seg in segments if not _STRIP_SEGMENT_RE.search(seg)]

    # 优先取最后一个符合中文姓名规则的段
    for seg in reversed(candidates):
        if _is_chinese_name(seg):
            return seg

    # 兜底：中文姓名正则
    return _fallback_chinese_name(name)
