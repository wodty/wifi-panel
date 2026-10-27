"""电视控制门面：按 protocol 字段分发到不同协议后端。

  adb      → Android TV 系（小米 / TCL·雷鸟 / 海信 / 创维 / 索尼 / 长虹 / 康佳）
  samsung  → 三星 Tizen（WebSocket 8001）
  lg       → LG webOS（SSAP 3000）

配置存 storage/tv.json：{ip, port, protocol}
密钥/令牌存 storage/ 下（adb_key、samsung_token、lg_client_key）。
所有方法均为阻塞调用，调用方（main.py）需放入线程执行器。
"""
import json
import re
from pathlib import Path

try:
    from .tv_adb import AdbTV
    from .tv_samsung import SamsungTV
    from .tv_lg import LgTV
except ImportError:  # 直接以脚本方式运行时
    from tv_adb import AdbTV
    from tv_samsung import SamsungTV
    from tv_lg import LgTV

IP_RE = re.compile(r"^[A-Za-z0-9._-]{3,60}$")

PROTOCOLS = {"adb": AdbTV, "samsung": SamsungTV, "lg": LgTV}


class TVController:
    def __init__(self, storage_dir) -> None:
        self.dir = Path(storage_dir)
        self.cfg_path = self.dir / "tv.json"

    # ---------- 配置 ----------
    def cfg(self) -> dict:
        if self.cfg_path.exists():
            try:
                return json.loads(self.cfg_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"ip": "", "port": 5555, "protocol": "adb"}

    def save_cfg(self, cfg: dict) -> None:
        ip = str(cfg.get("ip", "")).strip()
        port = int(cfg.get("port", 5555))
        protocol = str(cfg.get("protocol", "adb")).strip()
        if ip and not IP_RE.match(ip):
            raise ValueError("invalid ip/hostname")
        if not (1 <= port <= 65535):
            raise ValueError("invalid port")
        if protocol not in PROTOCOLS:
            raise ValueError(f"unknown protocol: {protocol}")
        self.cfg_path.write_text(
            json.dumps({"ip": ip, "port": port, "protocol": protocol},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")

    def serial(self):
        c = self.cfg()
        return f"{c['ip']}:{c['port']}" if c.get("ip") else None

    # ---------- 分发 ----------
    def _backend(self):
        c = self.cfg()
        proto = c.get("protocol", "adb")
        cls = PROTOCOLS.get(proto, AdbTV)
        return cls(c.get("ip", ""), int(c.get("port", 5555)), self.dir)

    def status(self) -> dict:
        c = self.cfg()
        backend = self._backend()
        info = {"cfg": c, "serial": self.serial(), "protocol": c.get("protocol", "adb")}
        try:
            info.update(backend.status())
        except Exception as e:
            info.update({"online": False, "error": str(e)})
        return info

    def connect(self) -> dict:
        if not self.serial():
            return {"ok": False, "msg": "请先填写电视 IP"}
        try:
            return self._backend().connect()
        except Exception as e:
            # adb 超时等异常统一转成人话，不让接口 500
            return {"ok": False, "msg": f"连接失败：电视不在线、IP 不对或网络调试未开启（{e}）"}

    def disconnect(self) -> dict:
        return self._backend().disconnect()

    def action(self, act: dict) -> dict:
        if not self.serial():
            return {"ok": False, "msg": "电视未配置"}
        try:
            return self._backend().action(act)
        except Exception as e:
            return {"ok": False, "msg": f"电视指令失败: {e}"}
