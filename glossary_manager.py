"""初学者投研术语智能识别、通俗中文释义与“免解释”记忆管理模块。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "术语配置.json"

# 术语知识库：采用纯正中文语序，分为“通俗理解”与“看盘实战意义”两部分
TERM_DATABASE: list[dict[str, Any]] = [
    {
        "term": "美联储与联邦公开市场委员会（FOMC）",
        "category": "宏观与货币政策",
        "keywords": ["美联储", "FOMC", "联邦公开市场委员会"],
        "aliases": ["FOMC", "美联储", "联储"],
        "definition": "美联储是美国的中央银行，而联邦公开市场委员会（简称 FOMC）是美联储内部专门决定“美元基准利率涨跌”的核心决策机构，每年通常召开 8 次例会。",
        "practical": "全球资金成本都看它脸色：一旦委员会态度强硬（市场俗称“鹰派”），意味着利率可能维持高位甚至继续加息，科技股往往承压；态度温和（俗称“鸽派”），则利好科技股估值扩张。",
    },
    {
        "term": "加息、降息与联邦基金利率",
        "category": "宏观与货币政策",
        "keywords": ["加息", "降息", "减息", "联邦基金利率", "利率目标区间", "EFFR"],
        "aliases": ["加息", "降息", "减息", "联邦基金利率", "EFFR"],
        "definition": "联邦基金利率是美国商业银行之间隔夜拆借美元的基准利率。调高该利率即“加息”，意在给过热经济和物价降温；调低即“降息”（或减息），意在降低企业和个人借钱成本、刺激经济。",
        "practical": "科技成长股大量利润来自未来数年，利率越高，未来利润折算到今天的价值就越低。因此“预期加息”通常压制纳斯达克，“预期降息”则提振纳斯达克。",
    },
    {
        "term": "基点（bp）",
        "category": "宏观与货币政策",
        "keywords": ["基点", "bp"],
        "aliases": ["基点", "bp", "BP"],
        "definition": "金融市场用来衡量利率微幅变动的最小常用单位。1 个基点等于 0.01%（即万分之一），100 个基点等于 1 个百分点（1%）。",
        "practical": "例如常说的“美联储加息 25 个基点”，就是把基准利率上调 0.25%；“美债收益率跳升 10 个基点”，代表借债成本上升了 0.10%。",
    },
    {
        "term": "担保隔夜融资利率（SOFR）",
        "category": "宏观与货币政策",
        "keywords": ["SOFR", "担保隔夜融资利率"],
        "aliases": ["SOFR", "隔夜融资利率"],
        "definition": "金融机构以美国国债作为抵押物、向市场借入隔夜美元现金的实际利率，由纽约联储每日官方公布。",
        "practical": "它是观察美元金融体系“钱荒与否”的最真实温度计：若该利率突然大幅高于美联储利率区间上限，说明市场短期现金流动性吃紧。",
    },
    {
        "term": "10年期美债收益率",
        "category": "宏观与货币政策",
        "keywords": ["10年期美债收益率", "十年期美债"],
        "aliases": ["10年期美债", "10年期美债收益率", "^TNX", "美债收益率"],
        "definition": "投资者购买并持有美国政府 10 年期国债所能获得的年化回报率，被华尔街公认为“全球资产定价之锚”。",
        "practical": "由于美国国债几乎没有违约风险，当 10 年期美债收益率接近或突破 5% 时，大量稳健资金会觉得“躺赚 5% 利息很划算”，从而减少对高估值科技股的配置。",
    },
    {
        "term": "美债期限利差（收益率曲线与倒挂）",
        "category": "宏观与货币政策",
        "keywords": ["期限利差", "利差", "10年减3月", "10年期减13周", "10年期减2年期", "收益率曲线", "倒挂"],
        "aliases": ["期限利差", "收益率倒挂", "收益率曲线", "10Y-3M", "10Y-2Y"],
        "definition": "用长期国债收益率减去短期国债收益率得到的差值（常见有“10年期减13周短债”和“10年期减2年期国债”）。正常情况下借钱时间越长，要求的利息补偿越高，利差为正数；若短期利率反超长期利率（利差变成负数），就叫“收益率倒挂”。",
        "practical": "利差保持正数且温和走阔，通常说明市场预期经济维持正增长或长期通胀有溢价；若利差由正转负陷入深度倒挂，历史上往往是美联储加息过猛、未来经济面临降温甚至衰退的经典预警。",
    },
    {
        "term": "收益率曲线形态演变（牛陡、熊陡、牛平、熊平）",
        "category": "宏观与货币政策",
        "keywords": ["牛陡", "熊陡", "牛平", "熊平", "陡峭化", "平坦化"],
        "aliases": ["牛陡", "熊陡", "牛平", "熊平", "曲线陡峭化", "曲线平坦化"],
        "definition": "债券价格与收益率反向变动（收益率跌=债券涨=债牛；收益率涨=债券跌=债熊）。利差变大叫“变陡”，利差缩小叫“变平”。由此组合成四种常见状态：①牛陡（短端利率降得比长端更快，常见于降息预期升温）；②熊陡（长端利率涨得比短端更快，常见于通胀担忧或国债增发）；③牛平（长端利率降得比短端更快，常见于避险买盘涌入长债）；④熊平（短端利率涨得比长端更快，常见于美联储释放加息信号）。",
        "practical": "科技成长股最喜欢“牛陡”（降息预期带来流动性宽松），最怕“熊陡”（长端10年期美债收益率快速飙升直接杀估值）与“熊平”（美联储鹰派加息抽紧资金）。",
    },
    {
        "term": "贴现率口径与平价债券等价收益率口径",
        "category": "宏观与货币政策",
        "keywords": ["贴现率口径", "平价收益率", "债券等价收益率"],
        "aliases": ["贴现率口径", "平价收益率", "债券等价收益率"],
        "definition": "二级市场行情代码（如 ^IRX）对3个月期国库券采用“360天贴现率”报价，而美国财政部官网每日曲线表采用“365天平价债券等价收益率”报价，因此同一天财政部公布的3个月收益率通常会比行情贴现率高出约 15~22 个基点。",
        "practical": "看盘时只需保持前后口径统一即可：日常盘中盯盘常用“10年期美债（^TNX）减13周贴现率（^IRX）”，而做跨期限国债曲线研究则统一采用美国财政部官方平价收益率表。",
    },
    {
        "term": "美元指数",
        "category": "宏观与货币政策",
        "keywords": ["美元指数", "DX-Y.NYB"],
        "aliases": ["美元指数", "DXY", "DX-Y.NYB"],
        "definition": "综合反映美元在国际外汇市场上对欧元、日元、英镑等一篮子主要货币强弱程度的指标。",
        "practical": "苹果、英伟达、微软等纳斯达克巨头有一半左右收入来自海外。美元指数过强不仅代表全球美元回流美国本土、新兴市场承压，也会让跨国科技公司的海外收入换算回美元时缩水。",
    },
    {
        "term": "个人消费支出物价指数（PCE）与消费者物价指数（CPI）",
        "category": "宏观与货币政策",
        "keywords": ["PCE", "CPI", "物价指数", "核心PCE"],
        "aliases": ["PCE", "CPI", "核心PCE", "通胀指标"],
        "definition": "两者都是衡量美国物价上涨速度（通货膨胀）的官方指标。其中剔除食品和能源波动后的“核心 PCE 物价指数”，是美联储决定是否加息或降息时最看重的头号通胀依据。",
        "practical": "只要核心 PCE 年化涨幅明显高于美联储设定的 2% 目标，美联储就很难放心降息。",
    },
    {
        "term": "国内生产总值（GDP）与修正值",
        "category": "宏观与货币政策",
        "keywords": ["GDP", "国内生产总值", "二次修正值"],
        "aliases": ["GDP", "国内生产总值"],
        "definition": "衡量一个国家在特定季度或年度内生产的所有最终商品和服务总价值，代表经济增长快慢。美国经济分析局对每季数据会先后发布初值、二次修正值和终值。",
        "practical": "科技股最喜欢“经济温和增长 + 通胀回落”的环境；若经济增长骤降但物价居高不下（俗称“类滞胀”），股市往往剧烈波动。",
    },
    {
        "term": "301条款关税与贸易代表办公室（USTR）",
        "category": "国际经贸与监管",
        "keywords": ["301条款", "贸易代表", "USTR", "关税"],
        "aliases": ["301条款", "USTR", "美国贸易代表办公室"],
        "definition": "美国贸易代表办公室是负责对外贸易谈判与关税政策的总统直属机构；“301条款”则是美国贸易法授权政府对被认定存在“不公平贸易做法”的贸易伙伴加征特别关税的法律工具。",
        "practical": "关税调升会直接推高跨国硬件、消费电子、服务器及汽车供应链的进口成本，并可能引发贸易伙伴反制。",
    },
    {
        "term": "出口管制、工业与安全局（BIS）及实体清单",
        "category": "国际经贸与监管",
        "keywords": ["出口管制", "BIS", "工业与安全局", "实体清单", "远程访问"],
        "aliases": ["BIS", "出口管制", "实体清单"],
        "definition": "美国商务部下属的工业与安全局负责管理高科技产品出口许可。被列入“实体清单”或受限地区的海外机构，未经美国政府特别批准，无法购买美国高端芯片、软件或租用受限的远程云计算算力。",
        "practical": "半导体公司（如英伟达、超威半导体、阿斯麦等）在海外拥有可观收入，出口管制范围的收紧或放宽会直接影响它们的订单预期。",
    },
    {
        "term": "美国证监会 8-K 重大事项法定公告",
        "category": "国际经贸与监管",
        "keywords": ["8-K", "美国证监会", "法定公告"],
        "aliases": ["8-K", "Form 8-K", "8-K公告"],
        "definition": "美国证券交易委员会规定，美股上市公司一旦发生可能显著影响股价的重大事件（如收购兼并、核心高管辞职或复职、正式发布财报等），必须在 4 个工作日内提交的官方披露文件。",
        "practical": "相比社交媒体传闻或小道消息，8-K 文件具有严格法律效力，造假需承担刑事责任，是核实公司重大变动的最高权威一手信源。",
    },
    {
        "term": "恐慌指数（VIX）与纳指波动率指数（VXN）",
        "category": "市场情绪与交易机制",
        "keywords": ["恐慌指数", "VIX", "VXN", "纳指波动率"],
        "aliases": ["VIX", "VXN", "恐慌指数", "^VIX", "^VXN"],
        "definition": "通过期权价格推算出来的未来 30 天市场预期波动幅度。VIX 对应标普500大盘，VXN 则专门对应纳斯达克100科技股。",
        "practical": "数值越低（如低于 18）代表市场平静乐观；突破 25 代表市场紧张不安；突破 35 往往代表极度恐慌抛售。当恐慌指数从高位单日暴跌逾 20% 时，通常意味着恐慌警报暂时解除、资金大举回流股市。",
    },
    {
        "term": "黑天鹅偏度指数（SKEW）",
        "category": "市场情绪与交易机制",
        "keywords": ["黑天鹅", "偏度指数", "SKEW"],
        "aliases": ["SKEW", "^SKEW", "偏度指数", "黑天鹅指数"],
        "definition": "衡量机构投资者在期权市场上花多少钱购买“防范大盘极端暴跌”保险的指标，正常区间通常在 100 至 135 之间。",
        "practical": "当该数值升至 140 以上时，说明尽管指数可能在涨，华尔街大资金暗地里仍在加买“防暴跌保险”，提示需留一份清醒。",
    },
    {
        "term": "信用风险偏好比值（高收益债与长端国债比值）",
        "category": "市场情绪与交易机制",
        "keywords": ["高收益公司债", "信用风险偏好", "HYG", "TLT"],
        "aliases": ["HYG/TLT", "信用风险偏好", "高收益债"],
        "definition": "比较“高收益企业债基金（HYG，风险较高、利息高）”与“长期美国国债基金（TLT，安全避险）”的价格比值。",
        "practical": "债市资金往往比股市更敏锐：比值上升说明聪明钱愿意承担企业违约风险、整体市场偏向进攻；比值大跌则说明资金正在撤退回国债避险。",
    },
    {
        "term": "空头回补（逼空行情）",
        "category": "市场情绪与交易机制",
        "keywords": ["空头回补", "逼空"],
        "aliases": ["空头回补", "逼空"],
        "definition": "此前看跌某只股票的投资者会先“借入股票卖出”（即做空），等跌下来再买回还掉赚差价。如果突然出现重大利好导致股价暴涨，做空者为防止巨额亏损被迫不计成本紧急买回股票平仓，这种集中买入会进一步把股价推得更高。",
        "practical": "熊市或大跌后的单日暴涨（例如单日涨超 10%~30%），往往包含大量空头被迫止损买回的力量，爆发力极强但后续需要真实长线买盘接力。",
    },
    {
        "term": "市场广度（上涨家数占比）",
        "category": "市场情绪与交易机制",
        "keywords": ["市场广度", "广度", "涨跌比"],
        "aliases": ["市场广度", "涨跌比"],
        "definition": "统计指数上涨时，内部究竟是“绝大多数成分股一起涨”，还是“只有两三只超级大盘股拉动指数、其余股票都在跌”。",
        "practical": "健康的上涨需要高市场广度（如超过 70%~80% 的股票同步上涨且站上均线）；若只有少数权重股独涨，行情通常走不远。",
    },
    {
        "term": "高弹性股票（高贝塔 / 高 Beta）",
        "category": "市场情绪与交易机制",
        "keywords": ["高弹性", "高贝塔", "Beta", "贝塔"],
        "aliases": ["Beta", "贝塔", "高弹性"],
        "definition": "衡量个股相对大盘涨跌放大倍数的指标。大盘涨 1% 时往往能涨 2%~3%、大盘跌 1% 时也跌得更猛的股票，称为高弹性（高贝塔）标的，典型代表如半导体、人工智能软件股。",
        "practical": "当市场情绪转暖反攻时，高弹性股票是冲锋主力；当市场避险下跌时，稳健型股票（如苹果）则更抗跌。",
    },
    {
        "term": "移动平均线（20日、50日、200日均线）与均线偏离度",
        "category": "技术分析与量化指标",
        "keywords": ["20日均线", "50日均线", "200日均线", "均线", "偏离度", "20MA", "50MA", "200MA"],
        "aliases": ["均线", "移动平均线", "20MA", "50MA", "200MA", "20日均线", "50日均线", "200日均线", "均线偏离度"],
        "definition": "把过去 20 个、50 个或 200 个交易日的收盘价算出的平均价格，分别代表短期（约一个月）、中期（约一个季度）和长期（约一年）的市场平均持仓成本。当前股价高于或低于均线的百分比即为“均线偏离度”。",
        "practical": "股价站上均线说明近期买入的人普遍赚钱，均线会形成支撑；反之股价跌破均线，上方套牢盘在反弹到均线附近时容易卖出解套，均线就变成了阻力位。其中 200 日均线常被称为“牛熊分界线”。",
    },
    {
        "term": "相对成交量（量比）",
        "category": "技术分析与量化指标",
        "keywords": ["量比", "相对成交量", "RVol"],
        "aliases": ["量比", "相对成交量", "RVol"],
        "definition": "当日成交股数除以过去 20 个交易日平均每日成交股数的倍数。1.0 倍代表成交平平；超过 1.25 倍代表明显放量；超过 2 倍以上属于巨量异动。",
        "practical": "俗话说“股市里什么都能骗人，唯独成交量不会”：放量大涨说明真金白银在抢筹，放量大跌则说明机构资金正在集中撤离。",
    },
    {
        "term": "20日年化波动率",
        "category": "技术分析与量化指标",
        "keywords": ["年化波动率", "20日年化波动率"],
        "aliases": ["年化波动率", "20日年化波动率", "波动率"],
        "definition": "根据最近 20 个交易日每天涨跌幅的剧烈程度，按全年约 252 个交易日折算出的年度价格摆动幅度指标。",
        "practical": "普通稳健大盘股的年化波动率多在 20%~35% 左右；如果某只股票年化波动率高达 100% 以上，说明它近期每天暴涨暴跌如同过山车，仓位控制必须格外谨慎。",
    },
    {
        "term": "距52周高点回撤",
        "category": "技术分析与量化指标",
        "keywords": ["距52周高点", "52周高点", "回撤"],
        "aliases": ["52周高点", "距52周高点", "回撤"],
        "definition": "当前收盘价相比过去一年（52周）最高价格下跌了多少百分比。",
        "practical": "通常回撤在 10% 以内属于正常震荡，回撤 10%~20% 称为“技术性回调”，回撤超过 20% 则进入个股或板块层面的“技术性熊市/深度修正区间”。",
    },
    {
        "term": "年度经常性收入（ARR）",
        "category": "科技与财报基本面",
        "keywords": ["ARR", "年度经常性收入"],
        "aliases": ["ARR", "年度经常性收入", "净新增ARR"],
        "definition": "云计算与网络安全软件公司最核心的业绩指标，指客户按年签订订阅合同所带来的可重复、可预测的年度合同收入；“净新增 ARR”则是单季度新签减去流失后的净增加额。",
        "practical": "软件公司不靠一锤子买卖，只要 ARR 保持高速增长，未来几年的现金流就非常稳固。",
    },
    {
        "term": "全股票收购与股本稀释",
        "category": "科技与财报基本面",
        "keywords": ["全股票收购", "股本稀释", "增发新股", "稀释"],
        "aliases": ["全股票收购", "股本稀释", "股权稀释"],
        "definition": "收购方不掏现金，而是向被收购公司的股东“新印一批自家股票”来完成并购。由于总股数变多了，原有老股东手中每一股所占公司的分红和投票权比例就会被摊薄，称为“股本稀释”。",
        "practical": "在大型全股票并购宣布当天，收购方股价往往会因为老股东担心“股份被摊薄、收购出价太贵或整合困难”而出现短期大跌。",
    },
    {
        "term": "资本开支（CapEx）与超大规模云厂商",
        "category": "科技与财报基本面",
        "keywords": ["资本开支", "超大规模云厂商"],
        "aliases": ["CapEx", "资本开支", "超大规模云厂商"],
        "definition": "超大规模云厂商指微软、亚马逊、谷歌、脸书母公司这类运营全球巨型数据中心的科技巨头；它们每年斥巨资购买人工智能芯片、服务器和电力设施的投入就叫“资本开支”。",
        "practical": "云巨头的资本开支正是英伟达、博通、美光等半导体公司的直接收入来源——云巨头越舍得花钱建数据中心，芯片股业绩就越强；但若花钱太多却迟迟赚不到软件收入，云巨头自身股价就会受质疑。",
    },
    {
        "term": "先进制程（如18A）与定制人工智能芯片（TPU/ASIC）",
        "category": "科技与财报基本面",
        "keywords": ["先进制程", "18A", "TPU", "先进封装"],
        "aliases": ["18A", "先进制程", "TPU", "ASIC", "先进封装"],
        "definition": "制程代表芯片内部晶体管的精细程度（18A 约等于 1.8 纳米级别，数字越小越先进、越省电且算力越强）；TPU 则是谷歌联合博通等厂商专门为自家人工智能任务量身定制的专用算力芯片，用以补充英伟达的通用芯片。",
        "practical": "谁能率先量产良率合格的先进制程或拿到云巨头定制芯片大单，谁就能在人工智能硬件竞争中分走高额利润。",
    },
]


def load_ignored_terms() -> list[str]:
    """读取用户配置的免解释术语列表。"""
    if not CONFIG_PATH.exists():
        save_ignored_terms([])
        return []
    try:
        payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        items = payload.get("已掌握免解释术语", [])
        return [str(x).strip() for x in items if str(x).strip()]
    except Exception:
        return []


def save_ignored_terms(terms: list[str]) -> None:
    """保存免解释术语列表至 JSON 配置文件。"""
    unique_terms = list(dict.fromkeys(t.strip() for t in terms if t.strip()))
    payload = {
        "说明": "本文件用于记录您已掌握、今后报告与看板中无需重复解释的金融与科技投研术语。您可直接在此数组中添加名词，或运行 python glossary_manager.py --ignore 名词1 名词2 自动屏蔽。",
        "已掌握免解释术语": unique_terms,
    }
    CONFIG_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _is_term_ignored(entry: dict[str, Any], ignored_list: list[str]) -> bool:
    """判断某个词条是否已被用户标记为不需要解释（支持简称、别名或包含匹配）。"""
    if not ignored_list:
        return False
    candidates = {entry["term"].lower()}
    for a in entry.get("aliases", []):
        candidates.add(a.lower())
    for k in entry.get("keywords", []):
        candidates.add(k.lower())

    for user_item in ignored_list:
        u = user_item.lower().strip()
        if not u:
            continue
        if u in candidates:
            return True
        if any(u in c or c in u for c in candidates if len(u) >= 2):
            return True
    return False


def infer_glossary_for_text(text: str) -> list[dict[str, str]]:
    """扫描中文报告正文，自动推断出现的专业术语并剔除用户已掌握词汇。"""
    ignored = load_ignored_terms()
    matched: list[dict[str, str]] = []
    lower_text = text.lower()

    for entry in TERM_DATABASE:
        if _is_term_ignored(entry, ignored):
            continue
        if any(kw.lower() in lower_text for kw in entry["keywords"]):
            matched.append(
                {
                    "term": entry["term"],
                    "category": entry["category"],
                    "definition": entry["definition"],
                    "practical": entry["practical"],
                }
            )
    return matched


def main() -> None:
    parser = argparse.ArgumentParser(description="管理投研报告中的初学者的术语免解释清单")
    parser.add_argument("--list", action="store_true", help="查看当前免解释清单与词库概览")
    parser.add_argument("--ignore", nargs="+", help="添加不再需要解释的术语（支持多个）")
    parser.add_argument("--restore", nargs="+", help="恢复需要解释的术语（从免解释清单移除）")
    args = parser.parse_args()

    current = load_ignored_terms()

    if args.ignore:
        updated = list(dict.fromkeys(current + args.ignore))
        save_ignored_terms(updated)
        print(f"已将以下名词加入免解释清单：{', '.join(args.ignore)}")
        current = updated

    if args.restore:
        remove_set = {x.lower().strip() for x in args.restore}
        updated = [x for x in current if x.lower().strip() not in remove_set]
        save_ignored_terms(updated)
        print(f"已恢复以下名词的自动解释：{', '.join(args.restore)}")
        current = updated

    if args.list or (not args.ignore and not args.restore):
        print(f"配置文件路径：{CONFIG_PATH}")
        print(f"内置专业术语总数：{len(TERM_DATABASE)} 条")
        print(f"当前已屏蔽（免解释）术语（{len(current)} 条）：{current if current else '暂无（全部自动开启解释）'}")


if __name__ == "__main__":
    main()
