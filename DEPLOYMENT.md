# Deployment and Automation Guide

## What this prototype does
- Builds a modern crypto dashboard in `index.html`.
- Uses `main.py` to fetch yield and news data, then inject fresh HTML blocks into the template.
- Fails safely by using fallback content when APIs are unavailable.

## Local run
1. Install Python 3.10+ if needed. On this machine the active interpreter is:
   ```powershell
   C:\Users\17275\AppData\Local\Programs\Python\Python311\python.exe
   ```
2. Install dependencies:
   ```bash
   C:\Users\17275\AppData\Local\Programs\Python\Python311\python.exe -m pip install -r requirements.txt
   ```
3. Run the data refresh:
   ```powershell
   C:\Users\17275\AppData\Local\Programs\Python\Python311\python.exe main.py
   ```
4. Open `index.html` in a browser.

## Runtime overrides
- `CRYPTO_DASHBOARD_POOLS_URL`: override the DeFiLlama pools endpoint.
- `CRYPTO_DASHBOARD_NEWS_URL`: override the news RSS endpoint.
- `CRYPTO_DASHBOARD_INDEX_FILE`: change the HTML output file path.
- `CRYPTO_DASHBOARD_TOP_POOLS`: change how many pools are rendered.
- `CRYPTO_DASHBOARD_TOP_NEWS`: change how many headlines are rendered.
- Equivalent CLI flags are available via `main.py` for one-off runs.
- You can also create a local `.env` file from [.env.example](.env.example) and the script will load it automatically.

## Daily serverless refresh (GitHub Actions)
- Workflow file: `.github/workflows/daily-dashboard-refresh.yml`
- Trigger schedule: every day at 13:00 UTC.
- Also supports manual runs from Actions tab via `workflow_dispatch`.
- The workflow updates `index.html`, commits, and pushes only when content changed.

## Daily local refresh (Windows Task Scheduler)
1. Open PowerShell as Administrator.
2. Register the task:
   ```powershell
   ./scripts/register-daily-task.ps1 -PythonPath "C:\Users\17275\AppData\Local\Programs\Python\Python311\python.exe" -RunTime "09:00"
   ```
3. Verify in Task Scheduler that `CryptoDashboardDailyRefresh` exists.
4. Optional manual test:
   ```powershell
   Start-ScheduledTask -TaskName "CryptoDashboardDailyRefresh"
   ```

## API sources
- Stablecoin pool metrics: `https://yields.llama.fi/pools`
- News RSS feed: `https://www.coindesk.com/arc/outboundfeeds/rss/`

## Hardening suggestions
- Add retries with exponential backoff for API calls.
- Track previous APY values to render trend arrows.
- Publish dashboard via GitHub Pages for public hosting.
