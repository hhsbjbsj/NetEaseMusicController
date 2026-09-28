# -*- coding: utf-8 -*-
import os
import sys
import time
import json
import ctypes
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import socket

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

user32 = ctypes.windll.user32

# Virtual Key Codes
VK_CONTROL = 0x11
VK_F1 = 0x70
VK_F2 = 0x71
VK_F3 = 0x72
VK_F4 = 0x73
VK_F6 = 0x75

# Multimedia Keys
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002

def press_hotkey(modifier_vk, key_vk):
    mod_scan = user32.MapVirtualKeyW(modifier_vk, 0)
    key_scan = user32.MapVirtualKeyW(key_vk, 0)
    # 1. Press modifier (Ctrl)
    user32.keybd_event(modifier_vk, mod_scan, 0, 0)
    time.sleep(0.04)
    # 2. Press main key (F1/F2/F3...)
    user32.keybd_event(key_vk, key_scan, 0, 0)
    time.sleep(0.06)
    # 3. Release main key FIRST
    user32.keybd_event(key_vk, key_scan, KEYEVENTF_KEYUP, 0)
    time.sleep(0.04)
    # 4. Release modifier (Ctrl) LAST
    user32.keybd_event(modifier_vk, mod_scan, KEYEVENTF_KEYUP, 0)

def press_media_key(media_vk):
    scan = user32.MapVirtualKeyW(media_vk, 0)
    user32.keybd_event(media_vk, scan, KEYEVENTF_EXTENDEDKEY, 0)
    time.sleep(0.06)
    user32.keybd_event(media_vk, scan, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)

class MusicBox:
    @staticmethod
    def next_song():
        print("[操作触发] 下一首 (Next Song)")
        press_hotkey(VK_CONTROL, VK_F3)
        time.sleep(0.03)
        press_media_key(VK_MEDIA_NEXT_TRACK)

    @staticmethod
    def prev_song():
        print("[操作触发] 上一首 (Previous Song)")
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
    def shutdown():
        print("[操作触发] 电脑关机 (Shutdown in 5 seconds)")
        os.system("shutdown -s -t 5")


BASE_DIR = os.path.dirname(os.path.abspath(__file__))

class MusicHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Clean log format
        sys.stdout.write(f"[{time.strftime('%H:%M:%S')}] {self.address_string()} - {format % args}\n")
        sys.stdout.flush()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # 1. Mobile App handshake endpoint
        if path == "/mobile_connect":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            data = {"code": 200, "message": "Connected", "platform": "win", "status": 1, "version": "0.0.1"}
            self.wfile.write(json.dumps(data).encode("utf-8"))
            return

        # 2. Main control endpoint / Web browser UI
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

        # 3. Static files (CSS / JS)
        if path.startswith("/static/"):
            rel_path = path.lstrip("/")
            file_path = os.path.join(BASE_DIR, rel_path)
            if os.path.exists(file_path):
                self.send_response(200)
                if file_path.endswith(".css"):
                    self.send_header("Content-Type", "text/css")
                elif file_path.endswith(".js"):
                    self.send_header("Content-Type", "application/javascript")
                self.end_headers()
                with open(file_path, "rb") as f:
                    self.wfile.write(f.read())
                return

        self.send_response(404)
        self.end_headers()


def main():
    port = 10010
    server_address = ("0.0.0.0", port)
    try:
        httpd = HTTPServer(server_address, MusicHandler)
    except OSError as e:
        print(f"\n[错误] 端口 {port} 被占用！请先关闭旧的黑色命令行窗口（music_switcher.exe）。")
        print(f"错误详情: {e}")
        input("\n按回车键退出...")
        return

    local_ip = get_local_ip()
    print("=" * 60)
    print("  网易云音乐遥控器（强化版）已成功启动！")
    print(f"  电脑本机IP地址 : {local_ip}")
    print(f"  服务监听端口   : {port}")
    print("-" * 60)
    print(f"  手机浏览器访问 : http://{local_ip}:{port}")
    print(f"  手机 APP 填写  : {local_ip}:{port}")
    print("=" * 60)
    print("支持双通道控制：网易云快捷键 (Ctrl+F1~F6) + Windows多媒体切歌键")
    print("正在监听手机指令...\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止。")

if __name__ == "__main__":
    main()
