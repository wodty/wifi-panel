"""多设备路由测试。

覆盖：
  1. 两台 Agent 同时在线（不再互相顶掉）
  2. 指令按 target 定向，只有目标收到
  3. target="*" 广播到所有在线电脑
  4. 目标离线返回明确错误，不静默丢弃
  5. 不带 target 时走默认设备（老前端兼容）
  6. 两个遥控按住同一个键，最后一个松手才真正松开
  7. 同一 id 重连顶掉旧连接
  8. 多台电视各自独立配置，老接口只动默认那台
  9. 面板 targets 能存能读

前置：中枢已在 127.0.0.1:8765 运行（PANEL_TOKEN=panel123）
"""
import asyncio
import json
import shutil
import urllib.request
from pathlib import Path

import websockets

BASE = "http://127.0.0.1:8765"
WS = "ws://127.0.0.1:8765"
TOKEN = "panel123"
STORAGE = Path(__file__).resolve().parent.parent / "server" / "storage"
DEVICES = STORAGE / "devices.json"

# id 用 0 开头，保证「默认设备=按 id 排序第一台」在本地有残留连接时也可预测
A, B = "pc-0001", "pc-0002"

passed = []


def ok(name):
    passed.append(name)
    print(f"  PASS  {name}")


def call(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"X-Token": TOKEN, "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req).read())


def call_err(path, method="GET", body=None):
    try:
        call(path, method, body)
    except urllib.error.HTTPError as e:
        return e.code
    return None


async def recv(ws, timeout=2.0):
    """读一条业务消息，跳过中枢心跳。"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remain = deadline - loop.time()
        if remain <= 0:
            raise asyncio.TimeoutError
        msg = json.loads(await asyncio.wait_for(ws.recv(), remain))
        if msg.get("t") == "ping":
            continue
        return msg


async def quiet(ws, timeout=0.6):
    """确认这段时间内没有业务消息（心跳不算）。"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remain = deadline - loop.time()
        if remain <= 0:
            return None
        try:
            msg = json.loads(await asyncio.wait_for(ws.recv(), remain))
        except asyncio.TimeoutError:
            return None
        if msg.get("t") == "ping":
            continue
        return msg


async def connect_agent(aid, name):
    url = f"{WS}/ws/agent?token={TOKEN}&id={aid}&name={name}"
    ws = await websockets.connect(url)
    await ws.send(json.dumps({"t": "hello", "id": aid, "name": name,
                              "platform": "test", "version": "0.2"}))
    return ws


async def test_multi_agent():
    a = await connect_agent(A, "机A")
    b = await connect_agent(B, "机B")
    await asyncio.sleep(0.4)

    devices = call("/api/devices")
    online = {p["id"] for p in devices["pcs"] if p["online"]}
    assert {A, B} <= online, devices
    ok("两台 Agent 同时在线，互不顶掉")

    remote = await websockets.connect(f"{WS}/ws/remote?token={TOKEN}")
    await recv(remote)  # agent_status
    await recv(remote)  # devices

    # 定向
    await remote.send(json.dumps({"t": "key_tap", "key": "a", "target": A}))
    assert await recv(a) == {"t": "key_tap", "key": "a"}
    assert await quiet(b) is None
    ok("target 定向：只有目标电脑收到")

    # 广播
    await remote.send(json.dumps({"t": "key_tap", "key": "b", "target": "*"}))
    assert await recv(a) == {"t": "key_tap", "key": "b"}
    assert await recv(b) == {"t": "key_tap", "key": "b"}
    ok("target=* 广播到所有在线电脑")

    # 离线目标
    await remote.send(json.dumps({"t": "key_tap", "key": "c", "target": "pc-nope"}))
    err = await recv(remote)
    assert err["t"] == "error" and err["msg"] == "target_offline", err
    ok("目标离线返回明确错误")

    # 不带 target -> 默认设备（按 id 排序第一台）
    await remote.send(json.dumps({"t": "key_tap", "key": "d"}))
    first = await recv(a, 1.5)
    assert first == {"t": "key_tap", "key": "d"}, first
    ok("不带 target 时走默认设备（老前端兼容）")

    await remote.close()
    await a.close()
    await b.close()


async def test_key_refcount():
    """两个遥控按住同一个键：先松手的不该把别人的键放掉。"""
    agent = await connect_agent(A, "机A")
    await asyncio.sleep(0.3)
    ra = await websockets.connect(f"{WS}/ws/remote?token={TOKEN}")
    rb = await websockets.connect(f"{WS}/ws/remote?token={TOKEN}")
    await recv(ra)
    await recv(rb)

    await ra.send(json.dumps({"t": "key_down", "key": "w", "target": A}))
    assert await recv(agent) == {"t": "key_down", "key": "w"}
    await rb.send(json.dumps({"t": "key_down", "key": "w", "target": A}))
    assert await quiet(agent) is None, "同一个键不应重复下发 key_down"
    ok("两个遥控按同一个键只下发一次 key_down")

    await ra.close()
    assert await quiet(agent) is None, "另一个遥控还按着，不该 key_up"
    ok("一个遥控松手不影响另一个还按着的键")

    await rb.close()
    msg = await recv(agent)
    assert msg == {"t": "key_up", "key": "w"}, msg
    ok("最后一个遥控断开才真正 key_up")

    await agent.close()


async def test_same_id_reconnect():
    first = await connect_agent(A, "机A")
    await asyncio.sleep(0.3)
    second = await connect_agent(A, "机A")
    await asyncio.sleep(0.3)
    closed = False
    try:
        await asyncio.wait_for(first.recv(), 2)
    except websockets.ConnectionClosed:
        closed = True
    except asyncio.TimeoutError:
        closed = False
    assert closed, "同 id 重连应顶掉旧连接"
    ok("同一 id 重连顶掉旧连接")
    await second.close()


async def test_multi_tv():
    before = json.loads(DEVICES.read_text(encoding="utf-8"))
    existing = [t["id"] for t in before.get("tvs", [])]
    created = []
    try:
        t1 = call("/api/devices/tv", "POST",
                  {"name": "客厅电视", "protocol": "adb", "ip": "192.168.99.91", "port": 5555})["tv"]
        t2 = call("/api/devices/tv", "POST",
                  {"name": "卧室电视", "protocol": "lg", "ip": "192.168.99.92", "port": 3000})["tv"]
        created = [t1["id"], t2["id"]]
        assert t1["id"] != t2["id"] and t1["id"] not in existing
        ok("可以添加多台电视，id 不冲突")

        tvs = {t["id"]: t for t in call("/api/devices")["tvs"]}
        assert tvs[t1["id"]]["ip"] == "192.168.99.91"
        assert tvs[t2["id"]]["protocol"] == "lg" and tvs[t2["id"]]["port"] == 3000
        ok("每台电视的协议 / IP / 端口互相独立")

        # 老接口只改「默认那台」（列表里的第一台），新加的电视不受影响
        call("/api/tv", "PUT", {"ip": "192.168.99.93", "port": 5555, "protocol": "adb"})
        tvs = {t["id"]: t for t in call("/api/devices")["tvs"]}
        first_id = tvs[call("/api/devices")["tvs"][0]["id"]]["id"]
        assert tvs[first_id]["ip"] == "192.168.99.93", tvs[first_id]
        assert tvs[t2["id"]]["ip"] == "192.168.99.92", tvs[t2["id"]]
        ok("老接口 /api/tv 只影响默认电视")

        # 定向指令：离线时返回的结果里带各自 id
        r = call(f"/api/devices/tv/{t2['id']}/action", "POST", {"kind": "key", "key": "home"})
        assert r["ok"] is False and r["id"] == t2["id"], r
        ok("电视动作按 id 定向，失败结果带设备 id")

        # 广播：打到所有电视并汇总
        r = call(f"/api/devices/tv/{t1['id']}/action", "POST",
                 {"kind": "key", "key": "home", "target": "*"})
        ids = {x["id"] for x in r.get("results", [])}
        assert {t1["id"], t2["id"]} <= ids, r
        assert r["ok"] is False and f"0/{len(ids)}" in r["msg"], r
        ok("电视广播打到所有电视并汇总结果")

        assert call(f"/api/devices/tv/{t2['id']}", "DELETE")["ok"] is True
        left = {t["id"] for t in call("/api/devices")["tvs"]}
        assert t2["id"] not in left and t1["id"] in left
        created.remove(t2["id"])
        ok("删除一台电视不影响其他台")
    finally:
        for tid in created:
            call(f"/api/devices/tv/{tid}", "DELETE")
        DEVICES.write_text(json.dumps(before, ensure_ascii=False, indent=2), encoding="utf-8")


def test_profile_targets():
    pid = "multi_target_test"
    body = {"name": "客厅", "targets": {"pc": A, "tv": "tv1"},
            "elements": [{"id": "e1", "type": "button", "label": "A",
                          "x": 10, "y": 10, "w": 10, "h": 10,
                          "action": {"type": "key", "key": "a"},
                          "target": "pc-0002"}]}
    call(f"/api/profiles/{pid}", "PUT", body)
    data = call(f"/api/profiles/{pid}")
    assert data["targets"] == {"pc": A, "tv": "tv1"}, data
    assert data["elements"][0]["target"] == "pc-0002"
    ok("面板 targets 与按键级 target 能存能读")

    listed = {p["id"]: p for p in call("/api/profiles")["profiles"]}
    assert listed[pid]["targets"]["pc"] == A
    ok("面板列表带出绑定的设备")

    call(f"/api/profiles/{pid}", "DELETE")


async def main():
    print("== 多设备测试 ==")
    await test_multi_agent()
    await test_key_refcount()
    await test_same_id_reconnect()
    test_profile_targets()
    await test_multi_tv()
    print(f"\n全部通过：{len(passed)} 项")


asyncio.run(main())
