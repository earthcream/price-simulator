# -*- coding: utf-8 -*-
"""
賃金データ（厚生労働省「毎月勤労統計調査」）を取得して data/wages.json に書き出す。

取得元は政府の「統計ダッシュボード」WebAPI（APIキー不要・毎月更新）。
https://dashboard.e-stat.go.jp/

注: e-Stat のデータベース版毎月勤労統計は2015年で更新が止まっているため使わない。
    産業別・職種別の賃金は年次統計（賃金構造基本統計・公共工事設計労務単価）で補完する。

出力形式:
  {"updated": "...", "source": "...", "months": [YYYYMM, ...],
   "series": {key: {"label": 表示名, "unit": "円"|"指数", "vals": [値|null, ...]}}}
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
API = "https://dashboard.e-stat.go.jp/api/1.0/Json/getData"

# 指標コード（統計ダッシュボード）
INDICATORS = {
    "total":    ("0302020000000010000", "現金給与総額（就業形態計）", "円"),
    "regular":  ("0302020000000110010", "現金給与総額（一般労働者）", "円"),
    "parttime": ("0302020000000110020", "現金給与総額（パートタイム労働者）", "円"),
    "nominal":  ("0302030202010090010", "名目賃金指数（現金給与総額、2020年＝100）", "指数"),
    "real":     ("0302030201010090010", "実質賃金指数（現金給与総額、2020年＝100）", "指数"),
}


def fetch_indicator(code):
    """月次値 {yyyymm(int): float} を返す"""
    r = requests.get(API, params={"Lang": "JP", "IndicatorCode": code}, timeout=120)
    r.raise_for_status()
    data = r.json()["GET_STATS"]["STATISTICAL_DATA"]["DATA_INF"]["DATA_OBJ"]
    if isinstance(data, dict):
        data = [data]
    out = {}
    for obj in data:
        vals = obj["VALUE"]
        if isinstance(vals, dict):
            vals = [vals]
        for v in vals:
            t = str(v.get("@time", ""))
            # 月次のみ（YYYYMM00形式）。年次・年度（2025CY00/2025FY00）は除外
            if v.get("@cycle") == "1" and len(t) == 8 and t[4:6].isdigit() and t[4:6] != "00":
                try:
                    out[int(t[:6])] = float(v["$"])
                except (KeyError, ValueError):
                    pass
    return out


def main():
    series_raw = {}
    for key, (code, label, unit) in INDICATORS.items():
        vals = fetch_indicator(code)
        if len(vals) < 60:
            sys.exit(f"ERROR: {label} の取得件数が少なすぎます ({len(vals)}件)")
        series_raw[key] = vals
        print(f"  {label}: {len(vals)}ヶ月 ({min(vals)}〜{max(vals)})")

    months = sorted(set().union(*[v.keys() for v in series_raw.values()]))
    out = {
        "updated": datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d"),
        "source": "厚生労働省「毎月勤労統計調査」（事業所規模5人以上・調査産業計）。統計ダッシュボード（総務省統計局）WebAPI経由",
        "months": months,
        "series": {},
    }
    for key, (code, label, unit) in INDICATORS.items():
        out["series"][key] = {
            "label": label, "unit": unit,
            "vals": [series_raw[key].get(m) for m in months],
        }
    with open(os.path.join(DATA, "wages.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"wages.json: {len(months)}ヶ月 ({months[0]}〜{months[-1]})")


if __name__ == "__main__":
    main()
