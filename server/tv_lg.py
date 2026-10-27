"""LG webOS 电视后端（SSAP 协议，端口 3000）。

首次连接电视屏幕会弹出「允许」提示，允许后 clientKey 自动保存。
方向键/OK 通过 pointer socket 的 button 事件发送；音量/电源走 SSAP URI。
"""
import json
import socket
import time
from pathlib import Path

import websocket

BUTTONS = {
    "dpad_up": "UP", "dpad_down": "DOWN", "dpad_left": "LEFT", "dpad_right": "RIGHT",
    "ok": "CLICK", "enter": "ENTER", "back": "BACK", "home": "HOME", "menu": "MENU",
}

MANIFEST = {
    "forcePairing": False,
    "manifest": {
        "manifestVersion": 1,
        "permissions": ["LAUNCH", "LAUNCH_WEBAPP", "APP_TO_APP",
                        "CONTROL_AUDIO", "CONTROL_DISPLAY", "CONTROL_POWER",
                        "READ_INSTALLED_APPS"],
        "signatures": [{"signatureVersion": 1}],
    },
}


class LgTV:
    NAME = "lg"

    def __init__(self, ip: str, port: int, storage_dir) -> None:
        self.ip, self.port = ip, port
        self.dir = Path(storage_dir)
        self.key_path = self.dir / "lg_client_key"

    # ---------- SSAP 基础 ----------
    def _saved_key(self) -> str:
        return self.key_path.read_text(encoding="utf-8").strip() if self.key_path.exists() else ""

    def _register(self, ws, wait_pairing: bool, timeout: float = 20.0) -> str:
        payload = dict(MANIFEST)
        key = self._saved_key()
        if key:
            payload["client-key"] = key
        ws.send(json.dumps({"type": "register", "payload": payload}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = json.loads(ws.recv())
            if msg.get("type") == "registered":
                client_key = (msg.get("payload") or {}).get("client-key")
                if client_key and client_key != key:
                    self.key_path.write_text(client_key, encoding="utf-8")
                return client_key or key
            # registered:pending → 电视弹窗等用户确认，继续等
        raise TimeoutError("配对超时：请在电视上点击「允许」")

    def _connect(self, wait_pairing: bool = True):
        ws = websocket.create_connection(f"ws://{self.ip}:{self.port}", timeout=5)
        try:
            self._register(ws, wait_pairing)
        except Exception:
            ws.close()
            raise
        return ws

    def _request(self, ws, uri: str, payload: dict = None) -> dict:
        ws.send(json.dumps({"type": "request", "uri": uri, "payload": payload or {}}))
        deadline = time.time() + 5
        while time.time() < deadline:
            msg = json.loads(ws.recv())
            if msg.get("type") == "response":
                return msg
        raise TimeoutError("电视响应超时")

    def _button(self, ws, name: str) -> None:
        # 先打开 pointer socket，再发 button 事件
        self._request(ws, "ssap://webos/pointer/socket")
        ws.send(json.dumps({"type": "button", "name": name}))

    # ---------- 对外操作 ----------
    def status(self) -> dict:
        online = False
        if self.ip:
            try:
                with socket.create_connection((self.ip, self.port), timeout=1.5):
                    online = True
            except OSError:
                online = False
        return {"online": online,
                "serial": f"{self.ip}:{self.port}" if self.ip else None,
                "paired": bool(self._saved_key())}

    def connect(self) -> dict:
        try:
            ws = self._connect(wait_pairing=True)
            ws.close()
            return {"ok": True, "msg": "已连接（配对密钥已保存，下次免确认）"}
        except Exception as e:
            return {"ok": False, "msg": f"{e}"}

    def disconnect(self) -> dict:
        return {"ok": True}

    def action(self, act: dict) -> dict:
        kind = str(act.get("kind", ""))
        if kind != "key":
            if kind == "app":
                ws = self._connect(wait_pairing=False)
                try:
                    resp = self._request(ws, "ssap://system.launcher/launch",
                                         {"id": str(act.get("package", "")).strip()})
                    err = (resp.get("payload") or {}).get("error")
                    if err:
                        return {"ok": False, "msg": f"启动失败: {err}"}
                    return {"ok": True}
                finally:
                    ws.close()
            return {"ok": False, "msg": f"未知动作类型: {kind}"}

        key = str(act.get("key", ""))
        ws = self._connect(wait_pairing=False)
        try:
            if key in BUTTONS:
                self._button(ws, BUTTONS[key])
            elif key == "volume_up":
                self._request(ws, "ssap://audio/volumeUp")
            elif key == "volume_down":
                self._request(ws, "ssap://audio/volumeDown")
            elif key == "mute":
                st = self._request(ws, "ssap://audio/getStatus")
                muted = bool((st.get("payload") or {}).get("mute"))
                self._request(ws, "ssap://audio/setMute", {"mute": not muted})
            elif key == "power":
                self._request(ws, "ssap://system/turnOff")
            else:
                return {"ok": False, "msg": f"LG 协议不支持按键: {key}"}
            return {"ok": True}
        finally:
            ws.close()
