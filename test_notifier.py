import base64
import hashlib
import hmac
import smtplib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, quote_plus, urlsplit

from notifier import (
    ConsoleNotifier,
    DingTalkNotifier,
    GmailNotifier,
    MultiNotifier,
    WeChatNotifier,
    build_notifier,
)


class GmailNotifierTest(unittest.TestCase):
    def _smtp_client(self, smtp_ssl):
        smtp = smtp_ssl.return_value.__enter__.return_value
        smtp.send_message.return_value = {}
        return smtp

    @patch("notifier.smtplib.SMTP_SSL")
    def test_sends_inline_png_with_plain_text_fallback(self, smtp_ssl):
        smtp = self._smtp_client(smtp_ssl)
        notifier = GmailNotifier("me@gmail.com", "abcd efgh ijkl mnop")

        with tempfile.TemporaryDirectory() as tmpdir:
            image_path = Path(tmpdir) / "基金日报.png"
            image_path.write_bytes(b"PNG DATA")

            with patch("builtins.print"):
                result = notifier.send(
                    "基金申购限额日报",
                    "# 完整报告\n\n中文内容",
                    image_path=str(image_path),
                )

        self.assertTrue(result)
        smtp_ssl.assert_called_once()
        self.assertEqual(smtp_ssl.call_args.args, ("smtp.gmail.com", 465))
        self.assertEqual(smtp_ssl.call_args.kwargs["timeout"], 10)
        self.assertIn("context", smtp_ssl.call_args.kwargs)
        smtp.login.assert_called_once_with("me@gmail.com", "abcdefghijklmnop")

        email_message = smtp.send_message.call_args.args[0]
        self.assertEqual(email_message["Subject"], "基金申购限额日报")
        self.assertEqual(email_message["From"], "me@gmail.com")
        self.assertEqual(email_message["To"], "me@gmail.com")
        self.assertEqual(email_message.get_content_type(), "multipart/alternative")

        plain_part, related_part = email_message.get_payload()
        self.assertEqual(plain_part.get_content_type(), "text/plain")
        self.assertIn("# 完整报告", plain_part.get_content())
        self.assertIn("中文内容", plain_part.get_content())
        self.assertEqual(related_part.get_content_type(), "multipart/related")

        html_part, image_part = related_part.get_payload()
        self.assertEqual(html_part.get_content_type(), "text/html")
        self.assertIn('src="cid:fund-limit-report"', html_part.get_content())
        self.assertIn("基金申购限额日报", html_part.get_content())
        self.assertEqual(image_part.get_content_type(), "image/png")
        self.assertEqual(image_part.get_payload(decode=True), b"PNG DATA")
        self.assertEqual(image_part["Content-ID"], "<fund-limit-report>")
        self.assertEqual(image_part.get_content_disposition(), "inline")
        self.assertEqual(image_part.get_filename(), "基金日报.png")

    @patch("notifier.smtplib.SMTP_SSL")
    def test_sends_plain_text_when_image_path_is_not_provided(self, smtp_ssl):
        smtp = self._smtp_client(smtp_ssl)
        notifier = GmailNotifier("me@gmail.com", "APP_PASSWORD")
        message = "# 日报\n\n| 基金 | 限额 |"

        with patch("builtins.print"):
            result = notifier.send("日报", message)

        self.assertTrue(result)
        email_message = smtp.send_message.call_args.args[0]
        self.assertEqual(email_message.get_content_type(), "text/plain")
        self.assertEqual(email_message.get_content().rstrip(), message)

    @patch("notifier.smtplib.SMTP_SSL")
    def test_missing_image_returns_false_without_connecting(self, smtp_ssl):
        notifier = GmailNotifier("me@gmail.com", "APP_PASSWORD")

        with patch("builtins.print"):
            result = notifier.send(
                "日报",
                "内容",
                image_path="/missing/fund-limit.png",
            )

        self.assertFalse(result)
        smtp_ssl.assert_not_called()

    @patch("notifier.smtplib.SMTP_SSL")
    def test_refused_recipient_returns_false(self, smtp_ssl):
        smtp = self._smtp_client(smtp_ssl)
        smtp.send_message.return_value = {"me@gmail.com": (550, b"rejected")}
        notifier = GmailNotifier("me@gmail.com", "APP_PASSWORD")

        with patch("builtins.print"):
            result = notifier.send("日报", "内容")

        self.assertFalse(result)

    @patch("notifier.smtplib.SMTP_SSL")
    def test_smtp_error_returns_false(self, smtp_ssl):
        smtp = self._smtp_client(smtp_ssl)
        smtp.login.side_effect = smtplib.SMTPAuthenticationError(535, b"bad auth")
        notifier = GmailNotifier("me@gmail.com", "APP_PASSWORD")

        with patch("builtins.print"):
            result = notifier.send("日报", "内容")

        self.assertFalse(result)


class DingTalkNotifierTest(unittest.TestCase):
    def test_signed_webhook_url_contains_timestamp_and_encoded_sign(self):
        notifier = DingTalkNotifier(
            "https://oapi.dingtalk.com/robot/send?access_token=TOKEN",
            "SECRET",
        )

        with patch("notifier.time.time", return_value=1710000000.123):
            signed_url = notifier._signed_webhook_url()

        query = urlsplit(signed_url).query
        params = parse_qs(query)
        timestamp = "1710000000123"
        expected_sign = base64.b64encode(
            hmac.new(
                b"SECRET",
                f"{timestamp}\nSECRET".encode("utf-8"),
                digestmod=hashlib.sha256,
            ).digest()
        ).decode("utf-8")

        self.assertEqual(params["access_token"], ["TOKEN"])
        self.assertEqual(params["timestamp"], [timestamp])
        self.assertEqual(params["sign"], [expected_sign])
        self.assertIn(f"sign={quote_plus(expected_sign)}", query)

    @patch("notifier.requests.post")
    def test_sends_dingtalk_markdown_payload(self, post):
        post.return_value = Mock(status_code=200)
        notifier = DingTalkNotifier("https://example.com/send?access_token=TOKEN", "SECRET")

        with patch("builtins.print"):
            result = notifier.send("日报", "# 内容")

        self.assertTrue(result)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["msgtype"], "markdown")
        self.assertEqual(payload["markdown"]["title"], "日报")
        self.assertEqual(payload["markdown"]["text"], "# 内容")

    @patch("notifier.requests.post")
    def test_sends_dingtalk_image_payload_when_image_url_is_provided(self, post):
        post.return_value = Mock(status_code=200)
        notifier = DingTalkNotifier("https://example.com/send?access_token=TOKEN", "SECRET")
        image_url = "https://example.com/reports/fund-limit.png"

        with patch("builtins.print"):
            result = notifier.send("日报", "# 内容", image_url=image_url)

        self.assertTrue(result)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["msgtype"], "markdown")
        self.assertEqual(payload["markdown"]["title"], "日报")
        self.assertEqual(
            payload["markdown"]["text"],
            "## 日报\n\n"
            "![日报](https://example.com/reports/fund-limit.png)\n\n"
            "[查看原图](https://example.com/reports/fund-limit.png)",
        )

    @patch("notifier.requests.post")
    def test_returns_false_when_dingtalk_returns_error_body(self, post):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = {
            "errcode": 310000,
            "errmsg": "keywords not in content",
        }
        notifier = DingTalkNotifier("https://example.com/send?access_token=TOKEN", "SECRET")

        with patch("builtins.print") as mock_print:
            result = notifier.send("日报", "# 内容")

        self.assertFalse(result)
        mock_print.assert_called_once_with(
            "DingTalk notification response. "
            "Status: 200, errcode: 310000, errmsg: keywords not in content"
        )

    @patch("notifier.requests.post")
    def test_returns_true_when_dingtalk_returns_success_body(self, post):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = {"errcode": 0, "errmsg": "ok"}
        notifier = DingTalkNotifier("https://example.com/send?access_token=TOKEN", "SECRET")

        with patch("builtins.print") as mock_print:
            result = notifier.send("日报", "# 内容")

        self.assertTrue(result)
        mock_print.assert_called_once_with(
            "DingTalk notification response. Status: 200, errcode: 0, errmsg: ok"
        )


class WeChatNotifierTest(unittest.TestCase):
    @patch("notifier.requests.post")
    def test_sends_wechat_markdown_payload(self, post):
        post.return_value = Mock(status_code=200)
        notifier = WeChatNotifier("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=KEY")

        with patch("builtins.print"):
            result = notifier.send("日报", "# 内容")

        self.assertTrue(result)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["msgtype"], "markdown")
        self.assertEqual(payload["markdown"]["content"], "# 内容")


class MultiNotifierTest(unittest.TestCase):
    def test_sends_to_all_notifiers_and_returns_false_when_any_fails(self):
        first = Mock()
        first.send.return_value = True
        second = Mock()
        second.send.return_value = False
        notifier = MultiNotifier([first, second])

        result = notifier.send("日报", "# 内容")

        self.assertFalse(result)
        first.send.assert_called_once_with(
            "日报",
            "# 内容",
            image_url=None,
            image_path=None,
        )
        second.send.assert_called_once_with(
            "日报",
            "# 内容",
            image_url=None,
            image_path=None,
        )

    def test_passes_image_url_and_path_to_all_notifiers(self):
        first = Mock()
        first.send.return_value = True
        second = Mock()
        second.send.return_value = True
        notifier = MultiNotifier([first, second])

        result = notifier.send(
            "日报",
            "# 内容",
            image_url="https://example.com/a.png",
            image_path="reports/a.png",
        )

        self.assertTrue(result)
        first.send.assert_called_once_with(
            "日报",
            "# 内容",
            image_url="https://example.com/a.png",
            image_path="reports/a.png",
        )
        second.send.assert_called_once_with(
            "日报",
            "# 内容",
            image_url="https://example.com/a.png",
            image_path="reports/a.png",
        )

    def test_requires_local_image_when_any_notifier_requires_it(self):
        first = Mock(requires_local_image=False)
        second = Mock(requires_local_image=True)

        notifier = MultiNotifier([first, second])

        self.assertTrue(notifier.requires_local_image)


class BuildNotifierTest(unittest.TestCase):
    @patch.dict(
        "os.environ",
        {
            "GMAIL_ADDRESS": "me@gmail.com",
            "GMAIL_APP_PASSWORD": "abcd efgh ijkl mnop",
        },
        clear=True,
    )
    def test_default_environment_values_are_used_for_configured_gmail_notifier(self):
        notifier = build_notifier({"notifier": {"type": "gmail"}})

        self.assertIsInstance(notifier, GmailNotifier)
        self.assertEqual(notifier.address, "me@gmail.com")
        self.assertEqual(notifier.app_password, "abcdefghijklmnop")

    @patch.dict(
        "os.environ",
        {
            "FUND_REPORT_GMAIL_ADDRESS": "custom@gmail.com",
            "FUND_REPORT_GMAIL_PASSWORD": "CUSTOM_PASSWORD",
        },
        clear=True,
    )
    def test_custom_environment_variable_names_are_used_for_gmail_notifier(self):
        notifier = build_notifier(
            {
                "notifier": {
                    "type": "gmail",
                    "address_env": "FUND_REPORT_GMAIL_ADDRESS",
                    "app_password_env": "FUND_REPORT_GMAIL_PASSWORD",
                }
            }
        )

        self.assertIsInstance(notifier, GmailNotifier)
        self.assertEqual(notifier.address, "custom@gmail.com")
        self.assertEqual(notifier.app_password, "CUSTOM_PASSWORD")

    @patch.dict("os.environ", {}, clear=True)
    @patch("builtins.print")
    def test_returns_console_when_selected_gmail_config_is_missing(self, _print):
        notifier = build_notifier({"notifier": {"type": "gmail"}})

        self.assertIsInstance(notifier, ConsoleNotifier)

    @patch.dict("os.environ", {}, clear=True)
    @patch("builtins.print")
    def test_does_not_read_gmail_credentials_from_config(self, _print):
        notifier = build_notifier(
            {
                "notifier": {
                    "type": "gmail",
                    "address": "inline@gmail.com",
                    "app_password": "INLINE_PASSWORD",
                }
            }
        )

        self.assertIsInstance(notifier, ConsoleNotifier)

    @patch.dict(
        "os.environ",
        {
            "DINGTALK_WEBHOOK_URL": "https://env.example.com/send?access_token=TOKEN",
            "DINGTALK_SECRET": "ENV_SECRET",
        },
        clear=True,
    )
    def test_default_environment_values_are_used_for_configured_dingtalk_notifier(self):
        notifier = build_notifier(
            {
                "notifier": {
                    "type": "dingtalk",
                }
            }
        )

        self.assertIsInstance(notifier, DingTalkNotifier)
        self.assertEqual(
            notifier.webhook_url,
            "https://env.example.com/send?access_token=TOKEN",
        )
        self.assertEqual(notifier.secret, "ENV_SECRET")

    @patch.dict(
        "os.environ",
        {
            "DINGTALK_WEBHOOK_URL_1": "https://example.com/send?access_token=TOKEN",
            "DINGTALK_SECRET_1": "SECRET",
        },
        clear=True,
    )
    def test_custom_environment_variable_names_are_used_for_dingtalk_notifier(self):
        notifier = build_notifier(
            {
                "notifier": {
                    "type": "dingtalk",
                    "webhook_url_env": "DINGTALK_WEBHOOK_URL_1",
                    "secret_env": "DINGTALK_SECRET_1",
                }
            }
        )

        self.assertIsInstance(notifier, DingTalkNotifier)
        self.assertEqual(
            notifier.webhook_url,
            "https://example.com/send?access_token=TOKEN",
        )
        self.assertEqual(notifier.secret, "SECRET")

    @patch.dict(
        "os.environ",
        {
            "DINGTALK_WEBHOOK_URL": "https://example.com/send?access_token=TOKEN",
            "DINGTALK_SECRET": "SECRET",
        },
        clear=True,
    )
    def test_returns_dingtalk_notifier_when_selected_and_config_complete(self):
        notifier = build_notifier(
            {
                "notifier": {
                    "type": "dingtalk",
                },
            }
        )

        self.assertIsInstance(notifier, DingTalkNotifier)

    @patch.dict("os.environ", {}, clear=True)
    @patch("builtins.print")
    def test_returns_console_when_selected_dingtalk_config_incomplete(self, _print):
        notifier = build_notifier(
            {
                "notifier": {
                    "type": "dingtalk",
                },
            }
        )

        self.assertIsInstance(notifier, ConsoleNotifier)

    @patch.dict("os.environ", {}, clear=True)
    @patch("builtins.print")
    def test_does_not_read_dingtalk_secret_values_from_config(self, _print):
        notifier = build_notifier(
            {
                "notifier": {
                    "type": "dingtalk",
                    "webhook_url": "https://example.com/send?access_token=TOKEN",
                    "secret": "SECRET",
                },
            }
        )

        self.assertIsInstance(notifier, ConsoleNotifier)

    @patch.dict(
        "os.environ",
        {
            "DINGTALK_WEBHOOK_URL_1": "https://example.com/send?access_token=TOKEN",
            "DINGTALK_SECRET_1": "SECRET",
            "WECHAT_WEBHOOK_URL_1": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=KEY",
        },
        clear=True,
    )
    def test_returns_multi_notifier_when_multiple_notifiers_configured(self):
        notifier = build_notifier(
            {
                "notifiers": [
                    {
                        "type": "dingtalk",
                        "webhook_url_env": "DINGTALK_WEBHOOK_URL_1",
                        "secret_env": "DINGTALK_SECRET_1",
                    },
                    {
                        "type": "wechat",
                        "webhook_url_env": "WECHAT_WEBHOOK_URL_1",
                    },
                ],
            }
        )

        self.assertIsInstance(notifier, MultiNotifier)
        self.assertIsInstance(notifier.notifiers[0], DingTalkNotifier)
        self.assertIsInstance(notifier.notifiers[1], WeChatNotifier)

    @patch.dict(
        "os.environ",
        {
            "WECHAT_WEBHOOK_URL_1": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=KEY",
        },
        clear=True,
    )
    @patch("builtins.print")
    def test_skips_invalid_notifier_in_multiple_config(self, _print):
        notifier = build_notifier(
            {
                "notifiers": [
                    {
                        "type": "dingtalk",
                        "webhook_url_env": "MISSING_DINGTALK_WEBHOOK_URL",
                        "secret_env": "MISSING_DINGTALK_SECRET",
                    },
                    {
                        "type": "wechat",
                        "webhook_url_env": "WECHAT_WEBHOOK_URL_1",
                    },
                ],
            }
        )

        self.assertIsInstance(notifier, WeChatNotifier)

    @patch.dict(
        "os.environ",
        {
            "WEBHOOK_URL": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=KEY",
        },
        clear=True,
    )
    def test_returns_wechat_notifier_when_selected_and_config_complete(self):
        notifier = build_notifier(
            {
                "notifier": {
                    "type": "wechat",
                },
            }
        )

        self.assertIsInstance(notifier, WeChatNotifier)

    @patch.dict("os.environ", {}, clear=True)
    @patch("builtins.print")
    def test_does_not_read_wechat_webhook_url_from_config(self, _print):
        notifier = build_notifier(
            {
                "notifier": {
                    "type": "wechat",
                    "webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=KEY",
                },
            }
        )

        self.assertIsInstance(notifier, ConsoleNotifier)

    @patch.dict("os.environ", {}, clear=True)
    def test_returns_console_notifier_when_selected(self):
        notifier = build_notifier({"notifier": {"type": "console"}})

        self.assertIsInstance(notifier, ConsoleNotifier)

    @patch.dict("os.environ", {}, clear=True)
    @patch("builtins.print")
    def test_returns_console_notifier_when_type_unknown(self, _print):
        notifier = build_notifier({"notifier": {"type": "email"}})

        self.assertIsInstance(notifier, ConsoleNotifier)

    @patch.dict("os.environ", {}, clear=True)
    @patch("builtins.print")
    def test_returns_console_notifier_when_notifiers_is_not_list(self, _print):
        notifier = build_notifier({"notifiers": {"type": "console"}})

        self.assertIsInstance(notifier, ConsoleNotifier)


if __name__ == "__main__":
    unittest.main()
