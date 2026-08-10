# -*- coding: utf-8 -*-
import time
import sys
import os
import json
from datetime import datetime
from pathlib import Path
import pandas as pd
from openai import OpenAI

if sys.platform == 'win32':
    os.system('chcp 65001 >nul 2>&1')
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

sys.path.insert(0, str(BASE_DIR))

from browser.chrome import ChromeBrowser
from config import (
    load_ai_config, save_ai_config,
    MIMO_API_BASE, MIMO_MODEL, AI_CONFIG_PATH
)


def wrap_text(text, width=60, indent=""):
    """将长文本按指定宽度换行，返回多行字符串"""
    lines = []
    while len(text) > width:
        lines.append(indent + text[:width])
        text = text[width:]
    if text:
        lines.append(indent + text)
    return "\n".join(lines)


def print_separator(title: str):
    print("\n" + "=" * 50)
    print(f"  {title}")
    print("=" * 50)


def get_all_candidate_names(page):
    """获取DOM中所有候选人姓名（包括隐藏的）"""
    try:
        result = page.evaluate('''() => {
            const items = document.querySelectorAll('.item.virtual_list');
            const result = {
                total: items.length,
                names: [],
                failed: []
            };
            
            items.forEach((item, index) => {
                // 尝试多种方式获取姓名
                let name = '';
                let method = '';
                
                // 方式1: .detail .firstline .name
                const nameEl1 = item.querySelector('.detail .firstline .name');
                if (nameEl1) {
                    name = nameEl1.textContent.trim();
                    method = '.detail .firstline .name';
                }
                
                // 方式2: .name
                if (!name) {
                    const nameEl2 = item.querySelector('.name');
                    if (nameEl2) {
                        name = nameEl2.textContent.trim();
                        method = '.name';
                    }
                }
                
                // 方式3: title属性
                if (!name) {
                    const nameEl3 = item.querySelector('[title]');
                    if (nameEl3 && nameEl3.title) {
                        name = nameEl3.title.trim();
                        method = 'title';
                    }
                }
                
                // 方式4: 第一个span
                if (!name) {
                    const span = item.querySelector('span');
                    if (span) {
                        name = span.textContent.trim().substring(0, 10);
                        method = 'first span';
                    }
                }
                
                if (name && name.length > 0 && name.length < 20 && name !== ' ') {
                    result.names.push(name);
                } else {
                    // 记录失败信息
                    result.failed.push({
                        index: index,
                        name: name,
                        method: method,
                        hasDetail: !!item.querySelector('.detail'),
                        hasFirstline: !!item.querySelector('.firstline'),
                        hasName: !!item.querySelector('.name'),
                        innerText: item.innerText.substring(0, 100)
                    });
                }
            });
            
            return result;
        }''')
        
        print(f"  DOM中元素总数: {result['total']}")
        print(f"  有效姓名数: {len(result['names'])}")
        print(f"  失败数量: {len(result['failed'])}")
        
        # 显示前几个失败的详细信息
        if result.get('failed'):
            print(f"\n  失败详情（前5个）:")
            for f in result['failed'][:5]:
                print(f"    [{f['index']}] name='{f['name']}' method='{f['method']}'")
                print(f"        hasDetail={f['hasDetail']}, hasFirstline={f['hasFirstline']}, hasName={f['hasName']}")
                print(f"        innerText='{f['innerText'][:50]}'")
        
        return result['names']
    except Exception as e:
        print(f"获取候选人失败: {e}")
        return []


def find_candidate_by_name(page, name):
    """根据姓名查找候选人元素（包括隐藏的）"""
    try:
        # 使用JavaScript查找，可以找到隐藏的元素
        index = page.evaluate('''(name) => {
            const items = document.querySelectorAll('.item.virtual_list');
            for (let i = 0; i < items.length; i++) {
                const nameEl = items[i].querySelector('.detail .firstline .name');
                if (nameEl && nameEl.textContent.trim() === name) {
                    return i;
                }
            }
            return -1;
        }''', name)
        
        if index >= 0:
            # 找到元素，返回Playwright元素句柄
            items = page.query_selector_all('.item.virtual_list')
            if index < len(items):
                return items[index]
    except Exception as e:
        print(f"查找候选人失败: {e}")
    
    return None


def get_visible_names(page):
    """获取当前可见的前5个候选人姓名"""
    try:
        return page.evaluate('''() => {
            try {
                return Array.from(document.querySelectorAll('.item.virtual_list .name'))
                    .map(el => el.textContent.trim())
                    .filter(n => n.length > 0)
                    .slice(0, 5);
            } catch(e) {
                return [];
            }
        }''')
    except:
        return []


def test_scroll(page):
    """测试滚动功能，逐个测试不同方案"""
    methods = {
        "1": ("click body + PageDown", lambda: (
            page.click('body'),
            time.sleep(0.5),
            page.keyboard.press('PageDown'),
            time.sleep(1.5)
        )),
        "2": ("focus body + PageDown", lambda: (
            page.focus('body'),
            time.sleep(0.5),
            page.keyboard.press('PageDown'),
            time.sleep(1.5)
        )),
        "3": ("mouse wheel on (600,400) 滚到底部", "wheel_600_400"),
        "4": ("mouse wheel on (500,300) 滚到底部", "wheel_500_300"),
        "5": ("JS scrollTop on .list", lambda: (
            page.evaluate("document.querySelector('.list').scrollTop += 600"),
            time.sleep(1.5)
        )),
        "6": ("JS window.scrollBy", lambda: (
            page.evaluate("window.scrollBy(0, 600)"),
            time.sleep(1.5)
        )),
        "7": ("dispatch wheel on .list", lambda: (
            page.evaluate('''() => {
                const list = document.querySelector('.list');
                if (list) list.dispatchEvent(new WheelEvent('wheel', {
                    deltaY: 600, bubbles: true, cancelable: true
                }));
            }'''),
            time.sleep(1.5)
        )),
    }

    while True:
        print_separator("测试滚动功能")
        print("\n请选择要测试的方案：\n")
        for k, (name, _) in methods.items():
            print(f"  {k}. {name}")
        print(f"  0. 返回主菜单")

        choice = input("\n选择: ").strip()

        if choice == "0":
            break

        if choice not in methods:
            print("无效选择")
            continue

        name, action = methods[choice]
        print(f"\n测试: {name}")

        # 滚回顶部
        try:
            page.keyboard.press('Home')
            time.sleep(1)
        except:
            pass

        if isinstance(action, str):
            # 滚到底部模式：用和 collect_all_candidates_with_scroll 一样的逻辑
            all_names = []
            seen = set()
            no_new_count = 0

            if action == "wheel_600_400":
                page.mouse.move(600, 400)
            elif action == "wheel_500_300":
                page.mouse.move(500, 300)
            time.sleep(0.5)

            for round_num in range(100):
                current = get_all_candidate_names(page)
                new_count = 0
                for n in current:
                    if n not in seen:
                        seen.add(n)
                        all_names.append(n)
                        new_count += 1

                if new_count > 0:
                    print(f"  轮次 {round_num + 1}: 新增 {new_count} 个，总计 {len(all_names)} 个")
                    no_new_count = 0
                else:
                    no_new_count += 1

                if no_new_count >= 3:
                    break

                page.mouse.wheel(0, 600)
                time.sleep(1)

            print(f"\n  结果: 共收集 {len(all_names)} 个候选人")
            if all_names:
                print(f"  前5个: {all_names[:5]}")
                print(f"  后5个: {all_names[-5:]}")

        else:
            # 单次滚动模式
            before = get_visible_names(page)
            print(f"  滚动前: {before}")

            try:
                action()
            except Exception as e:
                print(f"  执行异常: {e}")
                continue

            after = get_visible_names(page)
            print(f"  滚动后: {after}")

            if before and after and before != after:
                print(f"  ✓ 有效！")
            else:
                print(f"  ✗ 无效")

        input("\n按 Enter 继续...")


def wait_for_element(page, selectors, timeout=15):
    """轮询等待任意一个选择器的元素出现并可见，找到立即返回"""
    for _ in range(timeout):
        for sel in selectors:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    return el
            except:
                continue
        time.sleep(1)
    return None


def read_resume_text(page):
    """从附件预览页读取简历文本内容"""
    try:
        text = page.evaluate('''() => {
            // 优先读取简历内容区域
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
            // 兜底：读取整个 body 文本
            const body = document.body.innerText.trim();
            return body.substring(0, 8000);
        }''')
        return text
    except Exception as e:
        print(f"      读取简历文本失败: {e}")
        return ""


def evaluate_resume(resume_text, match_description, api_key, max_retries=3):
    """调用 MiMo API 评估简历是否符合要求"""
    client = OpenAI(
        api_key=api_key,
        base_url=MIMO_API_BASE,
    )

    prompt = f"""你是一个专业的简历筛选助手。请根据以下岗位要求，判断候选人简历是否符合要求。

【岗位要求】
{match_description}

【候选人简历】
{resume_text}

请严格按以下 JSON 格式回复，不要输出其他内容：
{{"match": true/false, "reason": "简要说明原因（30字以内）"}}"""

    last_error = None
    for attempt in range(max_retries):
        try:
            completion = client.chat.completions.create(
                model=MIMO_MODEL,
                messages=[
                    {"role": "system", "content": "你是简历筛选助手，只输出JSON格式结果。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_completion_tokens=4096,
                stream=False,
            )
            msg = completion.choices[0].message
            content = (msg.content or "").strip()

            # content 为空时尝试从 reasoning_content 提取
            if not content and hasattr(msg, 'reasoning_content') and msg.reasoning_content:
                reasoning = msg.reasoning_content
                # 尝试从推理内容中提取 JSON
                import re
                json_match = re.search(r'\{[^{}]*"match"\s*:\s*(true|false)[^{}]*\}', reasoning)
                if json_match:
                    content = json_match.group(0)

            if not content:
                last_error = "API返回空内容"
                print(f"      {last_error}(第{attempt+1}次)")
                if attempt < max_retries - 1:
                    time.sleep(2)
                continue

            if content.startswith("```"):
                content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

            result = json.loads(content)
            return {
                "match": bool(result.get("match", False)),
                "reason": str(result.get("reason", ""))
            }
        except Exception as e:
            last_error = e
            print(f"      API调用异常(第{attempt+1}次): {e}")
            if attempt < max_retries - 1:
                time.sleep(2)

    return {"match": True, "reason": f"AI评估失败({last_error})，默认通过"}


def check_ai_config():
    """检查 AI 配置是否完整，返回 (是否可用, 配置)"""
    config = load_ai_config()
    if config.get("api_key") and config.get("match_description") and config.get("enabled"):
        return True, config
    return False, config


def menu_config_ai():
    """AI 配置菜单"""
    config = load_ai_config()
    job_descs = config.get("job_descriptions", {})

    print_separator("AI 简历筛选配置")
    print(f"\n当前状态:")
    print(f"  AI 筛选: {'已启用' if config.get('enabled') else '未启用'}")
    print(f"  API Key: {'已配置 (' + config['api_key'][:8] + '...)' if config.get('api_key') else '未配置'}")
    print(f"  已配置岗位描述: {len(job_descs)} 个")
    for name, desc in job_descs.items():
        print(f"    - {name}:")
        print(wrap_text(desc, 55, "      "))

    print(f"\n  1. 配置 API Key")
    print(f"  2. 管理岗位匹配描述")
    print(f"  3. {'禁用' if config.get('enabled') else '启用'} AI 筛选")
    print(f"  4. 测试 API 连接")
    print(f"  0. 返回主菜单")

    choice = input("\n请选择: ").strip()

    if choice == "1":
        key = input("\n请输入 MiMo API Key: ").strip()
        if key:
            config["api_key"] = key
            save_ai_config(config)
            print("✓ API Key 已保存")
        else:
            print("未输入")

    elif choice == "2":
        menu_manage_job_descriptions(config)

    elif choice == "3":
        if not config.get("api_key") or not job_descs:
            print("\n请先配置 API Key 和至少一个岗位描述")
        else:
            config["enabled"] = not config.get("enabled", False)
            save_ai_config(config)
            print(f"✓ AI 筛选已{'启用' if config['enabled'] else '禁用'}")

    elif choice == "4":
        if not config.get("api_key"):
            print("\n请先配置 API Key")
        else:
            test_desc = list(job_descs.values())[0] if job_descs else "开发工程师"
            print(f"\n正在测试 API 连接 (使用描述: {test_desc[:30]}...)...")
            result = evaluate_resume(
                "张三，开发工程师，5年经验，熟悉多种技术栈",
                test_desc,
                config["api_key"]
            )
            print(f"  结果: {'匹配' if result['match'] else '不匹配'}")
            print(f"  原因: {result['reason']}")
            print("✓ API 连接正常")


def menu_manage_job_descriptions(config):
    """管理岗位匹配描述"""
    job_descs = config.get("job_descriptions", {})

    while True:
        print_separator("岗位匹配描述管理")
        if not job_descs:
            print("\n  暂无岗位描述")
        else:
            print(f"\n  已配置 {len(job_descs)} 个岗位:")
            for i, (name, desc) in enumerate(job_descs.items(), 1):
                print(f"    {i}. {name}")
                print(wrap_text(desc, 55, "       "))

        print(f"\n  a. 新增岗位描述")
        print(f"  d. 删除岗位描述")
        print(f"  0. 返回")

        choice = input("\n请选择: ").strip()

        if choice == "0":
            break
        elif choice == "a":
            name = input("\n岗位名称: ").strip()
            if not name:
                print("未输入")
                continue
            print(f"请输入 '{name}' 的匹配描述:")
            print("  例如: '3年以上经验，熟悉Vue/React，本科及以上学历'")
            desc = input("描述: ").strip()
            if desc:
                job_descs[name] = desc
                config["job_descriptions"] = job_descs
                save_ai_config(config)
                print(f"✓ 已添加: {name}")
        elif choice == "d":
            if not job_descs:
                print("\n暂无岗位描述")
                continue
            name = input("\n要删除的岗位名称: ").strip()
            if name in job_descs:
                del job_descs[name]
                config["job_descriptions"] = job_descs
                save_ai_config(config)
                print(f"✓ 已删除: {name}")
            else:
                print(f"未找到: {name}")
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(job_descs):
                name = list(job_descs.keys())[idx]
                print(f"\n当前: {name}")
                print(f"描述: {job_descs[name]}")
                print(f"\n  1. 修改描述")
                print(f"  2. 删除")
                sub = input("选择: ").strip()
                if sub == "1":
                    new_desc = input("新描述: ").strip()
                    if new_desc:
                        job_descs[name] = new_desc
                        config["job_descriptions"] = job_descs
                        save_ai_config(config)
                        print("✓ 已更新")
                elif sub == "2":
                    del job_descs[name]
                    config["job_descriptions"] = job_descs
                    save_ai_config(config)
                    print(f"✓ 已删除: {name}")


def download_resume(browser, candidate_name, download_dir, index, ai_config=None, job_name=""):
    """下载候选人简历"""
    context = browser.context
    page = browser.page
    result = {"success": False, "name": candidate_name, "file_path": "", "error": "", "ai_pass": None}
    
    try:
        print(f"  [{index}] {candidate_name}")
        
        # 查找候选人元素
        element = find_candidate_by_name(page, candidate_name)
        if not element:
            result["error"] = "元素未找到"
            print(f"      错误: 未找到候选人元素")
            return result
        
        # 滚动到该元素（让它可见）
        try:
            element.scroll_into_view_if_needed(timeout=5000)
            time.sleep(0.5)
        except:
            pass
        
        # 点击候选人
        pages_before = len(context.pages)
        element.click()

        # 等待新标签页出现（替代固定 sleep(2)）
        for _ in range(16):
            time.sleep(0.5)
            if len(context.pages) > pages_before:
                break

        pages = context.pages
        if len(pages) <= pages_before:
            result["error"] = "未打开新标签页"
            print(f"      错误: 未打开新标签页")
            return result
        
        detail_page = pages[-1]

        # 尝试查找附件按钮（最多2次，每次间隔1s）
        print(f"      查找附件...")
        attachment_btn = None
        for attempt in range(2):
            time.sleep(1)
            for sel in ['span:has-text("附件个人信息")', ':text("附件个人信息")']:
                try:
                    el = detail_page.query_selector(sel)
                    if el and el.is_visible():
                        attachment_btn = el
                        break
                except:
                    continue
            if attachment_btn:
                break

        if not attachment_btn:
            result["error"] = "未找到附件按钮"
            print(f"      未找到附件按钮（无附件简历）")
            detail_page.close()
            return result

        # 点击附件按钮
        print(f"      点击附件按钮...")
        pages_before_attach = len(context.pages)
        attachment_btn.click()
        time.sleep(2)

        pages_after = context.pages

        if len(pages_after) > pages_before_attach:
            attach_page = pages_after[-1]

            # 等待下载按钮出现（最多15s，出现即继续）
            print(f"      等待下载按钮加载...")
            download_selectors = [
                '.btn_item_download .download_a',
                '.download_a',
                'a.download_a',
                '[class*="download"] a',
                'a:has-text("下载")',
                '.btn_item:has-text("下载")',
            ]
            download_btn = wait_for_element(attach_page, download_selectors, timeout=15)

            # AI 筛选：下载前先评估简历
            if download_btn and ai_config and ai_config.get("enabled"):
                print(f"      AI 评估简历...")
                resume_text = read_resume_text(attach_page)
                if resume_text:
                    eval_result = evaluate_resume(
                        resume_text,
                        ai_config["match_description"],
                        ai_config["api_key"]
                    )
                    result["ai_pass"] = eval_result["match"]
                    if not eval_result["match"]:
                        print(f"      AI 不通过: {eval_result['reason']}")
                        result["error"] = f"AI不通过: {eval_result['reason']}"
                        attach_page.close()
                        time.sleep(0.5)
                        detail_page.close()
                        time.sleep(0.5)
                        return result
                    else:
                        print(f"      AI 通过: {eval_result['reason']}")
                else:
                    print(f"      无法读取简历内容，跳过AI评估")

            if download_btn:
                try:
                    with attach_page.expect_download(timeout=20000) as download_info:
                        download_btn.click()

                    download = download_info.value
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
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
                    print(f"      下载成功: {filename}")

                except Exception as e:
                    result["error"] = f"下载失败: {e}"
                    print(f"      下载失败: {e}")
            else:
                result["error"] = "未找到下载按钮"
                print(f"      未找到下载按钮（等待15s超时）")

            attach_page.close()
            time.sleep(0.5)

        else:
            # 附件按钮没有打开新标签页，可能在当前页弹窗
            print(f"      检查弹窗...")
            download_selectors = [
                '.btn_item_download .download_a',
                '.download_a',
                'a.download_a',
                '[class*="download"] a',
            ]
            download_btn = wait_for_element(detail_page, download_selectors, timeout=10)

            # AI 筛选（弹窗模式）
            if download_btn and ai_config and ai_config.get("enabled"):
                print(f"      AI 评估简历...")
                resume_text = read_resume_text(detail_page)
                if resume_text:
                    eval_result = evaluate_resume(
                        resume_text,
                        ai_config["match_description"],
                        ai_config["api_key"]
                    )
                    result["ai_pass"] = eval_result["match"]
                    if not eval_result["match"]:
                        print(f"      AI 不通过: {eval_result['reason']}")
                        result["error"] = f"AI不通过: {eval_result['reason']}"
                        detail_page.close()
                        time.sleep(0.5)
                        return result
                    else:
                        print(f"      AI 通过: {eval_result['reason']}")
                else:
                    print(f"      无法读取简历内容，跳过AI评估")

            if download_btn:
                try:
                    with detail_page.expect_download(timeout=20000) as download_info:
                        download_btn.click()

                    download = download_info.value
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
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
                    print(f"      下载成功: {filename}")

                except Exception as e:
                    result["error"] = f"下载失败: {e}"
                    print(f"      下载失败: {e}")
            else:
                result["error"] = "未找到下载按钮"
                print(f"      未找到下载按钮")
        
        detail_page.close()
        time.sleep(0.5)
        
    except Exception as e:
        result["error"] = str(e)
        print(f"      错误: {e}")
        try:
            pages = context.pages
            while len(pages) > 1:
                pages[-1].close()
                time.sleep(0.5)
                pages = context.pages
        except:
            pass
    
    return result


def test_pagination(page):
    """测试分页功能，检测页面上的分页控件"""
    print_separator("测试分页功能")

    # 用鼠标滚轮滚动到底部
    print("\n使用鼠标滚轮滚动到底部...")
    try:
        page.mouse.move(600, 400)
        time.sleep(0.5)
    except:
        pass

    for i in range(20):
        page.mouse.wheel(0, 600)
        time.sleep(0.8)

    time.sleep(1)

    result = page.evaluate('''() => {
        const info = {};
        info.pageTitle = document.title;
        info.pageUrl = window.location.href;

        // 检测 eh-pagination 容器
        const pager = document.querySelector('.eh-pagination');
        info.hasPager = !!pager;
        info.pagerVisible = pager ? pager.offsetParent !== null : false;
        info.pagerHTML = pager ? pager.outerHTML.substring(0, 1000) : '';

        // 总数
        const totalEl = document.querySelector('.eh-pagination__total');
        info.totalText = totalEl ? totalEl.textContent.trim() : '';

        // 每页条数
        const selected = document.querySelector('.eh-pagination .el-select-dropdown__item.selected');
        info.pageSize = selected ? selected.textContent.trim() : '';

        // 下一页按钮
        const nextBtn = document.querySelector('.eh-pagination__next.btn-next, .eh-pagination .btn-next');
        info.hasNextBtn = !!nextBtn;
        info.nextDisabled = nextBtn ? (nextBtn.disabled || nextBtn.hasAttribute('disabled')) : null;

        // 上一页按钮
        const prevBtn = document.querySelector('.eh-pagination__prev.btn-prev, .eh-pagination .btn-prev');
        info.hasPrevBtn = !!prevBtn;
        info.prevDisabled = prevBtn ? (prevBtn.disabled || prevBtn.hasAttribute('disabled')) : null;

        // 页码列表
        const pageItems = document.querySelectorAll('.eh-pagination__pagelist li');
        info.pageNumbers = Array.from(pageItems).map(el => ({
            text: el.textContent.trim(),
            active: el.classList.contains('active')
        }));

        // 兜底：搜索任何包含 pagination 关键字的元素
        const allEls = document.querySelectorAll('[class*="pagin"], [class*="page-"], [class*="pag"]');
        info.similarEls = Array.from(allEls).slice(0, 10).map(el => ({
            tag: el.tagName,
            class: el.className.substring(0, 80),
            visible: el.offsetParent !== null
        }));

        return info;
    }''')

    print(f"\n页面: {result['pageTitle']}")
    print(f"URL: {result['pageUrl'][:80]}")

    print(f"\n分页控件检测结果:")
    print(f"  eh-pagination 存在: {result['hasPager']}")
    print(f"  eh-pagination 可见: {result['pagerVisible']}")
    print(f"  总数: {result['totalText']}")
    print(f"  每页条数: {result['pageSize']}")
    print(f"  下一页按钮存在: {result['hasNextBtn']}")
    print(f"  下一页按钮禁用: {result['nextDisabled']}")
    print(f"  上一页按钮存在: {result['hasPrevBtn']}")
    print(f"  上一页按钮禁用: {result['prevDisabled']}")

    if result['pageNumbers']:
        print(f"  页码: {result['pageNumbers']}")
    else:
        print(f"  页码: 未找到")

    if result['pagerHTML']:
        print(f"\n  分页HTML片段:\n    {result['pagerHTML'][:500]}...")
    else:
        print(f"\n  未找到 eh-pagination")
        if result['similarEls']:
            print(f"  类似元素:")
            for el in result['similarEls']:
                print(f"    <{el['tag']}> class=\"{el['class']}\" visible={el['visible']}")
        else:
            print(f"  也未找到其他分页相关元素")

    return result


def has_next_page(page):
    """检测是否有下一页"""
    try:
        result = page.evaluate('''() => {
            const nextBtn = document.querySelector('.eh-pagination__next.btn-next, .eh-pagination .btn-next');
            if (!nextBtn) return { hasNext: false, reason: 'no_btn' };

            const isDisabled = nextBtn.disabled
                || nextBtn.hasAttribute('disabled');

            return { hasNext: !isDisabled, reason: isDisabled ? 'disabled' : 'available' };
        }''')
        return result['hasNext']
    except Exception as e:
        print(f"  检测分页失败: {e}")
        return False


def go_to_next_page(page):
    """点击下一页并等待页面加载完成"""
    try:
        # 记录当前第一个候选人姓名，用于判断页面是否刷新
        old_first = page.evaluate('''() => {
            const items = document.querySelectorAll('.item.virtual_list');
            if (items.length === 0) return '';
            const nameEl = items[0].querySelector('.detail .firstline .name');
            return nameEl ? nameEl.textContent.trim() : '';
        }''')

        # 记录当前页码
        old_page = page.evaluate('''() => {
            const active = document.querySelector('.eh-pagination__pagelist li.active');
            return active ? active.textContent.trim() : '';
        }''')

        # 点击下一页按钮
        clicked = page.evaluate('''() => {
            const nextBtn = document.querySelector('.eh-pagination__next.btn-next, .eh-pagination .btn-next');
            if (!nextBtn) return false;
            nextBtn.click();
            return true;
        }''')

        if not clicked:
            print("  点击下一页失败：按钮不存在")
            return False

        # 等待页面刷新：页码变化 或 第一个候选人变化
        for wait in range(30):
            time.sleep(1)

            new_page = page.evaluate('''() => {
                const active = document.querySelector('.eh-pagination__pagelist li.active');
                return active ? active.textContent.trim() : '';
            }''')

            if new_page and new_page != old_page:
                print(f"  翻页成功: 第{old_page}页 → 第{new_page}页 (等待 {wait + 1}s)")
                return True

            new_first = page.evaluate('''() => {
                const items = document.querySelectorAll('.item.virtual_list');
                if (items.length === 0) return '';
                const nameEl = items[0].querySelector('.detail .firstline .name');
                return nameEl ? nameEl.textContent.trim() : '';
            }''')

            if new_first and new_first != old_first:
                print(f"  翻页成功（列表已更新），等待 {wait + 1}s")
                return True

        print("  翻页超时（30s）")
        return False

    except Exception as e:
        print(f"  翻页失败: {e}")
        return False


def scroll_to_pagination(page):
    """滚动页面使分页控件可见（用鼠标滚轮模拟用户滚动到底部）"""
    try:
        page.mouse.move(600, 400)
        time.sleep(0.3)
    except:
        pass

    for i in range(20):
        page.mouse.wheel(0, 600)
        time.sleep(0.5)

    time.sleep(1)


def get_job_positions(page):
    """获取页面上的职位列表和当前活跃职位"""
    try:
        result = page.evaluate('''() => {
            const items = document.querySelectorAll('.job_name_text');
            const positions = [];
            let activeName = '';

            items.forEach(el => {
                const name = el.textContent.trim();
                if (!name) return;
                const isActive = el.classList.contains('at');
                positions.push({ name: name, active: isActive });
                if (isActive) activeName = name;
            });

            return { positions: positions, active: activeName };
        }''')
        return result
    except Exception as e:
        print(f"  获取职位列表失败: {e}")
        return {"positions": [], "active": ""}


def switch_job_position(page, target_name):
    """点击指定职位 tab 切换"""
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
        }''', target_name)

        if not clicked:
            print(f"  未找到职位: {target_name}")
            return False

        # 等待页面刷新，切换职位后列表需要重新加载
        print(f"  等待页面加载...")
        time.sleep(5)
        return True
    except Exception as e:
        print(f"  切换职位失败: {e}")
        return False


def collect_all_candidates_with_scroll(page):
    """通过滚动收集所有候选人"""
    all_names = []
    seen = set()
    no_new_count = 0

    # 移动鼠标到页面中间，触发虚拟列表加载
    try:
        page.mouse.move(600, 400)
        time.sleep(0.5)
    except:
        pass

    for round_num in range(100):
        # 获取当前候选人
        current = get_all_candidate_names(page)

        new_count = 0
        for name in current:
            if name not in seen:
                seen.add(name)
                all_names.append(name)
                new_count += 1

        if new_count > 0:
            print(f"  轮次 {round_num + 1}: 新增 {new_count} 个，总计 {len(all_names)} 个")
            no_new_count = 0
        else:
            no_new_count += 1

        if no_new_count >= 3:
            break

        # 使用鼠标滚轮向下滚动
        page.mouse.wheel(0, 600)
        time.sleep(1)

    return all_names


def auto_download_all(browser, download_dir, ai_config=None, job_name=""):
    """自动下载所有简历（支持分页）"""
    page = browser.page
    all_results = []
    page_num = 1
    global_index = 0

    try:
        while True:
            print_separator(f"第 {page_num} 页")

            # 收集当前页候选人
            print(f"\n收集第 {page_num} 页候选人...\n")
            all_names = collect_all_candidates_with_scroll(page)
            total = len(all_names)

            print(f"\n第 {page_num} 页共收集到 {total} 个候选人\n")

            if not all_names:
                print(f"第 {page_num} 页未找到候选人")
                break

            # 滚动回顶部
            page.keyboard.press('Home')
            time.sleep(1)

            # 逐个下载当前页
            print(f"开始下载第 {page_num} 页简历...\n")
            print(f"（按 Ctrl+C 可中断，已处理数据会保留）\n")
            for i, name in enumerate(all_names, 1):
                global_index += 1
                result = download_resume(browser, name, download_dir, global_index, ai_config, job_name)
                result["page"] = page_num
                all_results.append(result)
                time.sleep(1)

            print(f"\n第 {page_num} 页处理完成")

            # 检测是否有下一页
            scroll_to_pagination(page)
            time.sleep(1)

            if not has_next_page(page):
                print(f"\n已到最后一页，共 {page_num} 页")
                break

            # 翻到下一页
            print(f"\n正在翻到第 {page_num + 1} 页...")
            if not go_to_next_page(page):
                print("翻页失败，停止")
                break

            page_num += 1

    except KeyboardInterrupt:
        print(f"\n\n⚠ 用户中断，已处理 {len(all_results)} 个候选人")

    print(f"\n共处理 {page_num} 页，{global_index} 个候选人")
    return all_results


def export_results_excel(results, download_dir, job_name=""):
    """导出下载结果到 Excel"""
    if not results:
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    excel_path = download_dir.parent / f"result_{timestamp}.xlsx"

    rows = []
    for r in results:
        if r.get("ai_pass") is False:
            status = "AI不通过"
        elif r["success"]:
            status = "成功"
        else:
            status = "失败"

        rows.append({
            "职位": job_name or r.get("job", ""),
            "姓名": r["name"],
            "页码": r.get("page", ""),
            "下载状态": status,
            "AI评估": "通过" if r.get("ai_pass") is True else ("不通过" if r.get("ai_pass") is False else "未评估"),
            "文件路径": r.get("file_path", ""),
            "错误/原因": r.get("error", ""),
        })

    df = pd.DataFrame(rows)
    df.to_excel(excel_path, index=False, sheet_name="下载结果")
    return str(excel_path)


def show_results(results, download_dir, job_name=""):
    """显示下载结果统计并导出 Excel"""
    print_separator("下载结果统计")
    success_count = sum(1 for r in results if r["success"])
    ai_pass_count = sum(1 for r in results if r.get("ai_pass") is True)
    ai_fail_count = sum(1 for r in results if r.get("ai_pass") is False)
    print(f"\n总计: {len(results)} 个候选人")
    print(f"成功下载: {success_count} 个")
    if ai_pass_count or ai_fail_count:
        print(f"AI 通过: {ai_pass_count} 个 | AI 不通过: {ai_fail_count} 个")
    print(f"保存目录: {download_dir}")

    if results:
        print("\n详细结果：")
        for r in results:
            page_tag = f"[第{r.get('page', '?')}页] " if r.get('page') else ""
            ai_tag = ""
            if r.get("ai_pass") is True:
                ai_tag = "[AI✓] "
            elif r.get("ai_pass") is False:
                ai_tag = "[AI✗] "
            if r["success"]:
                print(f"  ✓ {page_tag}{ai_tag}{r['name']}: {r['file_path']}")
            else:
                print(f"  ✗ {page_tag}{ai_tag}{r['name']}: {r['error']}")

    # 导出 Excel
    excel_path = export_results_excel(results, download_dir, job_name)
    if excel_path:
        print(f"\n结果已导出: {excel_path}")


def main():
    print_separator("HR简历自动下载助手")

    download_dir = BASE_DIR / "output" / "resumes"
    download_dir.mkdir(parents=True, exist_ok=True)

    print("\n[1] 连接 Chrome 浏览器...")
    browser = ChromeBrowser()
    if not browser.connect():
        print("\n按 Enter 键退出...")
        input()
        sys.exit(1)

    print("✓ 当前浏览器连接成功")

    page_info = browser.get_current_page_info()
    print(f"\n当前页面: {page_info['title']}")
    print(f"URL: {page_info['url'][:80]}")

    while True:
        # 显示 AI 状态
        ai_ok, ai_cfg = check_ai_config()
        ai_status = "AI:ON" if ai_ok else "AI:OFF"

        print_separator("操作选择")
        print(f"\n请选择操作：                          [{ai_status}]")
        print("  0. 测试滚动功能（调试用）")
        print("  1. 开始自动浏览并下载所有简历（含分页）")
        print("  2. 下载指定简历")
        print("  3. 退出")
        print("  5. AI 简历筛选配置")
        print("  9. 测试分页功能（调试用）")

        choice = input("\n请输入选择: ").strip()

        if choice == "0":
            test_scroll(browser.page)
            print()
            continue

        elif choice == "9":
            test_pagination(browser.page)
            print()
            continue

        elif choice == "3":
            break

        elif choice == "5":
            menu_config_ai()
            print()
            continue

        elif choice == "1":
            # 获取页面上的职位列表
            pos_info = get_job_positions(browser.page)
            positions = pos_info.get("positions", [])
            active_name = pos_info.get("active", "")

            if not positions:
                print("\n未检测到职位列表，请确认已在候选人管理页面")
                continue

            # 选择职位
            print_separator("选择职位")
            print(f"\n当前活跃: {active_name or '未知'}\n")
            for i, pos in enumerate(positions, 1):
                mark = " →" if pos["name"] == active_name else "  "
                print(f"  {mark} {i}. {pos['name']}")

            print(f"\n  0. 使用当前职位 ({active_name})")
            pos_choice = input("\n选择职位序号: ").strip()

            if pos_choice == "0" or pos_choice == "":
                selected_pos = active_name
            elif pos_choice.isdigit() and 1 <= int(pos_choice) <= len(positions):
                selected_pos = positions[int(pos_choice) - 1]["name"]
            else:
                print("无效选择")
                continue

            # 切换职位（如果不是当前活跃的）
            if selected_pos != active_name:
                print(f"\n切换到: {selected_pos}...")
                if not switch_job_position(browser.page, selected_pos):
                    print("切换失败")
                    continue
                print("✓ 切换成功")
                time.sleep(2)

            # 选择 AI 匹配描述
            ai_cfg = None
            config = load_ai_config()
            job_descs = config.get("job_descriptions", {})

            if config.get("enabled") and config.get("api_key") and job_descs:
                print_separator("选择 AI 匹配描述")
                desc_names = list(job_descs.keys())
                for i, name in enumerate(desc_names, 1):
                    print(f"  {i}. {name}:")
                    print(wrap_text(job_descs[name], 55, "     "))
                print(f"  0. 跳过 AI 筛选")
                print(f"  n. 新增描述")

                desc_choice = input("\n选择: ").strip()

                if desc_choice == "0":
                    ai_cfg = None
                elif desc_choice == "n":
                    new_name = input("描述名称: ").strip()
                    new_desc = input("匹配描述: ").strip()
                    if new_name and new_desc:
                        job_descs[new_name] = new_desc
                        config["job_descriptions"] = job_descs
                        save_ai_config(config)
                        ai_cfg = {**config, "match_description": new_desc}
                        print(f"✓ 已添加: {new_name}")
                    else:
                        print("未输入完整，跳过 AI 筛选")
                elif desc_choice.isdigit() and 1 <= int(desc_choice) <= len(desc_names):
                    chosen_name = desc_names[int(desc_choice) - 1]
                    ai_cfg = {**config, "match_description": job_descs[chosen_name]}
                    print(f"✓ 使用描述: {chosen_name}")
                else:
                    print("无效选择，跳过 AI 筛选")
            elif config.get("api_key") and config.get("enabled"):
                print("\n⚠ 未配置岗位描述，跳过 AI 筛选")

            print_separator("自动下载")
            print(f"\n职位: {selected_pos}")
            print(f"保存目录: {download_dir}")
            if ai_cfg and ai_cfg.get("enabled"):
                print(f"AI 筛选: 已启用")
                print(f"匹配描述:")
                print(wrap_text(ai_cfg['match_description'], 55, "  "))
            else:
                print(f"AI 筛选: 未启用")
            confirm = input("\n确认开始自动下载？(y/n): ").strip().lower()
            if confirm != 'y':
                print("取消下载")
                continue

            results = auto_download_all(browser, download_dir, ai_cfg, selected_pos)
            show_results(results, download_dir, selected_pos)
            print()

        elif choice == "2":
            # 检查 AI 配置
            ai_ok, ai_cfg = check_ai_config()
            if not ai_ok:
                print("\n⚠ AI 筛选未配置或未启用")
                skip_ai = input("  跳过 AI 筛选直接下载？(y/n): ").strip().lower()
                if skip_ai != 'y':
                    continue
                ai_cfg = None

            print_separator("下载指定简历")
            indices_input = input("\n请输入要下载的序号（多个用逗号分隔，如 1,3,5）: ").strip()

            try:
                indices = [int(x.strip()) for x in indices_input.split(",")]
            except:
                print("输入无效")
                continue

            if not indices:
                print("未输入有效序号")
                continue

            # 先收集候选人
            print("\n正在收集候选人列表...")
            page = browser.page
            page.keyboard.press('Home')
            time.sleep(1)

            all_names = []
            seen = set()

            for _ in range(100):
                current = get_all_candidate_names(page)
                for name in current:
                    if name not in seen:
                        seen.add(name)
                        all_names.append(name)

                if len(all_names) >= max(indices):
                    break

                page.keyboard.press('PageDown')
                time.sleep(0.8)

            print(f"共找到 {len(all_names)} 个候选人")

            for i, name in enumerate(all_names[:20], 1):
                print(f"  {i}. {name}")
            if len(all_names) > 20:
                print(f"  ... 共 {len(all_names)} 个")

            confirm = input("\n确认下载？(y/n): ").strip().lower()
            if confirm != 'y':
                print("取消下载")
                continue

            # 滚动回顶部并逐个下载
            page.keyboard.press('Home')
            time.sleep(1)

            results = []
            for idx in indices:
                if idx <= len(all_names):
                    name = all_names[idx - 1]
                    result = download_resume(browser, name, download_dir, idx, ai_cfg)
                    results.append(result)
                    time.sleep(1)
                else:
                    print(f"  序号 {idx} 超出范围")

            show_results(results, download_dir)
            print()

        else:
            print("无效选择")
            continue

    browser.close()
    print_separator("退出")
    print("\n程序已退出")


if __name__ == "__main__":
    main()
