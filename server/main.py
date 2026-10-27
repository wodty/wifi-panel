"""wifi-panel 中枢服务。

职责：
  1. 托管 Web 面板静态页面（web/ 目录）
  2. 面板 profile 与设备表（PC / 电视）的存储
  3. WebSocket 中继：手机端(/ws/remote) -> 指定 PC Agent(/ws/agent) 或电视
  4. 安全兜底：远端断开时释放它按住的键，最后一台远端断开再无条件 release_all

多设备：
  每条指令可以带个 target（设备 id 或 "*"），中枢查设备表后投递。
  不带 target 时走面板默认 / 第一台在线设备，旧前端、旧面板照常工作。

运行：
  python -m uvicorn server.main:app --host 0.0.0.0 --port 8765
环境变量：
  PANEL_TOKEN  访问令牌（默认 panel123，部署时务必修改）
  PANEL_PORT   监听端口（默认 8765）
"""
import asyncio
import json
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, Set

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).resolve().parent.parent
WEB_DIR = BASE / "web"
STORAGE = BASE / "server" / "storage"
LAYOUTS = STORAGE / "layouts"
LAYOUTS.mkdir(parents=True, exist_ok=True)

TOKEN = os.environ.get("PANEL_TOKEN", "panel123")
PORT = int(os.environ.get("PANEL_PORT", "8765"))

PID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")

# 心跳：电脑睡眠/断网时 TCP 可能长时间不报错，靠心跳把「假在线」清掉
HEARTBEAT_INTERVAL = 15
HEARTBEAT_TIMEOUT = 45
AGENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")

# 允许从远端发来的消息类型（adb 由中枢本地执行，不转发给 Agent）
ALLOWED_TYPES = {
    "key_down", "key_up", "key_tap",
    "mouse_move", "mouse_click", "scroll",
    "media", "text", "adb", "ping",
}

try:
    from .tv import TVManager
    from .devices import DeviceError
    from . import templates
except ImportError:  # 直接以脚本方式运行时
    from tv import TVManager
    from devices import DeviceError
    import templates


def seed_default_profile() -> None:
    """播种/升级默认面板。

    - 存储里一个面板都没有：写入内置默认面板，新用户打开就能用。
    - 已有 default.json 但用户没改过、且模板版本较旧：按新模板重建。
      （用户手动改过的面板不动，避免覆盖自定义内容）
    """
    path = LAYOUTS / "default.json"
    exists = path.exists()
    if not exists and any(LAYOUTS.glob("*.json")):
        return  # 用户自己删掉了默认面板，不再塞回去
    if exists:
        try:
            cur = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            cur = {}
        old = int(cur.get("template_rev") or 0)
        if cur.get("edited") or old >= templates.REV:
            return
    data = templates.build(templates.DEFAULT_KIND, "default")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def heartbeat_loop() -> None:
    """定期 ping 各台 Agent；太久没回应的直接踢掉，避免「假在线」骗人。"""
    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)
        now = time.monotonic()
        changed = False
        for aid, conn in list(hub.agents.items()):
            if now - conn.last_seen > HEARTBEAT_TIMEOUT:
                if hub.agents.get(aid) is conn:
                    hub.agents.pop(aid, None)
                conn.holders.clear()
                try:
                    await conn.ws.close(code=4408)
                except Exception:
                    pass
                changed = True
                continue
            try:
                await conn.ws.send_text(json.dumps({"t": "ping"}))
            except Exception:
                pass
        if changed:
            await hub.broadcast({"t": "agent_status", "online": hub.any_online()})
            await broadcast_devices()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    seed_default_profile()
    task = asyncio.create_task(heartbeat_loop())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="wifi-panel", lifespan=lifespan)

# 页面可以不在中枢上（例如本地打开一份网页、或从旧书签指到新 NAS）：
# 放开跨域，鉴权仍靠 X-Token，浏览器读不到别人的令牌。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AgentConn:
    """一台 PC 的 Agent 连接。"""

    def __init__(self, ws: WebSocket, aid: str, name: str = "",
                 platform: str = "", version: str = "") -> None:
        self.ws = ws
        self.id = aid
        self.name = name or aid
        self.platform = platform
        self.version = version
        # key -> 正按住它的远端集合。多个遥控按同一个键时，最后一个松手才真松开。
        self.holders: dict = {}
        self.last_seen = time.monotonic()


class Hub:
    """维护多台 Agent、远端连接与按键状态。"""

    def __init__(self) -> None:
        self.agents: dict = {}          # id -> AgentConn
        self.remotes: Set[WebSocket] = set()
        self.remote_holds: dict = {}    # ws -> {agent_id: {key}}
        self.lock = asyncio.Lock()

    # ---------- 查询 ----------
    def any_online(self) -> bool:
        return bool(self.agents)

    def online_ids(self) -> list:
        return sorted(self.agents)

    def conn_for(self, aid: str = "") -> Optional[AgentConn]:
        """按 id 找连接；id 为空时取第一台在线（按 id 排序，结果稳定）。"""
        if aid:
            return self.agents.get(aid)
        for key in sorted(self.agents):
            return self.agents[key]
        return None

    def pc_list(self) -> list:
        """设备表里的 PC（含离线）+ 当前在线的 Agent。"""
        saved = {p.get("id"): p for p in devices.pcs()}
        out = []
        for aid in sorted(self.agents):
            conn = self.agents[aid]
            rec = saved.get(aid) or {}
            out.append({
                "id": aid,
                "name": rec.get("name") or conn.name or aid,
                "online": True,
                "platform": conn.platform or rec.get("platform", ""),
            })
        for pid, rec in saved.items():
            if pid in self.agents:
                continue
            out.append({
                "id": pid,
                "name": rec.get("name") or pid,
                "online": False,
                "platform": rec.get("platform", ""),
            })
        out.sort(key=lambda p: (not p["online"], p["id"]))
        return out

    # ---------- 发送 ----------
    async def send(self, conn: AgentConn, msg: dict) -> str:
        """发一条消息，成功返回 ""，失败返回错误码。"""
        try:
            await conn.ws.send_text(json.dumps(msg))
            return ""
        except Exception:
            if self.agents.get(conn.id) is conn:
                self.agents.pop(conn.id, None)
            return "target_offline"

    async def broadcast(self, msg: dict) -> None:
        text = json.dumps(msg)
        for ws in list(self.remotes):
            try:
                await ws.send_text(text)
            except Exception:
                self.remotes.discard(ws)

    # ---------- 按住状态 ----------
    async def hold_down(self, ws: WebSocket, conn: AgentConn, key: str) -> str:
        holders = conn.holders.setdefault(key, set())
        first = not holders
        holders.add(ws)
        self.remote_holds.setdefault(ws, {}).setdefault(conn.id, set()).add(key)
        if first:
            return await self.send(conn, {"t": "key_down", "key": key})
        return ""

    async def hold_up(self, ws: WebSocket, conn: AgentConn, key: str) -> str:
        holders = conn.holders.get(key)
        if holders is not None:
            holders.discard(ws)
        keys = (self.remote_holds.get(ws) or {}).get(conn.id)
        if keys is not None:
            keys.discard(key)
        if not holders:
            conn.holders.pop(key, None)
            return await self.send(conn, {"t": "key_up", "key": key})
        return ""  # 还有别的遥控按着这个键，别松

    async def release_remote(self, ws: WebSocket) -> None:
        """一台遥控断线：只释放它按过的键，其他遥控不受影响。"""
        held = self.remote_holds.pop(ws, {})
        for aid, keys in held.items():
            conn = self.agents.get(aid)
            if conn is None:
                continue
            for key in list(keys):
                holders = conn.holders.get(key)
                if holders is not None:
                    holders.discard(ws)
                if not holders:
                    conn.holders.pop(key, None)
                    await self.send(conn, {"t": "key_up", "key": key})

    async def release_all_if_needed(self) -> None:
        """最后一台远端断开时，无条件下发 release_all。

        即使逐键 key_up 已经清空，也作为兜底防线：
        防止任何未知原因导致的按键卡死（Agent 端释放是幂等的）。
        """
        async with self.lock:
            if self.remotes:
                return
            self.remote_holds.clear()
            for conn in list(self.agents.values()):
                conn.holders.clear()
                await self.send(conn, {"t": "release_all"})


hub = Hub()
tv = TVManager(STORAGE)
devices = tv.devices


async def broadcast_devices() -> None:
    """设备列表变化时推给所有遥控（只用缓存状态，不触发 adb 探测）。"""
    await hub.broadcast({"t": "devices", "pcs": hub.pc_list(), "tvs": tv.brief()})


async def _json(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="invalid json")
    return body


def check_token(request: Request) -> None:
    token = request.headers.get("x-token") or request.query_params.get("token", "")
    if token != TOKEN:
        raise HTTPException(status_code=401, detail="invalid token")


def _layout_path(pid: str) -> Path:
    if not PID_RE.match(pid):
        raise HTTPException(status_code=400, detail="bad profile id")
    return LAYOUTS / f"{pid}.json"


@app.get("/api/ping")
def ping(request: Request):
    check_token(request)
    default_tv = tv.devices.default_tv()
    return {
        "ok": True,
        "agent_online": hub.any_online(),
        "agents": len(hub.agents),
        "tvs": len(tv.list()),
        "default_tv": default_tv["id"] if default_tv else None,
    }


@app.get("/healthz")
def healthz():
    """容器健康检查用，不含任何鉴权信息。"""
    return {"ok": True}


# ---------- 面板 ----------
@app.get("/api/profiles")
def list_profiles(request: Request):
    check_token(request)
    items = []
    for p in sorted(LAYOUTS.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            items.append({
                "id": data.get("id", p.stem),
                "name": data.get("name", p.stem),
                "template": data.get("template"),
                "targets": data.get("targets") or {},
            })
        except Exception:
            continue
    return {"profiles": items}


@app.get("/api/profiles/{pid}")
def get_profile(pid: str, request: Request):
    check_token(request)
    path = _layout_path(pid)
    if not path.exists():
        raise HTTPException(status_code=404, detail="profile not found")
    return JSONResponse(content=json.loads(path.read_text(encoding="utf-8")))


@app.put("/api/profiles/{pid}")
async def put_profile(pid: str, request: Request):
    check_token(request)
    path = _layout_path(pid)
    data = await _json(request)
    if not isinstance(data.get("elements"), list):
        raise HTTPException(status_code=400, detail="profile must contain elements[]")
    data["id"] = pid
    if not data.get("name"):
        data["name"] = pid
    if not isinstance(data.get("targets"), dict):
        data.pop("targets", None)
    data["edited"] = True  # 标记为用户改过，内置模板升级时不再覆盖
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True}


@app.delete("/api/profiles/{pid}")
def delete_profile(pid: str, request: Request):
    check_token(request)
    path = _layout_path(pid)
    if path.exists():
        path.unlink()
    return {"ok": True}


# ---------- 内置模板 ----------
@app.get("/api/templates")
def list_templates(request: Request):
    check_token(request)
    return {"default": templates.DEFAULT_KIND, "templates": templates.catalog()}


@app.post("/api/templates/{kind}")
async def create_from_template(kind: str, request: Request):
    """按模板新建一份面板，返回新 id（前端建完直接打开）。"""
    check_token(request)
    if kind not in {t["kind"] for t in templates.TEMPLATES}:
        raise HTTPException(status_code=404, detail="unknown template")
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    pid = str(body.get("id") or f"p{os.urandom(4).hex()}")
    if not PID_RE.match(pid):
        raise HTTPException(status_code=400, detail="bad profile id")
    name = body.get("name")
    data = templates.build(kind, pid, name if isinstance(name, str) else None)
    targets = body.get("targets")
    if isinstance(targets, dict):
        data["targets"] = {k: str(v) for k, v in targets.items() if k in ("pc", "tv") and v}
    _layout_path(pid).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"ok": True, "id": pid}


# ---------- 设备：总览 ----------
@app.get("/api/devices")
async def api_devices(request: Request, refresh: int = 0):
    check_token(request)
    tvs = await tv.status_all_async(refresh=bool(refresh))
    return {"pcs": hub.pc_list(), "tvs": tvs}


# ---------- 设备：电视 ----------
@app.post("/api/devices/tv")
async def api_tv_create(request: Request):
    check_token(request)
    body = await _json(request)
    try:
        cfg = tv.save_tv(body)
    except DeviceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await broadcast_devices()
    return {"ok": True, "tv": cfg}


@app.put("/api/devices/tv/{tid}")
async def api_tv_update(tid: str, request: Request):
    check_token(request)
    body = await _json(request)
    body["id"] = tid
    try:
        cfg = tv.save_tv(body)
    except DeviceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await broadcast_devices()
    return {"ok": True, "tv": cfg}


@app.delete("/api/devices/tv/{tid}")
async def api_tv_delete(tid: str, request: Request):
    check_token(request)
    ok = tv.delete_tv(tid)
    await broadcast_devices()
    return {"ok": ok}


@app.post("/api/devices/tv/{tid}/connect")
async def api_tv_connect_id(tid: str, request: Request):
    check_token(request)
    res = await tv.connect_async(tid)
    await broadcast_devices()
    return res


@app.post("/api/devices/tv/{tid}/disconnect")
async def api_tv_disconnect_id(tid: str, request: Request):
    check_token(request)
    res = await tv.disconnect_async(tid)
    await broadcast_devices()
    return res


@app.post("/api/devices/tv/{tid}/action")
async def api_tv_action_id(tid: str, request: Request):
    check_token(request)
    body = await _json(request)
    if str(body.get("target")) == "*":
        return await tv.action_many(body)
    return await tv.action_async(body, tid)


# ---------- 设备：PC ----------
@app.put("/api/devices/pc/{pid}")
async def api_pc_rename(pid: str, request: Request):
    check_token(request)
    body = await _json(request)
    try:
        rec = devices.rename_pc(pid, body.get("name", ""))
    except DeviceError as e:
        code = 404 if "not found" in str(e) else 400
        raise HTTPException(status_code=code, detail=str(e))
    await broadcast_devices()
    return {"ok": True, "pc": rec}


@app.delete("/api/devices/pc/{pid}")
async def api_pc_delete(pid: str, request: Request):
    check_token(request)
    ok = devices.delete_pc(pid)
    await broadcast_devices()
    return {"ok": ok}


# ---------- 兼容老接口：默认电视 ----------
@app.get("/api/tv")
def api_tv_status(request: Request):
    check_token(request)
    return tv.status()


@app.put("/api/tv")
async def api_tv_save(request: Request):
    check_token(request)
    body = await _json(request)
    cur = devices.default_tv()
    payload = dict(cur or {})
    payload.update(body)
    try:
        tv.save_tv(payload)
    except DeviceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await broadcast_devices()
    return {"ok": True}


@app.post("/api/tv/connect")
async def api_tv_connect(request: Request):
    check_token(request)
    res = await tv.connect_async()
    await broadcast_devices()
    return res


@app.post("/api/tv/disconnect")
async def api_tv_disconnect(request: Request):
    check_token(request)
    res = await tv.disconnect_async()
    await broadcast_devices()
    return res


@app.post("/api/tv/action")
async def api_tv_action(request: Request):
    check_token(request)
    body = await _json(request)
    return await tv.action_async(body)


# ---------- WebSocket：PC Agent ----------
@app.websocket("/ws/agent")
async def ws_agent(ws: WebSocket):
    await ws.accept()
    if ws.query_params.get("token", "") != TOKEN:
        await ws.close(code=4401)
        return

    aid = (ws.query_params.get("id") or "").strip()
    if not AGENT_ID_RE.match(aid or ""):
        aid = "pc-" + os.urandom(3).hex()
    conn = AgentConn(ws, aid,
                     name=(ws.query_params.get("name") or "")[:24],
                     platform=(ws.query_params.get("platform") or "")[:60])

    # 同一台电脑重连：顶掉旧连接，旧连接的按键状态作废
    old = hub.agents.get(aid)
    hub.agents[aid] = conn
    if old is not None and old.ws is not ws:
        old.holders.clear()
        try:
            await old.ws.close(code=4400)
        except Exception:
            pass

    await hub.broadcast({"t": "agent_status", "online": True})
    await broadcast_devices()

    try:
        while True:
            raw = await ws.receive_text()
            conn.last_seen = time.monotonic()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if isinstance(msg, dict) and msg.get("t") == "hello":
                conn.name = str(msg.get("name") or conn.name or aid)[:24]
                conn.platform = str(msg.get("platform") or conn.platform)[:60]
                conn.version = str(msg.get("version") or "")[:20]
                try:
                    devices.upsert_pc(aid, conn.name, conn.platform)
                except DeviceError:
                    pass
                await broadcast_devices()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if hub.agents.get(aid) is conn:
            hub.agents.pop(aid, None)
            await hub.broadcast({"t": "agent_status", "online": hub.any_online()})
            await broadcast_devices()


# ---------- WebSocket：手机遥控 ----------
async def route_pc(ws: WebSocket, msg: dict, target: str) -> str:
    """把一条 PC 指令投递到目标（target 为空=默认，* = 全部在线）。"""
    if target == "*":
        conns = [hub.agents[aid] for aid in hub.online_ids()]
        if not conns:
            return "agent_offline"
    else:
        conn = hub.conn_for(target)
        if conn is None:
            return "target_offline" if target else "agent_offline"
        conns = [conn]

    kind = msg["t"]
    key = str(msg.get("key", "")).lower()
    payload = {k: v for k, v in msg.items() if k != "target"}
    errors = []
    for conn in conns:
        if kind == "key_down":
            err = await hub.hold_down(ws, conn, key)
        elif kind == "key_up":
            err = await hub.hold_up(ws, conn, key)
        else:
            err = await hub.send(conn, payload)
        if err:
            errors.append(err)
    return errors[0] if errors and len(errors) == len(conns) else ""


@app.websocket("/ws/remote")
async def ws_remote(ws: WebSocket):
    await ws.accept()
    if ws.query_params.get("token", "") != TOKEN:
        await ws.close(code=4401)
        return
    hub.remotes.add(ws)
    await ws.send_text(json.dumps({"t": "agent_status", "online": hub.any_online()}))
    await ws.send_text(json.dumps({"t": "devices", "pcs": hub.pc_list(), "tvs": tv.brief()}))
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            if not isinstance(msg, dict):
                continue
            t = msg.get("t")
            if t not in ALLOWED_TYPES:
                continue
            target = str(msg.get("target") or "").strip()

            if t == "ping":
                await ws.send_text(json.dumps({
                    "t": "pong",
                    "agent_online": hub.any_online(),
                    "agents": len(hub.agents),
                }))
                continue

            if t == "adb":
                # 电视指令由中枢本地执行，不经过 PC Agent
                act = msg.get("action") or {}
                if target == "*":
                    res = await tv.action_many(act)
                else:
                    res = await tv.action_async(act, target or None)
                try:
                    await ws.send_text(json.dumps({"t": "tv_result", **res}))
                except Exception:
                    pass
                continue

            err = await route_pc(ws, msg, target)
            if err:
                try:
                    await ws.send_text(json.dumps(
                        {"t": "error", "msg": err, "target": target,
                         "action": t}))
                except Exception:
                    pass
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        hub.remotes.discard(ws)
        # 释放这台设备自己按住的键（即使还有其他设备在线）
        await hub.release_remote(ws)
        await hub.release_all_if_needed()


app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
