# -*- coding: utf-8 -*-
"""
フロントエンドの「値動き検索」用に、品目レベルの指数値を data/prices.json に書き出す。

対象: 国内企業物価指数（消費税を除く）515品目 ＋ 輸入物価指数（円ベース）210品目
      ＋ 企業向けサービス価格指数（物流運賃・労働者派遣等）146品目
期間: 直近 YEARS 年分（ファイルサイズを抑えるため。全期間の推定は estimate.py が担う）

形式:
  {"months":[YYYYMM,...], "items":{code:{"n":名前,"k":"国内"|"輸入","p":階層パス,"v":[値,...]}}}
  値が無い月は null
"""
import gzip
import json
import os

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
YEARS = 15


def main():
    items = pd.read_csv(os.path.join(DATA, "items.csv"), encoding="utf-8-sig")
    with gzip.open(os.path.join(DATA, "series_long.csv.gz"), "rt", encoding="utf-8") as f:
        s = pd.read_csv(f)

    it = items[(items["level"] == "品目") & (items["kind"].isin(["domestic", "import_yen", "service"]))]
    codes = set(it["code"])
    s = s[s["code"].isin(codes)]

    latest = int(s["month"].max())
    start = (latest // 100 - YEARS) * 100 + latest % 100
    s = s[s["month"] >= start]
    months = sorted(s["month"].unique().tolist())
    wide = s.pivot(index="month", columns="code", values="value").reindex(months)

    out = {"months": [int(m) for m in months], "items": {}}
    for _, r in it.iterrows():
        if r["code"] not in wide:
            continue
        vals = [None if pd.isna(v) else round(float(v), 1) for v in wide[r["code"]].tolist()]
        out["items"][r["code"]] = {
            "n": r["name"],
            "k": {"domestic": "国内", "import_yen": "輸入", "service": "サービス"}[r["kind"]],
            "p": r["group_path"] if isinstance(r["group_path"], str) else "",
            "v": vals,
        }
    path = os.path.join(DATA, "prices.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"prices.json: {len(out['items'])}品目 × {len(months)}ヶ月, {os.path.getsize(path)/1e6:.2f} MB")


if __name__ == "__main__":
    main()
