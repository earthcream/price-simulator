# -*- coding: utf-8 -*-
"""
日本銀行「時系列統計データ検索サイト」から企業物価指数データを取得する。

取得するもの:
  1. cgpi_m_jp.zip     : 企業物価指数（2020年基準）月次
                         国内(税込22/税抜12)・輸出(円24/契約通貨23)・輸入(円26/契約通貨25)
                         2020年1月〜最新月
  2. cgpilink2.csv     : 2020年基準接続指数（品目レベル）1980年1月〜2019年12月
  2b. sppi_m_jp.zip / sppilink.csv : 企業向けサービス価格指数（2020年基準）と接続指数。
                         物流運賃（道路貨物・外航/内航海運・航空貨物）、倉庫、労働者派遣等の
                         サービス価格。1985年1月〜最新月
                         コード体系が2020年基準と共通なので、そのまま縦に接続できる
  3. cgpilink1.csv     : 同・類別レベル 1960年〜（参考・保存のみ）
  4. fm08_m_1.html     : 外国為替相場。FM08'FXERM07 = 東京市場ドル・円スポット
                         月中平均（1973年1月〜）をコントロール変数として使う

出力（data/ 配下）:
  - series_long.csv.gz : code, month(YYYYMM), value の縦持ちデータ（接続済み）
  - items.csv          : code, kind, level, depth, name, parent_names
  - fx.csv             : month, usdjpy
  - meta.json          : 最新月・系列数などのメタ情報

使い方:
  python scripts/fetch.py
"""
import gzip
import io
import json
import os
import re
import sys
import zipfile

import pandas as pd
import requests

BASE = "https://www.stat-search.boj.or.jp/info/"
FX_URL = "https://www.stat-search.boj.or.jp/ssi/mtshtml/fm08_m_1.html"
FX_CODE = "FM08'FXERM07"  # 東京市場 ドル・円 スポット 17時点/月中平均

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "raw")
DATA = os.path.join(ROOT, "data")

# 系列コードの2文字プレフィックス → 指数の種類
KIND_MAP = {
    "12": "domestic",         # 消費税を除く国内企業物価指数（推定にはこれを使う）
    "22": "domestic_tax",     # 国内企業物価指数（税込・表示用）
    "24": "export_yen",       # 輸出物価指数 円ベース
    "23": "export_contract",  # 輸出物価指数 契約通貨ベース
    "26": "import_yen",       # 輸入物価指数 円ベース
    "25": "import_contract",  # 輸入物価指数 契約通貨ベース
}


def download(session: requests.Session, url: str, dest: str) -> None:
    r = session.get(url, timeout=180)
    r.raise_for_status()
    with open(dest, "wb") as f:
        f.write(r.content)
    print(f"  downloaded {os.path.basename(dest)} ({len(r.content):,} bytes)")


def load_boj_wide(path_or_buf, encoding="cp932") -> pd.DataFrame:
    """日銀の横持ちCSV（1行=1系列、列=YYYYMM）を読む"""
    df = pd.read_csv(path_or_buf, encoding=encoding, index_col=False, dtype=str)
    cols = list(df.columns)
    df.columns = ["code", "stat", "name"] + cols[3:]
    return df


def parse_name(raw_name: str):
    """'品目/____大豆油' → (level='品目', depth=4, name='大豆油')"""
    raw_name = str(raw_name).strip()
    m = re.match(r"^\[.*\]\s*(.+)$", raw_name)  # '[国内企業物価指数] 総平均' 形式
    if m:
        return "総平均", 0, m.group(1).strip()
    if "/" in raw_name:
        level, rest = raw_name.split("/", 1)
        depth = len(rest) - len(rest.lstrip("_"))
        return level.strip(), depth, rest.lstrip("_").strip()
    return "総平均", 0, raw_name


def melt_long(df: pd.DataFrame) -> pd.DataFrame:
    """横持ち→縦持ち。値が空のセルは落とす"""
    month_cols = [c for c in df.columns if re.fullmatch(r"\d{6}", str(c))]
    long = df.melt(
        id_vars=["code"], value_vars=month_cols,
        var_name="month", value_name="value",
    )
    long["value"] = pd.to_numeric(long["value"], errors="coerce")
    long = long.dropna(subset=["value"])
    long["month"] = long["month"].astype(int)
    return long


def main():
    os.makedirs(RAW, exist_ok=True)
    os.makedirs(DATA, exist_ok=True)
    s = requests.Session()
    s.headers["User-Agent"] = "kakaku-hakyuu-simulator (data update script)"

    print("[1/4] 日銀サイトからファイルを取得")
    for fn in ["cgpi_m_jp.zip", "cgpilink1.csv", "cgpilink2.csv", "sppi_m_jp.zip", "sppilink.csv"]:
        download(s, BASE + fn, os.path.join(RAW, fn))
    download(s, FX_URL, os.path.join(RAW, "fm08_m_1.html"))

    print("[2/4] 現行系列（2020年基準）と接続指数（1980-2019）をパース")
    with zipfile.ZipFile(os.path.join(RAW, "cgpi_m_jp.zip")) as zf:
        with zf.open("cgpi_m_jp.csv") as f:
            cur = load_boj_wide(io.TextIOWrapper(f, encoding="cp932"), encoding=None)
    link = load_boj_wide(os.path.join(RAW, "cgpilink2.csv"))

    # 対象プレフィックスの系列だけ残す
    def keep(df):
        pref = df["code"].str.extract(r"^PRCG20_(\d\d)")[0]
        df = df.assign(kind=pref.map(KIND_MAP))
        return df.dropna(subset=["kind"])

    cur, link = keep(cur), keep(link)

    # --- 企業向けサービス価格指数（SPPI）: 本系列（プレフィックス52）を追加 ---
    with zipfile.ZipFile(os.path.join(RAW, "sppi_m_jp.zip")) as zf:
        with zf.open("sppi_m_jp.csv") as f:
            scur = load_boj_wide(io.TextIOWrapper(f, encoding="cp932"), encoding=None)
    slink = load_boj_wide(os.path.join(RAW, "sppilink.csv"))

    def keep_sppi(df):
        df = df[df["code"].str.match(r"^PRCS20_52")].copy()
        df["kind"] = "service"
        return df

    scur, slink = keep_sppi(scur), keep_sppi(slink)
    cur = pd.concat([cur, scur], ignore_index=True)
    link = pd.concat([link, slink], ignore_index=True)

    # 品目マスタ（現行系列基準。名前・階層は現行ファイルから取る）
    parsed = cur["name"].map(parse_name)
    items = pd.DataFrame({
        "code": cur["code"],
        "kind": cur["kind"],
        "level": [p[0] for p in parsed],
        "depth": [p[1] for p in parsed],
        "name": [p[2] for p in parsed],
    })
    # 接続指数に存在するコード＝長期系列があるコード
    items["has_link"] = items["code"].isin(set(link["code"]))

    # 階層パス：ファイルは階層順に並んでいるので、直前に出た浅い階層が親
    items["group_path"] = ""
    for kind_val, g in items.groupby("kind", sort=False):
        stack = {}  # depth -> name
        paths = []
        for _, r in g.iterrows():
            d = r["depth"]
            stack[d] = r["name"]
            for k in [k for k in stack if k > d]:
                del stack[k]
            paths.append(">".join(stack[k] for k in sorted(stack) if k < d))
        items.loc[g.index, "group_path"] = paths

    print("[3/4] 縦持ちに変換して接続")
    cur_long = melt_long(cur)
    link_long = melt_long(link)
    # 接続指数は2019年12月まで、現行は2020年1月から（重複なし）
    link_long = link_long[link_long["month"] <= 201912]
    cur_long = cur_long[cur_long["month"] >= 202001]
    series = pd.concat([link_long, cur_long], ignore_index=True)
    series = series.sort_values(["code", "month"]).reset_index(drop=True)

    print("[4/4] ドル円レートをパース")
    with open(os.path.join(RAW, "fm08_m_1.html"), encoding="cp932", errors="replace") as f:
        html = f.read()
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)
    header_codes = None
    fx_records = []
    for row in rows:
        cells = [re.sub(r"<[^>]+>", "", c).strip()
                 for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.S)]
        if not cells:
            continue
        if cells[0] == "データコード":
            header_codes = cells
        elif header_codes and re.fullmatch(r"\d{4}/\d{2}", cells[0]):
            idx = header_codes.index(FX_CODE)
            val = cells[idx] if idx < len(cells) else "ND"
            if val not in ("ND", ""):
                fx_records.append({"month": int(cells[0].replace("/", "")),
                                   "usdjpy": float(val)})
    fx = pd.DataFrame(fx_records).sort_values("month")
    if len(fx) < 400:
        sys.exit(f"ERROR: ドル円レートの取得件数が少なすぎます ({len(fx)}件)")

    # ---- 出力 ----
    with gzip.open(os.path.join(DATA, "series_long.csv.gz"), "wt", encoding="utf-8", newline="") as f:
        series.to_csv(f, index=False)
    items.to_csv(os.path.join(DATA, "items.csv"), index=False, encoding="utf-8-sig")
    fx.to_csv(os.path.join(DATA, "fx.csv"), index=False, encoding="utf-8")

    n_item = items[items["level"] == "品目"].groupby("kind")["code"].count().to_dict()
    meta = {
        "source": "日本銀行「時系列統計データ検索サイト」(https://www.stat-search.boj.or.jp/)",
        "latest_month": int(series["month"].max()),
        "first_month": int(series["month"].min()),
        "n_series": int(series["code"].nunique()),
        "n_items_by_kind": n_item,
        "fx_range": [int(fx["month"].min()), int(fx["month"].max())],
    }
    with open(os.path.join(DATA, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print("完了:", json.dumps(meta, ensure_ascii=False))


if __name__ == "__main__":
    main()
