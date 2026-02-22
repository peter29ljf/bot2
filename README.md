# Polymarket 跟单交易机器人

基于 Polymarket 公共 API 的自动跟单交易系统，支持监控目标钱包活动并自动复制交易。使用 JSON 文件存储，无需数据库。

## 主要功能

- **自动跟单**：监控目标钱包交易活动，按比例自动复制
- **交易模式**：支持只跟买、只跟卖、买卖都跟
- **滑点保护**：检查订单簿深度，过滤滑点过大的交易
- **风险控制**：每日交易上限、日亏损上限、最小/最大跟单金额
- **时间窗口**：仅跟单 `interval+1` 秒内的新交易，超时标注为「错过」
- **Web 控制面板**：配置参数、持仓状况、目标活动列表、当日盈亏

## 技术栈

- **后端**：Python 3.11 + Flask
- **前端**：原生 HTML + CSS + JavaScript
- **API**：Polymarket 公共 API（activity、book、midpoint）+ 私有交易 API
- **存储**：本地 JSON 文件（activity_list.json、position.json）

## 外部 API

| 用途     | 方法 | URL                                              |
|----------|------|--------------------------------------------------|
| 活动查询 | GET  | https://data-api.polymarket.com/activity         |
| 订单簿   | GET  | https://clob.polymarket.com/book                 |
| 中间价   | GET  | https://clob.polymarket.com/midpoint            |
| 发送交易 | POST | 私有 API（需自行配置 trade_api_url）             |

## 安装说明

### 前置条件

- Python 3.11+
- 交易 API 服务（用于执行下单）

### 安装步骤

1. 克隆仓库

```bash
git clone https://github.com/peter29ljf/bot2.git
cd bot2
```

2. 安装依赖

```bash
pip install -r requirements.txt
```

3. 配置

复制 `data/config.example.json` 为 `data/config.json`，并修改配置：

```json
{
  "trading_wallet": "0x...",
  "target_wallet": "0x...",
  "percentage": 1.0,
  "interval": 5,
  "max_trades": 10,
  "slippage_protection": 0.05,
  "min_amount": 2.0,
  "max_amount": 500.0,
  "trade_mode": "buy",
  "max_daily_loss": 200.0,
  "trade_api_url": "http://your-trade-api/trade",
  "web_host": "0.0.0.0",
  "web_port": 8000
}
```

4. 启动

```bash
python main.py
```

5. 访问控制面板

打开浏览器访问 `http://localhost:8000`

## 配置参数说明

| 参数                | 类型   | 默认值 | 说明                          |
|---------------------|--------|--------|-------------------------------|
| trading_wallet      | string | -      | 交易钱包地址（跟单执行方）     |
| target_wallet       | string | -      | 监控目标钱包地址               |
| percentage          | float  | 1.0    | 跟单比例（0.1 = 10%）          |
| interval            | int    | 5      | 检查间隔（秒）                 |
| max_trades          | int    | 10     | 每日最大跟单次数               |
| slippage_protection | float  | 0.05   | 滑点保护（5%）                 |
| min_amount          | float  | 2.0    | 最小跟单金额（USD）            |
| max_amount          | float  | 500.0  | 最大跟单金额（USD）            |
| trade_mode          | string | buy    | 交易模式：buy/sell/both        |
| max_daily_loss      | float  | 200.0  | 日亏损上限（USD）              |
| trade_api_url       | string | -      | 交易 API 地址                  |

## 项目结构

```
bot2/
├── main.py              # 入口
├── requirements.txt     # 依赖
├── README.md
├── data/
│   ├── config.json      # 配置（不提交）
│   ├── config.example.json
│   ├── activity_list.json
│   └── position.json
├── src/
│   ├── config.py        # 配置管理
│   ├── storage.py       # JSON 存储
│   ├── api_client.py    # API 客户端
│   ├── trader.py        # 交易逻辑
│   └── web.py           # Flask Web
├── templates/
│   └── index.html       # 前端页面
└── logs/                # 日志
```

## 滑点检查逻辑

1. 计算下单价格：`order_price = target_price × (1 + slippage_protection)`
2. 获取订单簿 asks，过滤 `ask_price >= order_price`
3. 汇总可用深度 `available_depth`
4. 若 `available_depth < follow_size`，则 `follow_size = available_depth`

## 注意事项

- **风险警告**：交易存在风险，请理解逻辑后再使用
- **交易 API**：需自行部署或使用可用的交易 API 服务
- **持续运行**：机器人需持续运行才能实时跟单

## 许可证

MIT License
