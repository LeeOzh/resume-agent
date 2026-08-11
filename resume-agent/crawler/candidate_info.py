# -*- coding: utf-8 -*-
"""
候选人信息提取模块
"""
from playwright.sync_api import Page


def get_all_candidate_info(page):
    """
    获取DOM中所有候选人的详细信息（包括学校）

    Args:
        page: Playwright页面对象

    Returns:
        dict: 包含候选人列表和统计信息
    """
    try:
        result = page.evaluate('''() => {
            const items = document.querySelectorAll('.item.virtual_list');
            const result = {
                total: items.length,
                candidates: [],
                failed: []
            };

            items.forEach((item, index) => {
                try {
                    // 获取姓名
                    let name = '';
                    const nameEl = item.querySelector('.detail .firstline .name')
                        || item.querySelector('.name');
                    if (nameEl) {
                        name = nameEl.textContent.trim();
                    }

                    // 获取学校信息
                    let school = '';
                    // 尝试多种方式获取学校
                    const schoolSelectors = [
                        '.school',
                        '.edu_school',
                        '.education .school',
                        '.detail .school',
                        '[class*="school"]',
                        '.education_info',
                        '.edu_info'
                    ];

                    for (const sel of schoolSelectors) {
                        const el = item.querySelector(sel);
                        if (el && el.textContent.trim()) {
                            school = el.textContent.trim();
                            break;
                        }
                    }

                    // 如果没找到专门的学校元素，尝试从innerText中提取
                    if (!school) {
                        const text = item.innerText;
                        // 匹配常见的学校格式
                        const schoolPatterns = [
                            /([\u4e00-\u9fa5]+大学)/,
                            /([\u4e00-\u9fa5]+学院)/,
                            /([\u4e00-\u9fa5]+学校)/,
                        ];
                        for (const pattern of schoolPatterns) {
                            const match = text.match(pattern);
                            if (match) {
                                school = match[1];
                                break;
                            }
                        }
                    }

                    // 获取学历
                    let education = '';
                    const eduSelectors = [
                        '.education',
                        '.edu',
                        '[class*="edu"]',
                        '.degree'
                    ];
                    for (const sel of eduSelectors) {
                        const el = item.querySelector(sel);
                        if (el && el.textContent.trim()) {
                            education = el.textContent.trim();
                            break;
                        }
                    }

                    // 获取工作经验
                    let experience = '';
                    const expSelectors = [
                        '.experience',
                        '.exp',
                        '[class*="exp"]',
                        '.work_year'
                    ];
                    for (const sel of expSelectors) {
                        const el = item.querySelector(sel);
                        if (el && el.textContent.trim()) {
                            experience = el.textContent.trim();
                            break;
                        }
                    }

                    // 获取求职意向
                    let applyInfo = '';
                    const applyEl = item.querySelector('.apply_news');
                    if (applyEl) {
                        applyInfo = applyEl.textContent.trim();
                    }

                    // 获取技能标签
                    let skills = [];
                    const skillEls = item.querySelectorAll('.search_tag .skill_label, .labelHighLight');
                    skillEls.forEach(el => {
                        const text = el.textContent.trim();
                        if (text) skills.push(text);
                    });

                    if (name && name.length > 0 && name.length < 20) {
                        result.candidates.push({
                            name: name,
                            school: school,
                            education: education,
                            experience: experience,
                            applyInfo: applyInfo,
                            skills: skills,
                            index: index
                        });
                    } else {
                        result.failed.push({
                            index: index,
                            name: name,
                            school: school,
                            innerText: item.innerText.substring(0, 150)
                        });
                    }
                } catch (e) {
                    result.failed.push({
                        index: index,
                        error: e.message
                    });
                }
            });

            return result;
        }''')

        return result

    except Exception as e:
        print(f"获取候选人信息失败: {e}")
        return {'total': 0, 'candidates': [], 'failed': []}


def get_candidate_names_only(page):
    """获取候选人姓名列表（兼容旧接口）"""
    result = get_all_candidate_info(page)
    return [c['name'] for c in result['candidates']]


def filter_candidates_by_school(candidates, school_filter):
    """
    使用学校过滤器过滤候选人

    Args:
        candidates: 候选人列表
        school_filter: 学校过滤器实例

    Returns:
        list: 过滤后的候选人列表
    """
    if not school_filter or not school_filter.enabled:
        return candidates

    filtered = []
    removed = []

    for candidate in candidates:
        school = candidate.get('school', '')
        if school_filter.is_allowed_school(school):
            filtered.append(candidate)
        else:
            removed.append(candidate)

    if removed:
        print(f"\n学校过滤结果:")
        print(f"  原始候选人: {len(candidates)} 人")
        print(f"  过滤后: {len(filtered)} 人")
        print(f"  已移除: {len(removed)} 人")

        if len(removed) <= 10:
            print(f"\n  被移除的候选人:")
            for c in removed:
                print(f"    - {c['name']} ({c.get('school', '未知学校')})")
        else:
            print(f"\n  被移除的候选人（前10个）:")
            for c in removed[:10]:
                print(f"    - {c['name']} ({c.get('school', '未知学校')})")
            print(f"    ... 还有 {len(removed) - 10} 人")

    return filtered