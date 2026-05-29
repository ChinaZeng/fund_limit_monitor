import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from monitor import FundMonitor


FEE_HTML = """
<html>
  <body>
    <h4>运作费用</h4>
    <table>
      <tr>
        <td>管理费率</td><td>0.80%（每年）</td>
        <td>托管费率</td><td>0.20%（每年）</td>
        <td>销售服务费率</td><td>---</td>
      </tr>
    </table>
    <h4>申购费率（前端）</h4>
    <table>
      <tr>
        <th>适用金额</th>
        <th>适用期限</th>
        <th>原费率 | 天天基金优惠费率 银行卡购买 | 活期宝购买</th>
      </tr>
      <tr>
        <td>小于50万元</td>
        <td>---</td>
        <td>1.50% | 0.15% | 0.15%</td>
      </tr>
      <tr>
        <td>大于等于500万元</td>
        <td>---</td>
        <td>每笔1000元</td>
      </tr>
    </table>
    <h4>赎回费率</h4>
    <table>
      <tr><th>适用金额</th><th>适用期限</th><th>赎回费率</th></tr>
      <tr><td>---</td><td>小于7天</td><td>1.50%</td></tr>
      <tr><td>---</td><td>大于等于365天，小于730天</td><td>0.25%</td></tr>
      <tr><td>---</td><td>大于等于730天</td><td>0.00%</td></tr>
    </table>
  </body>
</html>
"""

TRACKING_HTML = """
<html>
  <body>
    <div id="jjzsfj" class="box nb">
      <table class="fxtb">
        <tr>
          <th>跟踪指数</th>
          <th>年化跟踪误差</th>
          <th>同类平均跟踪误差</th>
        </tr>
        <tr>
          <td>纳斯达克100指数</td>
          <td>1.11%</td>
          <td>2.01%</td>
        </tr>
      </table>
      <div class="limit-time">截止至：2026-05-28</div>
    </div>
  </body>
</html>
"""


def make_monitor(history_db_path=None):
    monitor = object.__new__(FundMonitor)
    monitor.history_db_path = Path(history_db_path) if history_db_path else None
    if history_db_path:
        monitor._init_history_db()
    return monitor


def fund(
    code,
    limit_text,
    limit_val,
    status="开放申购",
    name=None,
    tracking_error=None,
):
    data = {
        "code": code,
        "name": name or f"测试基金{code}A",
        "status": status,
        "limit_text": limit_text,
        "limit_val": limit_val,
    }
    if tracking_error:
        data.update(
            {
                "tracking_error_display": tracking_error,
                "tracking_display": f"年化{tracking_error} / 同类2.01% / 05-28",
                "tracking_date": "2026-05-28",
            }
        )
    return data


def flattened_report_funds(report):
    funds = {}
    for section in report["sections"]:
        for group in section["groups"]:
            for item in group["funds"]:
                funds[item["code"]] = item
    return funds


class FundMonitorHistoryTest(unittest.TestCase):
    def test_history_database_initializes_table(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "history.db"
            make_monitor(db_path)

            with sqlite3.connect(db_path) as conn:
                limit_row = conn.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table' AND name = 'fund_limit_history'
                    """
                ).fetchone()
                plan_row = conn.execute(
                    """
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table' AND name = 'fund_investment_plan_history'
                    """
                ).fetchone()

            self.assertEqual(limit_row[0], "fund_limit_history")
            self.assertEqual(plan_row[0], "fund_investment_plan_history")

    def test_save_history_upserts_one_row_per_day(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = make_monitor(Path(tmpdir) / "history.db")

            monitor._save_history("2026-05-11", [fund("270042", "100元", 100)])
            monitor._save_history("2026-05-11", [fund("270042", "500元", 500)])

            with sqlite3.connect(monitor.history_db_path) as conn:
                count = conn.execute(
                    "SELECT COUNT(*) FROM fund_limit_history"
                ).fetchone()[0]
                limits_json = conn.execute(
                    "SELECT limits_json FROM fund_limit_history WHERE date = ?",
                    ("2026-05-11",),
                ).fetchone()[0]

            limits = json.loads(limits_json)
            self.assertEqual(count, 1)
            self.assertEqual(limits["270042"]["limit_value"], 500)
            self.assertEqual(limits["270042"]["limit_text"], "500元")

    def test_report_uses_latest_history_before_report_date(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = make_monitor(Path(tmpdir) / "history.db")
            monitor._save_history("2026-05-09", [fund("270042", "50元", 50)])
            monitor._save_history("2026-05-10", [fund("270042", "100元", 100)])
            monitor._save_history("2026-05-11", [fund("270042", "999元", 999)])

            report = monitor.build_report(
                [fund("270042", "500元", 500)],
                generated_at="2026-05-11 13:30:00",
            )
            item = flattened_report_funds(report)["270042"]

            self.assertEqual(item["previous_limit_display"], "100元")
            self.assertEqual(item["current_limit_display"], "500元")
            self.assertEqual(item["change_direction"], "increase")
            self.assertEqual(item["change_display"], "100元 -> 500元 ↑")
            self.assertEqual(item["limit_display"], "100元 -> 500元 ↑")

    def test_empty_database_ignores_legacy_history_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                Path("history.json").write_text(
                    json.dumps({"limits": {"270042": 100}}),
                    encoding="utf-8",
                )
                monitor = make_monitor(Path(tmpdir) / "history.db")

                report = monitor.build_report(
                    [fund("270042", "500元", 500)],
                    generated_at="2026-05-11 13:30:00",
                )
                item = flattened_report_funds(report)["270042"]
            finally:
                os.chdir(old_cwd)

            self.assertEqual(item["previous_limit_display"], "")
            self.assertEqual(item["change_display"], "")
            self.assertEqual(item["limit_display"], "500元")

    def test_change_display_handles_increase_decrease_unlimited_and_paused(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = make_monitor(Path(tmpdir) / "history.db")
            monitor._save_history(
                "2026-05-10",
                [
                    fund("A", "100元", 100),
                    fund("B", "500元", 500),
                    fund("C", "100元", 100),
                    fund("D", "100元", 100),
                ],
            )

            report = monitor.build_report(
                [
                    fund("A", "500元", 500),
                    fund("B", "100元", 100),
                    fund("C", "None", float("inf")),
                    fund("D", "None", -1, status="暂停申购"),
                ],
                generated_at="2026-05-11 13:30:00",
            )
            items = flattened_report_funds(report)
            markdown = monitor.render_report_markdown(report)

            self.assertEqual(items["A"]["change_display"], "100元 -> 500元 ↑")
            self.assertEqual(items["B"]["change_display"], "500元 -> 100元 ↓")
            self.assertEqual(items["C"]["change_display"], "100元 -> 不限 ↑")
            self.assertEqual(items["D"]["change_display"], "100元 -> 暂停申购 ↓")
            self.assertIn("测试基金D(D) 🔴 : 100元 -> 暂停申购 ↓", markdown)


class FundMonitorFeeTest(unittest.TestCase):
    def setUp(self):
        self.monitor = make_monitor()

    def test_parse_fee_info_from_eastmoney_tables(self):
        fee_info = self.monitor._parse_fee_info_html(FEE_HTML)

        self.assertEqual(
            fee_info["operation_display"],
            "管理0.80% 托管0.20% 销售-- 合计1.00%/年",
        )
        self.assertEqual(fee_info["subscription_display"], "<50万元 0.15%")
        self.assertEqual(
            fee_info["redemption_display"],
            "<7天 1.50% / >=730天 0.00%",
        )
        self.assertEqual(fee_info["fee_error"], "")

    @patch("monitor.requests.get", side_effect=Exception("network down"))
    def test_fetch_fee_failure_returns_error_without_raising(self, _get):
        fee_info = self.monitor.fetch_fund_fee_info("270042")

        self.assertEqual(fee_info["fee_error"], "费率获取失败")
        self.assertEqual(fee_info["operation_display"], "")

    def test_markdown_includes_fee_and_tracking_summary_section(self):
        funds_data = [
            {
                "code": "270042",
                "name": "广发纳斯达克100ETF联接A",
                "status": "开放申购",
                "limit_text": "100元",
                "limit_val": 100,
                "operation_display": "管理0.80% 托管0.20% 销售0.00% 合计1.00%/年",
                "subscription_display": "<100万元 0.13%",
                "redemption_display": "<7天 1.50% / >=2年 0.00%",
                "fee_error": "",
                "tracking_display": "年化1.11% / 同类2.01% / 05-28",
                "tracking_fetch_error": "",
            },
            {
                "code": "161125",
                "name": "易方达标普500指数A",
                "status": "暂停申购",
                "limit_text": "None",
                "limit_val": -1,
                "fee_error": "费率获取失败",
                "tracking_display": "",
                "tracking_fetch_error": "跟踪误差获取失败",
            },
        ]

        report = self.monitor.build_report(
            funds_data,
            generated_at="2026-05-11 13:30:00",
        )
        markdown = self.monitor.render_report_markdown(report)

        self.assertIn("## 费率摘要", markdown)
        self.assertIn(
            "| 基金 | 跟踪表现 | 运作费用 | 申购优惠 | 赎回费率 |",
            markdown,
        )
        self.assertIn(
            "| 广发纳指100(270042) | 年化1.11% / 同类2.01% / 05-28 | "
            "管理0.80% 托管0.20% 销售0.00% 合计1.00%/年 | "
            "<100万元 0.13% | <7天 1.50% / >=2年 0.00% |",
            markdown,
        )
        self.assertIn(
            "| 易方达标普500(161125) | 跟踪误差获取失败 | 费率获取失败 | -- | -- |",
            markdown,
        )


class FundMonitorTrackingTest(unittest.TestCase):
    def setUp(self):
        self.monitor = make_monitor()

    def test_parse_tracking_info_from_eastmoney_index_metrics(self):
        tracking_info = self.monitor._parse_tracking_info_html(TRACKING_HTML)

        self.assertEqual(tracking_info["tracking_index"], "纳斯达克100指数")
        self.assertEqual(tracking_info["tracking_error_display"], "1.11%")
        self.assertEqual(tracking_info["tracking_peer_error_display"], "2.01%")
        self.assertEqual(tracking_info["tracking_date"], "2026-05-28")
        self.assertEqual(
            tracking_info["tracking_display"],
            "年化1.11% / 同类2.01% / 05-28",
        )
        self.assertEqual(tracking_info["tracking_fetch_error"], "")

    def test_missing_tracking_metrics_are_empty_without_error(self):
        tracking_info = self.monitor._parse_tracking_info_html("<html></html>")

        self.assertEqual(tracking_info["tracking_display"], "")
        self.assertEqual(tracking_info["tracking_fetch_error"], "")

    @patch("monitor.requests.get", side_effect=Exception("network down"))
    def test_fetch_tracking_failure_returns_error_without_raising(self, _get):
        tracking_info = self.monitor.fetch_fund_tracking_info("270042")

        self.assertEqual(
            tracking_info["tracking_fetch_error"],
            "跟踪误差获取失败",
        )
        self.assertEqual(tracking_info["tracking_display"], "跟踪误差获取失败")

    def test_fetch_all_funds_merges_tracking_info(self):
        self.monitor.funds_config = [
            {"code": "270042", "name": "广发纳斯达克100ETF联接A"}
        ]

        with patch.object(
            self.monitor,
            "fetch_fund_info",
            return_value=fund(
                "270042",
                "100元",
                100,
                name="广发纳斯达克100ETF联接A",
            ),
        ), patch.object(
            self.monitor,
            "fetch_fund_fee_info",
            return_value={"fee_error": ""},
        ), patch.object(
            self.monitor,
            "fetch_fund_tracking_info",
            return_value={"tracking_display": "年化1.11% / 同类2.01% / 05-28"},
        ), patch(
            "monitor.time.sleep"
        ):
            funds_data = self.monitor.fetch_all_funds()

        self.assertEqual(
            funds_data[0]["tracking_display"],
            "年化1.11% / 同类2.01% / 05-28",
        )


class FundMonitorInvestmentPlanTest(unittest.TestCase):
    def setUp(self):
        self.monitor = make_monitor()

    def test_investment_plan_allocates_by_tracking_error_and_limit(self):
        report = self.monitor.build_report(
            [
                fund(
                    "000834",
                    "50元",
                    50,
                    name="大成纳斯达克100ETF联接A",
                    tracking_error="1.03%",
                ),
                fund(
                    "040046",
                    "10元",
                    10,
                    name="华安纳斯达克100ETF联接A",
                    tracking_error="1.05%",
                ),
                fund(
                    "270042",
                    "10元",
                    10,
                    name="广发纳斯达克100ETF联接A",
                    tracking_error="1.11%",
                ),
                fund(
                    "016452",
                    "200元",
                    200,
                    name="南方纳斯达克100指数A",
                    tracking_error="1.42%",
                ),
                fund(
                    "160213",
                    "100元",
                    -1,
                    status="暂停申购",
                    name="国泰纳斯达克100(LOF)",
                    tracking_error="1.00%",
                ),
                fund(
                    "017436",
                    "5000元",
                    5000,
                    name="华宝纳斯达克精选股票发起式A",
                ),
            ],
            generated_at="2026-05-29 13:30:00",
        )

        rows = report["investment_plan"]["rows"]

        self.assertFalse(report["investment_plan"]["changed"])
        self.assertEqual(
            report["investment_plan"]["display_title"],
            "纳指100定投计划",
        )
        self.assertEqual(report["investment_plan"]["target_display"], "100元")
        self.assertEqual(report["investment_plan"]["remaining_display"], "0元")
        self.assertEqual(
            [(row["code"], row["amount_display"]) for row in rows],
            [
                ("000834", "50元"),
                ("040046", "10元"),
                ("270042", "10元"),
                ("016452", "30元"),
            ],
        )

    def test_investment_plan_amount_comes_from_config(self):
        self.monitor.config = {"investment_plan_amount": 80}

        report = self.monitor.build_report(
            [
                fund(
                    "000834",
                    "50元",
                    50,
                    name="大成纳斯达克100ETF联接A",
                    tracking_error="1.03%",
                ),
                fund(
                    "016452",
                    "200元",
                    200,
                    name="南方纳斯达克100指数A",
                    tracking_error="1.42%",
                ),
            ],
            generated_at="2026-05-29 13:30:00",
        )

        rows = report["investment_plan"]["rows"]

        self.assertEqual(report["investment_plan"]["target_display"], "80元")
        self.assertEqual(report["investment_plan"]["remaining_display"], "0元")
        self.assertEqual(
            [(row["code"], row["amount_display"]) for row in rows],
            [("000834", "50元"), ("016452", "30元")],
        )

    def test_investment_plan_change_compares_order_code_and_amount(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = make_monitor(Path(tmpdir) / "history.db")
            old_funds = [
                fund(
                    "000834",
                    "50元",
                    50,
                    name="大成纳斯达克100ETF联接A",
                    tracking_error="1.03%",
                ),
                fund(
                    "040046",
                    "10元",
                    10,
                    name="华安纳斯达克100ETF联接A",
                    tracking_error="1.05%",
                ),
                fund(
                    "270042",
                    "10元",
                    10,
                    name="广发纳斯达克100ETF联接A",
                    tracking_error="1.11%",
                ),
                fund(
                    "016452",
                    "200元",
                    200,
                    name="南方纳斯达克100指数A",
                    tracking_error="1.42%",
                ),
            ]
            old_report = monitor.build_report(
                old_funds,
                generated_at="2026-05-28 13:30:00",
            )
            monitor._save_history(
                "2026-05-28",
                old_funds,
                old_report["investment_plan"],
            )

            unchanged_report = monitor.build_report(
                old_funds,
                generated_at="2026-05-29 13:30:00",
            )
            changed_report = monitor.build_report(
                [
                    old_funds[0],
                    fund(
                        "040046",
                        "5元",
                        5,
                        name="华安纳斯达克100ETF联接A",
                        tracking_error="1.05%",
                    ),
                    old_funds[2],
                    old_funds[3],
                ],
                generated_at="2026-05-29 13:30:00",
            )

        self.assertFalse(unchanged_report["investment_plan"]["changed"])
        self.assertTrue(changed_report["investment_plan"]["changed"])
        self.assertEqual(
            changed_report["investment_plan"]["display_title"],
            "纳指100定投计划【策略变更】",
        )
        self.assertEqual(
            changed_report["investment_plan"]["change_notice"],
            "【强提醒】定投策略较上期发生变化，请按新计划执行。",
        )

    def test_markdown_includes_investment_plan_table(self):
        report = self.monitor.build_report(
            [
                fund(
                    "000834",
                    "50元",
                    50,
                    name="大成纳斯达克100ETF联接A",
                    tracking_error="1.03%",
                ),
                fund(
                    "016452",
                    "200元",
                    200,
                    name="南方纳斯达克100指数A",
                    tracking_error="1.42%",
                ),
            ],
            generated_at="2026-05-29 13:30:00",
        )

        markdown = self.monitor.render_report_markdown(report)

        self.assertIn("## 纳指100定投计划", markdown)
        self.assertIn("| 顺序 | 基金 | 年化跟踪误差 | 单日限额 | 今日定投 |", markdown)
        self.assertIn("| 1 | 大成纳指100(000834) | 1.03% | 50元 | 50元 |", markdown)
        self.assertIn("| 2 | 南方纳指100(016452) | 1.42% | 200元 | 50元 |", markdown)

    def test_markdown_warns_when_investment_plan_changes(self):
        report = self.monitor.build_report(
            [
                fund(
                    "000834",
                    "50元",
                    50,
                    name="大成纳斯达克100ETF联接A",
                    tracking_error="1.03%",
                )
            ],
            generated_at="2026-05-29 13:30:00",
        )
        report["investment_plan"]["changed"] = True
        report["investment_plan"]["display_title"] = "纳指100定投计划【策略变更】"
        report["investment_plan"]["change_notice"] = (
            "【强提醒】定投策略较上期发生变化，请按新计划执行。"
        )

        markdown = self.monitor.render_report_markdown(report)

        self.assertIn("## 纳指100定投计划【策略变更】", markdown)
        self.assertIn("【强提醒】定投策略较上期发生变化，请按新计划执行。", markdown)


if __name__ == "__main__":
    unittest.main()
