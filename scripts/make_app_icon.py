# ── AI-ASSISTED ── 本文件由 AI 生成，待人工复核 ──
"""把芙宁娜立绘原图处理成 Tauri 打包用的图标母版。

原图是"带圆角外框的方形插画"，框外还有一圈柔和光晕。直接按像素抠边会得到毛边，
所以这里分两步：
  1. 用洪泛填充粗测外框包围盒，再从左上角的弧形边界拟合圆角半径；
  2. 用拟合出的圆角矩形**重绘**一张抗锯齿遮罩，把框外（含光晕）全部切掉。

输出 1024×1024 RGBA 母版，之后交给 Tauri CLI 生成全平台图标：
    cd apps/desktop/src/frontend
    npx tauri icon ../../../assets/pixel-art/icon_master_1024.png

复核重点：
1. 圆角半径是从左上角拟合的（~310px @1254）。若换图，务必跑 --probe 看四个角的偏差；
   拟合偏差大时用 --rect left,top,right,bottom,radius 手动覆盖。
2. 我选择把框外做成全透明，而不是保留浅蓝底——为了让图标在深色任务栏上不出现白方块。
   想保留原底就加 --keep-background。
3. 正方形的补边是"垂直居中补透明"，不是拉伸，避免人物被压扁。
"""
from __future__ import annotations

import argparse
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

# 框外背景实测 ≈ RGB(246,250,254)；±10 内视为同色。只见于粗测包围盒，不参与最终遮罩
FLOOD_THRESH = 10
# 判定"这一行/列确实有内容"的最小像素数，用来滤掉孤立噪点
CONTENT_MIN_PX = 100
MASTER_SIZE = 1024
# 遮罩超采样倍数，降采样后边缘才平滑
SUPERSAMPLE = 4


def detect_rect(im: Image.Image) -> tuple[int, int, int, int, float]:
    """返回外框的 (left, top, right, bottom, radius)，右/下为开区间。"""
    w, h = im.size
    probe = im.convert("RGB").copy()
    for seed in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        ImageDraw.floodfill(probe, seed, (255, 0, 255), thresh=FLOOD_THRESH)
    outside = np.all(np.array(probe) == (255, 0, 255), axis=2)
    if outside.sum() > 0.6 * w * h:
        raise SystemExit(f"框外面积占比异常（{outside.sum() / (w * h):.1%}），原图可能没有闭合外框")

    content = ~outside
    rows, cols = content.sum(1), content.sum(0)
    ys, xs = np.nonzero(rows > CONTENT_MIN_PX)[0], np.nonzero(cols > CONTENT_MIN_PX)[0]
    if not len(ys) or not len(xs):
        raise SystemExit("没找到内容区域")
    top, bottom, left, right = int(ys[0]), int(ys[-1]) + 1, int(xs[0]), int(xs[-1]) + 1

    # 从左上角估算半径：取沿左边缘的若干行，解 (r-dy)^2 = 2*r*inset - inset^2
    guesses: list[float] = []
    for dy in range(20, min(320, (bottom - top) // 2), 10):
        row = content[top + dy]
        xs_row = np.nonzero(row)[0]
        if not len(xs_row):
            continue
        inset = int(xs_row.min()) - left
        if inset <= dy:
            continue
        disc = 2 * dy * inset
        guesses.append((dy + inset) + math.sqrt(disc))
    if not guesses:
        raise SystemExit("圆角拟合失败，请用 --rect 手动指定")
    return left, top, right, bottom, float(np.median(guesses))


def rounded_mask(size: tuple[int, int], rect: tuple[int, int, int, int, float],
                 ss: int = SUPERSAMPLE) -> Image.Image:
    """在超采样画布上画圆角矩形，再降采样得到抗锯齿的 L 通道遮罩。"""
    w, h = size
    left, top, right, bottom, radius = rect
    big = Image.new("L", (w * ss, h * ss), 0)
    ImageDraw.Draw(big).rounded_rectangle(
        [left * ss, top * ss, right * ss - 1, bottom * ss - 1],
        radius=radius * ss, fill=255,
    )
    return big.resize((w, h), Image.LANCZOS)


def build_master(src: str, keep_background: bool = False,
                 rect_override: tuple[int, int, int, int, float] | None = None) -> Image.Image:
    im = Image.open(src).convert("RGB")
    w, h = im.size
    if w != h:
        raise SystemExit(f"原图必须是正方形，实际 {w}x{h}")

    rect = rect_override or detect_rect(im)
    left, top, right, bottom, radius = rect
    print(f"外框 left={left} top={top} right={right} bottom={bottom} radius={radius:.1f}")

    alpha = rounded_mask((w, h), rect)
    out = im.convert("RGBA")
    if not keep_background:
        out.putalpha(alpha)
    else:
        out.putalpha(Image.new("L", (w, h), 255))

    # 裁到外框，再居中补成正方形（补透明，不拉伸）
    out = out.crop((left, top, right, bottom))
    cw, ch = out.size
    side = max(cw, ch)
    if cw != ch:
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        canvas.paste(out, ((side - cw) // 2, (side - ch) // 2))
        out = canvas
        print(f"内容 {cw}x{ch} → 居中补成 {side}x{side}")

    return out.resize((MASTER_SIZE, MASTER_SIZE), Image.LANCZOS)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="assets/pixel-art/furina_icon_source.png")
    ap.add_argument("--out", default="assets/pixel-art/icon_master_1024.png")
    ap.add_argument("--keep-background", action="store_true", help="保留原图浅蓝底，不抠透明")
    ap.add_argument("--rect", help="手动指定 left,top,right,bottom,radius")
    ap.add_argument("--probe", action="store_true", help="只打印拟合结果，不写文件")
    ap.add_argument("--preview", action="store_true", help="额外输出小尺寸深底预览，便于肉眼验收")
    args = ap.parse_args()

    override = None
    if args.rect:
        parts = [float(p) for p in args.rect.split(",")]
        if len(parts) != 5:
            raise SystemExit("--rect 需要 5 个数：left,top,right,bottom,radius")
        override = (int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]), parts[4])

    if args.probe:
        im = Image.open(args.src).convert("RGB")
        rect = override or detect_rect(im)
        print("拟合结果:", rect)
        return 0

    master = build_master(args.src, args.keep_background, override)
    master.save(args.out)
    print(f"已写出 {args.out} {master.size} {master.mode}")

    if args.preview:
        pdir = "assets/pixel-art/preview"
        os.makedirs(pdir, exist_ok=True)
        for size in (32, 48, 64, 128):
            small = master.resize((size, size), Image.LANCZOS)
            zoom = small.resize((size * 8, size * 8), Image.NEAREST)
            dark = Image.new("RGBA", zoom.size, (32, 34, 40, 255))
            dark.alpha_composite(zoom)
            dark.save(f"{pdir}/icon_{size}_dark.png")
        print(f"预览已写出到 {pdir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
