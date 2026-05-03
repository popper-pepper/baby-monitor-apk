"""
婴儿看护系统 - Android APK 入口
================================
开箱即用，安装后点图标即可运行，无需 Termux。
"""

import os
import sys
import time
import threading
from datetime import datetime

# ── Kivy ──
import kivy
kivy.require("2.0.0")
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.clock import Clock
from kivy.utils import platform
from kivy.logger import Logger, LOG_LEVELS

# ── 服务模块 ──
from service import MonitorService

# ═══════════════════════════════════════════════════
# 样式常量
# ═══════════════════════════════════════════════════

COLOR_BG = (0.06, 0.06, 0.10, 1)
COLOR_CARD = (0.10, 0.10, 0.18, 1)
COLOR_GREEN = (0.13, 0.80, 0.37, 1)
COLOR_RED = (0.94, 0.27, 0.27, 1)
COLOR_BLUE = (0.23, 0.51, 0.96, 1)
COLOR_MUTED = (0.53, 0.53, 0.67, 1)
COLOR_ACCENT = (0.39, 0.40, 0.95, 1)


# ═══════════════════════════════════════════════════
# UI 组件
# ═══════════════════════════════════════════════════

class LogPanel(BoxLayout):
    """日志面板容器"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.size_hint_y = 0.25

        header = Label(
            text="📋 运行日志",
            size_hint_y=0.2,
            color=COLOR_MUTED,
            font_size="13sp",
            halign="left",
            valign="middle",
            text_size=(None, None),
        )
        self.add_widget(header)

        self._log_text = ""
        self.log_label = Label(
            text="系统启动中...",
            size_hint_y=0.8,
            color=COLOR_MUTED,
            font_size="11sp",
            halign="left",
            valign="top",
            text_size=(None, None),
            markup=True,
        )
        sv = ScrollView(size_hint=(1, 0.8))
        sv.add_widget(self.log_label)
        self.add_widget(sv)

    def append_log(self, msg):
        now = datetime.now().strftime("%H:%M:%S")
        entry = f"[{now}] {msg}"
        self._log_text = entry + "\n" + self._log_text
        lines = self._log_text.split("\n")[:30]
        self._log_text = "\n".join(lines)
        self.log_label.text = self._log_text
        # 确保 text_size 重新计算
        self.log_label.texture_update()
        self.log_label.text_size = (self.log_label.width, None)


class BabyMonitorUI(BoxLayout):
    """主界面"""

    def __init__(self, app_ref, **kwargs):
        super().__init__(**kwargs)
        self.app = app_ref
        self.service = None
        self.orientation = "vertical"
        self.padding = [16, 12, 16, 12]
        self.spacing = 10

        # ── 标题栏 ──
        title_bar = BoxLayout(
            size_hint_y=0.08, orientation="horizontal", spacing=8
        )
        self.status_dot = Label(
            text="●",
            font_size="20sp",
            color=COLOR_MUTED,
            size_hint_x=0.1,
        )
        title = Label(
            text="👶 婴儿看护系统",
            font_size="20sp",
            bold=True,
            halign="left",
            valign="middle",
            text_size=(None, None),
            size_hint_x=0.7,
        )
        self.clock_label = Label(
            text="",
            font_size="13sp",
            color=COLOR_MUTED,
            size_hint_x=0.2,
            halign="right",
        )
        title_bar.add_widget(self.status_dot)
        title_bar.add_widget(title)
        title_bar.add_widget(self.clock_label)
        self.add_widget(title_bar)

        # ── 控制按钮 ──
        btn_bar = BoxLayout(
            size_hint_y=0.1, orientation="horizontal", spacing=12
        )
        self.btn_start = Button(
            text="▶ 开始监控",
            font_size="17sp",
            bold=True,
            background_color=COLOR_GREEN,
            background_normal="",
            size_hint_x=0.5,
        )
        self.btn_start.bind(on_press=self.on_start)
        self.btn_stop = Button(
            text="■ 停止",
            font_size="17sp",
            bold=True,
            background_color=COLOR_RED,
            background_normal="",
            size_hint_x=0.5,
            disabled=True,
        )
        self.btn_stop.bind(on_press=self.on_stop)
        btn_bar.add_widget(self.btn_start)
        btn_bar.add_widget(self.btn_stop)
        self.add_widget(btn_bar)

        # ── 状态卡片 ──
        stats = BoxLayout(
            size_hint_y=0.14, orientation="horizontal", spacing=8
        )
        self.stat_motion = self._make_stat("运动量", "0", COLOR_GREEN)
        self.stat_events = self._make_stat("触发事件", "0", COLOR_BLUE)
        self.stat_state = self._make_stat("状态", "--", (0.96, 0.62, 0.05, 1))
        self.stat_fps = self._make_stat("帧率", "0", COLOR_MUTED)
        stats.add_widget(self.stat_motion)
        stats.add_widget(self.stat_events)
        stats.add_widget(self.stat_state)
        stats.add_widget(self.stat_fps)
        self.add_widget(stats)

        # ── 信息区域 ──
        self.info_label = Label(
            text="等待服务启动...",
            size_hint_y=0.08,
            color=COLOR_MUTED,
            font_size="13sp",
        )
        self.add_widget(self.info_label)

        # ── 打开控制面板按钮 ──
        self.web_btn = Button(
            text="🌐 打开控制面板 (浏览器)",
            size_hint_y=0.08,
            font_size="15sp",
            background_color=COLOR_ACCENT,
            background_normal="",
            disabled=True,
        )
        self.web_btn.bind(on_press=self.on_open_web)
        self.add_widget(self.web_btn)

        # ── 日志面板 ──
        self.log_panel = LogPanel()
        self.add_widget(self.log_panel)

        # ── 底部提示 ──
        hint = Label(
            text="摄像头地址在 config.yaml 中设置",
            size_hint_y=0.03,
            color=(0.3, 0.3, 0.4, 1),
            font_size="10sp",
        )
        self.add_widget(hint)

    def _make_stat(self, label, value, color):
        box = BoxLayout(orientation="vertical", padding=[4, 4])
        val = Label(
            text=value,
            font_size="22sp",
            bold=True,
            color=color,
        )
        lbl = Label(
            text=label,
            font_size="11sp",
            color=COLOR_MUTED,
        )
        box.add_widget(val)
        box.add_widget(lbl)
        box.val_label = val
        return box

    def on_start(self, _):
        if self.service:
            self.service.start_monitor()
            self.app.add_log("开始监控")
            self._update_state("监控中")

    def on_stop(self, _):
        if self.service:
            self.service.stop_monitor()
            self.app.add_log("停止监控")
            self._update_state("已停止")

    def on_open_web(self, _):
        import webbrowser
        webbrowser.open("http://127.0.0.1:5000")

    def _update_state(self, state):
        self.stat_state.val_label.text = state

    def update(self, dt):
        """定时刷新，由 Clock 调度"""
        if not self.service:
            return

        s = self.service.get_status()

        # 状态点
        st = s["state"]
        if st == "监控中":
            self.status_dot.color = COLOR_GREEN
        elif st == "运动!":
            self.status_dot.color = COLOR_RED
        elif st == "已停止":
            self.status_dot.color = COLOR_MUTED
        else:
            self.status_dot.color = (0.96, 0.62, 0.05, 1)

        # 统计
        self.stat_motion.val_label.text = str(s["motion_score"])
        self.stat_events.val_label.text = str(s["motion_events"])
        self.stat_state.val_label.text = st
        self.stat_fps.val_label.text = f"{s['fps']:.1f}"

        # 按钮状态
        running = s["running"]
        self.btn_start.disabled = running
        self.btn_stop.disabled = not running

        # 摄像头状态
        cam_ok = s["camera_connected"]
        if cam_ok is None:
            info = "正在连接摄像头..."
        elif cam_ok:
            ip = self.service.config.get("camera", {}).get("host", "?")
            info = f"📷 摄像头已连接 ({ip}:8080)"
        else:
            info = "⚠️ 摄像头离线，请检查 IP Webcam"
        self.info_label.text = info

        # 控制面板按钮
        self.web_btn.disabled = not running

        # 时钟
        self.clock_label.text = datetime.now().strftime("%H:%M:%S")


# ═══════════════════════════════════════════════════
# Kivy App
# ═══════════════════════════════════════════════════

class BabyMonitorApp(App):
    """婴儿看护系统 Android App"""

    def build(self):
        self.title = "婴儿看护系统"
        self.icon = ""  # 可选：data/icon.png

        # 创建 UI
        self.ui = BabyMonitorUI(app_ref=self)

        # 启动检测服务
        self._start_service()

        # 定时刷新 UI (每秒4次)
        Clock.schedule_interval(self.ui.update, 0.25)

        return self.ui

    def _start_service(self):
        """在后台线程中启动检测服务和 Flask 服务器"""
        try:
            self.service = MonitorService()
            self.ui.service = self.service
            threading.Thread(target=self._run_service, daemon=True).start()
        except Exception as e:
            self.add_log(f"服务启动失败: {e}")

    def _run_service(self):
        """后台线程：启动 Flask + 检测"""
        try:
            self.service.start_flask()
            self.add_log("Web 控制面板已就绪 http://127.0.0.1:5000")
            self.add_log("等待摄像头连接...")
        except Exception as e:
            self.add_log(f"服务异常: {e}")

    def add_log(self, msg):
        """添加日志（线程安全）"""
        Logger.info(f"BabyMonitor: {msg}")
        if hasattr(self, "ui") and self.ui:
            Clock.schedule_once(lambda dt: self.ui.log_panel.append_log(msg), 0)

    def on_stop(self):
        """App 退出时停止服务"""
        if hasattr(self, "service") and self.service:
            self.service.stop_monitor()
            self.add_log("系统停止")
        return super().on_stop()


if __name__ == "__main__":
    BabyMonitorApp().run()
