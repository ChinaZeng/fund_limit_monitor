import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from report_renderer import (
    DEFAULT_FONT_PATH,
    _build_index_tables,
    _investment_plan_rows,
    _wrap_text,
    build_font_subset_text,
    render_report_image,
)

try:
    from fontTools.ttLib import TTFont
except ImportError:
    TTFont = None


class ReportRendererTest(unittest.TestCase):
    def _sample_report(self):
        return {
            "title": "基金申购限额日报 (A类)",
            "generated_at": "2026-05-07 13:30:00",
            "investment_plan": {
                "title": "纳指100定投计划",
                "target_index": "纳斯达克100",
                "target_amount": 100,
                "target_display": "100元",
                "remaining_amount": 0,
                "remaining_display": "0元",
                "sort_note": "按年化跟踪误差从低到高，结合当日申购限额分配",
                "rows": [
                    {
                        "order": 1,
                        "code": "000834",
                        "name": "大成纳斯达克100ETF联接A",
                        "short_name": "大成纳指100",
                        "tracking_error_display": "1.03%",
                        "tracking_display": "年化1.03% / 同类2.01% / 05-28",
                        "limit_display": "50元",
                        "amount": 50,
                        "amount_display": "50元",
                    },
                    {
                        "order": 2,
                        "code": "016452",
                        "name": "南方纳斯达克100指数A",
                        "short_name": "南方纳指100",
                        "tracking_error_display": "1.42%",
                        "tracking_display": "年化1.42% / 同类2.01% / 05-28",
                        "limit_display": "200元",
                        "amount": 50,
                        "amount_display": "50元",
                    },
                ],
            },
            "sections": [
                {
                    "title": "可申购",
                    "groups": [
                        {
                            "title": "纳斯达克100",
                            "funds": [
                                {
                                    "code": "270042",
                                    "name": "广发纳斯达克100ETF联接A",
                                    "short_name": "广发纳指100",
                                    "limit_display": "100元 -> 500元 ↑",
                                    "previous_limit_display": "100元",
                                    "current_limit_display": "500元",
                                    "change_direction": "increase",
                                    "change_display": "100元 -> 500元 ↑",
                                    "status": "开放申购",
                                    "available": True,
                                }
                            ],
                        }
                    ],
                },
                {
                    "title": "不可申购",
                    "groups": [
                        {
                            "title": "标普500",
                            "funds": [
                                {
                                    "code": "161125",
                                    "name": "易方达标普500指数A",
                                    "short_name": "易方达标普500",
                                    "limit_display": "暂停申购",
                                    "status": "暂停申购",
                                    "available": False,
                                }
                            ],
                        }
                    ],
                },
                {
                    "title": "可申购",
                    "groups": [
                        {
                            "title": "其他",
                            "funds": [
                                {
                                    "code": "012920",
                                    "name": "易方达全球成长精选混合(QDII)A",
                                    "short_name": "易方达全球成长混合(QDII)",
                                    "limit_display": "20元",
                                    "status": "限大额",
                                    "available": True,
                                }
                            ],
                        }
                    ],
                },
            ],
            "fee_groups": [
                {
                    "title": "纳斯达克100",
                    "funds": [
                        {
                            "code": "270042",
                            "name": "广发纳斯达克100ETF联接A",
                            "short_name": "广发纳指100",
                            "operation_display": "管理0.80% 托管0.20% 销售0.00% 合计1.00%/年",
                            "subscription_display": "<100万元 0.13%",
                            "redemption_display": "<7天 1.50% / >=2年 0.00%",
                            "fee_error": "",
                            "tracking_display": "年化1.11% / 同类2.01% / 05-28",
                            "tracking_fetch_error": "",
                        }
                    ],
                },
                {
                    "title": "标普500",
                    "funds": [
                        {
                            "code": "161125",
                            "name": "易方达标普500指数A",
                            "short_name": "易方达标普500",
                            "operation_display": "",
                            "subscription_display": "",
                            "redemption_display": "",
                            "fee_error": "费率获取失败",
                            "tracking_display": "",
                            "tracking_fetch_error": "跟踪误差获取失败",
                        }
                    ],
                },
                {
                    "title": "其他",
                    "funds": [
                        {
                            "code": "012920",
                            "name": "易方达全球成长精选混合(QDII)A",
                            "short_name": "易方达全球成长混合(QDII)",
                            "operation_display": "管理1.20% 托管0.20% 销售0.00% 合计1.40%/年",
                            "subscription_display": "<100万元 0.15%",
                            "redemption_display": "<=6天 1.50% / >=730天 0.00%",
                            "fee_error": "",
                            "tracking_display": "",
                            "tracking_fetch_error": "",
                        }
                    ],
                },
            ],
        }

    def test_render_report_image_uses_bundled_font(self):
        self.assertTrue(DEFAULT_FONT_PATH.exists())
        ImageFont.truetype(str(DEFAULT_FONT_PATH), size=20)

        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "report.png"
            render_report_image(self._sample_report(), output)

            self.assertGreater(output.stat().st_size, 0)
            with Image.open(output) as image:
                self.assertEqual(image.format, "PNG")
                self.assertGreaterEqual(image.width, 1300)
                self.assertGreater(image.height, 500)

    def test_index_tables_merge_limit_and_fee_info(self):
        tables = _build_index_tables(self._sample_report())

        self.assertEqual(
            [table["title"] for table in tables],
            ["纳斯达克100", "标普500", "其他"],
        )
        self.assertEqual(tables[0]["summary"], "可申购: 1 / 不可申购: 0")
        self.assertEqual(tables[1]["summary"], "可申购: 0 / 不可申购: 1")
        self.assertEqual(tables[2]["summary"], "可申购: 1 / 不可申购: 0")
        self.assertEqual(
            tables[0]["rows"][0]["name"],
            "广发纳斯达克100ETF联接A(270042)",
        )
        self.assertEqual(tables[0]["rows"][0]["spread"], "可申购\n100元 -> 500元 ↑")
        self.assertEqual(
            tables[0]["rows"][0]["tracking"],
            "年化1.11% / 同类2.01% / 05-28",
        )
        self.assertEqual(
            tables[0]["rows"][0]["operation"],
            "管理0.80% 托管0.20%\n销售0.00% 合计1.00%/年",
        )
        self.assertEqual(tables[0]["rows"][0]["subscription"], "<100万元\n0.13%")
        self.assertEqual(
            tables[0]["rows"][0]["redemption"],
            "<7天 1.50%\n>=2年 0.00%",
        )
        self.assertEqual(tables[1]["rows"][0]["spread"], "不可申购\n暂停申购")
        self.assertEqual(tables[1]["rows"][0]["tracking"], "跟踪误差获取失败")
        self.assertTrue(tables[1]["rows"][0]["tracking_error"])
        self.assertEqual(tables[1]["rows"][0]["operation"], "费率获取失败")
        self.assertEqual(tables[1]["rows"][0]["subscription"], "--")
        self.assertEqual(
            tables[2]["rows"][0]["name"],
            "易方达全球成长精选混合(QDII)A(012920)",
        )
        self.assertEqual(tables[2]["rows"][0]["spread"], "可申购\n20元")

    def test_investment_plan_rows_for_image_table(self):
        rows = _investment_plan_rows(self._sample_report()["investment_plan"])

        self.assertEqual(rows[0]["fund"], "大成纳指100(000834)")
        self.assertEqual(rows[0]["tracking"], "1.03%")
        self.assertEqual(rows[0]["limit"], "50元")
        self.assertEqual(rows[0]["amount"], "50元")

    def test_investment_plan_empty_state_uses_placeholder(self):
        rows = _investment_plan_rows({"rows": []})

        self.assertEqual(rows[0]["fund"], "暂无可执行计划")
        self.assertTrue(rows[0]["placeholder"])

    def test_cell_wrapping_keeps_complete_copy(self):
        font = ImageFont.truetype(str(DEFAULT_FONT_PATH), size=17)
        draw = ImageDraw.Draw(Image.new("RGB", (300, 1), "#ffffff"))
        text = "管理0.80% 托管0.20% 销售0.00% 合计1.00%/年"

        lines = _wrap_text(draw, text, font, 120)

        self.assertGreater(len(lines), 1)
        self.assertNotIn("...", "".join(lines))
        self.assertEqual(
            "".join(lines).replace(" ", ""),
            text.replace(" ", ""),
        )

    @unittest.skipIf(TTFont is None, "fontTools is required for font coverage checks")
    def test_bundled_font_covers_current_report_text(self):
        with open("config.json", "r", encoding="utf-8") as f:
            config = json.load(f)

        font = TTFont(str(DEFAULT_FONT_PATH))
        covered_codepoints = set()
        for table in font["cmap"].tables:
            covered_codepoints.update(table.cmap.keys())

        expected_text = build_font_subset_text(config)
        missing = sorted({char for char in expected_text if ord(char) not in covered_codepoints})

        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
