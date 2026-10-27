"""内置面板模板（唯一数据源）。

服务端首次启动时用 DEFAULT_KIND 播种一个默认面板，前端「新建面板」
也从 /api/templates 读取模板列表——模板只在这里定义一份，避免前后端漂移。

坐标全部是百分比（0-100），换屏幕尺寸不会错位。
"""
from typing import Optional

# 默认模板：新用户第一次打开就能用，不需要自己拖按钮
DEFAULT_KIND = "universal"

# 模板版本：升级内置模板时 +1，服务端会据此刷新「未被用户改过」的默认面板
REV = 2

# 配色（低饱和深色底上的可读色）
C_BLUE = "#378add"    # 常规功能键
C_GREEN = "#639922"   # 确认类（Enter）
C_PURPLE = "#534AB7"  # 组合键
C_GRAY = "#888780"    # 次要键（Esc / Tab / 翻页）
C_BROWN = "#854f0b"   # 鼠标
C_RED = "#e24b4a"     # 破坏性/静音
C_TEAL = "#1f8a8a"    # 媒体
C_ORANGE = "#b4652f"  # 电视（和 PC 键在配色上分开）


def _btn(eid, label, x, y, w, h, action, color=C_BLUE, shape="rect"):
    return {
        "id": eid, "type": "button", "label": label,
        "x": x, "y": y, "w": w, "h": h,
        "shape": shape, "color": color, "action": action,
    }


def _k(key, mode="tap", mods=None):
    return {"type": "key", "key": key, "mode": mode, "mods": mods or []}


def _mouse(button):
    return {"type": "mouse_click", "button": button}


def _media(action):
    return {"type": "media", "action": action}


def _adb(key):
    return {"type": "adb_key", "key": key}


def _touchpad(eid, x=0, y=0, w=100, h=40):
    return {"id": eid, "type": "touchpad", "x": x, "y": y, "w": w, "h": h}


# ---------- 通用（默认）----------
# 竖屏全屏一张面板，一块屏幕同时管 PC 和电视：
#   顶部触控板（单指移动、轻点左键、双指滚动/右键）
#   鼠标三键 → PC 常用键 3 行 → 电视遥控 2 行（橙色，与 PC 键区分）
_COLS = (2, 22, 42, 62, 82)
_CW = 18


def universal() -> list:
    els = [_touchpad("u_tp", h=33)]

    # 三键鼠标：触控板轻点已经能左键，这里补显式按键（含中键）
    els += [
        _btn("u_m0", "左键", 2, 34, 30, 7, _mouse("left"), C_BROWN),
        _btn("u_m1", "中键", 35, 34, 30, 7, _mouse("middle"), C_BROWN),
        _btn("u_m2", "右键", 68, 34, 30, 7, _mouse("right"), C_BROWN),
    ]

    rows = [
        # PC · 基础编辑
        [("Esc", _k("esc"), C_GRAY), ("Tab", _k("tab"), C_GRAY),
         ("Enter", _k("enter"), C_GREEN), ("退格", _k("backspace"), C_GRAY),
         ("空格", _k("space"), C_BLUE)],
        # PC · 高频组合键
        [("复制", _k("c", mods=["ctrl"]), C_PURPLE), ("粘贴", _k("v", mods=["ctrl"]), C_PURPLE),
         ("撤销", _k("z", mods=["ctrl"]), C_PURPLE), ("全选", _k("a", mods=["ctrl"]), C_PURPLE),
         ("Alt+Tab", _k("tab", mods=["alt"]), C_PURPLE)],
        # PC · 窗口与翻页
        [("上页", _k("page_up"), C_GRAY), ("下页", _k("page_down"), C_GRAY),
         ("删除", _k("delete"), C_GRAY), ("静音", _media("mute"), C_TEAL),
         ("Win", _k("cmd"), C_PURPLE)],
        # 电视 · 方向环
        [("◀", _adb("dpad_left"), C_ORANGE), ("▲", _adb("dpad_up"), C_ORANGE),
         ("OK", _adb("ok"), C_GREEN), ("▼", _adb("dpad_down"), C_ORANGE),
         ("▶", _adb("dpad_right"), C_ORANGE)],
        # 电视 · 返回与音量（电源不放默认面板，避免误触关机）
        [("返回", _adb("back"), C_GRAY), ("桌面", _adb("home"), C_GRAY),
         ("菜单", _adb("menu"), C_GRAY), ("音量-", _adb("volume_down"), C_ORANGE),
         ("音量+", _adb("volume_up"), C_ORANGE)],
    ]
    y = 42.5
    row_h = 10.0
    for ri, row in enumerate(rows):
        for ci, (label, action, color) in enumerate(row):
            els.append(_btn(f"u{ri}{ci}", label, _COLS[ci], round(y, 1), _CW, row_h, action, color))
        y += row_h + 0.8
    return els


def gamepad() -> list:
    arrow = lambda k: _k(k, mode="hold")
    return [
        _touchpad("g_tp", h=42),
        _btn("g_w", "W", 14, 56, 13, 16, arrow("w"), C_BLUE, "round"),
        _btn("g_a", "A", 3, 74, 13, 16, arrow("a"), C_BLUE, "round"),
        _btn("g_s", "S", 14, 80, 13, 16, arrow("s"), C_BLUE, "round"),
        _btn("g_d", "D", 25, 74, 13, 16, arrow("d"), C_BLUE, "round"),
        _btn("g_jump", "跳", 78, 70, 16, 18, arrow("space"), C_GREEN, "round"),
        _btn("g_lmb", "左键", 60, 86, 14, 11, _mouse("left"), C_BROWN),
        _btn("g_shift", "Shift", 42, 86, 14, 11, arrow("shift"), C_PURPLE),
    ]


def tv() -> list:
    return [
        _btn("t_pow", "电源", 8, 6, 20, 9, _adb("power"), C_RED),
        _btn("t_volp", "音量+", 74, 20, 20, 11, _adb("volume_up"), C_BLUE),
        _btn("t_volm", "音量-", 74, 36, 20, 11, _adb("volume_down"), C_BLUE),
        _btn("t_mute", "静音", 74, 52, 20, 11, _adb("mute"), C_PURPLE),
        _btn("t_up", "▲", 41, 33, 18, 14, _adb("dpad_up"), C_BLUE, "round"),
        _btn("t_left", "◀", 22, 50, 16, 16, _adb("dpad_left"), C_BLUE, "round"),
        _btn("t_ok", "OK", 42, 50, 16, 16, _adb("ok"), C_GREEN, "round"),
        _btn("t_right", "▶", 62, 50, 16, 16, _adb("dpad_right"), C_BLUE, "round"),
        _btn("t_down", "▼", 41, 70, 18, 14, _adb("dpad_down"), C_BLUE, "round"),
        _btn("t_back", "返回", 8, 88, 20, 10, _adb("back"), C_GRAY),
        _btn("t_home", "桌面", 32, 88, 20, 10, _adb("home"), C_GRAY),
        _btn("t_menu", "菜单", 56, 88, 20, 10, _adb("menu"), C_GRAY),
    ]


def media() -> list:
    return [
        _btn("m_vup", "音量+", 8, 20, 26, 14, _media("volume_up"), C_BLUE),
        _btn("m_vdn", "音量-", 8, 38, 26, 14, _media("volume_down"), C_BLUE),
        _btn("m_mute", "静音", 8, 56, 26, 14, _media("mute"), C_PURPLE),
        _btn("m_play", "播放/暂停", 40, 38, 26, 14, _media("play_pause"), C_GREEN),
        _btn("m_esc", "Esc", 40, 20, 26, 14, _k("esc"), C_GRAY),
        _btn("m_alt", "Alt+Tab", 40, 56, 26, 14, _k("tab", mods=["alt"]), C_BROWN),
    ]


def blank() -> list:
    return [_touchpad("b_tp", h=40)]


TEMPLATES = [
    {"kind": "universal", "name": "通用", "desc": "PC 鼠标键盘 + 电视遥控，一块屏全管，默认推荐", "build": universal},
    {"kind": "gamepad", "name": "游戏手柄", "desc": "触控板 + WASD + 跳跃，横屏更佳", "build": gamepad},
    {"kind": "media", "name": "媒体控制", "desc": "音量、播放、窗口切换", "build": media},
    {"kind": "tv", "name": "电视遥控", "desc": "方向环 + 音量 + 返回（需先配电视）", "build": tv},
    {"kind": "blank", "name": "空白", "desc": "从一块触控板开始自己搭", "build": blank},
]

_BY_KIND = {t["kind"]: t for t in TEMPLATES}


def catalog() -> list:
    """给前端的模板清单（不含元素，减小传输）。"""
    return [
        {"kind": t["kind"], "name": t["name"], "desc": t["desc"],
         "default": t["kind"] == DEFAULT_KIND, "count": len(t["build"]())}
        for t in TEMPLATES
    ]


def build(kind: str, pid: str, name: Optional[str] = None) -> dict:
    """生成一份可直接落盘的 profile。"""
    tpl = _BY_KIND.get(kind) or _BY_KIND[DEFAULT_KIND]
    return {
        "id": pid,
        "name": name or tpl["name"],
        "template": tpl["kind"],
        "template_rev": REV,
        # 面板绑定的目标设备（{"pc": "pc-xxx", "tv": "tv1"}），空 = 用默认设备
        "targets": {},
        "elements": tpl["build"](),
    }
