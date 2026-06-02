"""
Generate a full stock research HTML report from collected JSON data.

Usage:
  python generate_stock_report.py output/data_600519.json --name 贵州茅台
  python generate_stock_report.py output/data_600519.json --analysis output/deepseek_600519.md
  python generate_stock_report.py output/data_600519.json --auto-deepseek
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"


def blocks_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    blocks = payload.get("blocks", payload)
    return blocks if isinstance(blocks, dict) else {}


def to_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def compact(value: Any, fallback: str = "-") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def first_value(row: dict[str, Any], aliases: list[str], fallback: Any = None) -> Any:
    if not isinstance(row, dict):
        return fallback
    lowered = {str(k).lower(): k for k in row.keys()}
    for alias in aliases:
        if alias in row and row[alias] not in (None, ""):
            return row[alias]
        key = lowered.get(alias.lower())
        if key is not None and row[key] not in (None, ""):
            return row[key]
    for key, value in row.items():
        key_text = str(key).lower()
        if value in (None, ""):
            continue
        if any(alias.lower() in key_text for alias in aliases):
            return value
    return fallback


def first_table_row(blocks: dict[str, Any], name: str) -> dict[str, Any]:
    rows = blocks.get(name)
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0]
    return {}


def detect_stock_name(blocks: dict[str, Any], code: str, explicit: str | None = None) -> str:
    if explicit:
        return explicit
    for block_name in ("spot", "basic_info"):
        for row in blocks.get(block_name, []) if isinstance(blocks.get(block_name), list) else []:
            if not isinstance(row, dict):
                continue
            value = first_value(row, ["股票简称", "证券简称", "名称", "简称", "name"])
            if value and str(value).strip() and code not in str(value):
                return str(value).strip()
    return f"{code} 个股"


def build_raw_data(blocks: dict[str, Any], limit: int = 180) -> list[list[Any]]:
    rows = blocks.get("kline_daily") or blocks.get("kline_minute") or []
    if not isinstance(rows, list):
        return []

    raw: list[list[Any]] = []
    for row in rows[-limit:]:
        if not isinstance(row, dict):
            continue
        date_value = first_value(row, ["day", "date", "日期", "时间"], "")
        date_text = compact(date_value, "")
        if "T" in date_text:
            date_text = date_text.split("T", 1)[0]
        if " " in date_text:
            date_text = date_text.split(" ", 1)[0]
        open_ = to_float(first_value(row, ["open", "开盘"]))
        high = to_float(first_value(row, ["high", "最高"]))
        low = to_float(first_value(row, ["low", "最低"]))
        close = to_float(first_value(row, ["close", "收盘", "最新价"]))
        volume = to_float(first_value(row, ["volume", "vol", "成交量"]))
        if date_text and any((open_, high, low, close)):
            raw.append([date_text, open_, high, low, close, volume])
    return raw


def build_pie_data(blocks: dict[str, Any]) -> list[dict[str, Any]]:
    rows = blocks.get("zygc") or []
    if not isinstance(rows, list):
        return [{"name": "主营业务", "value": 100}]

    data: list[dict[str, Any]] = []
    for index, row in enumerate(rows[:5], start=1):
        if not isinstance(row, dict):
            continue
        name = first_value(row, ["项目", "产品", "业务", "分类", "名称"], f"业务{index}")
        value = first_value(row, ["营业收入", "收入", "主营收入", "value"], None)
        ratio = first_value(row, ["占比", "比例", "收入比例"], None)
        numeric = to_float(value, 0.0)
        if numeric <= 0 and ratio is not None:
            numeric = to_float(ratio, 0.0)
            if 0 < numeric <= 1:
                numeric *= 100
        if numeric > 0:
            data.append({"name": compact(name, f"业务{index}")[:24], "value": round(numeric, 2)})
    return data or [{"name": "主营业务", "value": 100}]


def latest_quote(blocks: dict[str, Any], raw_data: list[list[Any]]) -> dict[str, Any]:
    spot = first_table_row(blocks, "spot")
    latest = raw_data[-1] if raw_data else ["-", 0, 0, 0, 0, 0]
    prev = raw_data[-2] if len(raw_data) > 1 else latest
    close = to_float(first_value(spot, ["最新价", "close", "收盘"], latest[4]))
    previous = to_float(prev[4])
    change = ((close - previous) / previous * 100) if previous else 0.0
    return {
        "price": close,
        "change": change,
        "date": latest[0],
        "high": to_float(first_value(spot, ["最高", "high"], latest[2])),
        "low": to_float(first_value(spot, ["最低", "low"], latest[3])),
        "volume": to_float(first_value(spot, ["成交量", "volume"], latest[5])),
    }


def markdown_to_html(markdown: str) -> str:
    lines = markdown.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    in_list = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for raw in lines:
        line = raw.strip()
        if not line:
            close_list()
            continue
        if line.startswith("### "):
            close_list()
            out.append(f"<h4>{html.escape(line[4:])}</h4>")
        elif line.startswith("## "):
            close_list()
            out.append(f"<h3>{html.escape(line[3:])}</h3>")
        elif line.startswith("# "):
            close_list()
            out.append(f"<h2>{html.escape(line[2:])}</h2>")
        elif line.startswith(("- ", "* ")):
            if not in_list:
                out.append("<ul class=\"alert-list\">")
                in_list = True
            out.append(f"<li>{html.escape(line[2:])}</li>")
        else:
            close_list()
            out.append(f"<p>{html.escape(line)}</p>")
    close_list()
    return "\n".join(out)


def parse_structured_analysis(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    stripped = text.strip()
    candidates = [stripped]
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, flags=re.DOTALL | re.IGNORECASE)
    if fence_match:
        candidates.insert(0, fence_match.group(1))
    object_match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    if object_match:
        candidates.append(object_match.group(0))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            repaired = re.sub(r",\s*([}\]])", r"\1", candidate)
            if repaired == candidate:
                continue
            try:
                parsed = json.loads(repaired)
            except json.JSONDecodeError:
                continue
        if isinstance(parsed, dict):
            steps = parsed.get("steps")
            if isinstance(steps, dict):
                return parsed
    return None


def step_data(structured: dict[str, Any] | None, key: str) -> dict[str, Any]:
    if not structured:
        return {}
    steps = structured.get("steps")
    if not isinstance(steps, dict):
        return {}
    value = steps.get(key)
    return value if isinstance(value, dict) else {}


def text_value(data: dict[str, Any], key: str, fallback: str = "") -> str:
    value = data.get(key)
    if isinstance(value, (list, dict)):
        return fallback
    return compact(value, fallback)


def list_value(data: dict[str, Any], key: str, fallback: list[str]) -> list[str]:
    value = data.get(key)
    if isinstance(value, list):
        items = [compact(item, "") for item in value if compact(item, "")]
        return items or fallback
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return fallback


def render_bullets(items: list[str]) -> str:
    return '<ul class="alert-list">' + "".join(f"<li>{html.escape(item)}</li>" for item in items) + "</ul>"


def render_table(rows: Any, title: str, limit: int = 8) -> str:
    if not isinstance(rows, list) or not rows:
        return f"<p class=\"muted\">暂无{html.escape(title)}数据。</p>"
    dict_rows = [row for row in rows[:limit] if isinstance(row, dict)]
    if not dict_rows:
        return f"<p class=\"muted\">暂无{html.escape(title)}数据。</p>"
    columns: list[str] = []
    for row in dict_rows:
        for key in row.keys():
            if key not in columns:
                columns.append(str(key))
            if len(columns) >= 5:
                break
        if len(columns) >= 5:
            break
    head = "".join(f"<th>{html.escape(col)}</th>" for col in columns)
    body = []
    for row in dict_rows:
        cells = "".join(f"<td>{html.escape(compact(row.get(col), ''))}</td>" for col in columns)
        body.append(f"<tr>{cells}</tr>")
    return f"<table class=\"cons\"><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def score_bar(label: str, score: int, total: int = 100, warn: bool = False) -> str:
    width = max(0, min(100, round(score / total * 100 if total else 0)))
    color = "background:var(--orange-warn);" if warn else ""
    return (
        f'<div class="score-bar"><span class="score-label">{html.escape(label)}</span>'
        f'<div class="score-track"><div class="score-fill" style="width:{width}%;{color}"></div></div>'
        f'<span class="score-num">{score}/{total}</span></div>'
    )


def render_news_list(rows: Any, limit: int = 6) -> str:
    if not isinstance(rows, list) or not rows:
        return '<p class="muted">暂无新闻或公告数据，需人工补充近期催化。</p>'
    items: list[str] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        title = compact(first_value(row, ["新闻标题", "标题", "title"], "未命名事件"))
        date = compact(first_value(row, ["发布时间", "日期", "date", "time"], ""))
        items.append(
            '<div class="news-item"><span class="bullet">•</span>'
            f'<span class="news-date">{html.escape(date[:10])}</span>'
            f'<span>{html.escape(title)}</span></div>'
        )
    return f'<div class="news-list">{"".join(items)}</div>' if items else '<p class="muted">暂无新闻或公告数据。</p>'


def classify_news_sentiment(title: str) -> tuple[str, str, str]:
    text = title.lower()
    negative_words = ["流出", "减持", "亏损", "下滑", "跌", "撤离", "不及预期", "风险", "处罚"]
    positive_words = ["增长", "中标", "订单", "盈利", "扭亏", "涨停", "突破", "回暖", "利好"]
    if any(word in text for word in negative_words):
        return ("利空", "var(--green-down)", "rgba(40,199,91,0.15)")
    if any(word in text for word in positive_words):
        return ("利好", "var(--red-up)", "rgba(245,86,86,0.15)")
    return ("中性", "var(--gold)", "rgba(212,168,83,0.15)")


def render_news_cards(rows: Any, limit: int = 8) -> str:
    if not isinstance(rows, list) or not rows:
        return '<p class="muted">暂无近期动态，需人工补充新闻、公告和政策催化。</p>'

    items: list[str] = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            continue
        title = compact(first_value(row, ["新闻标题", "标题", "title"], "未命名事件"))
        date = compact(first_value(row, ["发布时间", "日期", "date", "time"], ""))[:10]
        label, color, bg = classify_news_sentiment(title)
        items.append(
            f'<div class="news-item" style="border-left:3px solid {color};">'
            f'<span class="news-text">{html.escape((date + " " + title).strip())}</span>'
            f'<span style="padding:2px 8px;background:{bg};color:{color};border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap;margin-left:12px;">{label}</span>'
            "</div>"
        )
    return f'<div class="news-list">{"".join(items)}</div>' if items else '<p class="muted">暂无近期动态。</p>'


def render_checklist(items: list[str]) -> str:
    return '<ul class="checklist">' + "".join(f"<li>{html.escape(item)}</li>" for item in items) + "</ul>"


def render_peer_rows(peers: Any, stock_name: str) -> str:
    if not isinstance(peers, list) or not peers:
        return f"""<tr><td>成长性</td><td>待 AI 填充</td><td>行业均值</td><td>收入增速是否领先</td></tr>
      <tr><td>盈利能力</td><td>待 AI 填充</td><td>行业均值</td><td>毛利率/净利率是否改善</td></tr>
      <tr><td>估值</td><td>待 AI 填充</td><td>可比公司</td><td>估值溢价是否合理</td></tr>"""

    rows: list[str] = []
    for peer in peers[:6]:
        if not isinstance(peer, dict):
            continue
        name = text_value(peer, "name", "可比公司")
        growth = text_value(peer, "growth", "-")
        profitability = text_value(peer, "profitability", "-")
        valuation = text_value(peer, "valuation", "-")
        note = text_value(peer, "note", "待验证")
        rows.append(
            "<tr>"
            f"<td>{html.escape(name)}</td>"
            f"<td>{html.escape(growth)}</td>"
            f"<td>{html.escape(profitability)}</td>"
            f"<td>{html.escape(valuation)} / {html.escape(note)}</td>"
            "</tr>"
        )
    return "".join(rows) or render_peer_rows([], stock_name)


def render_technical_scores(technical: dict[str, Any]) -> str:
    trend = int(to_float(technical.get("trend"), 60))
    indicator = int(to_float(technical.get("indicator"), 60))
    pattern = int(to_float(technical.get("pattern"), 60))
    volume_price = int(to_float(technical.get("volume_price"), 55))
    fund_flow = int(to_float(technical.get("fund_flow"), 55))
    judgment = text_value(technical, "judgment", "技术面等待更多数据确认")
    return f"""
    <div class="rating-callout" style="margin-bottom:16px;"><div class="badge">技</div><div class="body"><div class="title">{html.escape(judgment)}</div><div class="desc">技术评分由 DeepSeek 结合 K 线、均线、指标和资金面信号生成。</div></div></div>
    {score_bar("多周期趋势", trend)}{score_bar("技术指标", indicator)}{score_bar("形态完整度", pattern)}{score_bar("量价配合", volume_price, warn=volume_price < 60)}{score_bar("资金面", fund_flow, warn=fund_flow < 60)}
"""


def render_elasticity_tree(step4: dict[str, Any]) -> str:
    drivers = step4.get("drivers")
    if not isinstance(drivers, list) or not drivers:
        drivers = [
            {"name": "核心业务", "ratio": "主营占比最高", "margin": "毛利率待验证", "factor": "收入弹性"},
            {"name": "次要业务", "ratio": "第二增长曲线", "margin": "费用摊薄", "factor": "规模效应"},
            {"name": "其他业务", "ratio": "补充贡献", "margin": "现金流", "factor": "估值修复"},
        ]
    cards: list[str] = []
    for index, driver in enumerate(drivers[:3]):
        if not isinstance(driver, dict):
            continue
        color = "var(--red-up)" if index == 0 else ("var(--gold)" if index == 1 else "var(--text-muted)")
        cards.append(
            f'<div style="flex:{2 if index == 0 else 1};background:var(--card-bg-alt);border:1px solid var(--border);border-left:4px solid {color};border-radius:8px;padding:12px;">'
            f'<strong style="color:{color};">{html.escape(text_value(driver, "name", f"弹性因子{index + 1}"))}</strong>'
            f'<div class="muted">营收占比：{html.escape(text_value(driver, "ratio", "待补充"))}</div>'
            f'<div class="muted">毛利率：{html.escape(text_value(driver, "margin", "待补充"))}</div>'
            f'<div class="muted">弹性因子：{html.escape(text_value(driver, "factor", "待验证"))}</div>'
            "</div>"
        )
    return (
        '<div style="margin:16px 0;">'
        '<div style="max-width:360px;margin:0 auto;background:linear-gradient(135deg,#1e1a10,#241f14);border:2px solid var(--gold);border-radius:10px;padding:12px;text-align:center;">'
        '<strong style="color:var(--gold-light);">业绩弹性树</strong><div class="muted">收入增长 x 毛利率修复 x 费用摊薄</div></div>'
        '<div style="width:2px;height:10px;background:var(--gold);margin:0 auto;"></div>'
        '<div style="border-top:2px solid var(--gold);margin:0 12%;"></div>'
        f'<div style="display:flex;gap:12px;margin-top:10px;align-items:stretch;">{"".join(cards)}</div>'
        "</div>"
    )


def render_formula_cards(step4: dict[str, Any], step6: dict[str, Any]) -> str:
    formulas = step4.get("formulas")
    if not isinstance(formulas, list) or not formulas:
        formulas = [
            {"label": "目标利润", "formula": "收入 x 毛利率 - 费用", "result": "等待财务验证"},
            {"label": "盈亏比", "formula": "(目标价 - 现价) / (现价 - 止损)", "result": text_value(step6, "profit_loss_ratio", "待补充")},
        ]
    cards: list[str] = []
    for formula in formulas[:4]:
        if not isinstance(formula, dict):
            continue
        cards.append(
            '<div style="background:var(--card-bg-alt);border:1px solid var(--border);border-radius:8px;padding:12px;">'
            f'<strong style="color:var(--gold);">公式 · {html.escape(text_value(formula, "label", "测算"))}</strong>'
            f'<div style="font-family:var(--font-mono);font-size:12px;color:var(--text-secondary);margin-top:6px;">{html.escape(text_value(formula, "formula", "待补充"))}</div>'
            f'<div style="color:var(--red-up);font-weight:700;margin-top:6px;">{html.escape(text_value(formula, "result", "待验证"))}</div>'
            "</div>"
        )
    return f'<div class="grid-2" style="margin-top:14px;">{"".join(cards)}</div>'


def render_catalyst_table(step8: dict[str, Any], tracking_items: list[str]) -> str:
    catalysts = step8.get("catalysts")
    if not isinstance(catalysts, list) or not catalysts:
        catalysts = [{"name": item, "impact": "影响研究结论", "status": "持续观察", "note": "等待公开数据验证"} for item in tracking_items[:6]]
    rows: list[str] = []
    for item in catalysts[:8]:
        if not isinstance(item, dict):
            continue
        status = text_value(item, "status", "持续观察")
        status_color = "var(--red-up)" if "已兑现" in status else ("var(--gold)" if "待" in status else "var(--text-muted)")
        rows.append(
            "<tr>"
            f"<td>{html.escape(text_value(item, 'name', '催化剂'))}</td>"
            f"<td>{html.escape(text_value(item, 'impact', '待评估'))}</td>"
            f"<td style=\"color:{status_color};font-weight:700;\">{html.escape(status)}</td>"
            f"<td>{html.escape(text_value(item, 'note', '持续跟踪'))}</td>"
            "</tr>"
        )
    return (
        '<h3 style="font-size:15px;color:var(--gold-light);margin:16px 0 8px;">催化剂兑现追踪</h3>'
        '<table class="cons"><thead><tr><th>跟踪指标/催化剂</th><th>预期影响</th><th>兑现状态</th><th>备注</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def render_event_log(step8: dict[str, Any]) -> str:
    events = list_value(step8, "events", ["首次覆盖：生成基础跟踪清单，等待后续数据更新。"])
    return (
        '<div style="border-left:4px solid var(--gold);background:var(--card-bg-alt);border-radius:8px;padding:12px 14px;margin-top:12px;">'
        '<p style="font-weight:700;color:var(--gold);margin-bottom:6px;">📋 事件记录</p>'
        + "".join(f'<p class="muted" style="margin:4px 0;">{html.escape(event)}</p>' for event in events[:6])
        + "</div>"
    )


def render_research_skeleton(
    blocks: dict[str, Any],
    stock_name: str,
    analysis_html: str,
    structured: dict[str, Any] | None = None,
) -> str:
    news = blocks.get("news") or blocks.get("notice")
    step0 = step_data(structured, "step0")
    step1 = step_data(structured, "step1")
    step2 = step_data(structured, "step2")
    step3 = step_data(structured, "step3")
    step4 = step_data(structured, "step4")
    step5 = step_data(structured, "step5")
    step6 = step_data(structured, "step6")
    step7 = step_data(structured, "step7")
    step8 = step_data(structured, "step8")
    technical = step_data(structured, "technical")
    summary = text_value(structured or {}, "summary", "")
    tags = list_value(structured or {}, "tags", ["研究辅助", "非投资建议", "可持续更新"])
    mission_title = text_value(step0, "title", "潜在主线")
    mission_bullets = list_value(step0, "bullets", ["产业景气、订单兑现、估值修复或主题催化。"])
    macro_title = text_value(step1, "title", "核心矛盾待 AI 深化")
    chain_title = text_value(step2, "title", "产业链位置待 AI 深化")
    chain_text = text_value(step2, "text", "DeepSeek 分析应在这里补齐：公司处于产业链哪一环、议价权来自哪里、景气度如何传导到利润表。")
    quality_score = int(to_float(step3.get("score"), 60))
    quality_rating = text_value(step3, "rating", "B")
    quality_text = text_value(step3, "text", "当前评分为模板初值，最终评级应由 DeepSeek 基于财务、行业和估值数据重算。")
    bull = text_value(step4, "bull", "行业景气上行，收入与利润率同步改善，估值修复。")
    base = text_value(step4, "base", "经营稳步恢复，估值跟随业绩小幅波动。")
    bear = text_value(step4, "bear", "需求不及预期，现金流或毛利率承压。")
    risk_items = list_value(step5, "risks", ["财报收入或利润连续低于预期", "主营毛利率明显下滑", "重要股东或机构资金持续流出", "跌破关键均线且成交放大"])
    valuation_text = text_value(step6, "text", "结合 PE/PB、现金流和行业估值。")
    target_range = text_value(step6, "target_range", "待补充")
    buy_zone = text_value(step6, "buy_zone", "待补充")
    stop_loss = text_value(step6, "stop_loss", "待补充")
    valuation_pl = text_value(step6, "profit_loss_ratio", "待补充")
    compare_text = text_value(step7, "text", "由 DeepSeek 补充可比公司、成长性、盈利能力和估值差异。")
    peers = step7.get("peers")
    judgment = text_value(step8, "judgment", "等待 DeepSeek 终评")
    tracking_items = list_value(step8, "tracking", ["下一期财报收入、毛利率、经营现金流", "大额订单、政策催化或行业价格变化", "资金流连续性和融资融券余额", "K 线是否重新站稳 MA20 / MA60"])
    tag_html = "".join(f'<span class="tag">{html.escape(tag)}</span>' for tag in tags[:5])
    analysis_block = f'<div class="analysis-body">{analysis_html}</div>' if analysis_html.strip() else ""
    return f"""
  <div class="card" id="mission">
    <div class="card-header"><span class="icon">0</span><h2>Step 0 投资命题</h2><span class="sub">先定义研究问题</span></div>
    {f'<p class="muted">{html.escape(summary)}</p>' if summary else ''}
    <div class="verdict-tags">{tag_html}</div>
    <div class="grid-3">
      <div class="scenario"><strong>研究对象</strong><div class="prob">{html.escape(stock_name)}</div><div class="muted">聚焦主营、财务、股东、资金流和技术面。</div></div>
      <div class="scenario bull"><strong>{html.escape(mission_title)}</strong><div class="prob">DeepSeek 主线</div><div class="muted">{html.escape("；".join(mission_bullets))}</div></div>
      <div class="scenario bear"><strong>反证条件</strong><div class="prob">需持续跟踪</div><div class="muted">业绩不及预期、资金流转弱、关键均线破位。</div></div>
    </div>
  </div>

  <div class="card" id="macro">
    <div class="card-header"><span class="icon">1</span><h2>Step 1 主要矛盾与宏观环境</h2></div>
    <div class="grid-2">
      <div><p class="muted">这一章对应原作者示例中的“为什么现在看”。自动版先把近期新闻、公告和数据缺口摊开，避免直接编造行业结论。</p>{render_news_list(news)}</div>
      <div class="verdict-highlight"><div class="judgment">{html.escape(macro_title)}</div><div class="verdict-grid">
        <div class="verdict-item"><div class="v-val">景气</div><div class="v-label">行业周期</div></div>
        <div class="verdict-item"><div class="v-val">兑现</div><div class="v-label">业绩质量</div></div>
        <div class="verdict-item"><div class="v-val">资金</div><div class="v-label">交易拥挤度</div></div>
        <div class="verdict-item"><div class="v-val">估值</div><div class="v-label">安全边际</div></div>
      </div></div>
    </div>
  </div>

  <div class="card" id="chain">
    <div class="card-header"><span class="icon">2</span><h2>Step 2 产业链位置</h2></div>
    <div class="chain-svg">
      <svg viewBox="0 0 760 170" role="img" aria-label="产业链示意">
        <defs><marker id="arrow-auto" markerWidth="10" markerHeight="10" refX="9" refY="4" orient="auto"><polygon points="0 0,10 4,0 8" fill="#d4a853"/></marker></defs>
        <rect x="20" y="45" width="150" height="80" rx="8" fill="#242733" stroke="#d4a853"/><text x="95" y="78" text-anchor="middle" class="svg-hdr">上游资源</text><text x="95" y="102" text-anchor="middle" class="svg-sub">原材料 / 技术 / 资本</text>
        <line x1="175" y1="85" x2="275" y2="85" stroke="#d4a853" stroke-width="2" marker-end="url(#arrow-auto)"/>
        <rect x="285" y="35" width="180" height="100" rx="8" fill="#2c1a1a" stroke="#f55656"/><text x="375" y="78" text-anchor="middle" class="svg-hdr">{html.escape(stock_name[:12])}</text><text x="375" y="104" text-anchor="middle" class="svg-sub">主营与竞争壁垒</text>
        <line x1="470" y1="85" x2="570" y2="85" stroke="#d4a853" stroke-width="2" marker-end="url(#arrow-auto)"/>
        <rect x="580" y="45" width="150" height="80" rx="8" fill="#242733" stroke="#d4a853"/><text x="655" y="78" text-anchor="middle" class="svg-hdr">下游需求</text><text x="655" y="102" text-anchor="middle" class="svg-sub">客户 / 场景 / 政策</text>
      </svg>
    </div>
    <div class="rating-callout" style="margin-top:12px;"><div class="badge">链</div><div class="body"><div class="title">{html.escape(chain_title)}</div><div class="desc">{html.escape(chain_text)}</div></div></div>
  </div>

  <div class="card" id="quality">
    <div class="card-header"><span class="icon">3</span><h2>Step 3 公司质地评分</h2></div>
    {score_bar("行业空间", min(100, quality_score + 10))}{score_bar("竞争壁垒", min(100, quality_score + 4))}{score_bar("成长性", quality_score)}{score_bar("盈利能力", max(0, quality_score - 8), warn=True)}{score_bar("治理结构", max(0, quality_score - 2))}{score_bar("估值性价比", max(0, quality_score - 12), warn=True)}
    <div class="rating-callout"><div class="badge">{html.escape(quality_rating[:2])}</div><div class="body"><div class="title">DeepSeek 初评：{html.escape(quality_rating)}</div><div class="desc">{html.escape(quality_text)}</div></div></div>
  </div>

  <div class="card" id="elasticity">
    <div class="card-header"><span class="icon">4</span><h2>Step 4 弹性空间</h2></div>
    {render_elasticity_tree(step4)}
    {render_formula_cards(step4, step6)}
    <div class="grid-3">
      <div class="scenario bull"><strong>乐观情景</strong><div class="prob">概率 25%</div><div class="muted">{html.escape(bull)}</div></div>
      <div class="scenario"><strong>基准情景</strong><div class="prob">概率 50%</div><div class="muted">{html.escape(base)}</div></div>
      <div class="scenario bear"><strong>悲观情景</strong><div class="prob">概率 25%</div><div class="muted">{html.escape(bear)}</div></div>
    </div>
  </div>

  <div class="card" id="risk">
    <div class="card-header"><span class="icon">5</span><h2>Step 5 风险与止损信号</h2></div>
    <div class="grid-2">
      {render_checklist(risk_items)}
      <ul class="alert-list"><li>数据接口为空时，不用想象补齐结论。</li><li>AI 结论必须能被财务、行情或公开事件反证。</li><li>本工具不输出确定性买卖建议。</li></ul>
    </div>
  </div>

  <div class="card" id="valuation">
    <div class="card-header"><span class="icon">6</span><h2>Step 6 估值与赔率</h2></div>
    <div class="grid-3">
      <div class="scenario"><strong>安全边际</strong><div class="prob">DeepSeek</div><div class="muted">{html.escape(valuation_text)}</div></div>
      <div class="scenario"><strong>目标区间</strong><div class="prob">{html.escape(target_range)}</div><div class="muted">买入区间：{html.escape(buy_zone)}</div></div>
      <div class="scenario"><strong>盈亏比</strong><div class="prob">{html.escape(valuation_pl)}</div><div class="muted">止损位：{html.escape(stop_loss)}</div></div>
    </div>
  </div>

  <div class="card" id="compare">
    <div class="card-header"><span class="icon">7</span><h2>Step 7 同业比较</h2></div>
    <p class="muted">{html.escape(compare_text)}</p>
    <table class="cons"><thead><tr><th>可比对象/维度</th><th>成长性</th><th>盈利能力</th><th>估值与备注</th></tr></thead><tbody>
      {render_peer_rows(peers, stock_name)}
    </tbody></table>
  </div>

  <div class="card" id="tracking">
    <div class="card-header"><span class="icon">8</span><h2>Step 8 跟踪清单与综合研判</h2></div>
    <div class="grid-2">
      <div>{render_checklist(tracking_items)}</div>
      <div>
        <div class="verdict-highlight"><div class="judgment">{html.escape(judgment)}</div><div class="verdict-grid">
          <div class="verdict-item"><div class="v-val">60</div><div class="v-label">基本面</div></div>
          <div class="verdict-item"><div class="v-val">55</div><div class="v-label">资金面</div></div>
          <div class="verdict-item"><div class="v-val">60</div><div class="v-label">技术面</div></div>
          <div class="verdict-item"><div class="v-val">B</div><div class="v-label">综合</div></div>
        </div></div>
        {score_bar("基本面 30%", 60)}{score_bar("资金面 20%", 55, warn=True)}{score_bar("技术面 20%", 60)}{score_bar("事件催化 15%", 58, warn=True)}{score_bar("估值赔率 15%", 56, warn=True)}
      </div>
    </div>
    {render_catalyst_table(step8, tracking_items)}
    {render_event_log(step8)}
    {analysis_block}
  </div>

  <div class="card" id="technical-score">
    <div class="card-header"><span class="icon">技</span><h2>技术面评分</h2><span class="sub">结构化 AI 研判</span></div>
    {render_technical_scores(technical)}
  </div>
"""


def build_default_analysis(blocks: dict[str, Any], stock_name: str) -> str:
    news_rows = blocks.get("news") if isinstance(blocks.get("news"), list) else []
    news_hint = "；".join(compact(first_value(row, ["新闻标题", "标题", "title"], "")) for row in news_rows[:3] if isinstance(row, dict))
    return f"""# 核心结论

- {stock_name} 的完整研报已基于本地采集数据生成；如配置 DEEPSEEK_API_KEY，可自动补充更细的 Step 0-8 深度分析。
- 当前页面重点保留行情、业务结构、财务/股东/新闻摘要和技术图表，便于先做日常复盘。
- 后续判断应继续跟踪业绩兑现、行业景气度、资金流变化和关键技术位。

# 近期催化与风险

- 近期信息：{news_hint or "暂无可用新闻摘要"}。
- 主要风险：公开数据接口可能缺项或延迟，AI 文字仅用于研究辅助，不构成投资建议。
"""


def build_deepseek_prompt(stock_name: str, code: str) -> str:
    return f"""请基于随附个股数据，为 {stock_name}（{code}）输出一份中文个股深度分析。

只返回严格 JSON，不要 Markdown，不要代码块，不要解释。字段结构如下：
{{
  "summary": "一句话核心结论",
  "tags": ["标签1", "标签2", "标签3"],
  "target_price": "例如 18-22元；没有依据则写 待评估",
  "profit_loss_ratio": "例如 2.1x；没有依据则写 待评估",
  "risk_level": "低/中/高",
  "suggested_position": "例如 30%-50%；没有依据则写 观察",
  "quality_score": 0,
  "steps": {{
    "step0": {{"title": "投资命题", "bullets": ["要点1", "要点2"]}},
    "step1": {{"title": "主要矛盾", "text": "为什么现在看"}},
    "step2": {{"title": "产业链位置", "text": "位置、议价权、景气传导"}},
    "step3": {{"score": 0, "rating": "A/B/C 等", "text": "公司质地判断"}},
    "step4": {{"bull": "乐观情景", "base": "基准情景", "bear": "悲观情景", "drivers": [{{"name": "业务线", "ratio": "营收占比", "margin": "毛利率", "factor": "弹性因子"}}], "formulas": [{{"label": "公式名", "formula": "计算公式", "result": "测算结果"}}]}},
    "step5": {{"risks": ["风险1", "风险2", "风险3"]}},
    "step6": {{"text": "估值与赔率判断", "target_range": "目标区间", "buy_zone": "买入区间", "stop_loss": "止损位", "profit_loss_ratio": "盈亏比"}},
    "step7": {{"text": "同业比较结论", "peers": [{{"name": "可比公司", "growth": "成长性", "profitability": "盈利能力", "valuation": "估值", "note": "备注"}}]}},
    "step8": {{"judgment": "综合研判", "tracking": ["跟踪项1", "跟踪项2"], "catalysts": [{{"name": "催化剂", "impact": "预期影响", "status": "待兑现/已兑现/持续观察", "note": "备注"}}], "events": ["事件记录1", "事件记录2"]}},
    "technical": {{"trend": 0, "indicator": 0, "pattern": 0, "volume_price": 0, "fund_flow": 0, "judgment": "技术面判断"}}
  }}
}}

要求：
1. 观点要具体，尽量引用数据中的财务、主营、股东、资金流、新闻和技术信号。
2. 对缺失数据要明确写“数据缺失/需人工补充”，不要编造。
3. 数字评分必须是 0-100 的整数。
4. 仅作研究辅助，不构成投资建议。
"""


def render_report(payload: dict[str, Any], code: str, stock_name: str, analysis_markdown: str | None = None) -> str:
    blocks = blocks_from_payload(payload)
    raw_data = build_raw_data(blocks)
    if not raw_data:
        today = dt.date.today().isoformat()
        raw_data = [[today, 0, 0, 0, 0, 0]]
    quote = latest_quote(blocks, raw_data)
    pie_data = build_pie_data(blocks)
    structured_analysis = parse_structured_analysis(analysis_markdown)
    if structured_analysis:
        analysis_html = ""
    else:
        analysis_html = markdown_to_html(analysis_markdown or build_default_analysis(blocks, stock_name))
    target_price = text_value(structured_analysis or {}, "target_price", "待评估")
    profit_loss_ratio = text_value(structured_analysis or {}, "profit_loss_ratio", "待评估")
    risk_level = text_value(structured_analysis or {}, "risk_level", "中")
    suggested_position = text_value(structured_analysis or {}, "suggested_position", "观察")
    top_summary = text_value(structured_analysis or {}, "summary", "本报告由本地采集数据、DeepSeek 结构化分析和可视化 HTML 模板合成。若部分接口为空，页面会保留缺失提示，避免用不可靠内容填充。")
    top_tags = list_value(structured_analysis or {}, "tags", ["普通个股模板", "DeepSeek 分析", "本地数据"])

    css = (ROOT / "shared" / "template_base.css").read_text(encoding="utf-8")
    js = (ROOT / "shared" / "template_base.js").read_text(encoding="utf-8")
    js = js.replace("__RAW_DATA_ARRAY__", json.dumps(raw_data, ensure_ascii=False))
    js = js.replace("__PIE_DATA_ARRAY__", json.dumps(pie_data, ensure_ascii=False))
    close = quote["price"]
    js = js.replace("__MARKLINE_DATA__", json.dumps([{"name": "现价", "yAxis": close}], ensure_ascii=False))
    js = js.replace("__MARKPOINT_DATA__", json.dumps([{"name": "现价", "coord": [raw_data[-1][0], close], "value": "现价"}], ensure_ascii=False))

    change_class = "val-up" if quote["change"] >= 0 else "val-down"
    generated_at = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    generated_date = generated_at[:10]
    module_counts = [{"模块": key, "记录数": len(value) if isinstance(value, (list, dict)) else int(bool(value))}
                     for key, value in blocks.items()]

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>个股研究-{html.escape(stock_name)}</title>
  <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
  <script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
  <style>{css}
  .muted{{color:var(--text-muted)}}
  .analysis-body h2,.analysis-body h3,.analysis-body h4{{margin:16px 0 8px;color:var(--gold-light)}}
  .analysis-body p{{margin:8px 0;color:var(--text-secondary)}}
  .analysis-body ul{{margin:8px 0 12px}}
  </style>
</head>
<body>
<nav class="top-nav">
  <div class="logo"><div class="logo-icon">研</div><div><div class="stock-name">{html.escape(stock_name)}</div><div class="stock-code">{html.escape(code)}</div></div></div>
  <div class="nav-links">
    <a href="#hero" class="active">行情</a><a href="#conclusion-top">结论</a><a href="#profile">画像</a><a href="#kline-section">K线</a><a href="#mission">任务</a><a href="#macro">宏观</a><a href="#chain">产业链</a><a href="#quality">质量</a><a href="#elasticity">弹性</a><a href="#risk">风险</a><a href="#valuation">估值</a><a href="#compare">对标</a><a href="#tracking">跟踪</a><a href="#technical">技术面</a>
  </div>
  <span class="nav-analysis-date">{generated_at}</span>
  <button class="theme-toggle" id="themeToggle">浅色模式</button>
</nav>
<div class="container">
  <div class="hero" id="hero">
    <div class="hero-price-block"><span class="hero-price">{quote["price"]:.2f}</span><span class="hero-change {change_class}">{quote["change"]:+.2f}%</span></div>
    <div class="hero-meta">
      <div class="hero-meta-item"><div class="val">{html.escape(compact(quote["date"]))}</div><div class="label">最新交易日</div></div>
      <div class="hero-meta-item"><div class="val">{html.escape(target_price)}</div><div class="label">中期目标价</div></div>
      <div class="hero-meta-item"><div class="val">{html.escape(profit_loss_ratio)}</div><div class="label">盈亏比</div></div>
      <div class="hero-meta-item"><div class="val">{html.escape(suggested_position)}</div><div class="label">建议仓位</div></div>
      <div class="hero-meta-item"><div class="val" style="color:var(--orange-warn);">{html.escape(risk_level)}</div><div class="label">风险等级</div></div>
    </div>
    <div class="hero-tags">{"".join(f'<span class="hero-tag">{html.escape(tag)}</span>' for tag in top_tags[:6])}</div>
  </div>

  <div class="conclusion-top" id="conclusion-top">
    <div class="big-verdict">{html.escape(top_summary)}</div>
    <div class="verdict-detail">交易参数：目标价 {html.escape(target_price)}，盈亏比 {html.escape(profit_loss_ratio)}，仓位 {html.escape(suggested_position)}，风险 {html.escape(risk_level)}。本页面仅作研究辅助，不构成投资建议。</div>
    <div class="verdict-tags">{"".join(f'<span class="tag">{html.escape(tag)}</span>' for tag in top_tags[:5])}</div>
  </div>

  <div class="grid-2" id="profile">
    <div class="card">
      <div class="card-header"><span class="icon">数</span><h2>数据模块概览</h2></div>
      {render_table(module_counts, "数据模块", 16)}
    </div>
    <div class="card">
      <div class="card-header"><span class="icon">业</span><h2>主营业务结构</h2></div>
      <div id="chart-business-pie" style="width:100%;height:280px;"></div>
    </div>
  </div>

  <div class="card" id="kline-section">
    <div class="card-header"><span class="icon">K</span><h2>K 线与均线</h2><span class="sub">自动注入最近行情</span></div>
    <div id="chart-kline-full" style="width:100%;height:480px;"></div>
    <div class="kpi-info-row">
      <div class="kpi-info-item"><div class="label">最新价</div><div class="value">{quote["price"]:.2f}</div></div>
      <div class="kpi-info-item"><div class="label">涨跌幅</div><div class="value">{quote["change"]:+.2f}%</div></div>
      <div class="kpi-info-item"><div class="label">最高</div><div class="value">{quote["high"]:.2f}</div></div>
      <div class="kpi-info-item"><div class="label">最低</div><div class="value">{quote["low"]:.2f}</div></div>
    </div>
  </div>

  <div class="grid-2">
    <div class="card">
      <div class="card-header"><span class="icon">财</span><h2>财务摘要</h2></div>
      {render_table(blocks.get("fin_abstract"), "财务摘要")}
    </div>
    <div class="card">
      <div class="card-header"><span class="icon">闻</span><h2>新闻与公告</h2></div>
      {render_news_cards(blocks.get("news") or blocks.get("notice"))}
    </div>
  </div>

  {render_research_skeleton(blocks, stock_name, analysis_html, structured_analysis)}

  <div class="card" id="technical">
    <div class="card-header"><span class="icon">技</span><h2>技术指标</h2><span class="sub">MACD / KDJ / RSI / BOLL</span></div>
    <div class="grid-2">
      <div id="chart-macd" style="height:280px;"></div>
      <div id="chart-kdj" style="height:280px;"></div>
      <div id="chart-rsi" style="height:260px;"></div>
      <div id="chart-boll" style="height:260px;"></div>
    </div>
  </div>

  <footer>
    <p>⚠️ 免责声明：本报告仅供研究参考，不构成投资建议。投资有风险，决策需谨慎。</p>
    <p>📅 分析基准日：{generated_date} · 数据截止：{html.escape(compact(quote["date"]))} · 研究状态：首次覆盖/自动生成</p>
    <p style="font-size:11px;color:var(--text-muted);">数据来源：akshare(雪球/新浪/同花顺/东方财富/巨潮资讯) · DeepSeek · stock-analysis · {generated_date} · @明立玩AI · 个股深度研究系统 v3.0</p>
    <p style="margin-top:6px;">作者：明立 · AI教育资深玩家 · AI应用落地近4年经验</p>
    <p>📮 联系作者获取更多skill：ll-mingli1221</p>
  </footer>
</div>
<script>{js}</script>
</body>
</html>"""


def maybe_generate_analysis(data_path: Path, code: str, stock_name: str, output_md: Path) -> str | None:
    from deepseek_client import build_stock_context, deepseek_chat, load_env_file

    load_env_file()
    if not os.getenv("DEEPSEEK_API_KEY"):
        return None
    prompt = build_deepseek_prompt(stock_name, code)
    context = build_stock_context(str(data_path), max_chars=18000)
    content = deepseek_chat(
        [
            {"role": "system", "content": "你是严谨的A股研究助理，只做研究框架、风险提示和数据解读，不构成投资建议。"},
            {"role": "user", "content": f"个股数据摘要：\n{context}\n\n任务：\n{prompt}"},
        ],
        max_tokens=6000,
        temperature=0.25,
    )
    output_md.write_text(content, encoding="utf-8")
    return content


def default_output_path(code: str, stock_name: str) -> Path:
    safe_name = re.sub(r'[\\/:*?"<>|]+', "-", stock_name).strip() or code
    return OUTPUT_DIR / f"个股研究-{safe_name}.html"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a full HTML stock research report.")
    parser.add_argument("json_file", help="Path to output/data_*.json")
    parser.add_argument("--analysis", help="Optional DeepSeek markdown file to render")
    parser.add_argument("--name", help="Stock name, if it cannot be detected from data")
    parser.add_argument("--code", help="Stock code, defaults to filename data_XXXXXX")
    parser.add_argument("--output", help="Output HTML path")
    parser.add_argument("--auto-deepseek", action="store_true", help="Call DeepSeek when DEEPSEEK_API_KEY is configured")
    args = parser.parse_args()

    data_path = Path(args.json_file)
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    code = args.code or data_path.stem.replace("data_", "")
    blocks = blocks_from_payload(payload)
    stock_name = detect_stock_name(blocks, code, args.name)

    analysis_text = None
    if args.analysis:
        analysis_text = Path(args.analysis).read_text(encoding="utf-8")
    elif args.auto_deepseek:
        OUTPUT_DIR.mkdir(exist_ok=True)
        timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M")
        analysis_path = OUTPUT_DIR / f"deepseek_{code}_{timestamp}.json"
        analysis_text = maybe_generate_analysis(data_path, code, stock_name, analysis_path)
        if analysis_text:
            print(f"[OK] DeepSeek markdown saved: {analysis_path}")

    output = Path(args.output) if args.output else default_output_path(code, stock_name)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_report(payload, code, stock_name, analysis_text), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
