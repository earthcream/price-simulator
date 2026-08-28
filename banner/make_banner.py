# -*- coding: utf-8 -*-
"""
価格波及シミュレーターの告知バナー（1320×420）を生成する。
  python banner/make_banner.py            → banner/ 配下に banner_A.png 等を出力
フレーズは COPIES を編集して差し替える。
"""
import math
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
W, Hh = 1320, 420
RED, CREAM, WHITE = (214, 68, 60), (253, 246, 244), (255, 255, 255)
FONT = "C:/Windows/Fonts/NotoSansJP-VF.ttf"
FALLBACK = "C:/Windows/Fonts/YuGothB.ttc"

# 上段 / 左の大見出し / 右の小見出し / 右の大見出し / 下段 / 角のCTA
COPIES = {
    "A": ("日銀の企業物価指数40年分で実証", "値上げの先読み", "無料で", "今すぐ使える",
          "原材料が上がると、自分の調達品は何ヶ月後に何％上がるか", "今すぐ\nCHECK"),
    "B": ("原材料高、次は何が上がる？", "何ヶ月後に何％", "調達の", "先読みツール",
          "原材料の値上がりが、自分の調達品に届く時期と幅がわかる", "今すぐ\nCHECK"),
    "C": ("サプライヤーの「原材料高騰」は本当か", "値上げ要請の前に", "根拠は", "データで",
          "過去40年の実績から、転嫁率と時期を確認できる", "無料\nCHECK"),
    "D": ("調達・購買人材のための無料ツール", "先に知る調達。", "差がつくのは", "情報の早さ",
          "いま上がっている原材料と、これから上がる調達品が一目でわかる", "今すぐ\nCHECK"),
    "E": ("日本銀行の統計×40年分の実績", "値上げ交渉の武器", "業界平均の", "転嫁率を提示",
          "「原油10%上昇→ナフサは3ヶ月後に約24%」まで具体的に", "今すぐ\nCHECK"),
}


def font(size, weight=900):
    try:
        f = ImageFont.truetype(FONT, size)
        try:
            f.set_variation_by_axes([weight])
        except Exception:
            pass
        return f
    except Exception:
        return ImageFont.truetype(FALLBACK, size)


def fit(draw, text, max_w, start, weight=900, min_size=24):
    """幅に収まる最大フォントサイズを探す"""
    size = start
    while size > min_size:
        f = font(size, weight)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 2
    return font(min_size, weight)


def make(key, top, big, r_small, r_big, bottom, cta, out):
    img = Image.new("RGB", (W, Hh), RED)
    d = ImageDraw.Draw(img)
    # 内側のクリーム地
    m = 38
    d.rectangle([m, m, W - m, Hh - m], fill=CREAM)

    # 上段（＼ … ／）
    f_top = fit(d, top, 900, 38, 700)
    tw = d.textlength(top, font=f_top)
    cx = W / 2
    d.text((cx - tw / 2, 62), top, font=f_top, fill=RED)
    f_sl = font(40, 500)
    d.text((cx - tw / 2 - 46, 58), "＼", font=f_sl, fill=RED)
    d.text((cx + tw / 2 + 6, 58), "／", font=f_sl, fill=RED)

    # 左の大見出し（右側ブロックの幅を確保して自動縮小）
    right_w = 470
    left_x = 110
    avail = W - m - right_w - left_x - 120
    f_big = fit(d, big, avail, 150, 900, 60)
    bw = d.textlength(big, font=f_big)
    bbox = d.textbbox((0, 0), big, font=f_big)
    bh = bbox[3] - bbox[1]
    by = 212 - bh / 2 - bbox[1]
    d.text((left_x, by), big, font=f_big, fill=RED)

    # ▶ の丸
    ccx = left_x + bw + 60
    d.ellipse([ccx - 34, 212 - 34, ccx + 34, 212 + 34], outline=RED, width=5)
    d.polygon([(ccx - 10, 212 - 16), (ccx - 10, 212 + 16), (ccx + 16, 212)], fill=RED)

    # 右の小見出し＋大見出し
    rx = ccx + 70
    rw = W - m - rx - 175
    f_rs = fit(d, r_small, rw, 44, 700)
    f_rb = fit(d, r_big, rw, 88, 900)
    rs_w = d.textlength(r_small, font=f_rs)
    rb_w = d.textlength(r_big, font=f_rb)
    rcx = rx + rw / 2
    d.text((rcx - rs_w / 2, 122), r_small, font=f_rs, fill=RED)
    d.text((rcx - rb_w / 2, 178), r_big, font=f_rb, fill=RED)

    # 下段
    f_bt = fit(d, bottom, 1000, 36, 700)
    btw = d.textlength(bottom, font=f_bt)
    d.text((cx - btw / 2 - 80, 312), bottom, font=f_bt, fill=RED)

    # 右下の扇形CTA
    r = 150
    d.pieslice([W - m - r, Hh - m - r, W - m + r, Hh - m + r], 180, 270, fill=RED)
    # 斜めの白文字
    f_c = font(27, 900)
    lines = cta.split("\n")
    txt = Image.new("RGBA", (220, 80), (0, 0, 0, 0))
    td = ImageDraw.Draw(txt)
    for i, ln in enumerate(lines):
        lw = td.textlength(ln, font=f_c)
        td.text((110 - lw / 2, 4 + i * 36), ln, font=f_c, fill=WHITE)
    txt = txt.rotate(45, expand=True, resample=Image.BICUBIC)
    ccx2, ccy2 = W - m - 66, Hh - m - 66   # 扇形の中ほど
    img.paste(txt, (int(ccx2 - txt.width / 2), int(ccy2 - txt.height / 2)), txt)

    img.save(out)
    print("saved", out)


if __name__ == "__main__":
    for k, v in COPIES.items():
        make(k, *v, out=os.path.join(HERE, f"banner_{k}.png"))
