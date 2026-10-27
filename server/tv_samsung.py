"""三星 Tizen 电视后端（WebSocket 遥控协议，端口 8001）。

首次连接电视会弹出「允许」提示，允许后返回的 token 自动保存，
之后免确认。协议参考 samsung-tv-ws-api / samsungctl。
"""
import base64
import json
import socket
import urllib.request
from pathlib import Path

import websocket

KEYS = {
    "dpad_up": "KEY_UP", "dpad_down": "KEY_DOWN", "dpad_left": "KEY_LEFT",
    "dpad_right": "KEY_RIGHT", "ok": "KEY_ENTER", "enter": "KEY_ENTER",
    "back": "KEY_RETURN", "home": "KEY_HOME", "menu": "KEY_MENU",
    "volume_up": "KEY_VOLUMEUP", "volume_down": "KEY_VOLUMEDOWN", "mute": "KEY_MUTE",
    "power": "KEY_POWER", "play_pause": "KEY_PLAY_PAUSE",
    "media_previous": "KEY_PREVIOUS", "media_next": "KEY_NEXT",
    "channel_up": "KEY_CHUP", "channel_down": "KEY_CHDOWN", "exit": "KEY_EXIT",
}


class SamsungTV:
    NAME = "samsung"

    def __init__(self, ip: str, port: int, storage_dir) -> None:
        self.ip, self.port = ip, port
        self.dir = Path(storage_dir)
        self.token_path = self.dir / "samsung_token"

    def _url(self) -> str:
        name = base64.b64encode("wifi-panel".encode()).decode()
        url = f"ws://{self.ip}:{self.port}/api/v2/channels/samsung.remote.control?name={name}"
        token = self.token_path.read_text(encoding="utf-8").strip() if self.token_path.exists() else ""
        if token:
            url += f"&token={token}"
        return url

    def _ws_connect(self, timeout: float = 5.0):
        ws = websocket.create_connection(self._url(), timeout=timeout)
        hello = json.loads(ws.recv())
        token = (hello.get("data") or {}).get("token")
        if token:
            saved = self.token_path.read_text(encoding="utf-8").strip() if self.token_path.exists() else ""
            if token != saved:
                self.token_path.write_text(token, encoding="utf-8")
        return ws

    def _click(self, key: str) -> None:
        ws = self._ws_connect()
        try:
            ws.send(json.dumps({
                "method": "ms.remote.control",
                "params": {"Cmd": "Click", "DataOfCmd": key,
                           "Option": {"typeofRemoteButton": "press"},
                           "TypeOfRemote": "SendRemoteKey"},
            }))
        finally:
            ws.close()

    # ---------- 对外操作 ----------
    def status(self) -> dict:
        online = False
        model = ""
        if self.ip:
            try:
                with urllib.request.urlopen(
                        f"http://{self.ip}:{self.port}/api/v2/", timeout=2) as r:
                    data = json.loads(r.read())
                    model = (data.get("device") or {}).get("modelName", "")
                    online = True
            except Exception:
                online = False
        return {"online": online, "serial": f"{self.ip}:{self.port}" if self.ip else None,
                "model": model}

    def connect(self) -> dict:
        try:
            ws = self._ws_connect(timeout=8)
            ws.close()
            return {"ok": True, "msg": "已连接（配对令牌已保存，下次免确认）"}
        except Exception as e:
            hint = "若电视弹出授权提示，请先在电视上点「允许」"
            return {"ok": False, "msg": f"{e}（{hint}）"}

    def disconnect(self) -> dict:
        return {"ok": True}

    def action(self, act: dict) -> dict:
        kind = str(act.get("kind", ""))
        if kind == "key":
            key = KEYS.get(str(act.get("key", "")))
            if key is None:
                return {"ok": False, "msg": f"三星协议不支持按键: {act.get('key')}"}
            self._click(key)
            return {"ok": True}
        if kind == "app":
            app_id = str(act.get("package", "")).strip()
            import re
            if not re.match(r"^[A-Za-z0-9.]{3,100}$", app_id):
                return {"ok": False, "msg": f"应用 ID 不合法: {app_id}"}
            req = urllib.request.Request(
                f"http://{self.ip}:{self.port}/api/v2/applications/{app_id}", method="POST")
            with urllib.request.urlopen(req, timeout=5):
                pass
            return {"ok": True}
        return {"ok": False, "msg": f"未知动作类型: {kind}"}
