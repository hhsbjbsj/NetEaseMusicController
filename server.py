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
winmm = ctypes.windll.winmm

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

def press_clean_media_key(vk):
    """发送纯净多媒体硬件按键脉冲（bScan=0，规避非标准映射码污染）"""
    user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY, 0)
    time.sleep(0.04)
    user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)

# ----------------- Windows CoreAudio (WASAPI) 真实系统硬件级主音量与静音控制 -----------------
import comtypes
from comtypes import GUID, IUnknown, COMMETHOD, HRESULT, CoCreateInstance, CLSCTX_INPROC_SERVER

CLSID_MMDeviceEnumerator = GUID('{BCDE0395-E52F-467C-8E3D-C4579291692E}')

class IAudioEndpointVolume(IUnknown):
    _iid_ = GUID('{5CDF2C82-841E-4546-9722-0CF74078229A}')
    _methods_ = [
        COMMETHOD([], HRESULT, 'RegisterControlChangeNotify'),
        COMMETHOD([], HRESULT, 'UnregisterControlChangeNotify'),
        COMMETHOD([], HRESULT, 'GetChannelCount', (['out'], ctypes.POINTER(wintypes.UINT), 'pnChannelCount')),
        COMMETHOD([], HRESULT, 'SetMasterVolumeLevel'),
        COMMETHOD([], HRESULT, 'SetMasterVolumeLevelScalar', (['in'], ctypes.c_float, 'fLevel'), (['in'], ctypes.c_void_p, 'pguidEventContext')),
        COMMETHOD([], HRESULT, 'GetMasterVolumeLevel'),
        COMMETHOD([], HRESULT, 'GetMasterVolumeLevelScalar', (['out'], ctypes.POINTER(ctypes.c_float), 'pfLevel')),
        COMMETHOD([], HRESULT, 'SetChannelVolumeLevel'),
        COMMETHOD([], HRESULT, 'SetChannelVolumeLevelScalar'),
        COMMETHOD([], HRESULT, 'GetChannelVolumeLevel'),
        COMMETHOD([], HRESULT, 'GetChannelVolumeLevelScalar'),
        COMMETHOD([], HRESULT, 'SetMute', (['in'], wintypes.BOOL, 'bMute'), (['in'], ctypes.c_void_p, 'pguidEventContext')),
        COMMETHOD([], HRESULT, 'GetMute', (['out'], ctypes.POINTER(wintypes.BOOL), 'pbMute')),
        COMMETHOD([], HRESULT, 'GetVolumeStepInfo'),
        COMMETHOD([], HRESULT, 'VolumeStepUp'),
        COMMETHOD([], HRESULT, 'VolumeStepDown'),
        COMMETHOD([], HRESULT, 'QueryHardwareSupport'),
        COMMETHOD([], HRESULT, 'GetVolumeRange')
    ]

class IMMDevice(IUnknown):
    _iid_ = GUID('{D666063F-1587-4E43-81F1-B948E807363F}')
    _methods_ = [
        COMMETHOD([], HRESULT, 'Activate',
                  (['in'], ctypes.POINTER(GUID), 'iid'),
                  (['in'], wintypes.DWORD, 'dwClsCtx'),
                  (['in'], ctypes.c_void_p, 'pActivationParams'),
                  (['out'], ctypes.POINTER(ctypes.POINTER(IAudioEndpointVolume)), 'ppInterface')),
        COMMETHOD([], HRESULT, 'OpenPropertyStore'),
        COMMETHOD([], HRESULT, 'GetId', (['out'], ctypes.POINTER(wintypes.LPWSTR), 'ppstrId'))
    ]

class IMMDeviceCollection(IUnknown):
    _iid_ = GUID('{0BD7A1BE-7A1A-44DB-8397-CC5392387B5E}')
    _methods_ = [
        COMMETHOD([], HRESULT, 'GetCount',
                  (['out'], ctypes.POINTER(wintypes.UINT), 'pcDevices')),
        COMMETHOD([], HRESULT, 'Item',
                  (['in'], wintypes.UINT, 'nDevice'),
                  (['out'], ctypes.POINTER(ctypes.POINTER(IMMDevice)), 'ppDevice'))
    ]

class IMMDeviceEnumerator(IUnknown):
    _iid_ = GUID('{A95664D2-9614-4F35-A746-DE8DB63617E6}')
    _methods_ = [
        COMMETHOD([], HRESULT, 'EnumAudioEndpoints',
                  (['in'], wintypes.DWORD, 'dataFlow'),
                  (['in'], wintypes.DWORD, 'dwStateMask'),
                  (['out'], ctypes.POINTER(ctypes.POINTER(IMMDeviceCollection)), 'ppDevices')),
        COMMETHOD([], HRESULT, 'GetDefaultAudioEndpoint',
                  (['in'], wintypes.DWORD, 'dataFlow'),
                  (['in'], wintypes.DWORD, 'role'),
                  (['out'], ctypes.POINTER(ctypes.POINTER(IMMDevice)), 'ppEndpoint'))
    ]

_audio_lock = threading.Lock()

def get_real_master_volume():
    """获取当前系统默认输出端点的真实硬件主音量百分比 (0-100)"""
    with _audio_lock:
        try:
            try:
                comtypes.CoInitialize()
            except Exception:
                pass
            enumerator = CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, CLSCTX_INPROC_SERVER)
            dev = enumerator.GetDefaultAudioEndpoint(0, 1) # eRender=0, eMultimedia=1
            ep = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_INPROC_SERVER, None)
            level = ep.GetMasterVolumeLevelScalar()
            return max(0, min(100, round(level * 100)))
        except Exception:
            return _volume_state.get("volume", 70)

def set_real_master_volume(pct):
    """
    向 Windows 默认音频端点及所有处于活动状态的输出设备（扬声器、耳机、VoiceMeeter 等）
    同步写入真实硬件级主音量 (0-100)
    """
    pct = max(0, min(100, int(pct)))
    scalar = float(pct) / 100.0
    with _audio_lock:
        try:
            try:
                comtypes.CoInitialize()
            except Exception:
                pass
            enumerator = CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, CLSCTX_INPROC_SERVER)
            # 1. 遍历并设定所有活跃渲染设备 (DEVICE_STATE_ACTIVE = 1)
            try:
                col = enumerator.EnumAudioEndpoints(0, 1)
                count = col.GetCount()
                for i in range(count):
                    try:
                        d = col.Item(i)
                        ep = d.Activate(IAudioEndpointVolume._iid_, CLSCTX_INPROC_SERVER, None)
                        ep.SetMasterVolumeLevelScalar(scalar, None)
                        if pct > 0:
                            ep.SetMute(False, None)
                    except Exception:
                        pass
            except Exception:
                pass
            # 2. 确保默认多媒体端点精准写入
            try:
                def_dev = enumerator.GetDefaultAudioEndpoint(0, 1)
                ep = def_dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_INPROC_SERVER, None)
                ep.SetMasterVolumeLevelScalar(scalar, None)
                if pct > 0:
                    ep.SetMute(False, None)
            except Exception:
                pass
        except Exception as e:
            print(f"[WASAPI] 写入主音量异常: {e}")

    # 兜底联动写入 waveOut
    try:
        set_sys_wave_volume(pct)
    except Exception:
        pass

    _volume_state["volume"] = pct
    if pct > 0:
        _volume_state["is_muted"] = False
    return pct

def set_real_master_mute(mute_bool):
    """向所有活动音频设备下发系统底层真实静音/解静音指令"""
    mute_bool = bool(mute_bool)
    with _audio_lock:
        try:
            try:
                comtypes.CoInitialize()
            except Exception:
                pass
            enumerator = CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, CLSCTX_INPROC_SERVER)
            try:
                col = enumerator.EnumAudioEndpoints(0, 1)
                count = col.GetCount()
                for i in range(count):
                    try:
                        d = col.Item(i)
                        ep = d.Activate(IAudioEndpointVolume._iid_, CLSCTX_INPROC_SERVER, None)
                        ep.SetMute(mute_bool, None)
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                def_dev = enumerator.GetDefaultAudioEndpoint(0, 1)
                ep = def_dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_INPROC_SERVER, None)
                ep.SetMute(mute_bool, None)
            except Exception:
                pass
        except Exception as e:
            print(f"[WASAPI] 设置静音异常: {e}")

    _volume_state["is_muted"] = mute_bool
    return mute_bool

def get_real_master_mute():
    """获取 Windows 默认音频端点当前的静音状态"""
    with _audio_lock:
        try:
            try:
                comtypes.CoInitialize()
            except Exception:
                pass
            enumerator = CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, CLSCTX_INPROC_SERVER)
            def_dev = enumerator.GetDefaultAudioEndpoint(0, 1)
            ep = def_dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_INPROC_SERVER, None)
            return bool(ep.GetMute())
        except Exception:
            return _volume_state.get("is_muted", False)

def get_sys_wave_volume():
    """获取系统 WaveOut 底层音量百分比 (0-100)"""
    try:
        vol = wintypes.DWORD()
        res = winmm.waveOutGetVolume(0, ctypes.byref(vol))
        if res == 0:
            left = vol.value & 0xFFFF
            return max(0, min(100, round((left / 65535.0) * 100)))
    except Exception:
        pass
    return 100

def set_sys_wave_volume(pct):
    """向系统所有底层音频输出设备写入统一音量 (0-100)"""
    pct = max(0, min(100, int(pct)))
    val = int(pct * 65535 / 100) & 0xFFFF
    dw_vol = (val << 16) | val
    try:
        num = winmm.waveOutGetNumDevs()
        for i in range(num):
            winmm.waveOutSetVolume(i, dw_vol)
    except Exception:
        pass
    return pct

_volume_state = {
    "volume": get_real_master_volume(),
    "is_muted": get_real_master_mute(),
    "last_vol": get_real_master_volume() or 80
}

_last_mute_cache = {"is_muted": False, "time": 0}

def is_audio_muted(target=None, w=None, h=None, force_refresh=False):
    """精准探测网易云底栏喇叭图标当前是否处于静音 X 态（带 1 秒 TTL 缓存）"""
    now = time.time()
    if not force_refresh and (now - _last_mute_cache["time"] < 1.0):
        return _last_mute_cache["is_muted"]

    try:
        if not target:
            target, _, w, h = get_orpheus_window()
        if not target or w < 300 or h < 200:
            return _volume_state.get("is_muted", False)

        hwndDC = user32.GetWindowDC(target)
        mfcDC = gdi32.CreateCompatibleDC(hwndDC)
        saveBitMap = gdi32.CreateCompatibleBitmap(hwndDC, w, h)
        gdi32.SelectObject(mfcDC, saveBitMap)
        user32.PrintWindow(target, mfcDC, 2)

        bg_r = gdi32.GetPixel(mfcDC, 20, h - 15) & 0xFF
        is_dark = (bg_r < 100)
        c = gdi32.GetPixel(mfcDC, w - 74, h - 41)
        r = c & 0xFF

        gdi32.DeleteObject(saveBitMap)
        gdi32.DeleteDC(mfcDC)
        user32.ReleaseDC(target, hwndDC)

        muted = (r > 60) if is_dark else (r < 160)
        _volume_state["is_muted"] = muted
        _last_mute_cache["is_muted"] = muted
        _last_mute_cache["time"] = now
        return muted
    except Exception:
        return _volume_state.get("is_muted", False)


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

        # 采样 17x17 栅格 (0=白/背景, 1=图标暗色，阈值设为 220 以稳定捕捉抗锯齿浅灰像素)
        grid = []
        for dy in range(-8, 9):
            row = []
            for dx in range(-8, 9):
                color = gdi32.GetPixel(mfcDC, cx + dx, cy + dy)
                r = color & 0xFF
                g = (color >> 8) & 0xFF
                b = (color >> 16) & 0xFF
                is_dark = 1 if (r < 220 and g < 220 and b < 220) else 0
                row.append(is_dark)
            grid.append(row)

        gdi32.DeleteObject(saveBitMap)
        gdi32.DeleteDC(mfcDC)
        user32.ReleaseDC(target, hwndDC)

        # 校验特征完整度：若暗色像素少于 45，说明 CEF 正处于点击动画过渡态中，稍等 150ms 重新截取稳定帧
        total_dark = sum(sum(row) for row in grid)
        if total_dark < 45:
            time.sleep(0.15)
            hwndDC = user32.GetWindowDC(target)
            mfcDC = gdi32.CreateCompatibleDC(hwndDC)
            saveBitMap = gdi32.CreateCompatibleBitmap(hwndDC, w, h)
            gdi32.SelectObject(mfcDC, saveBitMap)
            user32.PrintWindow(target, mfcDC, 2)
            grid = []
            for dy in range(-8, 9):
                row = []
                for dx in range(-8, 9):
                    color = gdi32.GetPixel(mfcDC, cx + dx, cy + dy)
                    r = color & 0xFF
                    g = (color >> 8) & 0xFF
                    b = (color >> 16) & 0xFF
                    is_dark = 1 if (r < 220 and g < 220 and b < 220) else 0
                    row.append(is_dark)
                grid.append(row)
            gdi32.DeleteObject(saveBitMap)
            gdi32.DeleteDC(mfcDC)
            user32.ReleaseDC(target, hwndDC)
            total_dark = sum(sum(row) for row in grid)
            if total_dark < 30:
                return _last_mode_cache.get("mode", "list_loop")

        # 1. 顺序播放 (sequential): 中间 6..11 行完全没有任何暗色像素 (双平箭头)
        mid_rows_sum = sum(sum(grid[y]) for y in range(6, 12))
        if mid_rows_sum == 0 and total_dark >= 40:
            return "sequential"

        # 2. 单曲循环 (single_loop): 中心竖线在 col 7..8 (数字 1 竖线特征累积 >= 8)
        col7_8 = sum(grid[y][x] for y in range(6, 13) for x in (7, 8))
        if col7_8 >= 8:
            return "single_loop"

        # 3. 随机播放 (shuffle): 左侧交叉区域 (rows 6..11, cols 3..6 交叉线特征累积 >= 7)
        cross_box = sum(grid[y][x] for y in range(6, 12) for x in range(3, 7))
        if cross_box >= 7:
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
            time.sleep(0.04)
            user32.PostMessageW(render_hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lparam)
            time.sleep(0.06)
            user32.PostMessageW(render_hwnd, WM_LBUTTONUP, 0, lparam)
            return True
    except Exception:
        pass
    return False

_last_liked_cache = {"is_liked": False, "time": 0, "song": ""}

def locate_heart_button(target=None, w=None, h=None):
    """
    通过像素扫描毫秒级精准定位网易云底栏红心收藏按钮的物理坐标与喜欢状态：
    - 返回: (cx, cy, is_liked)
    - 智能兼容：浅色主题、深色沉浸歌词页、任意歌曲名长度、VIP角标、评语角标
    """
    try:
        if not target:
            target, _, w, h = get_orpheus_window()
        if not target or w < 300 or h < 200:
            return 250, (h - 41) if h else 711, False

        hwndDC = user32.GetWindowDC(target)
        mfcDC = gdi32.CreateCompatibleDC(hwndDC)
        saveBitMap = gdi32.CreateCompatibleBitmap(hwndDC, w, h)
        gdi32.SelectObject(mfcDC, saveBitMap)
        user32.PrintWindow(target, mfcDC, 2)

        # 1. 检测是否已红心收藏（已喜欢状态）
        # 粗扫：以步长 2 高速侦测是否存在高饱和度红色像素团
        red_pts = []
        for y in range(h - 52, h - 30, 2):
            for x in range(140, min(w, 420), 2):
                c = gdi32.GetPixel(mfcDC, x, y)
                r = c & 0xFF
                g = (c >> 8) & 0xFF
                b = (c >> 16) & 0xFF
                if r > 190 and g < 100 and b < 100:
                    red_pts.append((x, y))

        if len(red_pts) >= 10:
            # 细扫聚类：精确计算红心中心，排除 VIP/角标小噪点
            min_rx = max(140, min(p[0] for p in red_pts) - 10)
            max_rx = min(w, max(p[0] for p in red_pts) + 10)
            all_red = []
            for y in range(h - 55, h - 25):
                for x in range(min_rx, max_rx):
                    c = gdi32.GetPixel(mfcDC, x, y)
                    r = c & 0xFF
                    g = (c >> 8) & 0xFF
                    b = (c >> 16) & 0xFF
                    if r > 190 and g < 100 and b < 100:
                        all_red.append((x, y))
            if len(all_red) >= 40:
                xs = [p[0] for p in all_red]
                ys = [p[1] for p in all_red]
                cx = (min(xs) + max(xs)) // 2
                cy = (min(ys) + max(ys)) // 2
                gdi32.DeleteObject(saveBitMap)
                gdi32.DeleteDC(mfcDC)
                user32.ReleaseDC(target, hwndDC)
                return cx, cy, True

        # 2. 未收藏状态：特征模板扫描定位空心心形轮廓
        y_tip = h - 32
        # 在底栏安全空白区采样背景底色（防误判深/浅色模式）
        bg_color = gdi32.GetPixel(mfcDC, 20, h - 15)
        bg_r = bg_color & 0xFF
        is_dark = (bg_r < 100)

        def is_outline(x, y):
            c = gdi32.GetPixel(mfcDC, x, y)
            r = c & 0xFF
            return (r > 60) if is_dark else (r < 215)

        def is_bg(x, y):
            return not is_outline(x, y)

        best_score = 0
        best_x = 250

        for x in range(150, min(w - 20, 420)):
            # 快速剪枝：心形底尖 y_tip 必须为轮廓像素
            if not is_outline(x, y_tip):
                continue

            score = 2
            # 向上中轴必须为空心背景
            if is_bg(x, y_tip - 1): score += 2
            if is_bg(x, y_tip - 2): score += 2
            if is_bg(x, y_tip - 3): score += 2
            if is_bg(x, y_tip - 4): score += 2
            if is_bg(x, y_tip - 5): score += 2
            if is_bg(x, y_tip - 6): score += 2

            # 两侧对称 V 型轮廓展开校验
            if is_outline(x - 3, y_tip - 1) or is_outline(x - 2, y_tip - 1): score += 2
            if is_outline(x + 2, y_tip - 1) or is_outline(x + 3, y_tip - 1): score += 2
            if is_outline(x - 5, y_tip - 2) or is_outline(x - 4, y_tip - 2): score += 2
            if is_outline(x + 4, y_tip - 2) or is_outline(x + 5, y_tip - 2): score += 2
            if is_outline(x - 6, y_tip - 3) or is_outline(x - 5, y_tip - 3): score += 2
            if is_outline(x + 5, y_tip - 3) or is_outline(x + 6, y_tip - 3): score += 2
            if is_outline(x - 7, y_tip - 4) or is_outline(x - 6, y_tip - 4): score += 2
            if is_outline(x + 6, y_tip - 4) or is_outline(x + 7, y_tip - 4): score += 2
            if is_outline(x - 5, y_tip - 17): score += 2

            if score > best_score:
                best_score = score
                best_x = x

        gdi32.DeleteObject(saveBitMap)
        gdi32.DeleteDC(mfcDC)
        user32.ReleaseDC(target, hwndDC)
        return best_x, h - 41, False
    except Exception:
        pass
    return 250, (h - 41) if h else 711, False

def is_song_liked(force_refresh=False):
    """带 1 秒 TTL 缓存的当前歌曲喜欢状态查询"""
    now = time.time()
    cur_song = get_current_song()
    if not force_refresh and (now - _last_liked_cache["time"] < 1.0) and (_last_liked_cache["song"] == cur_song):
        return _last_liked_cache["is_liked"]

    target, _, w, h = get_orpheus_window()
    _, _, liked = locate_heart_button(target, w, h)
    _last_liked_cache["is_liked"] = liked
    _last_liked_cache["time"] = now
    _last_liked_cache["song"] = cur_song
    return liked

def is_progress_near_end(target, w, h):
    """
    通过采样网易云播放进度条末梢 (98.2% 处) 像素，毫秒级侦测当前曲目是否已临近播毕 (最后 1-2 秒)：
    - True: 进度条已红化至 >= 98.2%，曲目即将自然结束
    - False: 正在常规播放区间
    """
    try:
        if not target or w < 300 or h < 200:
            return False
        test_x = int(w * 0.982)
        y = h - 82

        hwndDC = user32.GetWindowDC(target)
        mfcDC = gdi32.CreateCompatibleDC(hwndDC)
        saveBitMap = gdi32.CreateCompatibleBitmap(hwndDC, w, h)
        gdi32.SelectObject(mfcDC, saveBitMap)
        user32.PrintWindow(target, mfcDC, 2)

        c = gdi32.GetPixel(mfcDC, test_x, y)
        r = c & 0xFF
        g = (c >> 8) & 0xFF
        b = (c >> 16) & 0xFF

        gdi32.DeleteObject(saveBitMap)
        gdi32.DeleteDC(mfcDC)
        user32.ReleaseDC(target, hwndDC)

        return (r > 200 and g < 150 and b < 160)
    except Exception:
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
    基于状态环周期 (sequential -> list_loop -> single_loop -> shuffle)，
    以 550ms 充裕重绘时间（彻底跨越 Windows 500ms 双击阈值）注入脉冲步进，
    并在末尾进行视觉闭环复验。
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

        print(f"[模式切换] 注入确定性脉冲步进: 需点击 {needed_clicks} 次 (间隔 550ms)")
        for i in range(needed_clicks):
            click_cef_button(cx, cy)
            time.sleep(0.55)  # 严格大于 Windows 500ms 双击阈值，确保 CEF 完整单次点击重绘

        time.sleep(0.3)
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
                time.sleep(0.55)
            time.sleep(0.3)
            current = detect_play_mode(target_hwnd, w, h)

        print(f"[模式切换] 最终复验模式: 【{names.get(current, current)}】")
        _last_mode_cache["mode"] = current
        _last_mode_cache["time"] = time.time()
        return current

class SingleSongLoopManager:
    """
    新一代双核智能单曲循环引擎 (Dual-Core Seamless Looper):
    解决网易云音乐桌面端在特定歌单/私人FM/动态推荐/心动模式下单曲循环失效跳下一首的核心痛点：
    1. 前瞻式平滑重播 (Proactive Seamless Looper): 进度条达 98.2% 时在跳歌前主动无缝回弹 0:00，零卡顿零杂音。
    2. 反应式保底哨兵 (Reactive Guard): 毫秒级监控曲目标题，若网易云异常跳歌，立即自动无缝拉回上一首。
    3. 智能人工意图识别: 用户手动在手机遥控或电脑切歌时，自动接纳新曲目为新循环目标，绝不阻碍正常切歌。
    """
    def __init__(self):
        self.enabled = False
        self.target_song = ""
        self.interval = 0
        self.last_manual_switch_time = 0
        self.worker_thread = None
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.start_worker()

    def notify_manual_switch(self):
        """用户主动执行了上一首/下一首操作，授予 3.5 秒人工切歌保护期并更新循环锚点"""
        self.last_manual_switch_time = time.time()
        def _update():
            time.sleep(1.0)
            new_s = get_current_song()
            if new_s and new_s not in ("网易云音乐", "OrpheusBrowserHost"):
                self.target_song = new_s
                print(f"[智能单曲循环引擎] 用户手动切歌，循环目标曲目已更新为: 【{self.target_song}】")
        threading.Thread(target=_update, daemon=True).start()

    def set_state(self, state, interval=None):
        with self.lock:
            self.enabled = bool(state)
            if self.enabled:
                cur = get_current_song()
                if cur and cur not in ("网易云音乐", "OrpheusBrowserHost"):
                    self.target_song = cur
                print(f"[智能单曲循环引擎] 已开启！持续循环锁定曲目: 【{self.target_song}】")
            else:
                print("[智能单曲循环引擎] 已关闭")
            return self.enabled

    def toggle(self):
        return self.set_state(not self.enabled)

    def start_worker(self):
        if self.worker_thread and self.worker_thread.is_alive():
            return
        self.stop_event.clear()
        self.worker_thread = threading.Thread(target=self._loop_worker, daemon=True)
        self.worker_thread.start()

    def _loop_worker(self):
        last_prog_check = 0
        while not self.stop_event.is_set():
            time.sleep(0.20)
            if not self.enabled:
                continue

            # 暂停时不触发重播
            if not is_playing():
                continue

            now = time.time()
            # 人工手动切歌保护期
            if now - self.last_manual_switch_time < 3.5:
                continue

            current = get_current_song()
            if not current or current in ("网易云音乐", "OrpheusBrowserHost"):
                continue

            # 首次记录目标曲目
            if not self.target_song:
                self.target_song = current
                continue

            # 1. 反应式保底哨兵 (Reactive Guard):
            # 若曲目已被网易云换档至下一首，立即强力无缝拉回上一首并从 0:00 播放
            if current != self.target_song:
                print(f"[智能单曲循环引擎] 监测到曲目自然结束并跳转至【{current}】，立即自动无缝拉回【{self.target_song}】！")
                MusicBox.prev_song_internal()
                time.sleep(0.3)
                MusicBox.seek_to_start()
                time.sleep(1.2)
                self.target_song = get_current_song()
                continue

            # 2. 前瞻式平滑重播引擎 (Proactive Seamless Looper):
            # 每 0.6 秒扫描一次播放进度条尾部 (98.2%)。
            # 若接近播放尾声，提前回弹 0:00，彻底避免跳歌闪烁
            if now - last_prog_check >= 0.6:
                last_prog_check = now
                target_hwnd, _, w, h = get_orpheus_window()
                if target_hwnd and w > 0:
                    if is_progress_near_end(target_hwnd, w, h):
                        print(f"[智能单曲循环引擎] 曲目【{self.target_song}】进度已达 98.2%，主动注入 0:00 无缝从头重播！")
                        MusicBox.seek_to_start()
                        time.sleep(2.5) # 避开重播前 2.5 秒，防止重复触发

loop_manager = SingleSongLoopManager()

# 全局播放模式状态追踪：'list_loop' (列表循环), 'single_loop' (单曲循环), 'shuffle' (随机播放), 'sequential' (顺序播放)
current_play_mode = "list_loop"

class MusicBox:
    @staticmethod
    def seek_to_start():
        """将当前曲目瞬间无缝拉回 0:00"""
        target, render, w, h = get_orpheus_window()
        if render and w > 0:
            click_cef_button(20, h - 82)
        else:
            press_media_key(VK_MEDIA_PREV_TRACK)
            time.sleep(0.12)
            press_media_key(VK_MEDIA_PREV_TRACK)

    @staticmethod
    def prev_song_internal():
        """底层无感切回上一首，不刷新 manual switch 标记"""
        target, render, w, h = get_orpheus_window()
        if render and w > 0:
            click_cef_button(w // 2 - 50, h - 41)
        else:
            press_media_key(VK_MEDIA_PREV_TRACK)

    @staticmethod
    def next_song():
        print("[操作触发] 下一首 (Next Track)")
        loop_manager.notify_manual_switch()
        target, render, w, h = get_orpheus_window()
        if render and w > 0:
            click_cef_button(w // 2 + 50, h - 41)
        else:
            press_media_key(VK_MEDIA_NEXT_TRACK)

    @staticmethod
    def prev_song():
        print("[操作触发] 上一首 (Previous Track)")
        loop_manager.notify_manual_switch()
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
        """从头重播当前曲目"""
        print("[操作触发] 重新播放本首 (Replay from 0:00)")
        MusicBox.seek_to_start()

    @staticmethod
    def toggle_loop():
        """切换单曲自动循环模式"""
        cur = get_current_play_mode()
        target = "list_loop" if cur == "single_loop" else "single_loop"
        res = MusicBox.set_mode(target)
        return (res == "single_loop")

    @staticmethod
    def set_mode(mode_name):
        """设置特定的播放模式（通过视觉闭环自动换档到位，并联动智能循环引擎）"""
        res = switch_to_mode(mode_name)
        if mode_name == "single_loop" or res == "single_loop":
            loop_manager.set_state(True)
        else:
            loop_manager.set_state(False)
        return res or mode_name

    @staticmethod
    def like_song():
        """喜欢/收藏红心音乐（物理精准定位红心图标点击 + 全局热键双通道注入）"""
        print("[操作触发] 喜欢/收藏红心音乐 (Like Song: Physical CEF Click + Hotkey Injection)")
        cur_song = get_current_song()
        target, render, w, h = get_orpheus_window()
        if target and render:
            cx, cy, init_liked = locate_heart_button(target, w, h)
            print(f"[红心定位] 找到红心按钮坐标: ({cx}, {cy}), 当前喜欢状态: {init_liked}")
            click_cef_button(cx, cy)
            time.sleep(0.65)
            _, _, new_liked = locate_heart_button(target, w, h)
            # 若状态未翻转，补充一次脉冲
            if new_liked == init_liked:
                print("[红心重试] 补充脉冲点击...")
                click_cef_button(cx, cy)
                time.sleep(0.65)
                _, _, new_liked = locate_heart_button(target, w, h)

            _last_liked_cache["is_liked"] = new_liked
            _last_liked_cache["time"] = time.time()
            _last_liked_cache["song"] = cur_song
            print(f"[红心结果] 最新喜欢状态: {new_liked}")
            return new_liked
        else:
            press_hotkey(VK_CONTROL, VK_L, extra_mod=VK_MENU)
            return False

    @staticmethod
    def volume_mute():
        """静音切换（网易云底栏喇叭物理静音 + Windows CoreAudio 真实主静音双重联动）"""
        print("[操作触发] 静音切换 (Mute Toggle)")
        target, render, w, h = get_orpheus_window()
        cur_muted = (is_audio_muted(target, w, h, force_refresh=True) or get_real_master_mute() or _volume_state.get("is_muted", False))
        target_muted = not cur_muted

        # 1. 物理点击网易云底栏喇叭图标翻转静音
        if target and render:
            click_cef_button(w - 82, h - 41)
            time.sleep(0.20)
            is_audio_muted(target, w, h, force_refresh=True)

        # 2. Windows WASAPI 系统真实硬件静音全端点同步
        set_real_master_mute(target_muted)

        # 3. 记录与恢复最后音量
        if target_muted:
            _volume_state["last_vol"] = get_real_master_volume() or _volume_state.get("volume", 80)
        else:
            last = _volume_state.get("last_vol", 80) or 80
            set_real_master_volume(last)

        _volume_state["is_muted"] = target_muted
        print(f"[静音结果] 状态: {'已静音' if target_muted else '已取消静音'}")
        return target_muted

    @staticmethod
    def volume_up(step=5):
        """音量+（调大真实主音量并自动解除静音）"""
        target, render, w, h = get_orpheus_window()
        if is_audio_muted(target, w, h, force_refresh=True):
            if target and render:
                click_cef_button(w - 82, h - 41)
                time.sleep(0.15)

        set_real_master_mute(False)

        cur_vol = get_real_master_volume()
        new_vol = min(100, cur_vol + step)
        set_real_master_volume(new_vol)
        print(f"[操作触发] 音量+ (Volume Up) -> {new_vol}%")
        return new_vol

    @staticmethod
    def volume_down(step=5):
        """音量-（调小真实主音量）"""
        target, render, w, h = get_orpheus_window()
        cur_vol = get_real_master_volume()
        new_vol = max(0, cur_vol - step)

        if new_vol == 0:
            set_real_master_volume(0)
            set_real_master_mute(True)
            if not is_audio_muted(target, w, h, force_refresh=True):
                if target and render:
                    click_cef_button(w - 82, h - 41)
            _volume_state["is_muted"] = True
        else:
            if is_audio_muted(target, w, h, force_refresh=True):
                if target and render:
                    click_cef_button(w - 82, h - 41)
                    time.sleep(0.15)
            set_real_master_mute(False)
            set_real_master_volume(new_vol)
            _volume_state["is_muted"] = False

        print(f"[操作触发] 音量- (Volume Down) -> {new_vol}%")
        return new_vol

    @staticmethod
    def set_volume(target_vol):
        """设定指定音量 (0-100)"""
        try:
            val = int(target_vol)
        except (ValueError, TypeError):
            val = 50
        val = max(0, min(100, val))
        target, render, w, h = get_orpheus_window()

        if val > 0:
            if is_audio_muted(target, w, h, force_refresh=True):
                if target and render:
                    click_cef_button(w - 82, h - 41)
                    time.sleep(0.15)
            set_real_master_mute(False)
            set_real_master_volume(val)
            _volume_state["is_muted"] = False
        else:
            set_real_master_volume(0)
            set_real_master_mute(True)
            if not is_audio_muted(target, w, h, force_refresh=True):
                if target and render:
                    click_cef_button(w - 82, h - 41)
            _volume_state["is_muted"] = True

        print(f"[操作触发] 设定音量为: {val}%")
        return val

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

        # 1. 实时状态查询接口（含当前歌曲、播放模式、播放状态、喜欢状态、音量信息）
        if path == "/api/status":
            actual_mode = get_current_play_mode()
            self.send_cors_json({
                "status": 1,
                "version": "2.5.0",
                "current_song": get_current_song(),
                "play_mode": actual_mode,
                "is_playing": is_playing(),
                "is_liked": is_song_liked(),
                "volume": get_real_master_volume(),
                "is_muted": (is_audio_muted() or get_real_master_mute() or _volume_state.get("is_muted", False)),
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
                        "is_liked": is_song_liked(),
                        "volume": get_real_master_volume(),
                        "is_muted": _volume_state.get("is_muted", False),
                        "single_loop": (actual_mode == "single_loop" or loop_manager.enabled)
                    })
                    return
                _action_cooldown[cmd] = now

            if cmd == "set_mode":
                MusicBox.set_mode(val or "list_loop")
            elif cmd == "set_loop":
                state = query.get("state", ["true"])[0].lower() in ("true", "1")
                loop_manager.set_state(state, val)
            elif cmd == "set_volume":
                res = MusicBox.set_volume(val or 50)
                msg = f"音量已设为 {res}%"
            elif cmd == "schedule_shutdown":
                MusicBox.schedule_shutdown(val or 30)
            elif cmd and hasattr(MusicBox, cmd):
                res = getattr(MusicBox, cmd)()
                if cmd == "toggle_loop":
                    msg = "enabled" if res else "disabled"
                elif cmd == "like_song":
                    msg = "已添加到我喜欢的音乐" if res else "已取消喜欢"
                elif cmd == "volume_mute":
                    msg = "已开启静音" if res else "已取消静音"
                elif cmd in ("volume_up", "volume_down"):
                    msg = f"当前音量: {res}%"
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
                "is_liked": is_song_liked(force_refresh=(cmd == "like_song")),
                "volume": get_real_master_volume(),
                "is_muted": _volume_state.get("is_muted", False),
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
                "is_liked": is_song_liked(),
                "volume": get_real_master_volume(),
                "is_muted": (is_audio_muted() or get_real_master_mute() or _volume_state.get("is_muted", False)),
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

    try:
        comtypes.CoInitialize()
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
        init_mode = detect_play_mode()
        if init_mode == "single_loop":
            loop_manager.set_state(True)
    except Exception:
        pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止。")

if __name__ == "__main__":
    main()
