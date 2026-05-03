"""
婴儿看护系统 - 后台服务模块
===========================
运动检测 + Server酱通知 + Flask 控制面板。
纯 Pillow + numpy，零 OpenCV 依赖。
"""

import io
import json
import logging
import os
import sys
import threading
import time
import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path

import numpy as np
import requests
import yaml
from flask import Flask, Response, jsonify, request, render_template_string
from PIL import Image, ImageFilter

# ═══════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════

SCRIPT_DIR = Path(__file__).parent.resolve()
DEFAULT_CONFIG = SCRIPT_DIR / "config.yaml"
LOG_FILE = SCRIPT_DIR / "service.log"


# ═══════════════════════════════════════════════════
# 日志设置
# ═══════════════════════════════════════════════════

def setup_logging():
    """配置日志"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(str(LOG_FILE), encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def load_config(path=None):
    """加载 YAML 配置"""
    p = Path(path) if path else DEFAULT_CONFIG
    if not p.exists():
        logging.error(f"配置文件不存在: {p}")
        # 使用内置默认配置
        return _default_config()
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _default_config():
    """内置默认配置"""
    return {
        "camera": {
            "host": "127.0.0.1",
            "port": 8080,
            "snapshot_path": "/shot.jpg",
        },
        "motion": {
            "interval": 1.0,
            "sensitivity": 3000,
            "trigger_frames": 3,
            "cooldown": 30,
            "blur_ksize": 21,
            "threshold": 25,
        },
        "notification": {
            "server_chan_key": "",
            "title": "婴儿看护 - 检测到活动",
            "send_image": True,
        },
        "image_hosting": {
            "provider": "imgbb",
            "imgbb_api_key": "",
            "smms_token": "",
        },
        "web_server": {
            "host": "0.0.0.0",
            "port": 5000,
            "frame_interval": 0.3,
        },
        "display": {"show_window": False},
        "save": {"save_motion_frames": True, "output_dir": "captures"},
    }


# ═══════════════════════════════════════════════════
# 运动检测（Pillow + numpy）
# ═══════════════════════════════════════════════════

def _gaussian_blur(gray_np, ksize):
    """Pillow 高斯模糊"""
    radius = max(1, ksize // 6)
    pil = Image.fromarray(gray_np, mode="L")
    blurred = pil.filter(ImageFilter.GaussianBlur(radius=radius))
    return np.array(blurred, dtype=np.uint8)


def detect_motion(prev_gray, curr_gray, config):
    """帧差法运动检测，返回 (has_motion, motion_pixels)"""
    mc = config["motion"]
    prev = _gaussian_blur(prev_gray, mc["blur_ksize"])
    curr = _gaussian_blur(curr_gray, mc["blur_ksize"])
    delta = np.abs(prev.astype(np.int16) - curr.astype(np.int16))
    motion_pixels = int(np.sum(delta > mc["threshold"]))
    has_motion = motion_pixels > mc["sensitivity"]
    return has_motion, motion_pixels


# ═══════════════════════════════════════════════════
# IP Webcam 帧获取
# ═══════════════════════════════════════════════════

def fetch_frame(snapshot_url, max_retries=2):
    """获取单帧，返回 (pil_rgb, gray_np) 或 (None, None)"""
    for att in range(max_retries):
        try:
            resp = requests.get(snapshot_url, timeout=8)
            if resp.status_code == 200:
                pil = Image.open(BytesIO(resp.content)).convert("RGB")
                gray = np.array(pil.convert("L"), dtype=np.uint8)
                return pil, gray
        except Exception:
            pass
        if att < max_retries - 1:
            time.sleep(1)
    return None, None


def fetch_frame_bytes(snapshot_url, max_retries=2):
    """获取原始 JPG 字节"""
    for att in range(max_retries):
        try:
            resp = requests.get(snapshot_url, timeout=8)
            if resp.status_code == 200 and len(resp.content) > 1000:
                return resp.content
        except Exception:
            pass
        if att < max_retries - 1:
            time.sleep(1)
    return None


# ═══════════════════════════════════════════════════
# 图床上传
# ═══════════════════════════════════════════════════

def _pil_to_bytes(pil_img, quality=85):
    buf = BytesIO()
    pil_img.save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    return buf


def _upload_imgbb(img_bytes, api_key):
    if not api_key:
        return None
    try:
        fn = f"baby_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        r = requests.post(
            "https://api.imgbb.com/1/upload",
            params={"key": api_key},
            files={"image": (fn, img_bytes.getvalue(), "image/jpeg")},
            timeout=20,
        )
        d = r.json()
        if r.status_code == 200 and d.get("success"):
            return d["data"]["url"]
    except Exception:
        pass
    return None


def _upload_smms(img_bytes, token=""):
    try:
        fn = f"baby_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        headers = {"Authorization": token} if token else {}
        r = requests.post(
            "https://sm.ms/api/v2/upload",
            files={"smfile": (fn, img_bytes, "image/jpeg")},
            headers=headers,
            timeout=15,
        )
        if r.status_code == 200:
            d = r.json()
            if d.get("success"):
                return d["data"]["url"]
            elif "image_repeated" in d:
                return d.get("images")
    except Exception:
        pass
    return None


def upload_image(config, pil_img):
    """上传图片到图床，返回 URL 或 None"""
    ih = config.get("image_hosting", {})
    prv = ih.get("provider", "smms")
    if prv == "none":
        return None
    buf = _pil_to_bytes(pil_img)
    if prv == "imgbb":
        return _upload_imgbb(buf, ih.get("imgbb_api_key", ""))
    elif prv == "smms":
        return _upload_smms(buf, ih.get("smms_token", ""))
    return None


# ═══════════════════════════════════════════════════
# Server酱 通知
# ═══════════════════════════════════════════════════

def send_notification(config, pil_img=None):
    """通过 Server酱 推送微信通知"""
    nc = config["notification"]
    send_key = nc.get("server_chan_key", "")
    if not send_key:
        return False

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = nc.get("title", "婴儿看护 - 检测到活动")
    desp = f"## 宝宝活动提醒\n\n**时间**: {now_str}\n\n"

    if pil_img and nc.get("send_image", False):
        url = upload_image(config, pil_img)
        if url:
            desp += f"![现场照片]({url})\n\n"

    desp += "---\n婴儿看护系统自动检测"

    try:
        r = requests.post(
            f"https://sctapi.ftqq.com/{send_key}.send",
            data={"title": title, "desp": desp},
            timeout=15,
        )
        if r.status_code == 200:
            result = r.json()
            return result.get("code") == 0
    except Exception as e:
        logging.error(f"通知异常: {e}")
    return False


# ═══════════════════════════════════════════════════
# HTML 模板
# ═══════════════════════════════════════════════════

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>婴儿看护系统</title>
<style>
:root{--bg:#0f0f1a;--card:#1a1a2e;--card2:#222240;--text:#e8e8f0;--muted:#8888aa;--green:#22c55e;--red:#ef4444;--blue:#3b82f6;--accent:#6366f1;--radius:12px}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,'Segoe UI','PingFang SC',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;overflow-x:hidden;padding-bottom:env(safe-area-inset-bottom)}
.header{background:var(--card);padding:14px 16px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid rgba(255,255,255,0.05);position:sticky;top:0;z-index:10}
.header h1{font-size:18px;font-weight:600}
.status-dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;transition:background 0.3s}
.status-dot.stopped{background:#555}
.status-dot.running{background:var(--green);animation:pulse 2s infinite}
.status-dot.motion{background:var(--red);animation:pulse 0.5s infinite}
.status-dot.cooldown{background:#f59e0b}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}
.video-wrapper{position:relative;background:#000;width:100%;aspect-ratio:4/3;max-height:55vh;overflow:hidden}
.video-wrapper img{width:100%;height:100%;object-fit:contain;display:block}
.video-overlay{position:absolute;bottom:8px;left:8px;right:8px;display:flex;justify-content:space-between;font-size:12px;color:rgba(255,255,255,0.7);text-shadow:0 1px 3px rgba(0,0,0,0.8);pointer-events:none}
.camera-offline{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--muted);gap:12px}
.camera-offline .icon{font-size:48px;opacity:0.5}
.content{padding:12px 16px;display:flex;flex-direction:column;gap:14px}
.btn-group{display:flex;gap:12px}
.btn-group .btn{flex:1;padding:16px;border:none;border-radius:var(--radius);font-size:17px;font-weight:600;cursor:pointer;transition:all 0.15s;touch-action:manipulation}
.btn:active{transform:scale(0.96)}
.btn-start{background:var(--green);color:#fff;box-shadow:0 4px 15px rgba(34,197,94,0.3)}
.btn-start:disabled{background:#166534;box-shadow:none;opacity:0.7}
.btn-stop{background:var(--red);color:#fff;box-shadow:0 4px 15px rgba(239,68,68,0.3)}
.btn-stop:disabled{background:#7f1d1d;box-shadow:none;opacity:0.5}
.param-card{background:var(--card);border-radius:var(--radius);padding:16px}
.param-card .title{font-size:14px;color:var(--muted);margin-bottom:12px}
.param-item{margin-bottom:14px}
.param-item:last-child{margin-bottom:0}
.param-header{display:flex;justify-content:space-between;margin-bottom:6px;font-size:13px}
.param-header .value{color:var(--blue);font-weight:600;font-variant-numeric:tabular-nums}
.param-item input[type="range"]{-webkit-appearance:none;appearance:none;width:100%;height:6px;border-radius:3px;background:var(--card2);outline:none;cursor:pointer}
.param-item input[type="range"]::-webkit-slider-thumb{-webkit-appearance:none;width:22px;height:22px;border-radius:50%;background:var(--accent);cursor:pointer;box-shadow:0 2px 8px rgba(99,102,241,0.4)}
.status-bar{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.stat-item{background:var(--card);border-radius:10px;padding:12px;text-align:center}
.stat-item .num{font-size:26px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.2}
.stat-item .stat-label{font-size:12px;color:var(--muted);margin-top:2px}
.stat-item.green .num{color:var(--green)}
.stat-item.blue .num{color:var(--blue)}
.stat-item.orange .num{color:#f59e0b}
.log-card{background:var(--card);border-radius:var(--radius);padding:12px 16px;max-height:100px;overflow-y:auto}
.log-card .log-title{font-size:12px;color:var(--muted);margin-bottom:6px}
.log-entry{font-size:12px;color:var(--muted);padding:2px 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.toast{position:fixed;top:60px;left:50%;transform:translateX(-50%);background:var(--card);border:1px solid rgba(255,255,255,0.1);padding:10px 20px;border-radius:8px;font-size:14px;z-index:100;opacity:0;transition:opacity 0.3s;pointer-events:none}
.toast.show{opacity:1}
</style>
</head>
<body>
<div class="header"><h1><span class="status-dot stopped" id="statusDot"></span>婴儿看护系统</h1><span style="font-size:12px;color:var(--muted)" id="clock">{{ clock }}</span></div>
<div class="video-wrapper">
<img id="videoFeed" src="">
<div class="video-overlay"><span id="camLabel">摄像头: {{ camera_host }}</span><span id="frameInfo">-- fps</span></div>
<div class="camera-offline" id="camOffline" style="display:none"><div class="icon">&#x1F4F7;</div><div class="text">等待摄像头连接...</div></div>
</div>
<div class="content">
<div class="btn-group">
<button class="btn btn-start" id="btnStart" onclick="startMonitor()">&#9654; 开始监控</button>
<button class="btn btn-stop" id="btnStop" onclick="stopMonitor()" disabled>&#9632; 停止</button>
</div>
<div class="param-card">
<div class="title">&#x2699; 参数调节</div>
<div class="param-item"><div class="param-header"><span>灵敏度</span><span class="value" id="valSensitivity">{{ sensitivity }}</span></div><input type="range" id="sliderSensitivity" min="500" max="20000" step="100" value="{{ sensitivity }}" oninput="onParamChange('sensitivity',this,'valSensitivity')"></div>
<div class="param-item"><div class="param-header"><span>检测间隔(秒)</span><span class="value" id="valInterval">{{ interval }}s</span></div><input type="range" id="sliderInterval" min="0.5" max="5" step="0.1" value="{{ interval }}" oninput="onParamChange('interval',this,'valInterval')"></div>
<div class="param-item"><div class="param-header"><span>触发帧数</span><span class="value" id="valTriggerFrames">{{ trigger_frames }}帧</span></div><input type="range" id="sliderTriggerFrames" min="1" max="10" step="1" value="{{ trigger_frames }}" oninput="onParamChange('trigger_frames',this,'valTriggerFrames')"></div>
<div class="param-item"><div class="param-header"><span>通知冷却(秒)</span><span class="value" id="valCooldown">{{ cooldown }}s</span></div><input type="range" id="sliderCooldown" min="5" max="300" step="5" value="{{ cooldown }}" oninput="onParamChange('cooldown',this,'valCooldown')"></div>
</div>
<div class="status-bar">
<div class="stat-item green"><div class="num" id="statMotion">0</div><div class="stat-label">运动量</div></div>
<div class="stat-item blue"><div class="num" id="statEvents">0</div><div class="stat-label">触发事件</div></div>
<div class="stat-item orange"><div class="num" id="statState">--</div><div class="stat-label">状态</div></div>
<div class="stat-item"><div class="num" id="statFrames" style="color:var(--muted)">0</div><div class="stat-label">总帧数</div></div>
</div>
<div class="log-card"><div class="log-title">&#x1F4DD; 活动记录</div><div id="logEntries"><div class="log-entry">系统就绪</div></div></div>
</div>
<div class="toast" id="toast"></div>
<script>
let running=false,paramTimer=null;
function updateClock(){document.getElementById('clock').textContent=new Date().toLocaleTimeString('zh-CN')}
setInterval(updateClock,1000);
function refreshFrame(){var img=document.getElementById('videoFeed');if(img)img.src='/api/frame?_='+Date.now()}
setInterval(refreshFrame,500);setTimeout(refreshFrame,100);
async function pollStatus(){try{var r=await fetch('/api/status');var d=await r.json();updateUI(d)}catch(e){}}
setInterval(pollStatus,800);pollStatus();
function updateUI(d){var dot=document.getElementById('statusDot'),st=d.state||'已停止';
document.getElementById('statMotion').textContent=d.motion_score||0;
document.getElementById('statEvents').textContent=d.motion_events||0;
document.getElementById('statFrames').textContent=d.total_frames||0;
document.getElementById('statState').textContent=st;
dot.className='status-dot';
if(st==='监控中')dot.classList.add('running');
else if(st==='运动!')dot.classList.add('motion');
else if(st.includes('冷却'))dot.classList.add('cooldown');
else dot.classList.add('stopped');
running=d.running||false;
document.getElementById('btnStart').disabled=running;
document.getElementById('btnStop').disabled=!running;
if(d.fps)document.getElementById('frameInfo').textContent=d.fps.toFixed(1)+' fps';
var off=document.getElementById('camOffline'),feed=document.getElementById('videoFeed');
if(d.camera_connected===false){off.style.display='flex';feed.style.display='none';document.getElementById('camLabel').textContent='摄像头: 未连接'}
else{off.style.display='none';feed.style.display='block'}}
async function startMonitor(){try{var r=await fetch('/api/start',{method:'POST'});if(r.ok)showToast('监控已开始');addLog('开始监控')}catch(e){showToast('操作失败')}}
async function stopMonitor(){try{var r=await fetch('/api/stop',{method:'POST'});if(r.ok)showToast('监控已停止');addLog('停止监控')}catch(e){}}
function onParamChange(k,s,vid){var v=parseFloat(s.value);var el=document.getElementById(vid);
if(k==='interval')el.textContent=v+'s';else if(k==='trigger_frames')el.textContent=v+'帧';else if(k==='cooldown')el.textContent=v+'s';else el.textContent=v;
clearTimeout(paramTimer);paramTimer=setTimeout(function(){fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:k,value:v})})},500)}
function showToast(m){var el=document.getElementById('toast');el.textContent=m;el.classList.add('show');setTimeout(function(){el.classList.remove('show')},2000)}
function addLog(m){var c=document.getElementById('logEntries'),t=new Date().toLocaleTimeString('zh-CN'),e=document.createElement('div');e.className='log-entry';e.textContent='['+t+'] '+m;c.insertBefore(e,c.firstChild);while(c.children.length>20)c.removeChild(c.lastChild)}
var lastEC=0;setInterval(function(){var n=parseInt(document.getElementById('statEvents').textContent)||0;if(n>lastEC){addLog('运动事件 #'+n);lastEC=n}},1000);
</script>
</body>
</html>"""


# ═══════════════════════════════════════════════════
# 监控服务核心类
# ═══════════════════════════════════════════════════

class MonitorService:
    """封装检测线程、Flask 服务器和状态管理"""

    def __init__(self, config_path=None):
        setup_logging()
        self.config = load_config(config_path)
        cam = self.config["camera"]
        self.snapshot_url = (
            f"http://{cam['host']}:{cam['port']}{cam['snapshot_path']}"
        )
        ws = self.config.get("web_server", {})
        self.frame_interval = ws.get("frame_interval", 0.3)

        # 线程安全
        self._lock = threading.RLock()

        # 帧缓存
        self._cached_pil = None
        self._cached_gray = None
        self._cached_bytes = None
        self._cached_time = 0

        # 状态
        self._running = False
        self._cam_connected = None
        self._fps = 0
        self._frame_count = 0
        self._fps_timer = time.time()
        self._state = "已停止"
        self._motion_score = 0
        self._motion_events = 0
        self._motion_consecutive = 0
        self._in_cooldown = False
        self._cooldown_start = 0
        self._prev_gray = None
        self._last_event_pil = None
        self._total_frames = 0

        # 启动帧拉取
        self._start_frame_fetcher()

    # ── 帧拉取线程 ──

    def _start_frame_fetcher(self):
        t = threading.Thread(target=self._frame_loop, daemon=True)
        t.start()

    def _frame_loop(self):
        while True:
            data = fetch_frame_bytes(self.snapshot_url)
            if data:
                try:
                    pil = Image.open(BytesIO(data)).convert("RGB")
                    gray = np.array(pil.convert("L"), dtype=np.uint8)
                    now = time.time()
                    with self._lock:
                        self._cached_pil = pil
                        self._cached_gray = gray
                        self._cached_bytes = data
                        self._cached_time = now
                        self._cam_connected = True
                        self._frame_count += 1
                        if now - self._fps_timer >= 2.0:
                            self._fps = self._frame_count / (now - self._fps_timer)
                            self._frame_count = 0
                            self._fps_timer = now
                except Exception:
                    pass
            else:
                with self._lock:
                    self._cam_connected = False
            time.sleep(self.frame_interval)

    # ── 状态查询 ──

    def get_status(self):
        with self._lock:
            cd_remaining = 0
            if self._in_cooldown:
                elapsed = time.time() - self._cooldown_start
                cd = self.config["motion"]["cooldown"]
                cd_remaining = max(0, int(cd - elapsed))
            return {
                "running": self._running,
                "state": self._state,
                "motion_score": self._motion_score,
                "motion_events": self._motion_events,
                "motion_consecutive": self._motion_consecutive,
                "cooldown_remaining": cd_remaining,
                "total_frames": self._total_frames,
                "fps": self._fps,
                "camera_connected": self._cam_connected,
            }

    # ── 启动/停止 ──

    def start_monitor(self):
        with self._lock:
            if self._running:
                return False
            self._running = True
            self._state = "监控中"
            self._motion_consecutive = 0
            self._prev_gray = None
        t = threading.Thread(target=self._detection_loop, daemon=True)
        t.start()
        logging.info("运动检测已启动")
        return True

    def stop_monitor(self):
        with self._lock:
            if not self._running:
                return False
            self._running = False
            self._state = "已停止"
            self._in_cooldown = False
            self._motion_consecutive = 0
            self._prev_gray = None
        logging.info("运动检测已停止")
        return True

    def update_config(self, key, value):
        with self._lock:
            if key in self.config["motion"]:
                self.config["motion"][key] = value
                return True
        return False

    # ── 检测循环 ──

    def _detection_loop(self):
        mc = self.config["motion"]
        while True:
            loop_start = time.time()

            with self._lock:
                if not self._running:
                    break
                pil = self._cached_pil
                gray = self._cached_gray
                ct = self._cached_time

            if pil is None or gray is None:
                time.sleep(0.5)
                continue

            if time.time() - ct > 5:
                with self._lock:
                    self._cam_connected = False
                time.sleep(0.5)
                continue

            with self._lock:
                self._cam_connected = True
                self._total_frames += 1

            with self._lock:
                if self._prev_gray is not None:
                    has_motion, mp = detect_motion(self._prev_gray, gray, self.config)
                    self._motion_score = mp
                    if has_motion:
                        self._motion_consecutive += 1
                        self._last_event_pil = pil.copy()
                    else:
                        self._motion_consecutive = max(0, self._motion_consecutive - 1)
                else:
                    has_motion, mp = False, 0
                self._prev_gray = gray

            with self._lock:
                if self._in_cooldown:
                    elapsed = time.time() - self._cooldown_start
                    if elapsed >= mc["cooldown"]:
                        self._in_cooldown = False
                        self._motion_consecutive = 0
                        self._state = "监控中"
                    else:
                        self._state = f"冷却中({int(mc['cooldown']-elapsed)}s)"

            with self._lock:
                if not self._in_cooldown and self._motion_consecutive >= mc["trigger_frames"]:
                    self._motion_events += 1
                    self._in_cooldown = True
                    self._cooldown_start = time.time()
                    self._state = "运动!"
                    event_pil = self._last_event_pil.copy() if self._last_event_pil else pil
                    logging.info(f"第 {self._motion_events} 次运动事件")
                    threading.Thread(target=self._handle_event, args=(event_pil,), daemon=True).start()

            # 帧率控制
            elapsed = time.time() - loop_start
            sleep_time = mc["interval"] - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _handle_event(self, pil_img):
        # 保存
        if self.config.get("save", {}).get("save_motion_frames", False):
            try:
                out = SCRIPT_DIR / self.config["save"]["output_dir"]
                out.mkdir(parents=True, exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                fp = out / f"motion_{ts}_{uuid.uuid4().hex[:8]}.jpg"
                pil_img.save(str(fp), format="JPEG", quality=90)
            except Exception as e:
                logging.error(f"保存帧失败: {e}")
        send_notification(self.config, pil_img)

    # ── Flask 服务器 ──

    def start_flask(self):
        """启动 Flask Web 服务器（阻塞，应在后台线程调用）"""
        app = self._create_app()
        ws = self.config.get("web_server", {})
        host = ws.get("host", "0.0.0.0")
        port = ws.get("port", 5000)
        logging.info(f"Web 服务器启动 http://{host}:{port}")
        app.run(host=host, port=port, debug=False, threaded=True, use_reloader=False)

    def _create_app(self):
        app = Flask(__name__)

        @app.route("/")
        def index():
            mc = self.config["motion"]
            cam = self.config["camera"]
            return render_template_string(
                HTML_TEMPLATE,
                camera_host=f"{cam['host']}:{cam['port']}",
                sensitivity=mc["sensitivity"],
                interval=mc["interval"],
                trigger_frames=mc["trigger_frames"],
                cooldown=mc["cooldown"],
                clock=datetime.now().strftime("%H:%M:%S"),
            )

        @app.route("/api/frame")
        def api_frame():
            data = self._cached_bytes
            if data:
                return Response(data, mimetype="image/jpeg")
            return Response(self._placeholder(), mimetype="image/jpeg")

        @app.route("/video_feed")
        def video_feed():
            def gen():
                while True:
                    frame = self._cached_bytes
                    if frame:
                        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                    else:
                        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + self._placeholder() + b"\r\n"
                    time.sleep(self.frame_interval)
            return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")

        @app.route("/api/status")
        def api_status():
            return jsonify(self.get_status())

        @app.route("/api/start", methods=["POST"])
        def api_start():
            return jsonify({"success": self.start_monitor()})

        @app.route("/api/stop", methods=["POST"])
        def api_stop():
            return jsonify({"success": self.stop_monitor()})

        @app.route("/api/config", methods=["POST"])
        def api_config():
            d = request.get_json(silent=True)
            if d and "key" in d and "value" in d:
                ok = self.update_config(d["key"], d["value"])
                return jsonify({"success": ok})
            return jsonify({"success": False}), 400

        @app.route("/api/config", methods=["GET"])
        def api_get_config():
            return jsonify(self.config["motion"])

        @app.route("/api/ping")
        def api_ping():
            return jsonify({"ok": True})

        return app

    def _placeholder(self):
        img = Image.new("RGB", (320, 240), (20, 20, 40))
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        draw.text((80, 110), "摄像头未连接", fill=(136, 136, 170))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=30)
        buf.seek(0)
        return buf.read()
