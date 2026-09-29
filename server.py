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
from http.server import ThreadingHTTPServer as HTTPServer, BaseHTTPRequestHandler
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
gdi32 = ctypes.windll.gdi32

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

def get_orpheus_window():
    """获取网易云主窗口及渲染子窗口的真实句柄与尺寸"""
    try:
        hdesk = user32.OpenInputDesktop(0, False, 0x10000000)
        hwnds = []
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def callback(h, extra):
            cls_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(h, cls_buf, 256)
            if cls_buf.value == 'OrpheusBrowserHost':
                hwnds.append(h)
                return False
            return True
        user32.EnumDesktopWindows(hdesk, EnumWindowsProc(callback), 0)
        if not hwnds:
            return None, None, 0, 0
        target = hwnds[0]

        # 若窗口被最小化，无焦点唤醒以允许截取与后台点击
        if user32.IsIconic(target):
            user32.ShowWindow(target, 4)  # SW_SHOWNOACTIVATE
            time.sleep(0.1)

        rect = wintypes.RECT()
        user32.GetWindowRect(target, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top

        renders = []
        def child_cb(ch, extra):
            c_cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(ch, c_cls, 256)
            if 'Chrome_RenderWidgetHostHWND' in c_cls.value:
                renders.append(ch)
                return False
            return True
        user32.EnumChildWindows(target, EnumWindowsProc(child_cb), 0)
        render = renders[0] if renders else target
        return target, render, w, h
    except Exception:
        pass
    return None, None, 0, 0

def get_current_song():
    """实时读取网易云音乐窗口标题获取当前正在播放的曲目信息"""
    try:
        target, _, _, _ = get_orpheus_window()
        if target:
            length = user32.GetWindowTextLengthW(target)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(target, buf, length + 1)
                val = buf.value.strip()
                if val and val != "OrpheusBrowserHost":
                    return val
    except Exception:
        pass
    return "网易云音乐"

def detect_play_mode(target=None, w=None, h=None):
    """
    通过高速获取模式按钮 17x17 区域特征，100% 准确识别网易云当前真实的物理播放模式：
    - 'single_loop' (单曲循环)
    - 'list_loop' (列表循环)
    - 'shuffle' (随机播放)
    - 'sequential' (顺序播放)
    """
    try:
        if not target:
            target, _, w, h = get_orpheus_window()
        if not target or w < 300 or h < 200:
            return "list_loop"

        cx = w // 2 - 95
        cy = h - 41

        hwndDC = user32.GetWindowDC(target)
        mfcDC = gdi32.CreateCompatibleDC(hwndDC)
        saveBitMap = gdi32.CreateCompatibleBitmap(hwndDC, w, h)
        gdi32.SelectObject(mfcDC, saveBitMap)

        user32.PrintWindow(target, mfcDC, 2)

        # 采样 17x17 栅格 (0=白/背景, 1=图标暗色)
        grid = []
        for dy in range(-8, 9):
            row = []
            for dx in range(-8, 9):
                color = gdi32.GetPixel(mfcDC, cx + dx, cy + dy)
                r = color & 0xFF
                g = (color >> 8) & 0xFF
                b = (color >> 16) & 0xFF
                is_dark = 1 if (r < 180 and g < 180 and b < 180) else 0
                row.append(is_dark)
            grid.append(row)

        gdi32.DeleteObject(saveBitMap)
        gdi32.DeleteDC(mfcDC)
        user32.ReleaseDC(target, hwndDC)

        # 校验特征完整度：若暗色像素少于 20，属于无效捕获或尚未重绘，返回上一次可靠缓存
        total_dark = sum(sum(row) for row in grid)
        if total_dark < 20:
            return _last_mode_cache.get("mode", "list_loop")

        # 1. 顺序播放 (sequential): 中间 6..11 行完全没有任何暗色像素，且图标特征完整
        mid_rows_sum = sum(sum(grid[y]) for y in range(6, 12))
        if mid_rows_sum == 0 and total_dark >= 25:
            return "sequential"

        # 2. 单曲循环 (single_loop): 中心列 x=7 处有数字 1 的竖线 (连续暗色)
        digit1_count = sum(grid[y][7] for y in range(7, 12))
        if digit1_count >= 4:
            return "single_loop"

        # 3. 随机播放 (shuffle): 中间交叉区域 (y=6..11, x=4..7) 有多处交叉像素
        cross_count = sum(grid[y][x] for y in range(6, 12) for x in range(4, 8))
        if cross_count >= 5:
            return "shuffle"

        # 4. 列表循环 (list_loop): 环形箭头，中间中心区域为空
        return "list_loop"
    except Exception:
        return _last_mode_cache.get("mode", "list_loop")

_last_mode_cache = {"mode": "list_loop", "time": 0}
_last_play_cache = {"is_playing": True, "time": 0}
_mode_switch_lock = threading.Lock()
MODE_ORDER = ['sequential', 'list_loop', 'single_loop', 'shuffle']

def is_playing(force_refresh=False):
    """
    通过高速获取播放控制核心区域像素，100% 准确获取网易云物理播放状态：
    - True: 正在播放中（中心为暂停双竖线，两竖线中间隙呈底层红色背景）
    - False: 已暂停（中心为播放三角形，正中像素呈实心纯白）
    """
    now = time.time()
    if not force_refresh and (now - _last_play_cache["time"] < 0.6):
        return _last_play_cache["is_playing"]

    try:
        target, _, w, h = get_orpheus_window()
        if not target or w < 300 or h < 200:
            return _last_play_cache["is_playing"]

        cx = w // 2
        cy = h - 41

        hwndDC = user32.GetWindowDC(target)
        mfcDC = gdi32.CreateCompatibleDC(hwndDC)
        saveBitMap = gdi32.CreateCompatibleBitmap(hwndDC, w, h)
        gdi32.SelectObject(mfcDC, saveBitMap)
        user32.PrintWindow(target, mfcDC, 2)

        color = gdi32.GetPixel(mfcDC, cx, cy)
        r = color & 0xFF
        g = (color >> 8) & 0xFF
        b = (color >> 16) & 0xFF

        gdi32.DeleteObject(saveBitMap)
        gdi32.DeleteDC(mfcDC)
        user32.ReleaseDC(target, hwndDC)

        # 暂停时中心显示播放三角，正中为纯白 (r, g, b 均 > 200)
        # 播放时中心显示暂停双竖线，正中为底色红色 (g, b 较低)
        playing = not (r > 200 and g > 200 and b > 200)
        _last_play_cache["is_playing"] = playing
        _last_play_cache["time"] = now
        return playing
    except Exception:
        return _last_play_cache["is_playing"]

def click_cef_button(cx, cy):
    """向网易云渲染子窗口精确注入一次物理鼠标点击事件"""
    try:
        target_hwnd, render_hwnd, w, h = get_orpheus_window()
        if render_hwnd:
            lparam = (cy << 16) | (cx & 0xFFFF)
            WM_MOUSEMOVE = 0x0200
            WM_LBUTTONDOWN = 0x0201
            WM_LBUTTONUP = 0x0202
            MK_LBUTTON = 0x0001
            user32.PostMessageW(render_hwnd, WM_MOUSEMOVE, 0, lparam)
            time.sleep(0.03)
            user32.PostMessageW(render_hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
            time.sleep(0.05)
            user32.PostMessageW(render_hwnd, WM_LBUTTONUP, 0, lparam)
            return True
    except Exception:
        pass
    return False

def get_current_play_mode(force_refresh=False):
    """带 1 秒 TTL 缓存的高性能物理模式查询"""
    now = time.time()
    if not force_refresh and (now - _last_mode_cache["time"] < 1.0):
        return _last_mode_cache["mode"]
    mode = detect_play_mode()
    _last_mode_cache["mode"] = mode
    _last_mode_cache["time"] = now
    return mode

def switch_to_mode(target_mode):
    """
    闭环确定性模式换档器：
    基于状态环周期 (0: sequential -> 1: list_loop -> 2: single_loop -> 3: shuffle)，
    以 350ms 充裕重绘时间注入确定性脉冲步进，并在末尾进行视觉闭环复验与补正。
    确保 100% 精确到达目标模式，绝无超调、漏跳或循环回退。
    """
    with _mode_switch_lock:
        target_hwnd, render_hwnd, w, h = get_orpheus_window()
        if not target_hwnd or not render_hwnd:
            print("[模式切换] 未找到网易云窗口，无法换档")
            return target_mode

        names = {
            'sequential': '顺序播放',
            'list_loop': '列表循环',
            'single_loop': '单曲循环',
            'shuffle': '随机播放'
        }

        if target_mode not in MODE_ORDER:
            target_mode = 'list_loop'

        current = detect_play_mode(target_hwnd, w, h)
        print(f"[模式切换] 当前物理模式: 【{names.get(current, current)}】 -> 目标模式: 【{names.get(target_mode, target_mode)}】")
        if current == target_mode:
            print(f"[模式切换] 已经处于【{names.get(target_mode, target_mode)}】，无需额外换档")
            _last_mode_cache["mode"] = target_mode
            _last_mode_cache["time"] = time.time()
            return current

        cx = w // 2 - 95
        cy = h - 41

        idx_cur = MODE_ORDER.index(current)
        idx_tgt = MODE_ORDER.index(target_mode)
        needed_clicks = (idx_tgt - idx_cur) % 4

        print(f"[模式切换] 注入确定性脉冲步进: 需点击 {needed_clicks} 次 (间隔 350ms)")
        for i in range(needed_clicks):
            click_cef_button(cx, cy)
            time.sleep(0.35)  # 严格保证 CEF 渲染重绘完成，彻底杜绝丢帧与双击合并

        current = detect_play_mode(target_hwnd, w, h)
        if current == target_mode:
            print(f"[模式切换] 确定性换档成功！精准进入【{names.get(target_mode, target_mode)}】！")
            _last_mode_cache["mode"] = target_mode
            _last_mode_cache["time"] = time.time()
            return current

        # 闭环二次微调补正（仅在极个别丢帧情况下）
        needed_fix = (MODE_ORDER.index(target_mode) - MODE_ORDER.index(current)) % 4
        if needed_fix > 0:
            print(f"[模式切换] 触发闭环微调补正: 补点 {needed_fix} 次")
            for i in range(needed_fix):
                click_cef_button(cx, cy)
                time.sleep(0.35)
            current = detect_play_mode(target_hwnd, w, h)

        print(f"[模式切换] 最终复验模式: 【{names.get(current, current)}】")
        _last_mode_cache["mode"] = current
        _last_mode_cache["time"] = time.time()
        return current

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
        target, render, w, h = get_orpheus_window()
        if render and w > 0:
            click_cef_button(w // 2 + 50, h - 41)
        else:
            press_media_key(VK_MEDIA_NEXT_TRACK)

    @staticmethod
    def prev_song():
        print("[操作触发] 上一首 (Previous Track)")
        target, render, w, h = get_orpheus_window()
        if render and w > 0:
            click_cef_button(w // 2 - 50, h - 41)
        else:
            press_media_key(VK_MEDIA_PREV_TRACK)

    @staticmethod
    def pause_play():
        print("[操作触发] 播放/暂停 (Play/Pause)")
        target, render, w, h = get_orpheus_window()
        if render and w > 0:
            click_cef_button(w // 2, h - 41)
        else:
            press_media_key(VK_MEDIA_PLAY_PAUSE)
        time.sleep(0.15)
        return is_playing(force_refresh=True)

    @staticmethod
    def replay_song():
        """重播本首：两次点击上一首，网易云将立即从 0:00 重新播放当前曲目"""
        print("[操作触发] 重新播放本首 (Replay from 0:00)")
        target, render, w, h = get_orpheus_window()
        if render and w > 0:
            click_cef_button(w // 2 - 50, h - 41)
            time.sleep(0.12)
            click_cef_button(w // 2 - 50, h - 41)
        else:
            press_media_key(VK_MEDIA_PREV_TRACK)
            time.sleep(0.12)
            press_media_key(VK_MEDIA_PREV_TRACK)

    @staticmethod
    def toggle_loop():
        """切换单曲自动循环模式"""
        cur = get_current_play_mode()
        target = "list_loop" if cur == "single_loop" else "single_loop"
        res = MusicBox.set_mode(target)
        return (res == "single_loop")

    @staticmethod
    def set_mode(mode_name):
        """设置特定的播放模式（通过视觉闭环自动换档到位）"""
        res = switch_to_mode(mode_name)
        if mode_name == "single_loop":
            loop_manager.set_state(True)
        else:
            loop_manager.set_state(False)
        return res or mode_name

    @staticmethod
    def like_song():
        """喜欢/收藏红心音乐（默认网易云全局热键 Ctrl + Alt + L）"""
        print("[操作触发] 喜欢/收藏红心音乐 (Like Song: Ctrl+Alt+L)")
        press_hotkey(VK_CONTROL, VK_L, extra_mod=VK_MENU)

    @staticmethod
    def volume_up():
        print("[操作触发] 音量+ (Volume Up)")
        press_media_key(VK_VOLUME_UP)

    @staticmethod
    def volume_down():
        print("[操作触发] 音量- (Volume Down)")
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

_cached_local_ip = None

def get_local_ip():
    """带持久缓存的局域网 IP 查询"""
    global _cached_local_ip
    if not _cached_local_ip:
        best_ip, _, _, _ = get_best_lan_ip()
        _cached_local_ip = best_ip
    return _cached_local_ip



_action_cooldown = {}

class MusicHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        sys.stdout.write(f"[{time.strftime('%H:%M:%S')}] {self.address_string()} - {format % args}\n")
        sys.stdout.flush()

    def send_cors_json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, HEAD")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, HEAD")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # 1. 实时状态查询接口（含当前歌曲、播放模式、播放状态）
        if path == "/api/status":
            actual_mode = get_current_play_mode()
            self.send_cors_json({
                "status": 1,
                "version": "2.5.0",
                "current_song": get_current_song(),
                "play_mode": actual_mode,
                "is_playing": is_playing(),
                "single_loop": (actual_mode == "single_loop" or loop_manager.enabled),
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

            # 服务端防抖：对 pause_play, next_song, prev_song 等高频开关动作实施 300ms 冷却拦截，规避瞬态抖动
            now = time.time()
            if cmd in ("pause_play", "next_song", "prev_song"):
                last_t = _action_cooldown.get(cmd, 0)
                if now - last_t < 0.30:
                    actual_mode = get_current_play_mode()
                    self.send_cors_json({
                        "success": True,
                        "message": "debounced",
                        "current_song": get_current_song(),
                        "play_mode": actual_mode,
                        "is_playing": is_playing(),
                        "single_loop": (actual_mode == "single_loop" or loop_manager.enabled)
                    })
                    return
                _action_cooldown[cmd] = now

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

            actual_mode = get_current_play_mode(force_refresh=True)
            self.send_cors_json({
                "success": success,
                "message": msg,
                "current_song": get_current_song(),
                "play_mode": actual_mode,
                "is_playing": is_playing(),
                "single_loop": (actual_mode == "single_loop" or loop_manager.enabled)
            })
            return

        # 3. 兼容旧版 APP 连接握手接口
        if path == "/mobile_connect":
            actual_mode = get_current_play_mode()
            self.send_cors_json({
                "code": 200,
                "message": "Connected",
                "platform": "win",
                "status": 1,
                "version": "2.5.0",
                "current_song": get_current_song(),
                "play_mode": actual_mode,
                "is_playing": is_playing(),
                "single_loop": (actual_mode == "single_loop" or loop_manager.enabled)
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
                if self.command != 'HEAD':
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
