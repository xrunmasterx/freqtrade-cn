# freqtrade-cn

`freqtrade-cn` 是一个以 Docker 为主要运行入口的本地 Freqtrade 策略研究、回测和
DRY-RUN 观察栈。根仓库负责运行时配置和编排，后端、前端和公共策略分别由 Git
submodule 固定到精确提交。

当前正式兼容服务只有三个：

| 服务 | 用途 | 默认端口 | 默认模式 | 默认策略 |
|---|---|---:|---|---|
| `freqtrade` | Spot DRY-RUN 与看盘 | `8081` | Bitget Spot | `SampleStrategy` |
| `freqtrade-futures` | BTC/ETH Futures 共用钱包 DRY-RUN | `8082` | OKX Isolated Futures | `PriceFlowParticipationFreshnessStrategy` |
| `freqtrade-research` | 标准回测、安全分析和 A 股本地研究 | `8083` | Webserver only | 启动时不预选策略 |

> **安全边界：**仓库强制 `dry_run=true`。本文档不授权实盘、交易所写操作、停止现有
> Bot、轮换正在使用的凭据、删除状态或启动生产 Supervisor。默认 Futures 策略依赖本地
> cross-venue sidecar，且没有实时更新器；它是研究/Shadow 默认值，不是生产实盘声明。

## 给本地配置 AI 的强制规则

其他用户可以让 AI 阅读本 README 后配置新机器。AI 必须遵守以下规则：

1. 从仓库根目录工作，并先读取 `AGENTS.md`。涉及开发计划时再读取
   `docs/superpowers/README.md`；涉及图表时还要读取 `docs/chart-data-source-rules.md`。
2. 使用普通 recursive clone。不要把缺失或未初始化的 submodule 当作空目录继续配置。
3. 不覆盖已有 `.env`、本地 `config*.json`、秘密文件、SQLite、回测结果或行情数据。
   `bootstrap_runtime.py init` 是幂等的；发现已有文件时应保留并做语义比较。
4. 只编辑被 Git 忽略的本地运行配置；不要把真实配置写回 `*.example.json`。
5. API 密码、JWT 和 WebSocket token 必须保存在 `ft_userdata/secrets/` 的固定文件中。
   不得把秘密写入 JSON、环境变量、命令参数、日志、聊天、截图或提交。
6. 本地运行配置中的 `api_server.password`、`jwt_secret_key` 和 `ws_token` 必须保持
   `__SET_VIA_SECRET_FILE__`；入口脚本会从秘密文件注入真实值。
7. 默认保持 `dry_run: true`，交易所 `key`、`secret` 和 `password` 保持空字符串。
   不得因为用户说“启动”而推断出实盘授权。
8. 先确定要运行的服务、端口、代理和数据是否齐全，再做最小配置。不要顺带创建新
   Compose 服务、修改正式策略或启用未支持的市场。
9. Futures 启动前必须验证两份 E10 sidecar。缺失、过期或来源不明时停止并报告，不能
   用空文件、伪造列或关闭校验来绕过。
10. 使用 `tools/compose_runtime.py` 启动三个正式服务。原始 `docker compose up` 只用于
    明确的本地开发/数据准备，不能作为已审阅运行时证据。
11. 启动前运行本文的全部配置验证。启动后报告服务名、端口、DRY-RUN 状态、策略和
    数据覆盖；绝不报告秘密内容。
12. 停止服务、轮换凭据、恢复数据库、删除文件或状态前必须取得针对该服务和维护窗口的
    明确授权。

## 项目结构

```text
freqtrade-cn/
├── freqtrade/                 # 后端 submodule：Freqtrade、API、回测、Platform
├── frequi/                    # 前端 submodule：Vue/FreqUI
├── freqtrade-strategies/      # 公共示例策略 submodule
├── ft_userdata/user_data/     # 受控模板、项目策略、A 股样例研究数据
├── ft_userdata/runtime/       # 本机状态、日志、行情、数据库、回测结果（忽略）
├── ft_userdata/secrets/       # 本机秘密文件（忽略）
├── ops/                       # 运行时 manifest、安全策略和平台策略
├── tools/                     # bootstrap、验证、正式启动和研究工具
├── docs/                      # 运维、数据源规则、设计和验收记录
└── docker-compose.yml         # 根编排契约
```

## 前置条件

最低要求：

- Git，支持 submodule。
- Python `>=3.11`。仅使用 Docker 运行时也需要 Python 执行根目录的安全 wrapper。
- Docker Desktop 或 Docker Engine，以及 Compose v2（`docker compose`）。
- Windows 建议 PowerShell 7；Linux/macOS 可使用对应 shell。
- 如果模板保留代理配置，宿主机必须提供对应 HTTP CONNECT/HTTP 代理。
- 默认端口 `8081`、`8082`、`8083` 必须可用；平台只读控制面预留 `8090`。

先验证工具：

```powershell
git --version
python --version
docker version
docker compose version
```

在 Linux/macOS 上，如果 `python` 不指向 Python 3，请将后续命令中的 `python` 替换为
`python3`。

## 新机器配置：从零开始

### 1. 克隆并固定 submodule

```powershell
git clone --recurse-submodules https://github.com/xrunmasterx/freqtrade-cn.git
Set-Location freqtrade-cn
git submodule update --init --recursive
git submodule status --recursive
```

`git submodule status --recursive` 的每一行都应以空格开头。`-` 表示未初始化，`+` 表示
工作树提交与根仓库固定指针不一致；出现任一情况都不能继续正式启动。

POSIX shell 的复制命令是：

```sh
cp .env.example .env
```

Windows PowerShell 使用：

```powershell
Copy-Item .env.example .env
```

### 2. 初始化本机配置、秘密和状态

从根目录运行：

```powershell
python tools/bootstrap_runtime.py init
python tools/bootstrap_runtime.py migrate-research-paths
python tools/bootstrap_runtime.py sanitize-api-configs
```

`init` 会：

- 把缺失的三个本地配置从对应模板复制出来；
- 为三个服务生成相互独立的 API password、JWT secret 和 WebSocket token；
- 生成平台 PostgreSQL/API 的本地秘密；
- 创建每个服务独立的状态、日志、数据和回测目录；
- 把当前宿主机 UID/GID 合并进 `.env`，并生成忽略的 Compose identity override；
- 设置并验证 Windows owner-only ACL 或 POSIX 所有权/权限；
- 保留所有已经存在的配置和秘密，不自动用新模板覆盖。

`migrate-research-paths` 只迁移已知的旧 Research 路径；自定义路径会在写入前被拒绝。
`sanitize-api-configs` 会把三个本地配置的 API 秘密字段恢复为固定 sentinel，而不是删除
秘密文件。

### 3. 识别模板和本地运行配置

| 服务 | 受版本控制的模板 | AI 可编辑的本地文件 | 状态根目录 |
|---|---|---|---|
| Spot | `ft_userdata/user_data/config.example.json` | `ft_userdata/user_data/config.json` | `ft_userdata/runtime/freqtrade` |
| Futures | `ft_userdata/user_data/config.volatility.futures.example.json` | `ft_userdata/user_data/config.volatility.futures.json` | `ft_userdata/runtime/freqtrade-futures` |
| Research | `ft_userdata/user_data/config.research.example.json` | `ft_userdata/user_data/config.research.json` | `ft_userdata/runtime/freqtrade-research` |

这三个本地文件都被 `.gitignore` 排除。`init` 不会更新已经存在的文件，因此升级仓库后，
AI 必须比较本地文件与模板，只合并明确需要的新字段；禁止直接覆盖。

AI 应把模板和本地文件解析为 JSON，只比较键、类型和本文列出的必要值。不要对可能包含
历史交易所凭据的本地配置执行或展示原始文本 diff；即使项目要求凭据为空，也不能假设
一台已有机器从未被人工修改过。

## 通用配置

### 端口

`.env.example` 的默认值是：

```dotenv
FT_UI_PORT=8081
FT_FUTURES_UI_PORT=8082
FT_RESEARCH_UI_PORT=8083
```

只在忽略的 `.env` 中修改端口。三个端口必须是不同且未被占用的本地 TCP 端口。
Compose 固定绑定 `127.0.0.1`，不要为了“方便访问”改成 `0.0.0.0`。

Windows 检查端口：

```powershell
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
  Where-Object LocalPort -In 8081,8082,8083,8090 |
  Select-Object LocalAddress,LocalPort,OwningProcess
```

### 宿主机代理

三个模板默认把 CCXT 代理设置为：

```text
http://host.docker.internal:12639
```

AI 必须先询问或检测用户是否真的使用这个代理：

- Docker Desktop 访问宿主机代理使用 `host.docker.internal:<port>`。
- 在原生 Python 虚拟环境中访问宿主机代理通常使用 `127.0.0.1:<port>`。
- 如果代理端口不是 `12639`，只修改本地配置中
  `exchange.ccxt_config.httpsProxy` 和 `wsProxy`。
- 如果用户不需要代理，删除本地配置中的这两个键；不要填写一个不存在的代理地址。
- 不要把代理认证信息提交到仓库或输出到日志。

### API 登录秘密

每个服务有独立秘密目录：

```text
ft_userdata/secrets/freqtrade/
ft_userdata/secrets/freqtrade-futures/
ft_userdata/secrets/freqtrade-research/
```

每个目录包含：

```text
api_password
jwt_secret_key
ws_token
```

默认 UI 用户名来自模板，为 `freqtrader`。仓库没有默认密码；`api_password` 文件中的值
是本机生成的登录密码。操作员应通过本机受保护的秘密管理方式读取并输入它。AI 不得把
该值回显到终端、聊天或日志；如果当前交互无法安全传递秘密，应让操作员自行完成登录。

### DRY-RUN 和交易所凭据

默认公开行情和 DRY-RUN 不需要交易所私钥。保持：

```json
"dry_run": true,
"key": "",
"secret": "",
"password": ""
```

`ops/config/trading-safety.json` 会作为第二份配置加载并再次强制 `dry_run=true`。不要修改
这个受版本控制的安全策略来启用实盘。

## Spot 配置

本地文件：`ft_userdata/user_data/config.json`。

默认值：

- Exchange：Bitget。
- Trading mode：Spot。
- Pair whitelist：`BTC/USDT`、`ETH/USDT`。
- Timeframe：`1m`。
- Strategy：Compose/manifest 固定为 `SampleStrategy`。
- Wallet：DRY-RUN `10000 USDT`。

AI 可以在本地配置中修改支持的交易所、pair whitelist、stake 和代理，但必须保持
DRY-RUN、空交易所凭据和 API sentinel。修改后必须重新运行全部验证。

正式策略由 `docker-compose.yml` 和 `ops/runtime-services.json` 的启动参数拥有，不由 JSON
中的临时 `strategy` 字段拥有。要更改正式默认策略，需要一次受测试和评审的代码变更；
不要在新机器配置过程中私自修改 manifest 或 Compose。

## Futures：BTC/ETH E10 共用钱包配置

本地文件：`ft_userdata/user_data/config.volatility.futures.json`。

必须满足：

```text
bot_name: freqtrade-cn-okx-price-flow-futures
dry_run: true
trading_mode: futures
margin_mode: isolated
max_open_trades: 2
exchange.name: okx
exchange.ccxt_config.options.defaultType: swap
pair_whitelist:
  - BTC/USDT:USDT
  - ETH/USDT:USDT
cross_venue_sidecar_dir: /freqtrade/state/data-price-flow-deep-5y/cross-venue
```

一个 `freqtrade-futures` 服务、一个状态根目录、一个 `trades.sqlite` 和同一 pair whitelist
构成 BTC/ETH 共用钱包。不要为了两个交易对复制第二个服务。

实际可加载策略类是：

```text
PriceFlowParticipationFreshnessStrategy
```

它直接继承研究文件动态生成的 `PriceFlowEventAdaptive10Strategy`。文件
`PriceFlowEventAdaptiveResearchStrategy.py` 是 E01–E20 研究候选容器，并不存在同名的
可加载 `PriceFlowEventAdaptiveResearchStrategy` 类。AI 不得把文件名误写进 `--strategy`。

### E10 sidecar 是启动前硬前提

宿主机目录必须是：

```text
ft_userdata/runtime/freqtrade-futures/data-price-flow-deep-5y/cross-venue/
```

至少验证：

```text
BTC_USDT_USDT-15m-cross-venue.feather
ETH_USDT_USDT-15m-cross-venue.feather
manifest.json
```

PowerShell 检查：

```powershell
$SidecarRoot = 'ft_userdata/runtime/freqtrade-futures/data-price-flow-deep-5y/cross-venue'
$Required = @(
  'BTC_USDT_USDT-15m-cross-venue.feather',
  'ETH_USDT_USDT-15m-cross-venue.feather',
  'manifest.json'
)
$Required | ForEach-Object {
  $Path = Join-Path $SidecarRoot $_
  [pscustomobject]@{ Path = $Path; Exists = Test-Path -LiteralPath $Path }
}
```

所有 `Exists` 必须为 `True`。策略在 sidecar 缺失时会抛出 `FileNotFoundError`；不得捕获后
继续运行。还应检查 manifest 的数据覆盖范围包含计划观察/回测窗口。当前工具没有实时
sidecar updater，历史文件不能证明今天的跨交易所数据可用。

sidecar 不进入 Git。优先从已校验、具有 manifest 和校验信息的受信任本地研究产物复制。
从零生成会下载大量公开历史数据，并要求后端依赖、OKX Futures/Funding 数据以及可用的
Deribit HTTP CONNECT 代理；AI 在没有明确的数据窗口、存储预算和网络许可时不得自动执行。

经授权从零准备时，先安装下文的后端虚拟环境，再把 OKX 数据下载到固定数据根：

```powershell
docker compose --profile trading run --rm --no-deps freqtrade-futures download-data `
  --config /freqtrade/config/runtime.json `
  --user-data-dir /freqtrade/state `
  --datadir /freqtrade/state/data-price-flow-deep-5y `
  --trading-mode futures `
  --pairs BTC/USDT:USDT ETH/USDT:USDT `
  --timeframes 15m 1h `
  --candle-types futures funding_rate `
  --timerange <YYYYMMDD-YYYYMMDD>
```

确认以下前置文件位于数据根的 `futures/` 子目录：

```text
BTC_USDT_USDT-15m-futures.feather
ETH_USDT_USDT-15m-futures.feather
BTC_USDT_USDT-1h-funding_rate.feather
ETH_USDT_USDT-1h-funding_rate.feather
```

再查看并执行 cross-venue 工具。当前 Deribit 下载路径要求 HTTP CONNECT 代理：

```powershell
./freqtrade/.venv/Scripts/python tools/prepare_price_flow_cross_venue.py --help
./freqtrade/.venv/Scripts/python tools/prepare_price_flow_cross_venue.py `
  --data-root ft_userdata/runtime/freqtrade-futures/data-price-flow-deep-5y `
  --start <YYYY-MM-DD> `
  --end <YYYY-MM-DD> `
  --proxy-host 127.0.0.1 `
  --proxy-port 12639
```

Linux/macOS 的虚拟环境解释器路径是 `./freqtrade/.venv/bin/python`。生成完成后重新执行
sidecar 文件和覆盖范围检查。不要提交下载数据、raw archives、sidecar 或 manifest。

## Research 和 A 股本地研究配置

本地文件：`ft_userdata/user_data/config.research.json`。

必须保留：

```text
strategy_path: /freqtrade/user_data/strategies
research_input_root: /freqtrade/user_data/research_data
research_bots[0].id: a-share-local
research_bots[0].market: a_share
research_bots[0].data_source.type: local_csv
research_bots[0].data_source.root: a_share
```

Research 配置中的 `exchange` 是 Freqtrade Webserver 兼容配置，不是 A 股券商连接。不要在
这里写入券商凭据。A 股 chart/backtest 请求只读取本地文件，不会在 API 请求期间调用
AkShare、东方财富或其他远端提供商。

OHLCV 文件目录：

```text
ft_userdata/user_data/research_data/a_share/
```

命名和列契约：

```text
{instrument}-{timeframe}.csv
date,open,high,low,close,volume
```

支持的原始周期是 `1m`、`5m`、`15m`、`30m`、`60m`、`1d`。示例：

```text
600519.SH-1d.csv
688017.SH-1m.csv
```

市场日历、日状态和侧数据位于：

```text
ft_userdata/user_data/research_data/a_share_meta/calendar/trade_dates.csv
ft_userdata/user_data/research_data/a_share_meta/status/daily_status.csv
ft_userdata/user_data/research_data/a_share_meta/features/
ft_userdata/user_data/research_data/a_share_meta/events/
ft_userdata/user_data/research_data/a_share_meta/documents/
```

如需采集新的 A 股数据，安装 `research_ashare` extra 后使用：

```powershell
./freqtrade/.venv/Scripts/python tools/download_a_share_research_data.py `
  --config ft_userdata/user_data/config.research.json `
  --bot-id a-share-local `
  --instruments 600519.SH 688017.SH `
  --timeframes 1m 5m 15m 30m 60m 1d `
  --adjustment raw
```

新下载的数据默认不会自动获得发布授权。运行 `git status --short`，确保没有把本机数据、
manifest 或提供商产物意外加入提交。

`/research` 是简化研究路径，目前只支持 `sma_cross` 和
`sma_cross_feature_filter`，不是权威标准 Freqtrade 回测。权威回测使用 `/backtest`。

详细数据规则：

- [A 股研究数据](docs/a-share-research-data.md)
- [A 股市场正确性](docs/a-share-market-correctness.md)
- [A 股侧数据](docs/a-share-side-data.md)

## Platform Control 边界

Platform Control 使用 `8090`，具有市场目录、Runtime Registry 和规范化数字资产蜡烛查询
后端，但它不是普通本地快速启动的一部分。当前生产 Supervisor 和 Platform UI cutover
仍未启用。

- `tools/bootstrap_runtime.py init` 会准备平台本地秘密。
- `tools/compose_runtime.py` 对 `platform` 只开放配置渲染，不开放生产 start/stop。
- 不要使用原始 `docker compose up platform-control` 绕过评审门。
- 需要平台开发或验收时，严格按照
  [Platform Control 运维文档](docs/operations/platform-control.md) 操作。

## 启动前验证

完成任何本地配置修改后，从根目录依次运行：

```powershell
python tools/bootstrap_runtime.py verify
python tools/runtime_contract.py --check-configs-only
python tools/compose_runtime.py --profile trading --profile research config --quiet
git submodule status --recursive
git status --short
```

期望结果：

- `verify` 退出码为 `0`，且不打印秘密。
- Runtime contract 输出 `runtime contract: OK` 或以退出码 `0` 结束。
- Compose 渲染退出码为 `0`。
- Submodule 没有 `-` 或 `+` 前缀。
- Git 状态中没有本机配置、秘密、数据库、日志、sidecar 或下载数据。
- 正式 `up` 前根仓库及 submodule 必须与已提交身份一致；正式构建不会包含未提交代码。

如果验证失败，不要绕过脚本直接运行 Compose。修正第一条错误后重新执行完整验证。

## 启动服务

只启动用户明确要求的服务。

### Spot

```powershell
python tools/compose_runtime.py up freqtrade
python tools/compose_runtime.py ps freqtrade
python tools/compose_runtime.py logs --tail 100 freqtrade
```

入口：

- 看盘：<http://127.0.0.1:8081/graph>
- 交易状态：<http://127.0.0.1:8081/trade>

### Futures

先通过 E10 sidecar 检查，再运行：

```powershell
python tools/compose_runtime.py up freqtrade-futures
python tools/compose_runtime.py ps freqtrade-futures
python tools/compose_runtime.py logs --tail 100 freqtrade-futures
```

入口：

- 看盘：<http://127.0.0.1:8082/graph>
- 交易状态：<http://127.0.0.1:8082/trade>

页面必须明确显示 Futures、DRY-RUN、`freqtrade-futures` 身份和
`PriceFlowParticipationFreshnessStrategy`。不能用 `8081` 的 Spot 页面代替 Futures 验收。

### Research / Backtest

```powershell
python tools/compose_runtime.py up freqtrade-research
python tools/compose_runtime.py ps freqtrade-research
python tools/compose_runtime.py logs --tail 100 freqtrade-research
```

入口：

- 权威标准回测：<http://127.0.0.1:8083/backtest>
- Lookahead Analysis：<http://127.0.0.1:8083/lookahead_analysis>
- Recursive Analysis：<http://127.0.0.1:8083/recursive_analysis>
- A 股本地研究：<http://127.0.0.1:8083/research>

### 健康检查

```powershell
Invoke-RestMethod http://127.0.0.1:8081/api/v1/ping
Invoke-RestMethod http://127.0.0.1:8082/api/v1/ping
Invoke-RestMethod http://127.0.0.1:8083/api/v1/ping
```

只检查已启动服务。`pong` 只证明 API 存活；它不证明策略、sidecar 覆盖、交易所连接、
回测数据或实盘权限正确。

## 停止、状态和恢复

读取状态和有限日志是只读操作：

```powershell
python tools/compose_runtime.py --profile trading --profile research ps --all
python tools/compose_runtime.py logs --tail 100 freqtrade-futures
```

停止会改变运行状态，必须先取得明确授权：

```powershell
python tools/compose_runtime.py stop freqtrade
python tools/compose_runtime.py stop freqtrade-futures
python tools/compose_runtime.py stop freqtrade-research
```

不要删除 `ft_userdata/runtime/`。Spot 和 Futures 的数据库分别位于：

```text
ft_userdata/runtime/freqtrade/trades.sqlite
ft_userdata/runtime/freqtrade-futures/trades.sqlite
```

备份或恢复前阅读 [SQLite 备份与恢复](docs/operations/sqlite-backup-and-restore.md)。凭据轮换
前阅读 [运行时秘密](docs/operations/runtime-secrets.md)。

## 可选：本地开发依赖

仅运行 Docker 服务不要求安装完整后端和前端依赖。开发、测试、A 股采集或 PriceFlow
数据准备需要以下环境。

### 后端

Windows PowerShell：

```powershell
py -3.12 -m venv freqtrade/.venv
./freqtrade/.venv/Scripts/python -m pip install --upgrade pip
./freqtrade/.venv/Scripts/python -m pip install -e './freqtrade[develop,research_ashare]'
```

Linux/macOS：

```sh
python3 -m venv freqtrade/.venv
./freqtrade/.venv/bin/python -m pip install --upgrade pip
./freqtrade/.venv/bin/python -m pip install -e './freqtrade[develop,research_ashare]'
```

### 前端

项目固定 `pnpm 11.9.0`：

```powershell
corepack enable
corepack prepare pnpm@11.9.0 --activate
Set-Location frequi
pnpm install --frozen-lockfile
Set-Location ..
```

### 聚焦验证

```powershell
./freqtrade/.venv/Scripts/python -m pytest tests -q
./freqtrade/.venv/Scripts/python -m pytest ft_userdata/user_data/tests -q

Set-Location freqtrade
./.venv/Scripts/python -m pytest tests/rpc/test_chart_data.py -q
./.venv/Scripts/python -m ruff check freqtrade/rpc tests/rpc
Set-Location ..

Set-Location frequi
pnpm vitest run tests/unit/candleChartTooltip.spec.ts
pnpm typecheck
pnpm build
Set-Location ..
```

根目录 `tests/` 中包含使用 `pandas`、`numpy` 和 `pytest` 的 PriceFlow 测试，必须用已经安装
项目依赖的解释器运行，不能假设系统 Python 的纯标准库环境足够。

## 常见故障

### `compose runtime: verification failed`

按顺序检查：

1. 是否在仓库根目录。
2. `git submodule status --recursive` 是否干净。
3. 是否运行过 `bootstrap_runtime.py init`。
4. `.env` 和 `ft_userdata/runtime/compose.identity.yml` 是否属于当前宿主用户。
5. 本地配置的 API 三个字段是否仍为 sentinel。
6. 运行 `bootstrap_runtime.py verify` 时的第一条错误。

不要改脚本或原始 Compose 来绕过验证。

### 交易所连接超时

检查本地配置中的 `httpsProxy`、`wsProxy` 和宿主代理端口。如果本机不使用代理，删除代理
键；如果 Docker 使用代理，地址应是 `host.docker.internal`，不是容器内的
`127.0.0.1`。

### Futures 报 `Cross-venue sidecar is required`

固定路径下缺少对应 BTC/ETH feather 文件。停止服务，准备或复制经过验证的 sidecar，检查
manifest 覆盖范围，再重新启动。不要创建空文件，也不要移除策略校验。

### Research 看不到 A 股标的

确认：

- `config.research.json` 的 `research_input_root` 和 `local_csv` root 正确；
- 文件名是 `{instrument}-{timeframe}.csv`；
- CSV 只有 `date,open,high,low,close,volume` 契约列；
- Research 容器挂载的 `ft_userdata/user_data/research_data` 是只读且存在；
- API 请求使用 `a-share-local` Bot ID。

### 端口可访问但页面身份不对

不要只检查 HTTP 200。核对端口、Bot 名、Spot/Futures、DRY-RUN、策略名和服务 ID。`8081`、
`8082`、`8083` 是三个不同安全边界。

## 进一步文档

- [Docker 本地运行细节](README.docker.md)
- [运行时秘密和轮换](docs/operations/runtime-secrets.md)
- [Runtime Supervisor 边界](docs/operations/runtime-supervisor.md)
- [Platform Control 运维边界](docs/operations/platform-control.md)
- [图表数据源规则](docs/chart-data-source-rules.md)
- [当前开发状态与权威文档索引](docs/superpowers/README.md)
- [E10 策略报告](docs/e10-strategy-report.html)

任何文档都不能替代运行时验证，也不能把 DRY-RUN、Research 或兼容服务升级为实盘授权。
