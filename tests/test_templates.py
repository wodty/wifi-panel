# -*- coding: utf-8 -*-
"""模板功能冒烟测试：清单接口、实例化、默认播种。

前置：中枢已在 127.0.0.1:8765 运行（PANEL_TOKEN=panel123）。
"""
import json
import urllib.request

BASE = "http://127.0.0.1:8765"
TOKEN = "panel123"
passed = []


def req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"X-Token": TOKEN, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def ok(name):
    passed.append(name)
    print(f"  ✓ {name}")


def main():
    print("== 模板模块冒烟测试 ==")

    code, data = req("GET", "/api/templates")
    assert code == 200 and data["default"] == "universal", (code, data)
    kinds = [t["kind"] for t in data["templates"]]
    assert set(kinds) == {"universal", "gamepad", "media", "tv", "blank"}, kinds
    uni = next(t for t in data["templates"] if t["kind"] == "universal")
    assert uni["default"] and uni["count"] >= 20
    ok("模板清单完整，universal 标记为默认")

    # 默认面板已播种
    code, data = req("GET", "/api/profiles")
    assert any(p["id"] == "default" for p in data["profiles"]), data
    ok("首次启动已播种默认通用面板")

    code, prof = req("GET", "/api/profiles/default")
    assert code == 200
    els = prof["elements"]
    types = {e["type"] for e in els}
    assert "touchpad" in types and "button" in types
    # 坐标都在 0-100 内，不越界
    assert all(0 <= e["x"] <= 100 and 0 <= e["y"] <= 100
               and 0 < e["x"] + e["w"] <= 100 and 0 < e["y"] + e["h"] <= 100 for e in els)
    # 每个按钮都有合法动作
    acts = []
    for e in els:
        if e["type"] == "button":
            t = e.get("action", {}).get("type")
            assert t in {"key", "mouse_click", "media", "adb_key", "adb_app"}
            acts.append(t)
    ok(f"默认面板 {len(els)} 元素：坐标合法、动作齐全")

    # 默认面板必须同时覆盖 PC 与电视（曾经只有 PC 键，用户反馈缺失）
    assert prof.get("template_rev") == 2, prof.get("template_rev")
    assert "key" in acts and "mouse_click" in acts, acts
    tv_keys = {e["action"]["key"] for e in els
               if e.get("action", {}).get("type") == "adb_key"}
    need = {"dpad_up", "dpad_down", "dpad_left", "dpad_right", "ok", "back", "home", "volume_up", "volume_down"}
    assert need <= tv_keys, f"缺少电视键: {need - tv_keys}"
    ok(f"默认面板含电视遥控 {len(tv_keys)} 键（方向环/OK/返回/桌面/音量）")

    # 实例化与清理
    code, r = req("POST", "/api/templates/gamepad", {})
    assert code == 200 and r["ok"] and r["id"], r
    pid = r["id"]
    code, prof = req("GET", f"/api/profiles/{pid}")
    assert prof["name"] == "游戏手柄" and len(prof["elements"]) == 8
    ok("按模板实例化新面板")

    code, r = req("POST", "/api/templates/unknown_kind", {})
    assert code == 404
    ok("未知模板返回 404")

    req("DELETE", f"/api/profiles/{pid}")
    code, data = req("GET", "/api/profiles")
    assert all(p["id"] != pid for p in data["profiles"])
    ok("实例化面板可删除清理")

    print(f"\n全部通过：{len(passed)} 项")


if __name__ == "__main__":
    main()
