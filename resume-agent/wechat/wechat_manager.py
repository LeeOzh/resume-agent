# -*- coding: utf-8 -*-
"""
微信简历文件目录解析适配层（V1）。

方案：不依赖微信 UI 自动化（微信 4.1.x 主界面自绘、控件树不可用），
改为直接检测微信安装位置 -> 定位聊天文件目录（msg/file/年-月/），
扫描其中的 PDF 简历文件进行解析。
"""
import re
import time
from pathlib import Path


class WeChatManager:
    """封装微信安装位置/聊天文件目录检测与简历 PDF 扫描"""

    def __init__(self):
        self.wechat_exe = ''
        self.wxid_folder = ''
        self.chatfile_folder = ''
        self.last_error = ''

    @property
    def connected(self) -> bool:
        """检测成功即可用（不要求微信正在运行）"""
        return bool(self.chatfile_folder)

    def connect(self) -> bool:
        """检测微信安装位置与聊天文件目录（多级检测，适配不同安装目录）"""
        self.last_error = ''

        # 第一优先：用户手动指定的目录（已保存到配置，跨机器可用）
        try:
            from wechat.wechat_config import load_wechat_config
            manual = str(load_wechat_config().get("chatfile_dir", "") or "").strip()
            if manual and Path(manual).is_dir():
                self.chatfile_folder = manual
                self._detect_wechat_exe()
                return True
        except Exception:
            pass

        # 第二优先：pyweixin 自动检测（注册表 + 微信进程内存映射）
        try:
            from pyweixin import Tools
            self.wechat_exe = str(Tools.where_weixin() or '')
            self.wxid_folder = str(Tools.where_wxid_folder(open_folder=False) or '')
            self.chatfile_folder = str(Tools.where_chatfile_folder(open_folder=False) or '')
        except Exception as e:
            self.last_error = str(e)
            return False
        if not self.chatfile_folder or not Path(self.chatfile_folder).is_dir():
            # 第三优先：注册表安装路径 + 常见数据目录扫描
            found = self._scan_common_data_dirs()
            if not found:
                self.last_error = (
                    '未找到微信聊天文件目录。请确认微信已登录并保持运行，'
                    '或在页面上手动选择聊天文件目录'
                )
                return False
            self.chatfile_folder = found
            self.wxid_folder = str(Path(found).parent.parent)
        return True

    def _detect_wechat_exe(self):
        """从注册表读取微信安装位置（不要求微信正在运行）"""
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Tencent\Weixin") as key:
                install_dir = winreg.QueryValueEx(key, "InstallPath")[0]
            exe = Path(install_dir) / "Weixin.exe"
            if exe.exists():
                self.wechat_exe = str(exe)
        except Exception:
            pass

    def _scan_common_data_dirs(self):
        """
        兜底：在常见位置查找 xwechat_files/<wxid>/msg/file 目录。
        微信 4.x 数据目录默认在 文档/xwechat_files，也可能自定义到其他盘。
        """
        candidates = []
        try:
            import os
            home = Path(os.path.expanduser("~"))
            candidates += [
                home / "Documents" / "xwechat_files",
                home / "Documents" / "WeChat Files",
                Path("C:/App/op/xwechat_files"),
                Path("C:/xwechat_files"),
                Path("D:/xwechat_files"),
                Path("E:/xwechat_files"),
            ]
            # 微信安装目录同级/上级也可能存在数据目录
            if self.wechat_exe:
                install = Path(self.wechat_exe).parent
                candidates.append(install.parent / "xwechat_files")
                candidates.append(install.parent / "op" / "xwechat_files")
        except Exception:
            pass
        for root in candidates:
            try:
                if not root.is_dir():
                    continue
                for wxid_dir in root.iterdir():
                    msg_file = wxid_dir / "msg" / "file"
                    if msg_file.is_dir():
                        return str(msg_file)
            except Exception:
                continue
        return ''

    def get_sessions(self):
        """获取聊天文件目录下的月份子目录（如 2026-08），作为扫描范围"""
        if not self.chatfile_folder:
            return []
        try:
            base = Path(self.chatfile_folder)
            dirs = sorted(
                (p.name for p in base.iterdir() if p.is_dir() and re.match(r'^\d{4}-\d{2}$', p.name)),
                reverse=True,
            )
            return dirs or ['全部']
        except Exception as e:
            self.last_error = str(e)
            return []

    def start_listen(self, name: str) -> bool:
        """兼容旧接口：目录方案无需打开窗口，校验目录可读即可"""
        return self.connected

    def scan_pdf_files(self) -> list:
        """
        扫描聊天文件目录下所有 PDF 文件。
        返回 [{file_name, file_path, size, mtime}]，按修改时间倒序。
        """
        if not self.chatfile_folder:
            return []
        base = Path(self.chatfile_folder)
        files = []
        try:
            for p in base.rglob('*.pdf'):
                if not p.is_file():
                    continue
                try:
                    stat = p.stat()
                    files.append({
                        'file_name': p.name,
                        'file_path': str(p),
                        'size': stat.st_size,
                        'mtime': stat.st_mtime,
                    })
                except OSError:
                    continue
        except Exception as e:
            self.last_error = str(e)
            return []
        files.sort(key=lambda x: x['mtime'], reverse=True)
        return files

    def copy_file(self, src: Path, save_dir: Path, file_name: str) -> Path:
        """把文件复制到保存目录，同名追加序号，返回保存后的路径"""
        import shutil
        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        target = save_dir / file_name
        stem, suffix = Path(file_name).stem, Path(file_name).suffix
        n = 1
        while target.exists():
            target = save_dir / f'{stem}({n}){suffix}'
            n += 1
        shutil.copy2(src, target)
        return target

    def stop_listen(self):
        """兼容旧接口：无需清理"""
        pass
