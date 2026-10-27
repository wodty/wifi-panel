"""生成 Android 启动图标（mipmap-*dpi/ic_launcher.png）。

用法：
    python android/tools/gen_icons.py
需要 Pillow。改配色/形状只需改本文件的常量，重跑即可。
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent / "app" / "src" / "main" / "res"
SIZES = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}

BG_TOP = (24, 30, 48)       # 深蓝底
BG_BOTTOM = (16, 20, 33)
ACCENT = (86, 204, 190)     # 青绿
ACCENT2 = (122, 148, 255)   # 靛蓝
TILE = (238, 242, 250)


def rounded(draw, box, r, fill):
    draw.rounded_rectangle(box, radius=r, fill=fill)


def render(size: int) -> Image.Image:
    scale = 8  # 超采样，边缘更干净
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 竖向渐变底 + 圆角遮罩
    grad = Image.new("RGB", (1, s))
    for y in range(s):
        t = y / max(1, s - 1)
        grad.putpixel((0, y), tuple(int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM)))
    grad = grad.resize((s, s))
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.22), fill=255)
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)

    # WiFi 三段弧（圆心在下方居中）
    cx, cy = s * 0.5, s * 0.62
    for i, r in enumerate((0.30, 0.22, 0.14)):
        rr = s * r
        w = int(s * 0.055)
        d.arc(
            (cx - rr, cy - rr, cx + rr, cy + rr),
            start=225,
            end=315,
            fill=ACCENT if i == 2 else ACCENT2,
            width=w,
        )
    dot = s * 0.035
    d.ellipse((cx - dot, cy - dot - s * 0.015, cx + dot, cy + dot - s * 0.015), fill=TILE)

    # 底部 2x3 按键格（面板意象）
    bw, bh, gap = s * 0.115, s * 0.075, s * 0.022
    total_w = bw * 3 + gap * 2
    x0 = (s - total_w) / 2
    y0 = s * 0.74
    for row in range(2):
        for col in range(3):
            x = x0 + col * (bw + gap)
            y = y0 + row * (bh + gap)
            rounded(d, (x, y, x + bw, y + bh), bh * 0.32, TILE)

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    for dpi, size in SIZES.items():
        out = ROOT / f"mipmap-{dpi}" / "ic_launcher.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        render(size).save(out)
        print(f"wrote {out.relative_to(ROOT.parent.parent.parent.parent)} ({size}px)")


if __name__ == "__main__":
    main()
