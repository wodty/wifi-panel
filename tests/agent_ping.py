"""Agent 通路自检：不需要真实操作电脑，验证「手机端 -> 中枢 -> PC Agent」整条链路。

原理：发送一个无害的 key_up（释放未按下的键，屏幕不会有任何反应），
若 Agent 在线且链路通畅，中枢不会回 error。
用法：
  python tests/agent_ping.py [ws://host:8765] [token]
"""
import asyncio
import json
import sys

import websockets

WS = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:8765"
TOKEN = sys.argv[2] if len(sys.argv) > 2 else "panel123"


async def main():
    url = f"{WS}/ws/remote?token={TOKEN}"
    async with websockets.connect(url) as ws:
        first = json.loads(await asyncio.wait_for(ws.recv(), 3))
        online = first.get("online", False)
        print(f"Agent 状态: {'在线' if online else '离线'}")
        if not online:
            print("→ 请先启动 agent/agent.py")
            return 1
        await ws.send(json.dumps({"t": "key_up", "key": "unused_key_check"}))
        await asyncio.sleep(0.4)
        # 中枢发现 Agent 不在线时会回 error
        try:
            msg = json.loads(await asyncio.wait_for(ws.recv(), 1))
            if msg.get("t") == "error":
                print(f"链路异常: {msg.get('msg')}")
                return 1
        except asyncio.TimeoutError:
            pass
        print("链路正常：手机 -> 中枢 -> Agent 全通")
        return 0


sys.exit(asyncio.run(main()))
