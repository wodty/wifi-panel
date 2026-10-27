"""电视模块冒烟测试。

不要求真实电视在线：验证 TV API 的配置、鉴权与优雅降级
（adb 未安装 / 电视离线 / 非法输入均返回结构化错误而非 500）。
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


def call(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"X-Token": TOKEN, "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req).read())


def main_test():
    s = call("/api/tv")
    assert set(s) >= {"cfg", "adb_installed", "online"}, s
    ok("GET /api/tv 返回状态结构")

    call("/api/tv", "PUT", {"ip": "192.168.99.99", "port": 5555})
    assert call("/api/tv")["cfg"]["ip"] == "192.168.99.99"
    ok("PUT 保存电视配置")

    try:
        call("/api/tv", "PUT", {"ip": "bad ip!!", "port": 5555})
        raise AssertionError("invalid ip accepted")
    except urllib.error.HTTPError as e:
        assert e.code == 400
        ok("非法 IP 被拒绝 (400)")

    r = call("/api/tv/action", "POST", {"kind": "key", "key": "dpad_up"})
    assert isinstance(r, dict) and "ok" in r and r["ok"] is False, r
    ok("电视离线时按键指令优雅返回失败（不 500）")

    r = call("/api/tv/action", "POST", {"kind": "key", "key": "not_a_key"})
    assert r["ok"] is False
    ok("未知按键名被拒绝")

    r = call("/api/tv/action", "POST", {"kind": "app", "package": "bad pkg!"})
    assert r["ok"] is False
    ok("非法包名被拒绝（防注入）")

    call("/api/tv", "PUT", {"ip": "", "port": 5555})
    r = call("/api/tv/action", "POST", {"kind": "key", "key": "dpad_up"})
    assert r["ok"] is False and "未配置" in r["msg"]
    ok("未配置 IP 时给出明确提示")


async def ws_test():
    remote = await websockets.connect(f"{WS}/ws/remote?token={TOKEN}")
    first = json.loads(await asyncio.wait_for(remote.recv(), 3))
    assert first["t"] == "agent_status", first
    await remote.send(json.dumps({"t": "adb", "action": {"kind": "key", "key": "dpad_up"}}))
    msg = json.loads(await asyncio.wait_for(remote.recv(), 5))
    assert msg["t"] == "tv_result" and msg["ok"] is False, msg
    ok("WS adb 指令 -> 中枢本地执行并回 tv_result")
    await remote.close()


def test_protocols():
    """多协议：配置保存、非法协议拒绝、离线时优雅失败。"""
    call("/api/tv", "PUT", {"ip": "192.168.99.99", "port": 8001, "protocol": "samsung"})
    cfg = call("/api/tv")["cfg"]
    assert cfg["protocol"] == "samsung" and cfg["port"] == 8001
    ok("三星协议配置保存")

    r = call("/api/tv/action", "POST", {"kind": "key", "key": "dpad_up"})
    assert r["ok"] is False and isinstance(r["msg"], str)
    ok("三星离线时按键优雅失败（不 500）")

    try:
        call("/api/tv", "PUT", {"ip": "1.2.3.4", "port": 1, "protocol": "whatever"})
        raise AssertionError("invalid protocol accepted")
    except urllib.error.HTTPError as e:
        assert e.code == 400
        ok("非法协议被拒绝 (400)")

    call("/api/tv", "PUT", {"ip": "192.168.99.99", "port": 3000, "protocol": "lg"})
    for k in ("dpad_up", "volume_up", "power"):
        r = call("/api/tv/action", "POST", {"kind": "key", "key": k})
        assert r["ok"] is False and isinstance(r["msg"], str), r
    ok("LG 三类按键离线时优雅失败")

    call("/api/tv", "PUT", {"ip": "192.168.99.99", "port": 5555, "protocol": "adb"})
    ok("切回 ADB 协议")


async def main():
    print("== 电视模块冒烟测试 ==")
    main_test()
    test_protocols()
    await ws_test()
    print(f"\n全部通过：{len(passed)} 项")


asyncio.run(main())
