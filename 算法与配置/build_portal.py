"""交互式看板统一门户编译引擎（build_portal.py）。

功能：
自动扫描《交互式看板/》目录下所有按日期命名的每日科技股看板（YYYY-MM-DD.html）与《美债期限利差看板.html》，
编译生成统一的在线门户主页《交互式看板/index.html》（支持一键切换“每日纳斯达克科技看板”、“美债长短期利差看板”与“历史交易日归档”），
供本地浏览器直接双击运行及 GitHub Pages 自动发布为在线网页。
"""

from __future__ import annotations

from pathlib import Path
import re
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
DASHBOARD_DIR = ROOT_DIR / "交互式看板"
DATE_HTML_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.html$")


def build_portal() -> Path:
    """扫描所有看板文件并编译统一门户主页 index.html。"""
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    daily_dates: list[str] = []
    for p in DASHBOARD_DIR.iterdir():
        m = DATE_HTML_RE.match(p.name)
        if m:
            daily_dates.append(m.group(1))
    daily_dates.sort(reverse=True)

    latest_date = daily_dates[0] if daily_dates else ""
    has_spread = (DASHBOARD_DIR / "美债期限利差看板.html").exists()

    options_html = "\n".join(
        f'            <option value="{d}.html">{d}{"（最新收盘）" if i == 0 else ""}</option>'
        for i, d in enumerate(daily_dates)
    )

    portal_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>美股纳斯达克科技与美债利差交互投研门户</title>
  <script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>
  <style>
    html, body {{
      margin: 0;
      padding: 0;
      height: 100%;
      background-color: #0b0f19;
      color: #f3f4f6;
      font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
    }}
    .portal-shell {{
      display: flex;
      flex-direction: column;
      height: 100vh;
    }}
    .portal-frame {{
      flex: 1;
      width: 100%;
      border: 0;
      background-color: #0b0f19;
    }}
  </style>
</head>
<body>
  <div class="portal-shell">
    <nav class="bg-[#111827] border-b border-[#1f2937] px-4 py-2.5 flex flex-wrap items-center justify-between gap-3">
      <div class="flex items-center gap-3">
        <span class="px-2 py-0.5 rounded text-xs font-bold bg-[#3b82f6] text-white">投研总门户</span>
        <span class="text-sm font-bold">纳斯达克核心科技股与美债宏观交互看板中心</span>
      </div>

      <div class="flex flex-wrap items-center gap-2 text-xs">
        <button id="tab-daily" class="px-3 py-1.5 rounded-lg font-semibold border border-[#3b82f6] bg-[#3b82f6] text-white transition">
          每日纳斯达克科技看板
        </button>
        {"<button id='tab-spread' class='px-3 py-1.5 rounded-lg font-semibold border border-[#1f2937] bg-[#0b0f19] text-[#9ca3af] hover:text-white transition'>美债长短期期限利差看板</button>" if has_spread else ""}

        <div id="date-picker-wrap" class="flex items-center gap-1.5 ml-1">
          <label for="date-select" class="text-[#9ca3af]">交易日期：</label>
          <select id="date-select" class="bg-[#0b0f19] border border-[#1f2937] text-[#f3f4f6] rounded-lg px-2.5 py-1 focus:outline-none">
{options_html}
          </select>
        </div>
      </div>
    </nav>

    <iframe id="main-frame" class="portal-frame" src="{latest_date + '.html' if latest_date else '美债期限利差看板.html'}" title="投研交互看板视图"></iframe>
  </div>

  <script>
    const frame = document.getElementById("main-frame");
    const tabDaily = document.getElementById("tab-daily");
    const tabSpread = document.getElementById("tab-spread");
    const dateSelect = document.getElementById("date-select");
    const dateWrap = document.getElementById("date-picker-wrap");

    function setActiveTab(mode) {{
      if (mode === "daily") {{
        tabDaily.className = "px-3 py-1.5 rounded-lg font-semibold border border-[#3b82f6] bg-[#3b82f6] text-white transition";
        if (tabSpread) {{
          tabSpread.className = "px-3 py-1.5 rounded-lg font-semibold border border-[#1f2937] bg-[#0b0f19] text-[#9ca3af] hover:text-white transition";
        }}
        dateWrap.style.display = "flex";
        frame.src = dateSelect.value;
      }} else {{
        if (tabSpread) {{
          tabSpread.className = "px-3 py-1.5 rounded-lg font-semibold border border-[#3b82f6] bg-[#3b82f6] text-white transition";
        }}
        tabDaily.className = "px-3 py-1.5 rounded-lg font-semibold border border-[#1f2937] bg-[#0b0f19] text-[#9ca3af] hover:text-white transition";
        dateWrap.style.display = "none";
        frame.src = "美债期限利差看板.html";
      }}
    }}

    tabDaily.addEventListener("click", () => setActiveTab("daily"));
    if (tabSpread) {{
      tabSpread.addEventListener("click", () => setActiveTab("spread"));
    }}
    dateSelect.addEventListener("change", () => {{
      setActiveTab("daily");
    }});
  </script>
</body>
</html>
"""
    index_path = DASHBOARD_DIR / "index.html"
    index_path.write_text(portal_html, encoding="utf-8")
    return index_path


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    out = build_portal()
    print(f"[门户编译完成] 已生成统一交互看板入口：{out}")


if __name__ == "__main__":
    main()
