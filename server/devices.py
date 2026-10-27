"""设备表：PC 与电视的注册信息（唯一真相）。

storage/devices.json
  {"version": 2,
   "pcs": [{"id": "pc-ab12cd", "name": "客厅主机"}],
   "tvs": [{"id": "tv1", "name": "客厅电视", "protocol": "adb",
            "ip": "192.168.1.50", "port": 5555}]}

老版本只有一份 storage/tv.json（单台电视），首次启动自动迁移成 tv1，
配套的三星令牌 / LG 配对密钥搬到 storage/tvkeys/<tv_id>/ 下——
两台三星、两台 LG 各自配对，不会互相覆盖。
"""
import json
import os
import re
import shutil
from pathlib import Path

ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
IP_RE = re.compile(r"^[A-Za-z0-9._-]{3,60}$")

# 协议 → 默认端口
PROTOCOLS = {"adb": 5555, "samsung": 8001, "lg": 3000}

# 需要按设备隔离的凭证文件（adb_key 是「中枢这台机器」的身份，多台电视共用是对的）
TAG_FILES = ("samsung_token", "lg_client_key")

DEFAULT_TV_NAME = "电视"


class DeviceError(ValueError):
    """设备配置非法（转成 400 返回前端）。"""


def clean_name(raw, fallback: str = "") -> str:
    name = str(raw if raw is not None else "").strip()
    if len(name) > 24:
        name = name[:24]
    return name or fallback


class Devices:
    def __init__(self, storage_dir) -> None:
        self.dir = Path(storage_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "devices.json"
        self.keys_dir = self.dir / "tvkeys"
        self.data = self._load()

    # ---------- 读写 ----------
    def _empty(self) -> dict:
        return {"version": 2, "pcs": [], "tvs": []}

    def _load(self) -> dict:
        data = None
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                data = None
        if not isinstance(data, dict):
            data = self._empty()
            data["tvs"] = self._migrate_legacy()
            self.save(data)
        data.setdefault("version", 2)
        if not isinstance(data.get("pcs"), list):
            data["pcs"] = []
        if not isinstance(data.get("tvs"), list):
            data["tvs"] = []
        return data

    def save(self, data=None) -> None:
        if data is not None:
            self.data = data
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def _migrate_legacy(self) -> list:
        """把单台电视的 tv.json 迁成设备表里的 tv1。"""
        legacy = self.dir / "tv.json"
        if not legacy.exists():
            return []
        try:
            cfg = json.loads(legacy.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
        if not isinstance(cfg, dict):
            cfg = {}
        proto = str(cfg.get("protocol") or "adb")
        if proto not in PROTOCOLS:
            proto = "adb"
        try:
            port = int(cfg.get("port") or PROTOCOLS[proto])
        except (TypeError, ValueError):
            port = PROTOCOLS[proto]
        tv = {
            "id": "tv1",
            "name": DEFAULT_TV_NAME,
            "protocol": proto,
            "ip": str(cfg.get("ip") or "").strip(),
            "port": port,
        }
        if tv["ip"]:
            target = self.tv_dir(tv["id"])
            target.mkdir(parents=True, exist_ok=True)
            for fname in TAG_FILES:
                src = self.dir / fname
                if src.exists():
                    try:
                        shutil.move(str(src), str(target / fname))
                    except Exception:
                        pass
        # 留个后缀名，避免下次启动重复迁移（内容保留，便于回滚）
        try:
            legacy.rename(legacy.with_name("tv.json.migrated"))
        except Exception:
            pass
        return [tv]

    # ---------- 电视 ----------
    def tvs(self) -> list:
        return self.data["tvs"]

    def get_tv(self, tv_id: str):
        for tv in self.data["tvs"]:
            if tv.get("id") == tv_id:
                return tv
        return None

    def default_tv(self):
        """没指定目标时用第一台电视（兼容老前端与老配置）。"""
        return self.data["tvs"][0] if self.data["tvs"] else None

    def new_tv_id(self) -> str:
        used = {t.get("id") for t in self.data["tvs"]}
        n = 1
        while f"tv{n}" in used:
            n += 1
        return f"tv{n}"

    def tv_dir(self, tv_id: str) -> Path:
        if not ID_RE.match(str(tv_id)):
            raise DeviceError("bad device id")
        return self.keys_dir / str(tv_id)

    def upsert_tv(self, payload: dict) -> dict:
        """新建或更新一台电视。id 缺省时自动分配 tv1 / tv2 …"""
        if not isinstance(payload, dict):
            raise DeviceError("invalid payload")
        tv_id = str(payload.get("id") or "").strip()
        if tv_id and not ID_RE.match(tv_id):
            raise DeviceError("bad device id")

        cur = self.get_tv(tv_id) if tv_id else None
        proto = str(payload.get("protocol") or (cur or {}).get("protocol") or "adb").strip()
        if proto not in PROTOCOLS:
            raise DeviceError(f"unknown protocol: {proto}")
        ip = str(payload.get("ip", (cur or {}).get("ip", "")) or "").strip()
        if ip and not IP_RE.match(ip):
            raise DeviceError("invalid ip/hostname")
        raw_port = payload.get("port", (cur or {}).get("port", PROTOCOLS[proto]))
        try:
            port = int(raw_port or PROTOCOLS[proto])
        except (TypeError, ValueError):
            raise DeviceError("invalid port")
        if not (1 <= port <= 65535):
            raise DeviceError("invalid port")

        name = clean_name(payload.get("name"), (cur or {}).get("name") or "")
        if not tv_id:
            tv_id = self.new_tv_id()
        if not name:
            name = DEFAULT_TV_NAME if not self.data["tvs"] else f"电视 {len(self.data['tvs']) + 1}"

        tv = {"id": tv_id, "name": name, "protocol": proto, "ip": ip, "port": port}
        if cur is None:
            self.data["tvs"].append(tv)
        else:
            cur.update(tv)
        self.save()
        return tv

    def delete_tv(self, tv_id: str) -> bool:
        tv_id = str(tv_id or "")
        before = len(self.data["tvs"])
        self.data["tvs"] = [t for t in self.data["tvs"] if t.get("id") != tv_id]
        if len(self.data["tvs"]) == before:
            return False
        self.save()
        target = self.keys_dir / tv_id
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        return True

    def rename_tv(self, tv_id: str, name: str) -> dict:
        tv = self.get_tv(tv_id)
        if tv is None:
            raise DeviceError("tv not found")
        tv["name"] = clean_name(name, tv.get("name") or DEFAULT_TV_NAME)
        self.save()
        return tv

    # ---------- PC ----------
    def pcs(self) -> list:
        return self.data["pcs"]

    def get_pc(self, pc_id: str):
        for pc in self.data["pcs"]:
            if pc.get("id") == pc_id:
                return pc
        return None

    def upsert_pc(self, pc_id: str, name: str = "", platform: str = "") -> dict:
        """Agent 上线时登记/更新。用户改过的名字优先保留。"""
        pc_id = str(pc_id or "").strip()
        if not ID_RE.match(pc_id):
            raise DeviceError("bad device id")
        cur = self.get_pc(pc_id)
        if cur is None:
            cur = {"id": pc_id, "name": clean_name(name, platform or pc_id)}
            self.data["pcs"].append(cur)
        else:
            if not cur.get("name") and name:
                cur["name"] = clean_name(name, pc_id)
        if platform:
            cur["platform"] = platform
        self.save()
        return cur

    def rename_pc(self, pc_id: str, name: str) -> dict:
        pc = self.get_pc(pc_id)
        if pc is None:
            raise DeviceError("pc not found")
        pc["name"] = clean_name(name, pc.get("name") or pc_id)
        self.save()
        return pc

    def delete_pc(self, pc_id: str) -> bool:
        before = len(self.data["pcs"])
        self.data["pcs"] = [p for p in self.data["pcs"] if p.get("id") != pc_id]
        if len(self.data["pcs"]) == before:
            return False
        self.save()
        return True
