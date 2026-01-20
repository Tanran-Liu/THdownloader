#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
设备数据下载器 - Tkinter GUI 界面
"""

import asyncio
import logging
logger = logging.getLogger(__name__)# v2.3.1+
import threading
# v2.2
import json
import tkinter as tk
import tkinter.font as tkfont # v2.0
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import ttk, messagebox, filedialog, scrolledtext
from typing import List, Optional, Tuple, Dict, Callable, Any
import sys
import os

from download.async_downloader import AsyncDeviceDataDownloader, DownloadError
from download.db import (
    search_devices_by_name, get_device_by_exact_name,# v2.0
    search_devices_by_id, get_device_by_id,# v2.1
    # v2.3.1 ===== 用户管理 CRUD =====
    find_users_by_name_or_phone,
    create_user,
    update_user_info,
    list_bound_devices_for_user,
    add_device_binding,
    delete_device_binding,
)

class DownloadProgressWidget:
    """下载进度显示组件"""

    def __init__(self, parent):
        self.parent = parent
        self.current_message = ""
        self.current_progress = 0.0

        # 创建进度框架
        self.frame = ttk.LabelFrame(parent, text="下载进度", padding="10")

        # 进度条
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(
            self.frame,
            variable=self.progress_var,
            maximum=100,
            length=400
        )
        self.progress_bar.pack(fill=tk.X, pady=(0, 5))

        # 进度消息
        self.message_var = tk.StringVar(value="准备中...")
        self.message_label = ttk.Label(self.frame, textvariable=self.message_var)
        self.message_label.pack(pady=(0, 5))

        # 取消按钮
        self.cancel_btn = ttk.Button(
            self.frame,
            text="取消下载",
            state=tk.DISABLED
        )
        self.cancel_btn.pack()

    def update_progress(self, message: str, progress: float):
        """更新进度"""
        self.current_message = message
        self.current_progress = progress * 100

        self.progress_var.set(self.current_progress)
        self.message_var.set(f"{message} ({self.current_progress:.1f}%)")

    def enable_cancel_button(self, enabled: bool = True):
        """启用或禁用取消按钮"""
        self.cancel_btn.config(state=tk.NORMAL if enabled else tk.DISABLED)

    def reset(self):
        """重置进度显示"""
        self.current_message = ""
        self.current_progress = 0.0
        self.progress_var.set(0)
        self.message_var.set("准备中...")
        self.enable_cancel_button(False)


# class DeviceSelectionWidget:
#     """设备选择组件"""
#
#     def __init__(self, parent):
#         self.parent = parent
#         self.selected_devices = []
#
#         # 创建设备选择框架
#         self.frame = ttk.LabelFrame(parent, text="设备选择", padding="10")
#
#         # 说明标签
#         ttk.Label(
#             self.frame,
#             text="设备选择 (多个设备用逗号分隔，如: 1,2,3)"
#         ).pack(anchor=tk.W, pady=(0, 5))
#
#         # 设备输入框
#         self.device_var = tk.StringVar()
#         self.device_entry = ttk.Entry(
#             self.frame,
#             textvariable=self.device_var,
#             width=40
#         )
#         self.device_entry.pack(fill=tk.X, pady=(0, 5))
#
#         # 状态标签
#         self.status_var = tk.StringVar()
#         self.status_label = ttk.Label(self.frame, textvariable=self.status_var)
#         self.status_label.pack(anchor=tk.W)
#
#     def get_devices(self) -> List[int]:
#         """获取选择的设备列表"""
#         try:
#             devices = [int(d.strip()) for d in self.device_var.get().split(",") if d.strip()]
#             return devices
#         except ValueError:
#             return []
#
#     def validate_devices(self) -> bool:
#         """验证设备输入"""
#         devices = self.get_devices()
#
#         if not devices:
#             self.status_var.set("请输入至少一个有效的设备ID")
#             self.status_label.config(foreground="red")
#             return False
#
#         self.status_var.set(f"已选择 {len(devices)} 个设备")
#         self.status_label.config(foreground="green")
#         return True

# v2.2.1 通用下拉组件
class AutoCompletePopup:
    """
    通用下拉建议组件：绑定到一个 Entry
    - 防抖 + 后台线程 fetcher(keyword)->List[(id,name)]
    - Text 做高亮（可选）
    - 高度随匹配数量变化
    - 切到别的程序/最小化/点击空白自动隐藏
    """

    MAX_VISIBLE = 10
    MIN_WIDTH = 420

    def __init__(
        self,
        owner_frame: ttk.Frame,
        entry: ttk.Entry,
        fetcher: Callable[[str], List[Tuple[int, str]]],
        on_pick: Callable[[int, str], None],
    ):
        self.owner_frame = owner_frame
        self.entry = entry
        self.fetcher = fetcher
        self.on_pick = on_pick

        self._debounce_id = None
        self._popup: Optional[tk.Toplevel] = None
        self._text: Optional[tk.Text] = None
        self._suggestions: List[Tuple[int, str]] = []

        f = tkfont.Font(font=self.entry.cget("font"))
        self._row_height = max(18, f.metrics("linespace") + 6)

        root = self.owner_frame.winfo_toplevel()
        root.bind("<Button-1>", self._global_click_close, add=True)
        root.bind("<FocusOut>", lambda e: self.hide(), add=True)
        root.bind("<Unmap>", lambda e: self.hide(), add=True)
        root.bind("<Configure>", lambda e: self._reposition(), add=True)

        self.entry.bind("<Down>", lambda e: self.focus_popup())
        self.entry.bind("<Escape>", lambda e: self.hide())

    def on_typing(self, keyword: str):
        if self._debounce_id:
            self.owner_frame.after_cancel(self._debounce_id)
        self._debounce_id = self.owner_frame.after(250, lambda: self._search_bg(keyword))

    def _search_bg(self, keyword: str):
        kw = (keyword or "").strip()
        if not kw:
            self.hide()
            return

        def worker():
            try:
                rows = self.fetcher(kw) or []
            except Exception:
                rows = []
            self.owner_frame.after(0, lambda: self._render(kw, rows))

        threading.Thread(target=worker, daemon=True).start()

    def _ensure_popup(self):
        if self._popup and self._popup.winfo_exists():
            return

        root = self.owner_frame.winfo_toplevel()
        self._popup = tk.Toplevel(root)
        self._popup.withdraw()
        self._popup.overrideredirect(True)
        self._popup.transient(root)

        self._text = tk.Text(
            self._popup,
            height=5,
            width=60,
            wrap="none",
            cursor="hand2",
            font=self.entry.cget("font"),
            bd=1,
            relief="solid",
        )
        self._text.pack(fill="both", expand=True)
        self._text.bind("<Button-1>", self._on_click)
        self._text.bind("<Escape>", lambda e: self.hide())

    def _render(self, kw: str, rows: List[Tuple[int, str]]):
        self._suggestions = rows
        if not rows:
            self.hide()
            return

        self._ensure_popup()
        assert self._popup is not None
        assert self._text is not None

        visible = min(len(rows), self.MAX_VISIBLE)

        # 先写内容
        self._text.config(state="normal")
        self._text.delete("1.0", "end")
        self._text.tag_delete("match")

        low_kw = kw.lower()
        for idx, (_, name) in enumerate(rows[: self.MAX_VISIBLE]):
            self._text.insert("end", name + "\n")

            # 高亮匹配片段（不影响功能，你也可以删掉这段）
            low_name = name.lower()
            start = 0
            while True:
                pos = low_name.find(low_kw, start)
                if pos == -1:
                    break
                tag_start = f"{idx+1}.{pos}"
                tag_end = f"{idx+1}.{pos+len(kw)}"
                self._text.tag_add("match", tag_start, tag_end)
                start = pos + len(kw)

        self._text.tag_config("match", foreground="red")
        self._text.config(state="disabled")

        # 再定位大小（关键：先 geometry 再 deiconify，避免跑到左上角）
        self._text.config(height=visible)
        self._reposition(visible_rows=visible)
        self._popup.deiconify()
        self._popup.lift(self.owner_frame.winfo_toplevel())

    def _reposition(self, visible_rows: Optional[int] = None):
        if not (self._popup and self._popup.winfo_exists()):
            return
        self.owner_frame.update_idletasks()

        x = self.entry.winfo_rootx()
        y = self.entry.winfo_rooty() + self.entry.winfo_height()
        w = max(self.entry.winfo_width(), self.MIN_WIDTH)

        visible_rows = max(1, int(visible_rows or (self._text.cget("height") if self._text else 5)))
        h = visible_rows * self._row_height + 8

        self._popup.geometry(f"{w}x{h}+{x}+{y}")

    def hide(self):
        if self._popup and self._popup.winfo_exists():
            self._popup.withdraw()
        self._suggestions = []

    def focus_popup(self):
        if self._popup and self._popup.winfo_exists():
            self._popup.focus_force()

    def _on_click(self, event):
        if not self._text:
            return
        index = self._text.index(f"@{event.x},{event.y}")
        line = int(index.split(".")[0]) - 1
        if 0 <= line < len(self._suggestions):
            did, name = self._suggestions[line]
            self.on_pick(did, name)
            self.hide()

    def _global_click_close(self, event):
        if not (self._popup and self._popup.winfo_exists()):
            return
        w = event.widget
        # 点击在 popup 内不关
        if w is self._popup or (hasattr(w, "winfo_toplevel") and w.winfo_toplevel() is self._popup):
            return
        # 点在 entry 上不关
        if w is self.entry:
            return
        self.hide()

# v2.0
class DeviceNameSelectionWidget:
    """
    设备选择（按名称搜索，多选）
    - 输入时自动下拉（防抖 + 后台线程查库）
    - 下拉用 Text 做局部标红
    - 下拉高度随匹配数变化（最多 MAX_VISIBLE）
    - 切到别的程序/最小化时下拉自动隐藏（解决图层悬浮问题）
    - “添加”后清空输入框；“清空已选”一键清除
    - 对外接口保持：get_devices() -> List[int], validate_devices() -> bool
    """

    MAX_VISIBLE = 10
    MIN_WIDTH = 500

    def __init__(self, parent):
        self.parent = parent
        # v2.2.1 决定复用通用下拉组件AutoCompletePopup所以停用的代码
        #self._debounce_after_id = None
        #self._popup: Optional[tk.Toplevel] = None
        #self._text: Optional[tk.Text] = None
        #self._suggestions: List[Tuple[int, str]] = []  # (id, name)
        self._selected: Dict[int, str] = {}            # {id: name}

        self.frame = ttk.LabelFrame(parent, text="设备选择（按名称搜索）", padding="10")

        ttk.Label(
            self.frame,
            text="输入设备名称关键字，自动下拉匹配；选择或输入完整名称后点击“添加”。"
        ).pack(anchor=tk.W, pady=(0, 6))

        row = ttk.Frame(self.frame)
        row.pack(fill=tk.X, pady=(0, 6))

        self.keyword_var = tk.StringVar()
        self.entry = ttk.Entry(row, textvariable=self.keyword_var, width=40)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # v2.2.1--- 新增：给通用下拉用 ---
        self._picked_device_id: Optional[int] = None
        self._setting_var = False
        # v2.2.1
        self._ac = AutoCompletePopup(
            owner_frame=self.frame,
            entry=self.entry,
            fetcher=self._fetch_device_suggestions,
            on_pick=self._on_pick_device_suggestion,
        )

        # v2.2.1
        def _on_kw_change(*_):
            # 用户手动输入时，清掉之前点选的 id
            if not self._setting_var:
                self._picked_device_id = None
            self._ac.on_typing(self.keyword_var.get())

        # v2.2.1
        self.keyword_var.trace_add("write", _on_kw_change)

        # # v2.2.1 把方向键/ESC 也接到通用下拉
        self.entry.bind("<Down>", lambda e: self._ac.focus_popup())
        self.entry.bind("<Escape>", lambda e: self._ac.hide())
        self.entry.bind("<Return>", lambda e: self.add_current())

        self.btn_add = ttk.Button(row, text="添加", command=self.add_current)
        self.btn_add.pack(side=tk.LEFT, padx=(8, 0))

        self.btn_clear = ttk.Button(row, text="清空已选", command=self.clear_selected)
        self.btn_clear.pack(side=tk.LEFT, padx=(8, 0))

        self.status_var = tk.StringVar(value="尚未选择设备")
        self.status_label = ttk.Label(self.frame, textvariable=self.status_var)
        self.status_label.pack(anchor=tk.W, pady=(0, 6))

        box = ttk.LabelFrame(self.frame, text="已选择设备")
        box.pack(fill=tk.BOTH, expand=True)
        self.listbox = tk.Listbox(box, height=6)
        self.listbox.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        # v2.2.1 决定复用通用下拉组件AutoCompletePopup所以停用的代码
        # --- 字体/行高：用于计算下拉高度 ---
        # self._font = tkfont.Font(font=self.entry.cget("font"))
        # self._row_height = max(18, self._font.metrics("linespace") + 6)

        # --- bindings ---
        # self.keyword_var.trace_add("write", lambda *_: self.on_typing())
        # self.entry.bind("<Down>", lambda e: self.focus_popup())
        # self.entry.bind("<Return>", lambda e: self.add_current())
        # self.entry.bind("<Escape>", lambda e: self.hide_popup())

        #root = self.frame.winfo_toplevel()
        # root.bind("<Button-1>", self._global_click_close, add=True)
        # root.bind("<FocusOut>", self._on_root_focus_out, add=True)
        # root.bind("<Unmap>", lambda e: self.hide_popup(), add=True)
        # root.bind("<Configure>", lambda e: self._reposition_popup(), add=True)

    def get_devices(self) -> List[int]:
        return list(self._selected.keys())

    def validate_devices(self) -> bool:
        if not self._selected:
            self.status_var.set("请至少添加一个设备")
            self.status_label.config(foreground="red")
            return False
        self.status_var.set(f"已选择 {len(self._selected)} 个设备")
        self.status_label.config(foreground="green")
        return True

    def _fetch_device_suggestions(self, kw: str) -> List[Tuple[int, str]]:
        kw = (kw or "").strip()
        if not kw:
            return []

        # 数字：优先按 ID 查，同时也按 name 查（与你旧逻辑一致）
        if kw.isdigit():
            try:
                rows_by_id = search_devices_by_id(kw, limit=30)
            except Exception:
                rows_by_id = []
            try:
                rows_by_name = search_devices_by_name(kw, limit=30)
            except Exception:
                rows_by_name = []

            # 合并去重（按 did 去重）
            seen = set()
            merged: List[Tuple[int, str]] = []
            for did, name in (rows_by_id + rows_by_name):
                if did not in seen:
                    merged.append((did, name))
                    seen.add(did)
            return merged

        # 非数字：按名字查
        try:
            return search_devices_by_name(kw, limit=30) or []
        except Exception:
            return []

    def _on_pick_device_suggestion(self, did: int, name: str):
        # 点选后：记录 id，回填 name
        self._picked_device_id = did
        self._setting_var = True
        try:
            self.keyword_var.set(name)
            self.entry.icursor("end")
        finally:
            self._setting_var = False

    # v2.2.1 决定复用通用下拉组件AutoCompletePopup所以停用的代码
    # def on_typing(self):
    #     if self._debounce_after_id:
    #         self.frame.after_cancel(self._debounce_after_id)
    #     self._debounce_after_id = self.frame.after(250, self._trigger_search_background)

    # def _trigger_search_background(self):
    #     kw = self.keyword_var.get().strip()
    #     if not kw:
    #         self.hide_popup()
    #         return
    #
    #     def worker():
    #         rows = search_devices_by_name(kw, limit=30)
    #
    #         # v2.1: 如果用户输入的是纯数字，同步按ID检索并合并
    #         if kw.isdigit():
    #             try:
    #                 rows_by_id = search_devices_by_id(kw, limit=30)
    #             except Exception:
    #                 rows_by_id = []
    #
    #             if rows_by_id:
    #                 seen = set()
    #                 merged = []
    #                 for did, name in (rows_by_id + rows):
    #                     if did not in seen:
    #                         merged.append((did, name))
    #                         seen.add(did)
    #                 rows = merged
    #
    #         self.frame.after(0, lambda: self._render_suggestions(kw, rows))
    #         # try:
    #         #     rows = search_devices_by_name(kw, limit=30)
    #         # except Exception:
    #         #     rows = []
    #         # self.frame.after(0, lambda: self._render_suggestions(kw, rows))
    #
    #     threading.Thread(target=worker, daemon=True).start()
    #
    # def _render_suggestions(self, kw: str, rows: List[Tuple[int, str]]):
    #     self._suggestions = rows
    #     if not rows:
    #         self.hide_popup()
    #         return
    #
    #     self._ensure_popup()
    #     assert self._popup is not None and self._text is not None
    #
    #     visible = min(len(rows), self.MAX_VISIBLE)
    #     self._text.config(height=visible)
    #
    #     # 写入内容 + 标红
    #     self._text.config(state="normal")
    #     self._text.delete("1.0", "end")
    #     self._text.tag_delete("match")
    #
    #     low_kw = kw.lower()
    #     for idx, (_, name) in enumerate(rows):
    #         self._text.insert("end", name + "\n")
    #         low_name = name.lower()
    #         start = 0
    #         while True:
    #             pos = low_name.find(low_kw, start)
    #             if pos == -1:
    #                 break
    #             self._text.tag_add("match", f"{idx + 1}.{pos}", f"{idx + 1}.{pos + len(kw)}")
    #             start = pos + len(kw)
    #
    #     self._text.tag_config("match", foreground="red")
    #     self._text.config(state="disabled")
    #
    #     # 显示（如果当前是隐藏状态）
    #     if not self._popup.winfo_viewable():
    #         self._popup.deiconify()
    #         self._popup.lift(self.frame.winfo_toplevel())
    #
    #     # 定位（放在 deiconify 之后）
    #     self._reposition_popup(visible_rows=visible)
    #
    # def _ensure_popup(self):
    #     if self._popup and self._popup.winfo_exists():
    #         return
    #
    #     self._popup = tk.Toplevel(self.frame)
    #     self._popup.withdraw()
    #     self._popup.overrideredirect(True)
    #     # 注意：不设置 topmost，避免切到别的程序时仍悬浮在最上层
    #     self._popup.transient(self.frame.winfo_toplevel())
    #
    #     self._text = tk.Text(
    #         self._popup,
    #         height=5,
    #         width=60,
    #         wrap="none",
    #         cursor="hand2",
    #         font=self.entry.cget("font")
    #     )
    #     self._text.pack(fill="both", expand=True)
    #     self._text.bind("<Button-1>", self._on_popup_click)
    #     self._text.bind("<Escape>", lambda e: self.hide_popup())
    #
    # def _reposition_popup(self, visible_rows: Optional[int] = None):
    #     if not (self._popup and self._popup.winfo_exists()):
    #         return
    #
    #     self.frame.update_idletasks()
    #     # entry 还没布局好（宽度=1时很常见），延迟再定位，避免跑到 0,0
    #     if self.entry.winfo_width() <= 1:
    #         self.frame.after(10, lambda: self._reposition_popup(visible_rows=visible_rows))
    #         return
    #     x = self.entry.winfo_rootx()
    #     y = self.entry.winfo_rooty() + self.entry.winfo_height()
    #     w = max(self.entry.winfo_width(), self.MIN_WIDTH)
    #
    #     if visible_rows is None and self._text:
    #         visible_rows = int(self._text.cget("height"))
    #     visible_rows = max(1, int(visible_rows or 1))
    #
    #     h = visible_rows * self._row_height + 8
    #     self._popup.geometry(f"{w}x{h}+{x}+{y}")
    #
    # def _reposition_popup_dynamic(self, visible_rows: int):
    #     """
    #     - 确保 popup 已创建
    #     - 高度按匹配数动态调整
    #     - 重新定位到 entry 下方
    #     """
    #     self._ensure_popup()
    #     if self._text:
    #         try:
    #             self._text.config(height=max(1, int(visible_rows)))
    #         except Exception:
    #             pass
    #     self._reposition_popup(visible_rows=visible_rows)
    #
    # def hide_popup(self):
    #     #  不 destroy，改为 withdraw，避免触发一连串焦点/闪烁问题
    #     if self._popup and self._popup.winfo_exists():
    #         self._popup.withdraw()
    #     self._suggestions = []
    #
    # def focus_popup(self):
    #     if self._popup and self._popup.winfo_exists():
    #         self._popup.focus_force()
    #
    # def _on_popup_click(self, event):
    #     if not self._text:
    #         return
    #     index = self._text.index(f"@{event.x},{event.y}")
    #     line = int(index.split(".")[0])
    #     i = line - 1
    #     if 0 <= i < len(self._suggestions):
    #         _, name = self._suggestions[i]
    #         self.keyword_var.set(name)
    #         self.entry.icursor("end")
    #         self.hide_popup()
    #
    # def _global_click_close(self, event):
    #     if self._popup and self._popup.winfo_exists():
    #         widget = event.widget
    #         if widget is self._popup or (hasattr(widget, "winfo_toplevel") and widget.winfo_toplevel() is self._popup):
    #             return
    #         if widget is self.entry:
    #             return
    #         self.hide_popup()
    #
    # def _on_root_focus_out(self, event):
    #     self.frame.after(80, self._check_focus_then_maybe_hide)
    #
    # def _check_focus_then_maybe_hide(self):
    #     if not (self._popup and self._popup.winfo_exists()):
    #         return
    #     root = self.frame.winfo_toplevel()
    #     focused = root.focus_get()
    #     if focused is None:
    #         self.hide_popup()
    #         return
    #     top = focused.winfo_toplevel()
    #     if top is not root and top is not self._popup:
    #         self.hide_popup()

    # v2.2.1注释掉
    # def add_current(self):
    #     name = self.keyword_var.get().strip()
    #     if not name:
    #         return
    #
    #     # v2.1: 允许用户直接输入设备ID并添加
    #     if name.isdigit():
    #         try:
    #             matches = get_device_by_id(int(name))
    #         except Exception:
    #             matches = []
    #         if len(matches) == 1:
    #             did, n = matches[0]
    #             self._selected[did] = n
    #             self._refresh_selected_list()
    #             self.keyword_var.set("")
    #             self.hide_popup()
    #             return
    #
    #     for did, n in self._suggestions:
    #         if n == name:
    #             self._selected[did] = n
    #             self._refresh_selected_list()
    #             self.keyword_var.set("")
    #             self.hide_popup()
    #             return
    #
    #     matches = get_device_by_exact_name(name)
    #     if len(matches) == 1:
    #         did, n = matches[0]
    #         self._selected[did] = n
    #         self._refresh_selected_list()
    #         self.keyword_var.set("")
    #         self.hide_popup()
    #         return
    #
    #     self.hide_popup()
    #     self.status_var.set("未找到唯一匹配，请从下拉选择或输入更精确的名称")
    #     self.status_label.config(foreground="red")

    # v2.2.1添加
    def add_current(self):
        text = self.keyword_var.get().strip()
        if not text:
            return
        # 1) 优先：如果是从下拉点选过的，直接用 id 添加
        if self._picked_device_id is not None:
            did = self._picked_device_id
            name = text  # 回填的就是 name
            self._selected[did] = name
            self._refresh_selected_list()
            self._picked_device_id = None
            self.keyword_var.set("")
            self._ac.hide()
            return
        # 2) 用户直接输入 ID
        if text.isdigit():
            try:
                matches = get_device_by_id(int(text))
            except Exception:
                matches = []
            if len(matches) == 1:
                did, name = matches[0]
                self._selected[did] = name
                self._refresh_selected_list()
                self.keyword_var.set("")
                self._ac.hide()
                return
        # 3) 用户输入完整名称（精确匹配）
        try:
            matches = get_device_by_exact_name(text)
        except Exception:
            matches = []
        if len(matches) == 1:
            did, name = matches[0]
            self._selected[did] = name
            self._refresh_selected_list()
            self.keyword_var.set("")
            self._ac.hide()
            return
        # 4) 兜底：不唯一/找不到
        self._ac.hide()
        self.status_var.set("未找到唯一匹配，请从下拉选择或输入更精确的名称/ID")
        self.status_label.config(foreground="red")

    def clear_selected(self):
        self._selected.clear()
        self._refresh_selected_list()
        self.status_var.set("已清空已选设备")
        self.status_label.config(foreground="green")

    def _refresh_selected_list(self):
        self.listbox.delete(0, "end")
        for did, name in sorted(self._selected.items(), key=lambda x: x[1].lower()):
            self.listbox.insert("end", f"{name}  (ID={did})")
        if self._selected:
            self.status_var.set(f"已选择 {len(self._selected)} 个设备")
            self.status_label.config(foreground="green")
        else:
            self.status_var.set("尚未选择设备")
            self.status_label.config(foreground="black")

# v2.1
class DeviceConfigQueryWidget:
    """
    独立于下载选择框的“配置查询”：
    - 输入：设备名 或 设备ID
    - 点击按钮：查询配置（复用 AsyncDeviceDataDownloader._get_device_config_async）
    - 展示：JSON（pretty print）
    """

    def __init__(self, parent, get_downloader: Callable[[], Optional[AsyncDeviceDataDownloader]]):
        self.parent = parent
        self.get_downloader = get_downloader

        self.frame = ttk.LabelFrame(parent, text="设备配置查询", padding="10")

        row = ttk.Frame(self.frame)
        row.pack(fill=tk.X, pady=(0, 6))

        self.query_var = tk.StringVar()
        self.entry = ttk.Entry(row, textvariable=self.query_var, width=40)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # v2.2.1
        self._setting_var = False

        # v2.2.1
        self._picked_device_id: Optional[int] = None  # 用户从下拉点选时记录

        # v2.2.1
        self._ac = AutoCompletePopup(
            owner_frame=self.frame,  # 你的 widget 的主 frame
            entry=self.entry,  # 这个是“查询配置”的输入框 Entry
            fetcher=self._fetch_config_suggestions,
            on_pick=self._on_pick_config_suggestion,
        )

        def _on_query_change(*_):
            if not self._setting_var:
                self._picked_device_id = None  # 用户手动改动时，清掉之前点选的ID
            self._ac.on_typing(self.query_var.get())

        self.query_var.trace_add("write", _on_query_change)

        self.btn = ttk.Button(row, text="查询配置", command=self.query_config)
        self.btn.pack(side=tk.LEFT, padx=(8, 0))

        self.status_var = tk.StringVar(value="输入设备名或ID，点击“查询配置”。")
        self.status_label = ttk.Label(self.frame, textvariable=self.status_var)
        self.status_label.pack(anchor=tk.W, pady=(0, 6))

        self.text = scrolledtext.ScrolledText(self.frame, height=10, state=tk.DISABLED, wrap=tk.WORD)
        self.text.pack(fill=tk.BOTH, expand=True)

    def _set_text(self, s: str):
        self.text.config(state=tk.NORMAL)
        self.text.delete("1.0", "end")
        self.text.insert("end", s)
        self.text.config(state=tk.DISABLED)

    def _resolve_device(self, raw: str) -> Tuple[Optional[int], Optional[str], str]:
        """
        返回 (device_id, device_name, err_message)
        """
        q = (raw or "").strip()
        if not q:
            return None, None, "请输入设备名或设备ID"

        # 1) 纯数字：优先当作 device_id
        if q.isdigit():
            did = int(q)
            try:
                rows = get_device_by_id(did)
            except Exception:
                rows = []
            if len(rows) == 1:
                return rows[0][0], rows[0][1], ""
            # 允许用户输部分ID：给候选
            try:
                cand = search_devices_by_id(q, limit=10)
            except Exception:
                cand = []
            if len(cand) == 1:
                return cand[0][0], cand[0][1], ""
            if cand:
                return None, None, "ID 非唯一，请输入更完整ID。候选：\n" + "\n".join([f"{i} {n}" for i, n in cand])
            return None, None, "未找到该设备ID"

        # 2) 名称：先精确，再模糊
        try:
            exact = get_device_by_exact_name(q)
        except Exception:
            exact = []
        if len(exact) == 1:
            return exact[0][0], exact[0][1], ""
        try:
            cand = search_devices_by_name(q, limit=10)
        except Exception:
            cand = []
        if len(cand) == 1:
            return cand[0][0], cand[0][1], ""
        if cand:
            return None, None, "名称匹配不唯一，请更精确。候选：\n" + "\n".join([f"{i} {n}" for i, n in cand])
        return None, None, "未找到该设备名称"

    # v2.2.1
    def _fetch_config_suggestions(self, kw: str) -> List[Tuple[int, str]]:
        kw = (kw or "").strip()
        if not kw:
            return []

        # 数字：优先按ID搜；非数字：按名字搜
        if kw.isdigit():
            rows = search_devices_by_id(kw, limit=30)
        else:
            rows = search_devices_by_name(kw, limit=30)

        return rows or []

    # v2.2.1
    def _on_pick_config_suggestion(self, did: int, name: str):
        self._picked_device_id = did
        self._setting_var = True
        try:
            self.query_var.set(name)
            self.entry.icursor("end")
        finally:
            self._setting_var = False

    def query_config(self):
        # v2.2.1
        # raw = self.query_var.get()
        # device_id, device_name, err = self._resolve_device(raw)
        # if err:
        #     self.status_label.config(foreground="red")
        #     self.status_var.set(err)
        #     self._set_text("")
        #     return

        # v2.2.1
        raw = self.query_var.get().strip()
        # 如果是从下拉点选过的，直接用这个 device_id，不再做模糊/精确匹配
        if self._picked_device_id is not None:
            device_id = self._picked_device_id
            device_name = raw or ""
            err = ""
        else:
            device_id, device_name, err = self._resolve_device(raw)
        if err:
            self.status_label.config(foreground="red")
            self.status_var.set(err)
            self._set_text("")
            return

        downloader = self.get_downloader()
        if downloader is None:
            self.status_label.config(foreground="red")
            self.status_var.set("下载器未初始化，无法查询配置")
            return

        self.status_label.config(foreground="black")
        self.status_var.set(f"正在查询配置：{device_name} (ID={device_id}) ...")
        self._set_text("")

        root = self.frame.winfo_toplevel()

        def worker():
            loop = None
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                # 必须复用 async_downloader.py 里已有方法：
                row = loop.run_until_complete(downloader._get_device_config_async(device_id))
                if not row:
                    payload = {"device_id": device_id, "device_name": device_name, "error": "device_config 无记录"}
                else:
                    ver = row[-3]
                    payload: Dict[str, Any] = {
                        "device_id": device_id,
                        "device_name": device_name,
                        "config_version": ver,
                        "raw_columns": {
                            "config_col_2": row[2],
                            "config_col_3": row[3],
                        }
                    }

                    # row[2]/row[3] 就是你说的“json模式的东西”
                    try:
                        if ver == "2.0":
                            payload["raw_json"] = {
                                "data_config": json.loads(row[2]),
                                "image_config": json.loads(row[3]),
                            }
                        elif ver == "1.0":
                            payload["raw_json"] = {"config": json.loads(row[2])}
                    except Exception as e:
                        payload["raw_json_error"] = str(e)

                    # 复用 downloader 里已有解析逻辑（可选，但很实用）
                    try:
                        config_data, config_image = downloader._parse_config(row)
                        payload["parsed_mapping"] = {
                            "data_fields": config_data,
                            "image_fields": config_image,
                        }
                    except Exception as e:
                        payload["parsed_mapping_error"] = str(e)

                pretty = json.dumps(payload, ensure_ascii=False, indent=2)
                root.after(0, lambda: (self.status_label.config(foreground="green"),
                                      self.status_var.set(f"查询成功：{device_name} (ID={device_id})"),
                                      self._set_text(pretty)))
            except Exception as e:
                en = str(e)
                root.after(0, lambda err=en: (
                    self.status_label.config(foreground="red"),
                    self.status_var.set(f"查询失败: {err}"),
                    self._set_text(err)
                ))

            finally:
                if loop is not None:
                    try:
                        loop.close()
                    except Exception:
                        pass

        threading.Thread(target=worker, daemon=True).start()

# v2.3.1+ 添加用户增删改查功能（CRUD）
class UserAdminWidget:
    """
    用户管理（users + device_user）：
    - 搜索用户（name 或 phone）
    - 创建用户（users）
    - 更新用户（users：name/email/password）
    - 查询绑定设备（device_user）
    - 绑定设备（device_user insert）
    - 解绑设备：物理删除（device_user delete）
    日志：全部走 logging -> PyCharm 终端
    """

    def __init__(self, parent):
        self.parent = parent
        self.frame = ttk.LabelFrame(parent, text="用户管理（users / device_user）", padding="10")

        self._selected_user: Optional[Dict[str, Any]] = None
        self._bindings: List[Dict[str, Any]] = []

        # ===== 顶部：搜索 =====
        top = ttk.Frame(self.frame)
        top.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(top, text="搜索（姓名或电话）").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(top, textvariable=self.search_var, width=30)
        self.search_entry.pack(side=tk.LEFT, padx=(8, 8))
        self.btn_search = ttk.Button(top, text="搜索", command=self.on_search)
        self.btn_search.pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value="在此管理 users 和 device_user（解绑=物理删除）")
        self.status_label = ttk.Label(self.frame, textvariable=self.status_var)
        self.status_label.pack(anchor=tk.W, pady=(0, 8))

        # ===== 中间：左(用户列表) 右(详情/编辑) =====
        body = ttk.Frame(self.frame)
        body.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(body)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        right = ttk.Frame(body)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # 用户列表
        ttk.Label(left, text="搜索结果（选中后可编辑/管理绑定）").pack(anchor=tk.W)
        self.user_listbox = tk.Listbox(left, height=10)
        self.user_listbox.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self.user_listbox.bind("<<ListboxSelect>>", self.on_pick_user)

        # ===== 右侧：创建/更新 =====
        form = ttk.LabelFrame(right, text="用户信息", padding="10")
        form.pack(fill=tk.X, pady=(0, 10))

        self.user_id_var = tk.StringVar(value="")
        row_id = ttk.Frame(form)
        row_id.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(row_id, text="User ID").pack(side=tk.LEFT)
        ttk.Entry(row_id, textvariable=self.user_id_var, state="readonly", width=20).pack(side=tk.LEFT, padx=(8, 0))

        self.name_var = tk.StringVar()
        self.phone_var = tk.StringVar()
        self.email_var = tk.StringVar()
        self.pw_var = tk.StringVar()

        def _row(label, var, show=None):
            r = ttk.Frame(form)
            r.pack(fill=tk.X, pady=(0, 6))
            ttk.Label(r, text=label, width=10).pack(side=tk.LEFT)
            e = ttk.Entry(r, textvariable=var, show=show)
            e.pack(side=tk.LEFT, fill=tk.X, expand=True)
            return e

        _row("Name", self.name_var)
        _row("Phone", self.phone_var)
        _row("Email", self.email_var)
        _row("Password", self.pw_var, show="*")

        btns = ttk.Frame(form)
        btns.pack(fill=tk.X, pady=(6, 0))
        self.btn_create = ttk.Button(btns, text="创建用户", command=self.on_create_user)
        self.btn_create.pack(side=tk.LEFT)
        self.btn_update = ttk.Button(btns, text="更新用户", command=self.on_update_user)
        self.btn_update.pack(side=tk.LEFT, padx=(8, 0))
        self.btn_clear = ttk.Button(btns, text="清空表单", command=self.clear_form)
        self.btn_clear.pack(side=tk.LEFT, padx=(8, 0))

        # ===== 右侧：绑定管理 =====
        bind = ttk.LabelFrame(right, text="绑定设备（device_user）", padding="10")
        bind.pack(fill=tk.BOTH, expand=True)

        row_add = ttk.Frame(bind)
        row_add.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(row_add, text="Device ID").pack(side=tk.LEFT)
        self.bind_device_id_var = tk.StringVar()
        ttk.Entry(row_add, textvariable=self.bind_device_id_var, width=18).pack(side=tk.LEFT, padx=(8, 8))
        ttk.Button(row_add, text="绑定", command=self.on_bind_device).pack(side=tk.LEFT)
        ttk.Button(row_add, text="刷新绑定列表", command=self.refresh_bindings).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(bind, text="当前绑定（选中后可解绑：物理删除）").pack(anchor=tk.W, pady=(6, 0))
        self.bind_listbox = tk.Listbox(bind, height=8)
        self.bind_listbox.pack(fill=tk.BOTH, expand=True, pady=(6, 6))

        ttk.Button(bind, text="解绑（删除该绑定）", command=self.on_unbind_device).pack(anchor=tk.E)

        # 缓存：搜索结果 users
        self._users_cache: List[Dict[str, Any]] = []

    # ---------- UI 辅助 ----------
    def set_status(self, msg: str, ok: Optional[bool] = None):
        self.status_var.set(msg)
        if ok is True:
            self.status_label.config(foreground="green")
        elif ok is False:
            self.status_label.config(foreground="red")
        else:
            self.status_label.config(foreground="black")

    def clear_form(self):
        logger.info("[USER_ADMIN][UI] clear_form")
        self._selected_user = None
        self.user_id_var.set("")
        self.name_var.set("")
        self.phone_var.set("")
        self.email_var.set("")
        self.pw_var.set("")
        self.bind_device_id_var.set("")
        self.bind_listbox.delete(0, "end")
        self._bindings = []
        self.set_status("已清空表单", ok=True)

    def _require_selected_user_id(self) -> Optional[int]:
        uid = (self.user_id_var.get() or "").strip()
        if not uid.isdigit():
            self.set_status("请先在左侧选中一个用户", ok=False)
            return None
        return int(uid)

    # ---------- 事件：搜索 ----------
    def on_search(self):
        kw = (self.search_var.get() or "").strip()
        logger.info(f"[USER_ADMIN][UI] on_search keyword={kw!r}")

        if not kw:
            self.set_status("请输入姓名或电话再搜索", ok=False)
            return

        self.set_status("搜索中...", ok=None)

        def worker():
            try:
                res = find_users_by_name_or_phone(kw)
                logger.info(f"[USER_ADMIN][UI] search_result ok={res.get('ok')} count={res.get('count')}")
                users = res.get("users") or []
                self.frame.after(0, lambda: self._render_users(users, res))
            except Exception as e:
                logger.exception("[USER_ADMIN][UI] search_worker_failed")
                self.frame.after(0, lambda: self.set_status(f"搜索失败：{e}", ok=False))

        threading.Thread(target=worker, daemon=True).start()

    def _render_users(self, users: List[Dict[str, Any]], res: Dict[str, Any]):
        self._users_cache = users
        self.user_listbox.delete(0, "end")

        if not res.get("ok"):
            self.set_status(res.get("error", {}).get("message", "搜索失败"), ok=False)
            return

        if not users:
            self.set_status("未找到用户", ok=False)
            return

        for u in users:
            # 展示：id / name / phone / email
            self.user_listbox.insert("end", f"ID={u['id']} | {u.get('name')} | {u.get('phone')} | {u.get('email')}")
        self.set_status(f"找到 {len(users)} 个用户，点击左侧列表选择", ok=True)

    # ---------- 事件：选中用户 ----------
    def on_pick_user(self, _evt=None):
        sel = self.user_listbox.curselection()
        if not sel:
            return
        idx = int(sel[0])
        if idx < 0 or idx >= len(self._users_cache):
            return

        u = self._users_cache[idx]
        self._selected_user = u

        logger.info(f"[USER_ADMIN][UI] pick_user user_id={u.get('id')} name={u.get('name')!r}")

        # 回填表单（注意：password_hash 不回填）
        self.user_id_var.set(str(u.get("id", "")))
        self.name_var.set(u.get("name") or "")
        self.phone_var.set(u.get("phone") or "")
        self.email_var.set(u.get("email") or "")
        self.pw_var.set("")

        self.set_status(f"已选中用户：ID={u.get('id')}（可更新信息/管理绑定）", ok=True)
        self.refresh_bindings()

    # ---------- 事件：创建用户 ----------
    def on_create_user(self):
        name = (self.name_var.get() or "").strip()
        phone = (self.phone_var.get() or "").strip()
        email = (self.email_var.get() or "").strip()
        pw = (self.pw_var.get() or "").strip()

        logger.info(f"[USER_ADMIN][UI] create_user name={name!r} phone={phone!r} email={email!r}")

        if not name or not phone or not pw:
            self.set_status("创建用户需要：name / phone / password", ok=False)
            return

        self.set_status("创建中...", ok=None)

        def worker():
            try:
                res = create_user(name=name, phone=phone, email=(email or None), password_plain=pw)
                logger.info(f"[USER_ADMIN][UI] create_user_result ok={res.get('ok')} user_id={res.get('user_id')}")
                self.frame.after(0, lambda: self._after_create(res))
            except Exception as e:
                logger.exception("[USER_ADMIN][UI] create_user_failed")
                self.frame.after(0, lambda: self.set_status(f"创建失败：{e}", ok=False))

        threading.Thread(target=worker, daemon=True).start()

    def _after_create(self, res: Dict[str, Any]):
        if not res.get("ok"):
            err = res.get("error", {}).get("message", "创建失败")
            self.set_status(err, ok=False)
            messagebox.showerror("创建用户失败", err)
            return

        uid = res.get("user_id")
        self.set_status(f"创建成功：user_id={uid}（建议再搜索一次确认）", ok=True)
        messagebox.showinfo("创建成功", f"创建用户成功：ID={uid}")

    # ---------- 事件：更新用户 ----------
    def on_update_user(self):
        uid = self._require_selected_user_id()
        if uid is None:
            return

        name = (self.name_var.get() or "").strip()
        email = (self.email_var.get() or "").strip()
        pw = (self.pw_var.get() or "").strip()

        # 更新允许：name/email/password（phone 不给改）
        logger.info(f"[USER_ADMIN][UI] update_user user_id={uid} name={name!r} email={email!r} pw={'***' if pw else None}")

        self.set_status("更新中...", ok=None)

        def worker():
            try:
                res = update_user_info(
                    user_id=uid,
                    name=(name or None),
                    email=(email if email != "" else ""),  # 允许置空：传 "" 给 db.py 逻辑处理成 NULL
                    password_plain=(pw or None),
                )
                logger.info(f"[USER_ADMIN][UI] update_user_result ok={res.get('ok')} updated_rows={res.get('updated_rows')}")
                self.frame.after(0, lambda: self._after_update(res))
            except Exception as e:
                logger.exception("[USER_ADMIN][UI] update_user_failed")
                self.frame.after(0, lambda: self.set_status(f"更新失败：{e}", ok=False))

        threading.Thread(target=worker, daemon=True).start()

    def _after_update(self, res: Dict[str, Any]):
        if not res.get("ok"):
            err = res.get("error", {}).get("message", "更新失败")
            self.set_status(err, ok=False)
            messagebox.showerror("更新用户失败", err)
            return

        rows = res.get("updated_rows", 0)
        self.set_status(f"更新成功：影响行数={rows}（可重新搜索确认）", ok=True)
        messagebox.showinfo("更新成功", f"更新用户成功，影响行数={rows}")
        # 清掉密码框，避免误操作
        self.pw_var.set("")

    # ---------- 绑定：刷新 ----------
    def refresh_bindings(self):
        uid = self._require_selected_user_id()
        if uid is None:
            return

        logger.info(f"[USER_ADMIN][UI] refresh_bindings user_id={uid}")
        self.set_status("查询绑定中...", ok=None)

        def worker():
            try:
                res = list_bound_devices_for_user(uid)
                logger.info(f"[USER_ADMIN][UI] list_bindings_result ok={res.get('ok')} count={res.get('count')}")
                self.frame.after(0, lambda: self._render_bindings(res))
            except Exception as e:
                logger.exception("[USER_ADMIN][UI] refresh_bindings_failed")
                self.frame.after(0, lambda: self.set_status(f"查询绑定失败：{e}", ok=False))

        threading.Thread(target=worker, daemon=True).start()

    def _render_bindings(self, res: Dict[str, Any]):
        self.bind_listbox.delete(0, "end")

        if not res.get("ok"):
            err = res.get("error", {}).get("message", "查询绑定失败")
            self.set_status(err, ok=False)
            return

        bindings = res.get("bindings") or []
        self._bindings = bindings

        if not bindings:
            self.set_status("该用户暂无绑定设备", ok=True)
            return

        for b in bindings:
            self.bind_listbox.insert("end", f"device_id={b['device_id']} | {b.get('device_name')} | created_at={b.get('created_at')}")
        self.set_status(f"绑定设备 {len(bindings)} 条", ok=True)

    # ---------- 绑定：新增 ----------
    def on_bind_device(self):
        uid = self._require_selected_user_id()
        if uid is None:
            return

        did_raw = (self.bind_device_id_var.get() or "").strip()
        if not did_raw.isdigit():
            self.set_status("Device ID 必须是数字", ok=False)
            return
        did = int(did_raw)

        logger.info(f"[USER_ADMIN][UI] bind_device user_id={uid} device_id={did}")
        self.set_status("绑定中...", ok=None)

        def worker():
            try:
                res = add_device_binding(uid, did)
                logger.info(f"[USER_ADMIN][UI] bind_device_result ok={res.get('ok')} binding_id={res.get('binding_id')}")
                self.frame.after(0, lambda: self._after_bind(res, uid))
            except Exception as e:
                logger.exception("[USER_ADMIN][UI] bind_device_failed")
                self.frame.after(0, lambda: self.set_status(f"绑定失败：{e}", ok=False))

        threading.Thread(target=worker, daemon=True).start()

    def _after_bind(self, res: Dict[str, Any], uid: int):
        if not res.get("ok"):
            err = res.get("error", {}).get("message", "绑定失败")
            self.set_status(err, ok=False)
            messagebox.showerror("绑定失败", err)
            return

        self.set_status(f"绑定成功：binding_id={res.get('binding_id')}（将自动刷新）", ok=True)
        messagebox.showinfo("绑定成功", f"绑定成功：binding_id={res.get('binding_id')}")
        self.bind_device_id_var.set("")
        self.refresh_bindings()

    # ---------- 解绑：物理删除 ----------
    def on_unbind_device(self):
        uid = self._require_selected_user_id()
        if uid is None:
            return

        sel = self.bind_listbox.curselection()
        if not sel:
            self.set_status("请先在绑定列表中选中一条记录再解绑", ok=False)
            return

        idx = int(sel[0])
        if idx < 0 or idx >= len(self._bindings):
            self.set_status("解绑失败：选择项越界", ok=False)
            return

        device_id = int(self._bindings[idx]["device_id"])

        logger.info(f"[USER_ADMIN][UI] unbind_device(user_id={uid}, device_id={device_id})")
        if not messagebox.askyesno("确认解绑", f"确认解绑 device_id={device_id} 吗？\n（将物理删除 device_user 记录）"):
            logger.info("[USER_ADMIN][UI] unbind_cancelled_by_user")
            return

        self.set_status("解绑中（物理删除）...", ok=None)

        def worker():
            try:
                res = delete_device_binding(uid, device_id)
                logger.info(f"[USER_ADMIN][UI] unbind_result ok={res.get('ok')} deleted_rows={res.get('deleted_rows')}")
                self.frame.after(0, lambda: self._after_unbind(res))
            except Exception as e:
                logger.exception("[USER_ADMIN][UI] unbind_failed")
                self.frame.after(0, lambda: self.set_status(f"解绑失败：{e}", ok=False))

        threading.Thread(target=worker, daemon=True).start()

    def _after_unbind(self, res: Dict[str, Any]):
        if not res.get("ok"):
            err = res.get("error", {}).get("message", "解绑失败")
            self.set_status(err, ok=False)
            messagebox.showerror("解绑失败", err)
            return

        deleted = int(res.get("deleted_rows", 0))
        if deleted <= 0:
            self.set_status("未删除任何记录（可能本来就不存在该绑定）", ok=False)
            messagebox.showwarning("解绑结果", "未删除任何记录（可能本来就不存在该绑定）")
        else:
            self.set_status(f"解绑成功：deleted_rows={deleted}（已物理删除）", ok=True)
            messagebox.showinfo("解绑成功", f"解绑成功：deleted_rows={deleted}")

        self.refresh_bindings()

# V2.2.7
class DeviceLatestDataQueryWidget:
    """
    查询某设备“最新一条数据”：
    - 输入：设备名 或 设备ID（支持下拉联想）
    - 点击按钮：查询最新数据（复用 AsyncDeviceDataDownloader.get_latest_device_data_async）
    - 展示：JSON pretty
    """

    def __init__(self, parent, get_downloader: Callable[[], Optional[AsyncDeviceDataDownloader]]):
        self.parent = parent
        self.get_downloader = get_downloader

        self.frame = ttk.LabelFrame(parent, text="最新数据查询", padding="10")

        row = ttk.Frame(self.frame)
        row.pack(fill=tk.X, pady=(0, 6))

        self.query_var = tk.StringVar()
        self.entry = ttk.Entry(row, textvariable=self.query_var, width=40)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self._setting_var = False
        self._picked_device_id: Optional[int] = None

        self._ac = AutoCompletePopup(
            owner_frame=self.frame,
            entry=self.entry,
            fetcher=self._fetch_suggestions,
            on_pick=self._on_pick_suggestion,
        )

        def _on_query_change(*_):
            if not self._setting_var:
                self._picked_device_id = None
            self._ac.on_typing(self.query_var.get())

        self.query_var.trace_add("write", _on_query_change)

        self.btn = ttk.Button(row, text="查询最新数据", command=self.query_latest)
        self.btn.pack(side=tk.LEFT, padx=(8, 0))

        self.status_var = tk.StringVar(value="输入设备名或ID，点击“查询最新数据”。")
        self.status_label = ttk.Label(self.frame, textvariable=self.status_var)
        self.status_label.pack(anchor=tk.W, pady=(0, 6))

        self.text = scrolledtext.ScrolledText(self.frame, height=10, state=tk.DISABLED, wrap=tk.WORD)
        self.text.pack(fill=tk.BOTH, expand=True)

    def _set_text(self, s: str):
        self.text.config(state=tk.NORMAL)
        self.text.delete("1.0", "end")
        self.text.insert("end", s)
        self.text.config(state=tk.DISABLED)

    def _fetch_suggestions(self, kw: str) -> List[Tuple[int, str]]:
        kw = (kw or "").strip()
        if not kw:
            return []

        if kw.isdigit():
            try:
                rows_by_id = search_devices_by_id(kw, limit=30)
            except Exception:
                rows_by_id = []
            try:
                rows_by_name = search_devices_by_name(kw, limit=30)
            except Exception:
                rows_by_name = []

            seen = set()
            merged: List[Tuple[int, str]] = []
            for did, name in (rows_by_id + rows_by_name):
                if did not in seen:
                    merged.append((did, name))
                    seen.add(did)
            return merged

        try:
            return search_devices_by_name(kw, limit=30) or []
        except Exception:
            return []

    def _on_pick_suggestion(self, did: int, name: str):
        self._picked_device_id = did
        self._setting_var = True
        try:
            self.query_var.set(name)
            self.entry.icursor("end")
        finally:
            self._setting_var = False

    def _resolve_device(self, raw: str) -> Tuple[Optional[int], Optional[str], str]:
        q = (raw or "").strip()
        if not q:
            return None, None, "请输入设备名或设备ID"

        if q.isdigit():
            did = int(q)
            try:
                rows = get_device_by_id(did)
            except Exception:
                rows = []
            if len(rows) == 1:
                return rows[0][0], rows[0][1], ""

            try:
                cand = search_devices_by_id(q, limit=10)
            except Exception:
                cand = []
            if len(cand) == 1:
                return cand[0][0], cand[0][1], ""
            if cand:
                return None, None, "ID 非唯一，请输入更完整ID。候选：\n" + "\n".join([f"{i} {n}" for i, n in cand])
            return None, None, "未找到该设备ID"

        try:
            exact = get_device_by_exact_name(q)
        except Exception:
            exact = []
        if len(exact) == 1:
            return exact[0][0], exact[0][1], ""

        try:
            cand = search_devices_by_name(q, limit=10)
        except Exception:
            cand = []
        if len(cand) == 1:
            return cand[0][0], cand[0][1], ""
        if cand:
            return None, None, "名称匹配不唯一，请更精确。候选：\n" + "\n".join([f"{i} {n}" for i, n in cand])
        return None, None, "未找到该设备名称"

    def query_latest(self):
        raw = self.query_var.get().strip()

        if self._picked_device_id is not None:
            device_id = self._picked_device_id
            device_name = raw or ""
            err = ""
        else:
            device_id, device_name, err = self._resolve_device(raw)

        if err:
            self.status_label.config(foreground="red")
            self.status_var.set(err)
            self._set_text("")
            return

        downloader = self.get_downloader()
        if downloader is None:
            self.status_label.config(foreground="red")
            self.status_var.set("下载器未初始化，无法查询最新数据")
            return

        self.status_label.config(foreground="black")
        self.status_var.set(f"正在查询最新数据：{device_name} (ID={device_id}) ...")
        self._set_text("")

        root = self.frame.winfo_toplevel()

        def worker():
            loop = None
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                payload = loop.run_until_complete(downloader.get_latest_device_data_async(device_id))

                ok = bool(payload) and bool(payload.get("row"))  # ✅ 有row就算成功
                msg = "OK" if ok else "无数据/未找到"

                pretty = json.dumps(payload, ensure_ascii=False, indent=2, default=str)

                root.after(
                    0,
                    lambda ok=ok, pretty=pretty, msg=msg, device_name=device_name, device_id=device_id: (
                        self.status_label.config(foreground=("green" if ok else "red")),
                        self.status_var.set(
                            f"查询成功：{device_name} (ID={device_id})" if ok else f"查询失败：{msg}"
                        ),
                        self._set_text(pretty),
                    ),
                )

            except Exception as e:
                en = str(e)  # 关键：先把异常转成字符串保存下来
                root.after(0, lambda err=en: (self.status_label.config(foreground="red"),
                                                self.status_var.set(f"查询失败: {err}"),
                                                self._set_text(err)
                                                ))

            finally:
                    if loop is not None:
                        try:
                            loop.close()
                        except Exception:
                            pass

        threading.Thread(target=worker, daemon=True).start()

class DateRangeWidget:
    """日期范围选择组件"""

    def __init__(self, parent):
        self.parent = parent

        # 创建日期范围框架
        self.frame = ttk.LabelFrame(parent, text="时间范围", padding="10")

        # 创建水平布局框架
        date_frame = ttk.Frame(self.frame)
        date_frame.pack(fill=tk.X)

        # 开始时间
        start_frame = ttk.Frame(date_frame)
        start_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))

        ttk.Label(start_frame, text="开始时间").pack(anchor=tk.W)
        self.start_var = tk.StringVar(
            value=(datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d 00:00:00")
        )
        self.start_entry = ttk.Entry(start_frame, textvariable=self.start_var, width=20)
        self.start_entry.pack(fill=tk.X)

        # 结束时间
        end_frame = ttk.Frame(date_frame)
        end_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Label(end_frame, text="结束时间").pack(anchor=tk.W)
        self.end_var = tk.StringVar(
            value=datetime.now().strftime("%Y-%m-%d 23:59:59")
        )
        self.end_entry = ttk.Entry(end_frame, textvariable=self.end_var, width=20)
        self.end_entry.pack(fill=tk.X)

    def get_date_range(self) -> tuple[str, str]:
        """获取日期范围"""
        return self.start_var.get(), self.end_var.get()

    def validate_dates(self) -> bool:
        """验证日期格式"""
        start_str, end_str = self.get_date_range()
        try:
            start = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
            end = datetime.strptime(end_str, "%Y-%m-%d %H:%M:%S")

            if start >= end:
                return False

            return True
        except ValueError:
            return False


class ContentTypeWidget:
    """内容类型与图片选项组件"""

    def __init__(self, parent):
        self.parent = parent

        # 创建内容类型框架
        self.frame = ttk.LabelFrame(parent, text="下载选项", padding="10")

        # 标题
        ttk.Label(self.frame, text="选择下载内容类型:").pack(anchor=tk.W, pady=(0, 5))

        # 第一行选项
        options_frame1 = ttk.Frame(self.frame)
        options_frame1.pack(fill=tk.X, pady=(0, 5))

        self.data_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(options_frame1, text="设备数据", variable=self.data_var).pack(side=tk.LEFT, padx=(0, 10))

        self.image_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(options_frame1, text="图片数据", variable=self.image_var).pack(side=tk.LEFT, padx=(0, 10))

        self.zip_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(options_frame1, text="打包为ZIP文件", variable=self.zip_var).pack(side=tk.LEFT)

        # 第二行选项
        options_frame2 = ttk.Frame(self.frame)
        options_frame2.pack(fill=tk.X, pady=(0, 5))

        self.thumbnail_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(options_frame2, text="下载缩略图", variable=self.thumbnail_var).pack(side=tk.LEFT, padx=(0, 10))

        self.rename_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(options_frame2, text="重命名图片", variable=self.rename_var).pack(side=tk.LEFT)

        # v2.2.2 添加功能Excel列名使用原始Key（不映射）
        self.rawkey_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            options_frame2,
            text="Excel列名使用原始Key（不映射）",
            variable=self.rawkey_var
        ).pack(side=tk.LEFT, padx=(10, 0))

        # 重命名格式输入
        rename_frame = ttk.Frame(self.frame)
        rename_frame.pack(fill=tk.X)

        self.rename_format_var = tk.StringVar(value="%Y-%m-%d %H-%M-%S")
        self.rename_entry = ttk.Entry(
            rename_frame,
            textvariable=self.rename_format_var,
            width=50
        )
        self.rename_entry.pack(fill=tk.X)
        hint_label = ttk.Label(rename_frame, text="输入日期格式化字符串，如 %Y-%m-%d %H-%M-%S 生成格式: 2025-01-01 12-30-45")
        hint_label2 = ttk.Label(rename_frame, text="常用格式: %Y年%m月%d日%H时 或 %Y%m%d_%H%M (注意:避免使用:/?*\"<>|等字符)")
        hint_label.pack(anchor=tk.W)
        hint_label2.pack(anchor=tk.W)

    # v2.2.2 添加功能Excel列名使用原始Key（不映射）
    def use_raw_keys(self) -> bool:
        """是否启用：按JSON原始key导出Excel列名"""
        return bool(self.rawkey_var.get())

    def get_content_types(self) -> List[str]:
        """获取选择的内容类型"""
        contents = []
        if self.data_var.get():
            contents.append("data")
        if self.image_var.get():
            contents.append("image")
        return contents

    def should_zip(self) -> bool:
        """是否需要打包ZIP"""
        return self.zip_var.get()

    def should_thumbnail(self) -> bool:
        """是否下载缩略图"""
        return self.thumbnail_var.get()

    def get_rename_options(self) -> tuple[bool, Optional[str]]:
        """返回是否重命名以及重命名格式（可为空）"""
        enabled = self.rename_var.get()
        fmt_input = self.rename_format_var.get().strip()
        return enabled, (fmt_input or None)


class DownloadDirWidget:
    """下载目录选择组件"""

    def __init__(self, parent):
        self.parent = parent

        # 创建下载目录框架
        self.frame = ttk.LabelFrame(parent, text="下载目录", padding="10")

        # 目录输入框架
        dir_frame = ttk.Frame(self.frame)
        dir_frame.pack(fill=tk.X, pady=(0, 5))

        self.dir_var = tk.StringVar(value="./tmp/")
        self.dir_entry = ttk.Entry(dir_frame, textvariable=self.dir_var)
        self.dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))

        # 浏览按钮
        self.browse_btn = ttk.Button(dir_frame, text="浏览", command=self.browse_directory)
        self.browse_btn.pack(side=tk.RIGHT)

        # 提示标签
        self.hint_var = tk.StringVar(value="默认为 ./tmp/")
        self.hint_label = ttk.Label(self.frame, textvariable=self.hint_var)
        self.hint_label.pack(anchor=tk.W)

    def browse_directory(self):
        """浏览目录"""
        directory = filedialog.askdirectory(initialdir=self.dir_var.get())
        if directory:
            self.dir_var.set(directory)

    def get_download_dir(self) -> str:
        """获取下载目录路径"""
        return self.dir_var.get().strip() or "./tmp/"

    def validate_directory(self) -> bool:
        """验证目录路径是否有效"""
        dir_path = self.get_download_dir()
        try:
            path = Path(dir_path)
            path.mkdir(parents=True, exist_ok=True)
            self.hint_var.set("目录有效")
            self.hint_label.config(foreground="green")
            return True
        except Exception as e:
            self.hint_var.set(f"目录无效: {str(e)}")
            self.hint_label.config(foreground="red")
            return False


class LogWidget:
    """日志显示组件"""

    def __init__(self, parent):
        self.parent = parent
        self.log_messages = []

        # 创建日志框架
        self.frame = ttk.LabelFrame(parent, text="日志信息", padding="10")

        # 日志文本区域
        self.log_text = scrolledtext.ScrolledText(
            self.frame,
            height=12,
            width=60,
            state=tk.DISABLED,
            wrap=tk.WORD
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def add_log(self, message: str, level: str = "INFO"):
        """添加日志消息"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] [{level}] {message}\n"
        self.log_messages.append(formatted_message)

        # 更新文本区域
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, formatted_message)

        # 保留最近100条日志
        if len(self.log_messages) > 100:
            self.log_messages = self.log_messages[-100:]
            self.log_text.delete(1.0, tk.END)
            self.log_text.insert(1.0, "".join(self.log_messages))

        self.log_text.config(state=tk.DISABLED)
        self.log_text.see(tk.END)


class DownloadManagerApp:
    """主应用类"""

    def __init__(self):
        self.downloader = None
        self.current_worker = None
        self.download_dir = "./tmp/"
        self.download_thread = None
        self.is_downloading = False

        # v2.2.4
        self._active_downloader = None  # 本次下载实际使用的 downloader
        self._download_loop = None  # 下载线程里的 event loop
        self._download_task = None  # loop 上跑的 task（用于强制取消）

        # 创建主窗口
        self.root = tk.Tk()
        self.root.title("设备数据下载器 - HOTUNS")

        # v2.2.5+
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.root.geometry("1000x780")
        self.root.minsize(800, 800)

        # 设置编码和字体
        self.setup_fonts()

        # v2.2.5
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # 设置窗口图标（如果有的话）
        try:
            # self.root.iconbitmap("icon.ico")  # 如果有图标文件
            pass
        except:
            pass

        self.setup_ui()
        self.setup_bindings()

        # 初始化下载器
        self.update_downloader()

    # v2.2.5
    def on_close(self):
        # 1) 发取消
        try:
            self.handle_cancel_download()
        except Exception:
            pass

        # 2) 给下载线程一点点时间收尾（可选）
        try:
            if self.download_thread and self.download_thread.is_alive():
                self.download_thread.join(timeout=1.5)
        except Exception:
            pass

        # 3) 关闭 UI
        try:
            self.root.quit()
            self.root.destroy()
        except Exception:
            pass

        # 4) 兜底：强制结束整个 Python 进程（防止 executor 线程残留）
        import os
        os._exit(0)

    def setup_fonts(self):
        """设置字体以支持中文显示"""
        # 设置系统编码
        if hasattr(sys, 'setdefaultencoding'):
            sys.setdefaultencoding('utf-8')

        # 设置默认字体，优先使用支持中文的字体
        if sys.platform == "win32":
            default_font = ("Microsoft YaHei", 9)
        elif sys.platform == "darwin":
            default_font = ("PingFang SC", 9)
        else:
            # Linux系统，尝试多种中文字体
            import tkinter.font as tkFont
            available_fonts = tkFont.families()
            chinese_fonts = ["Noto Sans CJK SC", "WenQuanYi Micro Hei", "DejaVu Sans", "Liberation Sans"]
            selected_font = "TkDefaultFont"

            for font in chinese_fonts:
                if font in available_fonts:
                    selected_font = font
                    break

            default_font = (selected_font, 9)

        # 配置ttk样式
        style = ttk.Style()

        # 尝试设置主题
        try:
            if sys.platform == "win32":
                style.theme_use('vista')
            elif sys.platform == "darwin":
                style.theme_use('aqua')
            else:
                style.theme_use('clam')
        except:
            pass

        # 配置字体
        style.configure(".", font=default_font)
        style.configure("TLabel", font=default_font)
        style.configure("TButton", font=default_font)
        style.configure("TCheckbutton", font=default_font)
        style.configure("TEntry", font=default_font)
        style.configure("TLabelFrame.Label", font=default_font)

        # 设置重点按钮样式
        style.configure("Accent.TButton", font=default_font)

        # 设置根窗口的默认字体
        self.root.option_add('*Font', default_font)

    # v2.3.2+
    def setup_ui(self):
        """设置用户界面（两列布局：左=工具面板Tab，右=状态/日志）"""

        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 两列：左工具面板 / 右日志
        left_frame = ttk.Frame(main_frame)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # ========== 左侧：工具面板 ==========
        left_title = ttk.Label(left_frame, text="运维工具", font=("TkDefaultFont", 12, "bold"))
        left_title.pack(anchor=tk.W, pady=(0, 10))

        notebook = ttk.Notebook(left_frame)
        notebook.pack(fill=tk.BOTH, expand=True)

        tab_download = ttk.Frame(notebook)
        tab_device = ttk.Frame(notebook)
        tab_user = ttk.Frame(notebook)

        notebook.add(tab_download, text="数据下载")
        notebook.add(tab_device, text="设备查询")
        notebook.add(tab_user, text="用户管理")

        # --- Tab 1：设备数据下载配置（原 left_frame 的内容搬进来）---
        config_container = ttk.Frame(tab_download)
        config_container.pack(fill=tk.BOTH, expand=True)

        # 原来左侧的标题可选保留/不保留，这里不再重复标题
        # config_label = ttk.Label(config_container, text="设备数据下载配置", font=("TkDefaultFont", 12, "bold"))
        # config_label.pack(anchor=tk.W, pady=(0, 10))

        # 原 left_frame 里的 config_row / config_col_left/right 结构你之前已经简化为全在左列，
        # 这里我们保持一致：按你当前版本把四个组件纵向排列即可
        self.dir_widget = DownloadDirWidget(config_container)
        self.dir_widget.frame.pack(fill=tk.X, pady=(0, 10))

        self.device_widget = DeviceNameSelectionWidget(config_container)
        self.device_widget.frame.pack(fill=tk.X, pady=(0, 10))

        self.date_widget = DateRangeWidget(config_container)
        self.date_widget.frame.pack(fill=tk.X, pady=(0, 10))

        self.content_widget = ContentTypeWidget(config_container)
        self.content_widget.frame.pack(fill=tk.X, pady=(0, 10))

        # 按钮区域（开始下载 / 测试连接）
        button_frame = ttk.Frame(config_container)
        button_frame.pack(fill=tk.X, pady=(6, 0))

        self.download_btn = ttk.Button(
            button_frame,
            text="开始下载",
            command=self.handle_download,
            style="Accent.TButton"
        )
        self.download_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.test_btn = ttk.Button(
            button_frame,
            text="测试连接",
            command=self.handle_test_connections
        )
        self.test_btn.pack(side=tk.LEFT)

        # --- Tab 2：设备查询（保持你原本内容）---
        query_container = ttk.LabelFrame(tab_device, text="设备配置与最新数据", padding="10")
        query_container.pack(fill=tk.BOTH, expand=True)

        self.config_query_widget = DeviceConfigQueryWidget(
            query_container,
            get_downloader=lambda: self.downloader
        )
        self.config_query_widget.frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        # self.latest_data_query_widget = DeviceLatestDataQueryWidget(
        #     query_container,
        #     get_downloader=lambda: self.downloader
        # )
        # self.latest_data_query_widget.frame.pack(fill=tk.BOTH, expand=True)

        # --- Tab 3：用户管理 ---
        self.user_admin_widget = UserAdminWidget(tab_user)
        self.user_admin_widget.frame.pack(fill=tk.BOTH, expand=True)

        # ========== 右侧：状态和日志 ==========
        status_label = ttk.Label(right_frame, text="状态和日志", font=("TkDefaultFont", 12, "bold"))
        status_label.pack(anchor=tk.W, pady=(0, 10))

        self.progress_widget = DownloadProgressWidget(right_frame)
        self.progress_widget.frame.pack(fill=tk.X, pady=(0, 10))

        self.log_widget = LogWidget(right_frame)
        self.log_widget.frame.pack(fill=tk.BOTH, expand=True)

    # v2.3.2-
    # def setup_ui(self):
    #     """设置用户界面"""
    #     # 创建主框架
    #     main_frame = ttk.Frame(self.root, padding="10")
    #     main_frame.pack(fill=tk.BOTH, expand=True)
    #
    #     # 创建左右分栏
    #     left_frame = ttk.Frame(main_frame)
    #     left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
    #     left_frame.columnconfigure(0, weight=1)  # 只有1列，允许横向拉伸
    #     left_frame.rowconfigure(1, weight=1)  # 第1行(内容区)允许纵向拉伸
    #     # 第0行(标题)和第2行(按钮)不设置weight => 高度固定
    #
    #     # V2.2.7+
    #     mid_frame = ttk.Frame(main_frame)
    #     mid_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
    #
    #     right_frame = ttk.Frame(main_frame)
    #     right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
    #
    #     # 左侧配置区域
    #     config_label = ttk.Label(left_frame, text="设备数据下载配置", font=("TkDefaultFont", 12, "bold"))
    #     config_label.grid(row=0, column=0, sticky="w", pady=(0, 10))
    #
    #     # 创建配置组件的容器
    #     config_container = ttk.Frame(left_frame)
    #     config_container.grid(row=1, column=0, sticky="nsew")  # nsew=上下左右都贴边
    #
    #     # V2.2.7+
    #     # 配置区两列：左列=下载目录+设备选择+时间范围；右列=下载选项
    #     config_row = ttk.Frame(config_container)
    #     config_row.pack(fill=tk.BOTH, expand=True)
    #
    #     config_col_left = ttk.Frame(config_row)
    #     config_col_left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
    #
    #     config_col_right = ttk.Frame(config_row)
    #     config_col_right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
    #
    #     # V2.2.7-
    #     # # 上半部分：目录和设备选择
    #     # top_config = ttk.Frame(config_container)
    #     # top_config.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
    #     #
    #     # top_left = ttk.Frame(top_config)
    #     # top_left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
    #     #
    #     # top_right = ttk.Frame(top_config)
    #     # top_right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
    #     #
    #     # # 下半部分：时间和内容选择
    #     # bottom_config = ttk.Frame(config_container)
    #     # bottom_config.pack(fill=tk.X, pady=(0, 10))
    #     #
    #     # bottom_left = ttk.Frame(bottom_config)
    #     # bottom_left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
    #     #
    #     # bottom_right = ttk.Frame(bottom_config)
    #     # bottom_right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
    #
    #     # v2.2.7+
    #     self.dir_widget = DownloadDirWidget(config_col_left)
    #     self.dir_widget.frame.pack(fill=tk.X, pady=(0, 10))
    #
    #     self.device_widget = DeviceNameSelectionWidget(config_col_left)
    #     self.device_widget.frame.pack(fill=tk.X, pady=(0, 10))
    #
    #     self.date_widget = DateRangeWidget(config_col_left)
    #     self.date_widget.frame.pack(fill=tk.X, pady=(0, 10))
    #
    #     self.content_widget = ContentTypeWidget(config_col_left)
    #     self.content_widget.frame.pack(fill=tk.X)
    #
    #     # v2.2.7-
    #     # # 创建各个组件
    #     # self.dir_widget = DownloadDirWidget(top_left)
    #     # self.dir_widget.frame.pack(fill=tk.X, pady=(0, 10))
    #     #
    #     # #self.device_widget = DeviceSelectionWidget(top_left)
    #     # self.device_widget = DeviceNameSelectionWidget(top_left) # v2.0
    #     # self.device_widget.frame.pack(fill=tk.X)
    #     #
    #     # # v2.2
    #     # self.config_query_widget = DeviceConfigQueryWidget(
    #     #     top_left,
    #     #     get_downloader=lambda: self.downloader
    #     # )
    #     # self.config_query_widget.frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
    #     #
    #     # self.date_widget = DateRangeWidget(top_right)
    #     # self.date_widget.frame.pack(fill=tk.X, pady=(0, 10))
    #     #
    #     # self.content_widget = ContentTypeWidget(top_right)
    #     # self.content_widget.frame.pack(fill=tk.X)
    #
    #     # 按钮区域
    #     button_frame = ttk.Frame(left_frame)
    #     button_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
    #
    #     self.download_btn = ttk.Button(
    #         button_frame,
    #         text="开始下载",
    #         command=self.handle_download,
    #         style="Accent.TButton"
    #     )
    #     self.download_btn.pack(side=tk.LEFT, padx=(0, 10))
    #
    #     self.test_btn = ttk.Button(
    #         button_frame,
    #         text="测试连接",
    #         command=self.handle_test_connections
    #     )
    #     self.test_btn.pack(side=tk.LEFT)
    #
    #     # v2.3.1+
    #     # ===== 中间栏：Tab（设备查询 / 用户管理）=====
    #     mid_label = ttk.Label(mid_frame, text="工具面板", font=("TkDefaultFont", 12, "bold"))
    #     mid_label.pack(anchor=tk.W, pady=(0, 10))
    #
    #     notebook = ttk.Notebook(mid_frame)
    #     notebook.pack(fill=tk.BOTH, expand=True)
    #
    #     tab_device = ttk.Frame(notebook)
    #     tab_user = ttk.Frame(notebook)
    #
    #     notebook.add(tab_device, text="设备查询")
    #     notebook.add(tab_user, text="用户管理")
    #
    #     # --- 设备查询 Tab（保持你原本内容）---
    #     query_container = ttk.LabelFrame(tab_device, text="设备配置与最新数据", padding="10")
    #     query_container.pack(fill=tk.BOTH, expand=True)
    #
    #     self.config_query_widget = DeviceConfigQueryWidget(
    #         query_container,
    #         get_downloader=lambda: self.downloader
    #     )
    #     self.config_query_widget.frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
    #
    #     self.latest_data_query_widget = DeviceLatestDataQueryWidget(
    #         query_container,
    #         get_downloader=lambda: self.downloader
    #     )
    #     self.latest_data_query_widget.frame.pack(fill=tk.BOTH, expand=True)
    #
    #     # --- 用户管理 Tab（新增）---
    #     self.user_admin_widget = UserAdminWidget(tab_user)
    #     self.user_admin_widget.frame.pack(fill=tk.BOTH, expand=True)
    #
    #     # v2.3.1-
    #     # # V2.2.7+
    #     # # ===== 中间栏：设备查询（配置查询 + 最新数据查询）=====
    #     # query_label = ttk.Label(mid_frame, text="设备查询", font=("TkDefaultFont", 12, "bold"))
    #     # query_label.pack(anchor=tk.W, pady=(0, 10))
    #     #
    #     # query_container = ttk.LabelFrame(mid_frame, text="设备配置与最新数据", padding="10")
    #     # query_container.pack(fill=tk.BOTH, expand=True)
    #     #
    #     # # 设备配置查询
    #     # self.config_query_widget = DeviceConfigQueryWidget(
    #     #     query_container,
    #     #     get_downloader=lambda: self.downloader
    #     # )
    #     # self.config_query_widget.frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
    #
    #     # 最新数据查询（你要的新功能）
    #     self.latest_data_query_widget = DeviceLatestDataQueryWidget(
    #         query_container,
    #         get_downloader=lambda: self.downloader
    #     )
    #     self.latest_data_query_widget.frame.pack(fill=tk.BOTH, expand=True)
    #
    #     # 右侧状态区域
    #     status_label = ttk.Label(right_frame, text="状态和日志", font=("TkDefaultFont", 12, "bold"))
    #     status_label.pack(anchor=tk.W, pady=(0, 10))
    #
    #     self.progress_widget = DownloadProgressWidget(right_frame)
    #     self.progress_widget.frame.pack(fill=tk.X, pady=(0, 10))
    #
    #     self.log_widget = LogWidget(right_frame)
    #     self.log_widget.frame.pack(fill=tk.BOTH, expand=True)
    
    def setup_bindings(self):
        """设置键盘绑定"""
        self.root.bind('<Control-d>', lambda e: self.handle_download())
        self.root.bind('<Control-t>', lambda e: self.handle_test_connections())
        self.root.bind('<Control-q>', lambda e: self.root.quit())

        # 设置取消按钮的命令
        self.progress_widget.cancel_btn.config(command=self.handle_cancel_download)

    def update_downloader(self):
        """更新下载器实例"""
        download_dir = self.dir_widget.get_download_dir()
        self.download_dir = download_dir

        try:
            self.downloader = AsyncDeviceDataDownloader(root_path=download_dir)
            self.log_widget.add_log(f"下载器初始化成功，目录: {download_dir}", "INFO")
        except Exception as e:
            self.log_widget.add_log(f"初始化失败: {str(e)}", "ERROR")

    def handle_download(self):
        """处理下载请求"""
        if not self.is_downloading:
            self.start_download()

    def handle_test_connections(self):
        """处理连接测试请求"""
        if not self.is_downloading:
            self.test_connections()

    # v2.2.4+
    def handle_cancel_download(self):
        """处理取消下载请求：只取消下载，不退出程序，也不提前复位 UI"""
        if not self.is_downloading:
            return

        if self._active_downloader:
            self._active_downloader.cancel()

        # v2.2.5改
        # 直接 cancel 掉 asyncio task（更快停止 await）
        if self._download_loop and self._download_task:
            try:
                self._download_loop.call_soon_threadsafe(self._download_task.cancel)
                # 新增：同时 stop event loop，避免 run_until_complete 卡住
                self._download_loop.call_soon_threadsafe(self._download_loop.stop)
            except Exception:
                pass

        self.progress_widget.enable_cancel_button(False)
        self.log_widget.add_log("已发出取消请求：正在停止下载...", "WARNING")
        # 注意：这里不要改 is_downloading，不要启用开始按钮
        # 等 download_worker 真正结束后，download_finished() 会统一复位 UI
        # v2.2.5
        self.progress_widget.update_progress("取消中...（等待当前请求结束）",
                                             self.progress_widget.current_progress / 100.0)

    # v2.2.4-
    # def handle_cancel_download(self):
    #     """处理取消下载请求"""
    #     if self.is_downloading and self.downloader:
    #         self.downloader.cancel()
    #         self.log_widget.add_log("下载任务已取消", "WARNING")
    #         self.is_downloading = False
    #         self.progress_widget.enable_cancel_button(False)
    #         self.download_btn.config(state=tk.NORMAL)
    
    def test_connections(self):
        """测试数据库和OSS连接"""
        if not self.downloader:
            self.log_widget.add_log("下载器未初始化", "ERROR")
            return

        self.log_widget.add_log("开始测试连接...", "INFO")

        def test_worker():
            try:
                # 在新的事件循环中运行异步方法
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                results = loop.run_until_complete(self.downloader.test_connections())

                # 使用 after 方法在主线程中更新 UI
                self.root.after(0, self.update_test_results, results)

            except Exception as e:
                self.root.after(0, lambda: self.log_widget.add_log(f"连接测试失败: {str(e)}", "ERROR"))
            finally:
                loop.close()

        # 在新线程中运行测试
        test_thread = threading.Thread(target=test_worker, daemon=True)
        test_thread.start()

    def update_test_results(self, results):
        """更新测试结果到UI"""
        if results["database"]:
            self.log_widget.add_log("✓ 数据库连接成功", "INFO")
        else:
            self.log_widget.add_log("✗ 数据库连接失败", "ERROR")

        if results["oss"]:
            self.log_widget.add_log("✓ OSS连接成功", "INFO")
        else:
            self.log_widget.add_log("✗ OSS连接失败", "ERROR")
    
    def start_download(self):
        """开始下载任务"""
        # 验证输入
        if not self.device_widget.validate_devices():
            self.log_widget.add_log("设备选择无效", "ERROR")
            return

        if not self.date_widget.validate_dates():
            self.log_widget.add_log("日期范围无效", "ERROR")
            return

        if not self.dir_widget.validate_directory():
            self.log_widget.add_log("下载目录无效", "ERROR")
            return

        # 更新下载器目录
        self.update_downloader()
        # v2.2.4+
        self._active_downloader = self.downloader


        # v2.2.2 添加功能Excel列名使用原始Key（不映射）
        export_raw_keys = self.content_widget.use_raw_keys()
        self.downloader.export_raw_keys = export_raw_keys

        devices = self.device_widget.get_devices()
        start_time, end_time = self.date_widget.get_date_range()
        contents = self.content_widget.get_content_types()
        is_zip = self.content_widget.should_zip()
        thumb = self.content_widget.should_thumbnail()
        rename_enabled, rename_fmt = self.content_widget.get_rename_options()

        if not contents:
            self.log_widget.add_log("请至少选择一种内容类型", "ERROR")
            return

        self.log_widget.add_log(f"开始下载设备 {devices} 的数据...", "INFO")
        self.log_widget.add_log(f"下载目录: {self.download_dir}", "INFO")
        if "image" in contents:
            if thumb:
                self.log_widget.add_log("将下载缩略图 (style/small)", "INFO")
            if rename_enabled:
                self.log_widget.add_log(
                    f"图片重命名启用，格式: {rename_fmt or '保留第二个时间戳'}",
                    "INFO"
                )

        # 设置进度回调
        # v2.2.4+
        self.downloader.set_progress_callback(
            lambda msg, prog: self.root.after(0, lambda: self.progress_widget.update_progress(msg, prog))
        )
        # v2.2.4-
        # self.downloader.set_progress_callback(self.progress_widget.update_progress)

        # 设置下载状态
        self.is_downloading = True
        self.download_btn.config(state=tk.DISABLED)

        # v2.2.5改
        self.progress_widget.reset()
        self.progress_widget.enable_cancel_button(True)
        # self.progress_widget.enable_cancel_button(True)
        # self.progress_widget.reset()

        # 启动下载线程
        self.download_thread = threading.Thread(
            target=self.download_worker,
            args=(devices, contents, start_time, end_time, is_zip, thumb, rename_enabled, rename_fmt),
            daemon=True
        )
        self.download_thread.start()

    # v2.2.4+
    def download_worker(self, devices, contents, start_time, end_time, is_zip, thumb, rename_enabled, rename_fmt):
        """下载工作线程"""
        loop = None
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            self._download_loop = loop
            # 用 active_downloader，避免 self.downloader 被后续重建覆盖
            downloader = self._active_downloader

            self._download_task = loop.create_task(
                downloader.download_device_data(
                    devices=devices,
                    contents=contents,
                    start_at=start_time,
                    end_at=end_time,
                    is_zip=is_zip,
                    thumbnail=thumb,
                    rename_images=rename_enabled,
                    rename_format=rename_fmt
                )
            )

            results = loop.run_until_complete(self._download_task)

            self.root.after(0, self.update_download_results, results)

        except asyncio.CancelledError:
            # 用户取消（task.cancel）会到这里
            results = {
                "success": False,
                "processed_devices": 0,
                "failed_devices": devices,
                "download_path": None,
                "zip_path": None,
                "errors": ["下载任务被用户取消"]
            }
            self.root.after(0, self.update_download_results, results)

        # v2.2.5
        except RuntimeError as e:
            # 典型：Event loop stopped before Future completed.
            results = {
                "success": False,
                "processed_devices": 0,
                "failed_devices": devices,
                "download_path": None,
                "zip_path": None,
                "errors": [f"下载被强制停止: {e}"]
            }
            self.root.after(0, self.update_download_results, results)

        except DownloadError as e:
            self.root.after(0, lambda: self.log_widget.add_log(f"下载错误: {str(e)}", "ERROR"))
        except Exception as e:
            self.root.after(0, lambda: self.log_widget.add_log(f"未知错误: {str(e)}", "ERROR"))
        finally:
            self._download_task = None
            self._download_loop = None
            self._active_downloader = None

            # v2.2.5改
            if loop is not None:
                try:
                    pending = asyncio.all_tasks(loop)
                    for t in pending:
                        t.cancel()
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    loop.run_until_complete(loop.shutdown_asyncgens())
                except Exception:
                    pass

                try:
                    loop.close()
                except Exception:
                    pass

            self.root.after(0, self.download_finished)

    # v2.2.4-
    # def download_worker(self, devices, contents, start_time, end_time, is_zip, thumb, rename_enabled, rename_fmt):
    #     """下载工作线程"""
    #     try:
    #         # 在新的事件循环中运行异步下载
    #         loop = asyncio.new_event_loop()
    #         asyncio.set_event_loop(loop)
    #
    #         results = loop.run_until_complete(
    #             self.downloader.download_device_data(
    #                 devices=devices,
    #                 contents=contents,
    #                 start_at=start_time,
    #                 end_at=end_time,
    #                 is_zip=is_zip,
    #                 thumbnail=thumb,
    #                 rename_images=rename_enabled,
    #                 rename_format=rename_fmt
    #             )
    #         )
    #
    #         # 使用 after 方法在主线程中更新 UI
    #         self.root.after(0, self.update_download_results, results)
    #
    #     except DownloadError as e:
    #         self.root.after(0, lambda: self.log_widget.add_log(f"下载错误: {str(e)}", "ERROR"))
    #     except Exception as e:
    #         self.root.after(0, lambda: self.log_widget.add_log(f"未知错误: {str(e)}", "ERROR"))
    #     finally:
    #         loop.close()
    #         # 在主线程中重置状态
    #         self.root.after(0, self.download_finished)

    def update_download_results(self, results):
        """更新下载结果到UI"""
        if results["success"]:
            self.log_widget.add_log("下载完成！", "INFO")
            self.log_widget.add_log(f"成功处理 {results['processed_devices']} 个设备", "INFO")

            if results["failed_devices"]:
                self.log_widget.add_log(f"失败的设备: {results['failed_devices']}", "WARNING")

            if results["download_path"]:
                self.log_widget.add_log(f"下载目录: {results['download_path']}", "INFO")

            if results["zip_path"]:
                self.log_widget.add_log(f"ZIP文件: {results['zip_path']}", "INFO")
        else:
            self.log_widget.add_log("下载失败！", "ERROR")
            for error in results["errors"]:
                # v2.2.5+
                # 如果是用户取消，让进度条结束在“已取消”，避免一直停在“取消中...”
                if any("取消" in err for err in results.get("errors", [])):
                    self.progress_widget.update_progress("已取消", 0.0)

                self.log_widget.add_log(error, "ERROR")

    def download_finished(self):
        """下载完成后的清理工作"""
        self.is_downloading = False
        self.download_btn.config(state=tk.NORMAL)
        self.progress_widget.enable_cancel_button(False)

    def run(self):
        """运行应用"""
        self.root.mainloop()


if __name__ == "__main__":
    # v2.3.1+
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    # v2.3.1-
    # # 设置日志级别
    # logging.basicConfig(level=logging.INFO)

    # 启动应用
    app = DownloadManagerApp()
    app.run()
