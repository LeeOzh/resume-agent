# -*- coding: utf-8 -*-
import time
import sys
import os
from datetime import datetime
from pathlib import Path

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


def test_scroll(page):
    """测试滚动功能，找出可用的滚动方式"""
    print_separator("测试滚动功能")
    
    # 获取页面信息
    print("\n获取页面信息...")
    try:
        title = page.title()
        url = page.url
        print(f"页面: {title}")
        print(f"URL: {url}")
    except Exception as e:
        print(f"获取页面信息失败: {e}")
    
    # 检测候选人选择器
    print("\n检测候选人选择器...")
    try:
        selectors = [
            '.item.virtual_list',
            '[class*="virtual_list"]',
            '.card',
            '.el-card',
            '[page-mode]',
            '.candidate'
        ]
        
        found = False
        for sel in selectors:
            try:
                count = page.evaluate(f'document.querySelectorAll("{sel}").length')
                if count > 0:
                    print(f"  ✓ {sel}: {count} 个")
                    found = True
            except:
                pass
        
        if not found:
            print("  ✗ 未找到任何候选人元素")
    except Exception as e:
        print(f"  检测失败: {e}")
    
    # 测试鼠标滚轮滚动
    print("\n测试鼠标滚轮滚动...")
    
    # 记录滚动前的候选人
    try:
        before_names = page.evaluate('''() => {
            try {
                return Array.from(document.querySelectorAll('.item.virtual_list .name')).map(el => el.textContent.trim()).slice(0, 5);
            } catch(e) {
                return [];
            }
        }''')
        print(f"  滚动前候选人: {before_names}")
    except Exception as e:
        print(f"  获取候选人失败: {e}")
        before_names = []
    
    # 使用鼠标滚轮滚动
    print("  执行鼠标滚轮向下滚动...")
    try:
        # 先移动鼠标到页面中间
        page.mouse.move(500, 400)
        time.sleep(0.5)
        # 执行滚轮
        page.mouse.wheel(0, 500)
        time.sleep(2)
    except Exception as e:
        print(f"  滚轮滚动失败: {e}")
    
    # 记录滚动后的候选人
    try:
        after_names = page.evaluate('''() => {
            try {
                return Array.from(document.querySelectorAll('.item.virtual_list .name')).map(el => el.textContent.trim()).slice(0, 5);
            } catch(e) {
                return [];
            }
        }''')
        print(f"  滚动后候选人: {after_names}")
    except Exception as e:
        print(f"  获取候选人失败: {e}")
        after_names = []
    
    # 检查是否有变化
    if before_names and after_names:
        changed = before_names != after_names
        if changed:
            print("  ✓ 鼠标滚轮滚动有效！")
        else:
            print("  ✗ 鼠标滚轮滚动无效")
    else:
        print("  无法比较（候选人列表为空）")
    
    print(f"\n测试完成")


def download_resume(browser, candidate_name, download_dir, index):
    """下载候选人简历"""
    context = browser.context
    page = browser.page
    result = {"success": False, "name": candidate_name, "file_path": "", "error": ""}
    
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
        
        try:
            context.wait_for_event("page", timeout=8000)
        except:
            pass
        time.sleep(2)
        
        pages = context.pages
        if len(pages) <= pages_before:
            result["error"] = "未打开新标签页"
            print(f"      错误: 未打开新标签页")
            return result
        
        detail_page = pages[-1]
        
        # 等待页面基本加载
        time.sleep(1.5)
        
        # 查找"附件个人信息"按钮
        print(f"      查找附件...")
        attachment_btn = None
        
        selectors = [
            'span:has-text("附件个人信息")',
            ':text("附件个人信息")',
            'span:text-is("附件个人信息")',
        ]
        
        for selector in selectors:
            try:
                btn = detail_page.query_selector(selector)
                if btn and btn.is_visible():
                    attachment_btn = btn
                    print(f"      找到附件按钮")
                    break
            except:
                continue
        
        if not attachment_btn:
            try:
                all_spans = detail_page.query_selector_all('span')
                for span in all_spans:
                    try:
                        text = span.inner_text().strip()
                        if text == "附件个人信息":
                            attachment_btn = span
                            print(f"      找到附件按钮: {text}")
                            break
                    except:
                        continue
            except:
                pass
        
        if not attachment_btn:
            result["error"] = "未找到附件按钮"
            print(f"      未找到附件按钮")
            detail_page.close()
            return result
        
        # 点击附件按钮
        print(f"      点击附件按钮...")
        pages_before_attach = len(context.pages)
        attachment_btn.click()
        time.sleep(3)
        
        pages_after = context.pages
        
        if len(pages_after) > pages_before_attach:
            attach_page = pages_after[-1]
            time.sleep(1.5)
            
            print(f"      查找下载按钮...")
            download_btn = None
            
            download_selectors = [
                '.btn_item_download .download_a',
                '.download_a',
                'a.download_a',
                '[class*="download"] a',
                'a:has-text("下载")',
                '.btn_item:has-text("下载")',
            ]
            
            for selector in download_selectors:
                try:
                    btn = attach_page.query_selector(selector)
                    if btn and btn.is_visible():
                        download_btn = btn
                        print(f"      找到下载按钮: {selector}")
                        break
                except:
                    continue
            
            if not download_btn:
                try:
                    all_links = attach_page.query_selector_all('a')
                    for link in all_links:
                        try:
                            text = link.inner_text().strip()
                            cls = link.get_attribute('class') or ''
                            if text == "下载" or "download" in cls:
                                download_btn = link
                                print(f"      找到下载按钮: text={text}, class={cls}")
                                break
                        except:
                            continue
                except:
                    pass
            
            if download_btn:
                try:
                    with attach_page.expect_download(timeout=20000) as download_info:
                        download_btn.click()
                    
                    download = download_info.value
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    suggested_name = download.suggested_filename
                    
                    if suggested_name:
                        ext = Path(suggested_name).suffix or '.pdf'
                        filename = f"{candidate_name}_{timestamp}{ext}"
                    else:
                        filename = f"{candidate_name}_{timestamp}.pdf"
                    
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
            
            attach_page.close()
            time.sleep(0.5)
            
        else:
            print(f"      检查弹窗...")
            time.sleep(1.5)
            
            download_btn = None
            download_selectors = [
                '.btn_item_download .download_a',
                '.download_a',
                'a.download_a',
                '[class*="download"] a',
            ]
            
            for selector in download_selectors:
                try:
                    btn = detail_page.query_selector(selector)
                    if btn and btn.is_visible():
                        download_btn = btn
                        print(f"      找到下载按钮: {selector}")
                        break
                except:
                    continue
            
            if download_btn:
                try:
                    with detail_page.expect_download(timeout=20000) as download_info:
                        download_btn.click()
                    
                    download = download_info.value
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    suggested_name = download.suggested_filename
                    
                    if suggested_name:
                        ext = Path(suggested_name).suffix or '.pdf'
                        filename = f"{candidate_name}_{timestamp}{ext}"
                    else:
                        filename = f"{candidate_name}_{timestamp}.pdf"
                    
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


def collect_all_candidates_with_scroll(page):
    """通过滚动收集所有候选人"""
    all_names = []
    seen = set()
    no_new_count = 0
    
    # 先点击页面获取焦点
    try:
        page.click('body')
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
        
        # 使用键盘 Page Down 滚动
        page.keyboard.press('PageDown')
        time.sleep(1)
    
    return all_names


def auto_download_all(browser, download_dir):
    """自动下载所有简历"""
    page = browser.page
    results = []
    
    print("\n开始收集候选人...")
    print("使用 Page Down 滚动页面...\n")
    
    # 通过滚动收集所有候选人
    all_names = collect_all_candidates_with_scroll(page)
    total = len(all_names)
    
    print(f"\n共收集到 {total} 个候选人\n")
    
    if not all_names:
        print("未找到候选人")
        return results
    
    # 滚动回顶部
    page.keyboard.press('Home')
    time.sleep(1)
    
    # 逐个下载
    print("开始下载简历...\n")
    for i, name in enumerate(all_names, 1):
        result = download_resume(browser, name, download_dir, i)
        results.append(result)
        time.sleep(1)
    
    print(f"\n共处理 {total} 个候选人")
    return results


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
    
    print_separator("操作选择")
    print("\n请选择操作：")
    print("  0. 测试滚动功能（调试用）")
    print("  1. 开始自动浏览并下载所有简历")
    print("  2. 下载指定简历")
    print("  3. 退出")
    
    choice = input("\n请输入选择: ").strip()
    
    if choice == "0":
        # 测试滚动
        test_scroll(browser.page)
        print("\n按 Enter 键退出...")
        input()
        browser.close()
        return
    
    elif choice == "3":
        browser.close()
        return
    
    elif choice == "1":
        print_separator("自动下载")
        print(f"\n保存目录: {download_dir}")
        confirm = input("确认开始自动下载？(y/n): ").strip().lower()
        if confirm != 'y':
            print("取消下载")
            browser.close()
            return
        
        results = auto_download_all(browser, download_dir)
        
    elif choice == "2":
        print_separator("下载指定简历")
        indices_input = input("\n请输入要下载的序号（多个用逗号分隔，如 1,3,5）: ").strip()
        
        try:
            indices = [int(x.strip()) for x in indices_input.split(",")]
        except:
            print("输入无效")
            browser.close()
            return
        
        if not indices:
            print("未输入有效序号")
            browser.close()
            return
        
        # 先收集候选人
        print("\n正在收集候选人列表...")
        page = browser.page
        page.evaluate("window.scrollTo(0, 0)")
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
            
            page.evaluate("window.scrollBy(0, 400)")
            time.sleep(0.8)
        
        print(f"共找到 {len(all_names)} 个候选人")
        
        for i, name in enumerate(all_names[:20], 1):
            print(f"  {i}. {name}")
        if len(all_names) > 20:
            print(f"  ... 共 {len(all_names)} 个")
        
        confirm = input("\n确认下载？(y/n): ").strip().lower()
        if confirm != 'y':
            print("取消下载")
            browser.close()
            return
        
        # 滚动回顶部并逐个下载
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(1)
        
        results = []
        for idx in indices:
            if idx <= len(all_names):
                name = all_names[idx - 1]
                result = download_resume(browser, name, download_dir, idx)
                results.append(result)
                time.sleep(1)
            else:
                print(f"  序号 {idx} 超出范围")
    else:
        print("无效选择")
        browser.close()
        return
    
    # 显示结果
    print_separator("下载结果统计")
    success_count = sum(1 for r in results if r["success"])
    print(f"\n总计: {len(results)} 个候选人")
    print(f"成功下载: {success_count} 个")
    print(f"保存目录: {download_dir}")
    
    if results:
        print("\n详细结果：")
        for r in results:
            if r["success"]:
                print(f"  ✓ {r['name']}: {r['file_path']}")
            else:
                print(f"  ✗ {r['name']}: {r['error']}")
    
    browser.close()
    print_separator("完成")
    print("\n按 Enter 键退出...")
    input()


if __name__ == "__main__":
    main()
