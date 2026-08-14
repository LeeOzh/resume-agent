# -*- coding: utf-8 -*-
"""
ResumeDownloadWorkflow - 简历下载工作流（Phase 4B-2）。

从 download_worker.run() 机械拆分而来：候选人处理/翻页/简历详情/附件/AI 判断/
下载编排/TaskManager 状态/stop-pause/结果组装。

边界：
- 浏览器生命周期由 Worker 壳负责（经 browser_ready / refresh_driver 回调协作）
- 站点知识经 SiteAdapter
- 浏览器操作经 BrowserDriver
- TaskManager 写库属领域逻辑，Workflow 调用
"""
import time
from pathlib import Path

from db.models import generate_candidate_external_id


class ResumeDownloadWorkflow:
    def __init__(self, driver, site, task_manager=None, stop_event=None,
                 pause_event=None, ai_config=None, browser_ready=None,
                 refresh_driver=None):
        """
        Args:
            driver: BrowserDriver（已就绪）
            site: SiteAdapter
            task_manager: TaskManager（可选）
            stop_event / pause_event: multiprocessing.Event
            ai_config: AI 配置（可选）
            browser_ready: 回调，返回浏览器是否可用（重连由 Worker 壳负责）
            refresh_driver: 回调，返回最新 BrowserDriver（page 变化后重建）
        """
        self.driver = driver
        self.site = site
        self.tm = task_manager
        self.stop_event = stop_event
        self.pause_event = pause_event
        self.ai_config = ai_config
        self.browser_ready = browser_ready or (lambda: True)
        self.refresh_driver = refresh_driver or (lambda: self.driver)

        self.result = {
            'success': False,
            'results': [],
            'total_pages': 1,
            'current_page': 1,
            'error': '',
        }
        self.real_total_pages = 1
        self.page_num = 1
        self.all_results = []
        self.processed_count = 0
        self.success_count = 0
        self.failed_count = 0
        self.ai_pass_count = 0
        self.ai_fail_count = 0

    # ==================== 控制 ====================

    def is_stopped(self) -> bool:
        return self.stop_event is not None and self.stop_event.is_set()

    def is_pause_requested(self) -> bool:
        return self.pause_event is not None and self.pause_event.is_set()

    def candidate_ext_id(self, candidate):
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

    def get_candidate_status(self, candidate):
        if not self.tm or not self._task_id:
            return None
        try:
            ext_id = self.candidate_ext_id(candidate)
            c = self.tm.db.get_candidate_by_external_id(self._task_id, ext_id)
            return c.status if c else None
        except Exception:
            return None

    # ==================== 浏览器就绪（经回调协作，生命周期归 Worker 壳） ====================

    def ensure_browser_ready(self):
        return self.browser_ready()

    def refresh_page(self):
        new_driver = self.refresh_driver()
        if new_driver is not None:
            self.driver = new_driver
            return True
        return False

    def check_page_ready(self):
        """检查当前页面状态：ok / expired / drifted / error"""
        try:
            page_type = self.site.detect_page(self.driver)
        except Exception:
            return 'error'
        if page_type == 'LOGIN_PAGE':
            return 'expired'
        if page_type not in ('CANDIDATE_LIST_PAGE', 'JOB_LIST_PAGE'):
            return 'drifted'
        return 'ok'

    # ==================== 结果记录 ====================

    def record(self, candidate, page_no, download_result):
        """统计并持久化单个候选人的处理结果"""
        self.processed_count += 1
        if download_result.get('success'):
            self.success_count += 1
        else:
            self.failed_count += 1
        if download_result.get('ai_pass') is True:
            self.ai_pass_count += 1
        elif download_result.get('ai_pass') is False:
            self.ai_fail_count += 1
        # 单事务写入候选人结果 + 任务进度（问题11）；total_pages 用真实总页数（问题3）
        if self.tm and self._task_id:
            try:
                self.tm.save_candidate_result(
                    self._task_id, candidate, page_no, download_result,
                    progress={
                        'processed_count': self.processed_count,
                        'success_count': self.success_count,
                        'failed_count': self.failed_count,
                        'ai_pass_count': self.ai_pass_count,
                        'ai_fail_count': self.ai_fail_count,
                        'current_page': self.page_num,
                        'total_pages': self.real_total_pages,
                    },
                )
            except Exception:
                pass

    # ==================== 主流程 ====================

    def run(self, candidates, download_dir, job_name='', task_id=None,
            download_all_pages=False):
        """执行下载流程（从 download_worker.run 机械迁移，行为不变）"""
        self._task_id = task_id

        # 兼容旧调用：candidates 为纯名字列表
        if candidates and isinstance(candidates[0], str):
            candidates = [{'name': n} for n in candidates]

        # 恢复任务时读取已处理计数
        if self.tm and task_id:
            try:
                t = self.tm.get_task(task_id)
                if t:
                    self.processed_count = t.processed_count or 0
                    self.success_count = t.success_count or 0
                    self.failed_count = t.failed_count or 0
                    self.ai_pass_count = t.ai_pass_count or 0
                    self.ai_fail_count = t.ai_fail_count or 0
            except Exception:
                pass

        # 登录检查（站点能力）
        if self.site.is_logged_in(self.driver) == 'expired':
            self.result['error'] = '前程无忧登录状态已失效，请重新登录'
            self.result['login_expired'] = True
            return self.result

        def scroll_collect_and_process():
            """边滚动边收集并处理当前页候选人（问题2：避免回顶后 DOM 回收导致漏人）"""
            global_index = 0
            seen = set()
            no_new_count = 0

            try:
                self.driver.mouse_move(600, 400)
                time.sleep(0.3)
            except Exception:
                pass

            for _round in range(100):
                if self.is_stopped() or self.is_pause_requested():
                    return False

                current = self.site.extract_candidates(self.driver)
                if current is None:
                    if not (self.ensure_browser_ready() and self.refresh_page()):
                        self.result['error'] = '浏览器断开且自动重连失败，任务已暂停'
                        self.result['paused'] = True
                        return False
                    current = self.site.extract_candidates(self.driver)
                    if current is None:
                        self.result['error'] = '页面读取失败，任务已暂停'
                        self.result['paused'] = True
                        return False

                new_count = 0
                for cand in current:
                    if self.is_stopped() or self.is_pause_requested():
                        return False
                    name = cand.get('name', '')
                    if not name or name in seen:
                        continue
                    seen.add(name)
                    new_count += 1

                    status = self.check_page_ready()
                    if status == 'expired':
                        self.result['error'] = '前程无忧登录状态已失效，任务已暂停，请重新登录后继续'
                        self.result['login_expired'] = True
                        return False
                    if status == 'drifted':
                        self.result['error'] = '页面已离开候选人列表，任务已暂停'
                        self.result['paused'] = True
                        return False
                    if status == 'error':
                        if not (self.ensure_browser_ready() and self.refresh_page()):
                            self.result['error'] = '浏览器断开且自动重连失败，任务已暂停'
                            self.result['paused'] = True
                            return False

                    cand_status = self.get_candidate_status(cand)
                    if cand_status in ('downloaded', 'ai_rejected'):
                        continue

                    if self.tm and task_id:
                        try:
                            self.tm.mark_candidate_processing(task_id, self.candidate_ext_id(cand))
                        except Exception:
                            pass

                    global_index += 1
                    download_result = self.download_single_resume(
                        name, download_dir, global_index, job_name
                    )
                    # 失败重试一次（AI明确不通过/页面无文本时不重试）
                    if (not download_result.get('success')
                            and download_result.get('ai_pass') is not False
                            and download_result.get('ai_retryable', True)):
                        time.sleep(2)
                        download_result = self.download_single_resume(
                            name, download_dir, global_index, job_name
                        )
                    download_result['page'] = self.page_num
                    self.all_results.append(download_result)
                    self.record(cand, self.page_num, download_result)
                    time.sleep(1)

                if new_count == 0:
                    no_new_count += 1
                else:
                    no_new_count = 0
                if no_new_count >= 3:
                    break

                try:
                    self.driver.scroll_wheel(0, 600)
                    time.sleep(1)
                except Exception:
                    break

            return True

        if download_all_pages:
            # 读取真实总页数（问题3：total_pages 修复）
            total = self.site.extract_pagination(self.driver).get('totalPages', 1)
            if total:
                self.real_total_pages = total

            # 每页从顶部开始收集（问题2：避免残留滚动位置导致漏掉顶部候选人）
            try:
                self.site.scroll_to_top(self.driver)
                time.sleep(0.5)
            except Exception:
                pass

            while not self.is_stopped():
                if not self.ensure_browser_ready() or not self.refresh_page():
                    self.result['error'] = '浏览器断开且自动重连失败，任务已暂停'
                    self.result['paused'] = True
                    break

                if not scroll_collect_and_process():
                    break

                if self.is_stopped() or self.is_pause_requested():
                    break

                # 检测是否有下一页
                self.site.scroll_to_pagination(self.driver)
                if not self.site.has_next_page(self.driver):
                    break
                if not self.site.go_to_next_page(self.driver):
                    break
                self.page_num += 1
        else:
            # 单页下载模式（只下载选中的候选人）
            for i, cand in enumerate(candidates, 1):
                if self.is_stopped():
                    break
                if self.is_pause_requested():
                    break

                if not self.ensure_browser_ready() or not self.refresh_page():
                    self.result['error'] = '浏览器断开且自动重连失败，任务已暂停'
                    self.result['paused'] = True
                    break

                status = self.check_page_ready()
                if status == 'expired':
                    self.result['error'] = '前程无忧登录状态已失效，任务已暂停，请重新登录后继续'
                    self.result['login_expired'] = True
                    break
                if status == 'drifted':
                    self.result['error'] = '页面已离开候选人列表，任务已暂停'
                    self.result['paused'] = True
                    break
                if status == 'error':
                    if not (self.ensure_browser_ready() and self.refresh_page()):
                        self.result['error'] = '浏览器断开且自动重连失败，任务已暂停'
                        self.result['paused'] = True
                        break

                name = cand.get('name', '')
                if not name:
                    continue

                cand_status = self.get_candidate_status(cand)
                if cand_status in ('downloaded', 'ai_rejected'):
                    continue

                if self.tm and task_id:
                    try:
                        self.tm.mark_candidate_processing(task_id, self.candidate_ext_id(cand))
                    except Exception:
                        pass

                download_result = self.download_single_resume(
                    name, download_dir, i, job_name
                )
                # 失败重试一次（AI明确不通过/页面无文本时不重试）
                if (not download_result.get('success')
                        and download_result.get('ai_pass') is not False
                        and download_result.get('ai_retryable', True)):
                    time.sleep(2)
                    download_result = self.download_single_resume(
                        name, download_dir, i, job_name
                    )
                download_result['page'] = 1
                self.all_results.append(download_result)
                self.record(cand, 1, download_result)
                time.sleep(1)

        self.result['results'] = self.all_results
        self.result['total_pages'] = self.real_total_pages
        self.result['current_page'] = self.page_num
        self.result['success'] = True
        self.result['paused'] = (self.is_pause_requested() or self.is_stopped()
                                 or bool(self.result.get('paused')))
        return self.result

    # ==================== 单候选人下载（打开详情 -> 附件 -> AI -> 下载） ====================

    def download_single_resume(self, candidate_name, download_dir, index, job_name=""):
        """下载单个候选人简历（流程与原实现逐行一致）"""
        from browser.actions import BrowserDriver

        result = {"success": False, "name": candidate_name, "file_path": "",
                  "error": "", "ai_pass": None}

        def ai_check(page_driver):
            """AI 评估：通过返回 True；不通过/无法评估返回 False（结果写入 result）"""
            resume_text = self.site.extract_resume_text(page_driver)
            if not resume_text:
                result["ai_pass"] = None
                result["ai_reason"] = "无法读取简历文本"
                result["error"] = "无法读取简历文本，AI筛选跳过（待人工确认）"
                result["ai_retryable"] = False  # 页面本身无文本，重试无意义
                return False
            eval_result = evaluate_resume(
                resume_text,
                self.ai_config.get("match_description", ""),
                self.ai_config.get("api_key", "")
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
            element = self.site.find_candidate_by_name(self.driver, candidate_name)
            if not element:
                result["error"] = "元素未找到"
                return result

            # 尝试多种方式打开简历详情（流程与原实现逐行一致）
            detail_page = None
            try:
                time.sleep(0.5)
            except Exception:
                pass

            pages_before = len(self.driver.context_pages())
            url_before = self.driver.page_url()
            try:
                with self.driver.expect_popup(timeout=5000) as popup_info:
                    element.click()
            except Exception:
                pass

            for _ in range(8):
                if detail_page is not None:
                    break
                time.sleep(0.5)
                if len(self.driver.context_pages()) > pages_before:
                    detail_page = self.driver.context_pages()[-1]

            try:
                if self.driver.page_url() != url_before:      # 同页跳转（SPA 打开详情）
                    detail_page = self.driver.page
            except Exception:
                pass

            if detail_page is None:
                # 点击姓名字素
                try:
                    name_el = self.site.find_name_element(self.driver, candidate_name)
                    if name_el:
                        name_el.click()
                        for _ in range(8):
                            time.sleep(0.5)
                            if len(self.driver.context_pages()) > pages_before:
                                detail_page = self.driver.context_pages()[-1]
                        try:
                            if self.driver.page_url() != url_before:
                                detail_page = self.driver.page
                        except Exception:
                            pass
                except Exception:
                    pass

            if detail_page is None:
                # 检查当前页是否已有附件入口（同页详情）
                try:
                    has_detail = self.driver.query_selector(self.site.selector('attachment_btn'))
                    if has_detail:
                        detail_page = self.driver.page
                except Exception:
                    pass

            if detail_page is None:
                try:
                    cur_url = self.driver.page_url()
                    cur_title = self.driver.page_title()
                except Exception:
                    cur_url = ''
                    cur_title = ''
                result["error"] = f"未打开新标签页（url={cur_url[:90]} title={cur_title[:40]}）"
                return result

            detail_driver = BrowserDriver(detail_page)

            # 找附件按钮（站点能力）
            attachment_btn = self.site.find_attachment_button(detail_driver, timeout=12)
            if not attachment_btn:
                diag = save_attachment_debug(detail_driver, self.site, candidate_name)
                result["error"] = f"未找到附件按钮（诊断: {diag}）"
                self.driver.close_page(detail_page)
                return result

            # 打开附件页
            pages_before_attach = len(self.driver.context_pages())
            pages_after = self.driver.context_pages()
            try:
                attachment_btn.click()
            except Exception:
                pass
            for _ in range(10):
                if len(self.driver.context_pages()) > pages_before_attach:
                    pages_after = self.driver.context_pages()
                    break
                time.sleep(0.5)

            if len(pages_after) > pages_before_attach:
                # 附件页打开成功
                attach_page = pages_after[-1]
                attach_driver = BrowserDriver(attach_page)
                download_btn = self.site.find_download_button(attach_driver, timeout=15)
                if download_btn and self.ai_config and self.ai_config.get("enabled"):
                    if not ai_check(attach_driver):
                        self.driver.close_page(attach_page)
                        time.sleep(0.5)
                        self.driver.close_page(detail_page)
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
                self.driver.close_page(attach_page)
                time.sleep(0.5)
            else:
                # 附件页未打开，直接在当前详情页找下载按钮（兜底）
                download_btn = self.site.find_download_button(detail_driver, timeout=10)
                if download_btn and self.ai_config and self.ai_config.get("enabled"):
                    if not ai_check(detail_driver):
                        self.driver.close_page(detail_page)
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
                self.driver.close_page(detail_page)
                time.sleep(0.5)

        except Exception as e:
            result["error"] = str(e)

        # 清理多余页面（保留主页面）
        try:
            while len(self.driver.context_pages()) > 1:
                self.driver.close_page(self.driver.context_pages()[-1])
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

        import sys
        from pathlib import Path as _Path
        if getattr(sys, 'frozen', False):
            base = _Path(sys.executable).parent
        else:
            base = _Path(__file__).parent.parent
        debug_dir = base / "logs"
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
