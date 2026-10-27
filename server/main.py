"""wifi-panel 中枢服务。

职责：
  1. 托管 Web 面板静态页面（web/ 目录）
  2. 布局 profile 的 JSON 存储（server/storage/layouts/）
  3. WebSocket 消息中继：手机端(/ws/remote) -> PC Agent(/ws/agent)
  4. 安全兜底：所有远端断开后向 Agent 发送 release_all，防止按键卡死

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
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, Set

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).resolve().parent.parent
WEB_DIR = BASE / "web"
LAYOUTS = BASE / "server" / "storage" / "layouts"
LAYOUTS.mkdir(parents=True, exist_ok=True)

TOKEN = os.environ.get("PANEL_TOKEN", "panel123")
PORT = int(os.environ.get("PANEL_PORT", "8765"))

PID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")

# 允许从远端发来的消息类型（adb 由中枢本地执行，不转发给 Agent）
ALLOWED_TYPES = {
    "key_down", "key_up", "key_tap",
    "mouse_move", "mouse_click", "scroll",
    "media", "text", "adb", "ping",
}

try:
    from .tv import TVController
    from . import templates
except ImportError:  # 直接以脚本方式运行时
    from tv import TVController
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


@asynccontextmanager
async def lifespan(_app: FastAPI):
    seed_default_profile()
    yield


app = FastAPI(title="wifi-panel", lifespan=lifespan)

# 页面可以不在中枢上（例如本地打开一份网页、或从旧书签指到新 NAS）：
# 放开跨域，鉴权仍靠 X-Token，浏览器读不到别人的令牌。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Hub:
    """维护 Agent 连接、远端连接与按下状态。"""

    def __init__(self) -> None:
        self.agent: Optional[WebSocket] = None
        self.remotes: Set[WebSocket] = set()
        self.pressed: Set[str] = set()
        # 每个远端各自按住的键：单台断线时只释放它自己的，不影响其他设备
        self.remote_pressed: dict = {}
        self.lock = asyncio.Lock()

    async def broadcast(self, msg: dict) -> None:
        text = json.dumps(msg)
        for ws in list(self.remotes):
            try:
                await ws.send_text(text)
            except Exception:
                self.remotes.discard(ws)

    async def to_agent(self, msg: dict) -> bool:
        ws = self.agent
        if ws is None:
            return False
        try:
            await ws.send_text(json.dumps(msg))
            return True
        except Exception:
            self.agent = None
            return False

    async def release_all_if_needed(self) -> None:
        """最后一台远端断开时，无条件下发 release_all。

        即使逐键 key_up 已经清空 pressed，也作为兜底防线：
        防止任何未知原因导致的按键卡死（Agent 端释放是幂等的）。
        """
        async with self.lock:
            if self.remotes:
                return
            self.pressed.clear()
            await self.to_agent({"t": "release_all"})


hub = Hub()

tv = TVController(BASE / "server" / "storage")


async def run_tv(fn, *args):
    """adb 调用是阻塞的，丢进线程池执行。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: fn(*args))


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
    return {"ok": True, "agent_online": hub.agent is not None}


@app.get("/healthz")
def healthz():
    """容器健康检查用，不含任何鉴权信息。"""
    return {"ok": True}


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
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")
    if not isinstance(data, dict) or not isinstance(data.get("elements"), list):
        raise HTTPException(status_code=400, detail="profile must contain elements[]")
    data["id"] = pid
    if not data.get("name"):
        data["name"] = pid
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
    _layout_path(pid).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"ok": True, "id": pid}


# ---------- 电视控制 ----------
@app.get("/api/tv")
def api_tv_status(request: Request):
    check_token(request)
    return tv.status()


@app.put("/api/tv")
async def api_tv_save(request: Request):
    check_token(request)
    try:
        cfg = await request.json()
        tv.save_cfg(cfg)
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@app.post("/api/tv/connect")
async def api_tv_connect(request: Request):
    check_token(request)
    return await run_tv(tv.connect)


@app.post("/api/tv/disconnect")
async def api_tv_disconnect(request: Request):
    check_token(request)
    return await run_tv(tv.disconnect)


@app.post("/api/tv/action")
async def api_tv_action(request: Request):
    check_token(request)
    try:
        act = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")
    return await run_tv(tv.action, act)


@app.websocket("/ws/agent")
async def ws_agent(ws: WebSocket):
    await ws.accept()
    if ws.query_params.get("token", "") != TOKEN:
        await ws.close(code=4401)
        return
    hub.agent = ws
    await hub.broadcast({"t": "agent_status", "online": True})
    try:
        while True:
            raw = await ws.receive_text()
            # Agent -> 中枢目前只有状态类消息，全部忽略（预留版本/心跳）
            _ = raw
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if hub.agent is ws:
            hub.agent = None
            hub.pressed.clear()
            hub.remote_pressed.clear()
            await hub.broadcast({"t": "agent_status", "online": False})


@app.websocket("/ws/remote")
async def ws_remote(ws: WebSocket):
    await ws.accept()
    if ws.query_params.get("token", "") != TOKEN:
        await ws.close(code=4401)
        return
    hub.remotes.add(ws)
    await ws.send_text(json.dumps({"t": "agent_status", "online": hub.agent is not None}))
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            t = msg.get("t")
            if t not in ALLOWED_TYPES:
                continue
            if t == "ping":
                await ws.send_text(json.dumps({"t": "pong", "agent_online": hub.agent is not None}))
                continue
            if t == "adb":
                # 电视指令由中枢本地执行，不经过 PC Agent
                res = await run_tv(tv.action, msg.get("action") or {})
                try:
                    await ws.send_text(json.dumps({"t": "tv_result", **res}))
                except Exception:
                    pass
                continue
            if t == "key_down":
                key = str(msg.get("key", "")).lower()
                hub.pressed.add(key)
                hub.remote_pressed.setdefault(ws, set()).add(key)
            elif t == "key_up":
                key = str(msg.get("key", "")).lower()
                hub.pressed.discard(key)
                keys = hub.remote_pressed.get(ws)
                if keys:
                    keys.discard(key)
            ok = await hub.to_agent(msg)
            if not ok:
                await ws.send_text(json.dumps({"t": "error", "msg": "agent_offline"}))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        hub.remotes.discard(ws)
        # 释放这台设备自己按住的键（即使还有其他设备在线）
        for key in hub.remote_pressed.pop(ws, set()):
            hub.pressed.discard(key)
            await hub.to_agent({"t": "key_up", "key": key})
        await hub.release_all_if_needed()


app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
