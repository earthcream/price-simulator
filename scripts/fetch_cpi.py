# -*- coding: utf-8 -*-
"""
消費者物価指数（総務省・2020年基準・全国・品目別・月次）を e-Stat API から取得し、
  cpi/data.json            … ページ用データ（品目ごとの年×月マトリクス＋季節傾向）
  cpi/reports/YYYYMM.md    … 記事ネタ（今月・来月のお買い得／買い控え品目ランキング）
  cpi/reports/latest.md    … 上記の最新版のコピー
を書き出す。

- e-Stat の appId は環境変数 ESTAT_APP_ID または .estat_appid ファイルから読む
- 統計表: 0003427113「消費者物価指数（2020年基準）」 表章項目=指数, 地域=全国(00000)
- 季節傾向: 1〜12月が揃った各年について「年平均＝100」に換算し、月ごとに平均した乖離(%)
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "cpi")
REPORT_DIR = os.path.join(OUT_DIR, "reports")
API = "https://api.e-stat.go.jp/rest/3.0/app/json"
TABLE = "0003427113"
AREA = "00000"          # 全国
YEARS_BACK = 5          # 直近5年＋当年
JST = timezone(timedelta(hours=9))


def app_id():
    v = os.environ.get("ESTAT_APP_ID", "").strip()
    if v:
        return v
    p = os.path.join(ROOT, ".estat_appid")
    if os.path.exists(p):
        return open(p, encoding="utf-8").read().strip()
    sys.exit("ERROR: e-StatのappIdがありません（環境変数 ESTAT_APP_ID か .estat_appid）")


APP = None


def get(path, **params):
    params["appId"] = APP
    r = requests.get(f"{API}/{path}", params=params, timeout=300)
    r.raise_for_status()
    return r.json()


def fetch_items():
    """品目メタ情報 → [{code, name, level, parent}] （e-Statの並び順）"""
    m = get("getMetaInfo", statsDataId=TABLE)
    objs = m["GET_META_INFO"]["METADATA_INF"]["CLASS_INF"]["CLASS_OBJ"]
    cat = next(o for o in objs if o["@id"] == "cat01")
    cls = cat["CLASS"] if isinstance(cat["CLASS"], list) else [cat["CLASS"]]
    items = []
    for c in cls:
        name = re.sub(r"^\d{4}\s*", "", c["@name"]).strip()
        items.append({
            "code": c["@code"],
            "name": name,
            "level": int(c.get("@level") or 0),
            "parent": c.get("@parentCode", ""),
        })
    return items


def fetch_values(time_from):
    """{code: {yyyymm(int): float}}"""
    out = {}
    start = 1
    while True:
        d = get("getStatsData", statsDataId=TABLE, cdArea=AREA, cdTab="1",
                cdTimeFrom=time_from, startPosition=start, limit=100000, metaGetFlg="N")
        sd = d["GET_STATS_DATA"]["STATISTICAL_DATA"]
        vals = sd["DATA_INF"].get("VALUE", [])
        if isinstance(vals, dict):
            vals = [vals]
        for v in vals:
            t = v["@time"]              # 月次は YYYY00MMMM（例 2026000707）
            if len(t) != 10 or t[6:8] != t[8:10] or t[6:8] == "00":
                continue
            try:
                val = float(v["$"])
            except (KeyError, ValueError):
                continue
            out.setdefault(v["@cat01"], {})[int(t[:4]) * 100 + int(t[6:8])] = val
        nk = sd["RESULT_INF"].get("NEXT_KEY")
        if not nk:
            break
        start = int(nk)
    return out


def seasonal_profile(series, years):
    """年平均=100換算の月別平均乖離(%)。12ヶ月揃った年のみ。 → ([12個 or None], 使った年数)"""
    acc = [[] for _ in range(12)]
    used = 0
    for y in years:
        vals = [series.get(y * 100 + m) for m in range(1, 13)]
        if any(v is None for v in vals):
            continue
        mean = sum(vals) / 12
        if mean <= 0:
            continue
        for i, v in enumerate(vals):
            acc[i].append(v / mean * 100 - 100)
        used += 1
    if used == 0:
        return None, 0
    return [round(sum(a) / len(a), 2) for a in acc], used


def main():
    global APP
    APP = app_id()
    now = datetime.now(JST)
    items = fetch_items()
    parents = {it["parent"] for it in items if it["parent"]}
    first_year = now.year - YEARS_BACK
    values = fetch_values(f"{first_year}000101")

    latest = max(m for s in values.values() for m in s)
    ly, lm = divmod(latest, 100)
    years = list(range(first_year, ly + 1))

    out_items = []
    for it in items:
        s = values.get(it["code"])
        if not s:
            continue
        matrix = {}
        for y in years:
            row = [s.get(y * 100 + m) for m in range(1, 13)]
            if any(v is not None for v in row):
                matrix[str(y)] = row
        prof, used = seasonal_profile(s, years)
        prev = s.get((ly - 1) * 100 + lm)
        yoy = round((s[latest] / prev - 1) * 100, 1) if (latest in s and prev) else None
        mom_prev = s.get((ly * 100 + lm - 1) if lm > 1 else ((ly - 1) * 100 + 12))
        mom = round((s[latest] / mom_prev - 1) * 100, 1) if (latest in s and mom_prev) else None
        out_items.append({
            "code": it["code"],
            "name": it["name"],
            "level": it["level"],
            "parent": it["parent"],
            "leaf": it["code"] not in parents,
            "years": matrix,
            "season": prof,
            "season_years": used,
            "latest": s.get(latest),
            "yoy": yoy,
            "mom": mom,
        })

    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)
    data = {
        "updated": now.strftime("%Y-%m-%d %H:%M"),
        "source": "総務省統計局「消費者物価指数（2020年基準）」全国・品目別・月次（e-Stat 統計表ID 0003427113）",
        "latest_month": latest,
        "years": years,
        "items": out_items,
    }
    with open(os.path.join(OUT_DIR, "data.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    md = build_report(data, now)
    with open(os.path.join(REPORT_DIR, f"{latest}.md"), "w", encoding="utf-8") as f:
        f.write(md)
    with open(os.path.join(REPORT_DIR, "latest.md"), "w", encoding="utf-8") as f:
        f.write(md)
    print(f"品目 {len(out_items)}（うち品目レベル {sum(1 for i in out_items if i['leaf'])}） "
          f"最新月 {ly}年{lm}月 → cpi/data.json, cpi/reports/{latest}.md")


# ---------------------------------------------------------------- 記事ネタ
def build_report(data, now):
    ly, lm = divmod(data["latest_month"], 100)
    leaves = [i for i in data["items"] if i["leaf"] and i["season"] and i["season_years"] >= 3]

    def month_after(y, m, k):
        m2 = m + k
        return y + (m2 - 1) // 12, (m2 - 1) % 12 + 1

    lines = []
    lines.append(f"# 消費者物価指数からみた「買い時」「買い控え」品目（データ最新月：{ly}年{lm}月）")
    lines.append("")
    lines.append(f"- 出典：{data['source']}")
    lines.append(f"- 生成日時：{now.strftime('%Y-%m-%d %H:%M')}（JST）")
    lines.append(f"- 季節傾向：{data['years'][0]}年以降で1〜12月が揃った年を対象に、各年の年平均＝100として月別の乖離を平均したもの")
    lines.append(f"- 対象：品目レベル {len(leaves)}品目（季節傾向は3年分以上ある品目のみ）")
    lines.append("")

    # 対象月：データ最新月の翌月（＝記事公開時点の「今月」）と、その翌月（「来月」）
    targets = [("今月", month_after(ly, lm, 1)), ("来月", month_after(ly, lm, 2))]
    for label, (ty, tm) in targets:
        idx = tm - 1
        cheap = sorted(leaves, key=lambda i: i["season"][idx])[:15]
        dear = sorted(leaves, key=lambda i: -i["season"][idx])[:15]
        lines.append(f"## {label}（{ty}年{tm}月）に安くなりやすい品目 TOP15")
        lines.append("")
        lines.append("| 順位 | 品目 | 年平均比 | 年内で最安の月 | 直近の前年同月比 |")
        lines.append("|---|---|---|---|---|")
        for n, i in enumerate(cheap, 1):
            lines.append(f"| {n} | {i['name']} | {i['season'][idx]:+.1f}% | {_min_month(i)} | {_pct(i['yoy'])} |")
        lines.append("")
        lines.append(f"## {label}（{ty}年{tm}月）に高くなりやすい品目 TOP15")
        lines.append("")
        lines.append("| 順位 | 品目 | 年平均比 | 年内で最安の月 | 直近の前年同月比 |")
        lines.append("|---|---|---|---|---|")
        for n, i in enumerate(dear, 1):
            lines.append(f"| {n} | {i['name']} | {i['season'][idx]:+.1f}% | {_min_month(i)} | {_pct(i['yoy'])} |")
        lines.append("")

    # 足元の動き
    yo = [i for i in leaves if i["yoy"] is not None]
    up = sorted(yo, key=lambda i: -i["yoy"])[:15]
    dn = sorted(yo, key=lambda i: i["yoy"])[:15]
    lines.append(f"## 足元で値上がりが大きい品目（{ly}年{lm}月・前年同月比）TOP15")
    lines.append("")
    lines.append("| 順位 | 品目 | 前年同月比 | 前月比 |")
    lines.append("|---|---|---|---|")
    for n, i in enumerate(up, 1):
        lines.append(f"| {n} | {i['name']} | {_pct(i['yoy'])} | {_pct(i['mom'])} |")
    lines.append("")
    lines.append(f"## 足元で値下がりが大きい品目（{ly}年{lm}月・前年同月比）TOP15")
    lines.append("")
    lines.append("| 順位 | 品目 | 前年同月比 | 前月比 |")
    lines.append("|---|---|---|---|")
    for n, i in enumerate(dn, 1):
        lines.append(f"| {n} | {i['name']} | {_pct(i['yoy'])} | {_pct(i['mom'])} |")
    lines.append("")

    # 季節の振れ幅が大きい品目（記事の「時期で買え」ネタ）
    amp = sorted(leaves, key=lambda i: -(max(i["season"]) - min(i["season"])))[:20]
    lines.append("## 季節による価格差が大きい品目 TOP20（買う時期で差が出る品目）")
    lines.append("")
    lines.append("| 順位 | 品目 | 最安月 | 最高月 | 差（年平均比の幅） |")
    lines.append("|---|---|---|---|---|")
    for n, i in enumerate(amp, 1):
        mn = i["season"].index(min(i["season"])) + 1
        mx = i["season"].index(max(i["season"])) + 1
        lines.append(f"| {n} | {i['name']} | {mn}月（{min(i['season']):+.1f}%） | {mx}月（{max(i['season']):+.1f}%） | {max(i['season'])-min(i['season']):.1f}pt |")
    lines.append("")
    lines.append("※ 年平均比は季節的な傾向であり、当年の実際の価格を保証するものではない。")
    lines.append("※ グラフ・全品目の傾向は https://simulator.future-procurement.com/cpi/ で確認できる。")
    return "\n".join(lines) + "\n"


def _min_month(i):
    s = i["season"]
    return f"{s.index(min(s)) + 1}月"


def _pct(v):
    return "―" if v is None else f"{v:+.1f}%"


if __name__ == "__main__":
    main()
