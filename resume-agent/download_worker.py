# -*- coding: utf-8 -*-
"""
下载操作进程 - 在独立进程中运行，支持分页下载和中断

Phase 4B-1：站点知识全部下沉到 SiteAdapter，浏览器操作经 BrowserDriver。
业务流程、重试次数、兜底顺序、异常处理与原实现逐行一致。
"""
import sys
import json
import time
from pathlib import Path
from datetime import datetime

from browser.actions import BrowserDriver

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
        pause_event: multiprocessing.Event，暂停请求（当前候选人完成后暂停）
        task_id: 任务ID（用于状态更新）
        db_path: 数据库路径（可选）
    """
    from browser.browser_manager import BrowserManager
    from sites import Site51Job
    from db.models import generate_candidate_external_id
    from task import TaskManager

    site = Site51Job()

    # 兼容旧调用：candidates 为纯名字列表
    if candidates and isinstance(candidates[0], str):
        candidates = [{'name': n} for n in candidates]

    tm = None
    if task_id:
        try:
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
            return generate_candidate_external_id(
                candidate.get('name', ''),
                candidate.get('school', '') or '',
                candidate.get('major', '') or '',
            )
        except Exception:
            return candidate.get('name', '') or ''

    def get_candidate_status(candidate):
        """获取候选人在任务中的当前状态"""
        if not tm or not task_id:
            return None
        try:
            ext_id = candidate_ext_id(candidate)
            c = tm.db.get_candidate_by_external_id(task_id, ext_id)
            return c.status if c else None
        except Exception:
            return None

    result = {
        'success': False,
        'results': [],
        'total_pages': 1,
        'current_page': 1,
        'error': ''
    }

    real_total_pages = 1
    page_num = 1
    all_results = []
    processed_count = 0
    success_count = 0
    failed_count = 0
    ai_pass_count = 0
    ai_fail_count = 0

    # 恢复任务时读取已处理计数
    if tm and task_id:
        try:
            t = tm.get_task(task_id)
            if t:
                processed_count = t.processed_count or 0
                success_count = t.success_count or 0
                failed_count = t.failed_count or 0
                ai_pass_count = t.ai_pass_count or 0
                ai_fail_count = t.ai_fail_count or 0
        except Exception:
            pass

    try:
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

        driver = BrowserDriver(page)

        # 登录检查（站点能力）
        if site.is_logged_in(driver) == 'expired':
            result['error'] = '前程无忧登录状态已失效，请重新登录'
            result['login_expired'] = True
            manager.close()
            return result

        def ensure_browser_ready():
            """确保浏览器可用，断开则重连"""
            if manager.health_check():
                return True
            return manager.reconnect()

        def refresh_page():
            """重新获取 page/context（页面可能被重连/跳转替换）"""
            nonlocal page, context, driver
            page = manager.get_page()
            context = manager.context
            if page is not None:
                driver = BrowserDriver(page)
            return page is not None and context is not None

        def check_page_ready():
            """检查当前页面状态：ok / expired / drifted / error"""
            try:
                page_type = site.detect_page(driver)
            except Exception:
                return 'error'
            if page_type == 'LOGIN_PAGE':
                return 'expired'
            if page_type not in ('CANDIDATE_LIST_PAGE', 'JOB_LIST_PAGE'):
                return 'drifted'
            return 'ok'

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
            # 单事务写入候选人结果 + 任务进度（问题11）；total_pages 用真实总页数（问题3）
            if tm and task_id:
                try:
                    tm.save_candidate_result(
                        task_id, candidate, page_no, download_result,
                        progress={
                            'processed_count': processed_count,
                            'success_count': success_count,
                            'failed_count': failed_count,
                            'ai_pass_count': ai_pass_count,
                            'ai_fail_count': ai_fail_count,
                            'current_page': page_num,
                            'total_pages': real_total_pages,
                        },
                    )
                except Exception:
                    pass

        def scroll_collect_and_process():
            """边滚动边收集并处理当前页候选人（问题2：避免回顶后 DOM 回收导致漏人）"""
            nonlocal page, driver, all_results
            global_index = 0
            seen = set()
            no_new_count = 0

            try:
                driver.mouse_move(600, 400)
                time.sleep(0.3)
            except Exception:
                pass

            for _round in range(100):
                if is_stopped() or is_pause_requested():
                    return False

                current = site.extract_candidates(driver)
                if current is None:
                    if not (ensure_browser_ready() and refresh_page()):
                        result['error'] = '浏览器断开且自动重连失败，任务已暂停'
                        result['paused'] = True
                        return False
                    current = site.extract_candidates(driver)
                    if current is None:
                        result['error'] = '页面读取失败，任务已暂停'
                        result['paused'] = True
                        return False

                new_count = 0
                for cand in current:
                    if is_stopped() or is_pause_requested():
                        return False
                    name = cand.get('name', '')
                    if not name or name in seen:
                        continue
                    seen.add(name)
                    new_count += 1

                    status = check_page_ready()
                    if status == 'expired':
                        result['error'] = '前程无忧登录状态已失效，任务已暂停，请重新登录后继续'
                        result['login_expired'] = True
                        return False
                    if status == 'drifted':
                        result['error'] = '页面已离开候选人列表，任务已暂停'
                        result['paused'] = True
                        return False
                    if status == 'error':
                        if not (ensure_browser_ready() and refresh_page()):
                            result['error'] = '浏览器断开且自动重连失败，任务已暂停'
                            result['paused'] = True
                            return False

                    cand_status = get_candidate_status(cand)
                    if cand_status in ('downloaded', 'ai_rejected'):
                        continue

                    if tm and task_id:
                        try:
                            tm.mark_candidate_processing(task_id, candidate_ext_id(cand))
                        except Exception:
                            pass

                    global_index += 1
                    download_result = download_single_resume(
                        driver, site, name, download_dir, global_index, ai_config, job_name
                    )
                    # 失败重试一次（AI明确不通过/页面无文本时不重试）
                    if (not download_result.get('success')
                            and download_result.get('ai_pass') is not False
                            and download_result.get('ai_retryable', True)):
                        time.sleep(2)
                        download_result = download_single_resume(
                            driver, site, name, download_dir, global_index, ai_config, job_name
                        )
                    download_result['page'] = page_num
                    all_results.append(download_result)
                    record(cand, page_num, download_result)
                    time.sleep(1)

                if new_count == 0:
                    no_new_count += 1
                else:
                    no_new_count = 0
                if no_new_count >= 3:
                    break

                try:
                    driver.scroll_wheel(0, 600)
                    time.sleep(1)
                except Exception:
                    break

            return True

        if download_all_pages:
            # 读取真实总页数（问题3：total_pages 修复）
            total = site.extract_pagination(driver).get('totalPages', 1)
            if total:
                real_total_pages = total

            # 每页从顶部开始收集（问题2：避免残留滚动位置导致漏掉顶部候选人）
            try:
                site.scroll_to_top(driver)
                time.sleep(0.5)
            except Exception:
                pass

            while not is_stopped():
                if not ensure_browser_ready() or not refresh_page():
                    result['error'] = '浏览器断开且自动重连失败，任务已暂停'
                    result['paused'] = True
                    break

                if not scroll_collect_and_process():
                    break

                if is_stopped() or is_pause_requested():
                    break

                # 检测是否有下一页
                site.scroll_to_pagination(driver)
                if not site.has_next_page(driver):
                    break
                if not site.go_to_next_page(driver):
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

                status = check_page_ready()
                if status == 'expired':
                    result['error'] = '前程无忧登录状态已失效，任务已暂停，请重新登录后继续'
                    result['login_expired'] = True
                    break
                if status == 'drifted':
                    result['error'] = '页面已离开候选人列表，任务已暂停'
                    result['paused'] = True
                    break
                if status == 'error':
                    if not (ensure_browser_ready() and refresh_page()):
                        result['error'] = '浏览器断开且自动重连失败，任务已暂停'
                        result['paused'] = True
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
                    driver, site, name, download_dir, i, ai_config, job_name
                )
                # 失败重试一次（AI明确不通过/页面无文本时不重试）
                if (not download_result.get('success')
                        and download_result.get('ai_pass') is not False
                        and download_result.get('ai_retryable', True)):
                    time.sleep(2)
                    download_result = download_single_resume(
                        driver, site, name, download_dir, i, ai_config, job_name
                    )
                download_result['page'] = 1
                all_results.append(download_result)
                record(cand, 1, download_result)
                time.sleep(1)

        result['results'] = all_results
        result['total_pages'] = real_total_pages
        result['current_page'] = page_num
        result['success'] = True
        result['paused'] = is_pause_requested() or is_stopped() or bool(result.get('paused'))

        manager.close()

    except Exception as e:
        result['error'] = str(e)

    return result


def download_single_resume(driver, site, candidate_name, download_dir, index,
                           ai_config=None, job_name=""):
    """下载单个候选人简历（打开详情 -> 附件 -> AI 判断 -> 下载，流程与原实现一致）"""
    result = {"success": False, "name": candidate_name, "file_path": "", "error": "", "ai_pass": None}

    def ai_check(page_driver):
        """AI 评估：通过返回 True；不通过/无法评估返回 False（结果写入 result）"""
        resume_text = site.extract_resume_text(page_driver)
        if not resume_text:
            result["ai_pass"] = None
            result["ai_reason"] = "无法读取简历文本"
            result["error"] = "无法读取简历文本，AI筛选跳过（待人工确认）"
            result["ai_retryable"] = False  # 页面本身无文本，重试无意义
            return False
        eval_result = evaluate_resume(
            resume_text,
            ai_config.get("match_description", ""),
            ai_config.get("api_key", "")
        )
        result["ai_pass"] = eval_result.get("match")
        result["ai_reason"] = eval_result.get("reason", "")
        if eval_result.get("match") is False:
            result["error"] = f"AI不通过: {eval_result.get('reason', '')}"
            return False
        if eval_result.get("match") is None:
            result["error"] = f"AI评估失败，跳过下载（待人工确认）: {eval_result.get('reason', '')}"
            return False
        return True

    try:
        # 定位候选人元素（站点能力）
        element = site.find_candidate_by_name(driver, candidate_name)
        if not element:
            result["error"] = "元素未找到"
            return result

        # 尝试多种方式打开简历详情（流程与原实现逐行一致）
        detail_page = None
        try:
            time.sleep(0.5)
        except Exception:
            pass

        pages_before = len(driver.context_pages())
        url_before = driver.page_url()
        try:
            with driver.expect_popup(timeout=5000) as popup_info:
                element.click()
        except Exception:
            pass

        for _ in range(8):
            if detail_page is not None:
                break
            time.sleep(0.5)
            if len(driver.context_pages()) > pages_before:
                detail_page = driver.context_pages()[-1]

        try:
            if driver.page_url() != url_before:      # 同页跳转（SPA 打开详情）
                detail_page = driver.page
        except Exception:
            pass

        if detail_page is None:
            # 点击姓名字素
            try:
                name_el = site.find_name_element(driver, candidate_name)
                if name_el:
                    name_el.click()
                    for _ in range(8):
                        time.sleep(0.5)
                        if len(driver.context_pages()) > pages_before:
                            detail_page = driver.context_pages()[-1]
                    try:
                        if driver.page_url() != url_before:
                            detail_page = driver.page
                    except Exception:
                        pass
            except Exception:
                pass

        if detail_page is None:
            # 检查当前页是否已有附件入口（同页详情）
            try:
                has_detail = driver.query_selector(site.selector('attachment_btn'))
                if has_detail:
                    detail_page = driver.page
            except Exception:
                pass

        if detail_page is None:
            try:
                cur_url = driver.page_url()
                cur_title = driver.page_title()
            except Exception:
                cur_url = ''
                cur_title = ''
            result["error"] = f"未打开新标签页（url={cur_url[:90]} title={cur_title[:40]}）"
            return result

        detail_driver = BrowserDriver(detail_page)

        # 找附件按钮（站点能力）
        attachment_btn = site.find_attachment_button(detail_driver, timeout=12)
        if not attachment_btn:
            diag = save_attachment_debug(detail_driver, site, candidate_name)
            result["error"] = f"未找到附件按钮（诊断: {diag}）"
            driver.close_page(detail_page)
            return result

        # 打开附件页
        pages_before_attach = len(driver.context_pages())
        pages_after = driver.context_pages()
        try:
            attachment_btn.click()
        except Exception:
            pass
        for _ in range(10):
            if len(driver.context_pages()) > pages_before_attach:
                pages_after = driver.context_pages()
                break
            time.sleep(0.5)

        if len(pages_after) > pages_before_attach:
            # 附件页打开成功
            attach_page = pages_after[-1]
            attach_driver = BrowserDriver(attach_page)
            download_btn = site.find_download_button(attach_driver, timeout=15)
            if download_btn and ai_config and ai_config.get("enabled"):
                if not ai_check(attach_driver):
                    driver.close_page(attach_page)
                    time.sleep(0.5)
                    driver.close_page(detail_page)
                    time.sleep(0.5)
                    return result
            if download_btn:
                try:
                    with attach_driver.expect_download(timeout=20000) as download_info:
                        download_btn.click()
                    download = download_info.value
                    suggested_name = download.suggested_filename
                    if suggested_name:
                        filename = suggested_name
                    else:
                        ext = '.pdf'
                        filename = f"{candidate_name}_{index}{ext}"
                    file_path = Path(download_dir) / filename
                    download.save_as(str(file_path))
                    result["success"] = True
                    result["file_path"] = str(file_path)
                except Exception as e:
                    result["error"] = f"下载失败: {e}"
            else:
                result["error"] = "未找到下载按钮"
            driver.close_page(attach_page)
            time.sleep(0.5)
        else:
            # 附件页未打开，直接在当前详情页找下载按钮（兜底）
            download_btn = site.find_download_button(detail_driver, timeout=10)
            if download_btn and ai_config and ai_config.get("enabled"):
                if not ai_check(detail_driver):
                    driver.close_page(detail_page)
                    time.sleep(0.5)
                    return result
            if download_btn:
                try:
                    with detail_driver.expect_download(timeout=20000) as download_info:
                        download_btn.click()
                    download = download_info.value
                    suggested_name = download.suggested_filename
                    if suggested_name:
                        filename = suggested_name
                    else:
                        ext = '.pdf'
                        filename = f"{candidate_name}_{index}{ext}"
                    file_path = Path(download_dir) / filename
                    download.save_as(str(file_path))
                    result["success"] = True
                    result["file_path"] = str(file_path)
                except Exception as e:
                    result["error"] = f"下载失败: {e}"
            else:
                result["error"] = "未找到下载按钮"
            driver.close_page(detail_page)
            time.sleep(0.5)

    except Exception as e:
        result["error"] = str(e)

    # 清理多余页面（保留主页面）
    try:
        while len(driver.context_pages()) > 1:
            driver.close_page(driver.context_pages()[-1])
            time.sleep(0.5)
    except Exception:
        pass

    return result


def save_attachment_debug(driver, site, candidate_name) -> str:
    """附件入口未找到时，保存页面关键片段到 logs/，并返回诊断摘要"""
    try:
        import re as _re
        # 收集附件相关元素（站点 selector 由 SiteAdapter 提供）
        attach_els = driver.query_selector_all(site.selector('attachment_btn'))
        snippet_parts = []
        snippet_parts.append(f"ATTACH_ITEMS: {len(attach_els)}")
        if attach_els:
            try:
                snippet_parts.append("ATTACH_ITEM_HTML: " + attach_els[0].inner_html()[:1500])
            except Exception:
                pass
        body_text = ''
        try:
            body_text = driver.evaluate("() => document.body ? document.body.innerText.substring(0, 800) : ''") or ''
        except Exception:
            pass
        snippet_parts.append("URL: " + driver.page_url())
        snippet_parts.append("TEXT: " + str(body_text)[:800])
        snippet = "\n-----\n".join(snippet_parts)

        diag_parts = []
        if snippet:
            for line in snippet.splitlines()[:3]:
                key = line.split(':', 1)[0]
                val = line.split(':', 1)[1] if ':' in line else ''
                diag_parts.append(f"{key}={val}")
        try:
            url = driver.page_url()
            title = driver.page_title()
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


def evaluate_resume(resume_text, match_description, api_key):
    """调用AI评估简历"""
    from openai import OpenAI
    from config import MIMO_API_BASE, MIMO_MODEL

    # 问题5：设置请求超时，避免单个候选长时间挂起导致“中断”失灵
    client = OpenAI(api_key=api_key, base_url=MIMO_API_BASE, timeout=60)
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
                timeout=60,
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

    # 问题5：评估失败不再默认放行，标记 unknown 由上层跳过并记录
    return {"match": None, "reason": f"AI评估失败({last_error})"}
