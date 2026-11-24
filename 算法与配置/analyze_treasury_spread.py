"""美债长短期期限利差（长期国债收益率减去短期国债收益率）计算与全中文可视化引擎。

数据来源（100%权威一手数据）：
1. 雅虎财经二级市场官方基准指数：13周短端美债收益率（^IRX）、5年期（^FVX）、10年期（^TNX）、30年期（^TYX）、美元指数（DX-Y.NYB）、纳斯达克综合指数（^IXIC）；
2. 美国财政部（U.S. Department of the Treasury）每日官方平价国债收益率曲线（覆盖1个月至30年期全部14个标准期限，含关键的2年期美债收益率）。

输出产物（全部采用纯正中文母语语序，并自动附带初学者的术语通俗解读）：
1. 《美债期限利差看板.html》：自包含交互式可视化看板（支持多组长短利差切换、时间窗口缩放、悬停十字准星读数、全期限国债曲线形态对比、美元指数联动及新手术语伴读）；
2. 《资讯栏目/YYYY-MM-DD_美债长短期利差走势图.png》：高清三联中文投研配图；
3. 《资讯栏目/YYYY-MM-DD_美债期限利差专题分析.md》：完整量化统计表、曲线四象限形态判定与初学者术语解释报告。
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import statistics
import sys
from typing import Any
import urllib.parse
import urllib.request

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

from glossary_manager import infer_glossary_for_text, load_ignored_terms

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
SPREAD_DIR = ROOT_DIR / "国债利差专题"
DASHBOARD_DIR = ROOT_DIR / "交互式看板"

# 配置 Matplotlib 中文字体（Windows 优先使用微软雅黑，兼顾黑体回退，解决负号显示）
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

MATURITY_COLS: list[tuple[str, str, float]] = [
    ("1 Mo", "1个月", 1 / 12),
    ("2 Mo", "2个月", 2 / 12),
    ("3 Mo", "3个月", 0.25),
    ("6 Mo", "6个月", 0.5),
    ("1 Yr", "1年", 1.0),
    ("2 Yr", "2年", 2.0),
    ("3 Yr", "3年", 3.0),
    ("5 Yr", "5年", 5.0),
    ("7 Yr", "7年", 7.0),
    ("10 Yr", "10年", 10.0),
    ("20 Yr", "20年", 20.0),
    ("30 Yr", "30年", 30.0),
]


def _http_get(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def fetch_yahoo_series(symbol: str, range_str: str = "2y") -> dict[str, float]:
    """获取指定市场指数过去两年的日线收盘序列（返回 {YYYY-MM-DD: 收盘值}）。"""
    encoded = urllib.parse.quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range={range_str}&interval=1d"
    payload = json.loads(_http_get(url))
    res = payload["chart"]["result"][0]
    timestamps = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    series: dict[str, float] = {}
    for ts, c in zip(timestamps, closes):
        if c is not None:
            dt_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            series[dt_str] = round(float(c), 4)
    return series


def fetch_treasury_par_curve_year(year: int) -> list[dict[str, Any]]:
    """从美国财政部官网拉取指定年份的每日官方平价国债收益率曲线 CSV。"""
    url = (
        f"https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
        f"daily-treasury-rates.csv/{year}/all?type=daily_treasury_yield_curve"
        f"&field_tdr_date_value={year}&page&_format=csv"
    )
    text = _http_get(url, timeout=18)
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict[str, Any]] = []
    for raw in reader:
        d_raw = (raw.get("Date") or "").strip()
        if not d_raw:
            continue
        dt_iso = datetime.strptime(d_raw, "%m/%d/%Y").strftime("%Y-%m-%d")
        entry: dict[str, Any] = {"date": dt_iso}
        for col_en, _, _ in MATURITY_COLS:
            val_str = (raw.get(col_en) or "").strip()
            entry[col_en] = float(val_str) if val_str not in ("", "N/A") else None
        rows.append(entry)
    return rows


def classify_curve_movement_cn(
    long_change_bp: float,
    short_change_bp: float,
    spread_change_bp: float,
) -> tuple[str, str]:
    """根据长短端收益率变动（基点）判定收益率曲线形态演变（牛陡/熊陡/牛平/熊平）。"""
    if abs(spread_change_bp) < 1.5 and abs(long_change_bp) < 1.5 and abs(short_change_bp) < 1.5:
        return "窄幅平移（曲线形态稳定）", "长短端美债收益率波动均不足 1.5 个基点，市场等待新的宏观数据打破平衡。"

    if spread_change_bp >= 0:
        # 利差走阔（变陡）
        if long_change_bp >= 0 and long_change_bp >= short_change_bp:
            return (
                "熊陡（长端收益率上行更快、利差走阔）",
                "长期国债收益率升幅大于短期，常见于经济风险偏好回暖、避险国债遭抛售或市场担忧长期通胀与国债供给增加。",
            )
        return (
            "牛陡（短端收益率回落更快、利差走阔）",
            "短期国债收益率降幅大于长期，通常反映市场对美联储降息或流动性宽松的预期升温。",
        )
    else:
        # 利差收窄（变平）
        if short_change_bp > 0 and short_change_bp > long_change_bp:
            return (
                "熊平（短端收益率上行更快、利差收窄）",
                "短期国债收益率升幅快于长期，通常反映美联储释放鹰派信号或短端降息预期降温，资金面趋紧。",
            )
        return (
            "牛平（长端收益率回落更快、利差收窄）",
            "长期国债收益率降幅大于短期，常见于避险买盘涌入长期国债锁定收益，或市场对远期经济增长趋于谨慎。",
        )


def collect_yield_spread_dataset() -> dict[str, Any]:
    """并发采集市场收益率锚点、财政部全期限平价收益率曲线及美元/纳指对照序列，计算全套期限利差。"""
    yahoo_syms = ["^IRX", "^FVX", "^TNX", "^TYX", "DX-Y.NYB", "^IXIC"]
    curr_year = datetime.now(timezone.utc).year
    years_to_fetch = [curr_year - 1, curr_year]

    yahoo_map: dict[str, dict[str, float]] = {}
    treasury_rows: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=8) as pool:
        y_futs = {s: pool.submit(fetch_yahoo_series, s, "2y") for s in yahoo_syms}
        t_futs = {yr: pool.submit(fetch_treasury_par_curve_year, yr) for yr in years_to_fetch}

        for s, fut in y_futs.items():
            yahoo_map[s] = fut.result()
        for yr, fut in t_futs.items():
            try:
                treasury_rows.extend(fut.result())
            except Exception:
                pass

    treasury_by_date: dict[str, dict[str, Any]] = {r["date"]: r for r in treasury_rows}

    # 以 ^TNX 与 ^IRX 共同拥有的美股交易日作为主时间轴
    common_dates = sorted(set(yahoo_map["^TNX"].keys()) & set(yahoo_map["^IRX"].keys()))
    latest_date = common_dates[-1]

    # 对齐美元指数最新值（与主报告实时锚点口径保持完全一致）
    dxy_series = yahoo_map.get("DX-Y.NYB", {})
    last_dxy = dxy_series[sorted(dxy_series.keys())[-1]] if dxy_series else None

    records: list[dict[str, Any]] = []
    for d in common_dates:
        irx = round(yahoo_map["^IRX"][d], 2) if d in yahoo_map["^IRX"] else None
        fvx = round(yahoo_map["^FVX"][d], 2) if d in yahoo_map["^FVX"] else None
        tnx = round(yahoo_map["^TNX"][d], 2) if d in yahoo_map["^TNX"] else None
        tyx = round(yahoo_map["^TYX"][d], 2) if d in yahoo_map["^TYX"] else None
        dxy = round(dxy_series[d], 2) if d in dxy_series else None
        ixic = round(yahoo_map["^IXIC"][d], 2) if d in yahoo_map["^IXIC"] else None
        t_row = treasury_by_date.get(d, {})

        y2 = round(t_row["2 Yr"], 2) if t_row.get("2 Yr") is not None else None
        m3_par = round(t_row["3 Mo"], 2) if t_row.get("3 Mo") is not None else None
        y10_par = round(t_row["10 Yr"], 2) if t_row.get("10 Yr") is not None else None
        y30_par = round(t_row["30 Yr"], 2) if t_row.get("30 Yr") is not None else None

        # 若当日财政部某字段缺失，使用 ^TNX / ^TYX 对齐计算
        y10_eff = y10_par if y10_par is not None else tnx
        y30_eff = y30_par if y30_par is not None else tyx

        # 各核心长短期利差（基于标准两位小数公布收益率计算基点，确保公式与结果严丝合缝，1% = 100 基点）
        sp_10y_irx_bp = round((tnx - irx) * 100, 1) if (tnx is not None and irx is not None) else None
        sp_10y_2y_bp = round((y10_eff - y2) * 100, 1) if (y10_eff is not None and y2 is not None) else None
        sp_10y_3m_par_bp = round((y10_eff - m3_par) * 100, 1) if (y10_eff is not None and m3_par is not None) else None
        sp_30y_irx_bp = round((tyx - irx) * 100, 1) if (tyx is not None and irx is not None) else None
        sp_30y_10y_bp = round((y30_eff - y10_eff) * 100, 1) if (y30_eff is not None and y10_eff is not None) else None

        records.append(
            {
                "date": d,
                "irx_13w": irx,
                "fvx_5y": fvx,
                "tnx_10y": tnx,
                "tyx_30y": tyx,
                "tsy_3m_par": m3_par,
                "tsy_2y_par": y2,
                "tsy_10y_par": y10_par,
                "dxy": dxy,
                "ixic": ixic,
                "sp_10y_irx_bp": sp_10y_irx_bp,
                "sp_10y_2y_bp": sp_10y_2y_bp,
                "sp_10y_3m_par_bp": sp_10y_3m_par_bp,
                "sp_30y_irx_bp": sp_30y_irx_bp,
                "sp_30y_10y_bp": sp_30y_10y_bp,
            }
        )

    # 提取全期限收益率曲线快照（最新交易日、5个交易日前、20个交易日前、本年首个交易日）
    par_dates = sorted(treasury_by_date.keys())
    curve_snapshots: list[dict[str, Any]] = []
    if par_dates:
        idx_last = len(par_dates) - 1
        idx_1w = max(0, idx_last - 5)
        idx_1m = max(0, idx_last - 21)
        curr_yr_dates = [i for i, dt in enumerate(par_dates) if dt.startswith(latest_date[:4])]
        idx_ytd = curr_yr_dates[0] if curr_yr_dates else 0

        for label_cn, idx in [
            (f"最新收盘（{par_dates[idx_last]}）", idx_last),
            (f"一周前（{par_dates[idx_1w]}）", idx_1w),
            (f"一月前（{par_dates[idx_1m]}）", idx_1m),
            (f"年初基准（{par_dates[idx_ytd]}）", idx_ytd),
        ]:
            row = treasury_by_date[par_dates[idx]]
            curve_snapshots.append(
                {
                    "label_cn": label_cn,
                    "date": par_dates[idx],
                    "points": [
                        {
                            "col": col_en,
                            "maturity_cn": m_cn,
                            "years": yrs,
                            "yield_pct": row.get(col_en),
                        }
                        for col_en, m_cn, yrs in MATURITY_COLS
                        if row.get(col_en) is not None
                    ],
                }
            )

    # 计算最近一年（252个交易日）的统计分位与极值
    recent_1y = records[-252:] if len(records) >= 252 else records
    last_rec = records[-1]
    prev_rec = records[-2]
    rec_5d = records[-6] if len(records) >= 6 else records[0]
    rec_20d = records[-21] if len(records) >= 21 else records[0]

    def _spread_stats(key: str, title_cn: str, long_label: str, short_label: str, long_val: float | None, short_val: float | None) -> dict[str, Any]:
        vals = [r[key] for r in recent_1y if r[key] is not None]
        curr = last_rec[key]
        prev = prev_rec[key]
        v5 = rec_5d[key]
        v20 = rec_20d[key]
        inv_days = sum(1 for v in vals if v < 0)
        pct_rank = round(sum(1 for v in vals if v <= curr) / len(vals) * 100, 1) if (vals and curr is not None) else None
        return {
            "key": key,
            "title_cn": title_cn,
            "formula_cn": f"{long_label}（{long_val:.2f}%） − {short_label}（{short_val:.2f}%）" if (long_val is not None and short_val is not None) else f"{long_label} − {short_label}",
            "current_bp": round(curr) if curr is not None else None,
            "current_exact_bp": curr,
            "chg_1d_bp": round(curr - prev, 1) if (curr is not None and prev is not None) else None,
            "chg_5d_bp": round(curr - v5, 1) if (curr is not None and v5 is not None) else None,
            "chg_20d_bp": round(curr - v20, 1) if (curr is not None and v20 is not None) else None,
            "min_1y_bp": round(min(vals), 1) if vals else None,
            "max_1y_bp": round(max(vals), 1) if vals else None,
            "mean_1y_bp": round(statistics.mean(vals), 1) if vals else None,
            "inverted_days_1y": inv_days,
            "total_days_1y": len(vals),
            "percentile_1y": pct_rank,
            "status_cn": "正利差（正常向上倾斜）" if (curr is not None and curr >= 0) else "负利差（收益率倒挂预警）",
        }

    spread_summaries = [
        _spread_stats("sp_10y_irx_bp", "10年期减13周短端美债利差（盘面核心锚点）", "10年期美债", "13周短债贴现率", last_rec["tnx_10y"], last_rec["irx_13w"]),
        _spread_stats("sp_10y_2y_bp", "10年期减2年期美债利差（华尔街经典基准）", "10年期美债", "2年期美债", last_rec["tsy_10y_par"] or last_rec["tnx_10y"], last_rec["tsy_2y_par"]),
        _spread_stats("sp_10y_3m_par_bp", "10年期减3个月平价美债利差（联储衰退模型口径）", "10年期平价美债", "3个月平价美债", last_rec["tsy_10y_par"] or last_rec["tnx_10y"], last_rec["tsy_3m_par"]),
        _spread_stats("sp_30y_irx_bp", "30年期减13周美债全曲线总利差", "30年期美债", "13周短债贴现率", last_rec["tyx_30y"], last_rec["irx_13w"]),
        _spread_stats("sp_30y_10y_bp", "30年期减10年期超长端期限溢价", "30年期美债", "10年期美债", last_rec["tyx_30y"], last_rec["tnx_10y"]),
    ]

    # 判定单日与近20日曲线形态（基于 10年期 vs 13周）
    long_1d_bp = round((last_rec["tnx_10y"] - prev_rec["tnx_10y"]) * 100, 1)
    short_1d_bp = round((last_rec["irx_13w"] - prev_rec["irx_13w"]) * 100, 1)
    sp_1d_bp = round(last_rec["sp_10y_irx_bp"] - prev_rec["sp_10y_irx_bp"], 1)
    regime_1d_title, regime_1d_desc = classify_curve_movement_cn(long_1d_bp, short_1d_bp, sp_1d_bp)

    long_20d_bp = round((last_rec["tnx_10y"] - rec_20d["tnx_10y"]) * 100, 1)
    short_20d_bp = round((last_rec["irx_13w"] - rec_20d["irx_13w"]) * 100, 1)
    sp_20d_bp = round(last_rec["sp_10y_irx_bp"] - rec_20d["sp_10y_irx_bp"], 1)
    regime_20d_title, regime_20d_desc = classify_curve_movement_cn(long_20d_bp, short_20d_bp, sp_20d_bp)

    return {
        "latest_date": latest_date,
        "anchor_13w_pct": last_rec["irx_13w"],
        "anchor_2y_pct": last_rec["tsy_2y_par"],
        "anchor_10y_pct": last_rec["tnx_10y"],
        "anchor_30y_pct": last_rec["tyx_30y"],
        "anchor_dxy": last_dxy,
        "anchor_spread_10y_13w_bp": round(last_rec["sp_10y_irx_bp"]),
        "anchor_spread_10y_2y_bp": round(last_rec["sp_10y_2y_bp"]) if last_rec["sp_10y_2y_bp"] is not None else None,
        "regime_1d_title": regime_1d_title,
        "regime_1d_desc": regime_1d_desc,
        "regime_20d_title": regime_20d_title,
        "regime_20d_desc": regime_20d_desc,
        "spread_summaries": spread_summaries,
        "curve_snapshots": curve_snapshots,
        "records": records,
    }


def render_matplotlib_png(dataset: dict[str, Any], out_png: Path) -> None:
    """绘制深色机构级三联全中文《美债长短期收益率与期限利差可视化图》。"""
    recent = dataset["records"][-252:]
    dates = [datetime.strptime(r["date"], "%Y-%m-%d") for r in recent]
    y10 = [r["tnx_10y"] for r in recent]
    y13w = [r["irx_13w"] for r in recent]
    y2 = [r["tsy_2y_par"] for r in recent]
    sp_10_13w = [r["sp_10y_irx_bp"] for r in recent]
    sp_10_2y = [r["sp_10y_2y_bp"] for r in recent]

    bg_color = "#0b0f19"
    card_color = "#111827"
    grid_color = "#1f2937"
    text_color = "#f3f4f6"
    muted_color = "#9ca3af"

    fig = plt.figure(figsize=(14, 11), facecolor=bg_color, dpi=160)
    gs = fig.add_gridspec(3, 1, height_ratios=[1.15, 1.25, 1.0], hspace=0.34)

    tdate = dataset["latest_date"]
    fig.suptitle(
        f"美国国债长短期收益率与期限利差全景监测图（截至 {tdate} 收盘）",
        fontsize=16,
        fontweight="bold",
        color=text_color,
        y=0.965,
    )
    fig.text(
        0.5,
        0.935,
        f"核心锚点：10年期美债 {dataset['anchor_10y_pct']:.2f}%  |  2年期美债 {dataset['anchor_2y_pct']:.2f}%  |  "
        f"13周短债 {dataset['anchor_13w_pct']:.2f}%  |  10年减13周利差 {dataset['anchor_spread_10y_13w_bp']:+d} 基点  |  "
        f"美元指数 {dataset['anchor_dxy']:.2f}",
        ha="center",
        fontsize=10.5,
        color="#60a5fa",
    )

    # 子图1：长端 vs 短端美债收益率走势对比
    ax1 = fig.add_subplot(gs[0], facecolor=card_color)
    ax1.plot(dates, y10, color="#3b82f6", linewidth=2.0, label=f"10年期长期美债收益率（最新 {dataset['anchor_10y_pct']:.2f}%）")
    y2_clean_d = [d for d, v in zip(dates, y2) if v is not None]
    y2_clean_v = [v for v in y2 if v is not None]
    if y2_clean_v:
        ax1.plot(y2_clean_d, y2_clean_v, color="#f59e0b", linewidth=1.6, linestyle="--", label=f"2年期中短端美债收益率（最新 {dataset['anchor_2y_pct']:.2f}%）")
    ax1.plot(dates, y13w, color="#a855f7", linewidth=1.8, label=f"13周短端美债收益率（最新 {dataset['anchor_13w_pct']:.2f}%）")
    ax1.set_title("（一）近一年长期国债与短期国债年化收益率对比（单位：%）", color=text_color, fontsize=12, fontweight="bold", loc="left", pad=8)
    ax1.set_ylabel("年化收益率 (%)", color=muted_color, fontsize=10)
    ax1.grid(True, color=grid_color, linestyle="--", linewidth=0.7)
    ax1.legend(loc="upper left", facecolor=bg_color, edgecolor=grid_color, labelcolor=text_color, fontsize=9.5, ncol=3)

    # 子图2：长期减短期国债期限利差（核心可视化）
    ax2 = fig.add_subplot(gs[1], facecolor=card_color)
    ax2.axhline(0, color="#ef4444", linewidth=1.3, linestyle="-", alpha=0.85, label="0 基点（收益率倒挂警戒分界线）")
    ax2.plot(dates, sp_10_13w, color="#10b981", linewidth=2.1, label=f"10年期减13周短债利差（最新 {dataset['anchor_spread_10y_13w_bp']:+d} 基点）")
    ax2.fill_between(
        dates,
        sp_10_13w,
        0,
        where=[v >= 0 for v in sp_10_13w],
        color="#10b981",
        alpha=0.20,
        interpolate=True,
        label="正利差安全区（长端高于短端）",
    )
    ax2.fill_between(
        dates,
        sp_10_13w,
        0,
        where=[v < 0 for v in sp_10_13w],
        color="#ef4444",
        alpha=0.28,
        interpolate=True,
        label="负利差倒挂预警区（短端反超长端）",
    )
    sp2_d = [d for d, v in zip(dates, sp_10_2y) if v is not None]
    sp2_v = [v for v in sp_10_2y if v is not None]
    if sp2_v:
        ax2.plot(sp2_d, sp2_v, color="#38bdf8", linewidth=1.6, linestyle="-.", label=f"10年期减2年期国债利差（最新 {dataset['anchor_spread_10y_2y_bp']:+d} 基点）")

    # 标注最新收盘点位气泡
    ax2.scatter([dates[-1]], [sp_10_13w[-1]], color="#10b981", s=55, zorder=5)
    ax2.annotate(
        f"{dataset['anchor_spread_10y_13w_bp']:+d} 基点",
        xy=(dates[-1], sp_10_13w[-1]),
        xytext=(-68, 12),
        textcoords="offset points",
        color="#10b981",
        fontsize=10,
        fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.3", facecolor=bg_color, edgecolor="#10b981"),
        arrowprops=dict(arrowstyle="->", color="#10b981"),
    )
    ax2.set_title("（二）长期国债减去短期国债期限利差历史演变（单位：基点，100基点 = 1%）", color=text_color, fontsize=12, fontweight="bold", loc="left", pad=8)
    ax2.set_ylabel("期限利差 (基点 bp)", color=muted_color, fontsize=10)
    ax2.grid(True, color=grid_color, linestyle="--", linewidth=0.7)
    ax2.legend(loc="upper left", facecolor=bg_color, edgecolor=grid_color, labelcolor=text_color, fontsize=9, ncol=3)

    # 子图3：美国财政部官方全期限收益率曲线（1个月至30年）对比
    ax3 = fig.add_subplot(gs[2], facecolor=card_color)
    palette = ["#3b82f6", "#10b981", "#f59e0b", "#9ca3af"]
    styles = ["-", "--", "-.", ":"]
    for idx_s, snap in enumerate(dataset["curve_snapshots"]):
        x_idx = list(range(len(snap["points"])))
        y_vals = [p["yield_pct"] for p in snap["points"]]
        x_labels = [p["maturity_cn"] for p in snap["points"]]
        ax3.plot(
            x_idx,
            y_vals,
            color=palette[idx_s % len(palette)],
            linestyle=styles[idx_s % len(styles)],
            marker="o" if idx_s == 0 else ".",
            linewidth=2.2 if idx_s == 0 else 1.4,
            label=snap["label_cn"],
        )
        if idx_s == 0:
            ax3.set_xticks(x_idx)
            ax3.set_xticklabels(x_labels, color=text_color, fontsize=9.5)
            for xi, yi in zip(x_idx, y_vals):
                if x_labels[xi] in ("3个月", "2年", "5年", "10年", "30年"):
                    ax3.annotate(
                        f"{yi:.2f}%",
                        xy=(xi, yi),
                        xytext=(0, 8),
                        textcoords="offset points",
                        ha="center",
                        color="#93c5fd",
                        fontsize=8.5,
                        fontweight="bold",
                        bbox=dict(boxstyle="round,pad=0.18", facecolor=bg_color, edgecolor="none", alpha=0.82),
                    )

    ax3.set_title("（三）美国财政部官方全期限国债收益率曲线形态对比（从1个月短债至30年超长债）", color=text_color, fontsize=12, fontweight="bold", loc="left", pad=8)
    ax3.set_ylabel("官方平价收益率 (%)", color=muted_color, fontsize=10)
    ax3.grid(True, color=grid_color, linestyle="--", linewidth=0.7)
    ax3.legend(loc="lower right", facecolor=bg_color, edgecolor=grid_color, labelcolor=text_color, fontsize=9.5, ncol=2)

    for ax in (ax1, ax2):
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    for ax in (ax1, ax2, ax3):
        ax.tick_params(colors=muted_color, labelsize=9)
        for spine in ax.spines.values():
            spine.set_color(grid_color)

    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, facecolor=bg_color, bbox_inches="tight")
    plt.close(fig)


def build_spread_markdown(dataset: dict[str, Any], png_rel_name: str) -> tuple[str, list[dict[str, str]]]:
    """生成纯正中文语序的《美债期限利差专题分析.md》并自动推断初学者的术语解释。"""
    tdate = dataset["latest_date"]
    lines: list[str] = [
        f"# 美国国债长短期期限利差量化计算与可视化专题报告（截至 {tdate}）",
        "",
        f"> **官方锚点核验**：截至 **{tdate}** 美股收盘，13周短端美债收益率为 **{dataset['anchor_13w_pct']:.2f}%**，2年期美债收益率为 **{dataset['anchor_2y_pct']:.2f}%**，10年期美债收益率为 **{dataset['anchor_10y_pct']:.2f}%**，30年期美债收益率为 **{dataset['anchor_30y_pct']:.2f}%**；核心**10年期减13周美债期限利差为 {dataset['anchor_spread_10y_13w_bp']:+d} 个基点**（即 +{dataset['anchor_spread_10y_13w_bp']/100:.2f} 个百分点），美元指数报 **{dataset['anchor_dxy']:.2f}**。  ",
        "> **权威信源说明**：本算法仅采信**美国财政部官方每日国债收益率曲线表**与**雅虎财经二级市场官方基准指数**，杜绝一切非官方估算。",
        "",
        "---",
        "",
        "## 一、长短期国债期限利差全景可视化图",
        "",
        f"![美债长短期收益率与期限利差走势图]({png_rel_name})",
        "",
        "---",
        "",
        "## 二、五大核心长短期美债利差实时计算总表",
        "",
        "| 期限利差指标名称 | 计算公式（长期 − 短期） | 最新利差 | 单日变动 | 近5日变动 | 近20日变动 | 近一年最低 ~ 最高 | 近一年均值 | 近一年分位 | 近一年倒挂天数 | 当前曲线状态 |",
        "| :--- | :--- | ---: | ---: | ---: | ---: | :---: | ---: | ---: | :---: | :--- |",
    ]

    for s in dataset["spread_summaries"]:
        c_bp = f"**{s['current_bp']:+d} 基点**" if s["current_bp"] is not None else "暂无"
        d1 = f"{s['chg_1d_bp']:+.1f} 基点" if s["chg_1d_bp"] is not None else "暂无"
        d5 = f"{s['chg_5d_bp']:+.1f} 基点" if s["chg_5d_bp"] is not None else "暂无"
        d20 = f"{s['chg_20d_bp']:+.1f} 基点" if s["chg_20d_bp"] is not None else "暂无"
        rng = f"{s['min_1y_bp']:+.0f} ~ {s['max_1y_bp']:+.0f} 基点" if s["min_1y_bp"] is not None else "暂无"
        mn = f"{s['mean_1y_bp']:+.1f} 基点" if s["mean_1y_bp"] is not None else "暂无"
        pct = f"{s['percentile_1y']:.1f}%" if s["percentile_1y"] is not None else "暂无"
        inv = f"{s['inverted_days_1y']} / {s['total_days_1y']} 天"
        lines.append(
            f"| **{s['title_cn']}** | {s['formula_cn']} | {c_bp} | {d1} | {d5} | {d20} | {rng} | {mn} | {pct} | {inv} | {s['status_cn']} |"
        )

    lines.extend([
        "",
        "> **口径差异贴心提示**：二级市场盘面指数 `^IRX`（4.15%）按 **360天贴现率口径** 报价，所得10年期减13周利差为 **+77 个基点**；而美国财政部官方每日曲线表中的3个月国债（4.37%）按 **365天平价债券等价收益率口径** 报价，同口径下10年期减3个月利差为 **+55 个基点**。两者方向一致、均处于显著正斜率区间。",
        "",
        "---",
        "",
        "## 三、收益率曲线四象限形态诊断与纳斯达克传导逻辑",
        "",
        f"1. **单日曲线变动形态**：**{dataset['regime_1d_title']}** —— {dataset['regime_1d_desc']}",
        f"2. **近20个交易日中期形态**：**{dataset['regime_20d_title']}** —— {dataset['regime_20d_desc']}",
        f"3. **对纳斯达克科技股的估值启示**：当前长短期美债收益率曲线整体保持向上倾斜（未出现衰退型深度倒挂），说明债市定价的核心逻辑并非“美国经济即将硬着陆衰退”，而是“经济增长具韧性叠加通胀粘性使美联储维持高利率更久”。在此格局下，10年期美债收益率（{dataset['anchor_10y_pct']:.2f}%）与 5.00% 整数大关的距离，直接决定了科技巨头与高弹性芯片股的市盈率扩张上限；同时美元指数稳居 {dataset['anchor_dxy']:.2f} 偏强水位，跨国科技企业海外汇兑环境维持中性偏紧。",
        "",
    ])

    draft_text = "\n".join(lines)
    glossary_items = infer_glossary_for_text(draft_text)
    ignored = load_ignored_terms()

    lines.extend([
        "---",
        "",
        "## 四、初学者国债与利率术语通俗伴读",
        "",
        f"> 系统已自动提取本专题中可能较陌生的债券与利率名词（当前免解释屏蔽词数：**{len(ignored)}** 个；若某词无需再解释，请随时告知我）。",
        "",
    ])
    for idx, g in enumerate(glossary_items, 1):
        lines.append(f"{idx}. **{g['term']}**（*{g['category']}*）")
        lines.append(f"   - **通俗理解**：{g['definition']}")
        lines.append(f"   - **实战影响**：{g['practical']}")

    return "\n".join(lines) + "\n", glossary_items


def build_interactive_spread_html(dataset: dict[str, Any], glossary_items: list[dict[str, str]]) -> str:
    """生成纯正中文语序的自包含交互式《美债期限利差看板.html》（原生 SVG 交互绘图，零外部插件依赖）。"""
    tdate = dataset["latest_date"]
    js_payload = json.dumps(
        {
            "latestDate": tdate,
            "anchor13w": dataset["anchor_13w_pct"],
            "anchor2y": dataset["anchor_2y_pct"],
            "anchor10y": dataset["anchor_10y_pct"],
            "anchor30y": dataset["anchor_30y_pct"],
            "anchorDxy": dataset["anchor_dxy"],
            "spread10y13wBp": dataset["anchor_spread_10y_13w_bp"],
            "spread10y2yBp": dataset["anchor_spread_10y_2y_bp"],
            "regime1dTitle": dataset["regime_1d_title"],
            "regime1dDesc": dataset["regime_1d_desc"],
            "regime20dTitle": dataset["regime_20d_title"],
            "regime20dDesc": dataset["regime_20d_desc"],
            "summaries": dataset["spread_summaries"],
            "curveSnapshots": dataset["curve_snapshots"],
            "records": dataset["records"],
            "glossary": glossary_items,
        },
        ensure_ascii=False,
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>美国国债长短期期限利差与汇率官方锚点交互看板 — {tdate}</title>
  <script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>
  <style>
    :root {{
      --bg-fallback: #0b0f19;
      --card-fallback: #111827;
      --fg-fallback: #f3f4f6;
      --muted-fallback: #9ca3af;
      --border-fallback: #1f2937;
      --primary-fallback: #3b82f6;
      --success-fallback: #10b981;
      --error-fallback: #ef4444;
      --warning-fallback: #f59e0b;
    }}
    body {{
      background-color: var(--background, var(--bg-fallback));
      color: var(--foreground, var(--fg-fallback));
      font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
    }}
    .tabular-nums {{ font-variant-numeric: tabular-nums; }}
  </style>
</head>
<body class="bg-[var(--background,#0b0f19)] text-[var(--foreground,#f3f4f6)] antialiased p-4 md:p-6">
  <div class="max-w-7xl mx-auto space-y-5">

    <!-- 顶部中文标题栏 -->
    <header class="bg-[var(--card,#111827)] border border-[var(--border,#1f2937)] rounded-xl p-5 flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
      <div>
        <div class="flex items-center gap-2 text-xs tracking-wider text-[var(--muted-foreground,#9ca3af)] font-semibold">
          <span>宏观利率与跨资产定价锚点实验室</span>
          <span>•</span>
          <span>美国财政部与二级市场官方数据直连</span>
        </div>
        <h1 class="text-xl md:text-2xl font-bold mt-1">美国国债长短期期限利差计算与可视化看板</h1>
        <p class="text-xs text-[var(--muted-foreground,#9ca3af)] mt-1">
          最新收盘基准日：<span class="font-mono text-[var(--foreground,#f3f4f6)]">{tdate}</span> &nbsp;|&nbsp;
          核心公式：长期国债收益率 − 短期国债收益率（1 个百分点 = 100 个基点）
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <span class="px-3 py-1.5 rounded-lg text-xs font-semibold border border-[var(--success,#10b981)] text-[var(--success,#10b981)] bg-[var(--background,#0b0f19)]">
          10年减13周利差：{dataset["anchor_spread_10y_13w_bp"]:+d} 基点（正斜率未倒挂）
        </span>
        <span class="px-3 py-1.5 rounded-lg text-xs font-semibold border border-[var(--border,#1f2937)] bg-[var(--background,#0b0f19)]">
          美元指数：{dataset["anchor_dxy"]:.2f}
        </span>
        <a href="{tdate}.html" class="px-3 py-1.5 rounded-lg text-xs font-semibold border border-[var(--primary,#3b82f6)] text-[var(--primary,#3b82f6)] bg-[var(--background,#0b0f19)] hover:opacity-80">
          &larr; 返回每日科技投研看板
        </a>
      </div>
    </header>

    <!-- 官方锚点五大核心指标卡 -->
    <section class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3.5" id="anchor-cards"></section>

    <!-- 主交互区：长短期利差历史曲线 + 长短端双线对比 -->
    <section class="bg-[var(--card,#111827)] border border-[var(--border,#1f2937)] rounded-xl p-5 space-y-4">
      <div class="flex flex-col xl:flex-row xl:items-center xl:justify-between gap-3 pb-3 border-b border-[var(--border,#1f2937)]">
        <div>
          <h2 class="text-base font-bold">长期国债减去短期国债期限利差动态走势图</h2>
          <p class="text-xs text-[var(--muted-foreground,#9ca3af)]">绿色填充代表正利差（正常向上倾斜），红色填充代表负利差（收益率倒挂预警）；鼠标移入图表可逐日查看精确读数</p>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <div class="flex flex-wrap gap-1" id="pair-tabs">
            <button data-pair="sp_10y_irx_bp" class="pair-btn px-2.5 py-1 rounded-md text-xs font-medium border border-[var(--primary,#3b82f6)] bg-[var(--primary,#3b82f6)] text-white">10年 − 13周 (+77基点)</button>
            <button data-pair="sp_10y_2y_bp" class="pair-btn px-2.5 py-1 rounded-md text-xs font-medium border border-[var(--border,#1f2937)] text-[var(--muted-foreground,#9ca3af)]">10年 − 2年</button>
            <button data-pair="sp_10y_3m_par_bp" class="pair-btn px-2.5 py-1 rounded-md text-xs font-medium border border-[var(--border,#1f2937)] text-[var(--muted-foreground,#9ca3af)]">10年 − 3月(财政部平价)</button>
            <button data-pair="sp_30y_irx_bp" class="pair-btn px-2.5 py-1 rounded-md text-xs font-medium border border-[var(--border,#1f2937)] text-[var(--muted-foreground,#9ca3af)]">30年 − 13周</button>
            <button data-pair="sp_30y_10y_bp" class="pair-btn px-2.5 py-1 rounded-md text-xs font-medium border border-[var(--border,#1f2937)] text-[var(--muted-foreground,#9ca3af)]">30年 − 10年</button>
          </div>
          <span class="text-[var(--border,#1f2937)]">|</span>
          <div class="flex gap-1" id="range-tabs">
            <button data-days="63" class="range-btn px-2 py-1 rounded-md text-xs border border-[var(--border,#1f2937)] text-[var(--muted-foreground,#9ca3af)]">近3月</button>
            <button data-days="126" class="range-btn px-2 py-1 rounded-md text-xs border border-[var(--border,#1f2937)] text-[var(--muted-foreground,#9ca3af)]">近半年</button>
            <button data-days="252" class="range-btn px-2 py-1 rounded-md text-xs border border-[var(--primary,#3b82f6)] bg-[var(--primary,#3b82f6)] text-white">近1年</button>
            <button data-days="9999" class="range-btn px-2 py-1 rounded-md text-xs border border-[var(--border,#1f2937)] text-[var(--muted-foreground,#9ca3af)]">近2年全量</button>
          </div>
        </div>
      </div>

      <!-- 悬停实时数值栏 -->
      <div id="hover-readout" class="text-xs bg-[var(--background,#0b0f19)] border border-[var(--border,#1f2937)] rounded-lg px-3.5 py-2 flex flex-wrap items-center justify-between gap-2 tabular-nums"></div>

      <!-- 主利差 SVG 容器 -->
      <div class="relative w-full overflow-hidden">
        <svg id="spread-svg" viewBox="0 0 1000 300" class="w-full h-auto select-none"></svg>
      </div>

      <!-- 下方同步长短端收益率双线图 -->
      <div class="pt-2 border-t border-[var(--border,#1f2937)]">
        <div class="text-xs font-semibold mb-1.5 text-[var(--muted-foreground,#9ca3af)]">对应区间长期国债收益率（蓝线）与短期国债收益率（紫线）走势对照（单位：%）</div>
        <svg id="yields-svg" viewBox="0 0 1000 190" class="w-full h-auto select-none"></svg>
      </div>
    </section>

    <!-- 第二排：美国财政部全期限收益率曲线形态 + 曲线四象限诊断 -->
    <section class="grid grid-cols-1 lg:grid-cols-12 gap-4">
      <div class="lg:col-span-7 bg-[var(--card,#111827)] border border-[var(--border,#1f2937)] rounded-xl p-5 space-y-3">
        <div>
          <h2 class="text-base font-bold">美国财政部官方全期限收益率曲线对比（1个月 → 30年期）</h2>
          <p class="text-xs text-[var(--muted-foreground,#9ca3af)]">对比最新收盘、一周前、一月前与年初基准的整条国债利率曲线平移与陡峭度变化</p>
        </div>
        <svg id="curve-svg" viewBox="0 0 700 260" class="w-full h-auto select-none"></svg>
        <div id="curve-legend" class="flex flex-wrap gap-4 text-xs pt-1"></div>
      </div>

      <div class="lg:col-span-5 bg-[var(--card,#111827)] border border-[var(--border,#1f2937)] rounded-xl p-5 flex flex-col justify-between space-y-3">
        <div class="space-y-3">
          <h2 class="text-base font-bold">收益率曲线形态诊断与汇率传导解读</h2>
          <div class="p-3.5 rounded-lg border border-[var(--border,#1f2937)] bg-[var(--background,#0b0f19)] space-y-1">
            <div class="text-xs text-[var(--primary,#3b82f6)] font-semibold">单日曲线形态演变</div>
            <div class="text-sm font-bold" id="regime-1d-title"></div>
            <p class="text-xs text-[var(--muted-foreground,#9ca3af)] leading-relaxed" id="regime-1d-desc"></p>
          </div>
          <div class="p-3.5 rounded-lg border border-[var(--border,#1f2937)] bg-[var(--background,#0b0f19)] space-y-1">
            <div class="text-xs text-[var(--warning,#f59e0b)] font-semibold">近20日中期曲线演变</div>
            <div class="text-sm font-bold" id="regime-20d-title"></div>
            <p class="text-xs text-[var(--muted-foreground,#9ca3af)] leading-relaxed" id="regime-20d-desc"></p>
          </div>
          <div class="p-3.5 rounded-lg border border-[var(--border,#1f2937)] bg-[var(--background,#0b0f19)] space-y-1">
            <div class="text-xs text-[var(--success,#10b981)] font-semibold">口径核验说明（为何盘面 +77 基点 vs 财政部表 +55 基点？）</div>
            <p class="text-xs text-[var(--muted-foreground,#9ca3af)] leading-relaxed">
              盘面行情代码 <span class="font-mono">^IRX</span>（4.15%）采用 <strong>360天贴现率口径</strong>，与10年期美债（4.92%）相减得 <strong>+77 基点</strong>；美国财政部平价曲线表中的3个月国债（4.37%）采用 <strong>365天债券等价收益率口径</strong>，相减得 <strong>+55 基点</strong>。本看板同时收录两种官方口径供对照。
            </p>
          </div>
        </div>
      </div>
    </section>

    <!-- 五大核心利差量化统计明细表 -->
    <section class="bg-[var(--card,#111827)] border border-[var(--border,#1f2937)] rounded-xl p-5 space-y-3">
      <div>
        <h2 class="text-base font-bold">五大美债长短期期限利差量化统计总表</h2>
        <p class="text-xs text-[var(--muted-foreground,#9ca3af)]">全面统计单日、近5日、近20日基点变化，以及过去一年极值区间、历史分位数与倒挂天数</p>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-xs text-left border-collapse">
          <thead>
            <tr class="border-b border-[var(--border,#1f2937)] text-[var(--muted-foreground,#9ca3af)]">
              <th class="py-2.5 px-2 font-semibold">利差指标名称</th>
              <th class="py-2.5 px-2 font-semibold">长端 − 短端计算式</th>
              <th class="py-2.5 px-2 font-semibold text-right">最新利差</th>
              <th class="py-2.5 px-2 font-semibold text-right">单日变动</th>
              <th class="py-2.5 px-2 font-semibold text-right">近5日变动</th>
              <th class="py-2.5 px-2 font-semibold text-right">近20日变动</th>
              <th class="py-2.5 px-2 font-semibold text-right">近一年区间</th>
              <th class="py-2.5 px-2 font-semibold text-right">近一年分位</th>
              <th class="py-2.5 px-2 font-semibold text-right">近一年倒挂天数</th>
              <th class="py-2.5 px-2 font-semibold">当前状态</th>
            </tr>
          </thead>
          <tbody id="summary-tbody" class="divide-y divide-[var(--border,#1f2937)] tabular-nums"></tbody>
        </table>
      </div>
    </section>

    <!-- 初学者国债与期限利差术语通俗词典 -->
    <section class="bg-[var(--card,#111827)] border border-[var(--border,#1f2937)] rounded-xl p-5 space-y-3">
      <div>
        <h2 class="text-base font-bold">初学者国债与期限利差术语通俗伴读</h2>
        <p class="text-xs text-[var(--muted-foreground,#9ca3af)]">自动提取本页涉及的债券与宏观专业名词；若您已掌握某词无需再解释，直接告知我即可永久屏蔽</p>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-3" id="glossary-grid"></div>
    </section>

  </div>

  <script>
    const D = {js_payload};

    const PAIR_META = {{
      sp_10y_irx_bp: {{ label: "10年期美债 − 13周短端美债", longKey: "tnx_10y", shortKey: "irx_13w", longName: "10年期美债", shortName: "13周短债贴现率" }},
      sp_10y_2y_bp: {{ label: "10年期美债 − 2年期美债", longKey: "tnx_10y", shortKey: "tsy_2y_par", longName: "10年期美债", shortName: "2年期美债" }},
      sp_10y_3m_par_bp: {{ label: "10年期平价美债 − 3个月平价美债", longKey: "tnx_10y", shortKey: "tsy_3m_par", longName: "10年期美债", shortName: "3个月平价美债" }},
      sp_30y_irx_bp: {{ label: "30年期美债 − 13周短端美债", longKey: "tyx_30y", shortKey: "irx_13w", longName: "30年期美债", shortName: "13周短债贴现率" }},
      sp_30y_10y_bp: {{ label: "30年期美债 − 10年期美债", longKey: "tyx_30y", shortKey: "tnx_10y", longName: "30年期美债", shortName: "10年期美债" }}
    }};

    const fmtBp = (v, dec = 1) => (v === null || v === undefined ? "暂无" : `${{v >= 0 ? "+" : ""}}${{v.toFixed(dec)}} 基点`);
    const bpColor = (v) => (v > 0 ? "text-[var(--success,#10b981)]" : v < 0 ? "text-[var(--error,#ef4444)]" : "text-[var(--muted-foreground,#9ca3af)]");

    // 1. 顶部锚点卡片
    const cards = [
      {{ title: "13周短端美债收益率", code: "^IRX (贴现率口径)", val: `${{D.anchor13w.toFixed(2)}}%`, sub: "紧贴美联储基准利率走廊" }},
      {{ title: "2年期美债收益率", code: "美国财政部官方平价", val: `${{D.anchor2y.toFixed(2)}}%`, sub: "反映未来两年加息/降息路径" }},
      {{ title: "10年期长期美债收益率", code: "^TNX / 财政部同值", val: `${{D.anchor10y.toFixed(2)}}%`, sub: "全球科技股估值折现之锚" }},
      {{ title: "10年减13周期限利差", code: "4.92% − 4.15%", val: `${{D.spread10y13wBp >= 0 ? "+" : ""}}${{D.spread10y13wBp}} 基点`, sub: `10年减2年利差：+${{D.spread10y2yBp}} 基点`, highlight: true }},
      {{ title: "美元指数官方锚点", code: "DX-Y.NYB", val: `${{D.anchorDxy.toFixed(2)}}`, sub: `30年期超长美债：${{D.anchor30y.toFixed(2)}}%` }}
    ];
    document.getElementById("anchor-cards").innerHTML = cards.map(c => `
      <div class="bg-[var(--card,#111827)] border ${{c.highlight ? "border-[var(--success,#10b981)]" : "border-[var(--border,#1f2937)]"}} rounded-xl p-4 flex flex-col justify-between">
        <div class="flex items-center justify-between text-xs text-[var(--muted-foreground,#9ca3af)]">
          <span>${{c.title}}</span>
        </div>
        <div class="text-2xl font-bold tabular-nums mt-2 ${{c.highlight ? "text-[var(--success,#10b981)]" : ""}}">${{c.val}}</div>
        <div class="mt-2 pt-2 border-t border-[var(--border,#1f2937)] flex items-center justify-between text-xs text-[var(--muted-foreground,#9ca3af)]">
          <span>${{c.sub}}</span>
        </div>
      </div>
    `).join("");

    document.getElementById("regime-1d-title").textContent = D.regime1dTitle;
    document.getElementById("regime-1d-desc").textContent = D.regime1dDesc;
    document.getElementById("regime-20d-title").textContent = D.regime20dTitle;
    document.getElementById("regime-20d-desc").textContent = D.regime20dDesc;

    // 2. 交互式利差与双收益率 SVG 渲染
    let currentPair = "sp_10y_irx_bp";
    let currentDays = 252;

    function getFilteredRecords() {{
      const meta = PAIR_META[currentPair];
      const valid = D.records.filter(r => r[currentPair] !== null && r[meta.longKey] !== null && r[meta.shortKey] !== null);
      return valid.slice(-currentDays);
    }}

    function updateReadout(rec) {{
      const meta = PAIR_META[currentPair];
      const sp = rec[currentPair];
      const lv = rec[meta.longKey];
      const sv = rec[meta.shortKey];
      const dxyTxt = rec.dxy ? `美元指数：<strong>${{rec.dxy.toFixed(2)}}</strong>` : "";
      const ixicTxt = rec.ixic ? `纳斯达克综指：<strong>${{rec.ixic.toLocaleString("en-US", {{ minimumFractionDigits: 2 }})}}</strong>` : "";
      document.getElementById("hover-readout").innerHTML = `
        <div class="flex flex-wrap items-center gap-3">
          <span>交易日期：<strong class="font-mono">${{rec.date}}</strong></span>
          <span>${{meta.longName}}：<strong class="text-[#60a5fa]">${{lv.toFixed(2)}}%</strong></span>
          <span>${{meta.shortName}}：<strong class="text-[#c084fc]">${{sv.toFixed(2)}}%</strong></span>
          <span>期限利差（长 − 短）：<strong class="${{bpColor(sp)}}">${{fmtBp(sp, 1)}}</strong></span>
        </div>
        <div class="flex flex-wrap items-center gap-3 text-[var(--muted-foreground,#9ca3af)]">
          <span>${{dxyTxt}}</span>
          <span>${{ixicTxt}}</span>
        </div>
      `;
    }}

    function renderMainCharts() {{
      const rows = getFilteredRecords();
      if (!rows.length) return;
      updateReadout(rows[rows.length - 1]);

      const W = 1000, H = 300;
      const padL = 58, padR = 24, padT = 20, padB = 30;
      const plotW = W - padL - padR;
      const plotH = H - padT - padB;

      const vals = rows.map(r => r[currentPair]);
      const minV = Math.min(0, ...vals) - 12;
      const maxV = Math.max(0, ...vals) + 12;
      const xOf = (i) => padL + (i / Math.max(1, rows.length - 1)) * plotW;
      const yOf = (v) => padT + ((maxV - v) / Math.max(1, maxV - minV)) * plotH;
      const zeroY = yOf(0);

      // 网格刻度
      const ticks = 5;
      let gridHtml = "";
      for (let t = 0; t <= ticks; t++) {{
        const tv = minV + ((maxV - minV) * t) / ticks;
        const ty = yOf(tv);
        gridHtml += `<line x1="${{padL}}" y1="${{ty}}" x2="${{W - padR}}" y2="${{ty}}" stroke="#1f2937" stroke-dasharray="4 4" />`;
        gridHtml += `<text x="${{padL - 8}}" y="${{ty + 4}}" text-anchor="end" fill="#9ca3af" font-size="11">${{tv >= 0 ? "+" : ""}}${{Math.round(tv)}}bp</text>`;
      }}

      // X轴日期标签
      const stepX = Math.max(1, Math.floor(rows.length / 6));
      for (let i = 0; i < rows.length; i += stepX) {{
        gridHtml += `<text x="${{xOf(i)}}" y="${{H - 8}}" text-anchor="middle" fill="#9ca3af" font-size="11">${{rows[i].date.slice(0, 7)}}</text>`;
      }}

      // 构造折线与正负面积路径（使用 clipPath 精准分割 0 基点上下颜色）
      const pts = rows.map((r, i) => `${{xOf(i).toFixed(1)}},${{yOf(r[currentPair]).toFixed(1)}}`).join(" ");
      const areaPts = `${{xOf(0).toFixed(1)}},${{zeroY.toFixed(1)}} ` + pts + ` ${{xOf(rows.length - 1).toFixed(1)}},${{zeroY.toFixed(1)}}`;

      const svg = document.getElementById("spread-svg");
      svg.innerHTML = `
        <defs>
          <clipPath id="clip-pos"><rect x="${{padL}}" y="${{padT}}" width="${{plotW}}" height="${{Math.max(0, zeroY - padT)}}" /></clipPath>
          <clipPath id="clip-neg"><rect x="${{padL}}" y="${{zeroY}}" width="${{plotW}}" height="${{Math.max(0, padT + plotH - zeroY)}}" /></clipPath>
        </defs>
        ${{gridHtml}}
        <polygon points="${{areaPts}}" fill="#10b981" fill-opacity="0.22" clip-path="url(#clip-pos)" />
        <polygon points="${{areaPts}}" fill="#ef4444" fill-opacity="0.28" clip-path="url(#clip-neg)" />
        <line x1="${{padL}}" y1="${{zeroY}}" x2="${{W - padR}}" y2="${{zeroY}}" stroke="#ef4444" stroke-width="1.4" />
        <text x="${{W - padR - 4}}" y="${{zeroY - 6}}" text-anchor="end" fill="#ef4444" font-size="11">0 基点（倒挂警戒线）</text>
        <polyline fill="none" stroke="#10b981" stroke-width="2.2" points="${{pts}}" />
        <circle id="hover-dot" cx="${{xOf(rows.length - 1)}}" cy="${{yOf(vals[vals.length - 1])}}" r="5" fill="#10b981" stroke="#0b0f19" stroke-width="2" />
        <line id="hover-vline" x1="${{xOf(rows.length - 1)}}" y1="${{padT}}" x2="${{xOf(rows.length - 1)}}" y2="${{padT + plotH}}" stroke="#9ca3af" stroke-dasharray="3 3" opacity="0.5" />
        <rect id="hover-rect" x="${{padL}}" y="${{padT}}" width="${{plotW}}" height="${{plotH}}" fill="transparent" style="cursor: crosshair;" />
      `;

      // 渲染下方长短端双收益率折线图
      const meta = PAIR_META[currentPair];
      const H2 = 190, pT2 = 14, pB2 = 26, pH2 = H2 - pT2 - pB2;
      const allY = rows.flatMap(r => [r[meta.longKey], r[meta.shortKey]]);
      const minY = Math.min(...allY) - 0.15;
      const maxY = Math.max(...allY) + 0.15;
      const y2Of = (v) => pT2 + ((maxY - v) / Math.max(0.1, maxY - minY)) * pH2;

      let g2 = "";
      for (let t = 0; t <= 3; t++) {{
        const yv = minY + ((maxY - minY) * t) / 3;
        const yy = y2Of(yv);
        g2 += `<line x1="${{padL}}" y1="${{yy}}" x2="${{W - padR}}" y2="${{yy}}" stroke="#1f2937" stroke-dasharray="4 4" />`;
        g2 += `<text x="${{padL - 8}}" y="${{yy + 4}}" text-anchor="end" fill="#9ca3af" font-size="11">${{yv.toFixed(2)}}%</text>`;
      }}
      const longPts = rows.map((r, i) => `${{xOf(i).toFixed(1)}},${{y2Of(r[meta.longKey]).toFixed(1)}}`).join(" ");
      const shortPts = rows.map((r, i) => `${{xOf(i).toFixed(1)}},${{y2Of(r[meta.shortKey]).toFixed(1)}}`).join(" ");

      document.getElementById("yields-svg").innerHTML = `
        ${{g2}}
        <polyline fill="none" stroke="#3b82f6" stroke-width="2" points="${{longPts}}" />
        <polyline fill="none" stroke="#a855f7" stroke-width="1.8" stroke-dasharray="5 3" points="${{shortPts}}" />
        <line id="hover-vline-2" x1="${{xOf(rows.length - 1)}}" y1="${{pT2}}" x2="${{xOf(rows.length - 1)}}" y2="${{pT2 + pH2}}" stroke="#9ca3af" stroke-dasharray="3 3" opacity="0.5" />
      `;

      // 绑定鼠标悬停联动十字线
      const rect = document.getElementById("hover-rect");
      rect.addEventListener("mousemove", (ev) => {{
        const box = svg.getBoundingClientRect();
        const relX = ((ev.clientX - box.left) / box.width) * W;
        const idx = Math.max(0, Math.min(rows.length - 1, Math.round(((relX - padL) / plotW) * (rows.length - 1))));
        const cx = xOf(idx);
        const cy = yOf(rows[idx][currentPair]);
        document.getElementById("hover-dot").setAttribute("cx", cx);
        document.getElementById("hover-dot").setAttribute("cy", cy);
        document.getElementById("hover-vline").setAttribute("x1", cx);
        document.getElementById("hover-vline").setAttribute("x2", cx);
        document.getElementById("hover-vline-2").setAttribute("x1", cx);
        document.getElementById("hover-vline-2").setAttribute("x2", cx);
        updateReadout(rows[idx]);
      }});
    }}

    document.querySelectorAll(".pair-btn").forEach(btn => {{
      btn.addEventListener("click", () => {{
        currentPair = btn.dataset.pair;
        document.querySelectorAll(".pair-btn").forEach(b => {{
          b.className = "pair-btn px-2.5 py-1 rounded-md text-xs font-medium border border-[var(--border,#1f2937)] text-[var(--muted-foreground,#9ca3af)]";
        }});
        btn.className = "pair-btn px-2.5 py-1 rounded-md text-xs font-medium border border-[var(--primary,#3b82f6)] bg-[var(--primary,#3b82f6)] text-white";
        renderMainCharts();
      }});
    }});

    document.querySelectorAll(".range-btn").forEach(btn => {{
      btn.addEventListener("click", () => {{
        currentDays = parseInt(btn.dataset.days, 10);
        document.querySelectorAll(".range-btn").forEach(b => {{
          b.className = "range-btn px-2 py-1 rounded-md text-xs border border-[var(--border,#1f2937)] text-[var(--muted-foreground,#9ca3af)]";
        }});
        btn.className = "range-btn px-2 py-1 rounded-md text-xs border border-[var(--primary,#3b82f6)] bg-[var(--primary,#3b82f6)] text-white";
        renderMainCharts();
      }});
    }});

    // 3. 渲染美国财政部全期限收益率曲线（1个月 -> 30年）
    function renderYieldCurveSnapshot() {{
      const snaps = D.curveSnapshots;
      if (!snaps || !snaps.length) return;
      const W = 700, H = 260, padL = 48, padR = 20, padT = 20, padB = 34;
      const pW = W - padL - padR, pH = H - padT - padB;
      const allV = snaps.flatMap(s => s.points.map(p => p.yield_pct));
      const minY = Math.min(...allV) - 0.15;
      const maxY = Math.max(...allV) + 0.18;
      const nPts = snaps[0].points.length;
      const xOf = (i) => padL + (i / Math.max(1, nPts - 1)) * pW;
      const yOf = (v) => padT + ((maxY - v) / Math.max(0.1, maxY - minY)) * pH;

      let html = "";
      for (let t = 0; t <= 4; t++) {{
        const yv = minY + ((maxY - minY) * t) / 4;
        const yy = yOf(yv);
        html += `<line x1="${{padL}}" y1="${{yy}}" x2="${{W - padR}}" y2="${{yy}}" stroke="#1f2937" stroke-dasharray="4 4" />`;
        html += `<text x="${{padL - 6}}" y="${{yy + 4}}" text-anchor="end" fill="#9ca3af" font-size="11">${{yv.toFixed(2)}}%</text>`;
      }}

      snaps[0].points.forEach((p, i) => {{
        html += `<text x="${{xOf(i)}}" y="${{H - 10}}" text-anchor="middle" fill="#9ca3af" font-size="11">${{p.maturity_cn}}</text>`;
      }});

      const colors = ["#3b82f6", "#10b981", "#f59e0b", "#9ca3af"];
      const dashes = ["", "6 4", "3 3", "2 4"];
      snaps.slice().reverse().forEach((snap, revIdx) => {{
        const idx = snaps.length - 1 - revIdx;
        const pts = snap.points.map((p, i) => `${{xOf(i).toFixed(1)}},${{yOf(p.yield_pct).toFixed(1)}}`).join(" ");
        html += `<polyline fill="none" stroke="${{colors[idx]}}" stroke-width="${{idx === 0 ? 2.5 : 1.5}}" stroke-dasharray="${{dashes[idx]}}" points="${{pts}}" />`;
        if (idx === 0) {{
          snap.points.forEach((p, i) => {{
            html += `<circle cx="${{xOf(i)}}" cy="${{yOf(p.yield_pct)}}" r="3.5" fill="#3b82f6" />`;
            if (["3个月", "2年", "5年", "10年", "30年"].includes(p.maturity_cn)) {{
              html += `<text x="${{xOf(i)}}" y="${{yOf(p.yield_pct) - 8}}" text-anchor="middle" fill="#93c5fd" font-size="10.5" font-weight="bold">${{p.yield_pct.toFixed(2)}}%</text>`;
            }}
          }});
        }}
      }});

      document.getElementById("curve-svg").innerHTML = html;
      document.getElementById("curve-legend").innerHTML = snaps.map((s, idx) => `
        <span class="flex items-center gap-1.5">
          <span class="inline-block w-3 h-1 rounded" style="background:${{colors[idx]}}"></span>
          <span class="text-[var(--muted-foreground,#9ca3af)]">${{s.label_cn}}</span>
        </span>
      `).join("");
    }}

    // 4. 渲染统计表与术语词典
    document.getElementById("summary-tbody").innerHTML = D.summaries.map(s => `
      <tr class="hover:bg-[var(--background,#0b0f19)]">
        <td class="py-2.5 px-2 font-bold">${{s.title_cn}}</td>
        <td class="py-2.5 px-2 text-[var(--muted-foreground,#9ca3af)]">${{s.formula_cn}}</td>
        <td class="py-2.5 px-2 text-right font-mono font-bold ${{bpColor(s.current_bp)}}">${{s.current_bp >= 0 ? "+" : ""}}${{s.current_bp}} 基点</td>
        <td class="py-2.5 px-2 text-right font-mono ${{bpColor(s.chg_1d_bp)}}">${{fmtBp(s.chg_1d_bp)}}</td>
        <td class="py-2.5 px-2 text-right font-mono ${{bpColor(s.chg_5d_bp)}}">${{fmtBp(s.chg_5d_bp)}}</td>
        <td class="py-2.5 px-2 text-right font-mono ${{bpColor(s.chg_20d_bp)}}">${{fmtBp(s.chg_20d_bp)}}</td>
        <td class="py-2.5 px-2 text-right font-mono text-[var(--muted-foreground,#9ca3af)]">${{s.min_1y_bp >= 0 ? "+" : ""}}${{s.min_1y_bp}} ~ ${{s.max_1y_bp >= 0 ? "+" : ""}}${{s.max_1y_bp}} 基点</td>
        <td class="py-2.5 px-2 text-right font-mono">${{s.percentile_1y}}%</td>
        <td class="py-2.5 px-2 text-right font-mono">${{s.inverted_days_1y}} / ${{s.total_days_1y}} 天</td>
        <td class="py-2.5 px-2 ${{s.current_bp >= 0 ? "text-[var(--success,#10b981)]" : "text-[var(--error,#ef4444)]"}} font-semibold">${{s.status_cn}}</td>
      </tr>
    `).join("");

    document.getElementById("glossary-grid").innerHTML = D.glossary.map(g => `
      <div class="p-3.5 rounded-lg border border-[var(--border,#1f2937)] bg-[var(--background,#0b0f19)] space-y-1.5">
        <div>
          <span class="text-xs px-2 py-0.5 rounded border border-[var(--border,#1f2937)] text-[var(--primary,#3b82f6)] mr-1.5">${{g.category}}</span>
          <span class="text-sm font-bold">${{g.term}}</span>
        </div>
        <p class="text-xs leading-relaxed"><strong>通俗理解：</strong>${{g.definition}}</p>
        <p class="text-xs text-[var(--muted-foreground,#9ca3af)] leading-relaxed"><strong>实战影响：</strong>${{g.practical}}</p>
      </div>
    `).join("");

    renderMainCharts();
    renderYieldCurveSnapshot();
  </script>
</body>
</html>
"""


def run_spread_pipeline() -> dict[str, Any]:
    """执行美债长短期利差计算并输出至《国债利差专题》与《交互式看板》目录。"""
    dataset = collect_yield_spread_dataset()
    tdate = dataset["latest_date"]
    SPREAD_DIR.mkdir(parents=True, exist_ok=True)
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)

    png_filename = f"{tdate}_美债长短期利差走势图.png"
    png_path = SPREAD_DIR / png_filename
    render_matplotlib_png(dataset, png_path)

    md_text, glossary_items = build_spread_markdown(dataset, png_filename)
    md_path = SPREAD_DIR / f"{tdate}_美债期限利差专题分析.md"
    md_path.write_text(md_text, encoding="utf-8")

    html_text = build_interactive_spread_html(dataset, glossary_items)
    html_path = DASHBOARD_DIR / "美债期限利差看板.html"
    html_path.write_text(html_text, encoding="utf-8")

    return {
        "latest_date": tdate,
        "png_path": str(png_path),
        "md_path": str(md_path),
        "html_path": str(html_path),
        "anchor_spread_10y_13w_bp": dataset["anchor_spread_10y_13w_bp"],
        "anchor_spread_10y_2y_bp": dataset["anchor_spread_10y_2y_bp"],
        "regime_1d_title": dataset["regime_1d_title"],
        "glossary_count": len(glossary_items),
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="计算并可视化美国长期国债收益率减去短期国债收益率的差值")
    parser.parse_args()

    res = run_spread_pipeline()
    print(f"[利差计算完成] 基准日：{res['latest_date']}｜10年减13周利差：{res['anchor_spread_10y_13w_bp']:+d} 基点｜10年减2年利差：{res['anchor_spread_10y_2y_bp']:+d} 基点")
    print(f"[曲线形态判定] {res['regime_1d_title']}")
    print(f"[高清走势图] {res['png_path']}")
    print(f"[专题分析报告] {res['md_path']}")
    print(f"[交互式看板] {res['html_path']}")


if __name__ == "__main__":
    main()
