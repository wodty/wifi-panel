"""wifi-panel 端到端冒烟测试。

验证链路：远端 WebSocket -> 中枢 -> Agent WebSocket
  1. 错误令牌被拒绝
  2. Agent 上线后远端收到 agent_status
  3. 远端 key_down 转发到 Agent
  4. 远端全部断开后 Agent 收到 release_all（防按键卡死）
  5. profile 存储增删查正常

前置：中枢已在 127.0.0.1:8765 运行（PANEL_TOKEN=panel123）
"""
import asyncio
import json
import urllib.request

import websockets

BASE = "http://127.0.0.1:8765"
WS = "ws://127.0.0.1:8765"
TOKEN = "panel123"

passed = []


def ok(name):
    passed.append(name)
    print(f"  PASS  {name}")


async def test_auth_rejected():
    try:
        async with websockets.connect(f"{WS}/ws/remote?token=wrong") as ws:
            await ws.recv()
        raise AssertionError("bad token was accepted")
    except websockets.exceptions.ConnectionClosed as e:
        assert e.rcvd and e.rcvd.code == 4401, e
        ok("错误令牌被拒绝 (4401)")


async def test_relay_and_release():
    agent = await websockets.connect(f"{WS}/ws/agent?token={TOKEN}")
    remote = await websockets.connect(f"{WS}/ws/remote?token={TOKEN}")

    # 远端连上后应立即收到 agent_status
    status = json.loads(await asyncio.wait_for(remote.recv(), 3))
    assert status == {"t": "agent_status", "online": True}, status
    ok("Agent 上线 -> 远端收到 agent_status")

    # key_down 转发
    await remote.send(json.dumps({"t": "key_down", "key": "w"}))
    msg = json.loads(await asyncio.wait_for(agent.recv(), 3))
    assert msg == {"t": "key_down", "key": "w"}, msg
    ok("远端 key_down 转发到 Agent")

    # key_tap 转发
    await remote.send(json.dumps({"t": "key_tap", "key": "c", "mods": ["ctrl"]}))
    msg = json.loads(await asyncio.wait_for(agent.recv(), 3))
    assert msg["t"] == "key_tap" and msg["mods"] == ["ctrl"], msg
    ok("组合键 key_tap 转发")

    # 远端断开 -> Agent 先收到逐键 key_up，再收到 release_all 兜底
    await remote.close()
    msg = json.loads(await asyncio.wait_for(agent.recv(), 3))
    assert msg == {"t": "key_up", "key": "w"}, msg
    msg = json.loads(await asyncio.wait_for(agent.recv(), 3))
    assert msg == {"t": "release_all"}, msg
    ok("远端断开 -> key_up + release_all 双重兜底（防按键卡死）")

    await agent.close()
    # 等 Agent 离线广播（无远端在线，直接验证新远端收到的初始状态）
    remote2 = await websockets.connect(f"{WS}/ws/remote?token={TOKEN}")
    status = json.loads(await asyncio.wait_for(remote2.recv(), 3))
    assert status["online"] is False, status
    ok("Agent 离线 -> 新远端收到 offline 状态")
    await remote2.close()


async def test_profiles_api():
    pid = "smoke_test"
    body = json.dumps({"name": "冒烟", "elements": [
        {"id": "e1", "type": "button", "label": "A", "x": 10, "y": 10, "w": 10, "h": 10,
         "action": {"type": "key", "key": "a", "mode": "tap", "mods": []}}]}).encode()

    req = urllib.request.Request(f"{BASE}/api/profiles/{pid}", data=body, method="PUT",
                                 headers={"X-Token": TOKEN, "Content-Type": "application/json"})
    assert json.loads(urllib.request.urlopen(req).read())["ok"] is True
    ok("PUT 创建 profile")

    data = json.loads(urllib.request.urlopen(
        urllib.request.Request(f"{BASE}/api/profiles/{pid}", headers={"X-Token": TOKEN})).read())
    assert data["name"] == "冒烟" and data["elements"][0]["label"] == "A"
    ok("GET 读取 profile")

    try:
        urllib.request.urlopen(f"{BASE}/api/profiles/{pid}")
        raise AssertionError("missing token accepted")
    except urllib.error.HTTPError as e:
        assert e.code == 401
        ok("API 无令牌返回 401")

    req = urllib.request.Request(f"{BASE}/api/profiles/{pid}", method="DELETE",
                                 headers={"X-Token": TOKEN})
    assert json.loads(urllib.request.urlopen(req).read())["ok"] is True
    ok("DELETE 清理 profile")


async def main():
    print("== wifi-panel 冒烟测试 ==")
    await test_auth_rejected()
    await test_relay_and_release()
    await test_profiles_api()
    print(f"\n全部通过：{len(passed)} 项")


asyncio.run(main())
