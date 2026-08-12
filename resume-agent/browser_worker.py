# -*- coding: utf-8 -*-
"""
浏览器操作进程 - 在独立进程中运行
"""
import sys
import json
import time
from pathlib import Path

if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

sys.path.insert(0, str(BASE_DIR))


def run(switch_job=''):
    """执行浏览器连接和候选人获取"""
    from browser.browser_manager import BrowserManager
    from browser.page_detector import PageDetector, PageType, LoginStatus

    result = {
        'success': False,
        'candidates': [],
        'positions': [],
        'active_position': '',
        'page_title': '',
        'page_url': '',
        'page_type': '',
        'login_status': '',
        'current_page': 1,
        'error': ''
    }

    try:
        # 统一由 BrowserManager 启动/连接
        manager = BrowserManager()
        if not manager.initialize(auto_launch=True):
            result['error'] = manager.last_error or '浏览器连接失败'
            return result

        page = manager.get_page()
        if not page:
            result['error'] = '未找到可用页面'
            manager.close()
            return result

        result['page_title'] = page.title()
        result['page_url'] = page.url
        result['page_type'] = PageDetector.detect(page=page)
        result['login_status'] = PageDetector.is_logged_in(page=page)

        # 登录失效时禁止候选人自动化操作（方案第 9 节）
        if result['login_status'] == LoginStatus.EXPIRED:
            result['error'] = '前程无忧登录状态已失效，请重新登录'
            manager.close()
            return result

        # 获取职位列表（使用menu-item_content_active判断当前选中）
        try:
            pos_info = page.evaluate('''() => {
                const items = document.querySelectorAll('.job_name_text');
                const positions = [];
                let activeName = '';

                items.forEach(el => {
                    const name = el.textContent.trim();
                    if (!name) return;
                    
                    // 判断当前选中：检查menu-item_content是否有menu-item_content_active类
                    const menuItemContent = el.closest('.menu-item_content');
                    const isActive = menuItemContent ? menuItemContent.classList.contains('menu-item_content_active') : false;
                    
                    positions.push({ name: name, active: isActive });
                    if (isActive) activeName = name;
                });

                return { positions: positions, active: activeName };
            }''')
            result['positions'] = pos_info.get('positions', [])
            result['active_position'] = pos_info.get('active', '')
        except Exception as e:
            pass

        # 如果指定了切换职位
        if switch_job:
            try:
                clicked = page.evaluate('''(targetName) => {
                    const items = document.querySelectorAll('.job_name_text');
                    for (const el of items) {
                        if (el.textContent.trim() === targetName) {
                            const wrap = el.closest('.job_name_wrap') || el.closest('.menu-item') || el;
                            wrap.click();
                            return true;
                        }
                    }
                    return false;
                }''', switch_job)

                if clicked:
                    time.sleep(5)  # 等待页面刷新
                    result['active_position'] = switch_job
            except Exception:
                pass

        # 获取当前页码和总页数
        try:
            page_info = page.evaluate('''() => {
                let currentPage = 1;
                let totalPages = 1;

                // 获取当前页码
                const active = document.querySelector('.eh-pagination__pagelist li.active');
                if (active) {
                    const text = active.textContent.trim();
                    const num = parseInt(text);
                    if (!isNaN(num)) currentPage = num;
                }

                // 获取总页数（从分页控件的最后一页获取）
                const pageItems = document.querySelectorAll('.eh-pagination__pagelist li');
                if (pageItems.length > 0) {
                    const lastPage = pageItems[pageItems.length - 1];
                    const text = lastPage.textContent.trim();
                    const num = parseInt(text);
                    if (!isNaN(num)) totalPages = num;
                }

                // 也可以从总数和每页条数计算
                const totalEl = document.querySelector('.eh-pagination__total');
                if (totalEl) {
                    const match = totalEl.textContent.match(/\\d+/);
                    if (match) {
                        const total = parseInt(match[0]);
                        // 假设每页50条
                        const calculatedPages = Math.ceil(total / 50);
                        if (calculatedPages > totalPages) {
                            totalPages = calculatedPages;
                        }
                    }
                }

                return { currentPage, totalPages };
            }''')
            result['current_page'] = page_info.get('currentPage', 1)
            result['total_pages'] = page_info.get('totalPages', 1)
        except Exception:
            result['current_page'] = 1
            result['total_pages'] = 1

        # 滚动获取所有候选人（包含学校信息）
        all_candidates = []
        seen = set()
        no_new_count = 0

        try:
            page.mouse.move(600, 400)
            time.sleep(0.5)
        except Exception:
            pass

        for round_num in range(100):
            try:
                current = page.evaluate('''() => {
                    const items = document.querySelectorAll('.item.virtual_list');
                    const candidates = [];

                    items.forEach(item => {
                        let name = '';
                        let school = '';
                        let major = '';
                        let education = '';

                        // 获取姓名
                        const nameEl = item.querySelector('.detail .firstline .name')
                            || item.querySelector('.name');
                        if (nameEl) {
                            name = nameEl.textContent.trim();
                        }

                        // 获取学校、专业、学历
                        const schoolEl = item.querySelector('.school_name');
                        if (schoolEl) {
                            school = schoolEl.textContent.trim();
                        }

                        const majorEl = item.querySelector('.major_name');
                        if (majorEl) {
                            major = majorEl.textContent.trim();
                        }

                        // 获取学历
                        const detailEl = item.querySelector('.name.context-detail');
                        if (detailEl) {
                            const spans = detailEl.querySelectorAll('span[title]');
                            spans.forEach(span => {
                                const title = span.getAttribute('title');
                                if (title && (title === '本科' || title === '硕士' || title === '博士' || title === '大专' || title === '专科')) {
                                    education = title;
                                }
                            });
                        }

                        if (name && name.length > 0 && name.length < 20 && name !== ' ') {
                            candidates.push({
                                name: name,
                                school: school,
                                major: major,
                                education: education
                            });
                        }
                    });

                    return candidates;
                }''')
            except Exception:
                break

            new_count = 0
            for c in current:
                key = c['name']
                if key not in seen:
                    seen.add(key)
                    all_candidates.append(c)
                    new_count += 1

            if new_count > 0:
                no_new_count = 0
            else:
                no_new_count += 1

            if no_new_count >= 3:
                break

            try:
                page.mouse.wheel(0, 600)
                time.sleep(1)
            except Exception:
                break

        result['candidates'] = all_candidates
        result['success'] = True

        manager.close()

    except Exception as e:
        result['error'] = str(e)

    return result


def main():
    """命令行入口"""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--switch', type=str, default='', help='切换到指定职位')
    args = parser.parse_args()

    result = run(args.switch)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
