"""电视管理：多台电视的统一入口。

每台电视在 devices.json 里有一份配置（id / name / protocol / ip / port），
本模块按 id 创建对应协议后端，并负责三件事：

  1. 分发：按 protocol 走 ADB / 三星 Tizen / LG webOS
  2. 隔离：每台电视一把锁（adb 是串行的，两个遥控同时按不能交错）
  3. 缓存：在线状态缓存 30 秒，避免多台电视时每次刷新页面都去 adb 探活

凭证隔离：
  - adb_key 是「中枢这台机器」的身份，所有 ADB 电视共用（电视端各存一份授权）
  - 三星 token / LG 配对密钥按设备存放在 storage/tvkeys/<tv_id>/

所有方法均为阻塞调用；异步入口见 action_async / action_many / status_all。
"""
import asyncio
import time
from pathlib import Path

try:
    from .devices import Devices, DeviceError
    from .tv_adb import AdbTV
    from .tv_samsung import SamsungTV
    from .tv_lg import LgTV
except ImportError:  # 直接以脚本方式运行时
    from devices import Devices, DeviceError
    from tv_adb import AdbTV
    from tv_samsung import SamsungTV
    from tv_lg import LgTV

PROTOCOLS = {"adb": AdbTV, "samsung": SamsungTV, "lg": LgTV}

EMPTY_CFG = {"ip": "", "port": 5555, "protocol": "adb"}


class TVManager:
    STATUS_TTL = 30.0

    def __init__(self, storage_dir) -> None:
        self.dir = Path(storage_dir)
        self.devices = Devices(storage_dir)
        self._backends = {}
        self._locks = {}
        self._status = {}

    # ---------- 设备表 ----------
    def list(self) -> list:
        return self.devices.tvs()

    def resolve(self, tv_id=None):
        """没给 id 就用第一台（兼容老前端与老配置）。"""
        if tv_id:
            return self.devices.get_tv(str(tv_id))
        return self.devices.default_tv()

    def save_tv(self, payload: dict) -> dict:
        tv = self.devices.upsert_tv(payload)
        self.invalidate(tv["id"])
        return tv

    def delete_tv(self, tv_id: str) -> bool:
        ok = self.devices.delete_tv(tv_id)
        self.invalidate(tv_id)
        return ok

    def invalidate(self, tv_id: str) -> None:
        self._backends.pop(tv_id, None)
        self._status.pop(tv_id, None)

    # ---------- 后端 ----------
    def backend(self, tv: dict):
        tid = tv["id"]
        cached = self._backends.get(tid)
        key = (tv.get("protocol"), tv.get("ip"), int(tv.get("port") or 0))
        if cached and cached[0] == key:
            return cached[1]
        proto = tv.get("protocol", "adb")
        cls = PROTOCOLS.get(proto, AdbTV)
        if cls is AdbTV:
            # ADB 私钥是所有电视共用的一份，放全局目录
            inst = cls(tv.get("ip", ""), int(tv.get("port") or 5555), self.dir)
        else:
            # 三星 / LG 的配对凭证必须按设备隔离
            inst = cls(tv.get("ip", ""), int(tv.get("port") or 5555),
                       self.devices.tv_dir(tid))
        self._backends[tid] = (key, inst)
        return inst

    @staticmethod
    def serial(tv: dict):
        ip = tv.get("ip")
        return f"{ip}:{tv.get('port')}" if ip else None

    # ---------- 状态 ----------
    def status(self, tv_id=None, refresh: bool = False) -> dict:
        tv = self.resolve(tv_id)
        if tv is None:
            return {"id": None, "name": "", "cfg": dict(EMPTY_CFG), "serial": None,
                    "protocol": "adb", "online": False, "adb_installed": False}
        tid = tv["id"]
        now = time.monotonic()
        cached = self._status.get(tid)
        if cached and not refresh and now - cached[0] < self.STATUS_TTL:
            return cached[1]
        info = {"id": tid, "name": tv.get("name"), "cfg": dict(tv),
                "serial": self.serial(tv), "protocol": tv.get("protocol", "adb")}
        try:
            info.update(self.backend(tv).status())
        except Exception as e:
            info.update({"online": False, "error": str(e)})
        self._status[tid] = (now, info)
        return info

    def brief(self) -> list:
        """只读缓存，不触发 adb 探测——用于随时广播设备列表。"""
        out = []
        for t in self.list():
            cached = self._status.get(t["id"])
            out.append({
                "id": t["id"],
                "name": t.get("name") or t["id"],
                "protocol": t.get("protocol", "adb"),
                "ip": t.get("ip", ""),
                "port": t.get("port", 5555),
                "online": cached[1].get("online") if cached else None,
            })
        return out

    def status_all(self, refresh: bool = False) -> list:
        out = []
        for tv in self.list():
            st = self.status(tv["id"], refresh=refresh)
            out.append({
                "id": tv["id"],
                "name": tv.get("name") or tv["id"],
                "protocol": tv.get("protocol", "adb"),
                "ip": tv.get("ip", ""),
                "port": tv.get("port", 5555),
                "online": bool(st.get("online")),
                "serial": st.get("serial"),
                "adb_installed": st.get("adb_installed"),
                "error": st.get("error"),
            })
        return out

    def connect(self, tv_id=None) -> dict:
        tv = self.resolve(tv_id)
        if tv is None:
            return {"ok": False, "msg": "请先在「设备」里添加一台电视"}
        if not self.serial(tv):
            return {"ok": False, "msg": "请先填写电视 IP"}
        self._status.pop(tv["id"], None)
        try:
            res = self.backend(tv).connect()
        except Exception as e:
            # adb 超时等异常统一转成人话，不让接口 500
            res = {"ok": False,
                   "msg": f"连接失败：电视不在线、IP 不对或网络调试未开启（{e}）"}
        res.setdefault("id", tv["id"])
        self._status.pop(tv["id"], None)
        return res

    def disconnect(self, tv_id=None) -> dict:
        tv = self.resolve(tv_id)
        if tv is None:
            return {"ok": False, "msg": "没有电视可断开"}
        self._status.pop(tv["id"], None)
        try:
            return self.backend(tv).disconnect()
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    # ---------- 动作 ----------
    def action(self, act: dict, tv_id=None) -> dict:
        tv = self.resolve(tv_id)
        if tv is None:
            return {"ok": False, "msg": "未配置电视，请先在「设备」里添加"}
        if not tv.get("ip"):
            return {"ok": False, "id": tv["id"], "name": tv.get("name"),
                    "msg": "电视未配置 IP"}
        try:
            res = self.backend(tv).action(act)
        except Exception as e:
            res = {"ok": False, "msg": f"电视指令失败: {e}"}
        res.setdefault("id", tv["id"])
        res.setdefault("name", tv.get("name"))
        if not res.get("ok"):
            self._status.pop(tv["id"], None)  # 失败可能掉线，作废缓存
        return res

    def _lock(self, tv_id: str) -> asyncio.Lock:
        lock = self._locks.get(tv_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[tv_id] = lock
        return lock

    async def action_async(self, act: dict, tv_id=None) -> dict:
        """单台电视：同一台的指令串行执行，不同电视可以并行。"""
        tv = self.resolve(tv_id)
        key = tv["id"] if tv else (tv_id or "_")
        loop = asyncio.get_running_loop()
        async with self._lock(key):
            return await loop.run_in_executor(None, lambda: self.action(act, tv_id))

    async def action_many(self, act: dict, tv_ids=None) -> dict:
        """广播：并发打到多台，单台失败不影响其他台。"""
        ids = [t["id"] for t in self.list()] if tv_ids is None else list(tv_ids)
        if not ids:
            return {"ok": False, "msg": "还没有配置电视", "results": []}
        results = await asyncio.gather(
            *(self.action_async(act, tid) for tid in ids), return_exceptions=True)
        out = []
        for tid, res in zip(ids, results):
            if isinstance(res, Exception):
                out.append({"id": tid, "ok": False, "msg": str(res)})
            else:
                out.append(res)
        good = sum(1 for r in out if r.get("ok"))
        if len(out) == 1:
            return out[0]
        return {"ok": good == len(out), "results": out,
                "msg": f"{good}/{len(out)} 台电视执行成功"}

    async def status_all_async(self, refresh: bool = False) -> list:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self.status_all(refresh=refresh))

    async def connect_async(self, tv_id=None) -> dict:
        tv = self.resolve(tv_id)
        key = tv["id"] if tv else "_"
        loop = asyncio.get_running_loop()
        async with self._lock(key):
            return await loop.run_in_executor(None, lambda: self.connect(tv_id))

    async def disconnect_async(self, tv_id=None) -> dict:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self.disconnect(tv_id))
