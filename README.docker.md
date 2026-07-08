# Docker local run

This repository is organized as a top-level Docker project around the `freqtrade`,
`frequi`, and `freqtrade-strategies` submodules.

## First setup

Clone with submodules:

```powershell
git clone --recurse-submodules https://github.com/xrunmasterx/freqtrade-cn.git
cd freqtrade-cn
```

Create local config files:

```powershell
Copy-Item .env.example .env
Copy-Item ft_userdata\user_data\config.example.json ft_userdata\user_data\config.json
Copy-Item ft_userdata\user_data\config.research.example.json ft_userdata\user_data\config.research.json
```

Edit `ft_userdata\user_data\config.json` and `ft_userdata\user_data\config.research.json` before running:

- Replace the API password.
- Replace the proxy port if your local HTTP proxy is not `12639`.
- For Docker Desktop on Windows/macOS, use `host.docker.internal` to reach a proxy running on the host.
- For native venv runs, use `127.0.0.1` instead.

## Run

```powershell
docker compose build freqtrade
docker compose up -d freqtrade
```

Open the trading UI:

```text
http://127.0.0.1:8081/trade
```

Start only the research webserver:

```powershell
docker compose build freqtrade-research
docker compose up -d freqtrade-research
```

Open the research UI:

```text
http://127.0.0.1:8083/research
```

Services are assigned to compose profiles. Running `docker compose up -d`
without a profile or an explicit service name will not start profiled services.
To start every trading service, use:

```powershell
docker compose --profile trading build
docker compose --profile trading up -d
```

To start the research webserver, use:

```powershell
docker compose --profile research build
docker compose --profile research up -d
```

Default example login:

```text
username: freqtrader
password: change-me
```

## Stop

```powershell
docker compose down
```

## Current defaults

- Exchange: `bitget`
- Trading mode: `spot`
- Run mode: `dry_run`
- Timeframe: `5m`
- Pairs: `BTC/USDT`, `ETH/USDT`
- Strategy: `SampleStrategy`
- Host UI port: `8081`
- Research UI port: `8083`
- Container API/UI port: `8080`
