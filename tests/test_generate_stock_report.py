import json
import tempfile
import unittest
from pathlib import Path

import generate_stock_report as g


class GenerateStockReportTests(unittest.TestCase):
    def test_build_raw_data_prefers_daily_kline_and_keeps_ohlc_order(self):
        blocks = {
            "kline_daily": [
                {"day": "2026-06-01T00:00:00.000", "open": "10", "high": "12", "low": "9", "close": "11", "volume": "1000"},
                {"date": "2026-06-02", "open": 11, "high": 13, "low": 10, "close": 12, "volume": 2000},
            ],
            "kline_minute": [
                {"day": "2026-06-02 09:31:00", "open": "1", "high": "1", "low": "1", "close": "1", "volume": "1"}
            ],
        }

        raw = g.build_raw_data(blocks)

        self.assertEqual(raw, [["2026-06-01", 10.0, 12.0, 9.0, 11.0, 1000.0], ["2026-06-02", 11.0, 13.0, 10.0, 12.0, 2000.0]])

    def test_markdown_to_html_supports_headings_lists_and_paragraphs(self):
        html = g.markdown_to_html("# 核心结论\n\n- 需求改善\n- 估值偏高\n\n需要跟踪订单。")

        self.assertIn("<h2>核心结论</h2>", html)
        self.assertIn("<li>需求改善</li>", html)
        self.assertIn("<p>需要跟踪订单。</p>", html)

    def test_render_report_injects_chart_placeholders_and_report_sections(self):
        payload = {
            "blocks": {
                "spot": [{"股票简称": "测试股份", "最新价": 12.3}],
                "kline_daily": [{"day": "2026-06-02", "open": 10, "high": 13, "low": 9, "close": 12, "volume": 1000}],
                "zygc": [{"项目": "主营业务", "营业收入": 100, "占比": 0.6}],
                "news": [{"新闻标题": "订单增长", "发布时间": "2026-06-02"}],
            }
        }

        report = g.render_report(payload, "000001", "测试股份", "# 投资主线\n\n- 国产替代")

        self.assertIn("测试股份", report)
        self.assertIn("chart-kline-full", report)
        self.assertIn("const rawData = [[\"2026-06-02\", 10.0, 13.0, 9.0, 12.0, 1000.0]]", report)
        self.assertIn("<h2>投资主线</h2>", report)
        self.assertNotIn("__RAW_DATA_ARRAY__", report)

    def test_render_report_matches_example_section_skeleton(self):
        payload = {
            "blocks": {
                "spot": [{"股票简称": "测试股份", "最新价": 12.3}],
                "kline_daily": [{"day": "2026-06-02", "open": 10, "high": 13, "low": 9, "close": 12, "volume": 1000}],
                "zygc": [{"项目": "核心产品", "营业收入": 100}],
            }
        }

        report = g.render_report(payload, "000001", "测试股份", "# 核心结论\n\n- 国产替代")

        for section_id in [
            "hero",
            "conclusion-top",
            "profile",
            "kline-section",
            "mission",
            "macro",
            "chain",
            "quality",
            "elasticity",
            "risk",
            "valuation",
            "compare",
            "tracking",
            "technical",
        ]:
            self.assertIn(f'href="#{section_id}"', report)
            self.assertIn(f'id="{section_id}"', report)

        self.assertGreaterEqual(report.count('class="score-bar"'), 10)
        self.assertGreaterEqual(report.count('class="scenario'), 3)
        self.assertIn('class="chain-svg"', report)
        self.assertIn('class="checklist"', report)
        self.assertIn('class="verdict-highlight"', report)
        self.assertIn('class="rating-callout"', report)

    def test_parse_structured_analysis_accepts_json_inside_code_fence(self):
        text = """```json
{
  "summary": "国产替代主线明确，但估值需要业绩兑现支撑。",
  "tags": ["国产替代", "订单催化"],
  "steps": {
    "step0": {"title": "信创弹性", "bullets": ["党政订单回暖", "算力业务放量"]},
    "step3": {"score": 72, "rating": "B+", "text": "公司质地中等偏上。"}
  }
}
```"""

        parsed = g.parse_structured_analysis(text)

        self.assertEqual(parsed["summary"], "国产替代主线明确，但估值需要业绩兑现支撑。")
        self.assertEqual(parsed["steps"]["step0"]["title"], "信创弹性")
        self.assertEqual(parsed["steps"]["step3"]["score"], 72)

    def test_parse_structured_analysis_repairs_common_trailing_commas(self):
        text = """{
  "summary": "尾逗号也应被兼容",
  "steps": {
    "step0": {"title": "主线", "bullets": ["订单", "盈利",],},
  },
}"""

        parsed = g.parse_structured_analysis(text)

        self.assertEqual(parsed["summary"], "尾逗号也应被兼容")
        self.assertEqual(parsed["steps"]["step0"]["bullets"], ["订单", "盈利"])

    def test_structured_analysis_fills_specific_report_cards(self):
        payload = {
            "blocks": {
                "spot": [{"股票简称": "测试股份", "最新价": 12.3}],
                "kline_daily": [{"day": "2026-06-02", "open": 10, "high": 13, "low": 9, "close": 12, "volume": 1000}],
                "zygc": [{"项目": "核心产品", "营业收入": 100}],
            }
        }
        analysis = json.dumps(
            {
                "summary": "国产替代主线明确，但估值需要业绩兑现支撑。",
                "tags": ["国产替代", "订单催化"],
                "steps": {
                    "step0": {"title": "信创订单弹性", "bullets": ["党政订单回暖", "算力业务放量"]},
                    "step2": {"title": "产业链中游整机与生态", "text": "公司处于国产算力生态中游。"},
                    "step4": {"bull": "订单集中释放", "base": "收入稳步修复", "bear": "招标推迟"},
                    "step8": {"judgment": "中性偏积极", "tracking": ["订单公告", "毛利率修复"]},
                },
            },
            ensure_ascii=False,
        )

        report = g.render_report(payload, "000001", "测试股份", analysis)

        self.assertIn("国产替代主线明确", report)
        self.assertIn("信创订单弹性", report)
        self.assertIn("党政订单回暖", report)
        self.assertIn("产业链中游整机与生态", report)
        self.assertIn("订单集中释放", report)
        self.assertIn("中性偏积极", report)
        self.assertNotIn("如配置 DEEPSEEK_API_KEY", report)

    def test_structured_analysis_fills_trading_valuation_compare_and_technical_widgets(self):
        payload = {
            "blocks": {
                "spot": [{"股票简称": "测试股份", "最新价": 12.3}],
                "kline_daily": [{"day": "2026-06-02", "open": 10, "high": 13, "low": 9, "close": 12, "volume": 1000}],
                "zygc": [{"项目": "核心产品", "营业收入": 100}],
            }
        }
        analysis = json.dumps(
            {
                "summary": "等待回调后胜率更好。",
                "target_price": "18-22元",
                "profit_loss_ratio": "2.1x",
                "risk_level": "中",
                "suggested_position": "30%-50%",
                "steps": {
                    "step6": {
                        "target_range": "18-22元",
                        "buy_zone": "12-14元",
                        "stop_loss": "10.8元",
                        "profit_loss_ratio": "2.1x",
                        "text": "赔率来自订单兑现和估值修复。"
                    },
                    "step7": {
                        "peers": [
                            {"name": "可比A", "growth": "20%", "profitability": "强", "valuation": "25x", "note": "估值较高"},
                            {"name": "可比B", "growth": "12%", "profitability": "中", "valuation": "18x", "note": "更稳健"}
                        ]
                    },
                    "technical": {
                        "trend": 75,
                        "indicator": 68,
                        "pattern": 70,
                        "volume_price": 62,
                        "fund_flow": 58,
                        "judgment": "技术面中性偏强"
                    }
                }
            },
            ensure_ascii=False,
        )

        report = g.render_report(payload, "000001", "测试股份", analysis)

        self.assertIn("18-22元", report)
        self.assertIn("2.1x", report)
        self.assertIn("30%-50%", report)
        self.assertIn("12-14元", report)
        self.assertIn("10.8元", report)
        self.assertIn("可比A", report)
        self.assertIn("25x", report)
        self.assertIn("技术面中性偏强", report)
        self.assertIn("多周期趋势", report)


if __name__ == "__main__":
    unittest.main()
