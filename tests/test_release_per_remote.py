"""回归：单设备断线时只释放它自己按住的键。

场景：两台手机都在线，A 按住 W 后断线。
期望：Agent 收到 key_up w（而不是 release_all），B 的连接不受影响；
      B 断开后才收到 release_all。
"""
import asyncio
import json
import sys

sys.path.insert(0, ".")

import websockets

URL = "ws://127.0.0.1:8765"
TOKEN = "panel123"

passed = []


def ok(name):
    passed.append(name)
    print(f"  PASS  {name}")


async def recv_json(ws, timeout=3):
    while True:
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if msg.get("t") == "ping":
            continue
        return msg


AID = "pc-release-test"


async def main():
    print("== 单设备断线释放回归 ==")
    async with websockets.connect(
            f"{URL}/ws/agent?token={TOKEN}&id={AID}&name=断线测试机") as agent, \
               websockets.connect(f"{URL}/ws/remote?token={TOKEN}") as ra, \
               websockets.connect(f"{URL}/ws/remote?token={TOKEN}") as rb:
        # 清掉两台远端的初始 agent_status（中枢不给 Agent 推状态）
        await recv_json(ra)
        await recv_json(rb)

        # A 按住 W
        await ra.send(json.dumps({"t": "key_down", "key": "w", "target": AID}))
        assert (await recv_json(agent))["key"] == "w"
        ok("A key_down 转发到 Agent")

        # A 断线（with 块内先关闭）
        await ra.close()
        msg = await recv_json(agent)
        assert msg == {"t": "key_up", "key": "w"}, f"期望 key_up w，实际 {msg}"
        ok("A 断线 -> Agent 收到 key_up w（而非 release_all）")

        # B 仍在线，再按住 S
        await rb.send(json.dumps({"t": "key_down", "key": "s", "target": AID}))
        assert (await recv_json(agent))["key"] == "s"
        ok("B 不受影响，key_down 正常转发")

        # B 断线 -> 先释放它自己的 s，再全量兜底 release_all
        await rb.close()
        msg = await recv_json(agent)
        assert msg == {"t": "key_up", "key": "s"}, f"期望 key_up s，实际 {msg}"
        ok("B 断线 -> 先收到 key_up s")
        msg = await recv_json(agent)
        assert msg["t"] == "release_all", f"期望 release_all，实际 {msg}"
        ok("B 断线 -> release_all 兜底")

    print(f"\n全部通过：{len(passed)} 项")


if __name__ == "__main__":
    asyncio.run(main())
