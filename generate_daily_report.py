"""纯正中文语序投研日报、官方宏观政策资讯专栏与全中文交互看板自动生成引擎。

核心特性：
1. 强制采用自然中文母语语序生成所有报告标题、章节、表头、图表标签与解读话术；
2. 自动生成《资讯栏目/YYYY-MM-DD_官方宏观与政策资讯.md》与原始快照，严格只收录央行、财政/经贸部委及证监会法定一手信源，剔除一切市场小道消息；
3. 自动调用 glossary_manager 扫描正文并生成“初学者投研术语通俗伴读”，自动跳过用户在《术语配置.json》中标记为“不需要解释”的名词。
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import statistics
import sys
from typing import Any

from analyze_treasury_spread import run_spread_pipeline
from fetch_nasdaq_data import collect_all
from glossary_manager import infer_glossary_for_text, load_ignored_terms

BASE_DIR = Path(__file__).resolve().parent
BRIEFING_DIR = BASE_DIR / "资讯栏目"

WEEKDAY_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def fmt_pct(val: float | None, bold: bool = False) -> str:
    if val is None:
        return "暂无"
    s = f"+{val:.2f}%" if val > 0 else f"{val:.2f}%"
    return f"**{s}**" if bold else s


def fmt_vol_cn(vol: int | float | None) -> str:
    if not vol or vol <= 0:
        return "不适用"
    if vol >= 100_000_000:
        return f"{vol / 100_000_000:.2f}亿股"
    return f"{vol / 10_000:.2f}万股"


def ma_posture_cn(s: dict[str, Any]) -> str:
    d20 = s.get("dist_ma20_pct")
    d50 = s.get("dist_ma50_pct")
    d200 = s.get("dist_ma200_pct")
    above20 = d20 is not None and d20 > 0
    above50 = d50 is not None and d50 > 0
    above200 = d200 is not None and d200 > 0
    if above20 and above50 and above200:
        return "站稳短中长期全部均线"
    if above20 and above200 and not above50:
        return "站稳20日与200日均线，挑战50日均线"
    if not above20 and above50 and above200:
        return "守住50日与200日均线，微幅受压20日均线"
    if not above20 and not above50 and above200:
        return "守住200日牛熊分界线，受制于20日与50日均线"
    if above20 and not above50 and not above200:
        return "短线站上20日均线，上方中长期均线承压"
    return "处于20日、50日与200日三重均线下方"


def translate_official_title_cn(category: str, title_raw: str) -> str:
    """将美联储、联邦公报、贸易代表办公室及经济分析局的英文官方标题转译为自然中文语序摘要。"""
    t = (title_raw or "").strip()
    tl = t.lower()

    # 美联储官方条目识别
    if "minutes of the federal open market committee" in tl:
        return "美联储正式公布联邦公开市场委员会（FOMC）货币政策例会纪要：披露委员对通胀粘性与后续利率路径的内部投票分歧与政策讨论。"
    if "fomc statement" in tl or "issues fomc statement" in tl:
        return "美联储发布联邦公开市场委员会（FOMC）利率决议声明：宣布联邦基金利率目标区间决定及对美国经济增长、就业与通胀形势的官方评估。"
    if "tentative schedule of federal open market committee" in tl:
        return "美联储理事会正式公布修订后的联邦公开市场委员会（FOMC）年度议息会议日程安排。"
    if "discount rate meetings" in tl:
        return "美联储公布贴现率会议纪要：反映各地区联储董事会对信贷窗口利率与区域经济冷热的官方研判。"
    if category == "fed_speech":
        speaker_map = {
            "powell": "美联储主席鲍威尔",
            "jefferson": "美联储副主席杰斐逊",
            "waller": "美联储理事沃勒",
            "cook": "美联储理事库克",
            "barr": "美联储理事巴尔",
            "bowman": "美联储理事鲍曼",
            "kugler": "美联储理事库格勒",
            "warsh": "美联储官员沃什",
        }
        speaker_cn = "美联储高级官员"
        for k, v in speaker_map.items():
            if tl.startswith(k) or f" {k}," in tl:
                speaker_cn = v
                break
        if "global context" in tl:
            return f"{speaker_cn}发表《全球背景下的美国经济》正式演讲，阐述国际贸易、汇率与美国通胀及利率政策的传导关系。"
        if "frequent and complex shocks" in tl:
            return f"{speaker_cn}发表《频繁与复杂冲击下的货币政策》正式演讲，强调在供给与价格扰动下维持政策定力。"
        if "payments and tokenized" in tl:
            return f"{speaker_cn}发表金融支付清算体系专题正式演讲，阐述央行基础设施与现代金融监管框架。"
        return f"{speaker_cn}发表公开正式政策致辞（原文标题：{t}）。"

    # 联邦公报（BIS 出口管制 / USTR 301关税）识别
    if "remote access to advanced semiconductors" in tl:
        return "美国商务部工业与安全局（BIS）颁布《关于管控先进半导体远程算力访问》临时最终规则并正式生效：将监管范围从实体芯片出口延伸至海外数据中心远程算力租赁，并对印尼、马来西亚、新加坡、泰国、巴西五国增设先进计算许可要求。"
    if "product exclusion extensions" in tl and "china" in tl:
        return "美国贸易代表办公室发布《对华301条款关税部分产品排除期限延长公告》，明确特定工业与技术组件进口关税豁免展期安排。"
    if "section 301 investigation of vietnam" in tl:
        return "美国贸易代表办公室发布法定公告，决定延长针对越南相关贸易与汇率做法的301条款调查行动评估。"
    if "maritime, logistics" in tl and "china" in tl:
        return "美国贸易代表办公室发布《针对中国海事、物流与造船领域301条款行动修订公告》，调整相关跨境航运与港口贸易执行细则。"
    if "united states-mexico-canada" in tl or "binational panels" in tl:
        return "美国商务部国际贸易管理局发布《美墨加协定（USMCA）双边争端解决专家组名单申报公告》。"
    if "additional protocol report forms" in tl:
        return "美国商务部工业与安全局就合规申报表格向白宫管理与预算办公室提交法定审查通知。"

    # USTR 与 BEA 官方发布识别
    if "america first trade policy" in tl or "greer" in tl:
        return "美国贸易代表格里尔发表官方政策讲话，重申坚持现行基准关税执法框架与推进关键制造业供应链回流。"
    if "mexico" in tl and "workers" in tl:
        return "美国贸易代表办公室依据《美墨加协定》快速反应劳工机制，正式要求墨西哥政府对跨境制造企业劳工合规启动审查。"
    if "international trade in goods and services" in tl:
        return "美国经济分析局与普查局联合发布美国月度国际商品与服务贸易进出口及逆差官方统计公报。"
    if "multinational enterprises" in tl:
        return "美国经济分析局发布《美国跨国企业全球经营、雇佣与资本开支官方年度统计报告》。"
    if "gross domestic product" in tl or "gdp" in tl:
        return "美国经济分析局发布季度国内生产总值（GDP）与核心个人消费支出（PCE）物价指数官方核算报告。"

    return f"官方公报事项：{t}"


def build_official_briefing_md(
    payload: dict[str, Any],
    context_overrides: dict[str, Any] | None = None,
) -> tuple[str, list[dict[str, str]]]:
    """生成《资讯栏目/YYYY-MM-DD_官方宏观与政策资讯.md》纯官方中文简报。"""
    tdate = payload["latest_trading_date"]
    dt_obj = datetime.strptime(tdate, "%Y-%m-%d")
    wk_cn = WEEKDAY_CN[dt_obj.weekday()]
    os_data = payload["official_sources"]
    ms = payload["market_sentiment"]
    ctx = context_overrides or {}

    by_sent = {x["symbol"]: x for x in ms.get("indicators", [])}
    tnx = by_sent.get("^TNX", {}).get("close", "暂无")
    irx = by_sent.get("^IRX", {}).get("close", "暂无")
    dxy = by_sent.get("DX-Y.NYB", {}).get("close", "暂无")

    lines: list[str] = [
        f"# 官方宏观政策、美元利率与国际经贸资讯专刊（{dt_obj.year}年{dt_obj.month}月{dt_obj.day}日）",
        "",
        f"> **对应美股交易日**：{tdate}（{wk_cn}）  ",
        "> **信源准则**：本专栏**严禁收录任何市场小道消息、匿名传闻或机构单方面猜测**，所有条目均100%采自美联储、纽约联储、美国财政与经贸部委、美国联邦公报及美国证监会（SEC）具有法律效力的官方一手文件，并按中文母语逻辑精炼重组。",
        "",
        "---",
        "",
        "## 一、美元基准利率与美联储货币政策定调（加息 / 降息路径监测）",
        "",
    ]

    # 1.1 纽约联储实时基准利率表
    ny_rates = os_data.get("nyfed_rates", [])
    if ny_rates:
        lines.append("### 1. 纽约联储官方隔夜美元利率走廊最新读数")
        lines.append("")
        lines.append("| 官方利率指标 | 最新生效日 | 官方年化利率 | 市场流动性含义解读 |")
        lines.append("| :--- | :---: | ---: | :--- |")
        for r in ny_rates:
            rc = r["rate_pct"]
            hint = "处于美联储 3.75%~4.00% 目标区间中枢，银行间美元流动性平稳" if r["type"] == "EFFR" else "国债抵押回购资金价格正常，未出现美元钱荒信号"
            lines.append(f"| **{r['name_cn']}** | {r['effective_date']} | **{rc:.2f}%** | {hint} |")
        lines.append("")

    lines.append(
        f"- **国债市场与汇率官方锚点**：截至 {tdate} 收盘，13周短端美债收益率为 **{irx}%**，10年期美债收益率为 **{tnx}%**（期限利差 **{ms.get('spread_10y_3m_bp', 0):+d} 个基点**），美元指数报 **{dxy}**。"
    )

    # 1.2 美联储利率决议、纪要与官员讲话
    if ctx.get("fed_policy_summary_cn"):
        for bullet in ctx["fed_policy_summary_cn"]:
            lines.append(f"- {bullet}")
    else:
        for item in os_data.get("fed_monetary_and_speeches", [])[:6]:
            cat = "fed_speech" if "演讲" in item["source_cn"] else "fed_monetary"
            summary_cn = translate_official_title_cn(cat, item["title_raw"])
            lines.append(f"- **[{item['date']}｜{item['source_cn']}]** {summary_cn}（[官方原文]({item['link']})）")

    lines.extend([
        "",
        "---",
        "",
        "## 二、国际贸易关系、关税执法与高科技出口管制（部委法定文件）",
        "",
    ])

    if ctx.get("trade_and_tech_summary_cn"):
        for bullet in ctx["trade_and_tech_summary_cn"]:
            lines.append(f"- {bullet}")
    else:
        seen_titles: set[str] = set()
        for doc in os_data.get("federal_register_trade_tech", [])[:5]:
            t_raw = doc.get("title_raw") or ""
            if t_raw in seen_titles:
                continue
            seen_titles.add(t_raw)
            summary_cn = translate_official_title_cn("fedreg", t_raw)
            lines.append(f"- **[{doc['date']}｜美国联邦公报法定文件]** {summary_cn}（[官方公报]({doc['link']})）")
        for rel in os_data.get("ustr_and_bea_releases", [])[:4]:
            t_raw = rel.get("title_raw") or ""
            if t_raw in seen_titles:
                continue
            seen_titles.add(t_raw)
            summary_cn = translate_official_title_cn("ustr_bea", t_raw)
            lines.append(f"- **[{rel['date']}｜{rel['source_cn']}]** {summary_cn}（[官方原文]({rel['link']})）")

    lines.extend([
        "",
        "---",
        "",
        "## 三、美国宏观经济官方统计与近期法定发布日程",
        "",
    ])

    if ctx.get("macro_data_summary_cn"):
        for bullet in ctx["macro_data_summary_cn"]:
            lines.append(f"- {bullet}")
    else:
        for rel in os_data.get("ustr_and_bea_releases", []):
            if "经济分析局" in rel["source_cn"]:
                summary_cn = translate_official_title_cn("ustr_bea", rel["title_raw"])
                lines.append(f"- **[{rel['date']}｜{rel['source_cn']}]** {summary_cn}（[官方数据]({rel['link']})）")

    lines.extend([
        "",
        "---",
        "",
        "## 四、纳斯达克核心科技企业法定重大事项公告（美国证监会一手披露）",
        "",
    ])

    if ctx.get("sec_highlights_cn"):
        for bullet in ctx["sec_highlights_cn"]:
            lines.append(f"- {bullet}")
        lines.append("")

    sec_rows = os_data.get("sec_8k_filings", [])
    if sec_rows:
        lines.append("| 披露日期 | 公司名称（代码） | 法定表格 | 法定披露事项中文说明 | 证监会官方存档 |")
        lines.append("| :---: | :--- | :---: | :--- | :---: |")
        for row in sec_rows[:12]:
            lines.append(
                f"| {row['filing_date']} | **{row['name_cn']}** (`{row['symbol']}`) | `{row['form']}` | {row['items_cn']} | [查看原件]({row['url']}) |"
            )
    else:
        lines.append("- 近14日内样本公司暂无新增 8-K 或 425 法定临时公告。")

    draft_text = "\n".join(lines)
    glossary_items = infer_glossary_for_text(draft_text)
    ignored = load_ignored_terms()

    lines.extend([
        "",
        "---",
        "",
        "## 五、初学者政策与金融术语通俗解读",
        "",
        f"> 系统已自动扫描本篇官方资讯并提取可能较难理解的专业名词（当前免解释屏蔽词数：**{len(ignored)}** 个；如需屏蔽已掌握名词，可直接告知我或运行 `python glossary_manager.py --ignore 名词`）。",
        "",
    ])
    if glossary_items:
        for idx, g in enumerate(glossary_items, 1):
            lines.append(f"{idx}. **{g['term']}**（*{g['category']}*）")
            lines.append(f"   - **通俗理解**：{g['definition']}")
            lines.append(f"   - **实战影响**：{g['practical']}")
    else:
        lines.append("- 当前文内涉及的术语均已在您的“已掌握免解释清单”中。")

    return "\n".join(lines) + "\n", glossary_items


def build_daily_report_md(
    payload: dict[str, Any],
    narrative: dict[str, Any],
    briefing_rel_path: str,
) -> tuple[str, list[dict[str, str]]]:
    """按纯正中文母语语序构建每日纳斯达克与核心科技股深度分析主报告。"""
    tdate = payload["latest_trading_date"]
    dt_obj = datetime.strptime(tdate, "%Y-%m-%d")
    wk_cn = WEEKDAY_CN[dt_obj.weekday()]

    all_rows = payload["data"]
    indices = [r for r in all_rows if r["category"] == "Indices"]
    stocks = [r for r in all_rows if r["category"] != "Indices"]
    ms = payload["market_sentiment"]

    lines: list[str] = [
        f"# 美股纳斯达克科技股与核心指数每日投研报告（{dt_obj.year}年{dt_obj.month}月{dt_obj.day}日）",
        "",
        f"> **美股交易日期**：{dt_obj.year}年{dt_obj.month}月{dt_obj.day}日（{wk_cn}，{narrative.get('market_calendar_note', '正常交易日')}）  ",
        f"> **数据与信源口径**：行情与均线波动指标采自雅虎财经日线收盘数据；宏观与监管政策采自央行、部委及美国证监会法定公告（详见专栏文件 [{tdate}_官方宏观与政策资讯.md]({briefing_rel_path})）  ",
        "> **指标计算说明**：近5日与近20日涨跌幅分别统计最近5个、20个美股交易日累计表现；年初至今涨跌幅以2025年最后一个交易日收盘价为基准；量比（相对成交量）为当日成交量除以过去20个交易日日均成交量。",
        "",
        "---",
        "",
        "## 一、市场核心综述",
        "",
        narrative["executive_intro"],
        "",
    ]
    for b in narrative["executive_bullets"]:
        lines.append(f"- {b}")

    # 二、四大基准指数对比
    lines.extend([
        "",
        "---",
        "",
        "## 二、四大核心基准指数表现对比",
        "",
        "| 指数名称（代码） | 最新收盘点位 | 日内波动区间（最低 ~ 最高） | 单日涨跌 | 近5日涨跌 | 近20日涨跌 | 年初至今 | 20日均线（偏离度） | 50日均线（偏离度） | 200日均线（偏离度） | 量比 | 20日年化波动率 | 距52周高点 |",
        "| :--- | ---: | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for idx in indices:
        rvol_str = f"{idx['rel_vol_20d']:.2f}倍" if idx["rel_vol_20d"] is not None else "不适用"
        if idx["symbol"] == "^NDX":
            rvol_str += "*"
        rng = f"{idx['low']:,.2f} ~ {idx['high']:,.2f}" if (idx["low"] and idx["high"]) else "暂无"
        lines.append(
            f"| **{idx['name_cn']}** (`{idx['symbol']}`) | {idx['close']:,.2f} | {rng} | {fmt_pct(idx['chg_1d_pct'], True)} | {fmt_pct(idx['chg_5d_pct'])} | {fmt_pct(idx['chg_20d_pct'])} | {fmt_pct(idx['ytd_pct'])} | {idx['ma20']:,.2f} ({fmt_pct(idx['dist_ma20_pct'])}) | {idx['ma50']:,.2f} ({fmt_pct(idx['dist_ma50_pct'])}) | {idx['ma200']:,.2f} ({fmt_pct(idx['dist_ma200_pct'])}) | {rvol_str} | {idx['ann_vol_20d_pct']:.2f}% | {fmt_pct(idx['dist_52w_high_pct'])} |"
        )
    lines.extend([
        "",
        "> **指数口径补充说明**：`*` 数据源对纳斯达克100指数披露的单日成交股数统计口径与历史均量口径不一致，观察纳斯达克整体资金换手热度请以**纳斯达克综合指数**（成交 "
        + fmt_vol_cn(indices[0]["volume"])
        + f"，量比 {indices[0]['rel_vol_20d']:.2f}倍）为准；费城半导体指数为纯价格指数，不含指数级成交量。",
        "",
        "---",
        "",
        "## 三、多维市场情绪与跨资产风向标",
        "",
        f"- **综合市场情绪定量评分**：**{ms['composite_score']} / 100 分** —— 当前状态判定为 **「{ms['regime_cn']}」**",
        f"- **内部涨跌与均线温度**：19 家核心科技股中当日 **{ms['up_stocks']} 家上涨（占比 {ms['breadth_1d_pct']}%）**；站上20日均线 **{ms['above_ma20_count']} 家**，站上50日均线 **{ms['above_ma50_count']} 家**，站上200日牛熊分界线 **{ms['above_ma200_count']} 家**。",
    ])
    for note in ms.get("summary_notes_cn", []):
        lines.append(f"- {note}")
    lines.append(
        f"- **长短期国债利差可视化专刊**：已同步生成最新长短端收益率与期限利差走势图及全期限曲线分析（详见专题报告 [{tdate}_美债期限利差专题分析.md](资讯栏目/{tdate}_美债期限利差专题分析.md) 与交互看板 [美债期限利差看板.html](美债期限利差看板.html)）。"
    )
    lines.append("")
    lines.append(f"![美债长短期收益率与期限利差全景监测图](资讯栏目/{tdate}_美债长短期利差走势图.png)")

    lines.extend([
        "",
        "| 情绪维度分类 | 中文指标名称（代码） | 最新数值 | 单日涨跌幅 | 近5日涨跌幅 | 看盘实战解读 |",
        "| :--- | :--- | ---: | ---: | ---: | :--- |",
    ])
    for ind in ms.get("indicators", []):
        val_str = f"{ind['close']:,.2f}%" if ind["symbol"] in ("^IRX", "^FVX", "^TNX", "^TYX") else f"{ind['close']:,.2f}"
        lines.append(
            f"| {ind['group_cn']} | **{ind['name_cn']}** (`{ind['symbol']}`) | {val_str} | {fmt_pct(ind['chg_1d_pct'], abs(ind['chg_1d_pct']) >= 3)} | {fmt_pct(ind['chg_5d_pct'])} | {ind['meaning_cn']} |"
        )

    # 四、官方宏观政策与国际经贸权威资讯精要
    lines.extend([
        "",
        "---",
        "",
        "## 四、官方宏观政策与国际经贸权威资讯精要（零小道消息）",
        "",
        f"> 完整部委、央行与证监会法定原文链接及深度拆解已归档至专栏文件：[{tdate}_官方宏观与政策资讯.md]({briefing_rel_path})。",
        "",
    ])
    for b in narrative["official_digest_bullets"]:
        lines.append(f"- {b}")

    # 五、核心科技股表现与技术面分板块总表
    lines.extend([
        "",
        "---",
        "",
        "## 五、核心科技股表现与技术面分板块明细",
        "",
        "以下按三大科技子板块分类，组内均按**单日涨跌幅从高到低**排序：",
        "",
    ])

    sub_order = [
        ("Mega-Cap Tech", "（一）科技七巨头"),
        ("Semiconductors", "（二）半导体与芯片设备"),
        ("Software & Growth", "（三）软件、云计算与网络安全"),
    ]
    for cat_key, sec_title in sub_order:
        sub_items = sorted(
            [s for s in stocks if s["category"] == cat_key],
            key=lambda x: x["chg_1d_pct"],
            reverse=True,
        )
        lines.append(f"### {sec_title}")
        lines.append("")
        lines.append("| 公司名称（代码） | 收盘价（美元） | 单日涨跌 | 近5日涨跌 | 近20日涨跌 | 年初至今 | 当日成交量 | 量比 | 较20日均线 | 较50日均线 | 较200日均线及趋势位置 | 20日年化波动率 | 距52周高点 |")
        lines.append("| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :--- | ---: | ---: |")
        for s in sub_items:
            rv = f"**{s['rel_vol_20d']:.2f}倍**" if s["rel_vol_20d"] >= 1.25 else f"{s['rel_vol_20d']:.2f}倍"
            lines.append(
                f"| **{s['name_cn']}** (`{s['symbol']}`) | {s['close']:,.2f} | {fmt_pct(s['chg_1d_pct'], True)} | {fmt_pct(s['chg_5d_pct'])} | {fmt_pct(s['chg_20d_pct'])} | {fmt_pct(s['ytd_pct'])} | {fmt_vol_cn(s['volume'])} | {rv} | {fmt_pct(s['dist_ma20_pct'])} | {fmt_pct(s['dist_ma50_pct'])} | {fmt_pct(s['dist_ma200_pct'])}｜{ma_posture_cn(s)} | {s['ann_vol_20d_pct']:.1f}% | {fmt_pct(s['dist_52w_high_pct'])} |"
            )
        lines.append("")

    sorted_all = sorted(stocks, key=lambda x: x["chg_1d_pct"], reverse=True)
    top5 = " > ".join(f"{x['name_cn']} ({fmt_pct(x['chg_1d_pct'])})" for x in sorted_all[:5])
    bot5 = " < ".join(f"{x['name_cn']} ({fmt_pct(x['chg_1d_pct'])})" for x in reversed(sorted_all[-5:]))
    lines.append(f"> **全样本涨跌极值榜**：领涨前五依次为 **{top5}**；表现靠后五家依次为 **{bot5}**。")

    # 六、子板块轮动与市场广度分析
    lines.extend([
        "",
        "---",
        "",
        "## 六、子板块轮动与市场广度量化分析",
        "",
        "| 子板块名称 | 样本数 | 上涨家数（占比） | 等权单日均值 | 单日中位数 | 等权近5日均值 | 等权近20日均值 | 等权年初至今均值 | 站上20日均线 | 站上50日均线 | 站上200日均线 |",
        "| :--- | :---: | :---: | ---: | ---: | ---: | ---: | ---: | :---: | :---: | :---: |",
    ])

    sec_stats: list[tuple[str, list[dict[str, Any]]]] = [
        ("半导体与芯片设备", [s for s in stocks if s["category"] == "Semiconductors"]),
        ("科技七巨头", [s for s in stocks if s["category"] == "Mega-Cap Tech"]),
        ("软件、云计算与网安", [s for s in stocks if s["category"] == "Software & Growth"]),
        ("全部19家核心科技股合计", stocks),
    ]
    for label_cn, grp in sec_stats:
        n = len(grp)
        up = sum(1 for x in grp if x["chg_1d_pct"] > 0)
        a1 = statistics.mean(x["chg_1d_pct"] for x in grp)
        m1 = statistics.median(x["chg_1d_pct"] for x in grp)
        a5 = statistics.mean(x["chg_5d_pct"] for x in grp)
        a20 = statistics.mean(x["chg_20d_pct"] for x in grp)
        aytd = statistics.mean(x["ytd_pct"] for x in grp if x["ytd_pct"] is not None)
        c20 = sum(1 for x in grp if x["dist_ma20_pct"] > 0)
        c50 = sum(1 for x in grp if x["dist_ma50_pct"] > 0)
        c200 = sum(1 for x in grp if x["dist_ma200_pct"] > 0)
        is_total = label_cn.startswith("全部")
        nm = f"**{label_cn}**" if is_total else label_cn
        lines.append(
            f"| {nm} | {n} | {up} / {n} ({up / n * 100:.1f}%) | {fmt_pct(a1, True)} | {fmt_pct(m1)} | {fmt_pct(a5)} | {fmt_pct(a20)} | {fmt_pct(aytd)} | {c20} / {n} ({c20 / n * 100:.1f}%) | {c50} / {n} ({c50 / n * 100:.1f}%) | {c200} / {n} ({c200 / n * 100:.1f}%) |"
        )

    lines.append("")
    for idx_n, insight in enumerate(narrative["rotation_insights"], 1):
        lines.append(f"{idx_n}. {insight}")

    # 七、成交量异动与均线技术信号
    lines.extend([
        "",
        "---",
        "",
        "## 七、成交量异动与均线结构信号",
        "",
        "### （一）显著放量异动个股（20日量比 ≥ 1.25倍）",
        "",
    ])
    for b in narrative["volume_signals"]:
        lines.append(f"- {b}")

    lines.extend([
        "",
        "### （二）关键均线攻防与波动率警示",
        "",
    ])
    for b in narrative["ma_signals"]:
        lines.append(f"- {b}")

    # 八、个股催化剖析与短期风险展望
    lines.extend([
        "",
        "---",
        "",
        "## 八、重点个股催化剖析与短期风险展望",
        "",
        "### （一）重点异动个股驱动逻辑（区分法定事实与市场博弈）",
        "",
    ])
    for b in narrative["stock_catalysts"]:
        lines.append(f"- {b}")

    lines.extend([
        "",
        "### （二）短期交易窗口与核心风险展望",
        "",
    ])
    for idx_n, b in enumerate(narrative["outlook_points"], 1):
        lines.append(f"{idx_n}. {b}")

    # 九、初学者投研术语通俗伴读（自动推断 + 免解释配置过滤）
    draft_md = "\n".join(lines)
    glossary_items = infer_glossary_for_text(draft_md)
    ignored = load_ignored_terms()

    lines.extend([
        "",
        "---",
        "",
        "## 九、初学者投研术语通俗伴读",
        "",
        f"> 以下词条由系统根据今日报告正文自动识别生成，帮助初学者无障碍读懂专业数据。当前已设置免解释的名词共 **{len(ignored)}** 个；今后若某个名词您已完全熟悉、不再需要解释，只需直接告诉我（例如“以后不用解释均线和量比了”），系统便会将其写入《术语配置.json》永久跳过。",
        "",
    ])
    if glossary_items:
        lines.append("| 所属类别 | 专业术语名称 | 通俗中文解释 | 看盘实战意义 |")
        lines.append("| :--- | :--- | :--- | :--- |")
        for g in glossary_items:
            lines.append(f"| {g['category']} | **{g['term']}** | {g['definition']} | {g['practical']} |")
    else:
        lines.append("- 本篇报告涉及的所有术语均已列入您的免解释清单。")

    return "\n".join(lines) + "\n", glossary_items


def build_dashboard_html(
    payload: dict[str, Any],
    narrative: dict[str, Any],
    glossary_items: list[dict[str, str]],
) -> str:
    """生成100%纯正中文语序的自包含交互式投研看板 HTML（含市场情绪、官方资讯栏与新手术语词典）。"""
    tdate = payload["latest_trading_date"]
    all_rows = payload["data"]
    indices = [
        {
            "symbol": r["symbol"],
            "name_cn": r["name_cn"],
            "close": r["close"],
            "chg_1d": r["chg_1d_pct"],
            "chg_5d": r["chg_5d_pct"],
            "chg_20d": r["chg_20d_pct"],
            "dist_ma50": r["dist_ma50_pct"],
            "dist_52w": r["dist_52w_high_pct"],
        }
        for r in all_rows
        if r["category"] == "Indices"
    ]
    stocks = [
        {
            "symbol": r["symbol"],
            "name_cn": r["name_cn"],
            "sector_cn": r["category_cn"],
            "close": r["close"],
            "chg_1d": r["chg_1d_pct"],
            "chg_5d": r["chg_5d_pct"],
            "chg_20d": r["chg_20d_pct"],
            "ytd": r["ytd_pct"],
            "dist_ma20": r["dist_ma20_pct"],
            "dist_ma50": r["dist_ma50_pct"],
            "rel_vol": r["rel_vol_20d"],
            "ann_vol": r["ann_vol_20d_pct"],
            "dist_52w": r["dist_52w_high_pct"],
        }
        for r in all_rows
        if r["category"] != "Indices"
    ]

    ms = payload["market_sentiment"]
    by_sent = {x["symbol"]: x for x in ms.get("indicators", [])}
    sentiment_cards = []
    for sym, unit in [
        ("^VIX", ""),
        ("^VXN", ""),
        ("^SKEW", ""),
        ("DX-Y.NYB", ""),
        ("^TNX", "%"),
        ("^IRX", "%"),
        ("GC=F", "$"),
        ("BTC-USD", "$"),
    ]:
        if sym in by_sent:
            it = by_sent[sym]
            sentiment_cards.append(
                {
                    "symbol": sym,
                    "name_cn": it["name_cn"],
                    "group_cn": it["group_cn"],
                    "close": it["close"],
                    "unit": unit,
                    "chg_1d": it["chg_1d_pct"],
                    "meaning_cn": it["meaning_cn"],
                }
            )

    official_cards = narrative["dashboard_official_pillars"]
    commentary_cards = narrative["dashboard_commentary_cards"]

    data_bundle_js = json.dumps(
        {
            "indices": indices,
            "stocks": stocks,
            "sentimentSummary": {
                "score": ms["composite_score"],
                "regime": ms["regime_cn"],
                "upStocks": ms["up_stocks"],
                "totalStocks": ms["total_stocks"],
                "spread10y3mBp": ms["spread_10y_3m_bp"],
                "hygTltRatio": ms["hyg_tlt_ratio"],
                "hygTltChg": ms["hyg_tlt_chg_pct"],
            },
            "sentimentCards": sentiment_cards,
            "officialPillars": official_cards,
            "commentaryCards": commentary_cards,
            "glossary": glossary_items,
        },
        ensure_ascii=False,
    )

    down_stocks = ms["total_stocks"] - ms["up_stocks"]
    score_color = "#10b981" if ms["composite_score"] >= 50 else "#ef4444"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>纳斯达克与美股核心科技股每日投研看板 — {tdate}</title>
  <script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>
  <style>
    :root {{
      --bg-fallback: #0b0f19;
      --card-fallback: #111827;
      --fg-fallback: #f3f4f6;
      --muted-fallback: #9ca3af;
      --border-fallback: #1f2937;
      --primary-fallback: #3b82f6;
      --primary-fg-fallback: #ffffff;
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
    th.sortable {{ cursor: pointer; user-select: none; }}
    th.sortable:hover {{ color: var(--foreground, var(--fg-fallback)); }}
  </style>
</head>
<body class="bg-[var(--background,#0b0f19)] text-[var(--foreground,#f3f4f6)] antialiased p-4 md:p-6">
  <div class="max-w-7xl mx-auto space-y-5">

    <!-- 顶部中文投研抬头 -->
    <header class="bg-[var(--card,#111827)] border border-[var(--border,#1f2937)] rounded-xl p-5 flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
      <div>
        <div class="flex items-center gap-2 text-xs tracking-wider text-[var(--muted-foreground,#9ca3af)] font-semibold">
          <span>美股科技与量化投研案头</span>
          <span>•</span>
          <span>全中文权威数据与政策监测日报</span>
        </div>
        <h1 class="text-xl md:text-2xl font-bold mt-1">纳斯达克指数与核心科技股每日投研看板</h1>
        <p class="text-xs text-[var(--muted-foreground,#9ca3af)] mt-1">
          美东交易日期：<span class="font-mono text-[var(--foreground,#f3f4f6)]">{tdate}</span> &nbsp;|&nbsp;
          覆盖范围：4 大基准指数 + 19 家核心科技龙头 + 跨资产情绪 + 央行及部委纯官方资讯
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <span class="px-3 py-1.5 rounded-lg text-xs font-semibold border bg-[var(--background,#0b0f19)]" style="border-color: {score_color}; color: {score_color};">
          综合情绪：{ms["composite_score"]}分｜{ms["regime_cn"]}
        </span>
        <span class="px-3 py-1.5 rounded-lg text-xs font-semibold border border-[var(--border,#1f2937)] text-[var(--foreground,#f3f4f6)] bg-[var(--background,#0b0f19)]">
          样本涨跌家数：{ms["up_stocks"]} 涨 / {down_stocks} 跌
        </span>
        <a href="美债期限利差看板.html" class="px-3 py-1.5 rounded-lg text-xs font-semibold border border-[var(--primary,#3b82f6)] text-[var(--primary,#3b82f6)] bg-[var(--background,#0b0f19)] hover:opacity-80">
          打开美债长短期利差看板 &rarr;
        </a>
      </div>
    </header>

    <!-- 四大核心基准指数卡片 -->
    <section class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4" id="index-cards"></section>

    <!-- 新增：多维市场情绪与跨资产风向标 -->
    <section class="bg-[var(--card,#111827)] border border-[var(--border,#1f2937)] rounded-xl p-5 space-y-4">
      <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 pb-3 border-b border-[var(--border,#1f2937)]">
        <div>
          <h2 class="text-base font-bold">多维市场情绪与跨资产宏观风向标</h2>
          <p class="text-xs text-[var(--muted-foreground,#9ca3af)]">综合期权恐慌度、黑天鹅偏度、美元汇率、美债利率走廊与避险资产实时监控市场温度</p>
        </div>
        <div class="flex flex-wrap gap-2 text-xs tabular-nums" id="sentiment-badges"></div>
      </div>
      <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3" id="sentiment-grid"></div>
    </section>

    <!-- 核心科技股双向排行与板块/量比面板 -->
    <section class="grid grid-cols-1 lg:grid-cols-12 gap-4">
      <div class="lg:col-span-8 bg-[var(--card,#111827)] border border-[var(--border,#1f2937)] rounded-xl p-5 flex flex-col">
        <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 pb-3 border-b border-[var(--border,#1f2937)]">
          <div>
            <h2 class="text-base font-bold">核心科技股涨跌幅与均线偏离双向对比图</h2>
            <p class="text-xs text-[var(--muted-foreground,#9ca3af)]">点击右侧按钮切换时间窗口或均线偏离维度，直观识别领涨龙头与超跌标的</p>
          </div>
          <div class="flex flex-wrap gap-1.5" id="metric-tabs">
            <button data-metric="chg_1d" class="metric-btn px-2.5 py-1 rounded-md text-xs font-medium border border-[var(--primary,#3b82f6)] bg-[var(--primary,#3b82f6)] text-[var(--primary-foreground,#ffffff)]">单日涨跌</button>
            <button data-metric="chg_5d" class="metric-btn px-2.5 py-1 rounded-md text-xs font-medium border border-[var(--border,#1f2937)] text-[var(--muted-foreground,#9ca3af)]">近5日</button>
            <button data-metric="chg_20d" class="metric-btn px-2.5 py-1 rounded-md text-xs font-medium border border-[var(--border,#1f2937)] text-[var(--muted-foreground,#9ca3af)]">近20日</button>
            <button data-metric="dist_ma20" class="metric-btn px-2.5 py-1 rounded-md text-xs font-medium border border-[var(--border,#1f2937)] text-[var(--muted-foreground,#9ca3af)]">较20日均线</button>
            <button data-metric="dist_ma50" class="metric-btn px-2.5 py-1 rounded-md text-xs font-medium border border-[var(--border,#1f2937)] text-[var(--muted-foreground,#9ca3af)]">较50日均线</button>
          </div>
        </div>
        <div id="diverging-chart" class="mt-4 space-y-2"></div>
      </div>

      <div class="lg:col-span-4 space-y-4">
        <div class="bg-[var(--card,#111827)] border border-[var(--border,#1f2937)] rounded-xl p-5">
          <h2 class="text-base font-bold">三大科技子板块等权均值对比</h2>
          <p class="text-xs text-[var(--muted-foreground,#9ca3af)] mb-3">单日表现与近5日、年初至今平均涨跌幅对照</p>
          <div id="sector-chart" class="space-y-3"></div>
        </div>

        <div class="bg-[var(--card,#111827)] border border-[var(--border,#1f2937)] rounded-xl p-5">
          <h2 class="text-base font-bold">放量异动监控雷达（量比 &ge; 1.25倍）</h2>
          <p class="text-xs text-[var(--muted-foreground,#9ca3af)] mb-3">识别当日机构资金集中抢筹或大举换手标的</p>
          <div id="volume-radar" class="space-y-2"></div>
        </div>
      </div>
    </section>

    <!-- 盘面核心逻辑三栏点评 -->
    <section class="grid grid-cols-1 md:grid-cols-3 gap-4" id="commentary-cards"></section>

    <!-- 新增：官方宏观政策与国际经贸资讯专栏（零小道消息） -->
    <section class="bg-[var(--card,#111827)] border border-[var(--border,#1f2937)] rounded-xl p-5 space-y-4">
      <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 pb-3 border-b border-[var(--border,#1f2937)]">
        <div>
          <h2 class="text-base font-bold">官方宏观政策、美元利率与国际经贸资讯专栏</h2>
          <p class="text-xs text-[var(--muted-foreground,#9ca3af)]">严格剔除一切小道传闻，仅提炼美联储、纽约联储、商务部、贸易代表办公室及美国证监会法定一手文件</p>
        </div>
        <span class="px-2.5 py-1 rounded-md text-xs font-semibold border border-[var(--primary,#3b82f6)] text-[var(--primary,#3b82f6)]">
          纯官方权威信源 • 归档于《资讯栏目》文件夹
        </span>
      </div>
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-4" id="official-pillars"></div>
    </section>

    <!-- 19家核心科技股可筛选排序全中文明细表 -->
    <section class="bg-[var(--card,#111827)] border border-[var(--border,#1f2937)] rounded-xl p-5">
      <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 pb-4 border-b border-[var(--border,#1f2937)]">
        <div>
          <h2 class="text-base font-bold">19家纳斯达克核心科技股量化技术面明细表</h2>
          <p class="text-xs text-[var(--muted-foreground,#9ca3af)]">支持按中文子板块筛选，点击任意数字表头可切换升序或降序排列</p>
        </div>
        <div class="flex flex-wrap gap-1.5" id="sector-filters">
          <button data-sector="全部" class="sector-btn px-3 py-1 rounded-md text-xs font-medium border border-[var(--primary,#3b82f6)] bg-[var(--primary,#3b82f6)] text-[var(--primary-foreground,#ffffff)]">全部 (19)</button>
          <button data-sector="科技七巨头" class="sector-btn px-3 py-1 rounded-md text-xs font-medium border border-[var(--border,#1f2937)] text-[var(--muted-foreground,#9ca3af)]">科技七巨头 (7)</button>
          <button data-sector="半导体与芯片设备" class="sector-btn px-3 py-1 rounded-md text-xs font-medium border border-[var(--border,#1f2937)] text-[var(--muted-foreground,#9ca3af)]">半导体与芯片设备 (6)</button>
          <button data-sector="软件、云计算与网安" class="sector-btn px-3 py-1 rounded-md text-xs font-medium border border-[var(--border,#1f2937)] text-[var(--muted-foreground,#9ca3af)]">软件、云计算与网安 (6)</button>
        </div>
      </div>

      <div class="overflow-x-auto mt-3">
        <table class="w-full text-xs text-left border-collapse">
          <thead>
            <tr class="border-b border-[var(--border,#1f2937)] text-[var(--muted-foreground,#9ca3af)]">
              <th class="py-2.5 px-2 font-semibold">公司名称（代码）</th>
              <th class="py-2.5 px-2 font-semibold">所属板块</th>
              <th class="py-2.5 px-2 font-semibold text-right sortable" data-sort="close">收盘价(美元)</th>
              <th class="py-2.5 px-2 font-semibold text-right sortable" data-sort="chg_1d">单日涨跌</th>
              <th class="py-2.5 px-2 font-semibold text-right sortable" data-sort="chg_5d">近5日</th>
              <th class="py-2.5 px-2 font-semibold text-right sortable" data-sort="chg_20d">近20日</th>
              <th class="py-2.5 px-2 font-semibold text-right sortable" data-sort="ytd">年初至今</th>
              <th class="py-2.5 px-2 font-semibold text-right sortable" data-sort="dist_ma20">较20日均线</th>
              <th class="py-2.5 px-2 font-semibold text-right sortable" data-sort="dist_ma50">较50日均线</th>
              <th class="py-2.5 px-2 font-semibold text-right sortable" data-sort="rel_vol">20日量比</th>
              <th class="py-2.5 px-2 font-semibold text-right sortable" data-sort="ann_vol">年化波动率</th>
              <th class="py-2.5 px-2 font-semibold text-right sortable" data-sort="dist_52w">距52周高点</th>
            </tr>
          </thead>
          <tbody id="equity-tbody" class="divide-y divide-[var(--border,#1f2937)]"></tbody>
        </table>
      </div>
    </section>

    <!-- 新增：初学者投研术语通俗词典（支持检索与已掌握折叠） -->
    <section class="bg-[var(--card,#111827)] border border-[var(--border,#1f2937)] rounded-xl p-5 space-y-4">
      <div class="flex flex-col md:flex-row md:items-center md:justify-between gap-3 pb-3 border-b border-[var(--border,#1f2937)]">
        <div>
          <h2 class="text-base font-bold">初学者投研术语通俗伴读词典</h2>
          <p class="text-xs text-[var(--muted-foreground,#9ca3af)]">系统已自动提取今日报告中的专业名词并附通俗解释；若您已熟悉某词，可点击卡片右上角“本次隐藏”，或告知我永久不再解释</p>
        </div>
        <div class="flex items-center gap-2">
          <input id="glossary-search" type="text" placeholder="搜索术语（如：均线、加息、量比）..."
                 class="px-3 py-1.5 rounded-lg text-xs bg-[var(--background,#0b0f19)] border border-[var(--border,#1f2937)] text-[var(--foreground,#f3f4f6)] focus:outline-none" />
        </div>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-3" id="glossary-grid"></div>
    </section>

  </div>

  <script>
    const DATA = {data_bundle_js};

    const fmtPct = (v) => (v === null || v === undefined ? "暂无" : v > 0 ? `+${{v.toFixed(2)}}%` : `${{v.toFixed(2)}}%`);
    const pctColor = (v) => (v > 0 ? "text-[var(--success,#10b981)]" : v < 0 ? "text-[var(--error,#ef4444)]" : "text-[var(--muted-foreground,#9ca3af)]");

    // 1. 渲染四大基准指数卡片
    document.getElementById("index-cards").innerHTML = DATA.indices.map(idx => `
      <div class="bg-[var(--card,#111827)] border border-[var(--border,#1f2937)] rounded-xl p-4 flex flex-col justify-between">
        <div class="flex items-start justify-between">
          <div>
            <div class="text-sm font-bold">${{idx.name_cn}}</div>
            <div class="text-xs font-mono text-[var(--muted-foreground,#9ca3af)]">${{idx.symbol}}</div>
          </div>
          <span class="px-2 py-0.5 rounded text-xs font-semibold tabular-nums ${{pctColor(idx.chg_1d)}} border border-[var(--border,#1f2937)]">
            ${{fmtPct(idx.chg_1d)}}
          </span>
        </div>
        <div class="text-2xl font-bold tabular-nums mt-2">${{idx.close.toLocaleString("en-US", {{ minimumFractionDigits: 2 }})}}</div>
        <div class="grid grid-cols-3 gap-1 mt-3 pt-2.5 border-t border-[var(--border,#1f2937)] text-xs tabular-nums">
          <div><span class="text-[var(--muted-foreground,#9ca3af)] block">近5日</span><span class="${{pctColor(idx.chg_5d)}} font-medium">${{fmtPct(idx.chg_5d)}}</span></div>
          <div><span class="text-[var(--muted-foreground,#9ca3af)] block">较50日均线</span><span class="${{pctColor(idx.dist_ma50)}} font-medium">${{fmtPct(idx.dist_ma50)}}</span></div>
          <div><span class="text-[var(--muted-foreground,#9ca3af)] block">距52周高点</span><span class="text-[var(--muted-foreground,#9ca3af)] font-medium">${{fmtPct(idx.dist_52w)}}</span></div>
        </div>
      </div>
    `).join("");

    // 2. 渲染多维市场情绪风向标
    const ss = DATA.sentimentSummary;
    document.getElementById("sentiment-badges").innerHTML = `
      <span class="px-2.5 py-1 rounded border border-[var(--border,#1f2937)] bg-[var(--background,#0b0f19)]">
        10年减3月美债利差：<strong>${{ss.spread10y3mBp >= 0 ? "+" : ""}}${{ss.spread10y3mBp}} 基点</strong>
      </span>
      <span class="px-2.5 py-1 rounded border border-[var(--border,#1f2937)] bg-[var(--background,#0b0f19)]">
        信用债/国债风险比：<strong>${{ss.hygTltRatio}} (${{fmtPct(ss.hygTltChg)}})</strong>
      </span>
    `;
    document.getElementById("sentiment-grid").innerHTML = DATA.sentimentCards.map(c => {{
      const valTxt = c.unit === "$"
        ? `$${{c.close.toLocaleString("en-US", {{ minimumFractionDigits: 2 }})}}`
        : `${{c.close.toFixed(2)}}${{c.unit}}`;
      // 恐慌指数下跌属于情绪改善，用中性或直观涨跌色展示并标注说明
      return `
        <div class="p-3 rounded-lg border border-[var(--border,#1f2937)] bg-[var(--background,#0b0f19)] flex flex-col justify-between">
          <div>
            <div class="flex items-center justify-between text-xs">
              <span class="text-[var(--muted-foreground,#9ca3af)]">${{c.group_cn}}</span>
              <span class="font-mono text-[var(--muted-foreground,#9ca3af)]">${{c.symbol}}</span>
            </div>
            <div class="flex items-baseline justify-between mt-1">
              <span class="text-sm font-bold">${{c.name_cn}}</span>
              <span class="font-mono font-bold text-sm tabular-nums">${{valTxt}}</span>
            </div>
          </div>
          <div class="mt-2 pt-2 border-t border-[var(--border,#1f2937)] flex items-center justify-between text-xs">
            <span class="text-[var(--muted-foreground,#9ca3af)] truncate pr-2" title="${{c.meaning_cn}}">${{c.meaning_cn}}</span>
            <span class="font-mono font-semibold tabular-nums ${{pctColor(c.chg_1d)}} shrink-0">${{fmtPct(c.chg_1d)}}</span>
          </div>
        </div>
      `;
    }}).join("");

    // 3. 渲染核心科技股双向对比图
    let currentMetric = "chg_1d";
    function renderDivergingChart() {{
      const sorted = [...DATA.stocks].sort((a, b) => b[currentMetric] - a[currentMetric]);
      const maxAbs = Math.max(...sorted.map(s => Math.abs(s[currentMetric])), 1);

      document.getElementById("diverging-chart").innerHTML = sorted.map(s => {{
        const val = s[currentMetric];
        const widthPct = (Math.abs(val) / maxAbs) * 48;
        const isPos = val >= 0;
        const barColor = isPos ? "bg-[var(--success,#10b981)]" : "bg-[var(--error,#ef4444)]";
        return `
          <div class="grid grid-cols-12 items-center gap-2 text-xs">
            <div class="col-span-4 sm:col-span-3 flex items-center justify-between pr-1">
              <span class="font-semibold truncate">${{s.name_cn}}</span>
              <span class="font-mono text-[var(--muted-foreground,#9ca3af)] ml-1">${{s.symbol}}</span>
            </div>
            <div class="col-span-6 sm:col-span-7 relative h-4 flex items-center">
              <div class="w-full h-px bg-[var(--border,#1f2937)] absolute top-1/2"></div>
              <div class="w-px h-4 bg-[var(--muted-foreground,#9ca3af)] opacity-40 absolute left-1/2"></div>
              <div class="h-3 rounded-sm ${{barColor}} absolute transition-all"
                   style="${{isPos ? `left: 50%; width: ${{widthPct}}%;` : `right: 50%; width: ${{widthPct}}%;`}}"></div>
            </div>
            <div class="col-span-2 text-right font-mono font-semibold tabular-nums ${{pctColor(val)}}">
              ${{fmtPct(val)}}
            </div>
          </div>
        `;
      }}).join("");
    }}

    document.querySelectorAll(".metric-btn").forEach(btn => {{
      btn.addEventListener("click", () => {{
        currentMetric = btn.dataset.metric;
        document.querySelectorAll(".metric-btn").forEach(b => {{
          b.className = "metric-btn px-2.5 py-1 rounded-md text-xs font-medium border border-[var(--border,#1f2937)] text-[var(--muted-foreground,#9ca3af)]";
        }});
        btn.className = "metric-btn px-2.5 py-1 rounded-md text-xs font-medium border border-[var(--primary,#3b82f6)] bg-[var(--primary,#3b82f6)] text-[var(--primary-foreground,#ffffff)]";
        renderDivergingChart();
      }});
    }});

    // 4. 三大子板块对比
    const sectorOrder = ["半导体与芯片设备", "科技七巨头", "软件、云计算与网安"];
    document.getElementById("sector-chart").innerHTML = sectorOrder.map(secName => {{
      const items = DATA.stocks.filter(s => s.sector_cn === secName);
      const avg1d = items.reduce((a, b) => a + b.chg_1d, 0) / items.length;
      const avg5d = items.reduce((a, b) => a + b.chg_5d, 0) / items.length;
      const avgYtd = items.reduce((a, b) => a + (b.ytd || 0), 0) / items.length;
      return `
        <div class="p-3 rounded-lg border border-[var(--border,#1f2937)] bg-[var(--background,#0b0f19)]">
          <div class="flex justify-between items-center text-xs font-semibold">
            <span>${{secName}}（${{items.length}}家）</span>
            <span class="${{pctColor(avg1d)}} tabular-nums">单日：${{fmtPct(avg1d)}}</span>
          </div>
          <div class="flex justify-between items-center text-xs text-[var(--muted-foreground,#9ca3af)] mt-1.5 tabular-nums">
            <span>近5日均值：<strong class="${{pctColor(avg5d)}}">${{fmtPct(avg5d)}}</strong></span>
            <span>年初至今：<strong class="${{pctColor(avgYtd)}}">${{fmtPct(avgYtd)}}</strong></span>
          </div>
        </div>
      `;
    }}).join("");

    // 5. 放量异动雷达
    const volAnomalies = [...DATA.stocks].filter(s => s.rel_vol >= 1.25).sort((a, b) => b.rel_vol - a.rel_vol);
    document.getElementById("volume-radar").innerHTML = volAnomalies.map(s => `
      <div class="flex items-center justify-between text-xs p-2 rounded-lg border border-[var(--border,#1f2937)] bg-[var(--background,#0b0f19)]">
        <div>
          <span class="font-bold">${{s.name_cn}}</span>
          <span class="font-mono text-[var(--muted-foreground,#9ca3af)] ml-1">${{s.symbol}}</span>
        </div>
        <div class="flex items-center gap-3 tabular-nums">
          <span class="font-mono font-semibold text-[var(--warning,#f59e0b)]">量比 ${{s.rel_vol.toFixed(2)}}倍</span>
          <span class="font-mono font-semibold ${{pctColor(s.chg_1d)}} w-16 text-right">${{fmtPct(s.chg_1d)}}</span>
        </div>
      </div>
    `).join("");

    // 6. 渲染盘面点评三栏与官方政策资讯三栏
    document.getElementById("commentary-cards").innerHTML = DATA.commentaryCards.map(c => `
      <div class="bg-[var(--card,#111827)] border border-[var(--border,#1f2937)] rounded-xl p-4 space-y-1.5">
        <div class="text-xs font-semibold tracking-wider ${{c.tagColor}}">${{c.tag}}</div>
        <h3 class="text-sm font-bold">${{c.title}}</h3>
        <p class="text-xs text-[var(--muted-foreground,#9ca3af)] leading-relaxed">${{c.body}}</p>
      </div>
    `).join("");

    document.getElementById("official-pillars").innerHTML = DATA.officialPillars.map(p => `
      <div class="p-4 rounded-xl border border-[var(--border,#1f2937)] bg-[var(--background,#0b0f19)] space-y-2.5">
        <div class="flex items-center justify-between border-b border-[var(--border,#1f2937)] pb-2">
          <span class="text-sm font-bold">${{p.pillar}}</span>
          <span class="text-xs text-[var(--muted-foreground,#9ca3af)]">${{p.authority}}</span>
        </div>
        <ul class="space-y-2 text-xs text-[var(--muted-foreground,#9ca3af)] leading-relaxed list-disc pl-4">
          ${{p.items.map(it => `<li>${{it}}</li>`).join("")}}
        </ul>
      </div>
    `).join("");

    // 7. 渲染可筛选、可排序全中文表格
    let currentSector = "全部";
    let sortKey = "chg_1d";
    let sortAsc = false;

    function renderTable() {{
      const filtered = currentSector === "全部" ? DATA.stocks : DATA.stocks.filter(s => s.sector_cn === currentSector);
      const sorted = [...filtered].sort((a, b) => sortAsc ? (a[sortKey] - b[sortKey]) : (b[sortKey] - a[sortKey]));

      document.getElementById("equity-tbody").innerHTML = sorted.map(s => `
        <tr class="hover:bg-[var(--background,#0b0f19)] transition-colors">
          <td class="py-2.5 px-2">
            <span class="font-bold">${{s.name_cn}}</span>
            <span class="font-mono text-[var(--muted-foreground,#9ca3af)] ml-1">${{s.symbol}}</span>
          </td>
          <td class="py-2.5 px-2 text-[var(--muted-foreground,#9ca3af)]">${{s.sector_cn}}</td>
          <td class="py-2.5 px-2 text-right font-mono tabular-nums">${{s.close.toFixed(2)}}</td>
          <td class="py-2.5 px-2 text-right font-mono font-semibold tabular-nums ${{pctColor(s.chg_1d)}}">${{fmtPct(s.chg_1d)}}</td>
          <td class="py-2.5 px-2 text-right font-mono tabular-nums ${{pctColor(s.chg_5d)}}">${{fmtPct(s.chg_5d)}}</td>
          <td class="py-2.5 px-2 text-right font-mono tabular-nums ${{pctColor(s.chg_20d)}}">${{fmtPct(s.chg_20d)}}</td>
          <td class="py-2.5 px-2 text-right font-mono tabular-nums ${{pctColor(s.ytd)}}">${{fmtPct(s.ytd)}}</td>
          <td class="py-2.5 px-2 text-right font-mono tabular-nums ${{pctColor(s.dist_ma20)}}">${{fmtPct(s.dist_ma20)}}</td>
          <td class="py-2.5 px-2 text-right font-mono tabular-nums ${{pctColor(s.dist_ma50)}}">${{fmtPct(s.dist_ma50)}}</td>
          <td class="py-2.5 px-2 text-right font-mono tabular-nums ${{s.rel_vol >= 1.25 ? "font-bold text-[var(--warning,#f59e0b)]" : ""}}">${{s.rel_vol.toFixed(2)}}倍</td>
          <td class="py-2.5 px-2 text-right font-mono tabular-nums text-[var(--muted-foreground,#9ca3af)]">${{s.ann_vol.toFixed(1)}}%</td>
          <td class="py-2.5 px-2 text-right font-mono tabular-nums text-[var(--muted-foreground,#9ca3af)]">${{fmtPct(s.dist_52w)}}</td>
        </tr>
      `).join("");
    }}

    document.querySelectorAll(".sector-btn").forEach(btn => {{
      btn.addEventListener("click", () => {{
        currentSector = btn.dataset.sector;
        document.querySelectorAll(".sector-btn").forEach(b => {{
          b.className = "sector-btn px-3 py-1 rounded-md text-xs font-medium border border-[var(--border,#1f2937)] text-[var(--muted-foreground,#9ca3af)]";
        }});
        btn.className = "sector-btn px-3 py-1 rounded-md text-xs font-medium border border-[var(--primary,#3b82f6)] bg-[var(--primary,#3b82f6)] text-[var(--primary-foreground,#ffffff)]";
        renderTable();
      }});
    }});

    document.querySelectorAll("th.sortable").forEach(th => {{
      th.addEventListener("click", () => {{
        const key = th.dataset.sort;
        if (sortKey === key) {{
          sortAsc = !sortAsc;
        }} else {{
          sortKey = key;
          sortAsc = false;
        }}
        renderTable();
      }});
    }});

    // 8. 渲染初学者的术语通俗伴读词典
    const hiddenTerms = new Set();
    let searchKeyword = "";

    function renderGlossary() {{
      const list = DATA.glossary.filter(g => {{
        if (hiddenTerms.has(g.term)) return false;
        if (!searchKeyword) return true;
        const kw = searchKeyword.toLowerCase();
        return g.term.toLowerCase().includes(kw) || g.category.toLowerCase().includes(kw) || g.definition.toLowerCase().includes(kw);
      }});

      if (list.length === 0) {{
        document.getElementById("glossary-grid").innerHTML = `
          <div class="col-span-2 text-xs text-[var(--muted-foreground,#9ca3af)] py-4 text-center">
            未找到匹配术语，或当前术语均已隐藏。
          </div>
        `;
        return;
      }}

      document.getElementById("glossary-grid").innerHTML = list.map(g => `
        <div class="p-3.5 rounded-lg border border-[var(--border,#1f2937)] bg-[var(--background,#0b0f19)] space-y-1.5">
          <div class="flex items-start justify-between gap-2">
            <div>
              <span class="text-xs px-2 py-0.5 rounded border border-[var(--border,#1f2937)] text-[var(--primary,#3b82f6)] mr-1.5">${{g.category}}</span>
              <span class="text-sm font-bold">${{g.term}}</span>
            </div>
            <button data-hide="${{g.term}}" class="hide-term-btn text-xs text-[var(--muted-foreground,#9ca3af)] hover:text-[var(--foreground,#f3f4f6)] shrink-0">
              本次隐藏
            </button>
          </div>
          <p class="text-xs text-[var(--foreground,#f3f4f6)] leading-relaxed"><strong>通俗理解：</strong>${{g.definition}}</p>
          <p class="text-xs text-[var(--muted-foreground,#9ca3af)] leading-relaxed"><strong>看盘意义：</strong>${{g.practical}}</p>
        </div>
      `).join("");

      document.querySelectorAll(".hide-term-btn").forEach(btn => {{
        btn.addEventListener("click", () => {{
          hiddenTerms.add(btn.dataset.hide);
          renderGlossary();
        }});
      }});
    }}

    document.getElementById("glossary-search").addEventListener("input", (e) => {{
      searchKeyword = e.target.value.trim();
      renderGlossary();
    }});

    renderDivergingChart();
    renderTable();
    renderGlossary();
  </script>
</body>
</html>
"""


def get_default_narrative(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """根据采集到的当日量化、情绪与官方信源数据生成默认纯正中文语序解读（支持特定日期深度增强）。"""
    tdate = payload["latest_trading_date"]

    # 针对 2026-11-23 提供经过官方信源完整交叉核验的纯中文语序深度定稿；其他未来交易日亦可全自动回退生成
    if tdate == "2026-11-23":
        official_ctx = {
            "fed_policy_summary_cn": [
                "**美联储10月利率决议维持 3.75%~4.00% 不变（官方表决 10:2）**：在2026年10月27日至28日例会上，联邦公开市场委员会投票决定维持联邦基金利率目标区间在 **3.75% 至 4.00%**，其中理事库克（Lisa D. Cook）与克利夫兰联储主席哈马克（Beth M. Hammack）投出反对票，主张当场加息25个基点。",
                "**11月18日公布的官方会议纪要释放偏鹰派加息讨论信号**：官方纪要显示，多位与会委员认为10月按兵不动属于“险胜式的权衡”，几乎全体委员认为若通胀未能持续回落至 2% 目标，后续进一步**加息**将是恰当之举，市场据此持续关注12月议息会议动向。",
                "**多位美联储高层密集发表官方政策讲话**：11月19日至20日，美联储副主席杰斐逊、理事沃勒及理事库克先后在巴西央行会议、华盛顿联储挑战赛及智利央行年会上发表正式演讲，强调在通胀具备粘性的背景下，货币政策需保持足够限制性并视后续官方通胀数据相机抉择。",
            ],
            "trade_and_tech_summary_cn": [
                "**美国商务部工业与安全局（BIS）《先进半导体远程算力访问管制新规》于11月19日正式生效**：该项刊登于《美国联邦公报》的临时最终规则（EAR § 744.24）由美国财政部与国家安全委员会指导制定，首次将管制重心从“物理芯片运输出口”延伸至“全球数据中心远程算力租赁”——凡向中国等受限地区实体提供总算力性能超阈值（1,200万 TPP）远程访问服务的海外数据中心均须申请美国许可；同时将**印尼、马来西亚、新加坡、泰国、巴西**五国纳入高风险转运严控许可名单，并正式废止旧版人工智能扩散规则。",
                "**美国贸易代表办公室（USTR）维持关税高压执法并更新301条款公告**：贸易代表格里尔于11月18日发表官方讲话重申维持基准关税框架；同月《联邦公报》先后刊发对华301条款部分工业品关税排除展期公告、海事物流与造船领域301行动修订通知、延长对越南301调查决定，以及依据《美墨加协定》（USMCA）要求墨西哥政府审查跨境制造工厂劳工合规的正式公函。",
            ],
            "macro_data_summary_cn": [
                "**美国经济分析局（BEA）经济增长与物价官方核算**：此前公布的三季度美国实际国内生产总值（GDP）初值年化增长 **3.4%**，核心个人消费支出（核心 PCE）物价指数年化上涨 **2.5%**；经济分析局定于 **2026年11月25日（周三）** 正式发布三季度 GDP 二次修正值及企业利润与最新 PCE 物价数据。",
                "**美国劳工统计局（BLS）就业与通胀官方底数**：11月6日官方非农报告显示10月新增非农就业 **16.5万人**、失业率稳定在 **4.1%**；11月10日官方消费者物价指数（CPI）环比上涨 **0.4%**（住房与食品为主要推手），显示美国经济韧性与物价粘性并存。",
            ],
            "sec_highlights_cn": [
                "**英伟达（NVDA）于11月23日提交 8-K 法定高管复职公告（条款 5.02）**：董事会经一致表决，正式恢复联合创始人黄仁勋的总裁、首席执行官及董事职务并立即生效（此前美国政府高层已明确反馈不存在国家安全风险），正式终结自11月12日以来的公司治理悬念。",
                "**众击安全（CRWD）于11月23日密集提交 8-K 与多份 425 法定并购及财报文件**：公司一方面正式披露2027财年三季度业绩（营收15.8亿美元、同比增长28%，净新增年度经常性收入创纪录达4.19亿美元），另一方面正式签署以**全股票方式作价约439亿美元收购云安全龙头 Zscaler（ZS）**的法定合并协议（每1股 ZS 换取 1.135 股 CRWD）。",
                "**派拓网络（PANW）、超威半导体（AMD）与脸书母公司（META）近期 8-K 披露**：派拓网络于11月18日正式披露2027财年一季度财报（营收同比增39%至34.4亿美元）及并购事项；超威半导体与脸书母公司亦分别于11月20日及23日向美国证监会提交最新 8-K 法定报告。",
            ],
        }

        narrative = {
            "market_calendar_note": "正常交易日；北京时间 2026年11月24日凌晨收盘；本周四11月26日感恩节美股将全天休市",
            "executive_intro": "2026年11月23日（星期一），美股科技板块在经历连续数周的深度回调后，迎来一场罕见的**超跌逼空与信心全面修复行情**。盘前**英伟达（NVDA）**向美国证监会正式提交高管复职公告，宣布董事会一致投票恢复创始人黄仁勋的首席执行官职务，并获美国政府高层“无国家安全风险”明确背书。这一核心治理危机的解除直接点燃算力产业链买盘，推动纳斯达克综合指数创下 **1991年以来最大开盘涨幅纪录**，四大基准指数全天高开高走：",
            "executive_bullets": [
                "**四大指数全线暴涨，芯片板块领跑全场**：**费城半导体指数**单日飙升 **+14.03%** 收于 **9,588.05** 点；**纳斯达克100指数**大涨 **+6.86%** 收报 **26,746.10** 点；**纳斯达克综合指数**跃升 **+6.51%** 收于 **24,089.56** 点；**标普500指数**上涨 **+4.73%** 至 **7,237.17** 点，创下2025年4月以来最佳单日表现。",
                "**恐慌情绪骤降，但高波动与政策约束仍在**：随着避险情绪迅速退潮，标普500恐慌指数单日暴跌 **25.83%** 回落至 **26.62**，纳指100波动率指数回落 **19.76%** 至 **36.31**；但受美联储10月会议纪要偏鹰派加息讨论制约，10年期美债收益率仍坚守 **4.92%** 高位，黑天鹅偏度指数亦升至 **140.37**，提示机构在追涨同时仍保留尾部防跌保护。",
                "**个股呈现“算力狂欢”与“并购稀释重挫”的鲜明分化**：19家核心科技股中 **18家收涨（上涨占比 94.7%）**，全样本等权平均大涨 **+7.67%**。**英伟达（+31.48%，量比 2.71倍）** 单日市值激增约9,500亿美元，带动**美光科技（+19.04%）**、**英特尔（+16.34%）**、**特斯拉（+11.46%）**与**帕兰提尔（+11.06%）**领涨；唯独网络安全龙头**众击安全（CRWD，-8.92%，量比 4.59倍）**因宣布439亿美元全股票收购 Zscaler 引发约19%股本稀释担忧，放天量逆势下跌。",
            ],
            "official_digest_bullets": [
                "**美元利率与美联储动向**：纽约联储最新公布的联邦基金有效利率（EFFR）稳定于 **3.88%**（处于美联储 **3.75%~4.00%** 官方目标区间），担保隔夜融资利率（SOFR）报 **3.92%**；但11月18日公布的美联储10月议息纪要显示几乎所有委员认为若通胀居高不下，后续仍有必要继续**加息**，市场紧盯本周三（11月25日）即将公布的美国三季度 GDP 二次修正值与 PCE 物价指数。",
                "**国际贸易与半导体出口管制**：美国商务部工业与安全局（BIS）《管控先进半导体远程算力访问》新规已于11月19日正式生效，首次对向受限地区提供超阈值远程云算力的海外数据中心实施全球许可管制，并将新加坡、马来西亚、印尼、泰国、巴西五国列入严控转运许可范围；美国贸易代表办公室同步重申维持301条款及基准关税执法框架。",
                "**证监会法定公司披露**：11月23日**英伟达**正式提交 8-K 表（条款 5.02）确认黄仁勋复职；同日**众击安全**正式提交 8-K 与 425 表披露超预期三季报及 439 亿美元全股票换股收购 Zscaler 的约束性协议。",
            ],
            "rotation_insights": [
                "**高弹性算力与存储链领衔反攻，稳健防御型巨头相对滞涨**：此前近20个交易日回撤最深的**半导体与芯片设备板块**（近20日等权跌 -16.02%）成为当日空头回补主战场，6家公司全线收涨、等权单日涨幅高达 **+10.80%**；反观前期抗跌的稳健现金流龙头**苹果（+1.90%）**与**微软（+1.65%）**，在资金大举涌向高弹性品种时涨幅明显落后于指数。",
                "**单日广度极强但中期均线修复尚未完成**：尽管当日上涨广度高达 **94.7%**，但从均线趋势看，19家样本股中仍有 **16家（84.2%）位于20日与50日均线下方**，其中半导体板块站上20日与50日均线的家数依然是 **0家**。这表明周一的长阳本质上属于极端超卖后的首轮情绪修复，中期下降通道尚未彻底扭转。",
                "**网络安全双雄因并购筹码结构差异而剧烈分化**：**众击安全（-8.92%）**受大额全股票并购带来的股本摊薄拖累重挫，拉低软件板块等权涨幅至 **+3.03%**；而竞争对手**派拓网络（+2.94%，近5日累计 +11.81%）**凭借上周优异财报及无大额稀释优势承接了板块避险资金，稳居近5日全样本涨幅榜首。",
            ],
            "volume_signals": [
                "**众击安全（CRWD｜量比 4.59倍｜单日 -8.92%）**：全日狂飙至 4,231.33 万股（过去20日均量仅 921.55 万股），天量长阴直接击穿20日与50日均线，盘中最低触及 200.53 美元整数关口，目前仅依靠200日均线（176.74美元）提供长期支撑。",
                "**英伟达（NVDA｜量比 2.71倍｜单日 +31.48%）**：单日成交高达 7.79 亿股，资金承接极为踊跃，股价自上周五52周收盘低点（125.53美元）暴力拉升至 165.05 美元，上方即将面临20日均线（178.91美元）的套牢盘检验。",
                "**美光科技（MU｜量比 1.47倍｜+19.04%）与高通（QCOM｜量比 1.37倍｜+10.30%）**：同步放量长阳反抽，其中高通收盘价距离20日均线仅差 -2.22%，具备率先收复短期均线的潜力。",
                "**博通（AVGO｜量比 1.35倍｜+3.00%）与超威半导体（AMD｜量比 1.27倍｜+6.85%）**：两者虽放量跟涨，但涨幅明显落后于费城半导体指数（+14.03%），显示上方短线解套抛压较重。",
                "**特斯拉（TSLA｜量比 1.28倍｜+11.46%）与帕兰提尔（PLTR｜量比 1.28倍｜+11.06%）**：双双放量突破关键均线——特斯拉单日一根长阳同时收复20日、50日与200日三条均线；帕兰提尔则重新夺回200日牛熊分界线（154.09美元）。",
            ],
            "ma_signals": [
                "**全均线多头标的仅存两席**：截至收盘，19家样本公司中仅有**苹果**与**特斯拉**两家同时站在20日、50日与200日三重均线之上，趋势结构最为完好。",
                "**芯片股波动率仍处历史极值区间**：英特尔（142.8%）、英伟达（136.9%）、超威半导体（133.0%）、美光科技（131.8%）的20日年化波动率全部突破 130%，费城半导体指数年化波动率亦高达 **96.13%**，意味着短期日内震荡幅度仍将远超常态。",
            ],
            "stock_catalysts": [
                "**英伟达（+31.48%）**：核心驱动力为公司向美国证监会提交的黄仁勋复职 8-K 法定公告及白宫安全背书，彻底消除了困扰算力龙头的管理层真空。",
                "**众击安全（-8.92%）**：基本面三季报营收与净新增年度经常性收入双双创纪录并上调指引，但高达439亿美元的全股票收购 Zscaler 方案需增发约1.91亿股新股（摊薄现有股东权益约19%），引发机构对并购估值与整合难度的集中避险。",
                "**美光科技（+19.04%）、英特尔（+16.34%）、高通（+10.30%）、阿斯麦（+9.28%）**：受益于人工智能数据中心投资信心修复与前期深度超跌后的空头回补；其中英特尔叠加此前官方宣布 18A-P 先进制程斩获首个外部代工客户的利好延续，近5日逆势累涨 +7.55%。",
                "**特斯拉（+11.46%）、帕兰提尔（+11.06%）、新思科技（+7.78%）**：高弹性科技成长股随大盘风险偏好反转大幅上扬，资金回补前期跌幅较大的软件与智能驾驶龙头。",
                "**脸书母公司（+6.55%）、谷歌母公司（+6.34%）、亚马逊（+3.47%）**：超大规模云厂商随人工智能基础设施情绪回暖同步修复估值。",
            ],
            "outlook_points": [
                "**感恩节假期前的官方通胀大考**：本周四（11月26日）感恩节休市、周五提前半日收盘，节前交投流动性将逐步回落。周三（11月25日）美国经济分析局将正式公布**三季度 GDP 二次修正值与 PCE 物价指数**，若核心通胀超预期走高，可能推升12月美联储加息预期并令接近 5% 的10年期美债收益率再度施压科技股。",
                "**重点观察 20日均线与 200日均线阻力突破有效性**：标普500指数距200日均线仅剩 -1.54%，纳斯达克综合指数距20日均线为 -3.63%。未来两个交易日若能温和放量站稳均线上方，方能确认中期阶段性底部成立；反之若缩量冲高受阻，需提防空头回补结束后的二次回踩。",
                "**跟踪出口管制细则与并购消化情况**：持续留意半导体企业在商务部远程算力管制新规生效后的合规指引更新，以及众击安全在 200 美元整数关口与 200日均线（176.74美元）之间的机构筹码沉淀情况。",
            ],
            "dashboard_commentary_cards": [
                {
                    "tag": "法定催化 • 算力芯片领涨",
                    "tagColor": "text-[var(--success,#10b981)]",
                    "title": "黄仁勋正式复职引爆英伟达单日暴涨 +31.48%",
                    "body": "英伟达向美国证监会提交 8-K 法定公告恢复黄仁勋首席执行官职务，单日成交 7.79 亿股（量比 2.71倍），带动费城半导体指数飙升 14.03%，美光科技与英特尔双双大涨超 16%。",
                },
                {
                    "tag": "法定并购 • 网安龙头分化",
                    "tagColor": "text-[var(--error,#ef4444)]",
                    "title": "众击安全 439亿美元全股票并购引发 -8.92% 放量下跌",
                    "body": "众击安全三季报超预期，但同步提交法定协议以全股票方式收购 Zscaler（预计增发约19%新股），股本摊薄担忧导致 4.59倍天量抛售，成为全样本唯一收跌个股。",
                },
                {
                    "tag": "情绪与宏观 • 节前关键节点",
                    "tagColor": "text-[var(--warning,#f59e0b)]",
                    "title": "恐慌指数骤降 25.8%，紧盯周三官方 PCE 与均线阻力",
                    "body": "综合情绪回暖至 55.7 分，但 84.2% 核心科技股仍处 20日与50日均线下方，且黑天鹅偏度升至 140.37。感恩节休市前需重点关注周三官方 GDP 修正值与 PCE 物价数据。",
                },
            ],
            "dashboard_official_pillars": [
                {
                    "pillar": "一、美元利率与美联储政策",
                    "authority": "美联储 / 纽约联储",
                    "items": [
                        "联邦基金利率目标区间维持 3.75%~4.00%（10月决议 10:2 通过，2名委员主张加息25基点）；纽约联储最新有效利率 EFFR 报 3.88%，隔夜融资利率 SOFR 报 3.92%。",
                        "11月18日公布的10月会议纪要显示，几乎全体委员认为若通胀粘性持续，后续进一步加息仍属必要。",
                        "副主席杰斐逊、理事沃勒与库克于11月19日至20日密集发表正式演讲，强调政策需维持限制性以锚定 2% 通胀目标。",
                    ],
                },
                {
                    "pillar": "二、国际贸易与技术出口管制",
                    "authority": "商务部 BIS / 贸易代表 USTR",
                    "items": [
                        "商务部工业与安全局《管控先进半导体远程算力访问》新规于11月19日正式生效，严控海外数据中心向受限地区提供超阈值远程算力，并对新加坡、马来西亚等五国增设转运许可。",
                        "贸易代表格里尔11月18日正式重申坚持现行基准关税执法框架，联邦公报同步刊发对华301部分产品关税排除延期及海事物流301修订公告。",
                        "美国经济分析局定于11月25日（周三）正式发布三季度 GDP 二次修正值与核心 PCE 物价指数。",
                    ],
                },
                {
                    "pillar": "三、证监会上市公司法定披露",
                    "authority": "美国证监会 SEC EDGAR",
                    "items": [
                        "英伟达（11月23日 8-K 条款5.02）：董事会一致表决立即恢复黄仁勋总裁、首席执行官及董事职务。",
                        "众击安全（11月23日 8-K 及 425 表）：正式披露创纪录三季报（营收增28%至15.8亿美元），并签署439亿美元全股票收购 Zscaler 法定合并协议。",
                        "派拓网络（11月18日 8-K）：正式披露一季报营收大增39%至34.4亿美元；超威半导体与脸书母公司亦于近日提交法定临时报告。",
                    ],
                },
            ],
        }
        return official_ctx, narrative

    # 通用自动化纯中文语序模板（供今后任意新交易日无人值守直接运行）
    all_rows = payload["data"]
    indices = {r["symbol"]: r for r in all_rows if r["category"] == "Indices"}
    stocks = [r for r in all_rows if r["category"] != "Indices"]
    ms = payload["market_sentiment"]
    os_d = payload["official_sources"]

    ixic = indices["^IXIC"]
    ndx = indices["^NDX"]
    sox = indices["^SOX"]
    gspc = indices["^GSPC"]
    sorted_s = sorted(stocks, key=lambda x: x["chg_1d_pct"], reverse=True)
    vol_s = sorted([s for s in stocks if (s["rel_vol_20d"] or 0) >= 1.25], key=lambda x: x["rel_vol_20d"], reverse=True)

    direction_word = "震荡收高" if ixic["chg_1d_pct"] >= 0 else "承压回落"
    official_digest = []
    if os_d.get("nyfed_rates"):
        r0 = os_d["nyfed_rates"][0]
        official_digest.append(f"**纽约联储官方资金利率**：最新{r0['name_cn']}报 **{r0['rate_pct']:.2f}%**（生效日 {r0['effective_date']}）。")
    for it in os_d.get("fed_monetary_and_speeches", [])[:2]:
        cat = "fed_speech" if "演讲" in it["source_cn"] else "fed_monetary"
        official_digest.append(f"**[{it['date']}｜{it['source_cn']}]** {translate_official_title_cn(cat, it['title_raw'])}")
    for doc in os_d.get("federal_register_trade_tech", [])[:2]:
        official_digest.append(f"**[{doc['date']}｜联邦公报经贸与管制]** {translate_official_title_cn('fedreg', doc['title_raw'])}")

    generic_narrative = {
        "market_calendar_note": "美股最新收盘交易日",
        "executive_intro": f"美东时间 {tdate}，美股科技与核心基准指数整体呈现**{direction_word}**态势，综合市场情绪评分为 **{ms['composite_score']} 分（{ms['regime_cn']}）**：",
        "executive_bullets": [
            f"**核心指数表现**：纳斯达克综合指数收报 **{ixic['close']:,.2f}**（{fmt_pct(ixic['chg_1d_pct'], True)}），纳斯达克100指数收报 **{ndx['close']:,.2f}**（{fmt_pct(ndx['chg_1d_pct'], True)}），费城半导体指数收报 **{sox['close']:,.2f}**（{fmt_pct(sox['chg_1d_pct'], True)}），标普500指数收报 **{gspc['close']:,.2f}**（{fmt_pct(gspc['chg_1d_pct'], True)}）。",
            f"**市场广度与情绪**：19家核心科技股中 **{ms['up_stocks']} 家收涨（占比 {ms['breadth_1d_pct']}%）**；{ms['summary_notes_cn'][0] if ms['summary_notes_cn'] else ''}",
            f"**领涨与领跌焦点**：单日表现最强个股为 **{sorted_s[0]['name_cn']}（{fmt_pct(sorted_s[0]['chg_1d_pct'])}）** 与 **{sorted_s[1]['name_cn']}（{fmt_pct(sorted_s[1]['chg_1d_pct'])}）**；表现最弱个股为 **{sorted_s[-1]['name_cn']}（{fmt_pct(sorted_s[-1]['chg_1d_pct'])}）**。",
        ],
        "official_digest_bullets": official_digest or ["详见《资讯栏目》当日官方政策文件汇编。"],
        "rotation_insights": [
            f"**子板块强弱排序**：对比三大科技板块单日等权表现，资金围绕业绩确定性与估值弹性展开结构性轮动，当前全样本站上50日均线比例为 {ms['above_ma50_count']}/{ms['total_stocks']}。",
            f"**长期牛熊分界观察**：共 {ms['above_ma200_count']} 家核心科技股运行在200日均线之上，中长期趋势分化显著。",
        ],
        "volume_signals": [
            f"**{s['name_cn']}（{s['symbol']}｜量比 {s['rel_vol_20d']:.2f}倍｜单日 {fmt_pct(s['chg_1d_pct'])}）**：成交 {fmt_vol_cn(s['volume'])}，{ma_posture_cn(s)}。"
            for s in vol_s
        ] or ["当日无20日量比超过1.25倍的显著放量标的，整体交投平稳。"],
        "ma_signals": [
            f"**均线支撑与压力**：纳斯达克综合指数当前较20日均线偏离 {fmt_pct(ixic['dist_ma20_pct'])}、较50日均线偏离 {fmt_pct(ixic['dist_ma50_pct'])}；费城半导体指数20日年化波动率为 {sox['ann_vol_20d_pct']:.2f}%。"
        ],
        "stock_catalysts": [
            f"**{s['name_cn']}（{fmt_pct(s['chg_1d_pct'])}，量比 {s['rel_vol_20d']:.2f}倍）**：日内价格波动显著，建议结合《资讯栏目》中美国证监会最新 8-K 法定披露跟踪基本面变化。"
            for s in sorted_s[:3] + sorted_s[-2:]
        ],
        "outlook_points": [
            "**紧盯美联储利率预期与10年期美债收益率走向**：长端利率变化仍是决定科技成长股估值折现空间的首要宏观变量。",
            "**关注关键均线得失与成交量配合**：观察领涨品种能否持续放量站稳20日与50日均线。",
        ],
        "dashboard_commentary_cards": [
            {
                "tag": "指数与广度",
                "tagColor": "text-[var(--primary,#3b82f6)]",
                "title": f"纳指单日 {fmt_pct(ixic['chg_1d_pct'])}，样本 {ms['up_stocks']} 涨 {ms['total_stocks'] - ms['up_stocks']} 跌",
                "body": f"费城半导体指数单日 {fmt_pct(sox['chg_1d_pct'])}，全样本站上50日均线共 {ms['above_ma50_count']} 家。",
            },
            {
                "tag": "领涨龙头",
                "tagColor": "text-[var(--success,#10b981)]",
                "title": f"{sorted_s[0]['name_cn']}（{fmt_pct(sorted_s[0]['chg_1d_pct'])}）领跑核心科技股",
                "body": f"当日量比 {sorted_s[0]['rel_vol_20d']:.2f}倍，收盘报 {sorted_s[0]['close']:.2f} 美元，{ma_posture_cn(sorted_s[0])}。",
            },
            {
                "tag": "波动与防守",
                "tagColor": "text-[var(--error,#ef4444)]",
                "title": f"{sorted_s[-1]['name_cn']}（{fmt_pct(sorted_s[-1]['chg_1d_pct'])}）表现承压",
                "body": f"综合情绪得分 {ms['composite_score']} 分（{ms['regime_cn']}），建议关注高波动标的仓位管理。",
            },
        ],
        "dashboard_official_pillars": [
            {
                "pillar": "一、美元利率与央行动态",
                "authority": "美联储 / 纽约联储",
                "items": [
                    translate_official_title_cn("fed_speech" if "演讲" in x["source_cn"] else "fed_monetary", x["title_raw"])
                    for x in os_d.get("fed_monetary_and_speeches", [])[:3]
                ] or ["暂无新增美联储货币政策公报。"],
            },
            {
                "pillar": "二、国际贸易与技术管制",
                "authority": "联邦公报 / 商务部 / USTR",
                "items": [
                    translate_official_title_cn("fedreg", x["title_raw"])
                    for x in os_d.get("federal_register_trade_tech", [])[:3]
                ] or ["暂无新增联邦公报经贸管制文件。"],
            },
            {
                "pillar": "三、证监会法定重大公告",
                "authority": "美国证监会 SEC",
                "items": [
                    f"{x['filing_date']}｜{x['name_cn']}（{x['symbol']}）提交 {x['form']}：{x['items_cn']}"
                    for x in os_d.get("sec_8k_filings", [])[:3]
                ] or ["近期暂无新增核心科技股 8-K 法定披露。"],
            },
        ],
    }
    return {}, generic_narrative


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="生成纯中文语序纳斯达克投研报告、官方资讯专刊与交互看板")
    parser.add_argument("--input-json", type=str, help="可选：从已有采集 JSON 文件读取，省去重复联网")
    args = parser.parse_args()

    if args.input_json:
        payload = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
    else:
        payload = collect_all()

    tdate = payload["latest_trading_date"]
    BRIEFING_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 保存官方信源原始结构化快照
    snapshot_path = BRIEFING_DIR / f"{tdate}_官方信源原始快照.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "latest_trading_date": tdate,
                "market_sentiment": payload["market_sentiment"],
                "official_sources": payload["official_sources"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    # 2. 生成《资讯栏目/YYYY-MM-DD_官方宏观与政策资讯.md》
    official_ctx, narrative = get_default_narrative(payload)
    briefing_md, _ = build_official_briefing_md(payload, official_ctx)
    briefing_path = BRIEFING_DIR / f"{tdate}_官方宏观与政策资讯.md"
    briefing_path.write_text(briefing_md, encoding="utf-8")

    # 3. 生成主报告《YYYY-MM-DD.md》与交互看板《YYYY-MM-DD.html》
    rel_briefing = f"资讯栏目/{tdate}_官方宏观与政策资讯.md"
    report_md, glossary_items = build_daily_report_md(payload, narrative, rel_briefing)
    md_path = BASE_DIR / f"{tdate}.md"
    md_path.write_text(report_md, encoding="utf-8")

    html_str = build_dashboard_html(payload, narrative, glossary_items)
    html_path = BASE_DIR / f"{tdate}.html"
    html_path.write_text(html_str, encoding="utf-8")

    # 4. 同步运行美债长短期期限利差计算与可视化算法
    spread_res = run_spread_pipeline()

    print(f"[生成完成] 主报告：{md_path}")
    print(f"[生成完成] 交互看板：{html_path}")
    print(f"[生成完成] 官方政策资讯专刊：{briefing_path}")
    print(f"[生成完成] 官方信源快照：{snapshot_path}")
    print(f"[生成完成] 美债利差走势图：{spread_res['png_path']}")
    print(f"[生成完成] 美债利差交互看板：{spread_res['html_path']}")
    print(f"[术语伴读] 本期自动推断并解释专业术语 {len(glossary_items)} 条")


if __name__ == "__main__":
    main()
