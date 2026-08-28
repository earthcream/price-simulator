# -*- coding: utf-8 -*-
"""
年1回更新の労務費データを取得して data/labor.json に書き出す。

1) 賃金構造基本統計調査（厚労省・e-Stat API）
   - 一般_職種（小分類）DB（statsDataId=0003426315）
   - 職種145種 × 年（2020年〜）、企業規模計・男女計
   - きまって支給する現金給与額（月額・千円）と年間賞与その他特別給与額（千円）
   - e-Stat の appId は環境変数 ESTAT_APP_ID または .estat_appid ファイルから読む

2) 公共工事設計労務単価（国交省・報道発表PDF）
   - 47都道府県 × 51職種の日額単価。毎年2月中旬に翌3月適用分が公表される
   - PDFの様式が変わると失敗するので、失敗時はGitHub Actionsの通知で手動対応する
   - 新年度は ROMU_PDF を更新する（報道発表ページのPDF URLと表のページ番号）

使い方: python scripts/fetch_annual_labor.py
"""
import json
import os
import re
import sys

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
RAW = os.path.join(ROOT, "raw")

WAGE_TABLE = "0003426315"   # 賃金構造基本統計 一般_職種（小分類）DB

# 公共工事設計労務単価：年度ごとに更新する設定
ROMU_PDF = {
    "label": "令和8年3月から適用",
    "year": 2026,
    "url": "https://www.mlit.go.jp/report/press/content/001981942.pdf",
    "pages": [7, 8, 9, 10, 11],   # 0始まりのページ番号（単価表のページ）
}
# 全国全職種平均（加重平均）の推移。報道発表資料2より（適用年ベース）
ROMU_NATIONAL_AVG = {
    2012: 13072, 2013: 15175, 2014: 16190, 2015: 16678, 2016: 17704,
    2017: 18078, 2018: 18632, 2019: 19392, 2020: 20214, 2021: 20409,
    2022: 21084, 2023: 22227, 2024: 23600, 2025: 24852, 2026: 25834,
}


def app_id():
    v = os.environ.get("ESTAT_APP_ID", "").strip()
    if v:
        return v
    p = os.path.join(ROOT, ".estat_appid")
    if os.path.exists(p):
        return open(p).read().strip()
    sys.exit("ERROR: e-StatのappIdがありません（環境変数 ESTAT_APP_ID か .estat_appid）")


def fetch_wage_structure():
    """賃金構造基本統計: {years:[...], occupations:[{code,name,kimatte:[千円], bonus:[千円], n:[人]}]}"""
    APP = app_id()
    out = {}
    # 表章項目コードは年代で分かれている（08/40=きまって支給、12/44=年間賞与、13/45=労働者数）
    FIELD = {"08": "kim", "40": "kim", "12": "bon", "44": "bon", "13": "num", "45": "num"}
    for tab in ["08", "40", "12", "44", "13", "45"]:
        r = requests.get("https://api.e-stat.go.jp/rest/3.0/app/json/getStatsData",
                         params={"appId": APP, "statsDataId": WAGE_TABLE, "cdTab": tab,
                                 "cdCat01": "01", "cdCat02": "01", "limit": 100000}, timeout=300)
        r.raise_for_status()
        sd = r.json()["GET_STATS_DATA"]["STATISTICAL_DATA"]
        vals = sd["DATA_INF"]["VALUE"]
        if isinstance(vals, dict):
            vals = [vals]
        for v in vals:
            year = int(str(v["@time"])[:4])
            occ = v["@cat03"]
            try:
                out.setdefault(occ, {}).setdefault(FIELD[tab], {})[year] = float(v["$"])
            except ValueError:
                pass
        # 職種コード→名前
        if tab == "08":
            cls = sd["CLASS_INF"]["CLASS_OBJ"]
            names = {}
            for o in cls:
                if o["@id"] == "cat03":
                    cl = o["CLASS"]
                    if isinstance(cl, dict):
                        cl = [cl]
                    names = {c["@code"]: c["@name"] for c in cl}
    years = sorted({y for d in out.values() for t in d.values() for y in t})
    occs = []
    for code, d in out.items():
        if code not in names or "kim" not in d:
            continue
        occs.append({
            "code": code, "name": names[code],
            "kimatte": [d.get("kim", {}).get(y) for y in years],
            "bonus": [d.get("bon", {}).get(y) for y in years],
            "n": [d.get("num", {}).get(y) for y in years],
        })
    occs.sort(key=lambda o: o["code"])
    if len(occs) < 100 or len(years) < 3:
        sys.exit(f"ERROR: 賃金構造の取得結果が不足（職種{len(occs)}・年{len(years)}）")
    print(f"賃金構造: 職種{len(occs)} × 年{years}")
    return {"years": years, "occupations": occs,
            "note": "企業規模計（10人以上）・男女計。きまって支給する現金給与額は月額（千円）、年間賞与その他特別給与額は年額（千円）"}


def fetch_romu():
    """設計労務単価PDFをパース: {label, year, occupations:[...], prefs:[...], values:[[円|null]]}"""
    import pdfplumber
    os.makedirs(RAW, exist_ok=True)
    dest = os.path.join(RAW, f"romu_{ROMU_PDF['year']}.pdf")
    if not os.path.exists(dest):
        r = requests.get(ROMU_PDF["url"], timeout=300)
        r.raise_for_status()
        open(dest, "wb").write(r.content)
    pdf = pdfplumber.open(dest)
    occupations, prefs, cols = [], [], {}   # cols[occ_idx] = {pref: value}
    for pi in ROMU_PDF["pages"]:
        tables = pdf.pages[pi].extract_tables()
        if not tables:
            sys.exit(f"ERROR: 設計労務単価PDFのp{pi+1}に表がありません（様式変更の可能性）")
        t = tables[0]
        header = [str(c or "").replace("\n", "").strip() for c in t[0]]
        occ_names = header[2:]
        base = len(occupations)
        occupations += [o for o in occ_names if o]
        for row in t[1:]:
            cells = [str(c or "").replace("\n", "").strip() for c in row]
            m = re.match(r"^(\d{2})\s*(.+)$", cells[1]) if len(cells) > 1 else None
            if not m:
                continue
            pref = m.group(2).strip()
            if pref not in prefs:
                prefs.append(pref)
            for k, occ in enumerate(occ_names):
                if not occ:
                    continue
                raw = cells[2 + k].replace(",", "")
                val = int(raw) if raw.isdigit() else None
                cols.setdefault(base + k, {})[pref] = val
    values = [[cols.get(oi, {}).get(p) for oi in range(len(occupations))] for p in prefs]
    if len(prefs) != 47 or len(occupations) < 45:
        sys.exit(f"ERROR: 設計労務単価のパース結果が不正（都道府県{len(prefs)}・職種{len(occupations)}）")
    print(f"設計労務単価: {len(prefs)}都道府県 × {len(occupations)}職種（{ROMU_PDF['label']}）")
    return {"label": ROMU_PDF["label"], "year": ROMU_PDF["year"],
            "source_url": ROMU_PDF["url"],
            "occupations": occupations, "prefs": prefs, "values": values,
            "national_avg": ROMU_NATIONAL_AVG,
            "note": "1日8時間当たりの労務単価（円）。法定福利費相当額（本人負担分）を含む。空欄は当該県で単価が設定されていない職種"}


def main():
    out = {
        "wage_struct": fetch_wage_structure(),
        "romu": fetch_romu(),
    }
    with open(os.path.join(DATA, "labor.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print("labor.json:", os.path.getsize(os.path.join(DATA, "labor.json")) // 1024, "KB")


if __name__ == "__main__":
    main()
