# Fund Limit Monitor (基金限额监控)

此项目用于监控指定 QDII 基金（如纳斯达克 100、标普 500）的单日申购限额，并通过个人 QQ 邮箱发送通知。

## 功能

- 爬取天天基金网的基金详情数据。
- 提取“交易状态”和“单日限额”信息。
- 实时抓取基金费率和指数基金跟踪误差；Markdown 日报保留“费率摘要”区，图片日报按指数表格合并展示限额、跟踪表现和费率。
- 基于当日年化跟踪误差和申购限额，生成 100 元纳斯达克 100 定投分配计划。
- 使用 SQLite 保存每日限额历史，并在限额变化时展示“旧值 -> 新值”。
- 生成日报并通过抽象通知通道推送。
- 默认通过个人 QQ 邮箱发送正文内嵌图片版日报，并保留完整文本内容。
- 保留 Gmail、企业微信 Markdown 和钉钉加签机器人作为兼容通知通道。

## 目录结构

```
.
├── config.json       # 通知通道和基金配置
├── monitor.py        # 主程序
├── notifier.py       # 通知通道实现
├── report_renderer.py # 图片日报渲染
├── history.db        # 自动生成的历史数据库
├── assets/fonts/     # 内置中文字体子集
└── requirements.txt  # Python依赖
```

## 安装与配置

1. **安装依赖**

   ```bash
   pip install -r requirements.txt
   ```

2. **配置通知**

   程序由 `config.json` 中的 `notifiers` 指定通知通道列表：

   - `qqmail`：个人 QQ 邮箱 SMTP（默认）
   - `gmail`：个人 Gmail SMTP（兼容）
   - `dingtalk`：钉钉机器人（兼容）
   - `wechat`：企业微信机器人（兼容）
   - `console`：仅打印到终端

   程序会按列表顺序逐个发送，同一条日报可以同时推送到多个目标。某个通知配置不完整时只跳过该项，不影响其他通知。

   邮箱地址、SMTP 授权凭据、Webhook 和签名密钥等值只从环境变量读取，`config.json` 只保存环境变量名。默认 `config.json` 只声明 QQ 邮箱；未提供完整 QQ 邮箱凭据时，程序会把报告打印到终端。

   **个人 QQ 邮箱**

   QQ 邮箱发件地址同时也是收件地址。登录 QQ 邮箱网页版，在 **设置 → 账号 → POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV 服务** 中开启 `IMAP/SMTP` 或 `POP3/SMTP` 服务，然后生成授权码。SMTP 登录必须使用授权码，不要使用 QQ 密码，也不要把授权码写入仓库。

   ```json
   {
       "notifiers": [
           {
               "type": "qqmail",
               "address_env": "QQ_EMAIL_ADDRESS",
               "auth_code_env": "QQ_EMAIL_AUTH_CODE"
           }
       ],
       "investment_plan_amount": 100,
       "funds": [
           ...
       ]
   }
   ```

   ```bash
   export QQ_EMAIL_ADDRESS="123456789@qq.com"
   export QQ_EMAIL_AUTH_CODE="your-smtp-authorization-code"
   ```

   如果不配置环境变量名，默认读取 `QQ_EMAIL_ADDRESS` 和 `QQ_EMAIL_AUTH_CODE`。程序会在认证前自动移除授权码中的空白字符。

   程序固定使用 `smtp.qq.com:465` 和 SSL，不需要配置 SMTP 主机或端口。

   **QQ 邮箱图片日报**

   QQ 邮件会直接读取本地 PNG，以 CID 图片形式显示在 HTML 正文中；完整 Markdown 报告作为纯文本降级内容。指定的图片不存在或不可读时，邮件发送失败并让 CI 报错。

   本项目继续将 PNG 保存到 `reports/` 并由 GitHub Actions 公开归档：

   ```bash
   export REPORT_IMAGE_BASE_URL="https://raw.githubusercontent.com/OWNER/REPO/main/reports"
   export REPORT_IMAGE_DIR="reports"
   ```

   QQ 邮箱发送只依赖 payload 中的本地 `image_path`，不依赖 `REPORT_IMAGE_BASE_URL`；该 URL 继续用于公开归档链接和兼容通知通道。直接运行 `python3 monitor.py` 时，QQ 邮箱通知器也会自动生成本地 PNG。

   图片渲染默认使用项目内置字体 `assets/fonts/FundReportSans-Subset.otf`。如需替换字体：

   ```bash
   export REPORT_FONT_PATH="/path/to/font.otf"
   ```

   **历史数据**

   程序使用 `history.db` 保存每日限额快照，表中每个自然日只保留一条记录。生成日报时会与数据库中早于当天的最近一条记录对比；如果限额发生增加或减少，Markdown 和图片日报都会展示类似 `100元 -> 500元 ↑` 的变化。

   旧版 `history.json` 不再读取，也不会迁移。切换到 SQLite 后首次运行数据库为空，因此当日报告不会显示历史变化。

   **费率摘要**

   日报会从天天基金基金档案费率页实时抓取每只基金的费率信息，例如：

   ```text
   https://fundf10.eastmoney.com/jjfl_270042.html
   ```

   Markdown 报告末尾会新增“费率摘要”区；图片日报会按纳斯达克 100、标普 500 生成两张表格，合并展示名称、价差信息、跟踪表现、运作费率、申购优惠、赎回费率。当前展示口径为：

   - 跟踪表现：从天天基金特色数据页的“指数基金指标”抓取年化跟踪误差、同类平均跟踪误差和数据日期，展示为 `年化1.11% / 同类2.01% / 05-28`。非指数基金或没有该指标时显示 `--`。
   - 运作费用：管理费率、托管费率、销售服务费率，以及可解析百分比的年度合计。
   - 申购费率：最低金额档的天天基金优惠费率，优先取“银行卡购买”列。
   - 赎回费率：第一条和最后一条持有期档位。

   若某只基金费率页请求失败或结构异常，该基金会显示“费率获取失败”，不会影响限额日报生成和通知发送。
   若跟踪表现请求失败或结构异常，该基金会显示“跟踪误差获取失败”，不会写入限额历史，也不会影响日报生成和通知发送。

   **定投计划**

   日报会单独生成“纳指100定投计划”表，金额由 `config.json` 的 `investment_plan_amount` 配置，默认 100 元。规则为：只选择纳斯达克 100 基金中当前可申购且有年化跟踪误差数据的品种，按年化跟踪误差从低到高排序；每只基金最多投到当日申购限额，额度不够时继续选择下一只，直到配置金额用完或没有可执行基金。
   程序会把最终执行计划保存到 `history.db`，并在下次生成日报时比较“顺序、基金代码、定投金额”。若任一项发生变化，Markdown 和图片日报都会在“纳指100定投计划”表头显示“策略变更”强提醒；首次没有历史基线时只保存当前计划，不提醒。

   **兼容通道：Gmail**

   原有 Gmail 通知器仍可通过 `type: "gmail"` 显式启用，默认读取 `GMAIL_ADDRESS` 和 `GMAIL_APP_PASSWORD`。GitHub Actions 默认工作流不再注入这两个变量。

   **兼容通道：企业微信**

   ```json
   {
       "notifiers": [
           {
               "type": "wechat",
               "webhook_url_env": "WEBHOOK_URL"
           }
       ],
       "funds": [
           ...
       ]
   }
   ```

   ```bash
   export WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY"
   ```

   如果不配置 `webhook_url_env`，默认读取 `WEBHOOK_URL`。

   **兼容通道：钉钉**

   钉钉加签机器人仍然可用，但不再出现在默认配置和 GitHub Actions 中：

   ```json
   {
       "notifiers": [
           {
               "type": "dingtalk",
               "webhook_url_env": "DINGTALK_WEBHOOK_URL",
               "secret_env": "DINGTALK_SECRET"
           }
       ],
       "funds": [
           ...
       ]
   }
   ```

   ```bash
   export DINGTALK_WEBHOOK_URL="https://oapi.dingtalk.com/robot/send?access_token=YOUR_TOKEN"
   export DINGTALK_SECRET="SECxxxxxxxxxxxxxxxx"
   ```

   同一个 `notifiers` 数组也可以配置多个通道；程序会按列表顺序逐一发送。多个同类机器人应分别使用不同的环境变量名。

   **终端打印**

   ```json
   {
       "notifiers": [
           {
               "type": "console"
           }
       ],
       "funds": [
           ...
       ]
   }
   ```

   旧的单个 `notifier` 对象仍然兼容；新配置建议使用 `notifiers` 数组。

   您也可以在该文件中调整需要监控的基金代码。

## 运行

**手动运行：**

```bash
python3 monitor.py
```

正常情况下，您会在配置的 QQ 邮箱收件箱收到来自自己的日报邮件；如果凭据未配置完整，报告会打印到终端。

**两阶段生成并发送：**

```bash
python3 monitor.py --prepare-report --report-output .report/latest.json
python3 monitor.py --send-report .report/latest.json
```

该模式适合 CI：先生成并提交 `reports/*.png` 和 `history.db`，再把同一张本地 PNG 内嵌到 QQ 邮件中发送。

**重新生成字体子集：**

修改基金列表或图片文案后，运行：

```bash
python3 scripts/build_font_subset.py
```

字体来源为 Noto Sans CJK SC，许可证见 `assets/fonts/OFL.txt`。

**运行测试：**

```bash
python3 -m unittest test_monitor.py test_report_renderer.py test_notifier.py
python3 -m py_compile monitor.py notifier.py report_renderer.py test_notifier.py test_report_renderer.py test_monitor.py
```

## GitHub Actions 自动运行

本项目已配置 GitHub Actions workflow，每天可自动运行、生成图片日报、更新历史记录并发送通知。

它可以手动触发（Workflow dispatch），也会在每天北京时间 13:30 (UTC 05:30) 自动运行。

先登录 [QQ 邮箱](https://mail.qq.com/)，在账号设置中开启 `IMAP/SMTP` 或 `POP3/SMTP` 服务并生成授权码。QQ 邮箱 SMTP 使用 `smtp.qq.com`、465 和 SSL；服务器参数和授权码用法可参考[腾讯云官方 SMTP 配置文档](https://docs.cloudbase.net/en/authentication-v2/method/email-login)。

然后在仓库 **Settings -> Secrets and variables -> Actions** 中添加：

- `QQ_EMAIL_ADDRESS`：完整个人 QQ 邮箱地址，例如 `123456789@qq.com`
- `QQ_EMAIL_AUTH_CODE`：QQ 邮箱生成的 SMTP 授权码，不是 QQ 密码

工作流只读取这两个 QQ 邮箱 Secret，不再读取 Gmail 或其他通知通道凭据。添加后建议通过 **Workflow dispatch** 手动触发一次，确认邮件发件人和收件人相同，正文显示完整日报图片，并可查看纯文本降级内容。

## 注意事项

- 脚本依赖天天基金网的页面结构，如果网站改版可能会失效。
- 请适度控制抓取频率，避免被封禁 IP。
