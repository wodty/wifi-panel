"""ADB 协议后端：Android TV 系（小米 / TCL·雷鸟 / 海信 / 创维 / 索尼 / 长虹 / 康佳）。"""
import os
import shutil
import subprocess
from pathlib import Path

# Android KEYCODE
KEYCODES = {
    "dpad_up": 19, "dpad_down": 20, "dpad_left": 21, "dpad_right": 22,
    "ok": 23, "enter": 66, "back": 4, "home": 3, "menu": 82,
    "volume_up": 24, "volume_down": 25, "mute": 164,
    "power": 26, "wake": 224, "sleep": 223, "play_pause": 85,
    "media_previous": 88, "media_next": 87,
}


class TVError(Exception):
    pass


class AdbTV:
    NAME = "adb"

    def __init__(self, ip: str, port: int, storage_dir) -> None:
        self.ip, self.port = ip, port
        self.dir = Path(storage_dir)
        self.key_path = self.dir / "adb_key"
        self._gen_keys_if_needed()

    # ---------- adb 基础 ----------
    def _gen_keys_if_needed(self) -> None:
        if self.key_path.exists():
            return
        adb = shutil.which("adb")
        if adb:
            try:
                subprocess.run([adb, "keygen", str(self.key_path)],
                               check=True, capture_output=True, timeout=10)
            except Exception:
                pass

    def _env(self) -> dict:
        env = dict(os.environ)
        if self.key_path.exists():
            env["ADB_VENDOR_KEYS"] = str(self.key_path)
        return env

    def _run(self, *args, timeout: int = 8):
        """返回 (returncode, stdout, stderr)。超时强杀整个进程树，避免管道被 adb 子进程占住。"""
        adb = shutil.which("adb")
        if not adb:
            raise TVError("adb_missing")
        try:
            proc = subprocess.Popen([adb, *args], stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, env=self._env())
        except Exception:
            raise TVError("adb_missing")
        try:
            out, err = proc.communicate(timeout=timeout)
            return proc.returncode, (out or "").strip(), (err or "").strip()
        except subprocess.TimeoutExpired:
            self._kill_tree(proc)
            raise TVError("adb_timeout")

    @staticmethod
    def _kill_tree(proc) -> None:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               capture_output=True, timeout=5)
            else:
                proc.kill()
        except Exception:
            pass

    # ---------- 对外操作 ----------
    def status(self) -> dict:
        adb_installed = shutil.which("adb") is not None
        online = False
        serial = f"{self.ip}:{self.port}" if self.ip else None
        if serial and adb_installed:
            try:
                code, out, _ = self._run("-s", serial, "get-state", timeout=5)
                online = code == 0 and out == "device"
            except TVError:
                online = False
        return {"adb_installed": adb_installed, "online": online, "serial": serial}

    def connect(self) -> dict:
        serial = f"{self.ip}:{self.port}"
        try:
            code, out, err = self._run("connect", serial, timeout=12)
        except TVError:
            return {"ok": False,
                    "msg": "连接超时：电视不在线、IP 不对，或「网络调试」未开启"}
        text = (out or err)
        ok = code == 0 and "connected to" in text.lower() and "failed" not in text.lower()
        return {"ok": ok, "msg": text}

    def disconnect(self) -> dict:
        serial = f"{self.ip}:{self.port}"
        try:
            self._run("disconnect", serial, timeout=5)
        except TVError:
            pass
        return {"ok": True}

    def action(self, act: dict) -> dict:
        kind = str(act.get("kind", ""))
        serial = f"{self.ip}:{self.port}"
        if kind == "key":
            code_key = KEYCODES.get(str(act.get("key", "")))
            if code_key is None:
                return {"ok": False, "msg": f"未知按键: {act.get('key')}"}
            code, out, err = self._run("-s", serial, "shell", "input", "keyevent", str(code_key))
        elif kind == "app":
            pkg = str(act.get("package", "")).strip()
            import re
            if not re.match(r"^[A-Za-z][A-Za-z0-9_.]{2,100}$", pkg):
                return {"ok": False, "msg": f"包名不合法: {pkg}"}
            code, out, err = self._run("-s", serial, "shell", "monkey", "-p", pkg, "1")
        else:
            return {"ok": False, "msg": f"未知动作类型: {kind}"}
        if code != 0:
            text = (err or out) or f"adb 退出码 {code}（电视可能离线，请重新连接）"
            return {"ok": False, "msg": text}
        if "error" in (out + err).lower() or "offline" in (out + err).lower():
            return {"ok": False, "msg": (err or out) or "电视离线，请重新连接"}
        return {"ok": True}
