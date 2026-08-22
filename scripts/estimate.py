# -*- coding: utf-8 -*-
"""
価格波及のローカル・プロジェクション推定（Jordà 2005）。

対象: data/input_map.csv の全ペア（下流品目 y ← 上流候補 x）
モデル（h = 0..12 の各ホライズンで別々にOLS）:

  log y_{t+h} - log y_{t-1}
      = a_h
      + b_h * dlx_t                  ... 累積弾性値（係数の解釈: xが1%上がるとyがhヶ月後までに b_h %上がる）
      + Σ_{l=1..2} c_l * dly_{t-l}   ... 被説明変数の自ラグ
      + d1 * dlx_{t-1}               ... 説明変数のラグ
      + e1 * dlfx_t + e2 * dlfx_{t-1}   ... ドル円レート（対数階差）
      + f1 * dloil_t + f2 * dloil_{t-1} ... 原油価格（輸入物価・原油・契約通貨ベース、対数階差）
      + u_t

  標準誤差は Newey-West（ラグ = h+1）
  非対称性: dlx を正部分・負部分に分けた回帰も行い、上昇時・下降時の h=12 累積弾性値を出す

採用基準（これを満たさないペアは推定不能扱いで数値を出さない）:
  - 観測数 >= MIN_OBS
  - ピーク時点（|b_h| 最大の h）の p値 < 0.10
  - ピーク時点の弾性値が正（コスト波及として解釈可能）

出力: data/results.json
"""
import json
import os
import warnings
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import statsmodels.api as sm

warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

H = 12            # 最大ホライズン（月）
NLAG_Y = 2        # 自ラグ数
MIN_OBS = 120     # 最低観測数（月）
P_THRESH = 0.10   # 有意水準
OIL_CODE = "PRCG20_2500550010"   # 輸入物価指数・原油（契約通貨ベース）
ALERT_WINDOW = 3  # 予兆アラート: 直近何ヶ月の変化を見るか
ALERT_MIN_CHANGE = 0.02  # 直近変化がこの水準（対数、約2%）以上で候補
ALERT_Z = 1.5     # かつ過去分布に対するzスコアがこの水準以上


def month_index(m):
    """YYYYMM -> 連続月番号"""
    return (m // 100) * 12 + (m % 100 - 1)


def load_data():
    series = pd.read_csv(os.path.join(DATA, "series_long.csv.gz"))
    items = pd.read_csv(os.path.join(DATA, "items.csv"), encoding="utf-8-sig")
    fx = pd.read_csv(os.path.join(DATA, "fx.csv"))
    imap = pd.read_csv(os.path.join(DATA, "input_map.csv"), encoding="utf-8-sig")

    series["t"] = series["month"].map(month_index)
    wide = series.pivot(index="t", columns="code", values="value").sort_index()
    logw = np.log(wide)

    fx = fx.set_index(fx["month"].map(month_index))["usdjpy"].sort_index()
    dlfx = np.log(fx).diff()
    dloil = logw[OIL_CODE].diff() if OIL_CODE in logw else None

    t2month = dict(zip(series["t"], series["month"]))
    return logw, dlfx, dloil, items, imap, t2month


def run_lp(ly, lx, dlfx, dloil, control_oil=True):
    """1ペアのローカル・プロジェクション。dict か None（サンプル不足）を返す"""
    dly, dlx = ly.diff(), lx.diff()

    base = pd.DataFrame({
        "dlx": dlx,
        "dlx_l1": dlx.shift(1),
        "dly_l1": dly.shift(1),
        "dly_l2": dly.shift(2),
        "dlfx": dlfx, "dlfx_l1": dlfx.shift(1),
    })
    if control_oil and dloil is not None:
        base["dloil"] = dloil
        base["dloil_l1"] = dloil.shift(1)

    # 非対称項
    pos = dlx.clip(lower=0)
    neg = dlx.clip(upper=0)

    res = {"h": [], "beta": [], "se": [], "p": [],
           "beta_up": [], "beta_dn": [], "se_up": [], "se_dn": []}
    n_obs = None
    idx_used = None
    for h in range(H + 1):
        dep = ly.shift(-h) - ly.shift(1)      # log y_{t+h} - log y_{t-1}
        df = base.copy()
        df["dep"] = dep
        df = df.dropna()
        if len(df) < MIN_OBS:
            return None
        if n_obs is None:
            n_obs = len(df)
            idx_used = df.index
        X = sm.add_constant(df.drop(columns="dep"))
        model = sm.OLS(df["dep"], X).fit(cov_type="HAC", cov_kwds={"maxlags": h + 1})
        res["h"].append(h)
        res["beta"].append(model.params["dlx"])
        res["se"].append(model.bse["dlx"])
        res["p"].append(model.pvalues["dlx"])

        # 非対称: dlx を正負に分けて再推定
        df2 = df.drop(columns="dlx").copy()
        df2["dlx_up"] = pos.reindex(df.index)
        df2["dlx_dn"] = neg.reindex(df.index)
        X2 = sm.add_constant(df2.drop(columns="dep"))
        m2 = sm.OLS(df2["dep"], X2).fit(cov_type="HAC", cov_kwds={"maxlags": h + 1})
        res["beta_up"].append(m2.params["dlx_up"])
        res["beta_dn"].append(m2.params["dlx_dn"])
        res["se_up"].append(m2.bse["dlx_up"])
        res["se_dn"].append(m2.bse["dlx_dn"])

    res["n_obs"] = n_obs
    res["t_first"], res["t_last"] = int(idx_used.min()), int(idx_used.max())
    return res


def main():
    logw, dlfx, dloil, items, imap, t2month = load_data()
    code2name = dict(zip(items["code"], items["name"]))
    code2kind = dict(zip(items["code"], items["kind"]))
    dom_items = items[(items["level"] == "品目") & (items["kind"] == "domestic")]
    code2path = dict(zip(items["code"], items["group_path"]))

    latest_t = int(logw.index.max())
    results = {}
    n_pairs = n_sig = 0

    for tcode, grp in imap.groupby("対象品目コード", sort=False):
        tname = grp["対象品目名"].iloc[0]
        entry = {
            "name": tname,
            "path": code2path.get(tcode, ""),
            "drivers": [],
            "insufficient": [],   # サンプル不足・不採用の候補（表示用）
        }
        if tcode not in logw:
            results[tcode] = entry
            continue
        ly = logw[tcode]

        for _, row in grp.iterrows():
            ccode, cname, reason = row["候補品目コード"], row["候補品目名"], row["根拠"]
            n_pairs += 1
            if ccode not in logw:
                entry["insufficient"].append({"code": ccode, "name": cname, "why": "系列なし"})
                continue
            lx = logw[ccode]
            # ドライバー自身が原油の場合は原油コントロールを外す（完全共線を回避）
            ctrl_oil = (ccode != OIL_CODE)
            lp = run_lp(ly, lx, dlfx, dloil, control_oil=ctrl_oil)
            if lp is None:
                entry["insufficient"].append({"code": ccode, "name": cname, "why": "サンプル不足"})
                continue

            beta = np.array(lp["beta"])
            se = np.array(lp["se"])
            p = np.array(lp["p"])
            peak_h = int(np.argmax(np.abs(beta)))
            # 採用判定: ピークで p<0.1 かつ 弾性値が正
            if p[peak_h] >= P_THRESH or beta[peak_h] <= 0:
                entry["insufficient"].append({"code": ccode, "name": cname, "why": "統計的に有意でない"})
                continue

            n_sig += 1
            entry["drivers"].append({
                "code": ccode,
                "name": cname,
                "kind": "輸入" if code2kind.get(ccode, "").startswith("import") else "国内",
                "reason": reason,
                "elast": [round(float(b), 4) for b in beta],
                "ci_lo": [round(float(b - 1.96 * s), 4) for b, s in zip(beta, se)],
                "ci_hi": [round(float(b + 1.96 * s), 4) for b, s in zip(beta, se)],
                "p": [round(float(x), 4) for x in p],
                "longrun": round(float(beta[H]), 4),
                "peak_h": peak_h,
                "peak_elast": round(float(beta[peak_h]), 4),
                "up12": round(float(lp["beta_up"][H]), 4),
                "up12_se": round(float(lp["se_up"][H]), 4),
                "dn12": round(float(lp["beta_dn"][H]), 4),
                "dn12_se": round(float(lp["se_dn"][H]), 4),
                "asym": round(float(lp["beta_up"][H] - lp["beta_dn"][H]), 4),
                "n_obs": lp["n_obs"],
                "sample": [t2month.get(lp["t_first"]), t2month.get(lp["t_last"])],
            })

        # 弾性値の大きい順
        entry["drivers"].sort(key=lambda d: -abs(d["peak_elast"]))
        results[tcode] = entry

    # ---- 予兆アラート: 直近で大きく動いた川上品目 → 影響を受ける川下品目 ----
    driver_codes = sorted({d["code"] for e in results.values() for d in e["drivers"]})
    alerts = []
    for ccode in driver_codes:
        lx = logw[ccode].dropna()
        if lx.index.max() < latest_t - 1:   # 直近データがない系列は除外
            continue
        chg = lx.diff(ALERT_WINDOW)
        recent = chg.iloc[-1]
        hist = chg.iloc[:-1].dropna()
        if len(hist) < 60 or not np.isfinite(recent):
            continue
        z = (recent - hist.mean()) / hist.std()
        if abs(recent) < ALERT_MIN_CHANGE or abs(z) < ALERT_Z:
            continue
        affected = []
        for tcode, e in results.items():
            for d in e["drivers"]:
                if d["code"] == ccode:
                    affected.append({
                        "code": tcode, "name": e["name"],
                        "impact": round(float(recent) * d["peak_elast"] * 100, 2),  # %ポイント
                        "peak_h": d["peak_h"],
                        "longrun_impact": round(float(recent) * d["longrun"] * 100, 2),
                    })
        if not affected:
            continue
        affected.sort(key=lambda a: -abs(a["impact"]))
        alerts.append({
            "code": ccode,
            "name": code2name.get(ccode, ccode),
            "kind": "輸入" if code2kind.get(ccode, "").startswith("import") else "国内",
            "recent_change": round(float(recent) * 100, 2),   # %（直近3ヶ月、対数）
            "z": round(float(z), 2),
            "window": ALERT_WINDOW,
            "affected": affected[:20],
        })
    alerts.sort(key=lambda a: -abs(a["recent_change"]) * len(a["affected"]) ** 0.5)

    meta = json.load(open(os.path.join(DATA, "meta.json"), encoding="utf-8"))
    out = {
        "meta": {
            "source": meta["source"],
            "latest_month": meta["latest_month"],
            "generated_at": datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d"),  # データ更新日（JST）
            "generated_note": "国内企業物価指数（消費税を除く・2020年基準接続指数で長期化）515品目 / 輸入物価指数（円ベース） / ドル円・原油をコントロールしたローカル・プロジェクション推定",
            "h_max": H,
            "p_thresh": P_THRESH,
            "min_obs": MIN_OBS,
        },
        "items": results,
        "alerts": alerts,
        # ドライバーとして登場する品目（輸入品目を含む）の階層パス。プルダウンの類別分けに使う
        "paths": {c: code2path.get(c, "") for c in driver_codes},
    }
    with open(os.path.join(DATA, "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    size = os.path.getsize(os.path.join(DATA, "results.json"))
    print(f"ペア数: {n_pairs}, 有意: {n_sig} ({n_sig/max(n_pairs,1)*100:.0f}%)")
    print(f"アラート: {len(alerts)}件")
    print(f"results.json: {size/1e6:.1f} MB")


if __name__ == "__main__":
    main()
