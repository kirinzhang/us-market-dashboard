# 美股阶段仪表盘

帮助判断当下美股的**流动性**和**主线叙事**，给出“进攻 / 谨慎持有 / 防守持有 / 换主线 / 清仓”的阶段建议。仅供参考，不构成投资建议。

- 页面：<https://kirinzhang.github.io/us-market-dashboard/>
- 每个交易日更新两次：美东 05:30（开盘前 4 小时）和 17:00（收盘后 1 小时）
- 叙事开关、流动性开关变色或硬性风控开关触发时发邮件
- 全部使用免费数据：FRED（宏观）、Yahoo Finance（行情、期权）、维基百科（标普 500 成分股）

## 页面内容

| 区块 | 内容 |
| --- | --- |
| 阶段 | 叙事开关（你持有的主线是否还在走强）+ 流动性开关 → 阶段与参考仓位；4 个硬性风控开关 |
| 宏观流动性 | 净流动性（美联储总资产 − TGA − 逆回购）、准备金、利率曲线、实际利率、信用利差、VIX 期限结构、MOVE、美元、油、金、市场宽度 |
| 资金轮动 | 16 个主题篮子的超额收益排行、拥挤度、成交额占比变化；相对轮动图 RRG；行业板块与风格比值 |
| 关注标的 | AI 核心股、杠杆 ETF、大盘 ETF 的涨跌和均线位置，点击看 K 线；SPY/QQQ/NVDA 期权快照 |
| 日历 | 未来 14 天的 FOMC、CPI、非农和关注股财报 |
| 信号日志 | 每次状态变化的记录 |

## 首次设置（只需做一次）

1. **开启 Pages**：仓库 Settings → Pages → Build and deployment → Source 选 **GitHub Actions**。
2. **配置邮件**（Settings → Secrets and variables → Actions → New repository secret）：

   | Secret | 说明 |
   | --- | --- |
   | `SMTP_USER` | 发件邮箱，例如你的 Gmail 地址 |
   | `SMTP_PASSWORD` | Gmail 需要用[应用专用密码](https://myaccount.google.com/apppasswords)（要先开启两步验证），不是登录密码 |
   | `MAIL_TO` | 收件邮箱，多个用逗号分隔 |
   | `SMTP_HOST` / `SMTP_PORT` | 可选，默认 `smtp.gmail.com` / `465`。QQ 邮箱为 `smtp.qq.com` / `465`，密码填授权码 |
   | `MASSIVE_API_KEY` | **建议填**。美股和 ETF 日线的主数据源（Massive，原 Polygon.io，Stocks Starter $29/月，不限调用次数）。不填时全部用 yfinance |
   | `FRED_API_KEY` | **强烈建议填**。GitHub Actions 的机器经常连不上 FRED 的公开 CSV，不填时净流动性、信用利差、SOFR 等会缺失（美债收益率会自动改用财政部官网）。[免费申请](https://fred.stlouisfed.org/docs/api/api_key.html) |

3. **手动跑第一次**：Actions → “更新数据并部署” → Run workflow。几分钟后页面就有数据，并会收到一封“首次运行”邮件。

## 修改配置

不需要改代码：

- `config/universe.yaml`：关注个股、杠杆 ETF、主题篮子成分、你当前持有的主线（`holding_themes`）
- `config/settings.yaml`：各开关的阈值（初始值，待回测校准）
- `config/events.yaml`：宏观事件日期和休市日，每年初补充下一年

## 判断规则

**流动性开关**（3 个软指标 + 4 个硬性开关）

- 软指标：净流动性 13 周下降；高收益债利差 20 日走阔 > 0.10pp；美元指数 20 日涨幅 > 1.5%
- 硬性开关：HY 利差 20 日走阔 ≥ 1pp；VIX/VIX3M > 1 连续 3 天；标普跌破 200 日线且站上 50 日线比例 < 30%；美元/日元 5 日跌 ≥ 4%
- 红：任一硬性开关触发，或 3 个软指标全部恶化；黄：2 个软指标恶化；其余为绿

**叙事开关**（看 `holding_themes` 的第一个主题）

- 红：强度排名跌出前 5 连续 10 天，且主题指数跌破 50 日线，且成交额占比 20 日下降
- 黄：跌出前 5 连续 5 天，或跌破 50 日线，或拥挤度 ≥ 0.85
- 主题强度 = 20 日与 60 日相对 SPY 超额收益的平均

**阶段**

| 叙事 | 流动性 | 阶段 | 参考仓位 |
| --- | --- | --- | --- |
| 绿 | 绿 | 进攻：持有，允许在主线内加仓 | 80–100% |
| 非红（含黄） | 非红（含黄） | 谨慎持有：不追高，加仓只加回调 | 60–80% |
| 非红 | 红 | 防守持有：不加仓，先减杠杆 ETF 和期权 | 40–60% |
| 红 | 非红 | 换主线：减旧主线，看 RRG 领先/改善象限 | 40–60% |
| 红 | 红 | 清仓 | 0–20% |

## 本地运行

```bash
pip install -r requirements.txt pytest
python -m pytest -q                                   # 用合成数据测试，不联网
PYTHONPATH=src python -m dashboard.build --force --no-email
cd site && python -m http.server 8000                 # 打开 http://localhost:8000
```

## 已知限制

- Yahoo Finance 是非官方接口，偶尔会限流或缺数据；缺失的部分会在页面底部列出，不影响其他部分。
- FRED 的部分 ICE 信用利差序列只提供近几年历史，分位数按可得历史计算。
- 免费期权数据是收盘快照，精度不如付费源。
