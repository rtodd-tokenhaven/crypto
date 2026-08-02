# Crypto Yield Tracker & News Dashboard

A production-ready prototype for a localized crypto yield tracker and breaking news dashboard.

## Features
- Modern dark-mode dashboard styled for crypto users
- Top stablecoin yield cards with APY, network badge, and TVL
- Daily yield analytics briefing block
- Breaking news feed with ticker badges
- Localized UI labels with English and Spanish support
- Daily automation via GitHub Actions or Windows Task Scheduler

## Requirements
- Python 3.10+
- `requests`

## Quick Start
1. Install dependencies:
   ```powershell
   C:\Users\17275\AppData\Local\Programs\Python\Python311\python.exe -m pip install -r requirements.txt
   ```
2. Refresh the dashboard content:
   ```powershell
   C:\Users\17275\AppData\Local\Programs\Python\Python311\python.exe main.py
   ```
3. Open `index.html` in your browser.

## Configuration
You can override runtime values with environment variables or CLI flags.

Environment variables:
- `CRYPTO_DASHBOARD_POOLS_URL`
- `CRYPTO_DASHBOARD_NEWS_URL`
- `CRYPTO_DASHBOARD_INDEX_FILE`
- `CRYPTO_DASHBOARD_TOP_POOLS`
- `CRYPTO_DASHBOARD_TOP_NEWS`

Optional local file:
- Copy [.env.example](.env.example) to `.env` for local overrides.

## Automation
- GitHub Actions workflow: [.github/workflows/daily-dashboard-refresh.yml](.github/workflows/daily-dashboard-refresh.yml)
- GitHub Pages workflow: [.github/workflows/pages.yml](.github/workflows/pages.yml)
- Windows scheduled task helper: [scripts/register-daily-task.ps1](scripts/register-daily-task.ps1)

## Public Hosting
To publish the dashboard publicly, enable GitHub Pages in the repository settings and use the GitHub Actions source option. The Pages workflow will deploy the latest `index.html` on every push to `main`.

## Supporting Files
- [DEPLOYMENT.md](DEPLOYMENT.md)
- [main.py](main.py)
- [index.html](index.html)
