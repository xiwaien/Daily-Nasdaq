"""纳斯达克核心科技股、跨资产市场情绪与官方宏观政策数据采集引擎（全中文语序增强版）。"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

# 四大基准指数与 19 家核心科技企业（内置标准中文简称与中文板块名）
SYMBOLS: dict[str, list[tuple[str, str, str]]] = {
    "Indices": [
        ("^IXIC", "Nasdaq Composite", "纳斯达克综合指数"),
        ("^NDX", "Nasdaq-100", "纳斯达克100指数"),
        ("^SOX", "PHLX Semiconductor", "费城半导体指数"),
        ("^GSPC", "S&P 500", "标普500指数"),
    ],
    "Mega-Cap Tech": [
        ("AAPL", "Apple", "苹果"),
        ("MSFT", "Microsoft", "微软"),
        ("NVDA", "NVIDIA", "英伟达"),
        ("AMZN", "Amazon", "亚马逊"),
        ("GOOGL", "Alphabet", "谷歌母公司"),
        ("META", "Meta Platforms", "脸书母公司"),
        ("TSLA", "Tesla", "特斯拉"),
    ],
    "Semiconductors": [
        ("AVGO", "Broadcom", "博通"),
        ("AMD", "AMD", "超威半导体"),
        ("QCOM", "Qualcomm", "高通"),
        ("MU", "Micron Technology", "美光科技"),
        ("ASML", "ASML Holding", "阿斯麦"),
        ("INTC", "Intel", "英特尔"),
    ],
    "Software & Growth": [
        ("NFLX", "Netflix", "奈飞"),
        ("ADBE", "Adobe", "奥多比"),
        ("PANW", "Palo Alto Networks", "派拓网络"),
        ("CRWD", "CrowdStrike", "众击安全"),
        ("PLTR", "Palantir", "帕兰提尔"),
        ("SNPS", "Synopsys", "新思科技"),
    ],
}

CATEGORY_CN_MAP: dict[str, str] = {
    "Indices": "核心基准指数",
    "Mega-Cap Tech": "科技七巨头",
    "Semiconductors": "半导体与芯片设备",
    "Software & Growth": "软件、云计算与网安",
}

# 市场情绪与跨资产宏观风向标标的池
SENTIMENT_SYMBOLS: list[tuple[str, str, str, str]] = [
    ("^VIX", "标普500恐慌指数", "期权恐慌与波动", "数值越高代表市场避险恐慌越重，低于20偏乐观，高于30属恐慌区间"),
    ("^VXN", "纳指100波动率指数", "期权恐慌与波动", "专门衡量纳斯达克科技权重股的隐含波动与期权对冲热度"),
    ("^SKEW", "黑天鹅尾部偏度指数", "期权恐慌与波动", "衡量机构买入极端暴跌保护期权的意愿，高于140提示尾部防范升温"),
    ("DX-Y.NYB", "美元指数", "汇率与全球流动性", "反映美元对主要货币强弱，走强往往压制跨国科技股海外折算收益"),
    ("^IRX", "13周美债收益率", "利率与美联储预期", "紧贴美联储近期基准利率预期的短端资金利率指标"),
    ("^FVX", "5年期美债收益率", "利率与美联储预期", "反映市场对未来中期利率路径与信贷成本的定价"),
    ("^TNX", "10年期美债收益率", "利率与美联储预期", "全球科技股估值折现之锚，收益率上行直接压制高估值成长股"),
    ("^TYX", "30年期美债收益率", "利率与美联储预期", "反映超长期经济增长、通胀粘性与财政发债供给压力"),
    ("GC=F", "纽约黄金期货", "避险与通胀预期", "衡量央行购金、地缘避险需求及实际利率预期"),
    ("CL=F", "纽约原油期货", "避险与通胀预期", "衡量能源通胀输入压力与全球工业活动景气度"),
    ("BTC-USD", "比特币价格", "流动性与风险偏好", "全天候交易的高弹性风险资产，反映全球投机流动性松紧"),
    ("^RUT", "罗素2000小盘股指数", "跨市场广度与轮动", "反映美国本土中小市值企业表现及内需风险偏好"),
    ("^DJI", "道琼斯工业平均指数", "跨市场广度与轮动", "反映传统工业、金融与消费蓝筹股表现，用于对比科技与价值轮动"),
    ("HYG", "高收益公司债基金", "债市信用风险偏好", "代表高风险企业信用债价格，走强意味着资金愿意承担信用风险"),
    ("TLT", "20年期以上长端美债基金", "债市信用风险偏好", "代表长期国债避险资产价格，与高收益债比值可量化风险偏好"),
]

# 19 家核心科技股美国证监会官方 CIK 编码（用于拉取法定 8-K / 6-K 重大事项公告）
SEC_CIKS: dict[str, str] = {
    "AAPL": "0000320193",
    "MSFT": "0000789019",
    "NVDA": "0001045810",
    "AMZN": "0001018724",
    "GOOGL": "0001652044",
    "META": "0001326801",
    "TSLA": "0001318605",
    "AVGO": "0001730168",
    "AMD": "0000002488",
    "QCOM": "0000804328",
    "MU": "0000723125",
    "ASML": "0000937966",
    "INTC": "0000050863",
    "NFLX": "0001065280",
    "ADBE": "0000796343",
    "PANW": "0001327567",
    "CRWD": "0001535527",
    "PLTR": "0001321655",
    "SNPS": "0000883241",
}

SEC_8K_ITEM_CN: dict[str, str] = {
    "1.01": "签署重大具有法律约束力的协议（如并购或战略合作）",
    "1.02": "终止重大商业或并购协议",
    "2.01": "完成重大资产收购或处置交割",
    "2.02": "正式披露季度或年度经营业绩与财务状况",
    "2.03": "新增重大直接财务债务或表外融资义务",
    "2.05": "宣布重大业务重组、关停或人员调整计划",
    "3.02": "未注册股权证券发行事项",
    "5.02": "董事或核心高级管理人员离任、复职或新任变动",
    "5.03": "修订公司章程或治理细则",
    "5.07": "年度或特别股东大会表决结果披露",
    "7.01": "依据公平披露准则发布的官方投资者沟通文件",
    "8.01": "公司主动披露的其他法定重大事项",
    "9.01": "随附法定财务报表及协议附件清单",
}


def _http_get_text(url: str, user_agent: str = "Mozilla/5.0", timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def fetch_symbol(symbol: str, name: str, name_cn: str, category: str) -> dict[str, Any]:
    """从 Yahoo Finance 获取过去一年日线行情并计算全套均线、波动率与年初至今指标。"""
    encoded = urllib.parse.quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=1y&interval=1d"
    payload = json.loads(_http_get_text(url))

    result = payload["chart"]["result"][0]
    meta = result["meta"]
    timestamps = result["timestamp"]
    quote = result["indicators"]["quote"][0]
    closes_raw = quote["close"]
    highs_raw = quote["high"]
    lows_raw = quote["low"]
    volumes_raw = quote["volume"]

    rows = [
        (
            datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d"),
            c,
            h,
            l,
            v if v is not None else 0,
        )
        for ts, c, h, l, v in zip(timestamps, closes_raw, highs_raw, lows_raw, volumes_raw)
        if c is not None
    ]
    closes = [r[1] for r in rows]
    volumes = [r[4] for r in rows]
    last_date = rows[-1][0]
    last_close = closes[-1]
    prev_close = closes[-2]
    last_high = rows[-1][2]
    last_low = rows[-1][3]

    chg_1d = (last_close - prev_close) / prev_close * 100.0
    chg_5d = (last_close - closes[-6]) / closes[-6] * 100.0 if len(closes) >= 6 else None
    chg_20d = (last_close - closes[-21]) / closes[-21] * 100.0 if len(closes) >= 21 else None

    prev_year_rows = [r[1] for r in rows if r[0].startswith(str(int(last_date[:4]) - 1) + "-12")]
    ytd_pct = ((last_close - prev_year_rows[-1]) / prev_year_rows[-1] * 100.0) if prev_year_rows else None

    ma20 = statistics.mean(closes[-20:]) if len(closes) >= 20 else None
    ma50 = statistics.mean(closes[-50:]) if len(closes) >= 50 else None
    ma200 = statistics.mean(closes[-200:]) if len(closes) >= 200 else None
    dist_ma20 = (last_close - ma20) / ma20 * 100.0 if ma20 else None
    dist_ma50 = (last_close - ma50) / ma50 * 100.0 if ma50 else None
    dist_ma200 = (last_close - ma200) / ma200 * 100.0 if ma200 else None

    avg_vol20 = statistics.mean(volumes[-21:-1]) if len(volumes) >= 21 else None
    rel_vol = (volumes[-1] / avg_vol20) if (avg_vol20 and avg_vol20 > 0) else None

    vol_20d = None
    if len(closes) >= 21:
        rets = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(-20, 0)]
        vol_20d = statistics.stdev(rets) * math.sqrt(252) * 100.0

    high_52w = meta.get("fiftyTwoWeekHigh")
    dist_52w_high = (last_close - high_52w) / high_52w * 100.0 if high_52w else None

    return {
        "category": category,
        "category_cn": CATEGORY_CN_MAP.get(category, category),
        "symbol": symbol,
        "name": name,
        "name_cn": name_cn,
        "display_cn": f"{name_cn} ({symbol})",
        "date": last_date,
        "close": round(last_close, 2),
        "prev_close": round(prev_close, 2),
        "low": round(last_low, 2) if last_low is not None else None,
        "high": round(last_high, 2) if last_high is not None else None,
        "chg_1d_pct": round(chg_1d, 2),
        "chg_5d_pct": round(chg_5d, 2) if chg_5d is not None else None,
        "chg_20d_pct": round(chg_20d, 2) if chg_20d is not None else None,
        "ytd_pct": round(ytd_pct, 2) if ytd_pct is not None else None,
        "ma20": round(ma20, 2) if ma20 is not None else None,
        "dist_ma20_pct": round(dist_ma20, 2) if dist_ma20 is not None else None,
        "ma50": round(ma50, 2) if ma50 is not None else None,
        "dist_ma50_pct": round(dist_ma50, 2) if dist_ma50 is not None else None,
        "ma200": round(ma200, 2) if ma200 is not None else None,
        "dist_ma200_pct": round(dist_ma200, 2) if dist_ma200 is not None else None,
        "volume": volumes[-1],
        "avg_vol_20d": round(avg_vol20) if avg_vol20 is not None else None,
        "rel_vol_20d": round(rel_vol, 2) if rel_vol is not None else None,
        "ann_vol_20d_pct": round(vol_20d, 2) if vol_20d is not None else None,
        "high_52w": round(high_52w, 2) if high_52w else None,
        "dist_52w_high_pct": round(dist_52w_high, 2) if dist_52w_high is not None else None,
    }


def _fetch_one_sentiment(item: tuple[str, str, str, str]) -> dict[str, Any]:
    symbol, name_cn, group_cn, meaning_cn = item
    encoded = urllib.parse.quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=3mo&interval=1d"
    payload = json.loads(_http_get_text(url))
    res = payload["chart"]["result"][0]
    ts_list = res["timestamp"]
    closes_raw = res["indicators"]["quote"][0]["close"]
    rows = [
        (datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d"), c)
        for t, c in zip(ts_list, closes_raw)
        if c is not None
    ]
    closes = [r[1] for r in rows]
    lc = closes[-1]
    pc = closes[-2]
    chg_1d = (lc - pc) / pc * 100.0
    chg_5d = (lc - closes[-6]) / closes[-6] * 100.0 if len(closes) >= 6 else None
    diff_1d = lc - pc
    return {
        "symbol": symbol,
        "name_cn": name_cn,
        "group_cn": group_cn,
        "meaning_cn": meaning_cn,
        "date": rows[-1][0],
        "close": round(lc, 2),
        "prev_close": round(pc, 2),
        "diff_1d": round(diff_1d, 2),
        "chg_1d_pct": round(chg_1d, 2),
        "chg_5d_pct": round(chg_5d, 2) if chg_5d is not None else None,
    }


def fetch_market_sentiment(core_results: list[dict[str, Any]]) -> dict[str, Any]:
    """并发抓取跨资产市场情绪指标并合成为纯正中文语序的情绪量化结论。"""
    indicators: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [(it[0], pool.submit(_fetch_one_sentiment, it)) for it in SENTIMENT_SYMBOLS]
        for sym, fut in futs:
            try:
                indicators.append(fut.result())
            except Exception as exc:
                errors.append({"symbol": sym, "error": str(exc)})

    by_sym = {x["symbol"]: x for x in indicators}
    stocks = [x for x in core_results if x["category"] != "Indices"]
    up_count = sum(1 for s in stocks if s["chg_1d_pct"] > 0)
    above_ma20 = sum(1 for s in stocks if (s.get("dist_ma20_pct") or -999) > 0)
    above_ma50 = sum(1 for s in stocks if (s.get("dist_ma50_pct") or -999) > 0)
    above_ma200 = sum(1 for s in stocks if (s.get("dist_ma200_pct") or -999) > 0)
    breadth_1d_pct = round(up_count / len(stocks) * 100.0, 1) if stocks else 0.0

    vix = by_sym.get("^VIX", {}).get("close")
    vix_chg = by_sym.get("^VIX", {}).get("chg_1d_pct")
    vxn = by_sym.get("^VXN", {}).get("close")
    skew = by_sym.get("^SKEW", {}).get("close")
    irx = by_sym.get("^IRX", {}).get("close")
    tnx = by_sym.get("^TNX", {}).get("close")
    tyx = by_sym.get("^TYX", {}).get("close")
    hyg = by_sym.get("HYG")
    tlt = by_sym.get("TLT")

    spread_10y_3m_bp = round((tnx - irx) * 100) if (tnx is not None and irx is not None) else None
    spread_30y_10y_bp = round((tyx - tnx) * 100) if (tyx is not None and tnx is not None) else None
    tech_vol_spread = round(vxn - vix, 2) if (vxn is not None and vix is not None) else None

    hyg_tlt_ratio = None
    hyg_tlt_chg_pct = None
    if hyg and tlt and tlt["close"] > 0 and tlt["prev_close"] > 0:
        curr_r = hyg["close"] / tlt["close"]
        prev_r = hyg["prev_close"] / tlt["prev_close"]
        hyg_tlt_ratio = round(curr_r, 4)
        hyg_tlt_chg_pct = round((curr_r - prev_r) / prev_r * 100.0, 2)

    # 综合情绪评分（0~100分，50分为中性）
    score = 50.0
    if vix is not None:
        # VIX=20 为中性基准，越低越乐观，越高越恐慌
        score += max(-22.0, min(18.0, (22.0 - vix) * 1.4))
    if vix_chg is not None and vix_chg <= -15.0:
        score += 8.0  # 恐慌指数单日骤降代表情绪急剧修复
    elif vix_chg is not None and vix_chg >= 15.0:
        score -= 8.0
    score += (breadth_1d_pct - 50.0) * 0.25
    if stocks:
        score += (above_ma50 / len(stocks) - 0.5) * 20.0
    if hyg_tlt_chg_pct is not None:
        score += max(-5.0, min(5.0, hyg_tlt_chg_pct * 4.0))
    score = round(max(5.0, min(95.0, score)), 1)

    if score < 30:
        regime_cn = "极度恐慌（防御避险为主）"
    elif score < 45:
        regime_cn = "偏空谨慎（波动高企、均线承压）"
    elif score < 60:
        if vix is not None and vix > 25 and breadth_1d_pct >= 75:
            regime_cn = "恐慌修复（超跌逼空回暖，但波动仍高）"
        else:
            regime_cn = "多空均衡（震荡整固阶段）"
    elif score < 75:
        regime_cn = "温和乐观（风险偏好改善）"
    else:
        regime_cn = "极度亢奋（警惕短线过热追高）"

    notes_cn: list[str] = []
    if vix is not None and vxn is not None:
        notes_cn.append(
            f"期权波动层面：标普500恐慌指数收于 {vix:.2f}（单日 {vix_chg:+.2f}%），纳指100波动率指数收于 {vxn:.2f}，科技股相对大盘仍保有 {tech_vol_spread:+.2f} 点的额外波动溢价。"
        )
    if skew is not None:
        skew_hint = "机构防范极端尾部暴跌的对冲需求偏高" if skew >= 140 else "尾部黑天鹅对冲需求处于常态区间"
        notes_cn.append(f"尾部风险层面：黑天鹅偏度指数报 {skew:.2f}，显示{skew_hint}。")
    if spread_10y_3m_bp is not None and tnx is not None:
        curve_hint = "收益率曲线维持正斜率（未倒挂）" if spread_10y_3m_bp >= 0 else "短端利率高于长端（曲线倒挂）"
        notes_cn.append(
            f"利率与美债层面：10年期美债收益率报 {tnx:.2f}%，10年期减13周美债期限利差为 {spread_10y_3m_bp:+d} 个基点，{curve_hint}。"
        )
    if hyg_tlt_ratio is not None and hyg_tlt_chg_pct is not None:
        credit_hint = "信用债表现优于长端国债，债市资金偏向承担风险" if hyg_tlt_chg_pct > 0 else "长端国债表现强于高收益债，债市资金偏向防御避险"
        notes_cn.append(f"跨资产信用层面：高收益公司债与长期国债比值报 {hyg_tlt_ratio:.4f}（单日 {hyg_tlt_chg_pct:+.2f}%），{credit_hint}。")

    return {
        "composite_score": score,
        "regime_cn": regime_cn,
        "breadth_1d_pct": breadth_1d_pct,
        "up_stocks": up_count,
        "total_stocks": len(stocks),
        "above_ma20_count": above_ma20,
        "above_ma50_count": above_ma50,
        "above_ma200_count": above_ma200,
        "spread_10y_3m_bp": spread_10y_3m_bp,
        "spread_30y_10y_bp": spread_30y_10y_bp,
        "tech_vol_spread": tech_vol_spread,
        "hyg_tlt_ratio": hyg_tlt_ratio,
        "hyg_tlt_chg_pct": hyg_tlt_chg_pct,
        "summary_notes_cn": notes_cn,
        "indicators": indicators,
        "errors": errors,
    }


def _parse_pubdate(raw_date: str) -> str | None:
    if not raw_date:
        return None
    try:
        dt = parsedate_to_datetime(raw_date.strip())
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return raw_date[:10] if len(raw_date) >= 10 else None


def fetch_official_policy_sources(reference_date_str: str) -> dict[str, Any]:
    """仅从央行、财政与统计部委、联邦公报及美国证监会抓取纯官方权威资讯（杜绝小道消息）。"""
    ref_dt = datetime.strptime(reference_date_str, "%Y-%m-%d")
    cutoff_45d = (ref_dt - timedelta(days=45)).strftime("%Y-%m-%d")
    cutoff_14d = (ref_dt - timedelta(days=14)).strftime("%Y-%m-%d")

    official_data: dict[str, Any] = {
        "采集原则": "仅收录美联储、纽约联储、美国联邦公报、美国商务部工业与安全局、美国贸易代表办公室、美国经济分析局、欧洲央行及美国证监会法定公告，严禁混入未经官方证实的市场传闻。",
        "nyfed_rates": [],
        "fed_monetary_and_speeches": [],
        "federal_register_trade_tech": [],
        "ustr_and_bea_releases": [],
        "ecb_releases": [],
        "sec_8k_filings": [],
        "errors": [],
    }

    # 1. 纽约联储官方隔夜基准利率
    try:
        nyfed = json.loads(
            _http_get_text("https://markets.newyorkfed.org/api/rates/all/latest.json", "NasdaqTechResearchDesk/1.0")
        )
        rate_name_map = {
            "EFFR": "联邦基金有效利率（EFFR）",
            "SOFR": "担保隔夜融资利率（SOFR）",
            "OBFR": "隔夜银行融资利率（OBFR）",
            "TGCR": "三方一般抵押品利率（TGCR）",
            "BGCR": "广义一般抵押品利率（BGCR）",
        }
        for item in nyfed.get("refRates", []):
            rtype = item.get("type")
            if rtype in rate_name_map and item.get("percentRate") is not None:
                official_data["nyfed_rates"].append(
                    {
                        "type": rtype,
                        "name_cn": rate_name_map[rtype],
                        "effective_date": item.get("effectiveDate"),
                        "rate_pct": item.get("percentRate"),
                        "volume_billions": item.get("volumeInBillions"),
                    }
                )
    except Exception as exc:
        official_data["errors"].append({"source": "纽约联储利率接口", "error": str(exc)})

    # 2. 美联储货币政策声明、纪要与理事官方演讲 RSS
    for source_cn, rss_url in [
        ("美联储货币政策官方公报", "https://www.federalreserve.gov/feeds/press_monetary.xml"),
        ("美联储官员正式演讲稿", "https://www.federalreserve.gov/feeds/speeches.xml"),
    ]:
        try:
            raw = _http_get_text(rss_url).lstrip("\ufeff")
            root = ET.fromstring(raw)
            for it in root.findall(".//item")[:6]:
                pdate = _parse_pubdate(it.findtext("pubDate") or "")
                if pdate and pdate >= cutoff_45d:
                    official_data["fed_monetary_and_speeches"].append(
                        {
                            "source_cn": source_cn,
                            "date": pdate,
                            "title_raw": (it.findtext("title") or "").strip(),
                            "description_raw": (it.findtext("description") or "").strip(),
                            "link": (it.findtext("link") or "").strip(),
                        }
                    )
        except Exception as exc:
            official_data["errors"].append({"source": source_cn, "error": str(exc)})

    # 3. 美国联邦公报官方行政法规（商务部 BIS 出口管制与美国贸易代表办公室关税公告）
    try:
        fr_url = (
            "https://www.federalregister.gov/api/v1/documents.json?per_page=8&order=newest"
            "&conditions[agencies][]=industry-and-security-bureau"
            "&conditions[agencies][]=trade-representative-office-of-united-states"
        )
        fr_json = json.loads(_http_get_text(fr_url, "NasdaqTechResearchDesk/1.0"))
        for doc in fr_json.get("results", []):
            pdate = doc.get("publication_date")
            if pdate and pdate >= cutoff_45d:
                official_data["federal_register_trade_tech"].append(
                    {
                        "source_cn": "美国联邦公报（商务部与贸易代表办公室法定文件）",
                        "date": pdate,
                        "doc_type": doc.get("type"),
                        "title_raw": doc.get("title"),
                        "abstract_raw": doc.get("abstract"),
                        "link": doc.get("html_url"),
                    }
                )
    except Exception as exc:
        official_data["errors"].append({"source": "美国联邦公报接口", "error": str(exc)})

    # 4. 美国贸易代表办公室（USTR）与美国经济分析局（BEA）RSS
    for source_cn, rss_url in [
        ("美国贸易代表办公室（USTR）", "https://ustr.gov/rss.xml"),
        ("美国经济分析局（BEA）", "https://apps.bea.gov/rss/rss.xml"),
    ]:
        try:
            raw = _http_get_text(rss_url).lstrip("\ufeff")
            root = ET.fromstring(raw)
            for it in root.findall(".//item")[:8]:
                pdate = _parse_pubdate(it.findtext("pubDate") or "")
                if pdate and pdate >= cutoff_45d:
                    official_data["ustr_and_bea_releases"].append(
                        {
                            "source_cn": source_cn,
                            "date": pdate,
                            "title_raw": (it.findtext("title") or "").strip(),
                            "link": (it.findtext("link") or "").strip(),
                        }
                    )
        except Exception as exc:
            official_data["errors"].append({"source": source_cn, "error": str(exc)})

    # 5. 欧洲央行（ECB）货币政策公报 RSS
    try:
        raw = _http_get_text("https://www.ecb.europa.eu/rss/press.html").lstrip("\ufeff")
        root = ET.fromstring(raw)
        for it in root.findall(".//item")[:5]:
            pdate = _parse_pubdate(it.findtext("pubDate") or "")
            if pdate and pdate >= cutoff_45d:
                official_data["ecb_releases"].append(
                    {
                        "source_cn": "欧洲中央银行官方公报",
                        "date": pdate,
                        "title_raw": (it.findtext("title") or "").strip(),
                        "link": (it.findtext("link") or "").strip(),
                    }
                )
    except Exception as exc:
        official_data["errors"].append({"source": "欧洲央行公报", "error": str(exc)})

    # 6. 19 家核心科技企业近 14 天美国证监会 8-K / 6-K / 425 重大法定披露（并发采集）
    name_lookup = {
        sym: name_cn
        for items in SYMBOLS.values()
        for sym, _, name_cn in items
    }

    def _fetch_sec_for_company(sym_cik: tuple[str, str]) -> list[dict[str, Any]]:
        sym, cik = sym_cik
        sec_url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        sec_json = json.loads(
            _http_get_text(sec_url, "NasdaqTechResearchDesk/1.0 (official-filings-monitor@example.com)")
        )
        recent = sec_json.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        items_arr = recent.get("items", [])
        acc_nums = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])
        out_rows: list[dict[str, Any]] = []
        seen_425_dates: set[str] = set()

        for form, fdate, item_codes, acc, pdoc in zip(
            forms[:35], dates[:35], items_arr[:35], acc_nums[:35], primary_docs[:35]
        ):
            if fdate < cutoff_14d:
                continue
            if form in ("8-K", "8-K/A", "6-K"):
                if isinstance(item_codes, str):
                    codes = [c.strip() for c in item_codes.split(",") if c.strip()]
                elif isinstance(item_codes, list):
                    codes = [str(c).strip() for c in item_codes if str(c).strip()]
                else:
                    codes = []
                cn_clauses = [SEC_8K_ITEM_CN.get(c, f"条款 {c}") for c in codes if c != "9.01"]
                if not cn_clauses and codes:
                    cn_clauses = [SEC_8K_ITEM_CN.get(c, f"条款 {c}") for c in codes]
                acc_clean = acc.replace("-", "")
                filing_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}/{pdoc}"
                out_rows.append(
                    {
                        "symbol": sym,
                        "name_cn": name_lookup.get(sym, sym),
                        "filing_date": fdate,
                        "form": form,
                        "item_codes": codes,
                        "items_cn": "；".join(cn_clauses) if cn_clauses else "法定临时重大事项披露",
                        "url": filing_url,
                    }
                )
            elif form == "425" and fdate not in seen_425_dates:
                seen_425_dates.add(fdate)
                acc_clean = acc.replace("-", "")
                filing_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}/{pdoc}"
                out_rows.append(
                    {
                        "symbol": sym,
                        "name_cn": name_lookup.get(sym, sym),
                        "filing_date": fdate,
                        "form": "425",
                        "item_codes": ["425"],
                        "items_cn": "上市公司重大换股并购或合并事项法定披露文件",
                        "url": filing_url,
                    }
                )
        return out_rows

    with ThreadPoolExecutor(max_workers=6) as pool:
        sec_futs = [(sym, pool.submit(_fetch_sec_for_company, (sym, cik))) for sym, cik in SEC_CIKS.items()]
        for sym, fut in sec_futs:
            try:
                official_data["sec_8k_filings"].extend(fut.result())
            except Exception as exc:
                official_data["errors"].append({"source": f"SEC-{sym}", "error": str(exc)})

    official_data["sec_8k_filings"].sort(key=lambda x: (x["filing_date"], x["symbol"]), reverse=True)
    return official_data


def collect_all() -> dict[str, Any]:
    """统一执行指数、核心个股、市场情绪与官方政策信源的全量并发采集。"""
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    tasks: list[tuple[str, str, str, str]] = [
        (symbol, name, name_cn, category)
        for category, items in SYMBOLS.items()
        for symbol, name, name_cn in items
    ]
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [(t[0], pool.submit(fetch_symbol, *t)) for t in tasks]
        for sym, fut in futs:
            try:
                results.append(fut.result())
            except Exception as exc:
                errors.append({"symbol": sym, "error": str(exc)})

    latest_date = results[0]["date"] if results else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    market_sentiment = fetch_market_sentiment(results)
    official_sources = fetch_official_policy_sources(latest_date)

    return {
        "latest_trading_date": latest_date,
        "language_mode": "zh-CN-idiomatic",
        "data": results,
        "market_sentiment": market_sentiment,
        "official_sources": official_sources,
        "errors": errors,
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="采集纳斯达克核心数据、市场情绪与官方政策信源")
    parser.add_argument("--out", type=str, help="可选：将 JSON 结果以 UTF-8 直接写入指定文件路径")
    args = parser.parse_args()

    payload = collect_all()
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
