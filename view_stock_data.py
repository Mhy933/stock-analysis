"""
Convert collected stock JSON data into a readable local HTML summary.

Usage:
  python view_stock_data.py output/data_159995.json
  python view_stock_data.py output/data_159995.json --output output/summary_159995.html
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


def fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    if isinstance(value, int):
        return f"{value:,}"
    return html.escape(str(value))


def table(title: str, rows: list[dict[str, Any]], limit: int = 20) -> str:
    if not rows:
        return f"<section><h2>{html.escape(title)}</h2><p class='muted'>暂无数据</p></section>"

    rows = rows[:limit]
    columns: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in columns:
                columns.append(key)
        if len(columns) >= 10:
            break
    columns = columns[:10]

    head = "".join(f"<th>{html.escape(str(col))}</th>" for col in columns)
    body = []
    for row in rows:
        cells = "".join(f"<td>{fmt(row.get(col))}</td>" for col in columns)
        body.append(f"<tr>{cells}</tr>")

    more = ""
    if len(rows) == limit:
        more = "<p class='muted'>仅展示前 {0} 条。</p>".format(limit)

    return f"""
    <section>
      <h2>{html.escape(title)}</h2>
      <div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>
      {more}
    </section>
    """


def latest_price_block(kline: list[dict[str, Any]]) -> str:
    if not kline:
        return "<p class='muted'>暂无行情数据</p>"

    latest = kline[-1]
    first = kline[0]
    try:
        start = float(first.get("close", 0))
        close = float(latest.get("close", 0))
        change = (close - start) / start * 100 if start else 0
        change_text = f"{change:+.2f}%"
    except (TypeError, ValueError):
        change_text = "-"

    return f"""
    <div class="metrics">
      <div><b>{fmt(latest.get("close"))}</b><span>最新收盘</span></div>
      <div><b>{change_text}</b><span>区间涨跌</span></div>
      <div><b>{len(kline):,}</b><span>行情记录</span></div>
      <div><b>{fmt(latest.get("day"))}</b><span>最新时间</span></div>
    </div>
    """


def render_html(data: dict[str, Any], source: Path) -> str:
    blocks = data.get("blocks", data)
    if not isinstance(blocks, dict):
        blocks = {}

    counts = []
    for key, value in blocks.items():
        if isinstance(value, list):
            counts.append({"模块": key, "记录数": len(value)})
        elif isinstance(value, dict):
            counts.append({"模块": key, "记录数": len(value)})
        elif value:
            counts.append({"模块": key, "记录数": 1})
        else:
            counts.append({"模块": key, "记录数": 0})

    kline = blocks.get("kline_daily") or blocks.get("kline_minute") or []
    if not isinstance(kline, list):
        kline = []

    sections = [
        table("数据模块概览", counts, limit=60),
        table("实时行情", blocks.get("spot", []), limit=10),
        table("新闻公告", blocks.get("news", []), limit=20),
        table("基金持仓 / ETF 成分", blocks.get("fund_hold", []), limit=30),
        table("融资融券", blocks.get("margin", []), limit=10),
        table("最近行情记录", kline[-30:] if kline else [], limit=30),
    ]

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>股票数据查看 - {html.escape(source.name)}</title>
  <style>
    body {{ margin: 0; background: #101318; color: #eef2f6; font-family: "Microsoft YaHei", Arial, sans-serif; }}
    main {{ width: min(1180px, calc(100% - 32px)); margin: 0 auto; padding: 28px 0 46px; }}
    header {{ border-bottom: 1px solid #303947; padding-bottom: 18px; margin-bottom: 20px; }}
    h1 {{ margin: 0; font-size: 28px; }}
    h2 {{ margin: 0 0 12px; font-size: 18px; }}
    p {{ margin: 8px 0 0; }}
    section {{ background: #181d24; border: 1px solid #303947; border-radius: 8px; padding: 18px; margin-top: 14px; }}
    .muted {{ color: #aab3bf; }}
    .metrics {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 18px; }}
    .metrics div {{ background: #202631; border: 1px solid #303947; border-radius: 8px; padding: 14px; }}
    .metrics b {{ display: block; color: #d7aa55; font-size: 22px; overflow-wrap: anywhere; }}
    .metrics span {{ display: block; color: #aab3bf; font-size: 13px; margin-top: 4px; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid #303947; padding: 9px 10px; text-align: left; vertical-align: top; }}
    th {{ color: #d7aa55; white-space: nowrap; }}
    td {{ color: #eef2f6; max-width: 360px; }}
    @media (max-width: 760px) {{ .metrics {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>股票数据查看</h1>
      <p class="muted">来源文件：{html.escape(str(source))}</p>
      {latest_price_block(kline)}
    </header>
    {''.join(sections)}
  </main>
</body>
</html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a readable HTML summary from stock JSON data.")
    parser.add_argument("json_file")
    parser.add_argument("--output")
    args = parser.parse_args()

    source = Path(args.json_file)
    data = json.loads(source.read_text(encoding="utf-8"))
    output = Path(args.output) if args.output else source.with_name(source.stem.replace("data_", "summary_") + ".html")
    output.write_text(render_html(data, source), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
