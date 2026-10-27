"""wifi-panel PC Agent。

主动外连中枢的 WebSocket（PC 端不开端口、不动防火墙），
接收动作指令并用 pynput 注入鼠标键盘事件。

用法：
  python agent.py [ws://hub:8765/ws/agent] [token] [--name 客厅主机] [--id pc-xxxxxx]
环境变量：
  PANEL_URL    中枢地址（默认 ws://localhost:8765/ws/agent）
  PANEL_TOKEN  访问令牌（默认 panel123）
  PANEL_NAME   设备显示名（默认取主机名）
  PANEL_ID     设备唯一 id（默认自动生成并保存到 agent/.agent_id）

多台电脑：每台电脑的 id 不同，中枢会把它们当成不同设备，
手机上可以分别选「客厅主机 / 书房主机」，也可以用「全部电脑」一起发指令。
"""
import argparse
import asyncio
import json
import os
import platform
import re
import uuid
from pathlib import Path
from urllib.parse import quote

import websockets
from pynput.keyboard import Controller as Keyboard, Key, KeyCode
from pynput.mouse import Button, Controller as Mouse

ID_FILE = Path(__file__).resolve().parent / ".agent_id"


def _load_or_make_id() -> str:
    """设备 id 必须跨重启稳定，否则每次重连在中枢看来都是新设备。"""
    try:
        if ID_FILE.exists():
            saved = ID_FILE.read_text(encoding="utf-8").strip()
            if re.fullmatch(r"[A-Za-z0-9_-]{1,32}", saved):
                return saved
        made = "pc-" + uuid.uuid4().hex[:6]
        ID_FILE.write_text(made, encoding="utf-8")
        return made
    except Exception:
        return "pc-" + uuid.uuid4().hex[:6]


def _parse_args():
    ap = argparse.ArgumentParser(description="wifi-panel PC Agent")
    ap.add_argument("url", nargs="?", help="中枢地址，如 ws://192.168.1.10:8765/ws/agent")
    ap.add_argument("token", nargs="?", help="访问令牌")
    ap.add_argument("--name", help="设备显示名，如 客厅主机")
    ap.add_argument("--id", help="设备唯一 id（默认自动生成）")
    return ap.parse_args()


ARGS = _parse_args()
HUB = ARGS.url or os.environ.get("PANEL_URL", "ws://localhost:8765/ws/agent")
TOKEN = ARGS.token or os.environ.get("PANEL_TOKEN", "panel123")
AGENT_ID = (ARGS.id or os.environ.get("PANEL_ID") or _load_or_make_id()).strip()
NAME = (ARGS.name or os.environ.get("PANEL_NAME") or platform.node() or AGENT_ID).strip()[:24]
VERSION = "0.2"

SPECIAL_KEYS = {
    "space": Key.space, "enter": Key.enter, "tab": Key.tab, "esc": Key.esc,
    "escape": Key.esc, "backspace": Key.backspace, "delete": Key.delete,
    "up": Key.up, "down": Key.down, "left": Key.left, "right": Key.right,
    "home": Key.home, "end": Key.end, "page_up": Key.page_up, "page_down": Key.page_down,
    "insert": Key.insert, "caps_lock": Key.caps_lock,
    "ctrl": Key.ctrl, "shift": Key.shift, "alt": Key.alt, "cmd": Key.cmd,
    "media_volume_up": Key.media_volume_up, "media_volume_down": Key.media_volume_down,
    "media_volume_mute": Key.media_volume_mute, "media_play_pause": Key.media_play_pause,
    "media_previous": Key.media_previous, "media_next": Key.media_next,
}
MOD_KEYS = {"ctrl": Key.ctrl, "shift": Key.shift, "alt": Key.alt, "cmd": Key.cmd}
MOUSE_BUTTONS = {"left": Button.left, "right": Button.right, "middle": Button.middle}

kbd = Keyboard()
mouse = Mouse()
held: set = set()


def to_key(name: str):
    name = (name or "").strip().lower()
    if not name:
        return None
    if name in SPECIAL_KEYS:
        return SPECIAL_KEYS[name]
    m = re.fullmatch(r"f([1-9]|1[0-2])", name)
    if m:
        return getattr(Key, name)
    if len(name) > 1:
        name = name[:1]
    return KeyCode.from_char(name)


def do_key_down(key_name: str) -> None:
    k = to_key(key_name)
    if k is None:
        return
    if key_name.lower() not in held:
        held.add(key_name.lower())
        kbd.press(k)


def do_key_up(key_name: str) -> None:
    k = to_key(key_name)
    name = (key_name or "").lower()
    if k is None:
        return
    held.discard(name)
    kbd.release(k)


def do_release_all() -> None:
    for name in list(held):
        do_key_up(name)


def do_key_tap(key_name: str, mods: list) -> None:
    k = to_key(key_name)
    if k is None:
        return
    mod_keys = [MOD_KEYS[m] for m in (mods or []) if m in MOD_KEYS]
    if mod_keys:
        with kbd.pressed(*mod_keys):
            kbd.tap(k)
    else:
        kbd.tap(k)


def handle(msg: dict) -> None:
    t = msg.get("t")
    if t == "key_down":
        do_key_down(str(msg.get("key", "")))
    elif t == "key_up":
        do_key_up(str(msg.get("key", "")))
    elif t == "key_tap":
        do_key_tap(str(msg.get("key", "")), msg.get("mods") or [])
    elif t == "mouse_move":
        try:
            mouse.move(int(msg.get("dx", 0)), int(msg.get("dy", 0)))
        except (TypeError, ValueError):
            pass
    elif t == "mouse_click":
        btn = MOUSE_BUTTONS.get(str(msg.get("button", "left")), Button.left)
        mouse.click(btn)
    elif t == "scroll":
        try:
            dy = float(msg.get("dy", 0))
            mouse.scroll(0, max(-10, min(10, dy)))
        except (TypeError, ValueError):
            pass
    elif t == "media":
        key = {
            "volume_up": "media_volume_up", "volume_down": "media_volume_down",
            "mute": "media_volume_mute", "play_pause": "media_play_pause",
        }.get(str(msg.get("action", "")))
        if key:
            do_key_tap(key, [])
    elif t == "text":
        kbd.type(str(msg.get("text", "")))
    elif t == "release_all":
        do_release_all()


async def agent_loop() -> None:
    url = (f"{HUB}?token={quote(TOKEN)}&id={quote(AGENT_ID)}"
           f"&name={quote(NAME)}&platform={quote(platform.platform()[:60])}")
    backoff = 1
    print(f"[agent] device: {NAME} ({AGENT_ID})")
    while True:
        try:
            async with websockets.connect(url, ping_interval=10, ping_timeout=10) as ws:
                backoff = 1
                print(f"[agent] connected: {HUB}")
                await ws.send(json.dumps({
                    "t": "hello",
                    "id": AGENT_ID,
                    "name": NAME,
                    "platform": platform.platform(),
                    "version": VERSION,
                }))
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        continue
                    if isinstance(msg, dict) and msg.get("t") == "ping":
                        # 中枢靠心跳判断这台电脑是不是真在线（睡眠/断网时会假在线）
                        await ws.send(json.dumps({"t": "pong"}))
                        continue
                    try:
                        handle(msg)
                    except Exception as e:  # 单条指令失败不影响后续
                        print(f"[agent] handle error: {e}")
        except Exception as e:
            print(f"[agent] disconnected: {e}, retry in {backoff}s")
        do_release_all()
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 30)


if __name__ == "__main__":
    try:
        asyncio.run(agent_loop())
    except KeyboardInterrupt:
        do_release_all()
        print("[agent] bye")
