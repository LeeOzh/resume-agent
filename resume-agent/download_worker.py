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


def run(candidate_names, download_dir, job_name='', ai_config=None, 
        download_all_pages=False, stop_event=None):
    """
    执行下载操作
    
    Args:
        candidate_names: 候选人姓名列表
        download_dir: 下载目录
        job_name: 职位名称
        ai_config: AI配置
        download_all_pages: 是否下载所有页
        stop_event: multiprocessing.Event，用于跨进程中断
    """
    from playwright.sync_api import sync_playwright
    from config import CHROME_DEBUG_PORT

    def is_stopped():
        """检查是否已停止"""
        return stop_event is not None and stop_event.is_set()

    result = {
        'success': False,
        'results': [],
        'total_pages': 1,
        'current_page': 1,
        'error': ''
    }

    try:
        # 检测端口
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        port_open = sock.connect_ex(('127.0.0.1', CHROME_DEBUG_PORT)) == 0
        sock.close()

        if not port_open:
            result['error'] = f'调试端口 {CHROME_DEBUG_PORT} 未开放'
            return result

        # 连接浏览器
        pw = sync_playwright().start()
        browser = pw.chromium.connect_over_cdp(f'http://localhost:{CHROME_DEBUG_PORT}')

        contexts = browser.contexts
        if not contexts:
            result['error'] = '未找到浏览器上下文'
            pw.stop()
            return result

        context = contexts[0]
        pages = context.pages

        if not pages:
            result['error'] = '未找到打开的页面'
            pw.stop()
            return result

        page = pages[-1]

        # 创建下载目录
        download_path = Path(download_dir)
        download_path.mkdir(parents=True, exist_ok=True)

        all_results = []
        page_num = 1
        global_index = 0

        if download_all_pages:
            # 分页下载模式
            while not is_stopped():
                # 收集当前页候选人
                current_names = collect_all_candidates_with_scroll(page)
                if not current_names:
                    break

                # 滚动回顶部
                page.keyboard.press('Home')
                time.sleep(1)

                # 逐个下载当前页
                for name in current_names:
                    if is_stopped():
                        break

                    global_index += 1
                    download_result = download_single_resume(
                        context, page, name, download_path, global_index, ai_config, job_name
                    )
                    download_result['page'] = page_num
                    all_results.append(download_result)
                    time.sleep(1)

                if is_stopped():
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
            for i, name in enumerate(candidate_names, 1):
                if is_stopped():
                    break

                download_result = download_single_resume(
                    context, page, name, download_path, i, ai_config, job_name
                )
                download_result['page'] = 1
                all_results.append(download_result)
                time.sleep(1)

        result['results'] = all_results
        result['total_pages'] = page_num
        result['current_page'] = page_num
        result['success'] = True

        pw.stop()

    except Exception as e:
        result['error'] = str(e)

    return result


def collect_all_candidates_with_scroll(page):
    """滚动获取当前页所有候选人"""
    all_names = []
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
                const names = [];
                items.forEach(item => {
                    const nameEl = item.querySelector('.detail .firstline .name') || item.querySelector('.name');
                    if (nameEl) {
                        const name = nameEl.textContent.trim();
                        if (name && name.length > 0 && name.length < 20 && name !== ' ') {
                            names.push(name);
                        }
                    }
                });
                return names;
            }''')
        except Exception:
            break

        new_count = 0
        for name in current:
            if name not in seen:
                seen.add(name)
                all_names.append(name)
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

    return all_names


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

        # 点击候选人
        pages_before = len(context.pages)
        element.click()

        # 等待新标签页出现
        for _ in range(16):
            time.sleep(0.5)
            if len(context.pages) > pages_before:
                break

        pages = context.pages
        if len(pages) <= pages_before:
            result["error"] = "未打开新标签页"
            return result

        detail_page = pages[-1]

        # 尝试查找附件按钮
        attachment_btn = None
        for attempt in range(2):
            time.sleep(1)
            for sel in ['span:has-text("附件个人信息")', ':text("附件个人信息")']:
                try:
                    el = detail_page.query_selector(sel)
                    if el and el.is_visible():
                        attachment_btn = el
                        break
                except Exception:
                    continue
            if attachment_btn:
                break

        if not attachment_btn:
            result["error"] = "未找到附件按钮"
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
    try:
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

        completion = client.chat.completions.create(
            model=MIMO_MODEL,
            messages=[
                {"role": "system", "content": "你是简历筛选助手，只输出JSON格式结果。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=100,
        )

        content = completion.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        import json
        result = json.loads(content)
        return {"match": bool(result.get("match", False)), "reason": str(result.get("reason", ""))}
    except Exception as e:
        return {"match": True, "reason": f"AI评估失败，默认通过"}