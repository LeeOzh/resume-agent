# -*- coding: utf-8 -*-
"""
下载操作进程 - 在独立进程中运行，支持分页下载和中断
"""
import sys
import json
import time
from pathlib import Path
from datetime import datetime

if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

sys.path.insert(0, str(BASE_DIR))


def run(candidates, download_dir, job_name='', ai_config=None, 
        download_all_pages=False, stop_event=None, task_id=None, db_path=None,
        pause_event=None):
    """
    执行下载操作
    
    Args:
        candidates: 候选人列表，每个为dict（name/school/major/education）
        download_dir: 下载目录
        job_name: 职位名称
        ai_config: AI配置
        download_all_pages: 是否下载所有页
        stop_event: multiprocessing.Event，用于跨进程中断
        task_id: 数据库任务ID，用于候选人状态实时持久化
        db_path: 数据库文件路径（默认使用项目配置）
        pause_event: multiprocessing.Event，暂停请求（当前候选人完成后暂停）
    """
    # 兼容旧调用：只传姓名列表
    if candidates and isinstance(candidates[0], str):
        candidates = [{'name': n} for n in candidates]

    # 数据库持久化（候选人状态实时写入，禁止攒到最后一次性保存）
    tm = None
    if task_id:
        try:
            from task import TaskManager
            tm = TaskManager(db_path) if db_path else TaskManager()
        except Exception:
            tm = None

    def is_stopped():
        """检查是否已停止"""
        return stop_event is not None and stop_event.is_set()

    def is_pause_requested():
        """检查是否请求暂停（当前候选人完成后暂停）"""
        return pause_event is not None and pause_event.is_set()

    def candidate_ext_id(candidate):
        """获取候选人外部ID（优先显式ID，否则姓名+学校+专业hash）"""
        if candidate.get('external_id'):
            return candidate['external_id']
        try:
            from db.models import generate_candidate_external_id
            return generate_candidate_external_id(
                candidate.get('name', ''),
                candidate.get('school', '') or '',
                candidate.get('major', '') or '',
            )
        except Exception:
            return candidate.get('name', '') or ''

    def get_candidate_status(candidate):
        """查询候选人当前状态，用于跳过已处理候选人"""
        if not tm or not task_id:
            return None
        try:
            ext_id = candidate_ext_id(candidate)
            c = tm.db.get_candidate_by_external_id(task_id, ext_id)
            return c.status if c else None
        except Exception:
            return None

    def persist_candidate(candidate, page_num, download_result):
        """将候选人处理结果写入数据库（每个候选人立即保存）"""
        if not tm or not task_id:
            return
        try:
            name = candidate.get('name', '')
            school = candidate.get('school', '') or ''
            major = candidate.get('major', '') or ''
            education = candidate.get('education', '') or ''
            ext_id = candidate_ext_id(candidate)
            tm.upsert_candidate(task_id, {
                'external_id': ext_id,
                'name': name,
                'school': school,
                'major': major,
                'education': education,
                'page': page_num,
                'sort_index': candidate.get('sort_index', 0),
            })
            if download_result.get('ai_pass') is not None:
                tm.save_ai_result(
                    task_id, ext_id,
                    ai_pass=bool(download_result.get('ai_pass')),
                    ai_reason=download_result.get('ai_reason', '') or '',
                )
            if download_result.get('success'):
                tm.mark_candidate_downloaded(
                    task_id, ext_id,
                    file_path=download_result.get('file_path', '') or '',
                )
            elif download_result.get('ai_pass') is False:
                pass  # save_ai_result 已把状态置为 ai_rejected
            else:
                tm.mark_candidate_failed(
                    task_id, ext_id,
                    error=download_result.get('error', '') or '',
                )
        except Exception:
            pass

    def update_task_progress(**stats):
        """更新任务进度"""
        if not tm or not task_id:
            return
        try:
            tm.update_progress(task_id, **stats)
        except Exception:
            pass

    result = {
        'success': False,
        'results': [],
        'total_pages': 1,
        'current_page': 1,
        'error': ''
    }

    # 从数据库恢复已累计的进度（恢复任务时计数不归零，方案第 21 节）
    base_counters = {'processed': 0, 'success': 0, 'failed': 0, 'ai_pass': 0, 'ai_fail': 0}
    if tm and task_id:
        try:
            t = tm.get_task(task_id)
            base_counters['processed'] = t.processed_count or 0
            base_counters['success'] = t.success_count or 0
            base_counters['failed'] = t.failed_count or 0
            base_counters['ai_pass'] = t.ai_pass_count or 0
            base_counters['ai_fail'] = t.ai_fail_count or 0
        except Exception:
            pass

    try:
        from browser.browser_manager import BrowserManager
        from browser.page_detector import PageDetector, LoginStatus

        # 统一由 BrowserManager 启动/连接（方案第 3 节）
        manager = BrowserManager()
        if not manager.initialize(auto_launch=True):
            result['error'] = manager.last_error or '浏览器连接失败'
            return result

        context = manager.context
        page = manager.get_page()
        if not page or not context:
            result['error'] = '未找到打开的页面'
            manager.close()
            return result

        # 登录状态检测：登录失效时禁止候选人自动化操作（方案第 9 节）
        if PageDetector.is_logged_in(page=page) == LoginStatus.EXPIRED:
            result['error'] = '前程无忧登录状态已失效，请重新登录'
            result['login_expired'] = True
            manager.close()
            return result

        def ensure_browser_ready():
            """浏览器健康检查，断开时自动重连（最多3次）"""
            if manager.health_check():
                return True
            return manager.reconnect()

        def refresh_page():
            """重连后重新获取 page/context"""
            nonlocal page, context
            page = manager.get_page()
            context = manager.context
            return page is not None and context is not None

        # 创建下载目录
        download_path = Path(download_dir)
        download_path.mkdir(parents=True, exist_ok=True)

        all_results = []
        page_num = 1
        global_index = 0
        processed_count = base_counters['processed']
        success_count = base_counters['success']
        failed_count = base_counters['failed']
        ai_pass_count = base_counters['ai_pass']
        ai_fail_count = base_counters['ai_fail']

        def record(candidate, page_no, download_result):
            """统计并持久化单个候选人的处理结果"""
            nonlocal processed_count, success_count, failed_count, ai_pass_count, ai_fail_count
            processed_count += 1
            if download_result.get('success'):
                success_count += 1
            else:
                failed_count += 1
            if download_result.get('ai_pass') is True:
                ai_pass_count += 1
            elif download_result.get('ai_pass') is False:
                ai_fail_count += 1
            persist_candidate(candidate, page_no, download_result)
            update_task_progress(
                processed_count=processed_count,
                success_count=success_count,
                failed_count=failed_count,
                ai_pass_count=ai_pass_count,
                ai_fail_count=ai_fail_count,
                current_page=page_num,
                total_pages=page_num,
            )

        if download_all_pages:
            # 分页下载模式
            while not is_stopped():
                # 收集当前页候选人（含学校/专业/学历信息）
                if not ensure_browser_ready() or not refresh_page():
                    result['error'] = '浏览器断开且自动重连失败，任务已暂停'
                    result['paused'] = True
                    break
                if PageDetector.is_logged_in(page=page) == LoginStatus.EXPIRED:
                    result['error'] = '前程无忧登录状态已失效，任务已暂停，请重新登录后继续'
                    result['login_expired'] = True
                    break
                current_candidates = collect_all_candidates_with_scroll(page)
                if not current_candidates:
                    break

                # 滚动回顶部
                page.keyboard.press('Home')
                time.sleep(1)

                # 逐个下载当前页
                for cand in current_candidates:
                    if is_stopped():
                        break
                    if is_pause_requested():
                        break

                    if not ensure_browser_ready() or not refresh_page():
                        result['error'] = '浏览器断开且自动重连失败，任务已暂停'
                        result['paused'] = True
                        break
                    if PageDetector.is_logged_in(page=page) == LoginStatus.EXPIRED:
                        result['error'] = '前程无忧登录状态已失效，任务已暂停，请重新登录后继续'
                        result['login_expired'] = True
                        break

                    # 已处理候选人直接跳过（方案第 25/26 节）
                    cand_status = get_candidate_status(cand)
                    if cand_status in ('downloaded', 'ai_rejected'):
                        continue

                    global_index += 1
                    name = cand.get('name', '')
                    # 标记处理中
                    if tm and task_id:
                        try:
                            tm.mark_candidate_processing(task_id, candidate_ext_id(cand))
                        except Exception:
                            pass
                    download_result = download_single_resume(
                        context, page, name, download_path, global_index, ai_config, job_name
                    )
                    # 失败重试一次（AI不通过不重试）
                    if (not download_result.get('success')
                            and download_result.get('ai_pass') is not False):
                        time.sleep(2)
                        download_result = download_single_resume(
                            context, page, name, download_path, global_index, ai_config, job_name
                        )
                    download_result['page'] = page_num
                    all_results.append(download_result)
                    record(cand, page_num, download_result)
                    time.sleep(1)

                if is_stopped():
                    break
                if is_pause_requested():
                    break

                # 检测是否有下一页
                scroll_to_pagination(page)
                time.sleep(1)

                if not has_next_page(page):
                    break

                # 翻到下一页
                if not go_to_next_page(page):
                    break

                page_num += 1
        else:
            # 单页下载模式（只下载选中的候选人）
            for i, cand in enumerate(candidates, 1):
                if is_stopped():
                    break
                if is_pause_requested():
                    break

                if not ensure_browser_ready() or not refresh_page():
                    result['error'] = '浏览器断开且自动重连失败，任务已暂停'
                    result['paused'] = True
                    break
                if PageDetector.is_logged_in(page=page) == LoginStatus.EXPIRED:
                    result['error'] = '前程无忧登录状态已失效，任务已暂停，请重新登录后继续'
                    result['login_expired'] = True
                    break

                name = cand.get('name', '')
                if not name:
                    continue

                cand_status = get_candidate_status(cand)
                if cand_status in ('downloaded', 'ai_rejected'):
                    continue

                if tm and task_id:
                    try:
                        tm.mark_candidate_processing(task_id, candidate_ext_id(cand))
                    except Exception:
                        pass
                download_result = download_single_resume(
                    context, page, name, download_path, i, ai_config, job_name
                )
                # 失败重试一次（AI不通过不重试）
                if (not download_result.get('success')
                        and download_result.get('ai_pass') is not False):
                    time.sleep(2)
                    download_result = download_single_resume(
                        context, page, name, download_path, i, ai_config, job_name
                    )
                download_result['page'] = 1
                all_results.append(download_result)
                record(cand, 1, download_result)
                time.sleep(1)

        result['results'] = all_results
        result['total_pages'] = page_num
        result['current_page'] = page_num
        result['success'] = True
        result['paused'] = is_pause_requested() or is_stopped() or bool(result.get('paused'))

        manager.close()

    except Exception as e:
        result['error'] = str(e)

    return result


def collect_all_candidates_with_scroll(page):
    """滚动获取当前页所有候选人（含学校/专业/学历信息）"""
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

                    const nameEl = item.querySelector('.detail .firstline .name')
                        || item.querySelector('.name');
                    if (nameEl) {
                        name = nameEl.textContent.trim();
                    }

                    const schoolEl = item.querySelector('.school_name');
                    if (schoolEl) {
                        school = schoolEl.textContent.trim();
                    }

                    const majorEl = item.querySelector('.major_name');
                    if (majorEl) {
                        major = majorEl.textContent.trim();
                    }

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
        for candidate in current:
            name = candidate['name']
            if name not in seen:
                seen.add(name)
                all_candidates.append(candidate)
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

    return all_candidates


def scroll_to_pagination(page):
    """滚动到分页控件"""
    try:
        page.mouse.move(600, 400)
        time.sleep(0.3)
    except Exception:
        pass

    for i in range(20):
        page.mouse.wheel(0, 600)
        time.sleep(0.5)

    time.sleep(1)


def has_next_page(page):
    """检查是否有下一页"""
    try:
        result = page.evaluate('''() => {
            const nextBtn = document.querySelector('.eh-pagination__next.btn-next, .eh-pagination .btn-next');
            if (!nextBtn) return false;
            return !(nextBtn.disabled || nextBtn.hasAttribute('disabled'));
        }''')
        return result
    except Exception:
        return False


def go_to_next_page(page):
    """点击下一页"""
    try:
        old_first = page.evaluate('''() => {
            const items = document.querySelectorAll('.item.virtual_list');
            if (items.length === 0) return '';
            const nameEl = items[0].querySelector('.detail .firstline .name');
            return nameEl ? nameEl.textContent.trim() : '';
        }''')

        clicked = page.evaluate('''() => {
            const nextBtn = document.querySelector('.eh-pagination__next.btn-next, .eh-pagination .btn-next');
            if (!nextBtn) return false;
            nextBtn.click();
            return true;
        }''')

        if not clicked:
            return False

        # 等待页面刷新
        for wait in range(30):
            time.sleep(1)

            new_first = page.evaluate('''() => {
                const items = document.querySelectorAll('.item.virtual_list');
                if (items.length === 0) return '';
                const nameEl = items[0].querySelector('.detail .firstline .name');
                return nameEl ? nameEl.textContent.trim() : '';
            }''')

            if new_first and new_first != old_first:
                return True

        return False
    except Exception:
        return False


def download_single_resume(context, page, candidate_name, download_dir, index, ai_config=None, job_name=""):
    """下载单个候选人简历"""
    result = {"success": False, "name": candidate_name, "file_path": "", "error": "", "ai_pass": None}

    try:
        # 查找候选人元素
        element = find_candidate_by_name(page, candidate_name)
        if not element:
            result["error"] = "元素未找到"
            return result

        # 滚动到该元素
        try:
            element.scroll_into_view_if_needed(timeout=5000)
            time.sleep(0.5)
        except Exception:
            pass

        # 点击候选人：优先用 expect_popup 捕获新标签页/弹窗；
        # 兼容同页跳转（SPA）与姓名元素点击
        pages_before = len(context.pages)
        url_before = page.url
        detail_page = None

        try:
            with page.expect_popup(timeout=8000) as popup_info:
                element.click()
            detail_page = popup_info.value
        except Exception:
            pass

        # 未捕获到弹窗：等待新页面或同页跳转
        for _ in range(16):
            if detail_page is not None:
                break
            time.sleep(0.5)
            if len(context.pages) > pages_before:
                detail_page = context.pages[-1]
                break
            try:
                if page.url != url_before:      # 同页跳转（SPA 打开详情）
                    detail_page = page
                    break
            except Exception:
                pass

        if detail_page is None:
            # 兜底：点击姓名元素（部分页面点击行为挂在姓名上）
            try:
                name_el = find_name_element(page, candidate_name)
                if name_el:
                    name_el.click()
                    for _ in range(12):
                        time.sleep(0.5)
                        if len(context.pages) > pages_before:
                            detail_page = context.pages[-1]
                            break
                        try:
                            if page.url != url_before:
                                detail_page = page
                                break
                        except Exception:
                            pass
            except Exception:
                pass

        if detail_page is None:
            # 兜底：当前页已异步渲染成详情
            try:
                has_detail = page.evaluate('''() => {
                    const q = (s) => !!document.querySelector(s);
                    return q('.attach_resume_item') || q('#attachment') ||
                           !!(document.body && document.body.innerText.includes('附件个人信息'));
                }''')
                if has_detail:
                    detail_page = page
            except Exception:
                pass

        if detail_page is None:
            try:
                cur_url = page.url
                cur_title = page.title()
            except Exception:
                cur_url = cur_title = ''
            result["error"] = f"未打开新标签页（url={cur_url[:90]} title={cur_title[:40]}）"
            return result

        # 尝试查找附件个人信息入口（页面异步加载，最多等12秒）
        attachment_btn = find_attachment_button(detail_page, timeout=12)

        if not attachment_btn:
            # 保存页面诊断信息，并把诊断摘要直接带回结果
            diag = save_attachment_debug(detail_page, candidate_name)
            result["error"] = f"未找到附件按钮（诊断: {diag}）"
            detail_page.close()
            return result

        # 点击附件按钮
        pages_before_attach = len(context.pages)
        attachment_btn.click()
        time.sleep(2)

        pages_after = context.pages

        if len(pages_after) > pages_before_attach:
            attach_page = pages_after[-1]

            # 等待下载按钮出现
            download_selectors = [
                '.btn_item_download .download_a',
                '.download_a',
                'a.download_a',
                '[class*="download"] a',
                'a:has-text("下载")',
                '.btn_item:has-text("下载")',
            ]
            download_btn = wait_for_element(attach_page, download_selectors, timeout=15)

            # AI 筛选
            if download_btn and ai_config and ai_config.get("enabled"):
                resume_text = read_resume_text(attach_page)
                if resume_text:
                    eval_result = evaluate_resume(
                        resume_text,
                        ai_config.get("match_description", ""),
                        ai_config.get("api_key", "")
                    )
                    result["ai_pass"] = eval_result.get("match", True)
                    result["ai_reason"] = eval_result.get("reason", "")
                    if not eval_result.get("match", True):
                        result["error"] = f"AI不通过: {eval_result.get('reason', '')}"
                        attach_page.close()
                        time.sleep(0.5)
                        detail_page.close()
                        time.sleep(0.5)
                        return result

            if download_btn:
                try:
                    with attach_page.expect_download(timeout=20000) as download_info:
                        download_btn.click()

                    download = download_info.value
                    suggested_name = download.suggested_filename

                    if suggested_name:
                        ext = Path(suggested_name).suffix or '.pdf'
                        filename = f"51job-{candidate_name}_{job_name}{ext}"
                    else:
                        filename = f"51job-{candidate_name}_{job_name}.pdf"

                    file_path = download_dir / filename
                    download.save_as(str(file_path))

                    result["success"] = True
                    result["file_path"] = str(file_path)

                except Exception as e:
                    result["error"] = f"下载失败: {e}"
            else:
                result["error"] = "未找到下载按钮"

            attach_page.close()
            time.sleep(0.5)

        else:
            # 弹窗模式
            download_selectors = [
                '.btn_item_download .download_a',
                '.download_a',
                'a.download_a',
                '[class*="download"] a',
            ]
            download_btn = wait_for_element(detail_page, download_selectors, timeout=10)

            # AI 筛选
            if download_btn and ai_config and ai_config.get("enabled"):
                resume_text = read_resume_text(detail_page)
                if resume_text:
                    eval_result = evaluate_resume(
                        resume_text,
                        ai_config.get("match_description", ""),
                        ai_config.get("api_key", "")
                    )
                    result["ai_pass"] = eval_result.get("match", True)
                    result["ai_reason"] = eval_result.get("reason", "")
                    if not eval_result.get("match", True):
                        result["error"] = f"AI不通过: {eval_result.get('reason', '')}"
                        detail_page.close()
                        time.sleep(0.5)
                        return result

            if download_btn:
                try:
                    with detail_page.expect_download(timeout=20000) as download_info:
                        download_btn.click()

                    download = download_info.value
                    suggested_name = download.suggested_filename

                    if suggested_name:
                        ext = Path(suggested_name).suffix or '.pdf'
                        filename = f"51job-{candidate_name}_{job_name}{ext}"
                    else:
                        filename = f"51job-{candidate_name}_{job_name}.pdf"

                    file_path = download_dir / filename
                    download.save_as(str(file_path))

                    result["success"] = True
                    result["file_path"] = str(file_path)

                except Exception as e:
                    result["error"] = f"下载失败: {e}"
            else:
                result["error"] = "未找到下载按钮"

        detail_page.close()
        time.sleep(0.5)

    except Exception as e:
        result["error"] = str(e)
        # 清理打开的页面
        try:
            while len(context.pages) > 1:
                context.pages[-1].close()
                time.sleep(0.5)
        except Exception:
            pass

    return result


def find_attachment_button(detail_page, timeout=12):
    """
    查找详情页“附件个人信息”入口。

    页面异步加载，最多轮询 timeout 秒；支持：
    - 真实结构：div.attach_resume_item（含图标 + 文本“附件个人信息”），优先返回该容器
    - 直接可见的文本元素
    - 文本位于隐藏 tooltip（Element UI el-tooltip）时，向上找可见的祖先触发元素
    """
    selectors = [
        '.attach_resume_item:has-text("附件个人信息")',
        '.attach_resume_item',
        'span:has-text("附件个人信息")',
        ':text("附件个人信息")',
        'span:text-is("附件个人信息")',
        '[title*="附件个人信息"]',
        '[aria-label*="附件个人信息"]',
        '.el-tooltip:has-text("附件个人信息")',
        '[class*="attachment"]:has-text("附件个人信息")',
    ]
    for _ in range(timeout):
        for sel in selectors:
            try:
                el = detail_page.query_selector(sel)
                if not el:
                    continue
                # 容器元素直接作为点击目标（图标+文本的父容器）
                if sel.startswith('.attach_resume_item'):
                    return el
                if el.is_visible():
                    return el
                # 文本元素不可见时，向上找可见的可点击祖先（tooltip 图标场景）
                try:
                    handle = el.evaluate_handle('''(el) => {
                        let p = el;
                        while (p) {
                            if (p.offsetParent !== null &&
                                ['DIV', 'IMG', 'A', 'BUTTON', 'SPAN'].includes(p.tagName)) {
                                return p;
                            }
                            p = p.parentElement;
                        }
                        return null;
                    }''')
                    ancestor = handle.as_element() if handle else None
                    if ancestor and ancestor.is_visible():
                        return ancestor
                except Exception:
                    pass
            except Exception:
                continue
        time.sleep(1)
    return None


def save_attachment_debug(detail_page, candidate_name) -> str:
    """
    附件入口未找到时，保存页面关键片段到 logs/，并返回诊断摘要。

    Returns:
        诊断摘要字符串（attach_item 数量 / 文本是否包含 / url / title）
    """
    try:
        import re as _re
        snippet = detail_page.evaluate('''() => {
            const parts = [];
            const attachItems = document.querySelectorAll('.attach_resume_item');
            parts.push('ATTACH_ITEMS: ' + attachItems.length);
            parts.push('ATTACH_ITEM_HTML: ' + (attachItems[0] ? attachItems[0].outerHTML.substring(0, 1500) : ''));
            const attach = document.querySelector('#attachment');
            if (attach) parts.push('ID_ATTACHMENT: ' + attach.outerHTML.substring(0, 4000));
            const tooltips = document.querySelectorAll('.el-tooltip, [class*="attachment"], [title*="附件"]');
            parts.push('TOOLTIPS: ' + Array.from(tooltips).slice(0, 10)
                .map(e => e.outerHTML.substring(0, 400)).join('\\n'));
            parts.push('URL: ' + location.href);
            parts.push('TEXT: ' + (document.body ? document.body.innerText.substring(0, 800) : ''));
            return parts.join('\\n-----\\n');
        }''')
        diag_parts = []
        if snippet:
            for line in snippet.splitlines()[:3]:
                diag_parts.append(line.split(':', 1)[0] + '=' + (line.split(':', 1)[1] if ':' in line else ''))
        try:
            url = detail_page.url or ''
            title = detail_page.title() or ''
        except Exception:
            url = title = ''
        summary = ' | '.join(diag_parts)
        summary += f" | url={url[:80]} | title={title[:40]}"

        debug_dir = BASE_DIR / "logs"
        debug_dir.mkdir(parents=True, exist_ok=True)
        safe = _re.sub(r'[\\/:*?"<>|]', '_', candidate_name or 'candidate')
        path = debug_dir / f"attachment_debug_{safe}.html"
        path.write_text(snippet or '', encoding="utf-8")
        print(f"      附件检测失败，诊断已保存: {path}")
        return summary
    except Exception:
        return "诊断生成失败"


def find_candidate_by_name(page, name):
    """根据姓名查找候选人元素"""
    try:
        index = page.evaluate('''(name) => {
            const items = document.querySelectorAll('.item.virtual_list');
            for (let i = 0; i < items.length; i++) {
                const nameEl = items[i].querySelector('.detail .firstline .name') || items[i].querySelector('.name');
                if (nameEl && nameEl.textContent.trim() === name) {
                    return i;
                }
            }
            return -1;
        }''', name)

        if index >= 0:
            items = page.query_selector_all('.item.virtual_list')
            if index < len(items):
                return items[index]
    except Exception:
        pass

    return None


def find_name_element(page, name):
    """根据姓名查找候选人姓名元素（点击兜底用）"""
    try:
        index = page.evaluate('''(name) => {
            const items = document.querySelectorAll('.item.virtual_list');
            for (let i = 0; i < items.length; i++) {
                const nameEl = items[i].querySelector('.detail .firstline .name') || items[i].querySelector('.name');
                if (nameEl && nameEl.textContent.trim() === name) {
                    return i;
                }
            }
            return -1;
        }''', name)
        if index >= 0:
            items = page.query_selector_all('.item.virtual_list')
            if index < len(items):
                return (
                    items[index].query_selector('.detail .firstline .name')
                    or items[index].query_selector('.name')
                )
    except Exception:
        pass
    return None


def wait_for_element(page, selectors, timeout=15):
    """等待元素出现"""
    for _ in range(timeout):
        for sel in selectors:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    return el
            except Exception:
                continue
        time.sleep(1)
    return None


def read_resume_text(page):
    """读取简历文本"""
    try:
        text = page.evaluate('''() => {
            const selectors = [
                '.resume-content', '.resume-detail', '.resume-preview',
                '.attachment-content', '.file-content', '.pdf-content',
                '[class*="resume"]', '[class*="preview"]', '[class*="detail"]'
            ];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (el && el.innerText.trim().length > 100) {
                    return el.innerText.trim().substring(0, 8000);
                }
            }
            const body = document.body.innerText.trim();
            return body.substring(0, 8000);
        }''')
        return text
    except Exception:
        return ""


def evaluate_resume(resume_text, match_description, api_key):
    """调用AI评估简历"""
    from openai import OpenAI
    from config import MIMO_API_BASE, MIMO_MODEL

    client = OpenAI(api_key=api_key, base_url=MIMO_API_BASE)
    prompt = f"""你是一个专业的简历筛选助手。请根据以下岗位要求，判断候选人简历是否符合要求。

【岗位要求】
{match_description}

【候选人简历】
{resume_text}

请严格按以下 JSON 格式回复，不要输出其他内容：
{{"match": true/false, "reason": "简要说明原因（30字以内）"}}"""

    last_error = ""
    # MiMo 是推理模型：推理过程会消耗 token，max_tokens 太小会导致最终答案为空，
    # 这里加大额度并失败重试一次（推理 800 -> 2000）
    for attempt, max_tokens in enumerate([800, 2000]):
        try:
            completion = client.chat.completions.create(
                model=MIMO_MODEL,
                messages=[
                    {"role": "system", "content": "你是简历筛选助手，只输出JSON格式结果。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=max_tokens,
            )

            content = (completion.choices[0].message.content or "").strip()
            if not content:
                last_error = "模型未返回内容（推理过长）"
                continue
            if content.startswith("```"):
                content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            import json
            result = json.loads(content)
            return {"match": bool(result.get("match", False)),
                    "reason": str(result.get("reason", ""))}
        except Exception as e:
            last_error = str(e)
            continue

    return {"match": True, "reason": f"AI评估失败({last_error})，默认通过"}
