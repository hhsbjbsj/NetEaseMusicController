# -*- coding: utf-8 -*-
"""
NetEaseMusicController Server (Modern v2.5 全功能旗舰版)
- Python 3 原生标准库实现，零第三方依赖
- 硬件扫描码模拟 + Windows 原生多媒体硬件键双通道注入
- 实时获取电脑当前正在播放的曲目名称（Now Playing）
- 全面支持：上一首、播放/暂停、下一首、音量增减、静音
- 专属音乐模式：单曲循环、列表循环、随机播放、顺序播放、从头重播本首、红心收藏（喜欢歌曲）
- 睡眠关机助手：支持 15/30/45/60 分钟定时关机、取消定时关机、立即关机
- 自动识别局域网 IP，支持现代响应式 Web UI、PWA 移动端沉浸体验、Android APP REST API
"""
import os
import sys
import time
import json
import ctypes
import socket
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from ctypes import wintypes

try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(errors='replace')
except Exception:
    pass

user32 = ctypes.windll.user32

# Virtual Key Codes
VK_CONTROL = 0x11
VK_MENU = 0x12    # Alt
VK_SHIFT = 0x10
VK_F1 = 0x70
VK_F2 = 0x71
VK_F3 = 0x72
VK_F4 = 0x73
VK_F6 = 0x75
VK_L = 0x4C       # L key for Like (Ctrl + Alt + L)

# Multimedia Keys
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002

def press_hotkey(modifier_vk, key_vk, extra_mod=None):
    """发送带硬件扫描码与物理延时的组合按键"""
    mod_scan = user32.MapVirtualKeyW(modifier_vk, 0)
    key_scan = user32.MapVirtualKeyW(key_vk, 0)
    extra_scan = user32.MapVirtualKeyW(extra_mod, 0) if extra_mod else 0

    user32.keybd_event(modifier_vk, mod_scan, 0, 0)
    if extra_mod:
        user32.keybd_event(extra_mod, extra_scan, 0, 0)
    time.sleep(0.04)

    user32.keybd_event(key_vk, key_scan, 0, 0)
    time.sleep(0.06)

    user32.keybd_event(key_vk, key_scan, KEYEVENTF_KEYUP, 0)
    time.sleep(0.04)
    if extra_mod:
        user32.keybd_event(extra_mod, extra_scan, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(modifier_vk, mod_scan, KEYEVENTF_KEYUP, 0)

def press_media_key(media_vk):
    """发送 Windows 原生多媒体硬件功能键"""
    scan = user32.MapVirtualKeyW(media_vk, 0)
    user32.keybd_event(media_vk, scan, KEYEVENTF_EXTENDEDKEY, 0)
    time.sleep(0.06)
    user32.keybd_event(media_vk, scan, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)

def get_current_song():
    """实时读取网易云音乐窗口标题获取当前正在播放的曲目信息"""
    try:
        hdesk = user32.OpenInputDesktop(0, False, 0x10000000)
        if hdesk:
            user32.SetThreadDesktop(hdesk)
        hwnd = user32.FindWindowW('OrpheusBrowserHost', None)
        if hwnd:
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                val = buf.value.strip()
                if val and val != "OrpheusBrowserHost":
                    return val
    except Exception:
        pass
    return "网易云音乐"

class SingleSongLoopManager:
    """管理单曲自动循环重播助手状态与定时器"""
    def __init__(self):
        self.enabled = False
        self.interval = 210  # 默认 210 秒（约 3.5 分钟）自动触发一次重播
        self.timer_thread = None
        self.stop_event = threading.Event()
        self.lock = threading.Lock()

    def toggle(self):
        with self.lock:
            self.enabled = not self.enabled
            if self.enabled:
                self.start_timer()
            else:
                self.stop_timer()
            return self.enabled

    def set_state(self, state, interval=None):
        with self.lock:
            self.enabled = bool(state)
            if interval:
                try:
                    self.interval = max(30, int(interval))
                except ValueError:
                    pass
            if self.enabled:
                self.start_timer()
            else:
                self.stop_timer()
            return self.enabled

    def start_timer(self):
        self.stop_event.clear()
        if self.timer_thread and self.timer_thread.is_alive():
            return
        self.timer_thread = threading.Thread(target=self._loop_worker, daemon=True)
        self.timer_thread.start()

    def stop_timer(self):
        self.stop_event.set()

    def _loop_worker(self):
        while not self.stop_event.is_set():
            if self.stop_event.wait(timeout=self.interval):
                break
            if self.enabled:
                print(f"[单曲循环助手] 达到循环周期 ({self.interval}秒)，自动触发单曲重播！")
                MusicBox.replay_song()

loop_manager = SingleSongLoopManager()

# 全局播放模式状态追踪：'list_loop' (列表循环), 'single_loop' (单曲循环), 'shuffle' (随机播放), 'sequential' (顺序播放)
current_play_mode = "list_loop"

class MusicBox:
    @staticmethod
    def next_song():
        print("[操作触发] 下一首 (Next Track)")
        press_hotkey(VK_CONTROL, VK_F3)
        time.sleep(0.03)
        press_media_key(VK_MEDIA_NEXT_TRACK)

    @staticmethod
    def prev_song():
        print("[操作触发] 上一首 (Previous Track)")
        press_hotkey(VK_CONTROL, VK_F1)
        time.sleep(0.03)
        press_media_key(VK_MEDIA_PREV_TRACK)

    @staticmethod
    def pause_play():
        print("[操作触发] 播放/暂停 (Play/Pause)")
        press_hotkey(VK_CONTROL, VK_F2)
        time.sleep(0.03)
        press_media_key(VK_MEDIA_PLAY_PAUSE)

    @staticmethod
    def replay_song():
        """重播本首：连续发送两次上一首命令，网易云将立即从 0:00 重新播放当前曲目"""
        print("[操作触发] 重新播放本首 (Replay from 0:00)")
        press_hotkey(VK_CONTROL, VK_F1)
        time.sleep(0.05)
        press_media_key(VK_MEDIA_PREV_TRACK)
        time.sleep(0.12)
        press_hotkey(VK_CONTROL, VK_F1)
        time.sleep(0.05)
        press_media_key(VK_MEDIA_PREV_TRACK)

    @staticmethod
    def toggle_loop():
        """切换单曲自动循环模式"""
        global current_play_mode
        state = loop_manager.toggle()
        if state:
            current_play_mode = "single_loop"
        else:
            current_play_mode = "list_loop"
        print(f"[操作触发] 单曲自动循环模式: {'【开启】' if state else '【关闭】'}")
        MusicBox.cycle_mode_ui()
        return state

    @staticmethod
    def set_mode(mode_name):
        """设置特定的播放模式"""
        global current_play_mode
        current_play_mode = mode_name
        if mode_name == "single_loop":
            loop_manager.set_state(True)
            print("[操作触发] 切换播放模式 -> 【单曲循环】")
        else:
            loop_manager.set_state(False)
            mode_desc = {
                "list_loop": "【列表循环】",
                "shuffle": "【随机播放】",
                "sequential": "【顺序播放】"
            }.get(mode_name, mode_name)
            print(f"[操作触发] 切换播放模式 -> {mode_desc}")
        
        # 联动触发网易云界面的模式切换
        MusicBox.cycle_mode_ui()
        return current_play_mode

    @staticmethod
    def cycle_mode_ui():
        """向网易云窗口发送模式切换点击指令"""
        try:
            hdesk = user32.OpenInputDesktop(0, False, 0x10000000)
            if hdesk:
                user32.SetThreadDesktop(hdesk)
            hwnd = user32.FindWindowW('OrpheusBrowserHost', None)
            if hwnd:
                rect = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                w = rect.right - rect.left
                h = rect.bottom - rect.top
                if w > 200 and h > 100:
                    # 查找渲染子窗口
                    EnumChildProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
                    render_hwnds = []
                    def callback(h_child, extra):
                        cls_buf = ctypes.create_unicode_buffer(256)
                        user32.GetClassNameW(h_child, cls_buf, 256)
                        if 'Chrome_RenderWidgetHostHWND' in cls_buf.value:
                            render_hwnds.append(h_child)
                        return True
                    user32.EnumChildWindows(hwnd, EnumChildProc(callback), 0)
                    if render_hwnds:
                        target = render_hwnds[0]
                        cx = max(10, w - 240)
                        cy = max(10, h - 36)
                        lparam = (cy << 16) | (cx & 0xFFFF)
                        user32.PostMessageW(target, 0x0201, 1, lparam)
                        time.sleep(0.04)
                        user32.PostMessageW(target, 0x0202, 0, lparam)
        except Exception:
            pass

    @staticmethod
    def like_song():
        """喜欢/收藏红心音乐（默认网易云全局热键 Ctrl + Alt + L）"""
        print("[操作触发] 喜欢/收藏红心音乐 (Like Song: Ctrl+Alt+L)")
        press_hotkey(VK_CONTROL, VK_L, extra_mod=VK_MENU)

    @staticmethod
    def volume_up():
        print("[操作触发] 音量+ (Volume Up)")
        press_hotkey(VK_CONTROL, VK_F6)
        press_media_key(VK_VOLUME_UP)

    @staticmethod
    def volume_down():
        print("[操作触发] 音量- (Volume Down)")
        press_hotkey(VK_CONTROL, VK_F4)
        press_media_key(VK_VOLUME_DOWN)

    @staticmethod
    def volume_mute():
        print("[操作触发] 静音切换 (Mute)")
        press_media_key(VK_VOLUME_MUTE)

    @staticmethod
    def schedule_shutdown(minutes=30):
        try:
            m = int(minutes)
        except (ValueError, TypeError):
            m = 30
        seconds = m * 60
        print(f"[操作触发] 设定睡眠关机: {m} 分钟后电脑将自动关机")
        os.system(f"shutdown -s -t {seconds}")

    @staticmethod
    def cancel_shutdown():
        print("[操作触发] 取消定时关机任务")
        os.system("shutdown -a")

    @staticmethod
    def shutdown():
        print("[操作触发] 电脑关机 (5秒倒计时)")
        os.system("shutdown -s -t 5")


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ----------------- 智能局域网 IP 与网卡探测 -----------------
class IP_ADDR_STRING(ctypes.Structure):
    pass

IP_ADDR_STRING._fields_ = [
    ('Next', ctypes.POINTER(IP_ADDR_STRING)),
    ('IpAddress', ctypes.c_char * 16),
    ('IpMask', ctypes.c_char * 16),
    ('Context', wintypes.DWORD)
]

MAX_ADAPTER_NAME_LENGTH = 256
MAX_ADAPTER_DESCRIPTION_LENGTH = 128
MAX_ADAPTER_ADDRESS_LENGTH = 8

class IP_ADAPTER_INFO(ctypes.Structure):
    pass

IP_ADAPTER_INFO._fields_ = [
    ('Next', ctypes.POINTER(IP_ADAPTER_INFO)),
    ('ComboIndex', wintypes.DWORD),
    ('AdapterName', ctypes.c_char * (MAX_ADAPTER_NAME_LENGTH + 4)),
    ('Description', ctypes.c_char * (MAX_ADAPTER_DESCRIPTION_LENGTH + 4)),
    ('AddressLength', wintypes.UINT),
    ('Address', ctypes.c_byte * MAX_ADAPTER_ADDRESS_LENGTH),
    ('Index', wintypes.DWORD),
    ('Type', wintypes.UINT),
    ('DhcpEnabled', wintypes.UINT),
    ('CurrentIpAddress', ctypes.POINTER(IP_ADDR_STRING)),
    ('IpAddressList', IP_ADDR_STRING),
    ('GatewayList', IP_ADDR_STRING),
    ('DhcpServer', IP_ADDR_STRING),
    ('HaveWins', wintypes.BOOL),
    ('PrimaryWinsServer', IP_ADDR_STRING),
    ('SecondaryWinsServer', IP_ADDR_STRING),
    ('LeaseObtained', ctypes.c_longlong),
    ('LeaseExpires', ctypes.c_longlong)
]

def get_network_details():
    """通过 Windows 原生 iphlpapi 获取所有网卡的物理属性、默认网关与局域网 IP"""
    adapters = []
    try:
        iphlpapi = ctypes.windll.iphlpapi
        buflen = wintypes.ULONG(0)
        iphlpapi.GetAdaptersInfo(None, ctypes.byref(buflen))
        if buflen.value > 0:
            buf = ctypes.create_string_buffer(buflen.value)
            res = iphlpapi.GetAdaptersInfo(ctypes.cast(buf, ctypes.POINTER(IP_ADAPTER_INFO)), ctypes.byref(buflen))
            if res == 0:
                curr = ctypes.cast(buf, ctypes.POINTER(IP_ADAPTER_INFO))
                while curr:
                    info = curr.contents
                    desc = info.Description.decode('ascii', errors='ignore').strip()
                    name = info.AdapterName.decode('ascii', errors='ignore').strip()

                    ips = []
                    ip_ptr = ctypes.pointer(info.IpAddressList)
                    while ip_ptr:
                        ip_val = ip_ptr.contents.IpAddress.decode('ascii', errors='ignore').strip('\x00').strip()
                        if ip_val and ip_val != '0.0.0.0' and not ip_val.startswith('127.') and not ip_val.startswith('169.254.'):
                            ips.append(ip_val)
                        ip_ptr = ip_ptr.contents.Next

                    gateways = []
                    gw_ptr = ctypes.pointer(info.GatewayList)
                    while gw_ptr:
                        gw_val = gw_ptr.contents.IpAddress.decode('ascii', errors='ignore').strip('\x00').strip()
                        if gw_val and gw_val != '0.0.0.0':
                            gateways.append(gw_val)
                        gw_ptr = gw_ptr.contents.Next

                    if ips:
                        adapters.append({
                            'name': name,
                            'desc': desc,
                            'type': info.Type,
                            'ips': ips,
                            'gateways': gateways
                        })
                    curr = info.Next
    except Exception:
        pass
    return adapters

def get_best_lan_ip():
    """
    智能选择最适合手机/外部设备访问的本机局域网 IP。
    严格排除 TUN、TAP、Karing、Tailscale 等各类 VPN / 代理虚拟网卡。
    返回: (best_ip, adapter_desc, gateway, secondary_candidates)
    """
    adapters = get_network_details()
    candidates = []

    for a in adapters:
        desc_lower = a['desc'].lower()
        is_vpn = any(k in desc_lower for k in [
            'tun', 'tap', 'vpn', 'karing', 'tailscale', 'wireguard',
            'clash', 'sing-box', 'virtual', 'vmware', 'vethernet', 'hyper-v'
        ]) or (a['type'] == 53)  # MIB_IF_TYPE_PROP_VIRTUAL

        has_gw = len(a['gateways']) > 0

        for ip in a['ips']:
            score = 0
            if has_gw:
                score += 100
                if ip.startswith('192.168.'):
                    score += 50
                elif ip.startswith('10.'):
                    score += 20
                elif ip.startswith('172.'):
                    score += 20
            else:
                if ip.startswith('192.168.'):
                    score += 30
                elif ip.startswith('10.'):
                    score += 5
                elif ip.startswith('100.'):
                    score -= 40

            if a['type'] in (6, 71):  # Ethernet or 802.11 Wi-Fi
                score += 40

            if is_vpn:
                score -= 150

            candidates.append({
                'ip': ip,
                'desc': a['desc'],
                'gateway': a['gateways'][0] if has_gw else None,
                'score': score,
                'is_vpn': is_vpn
            })

    candidates.sort(key=lambda x: x['score'], reverse=True)

    if candidates and candidates[0]['score'] > 0:
        best = candidates[0]
        secondaries = [c for c in candidates[1:] if c['ip'] != best['ip']]
        return best['ip'], best['desc'], best['gateway'], secondaries

    # 降级备用
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('223.5.5.5', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip, "默认网络适配器", None, []
    except Exception:
        pass

    return "127.0.0.1", "本地回环", None, []

def get_local_ip():
    """兼容旧接口调用"""
    best_ip, _, _, _ = get_best_lan_ip()
    return best_ip



class MusicHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        sys.stdout.write(f"[{time.strftime('%H:%M:%S')}] {self.address_string()} - {format % args}\n")
        sys.stdout.flush()

    def send_cors_json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # 1. 实时状态查询接口（含当前歌曲、播放模式）
        if path == "/api/status":
            self.send_cors_json({
                "status": 1,
                "version": "2.5.0",
                "current_song": get_current_song(),
                "play_mode": current_play_mode,
                "single_loop": loop_manager.enabled,
                "loop_interval": loop_manager.interval,
                "local_ip": get_local_ip(),
                "port": 10010
            })
            return

        # 2. 通用动作调用接口 (/api/action?cmd=...)
        if path == "/api/action":
            cmd = query.get("cmd", [None])[0]
            val = query.get("val", [None])[0]
            success = True
            msg = "OK"

            if cmd == "set_mode":
                MusicBox.set_mode(val or "list_loop")
            elif cmd == "set_loop":
                state = query.get("state", ["true"])[0].lower() in ("true", "1")
                loop_manager.set_state(state, val)
            elif cmd == "schedule_shutdown":
                MusicBox.schedule_shutdown(val or 30)
            elif cmd and hasattr(MusicBox, cmd):
                res = getattr(MusicBox, cmd)()
                if cmd == "toggle_loop":
                    msg = "enabled" if res else "disabled"
            else:
                success = False
                msg = f"Unknown command: {cmd}"

            self.send_cors_json({
                "success": success,
                "message": msg,
                "current_song": get_current_song(),
                "play_mode": current_play_mode,
                "single_loop": loop_manager.enabled
            })
            return

        # 3. 兼容旧版 APP 连接握手接口
        if path == "/mobile_connect":
            self.send_cors_json({
                "code": 200,
                "message": "Connected",
                "platform": "win",
                "status": 1,
                "version": "2.5.0",
                "current_song": get_current_song(),
                "play_mode": current_play_mode,
                "single_loop": loop_manager.enabled
            })
            return

        # 4. PWA Manifest
        if path == "/manifest.json":
            manifest_path = os.path.join(BASE_DIR, "manifest.json")
            if os.path.exists(manifest_path):
                self.send_response(200)
                self.send_header("Content-Type", "application/manifest+json; charset=utf-8")
                self.end_headers()
                with open(manifest_path, "rb") as f:
                    self.wfile.write(f.read())
                return

        # 5. Service Worker
        if path == "/sw.js":
            sw_path = os.path.join(BASE_DIR, "sw.js")
            if os.path.exists(sw_path):
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript; charset=utf-8")
                self.end_headers()
                with open(sw_path, "rb") as f:
                    self.wfile.write(f.read())
                return

        # 6. Web 控制面板主页
        if path in ("/", "/index.html"):
            action = query.get("action", [None])[0]
            if action and hasattr(MusicBox, action):
                try:
                    getattr(MusicBox, action)()
                except Exception as e:
                    print(f"执行按键失败: {e}")

            html_path = os.path.join(BASE_DIR, "templates", "index.html")
            if os.path.exists(html_path):
                with open(html_path, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(content)
            else:
                self.send_response(404)
                self.end_headers()
            return

        # 7. 静态资源（CSS / JS / SVG / PNG）
        if path.startswith("/static/"):
            rel_path = path.lstrip("/")
            file_path = os.path.join(BASE_DIR, rel_path)
            if os.path.exists(file_path):
                self.send_response(200)
                if file_path.endswith(".css"):
                    self.send_header("Content-Type", "text/css")
                elif file_path.endswith(".js"):
                    self.send_header("Content-Type", "application/javascript")
                elif file_path.endswith(".svg"):
                    self.send_header("Content-Type", "image/svg+xml")
                elif file_path.endswith(".png"):
                    self.send_header("Content-Type", "image/png")
                self.end_headers()
                with open(file_path, "rb") as f:
                    self.wfile.write(f.read())
                return

        # 8. 直接下载 Android 原生客户端 APK
        if path in ("/download", "/download/apk", "/app-debug.apk"):
            apk_path = os.path.join(BASE_DIR, "app-debug.apk")
            if os.path.exists(apk_path):
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.android.package-archive")
                self.send_header("Content-Disposition", 'attachment; filename="NetEaseController-v2.5.0.apk"')
                self.send_header("Content-Length", str(os.path.getsize(apk_path)))
                self.end_headers()
                with open(apk_path, "rb") as f:
                    while True:
                        chunk = f.read(65536)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                return

        self.send_response(404)
        self.end_headers()


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

    port = 10010
    server_address = ("0.0.0.0", port)
    try:
        httpd = HTTPServer(server_address, MusicHandler)
    except OSError as e:
        print(f"\n[错误] 端口 {port} 被占用！请先关闭旧的命令行窗口。")
        print(f"错误详情: {e}")
        input("\n按回车键退出...")
        return

    best_ip, adapter_desc, gateway, secondaries = get_best_lan_ip()
    print("=" * 64)
    print("  网易云音乐遥控器（Modern v2.5 全功能旗舰版）已启动！")
    print(f"  电脑局域网 IP : {best_ip}")
    print(f"  物理网络适配器: {adapter_desc}")
    if gateway:
        print(f"  路由器网关    : {gateway}")
    print(f"  服务监听端口  : {port}")
    print("-" * 64)
    print(f"  [+] 手机浏览器访问 : http://{best_ip}:{port}")
    print(f"  [+] 手机 APP 填写  : {best_ip}:{port}")
    if secondaries:
        print("-" * 64)
        print("  其他网络备用地址 (如需外部/特定网络远程连接):")
        for s in secondaries:
            tag = "VPN/虚拟网卡" if s.get('is_vpn') else "备用网卡"
            print(f"    * http://{s['ip']}:{port} ({s['desc']} [{tag}])")
    print("=" * 64)
    print("支持特性：")
    print("  * 实时曲目追踪 (Now Playing 歌名回显)")
    print("  * 播放模式支持：列表循环 / 单曲循环 / 随机播放 / 顺序播放")
    print("  * 喜欢歌曲红心收藏 (Ctrl+Alt+L)")
    print("  * 从头重播当前歌曲 (Replay from 0:00)")
    print("  * 睡眠定时关机 (15/30/45/60分钟 / 取消)")
    print("  * 双通道按键注入：网易云全局热键 + Windows多媒体硬件键")
    print("正在监听手机指令...\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止。")

if __name__ == "__main__":
    main()
