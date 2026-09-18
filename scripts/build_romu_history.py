# -*- coding: utf-8 -*-
"""
公共工事設計労務単価の職種別・全国単純平均の年推移を作り data/romu_history.json に書き出す。

- 各年の国交省報道発表ページから単価表入りPDFを取得し、47都道府県×約50職種をパース
- 職種ごとに全国単純平均（単価が設定されている県の平均）を計算
- 新年度が公表されたら YEAR_PAGES に報道発表ページのURLを1行追加する
  （yearly-update.yml から毎年自動実行。表の様式が変わった年はスキップして警告）
"""
import io
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
RAW = os.path.join(ROOT, "raw")
UA = {"User-Agent": "Mozilla/5.0 (compatible; procurement-cost-site)"}

# 適用年 → 報道発表ページ（毎年ここに1行追加する）
YEAR_PAGES = {
    2020: "https://www.mlit.go.jp/report/press/totikensangyo14_hh_000893.html",
    2021: "https://www.mlit.go.jp/report/press/tochi_fudousan_kensetsugyo14_hh_000001_00026.html",
    2022: "https://www.mlit.go.jp/report/press/tochi_fudousan_kensetsugyo14_hh_000001_00077.html",
    2023: "https://www.mlit.go.jp/report/press/tochi_fudousan_kensetsugyo14_hh_000001_00130.html",
    2024: "https://www.mlit.go.jp/report/press/tochi_fudousan_kensetsugyo14_hh_000001_00204.html",
    2025: "https://www.mlit.go.jp/report/press/tochi_fudousan_kensetsugyo14_hh_000001_00261.html",
    2026: "https://www.mlit.go.jp/report/press/tochi_fudousan_kensetsugyo14_hh_000001_00337.html",
}


def parse_year(year, page_url):
    """1年分をパースして {職種名: 全国単純平均} を返す。表が見つからなければ None"""
    import pdfplumber
    r = requests.get(page_url, timeout=120, headers=UA)
    r.encoding = r.apparent_encoding
    m = re.search(r'href="((?:/report/press/content|/common)/\d+\.pdf)"', r.text)
    if not m:
        print(f"  {year}: PDFリンクなし SKIP")
        return None
    dest = os.path.join(RAW, f"romu_press_{year}.pdf")
    if not os.path.exists(dest):
        pr = requests.get("https://www.mlit.go.jp" + m.group(1), timeout=300, headers=UA)
        pr.raise_for_status()
        open(dest, "wb").write(pr.content)
    pdf = pdfplumber.open(dest)

    sums, counts = {}, {}
    n_pref_rows = 0
    for page in pdf.pages:
        for t in page.extract_tables():
            if not t or len(t) < 20:
                continue
            header = [str(c or "").replace("\n", "").strip() for c in t[0]]
            if "都道府県名" not in "".join(header[:3]):
                continue
            occ_names = header[2:]
            for row in t[1:]:
                cells = [str(c or "").replace("\n", "").strip() for c in row]
                if len(cells) < 3 or not re.match(r"^\d{2}\s*.+$", cells[1] or ""):
                    continue
                n_pref_rows += 1
                for k, occ in enumerate(occ_names):
                    if not occ or 2 + k >= len(cells):
                        continue
                    raw = cells[2 + k].replace(",", "")
                    if raw.isdigit():
                        sums[occ] = sums.get(occ, 0) + int(raw)
                        counts[occ] = counts.get(occ, 0) + 1
    if len(sums) < 40 or n_pref_rows < 40:
        print(f"  {year}: 表を検出できず（職種{len(sums)}・行{n_pref_rows}）SKIP")
        return None
    avgs = {occ: round(sums[occ] / counts[occ]) for occ in sums}
    print(f"  {year}: 職種{len(avgs)} OK")
    return avgs


def main():
    os.makedirs(RAW, exist_ok=True)
    years, table = [], {}
    for year in sorted(YEAR_PAGES):
        avgs = parse_year(year, YEAR_PAGES[year])
        if avgs is None:
            continue
        years.append(year)
        for occ, v in avgs.items():
            table.setdefault(occ, {})[year] = v
    if len(years) < 3:
        sys.exit("ERROR: 取得できた年が少なすぎます")
    # 3時点以上ある職種だけ残す
    table = {occ: d for occ, d in table.items() if len(d) >= 3}
    out = {
        "updated": datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d"),
        "source": "国土交通省「公共工事設計労務単価」各年の報道発表資料から、都道府県単純平均を算出",
        "note": "各職種の全国単純平均（単価が設定されている都道府県の平均、1日8時間当たり・円）。適用年ベース",
        "years": years,
        "occupations": table,
    }
    with open(os.path.join(DATA, "romu_history.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"romu_history.json: 職種{len(table)} × 年{years}")


if __name__ == "__main__":
    main()
