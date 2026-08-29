# -*- coding: utf-8 -*-
"""
全日本トラック協会・日本貨物運送協同組合連合会「WebKIT成約運賃指数」を取得して
data/webkit.json に書き出す（毎月更新）。

- 一覧ページ https://jta.or.jp/member/keiei/kit_release.html の最新PDFを取得
  （URLは https://jta.or.jp/pdf/kit_release/YYYYMM.pdf の規則）
- 最新PDFの2ページ目に平成22年4月（2010年4月）からの月次全履歴表があるため、
  1枚のPDFで全期間を再構築できる
- 指数はトラックのスポット（求荷求車）成約運賃。2010年4月＝100
"""
import io
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
UA = {"User-Agent": "Mozilla/5.0 (compatible; procurement-cost-site)"}
LIST_URL = "https://jta.or.jp/member/keiei/kit_release.html"


def era_to_start_year(label):
    """'平成２２年度'/'令和３年度'/'令和元年度' → 年度開始年（西暦）"""
    t = unicodedata.normalize("NFKC", label).replace("年度", "").strip()
    m = re.match(r"^(平成|令和)(元|\d+)$", t)
    if not m:
        return None
    n = 1 if m.group(2) == "元" else int(m.group(2))
    return (1988 if m.group(1) == "平成" else 2018) + n


def main():
    import pdfplumber
    r = requests.get(LIST_URL, timeout=120, headers=UA)
    r.encoding = r.apparent_encoding
    pdfs = re.findall(r'href="(https?://jta\.or\.jp/pdf/kit_release/(\d{6})\.pdf)"', r.text)
    if not pdfs:
        sys.exit("ERROR: WebKITの一覧ページからPDFが見つかりません")
    url, ym = max(pdfs, key=lambda x: x[1])
    pr = requests.get(url, timeout=300, headers=UA)
    pr.raise_for_status()
    pdf = pdfplumber.open(io.BytesIO(pr.content))

    series = {}
    for page in pdf.pages:
        txt = page.extract_text() or ""
        if "成約運賃指数（月別）" not in txt:
            continue
        for table in page.extract_tables():
            for row in table:
                cells = [unicodedata.normalize("NFKC", str(c)).strip() if c else "" for c in row]
                y0 = era_to_start_year(cells[0]) if cells else None
                if y0 is None or len(cells) < 13:
                    continue
                for k, mth in enumerate([4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]):
                    v = cells[1 + k].replace(",", "")
                    if re.fullmatch(r"\d+(\.\d+)?", v):
                        yy = y0 if mth >= 4 else y0 + 1
                        series[yy * 100 + mth] = float(v)
    months = sorted(series)
    if len(months) < 100:
        sys.exit(f"ERROR: WebKITの履歴が少なすぎます（{len(months)}ヶ月）様式変更の可能性")
    out = {
        "updated": datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d"),
        "source": "全日本トラック協会・日本貨物運送協同組合連合会「求荷求車情報ネットワーク（WebKIT）成約運賃指数」",
        "source_page": "https://jta.or.jp/member/keiei/kit_release.html",
        "pdf": url,
        "base": "2010年4月＝100",
        "months": months,
        "vals": [series[m] for m in months],
    }
    with open(os.path.join(DATA, "webkit.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"webkit.json: {months[0]}〜{months[-1]}（{len(months)}ヶ月）最新値 {series[months[-1]]}")


if __name__ == "__main__":
    main()
