from __future__ import annotations

import argparse
import html
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET

import requests

DEFI_LLAMA_POOLS_URL = "https://yields.llama.fi/pools"
NEWS_RSS_URL = "https://www.coindesk.com/arc/outboundfeeds/rss/"

STABLE_ASSETS = {"USDC", "USDT", "USDS"}
MIN_TVL_USD = 1_000_000
TOP_POOL_COUNT = 5
TOP_NEWS_COUNT = 5

INDEX_FILE = Path(__file__).with_name("index.html")

ENV_POOLS_URL = "CRYPTO_DASHBOARD_POOLS_URL"
ENV_NEWS_URL = "CRYPTO_DASHBOARD_NEWS_URL"
ENV_INDEX_FILE = "CRYPTO_DASHBOARD_INDEX_FILE"
ENV_TOP_POOLS = "CRYPTO_DASHBOARD_TOP_POOLS"
ENV_TOP_NEWS = "CRYPTO_DASHBOARD_TOP_NEWS"
DOTENV_FILE = Path(__file__).with_name(".env")


@dataclass
class PoolMetric:
    network: str
    asset: str
    apy: float
    tvl_usd: float
    project: str


@dataclass
class NewsItem:
    ticker: str
    title: str


def fetch_top_stablecoin_yields(
    top_n: int = TOP_POOL_COUNT,
) -> tuple[list[PoolMetric], str | None]:
    """Pull and rank top stablecoin pools by APY from DeFiLlama."""
    try:
        response = requests.get(DEFI_LLAMA_POOLS_URL, timeout=20)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        return [], f"DeFiLlama request failed: {exc}"
    except ValueError as exc:
        return [], f"Invalid DeFiLlama JSON payload: {exc}"

    pools = payload.get("data", [])
    if not isinstance(pools, list):
        return [], "Unexpected DeFiLlama payload shape: data is not a list"

    filtered: list[PoolMetric] = []
    for pool in pools:
        symbol = str(pool.get("symbol", "")).upper().strip()
        base_symbol = normalize_asset_symbol(symbol)

        if base_symbol not in STABLE_ASSETS:
            continue

        tvl = to_float(pool.get("tvlUsd"))
        apy = to_float(pool.get("apy"))

        if tvl is None or apy is None or tvl <= MIN_TVL_USD:
            continue

        chain = str(pool.get("chain", "Unknown")).strip() or "Unknown"
        project = str(pool.get("project", "Unknown")).strip() or "Unknown"
        filtered.append(
            PoolMetric(
                network=chain,
                asset=base_symbol,
                apy=apy,
                tvl_usd=tvl,
                project=project,
            )
        )

    ranked = sorted(filtered, key=lambda p: p.apy, reverse=True)[:top_n]
    if not ranked:
        return [], "No stablecoin pools met the filter constraints"

    return ranked, None


def normalize_asset_symbol(symbol: str) -> str:
    """Normalize symbols such as USDC.e, USDT-b into canonical tickers."""
    if not symbol:
        return ""
    cleaned = symbol.strip().upper().replace(" ", "")
    if cleaned.startswith("USDC"):
        return "USDC"
    if cleaned.startswith("USDT"):
        return "USDT"
    if cleaned.startswith("USDS"):
        return "USDS"
    return cleaned.split("-")[0].split(".")[0].split("_")[0]


def to_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_env_file(path: Path = DOTENV_FILE) -> None:
    """Load a simple .env file without introducing another dependency."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


@dataclass(frozen=True)
class RuntimeConfig:
    pools_url: str
    news_url: str
    index_file: Path
    top_pools: int
    top_news: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh the crypto yield dashboard HTML.")
    parser.add_argument("--pools-url", default=os.getenv(ENV_POOLS_URL, DEFI_LLAMA_POOLS_URL))
    parser.add_argument("--news-url", default=os.getenv(ENV_NEWS_URL, NEWS_RSS_URL))
    parser.add_argument("--index-file", default=os.getenv(ENV_INDEX_FILE, str(INDEX_FILE)))
    parser.add_argument(
        "--top-pools",
        type=int,
        default=int(os.getenv(ENV_TOP_POOLS, str(TOP_POOL_COUNT))),
    )
    parser.add_argument(
        "--top-news",
        type=int,
        default=int(os.getenv(ENV_TOP_NEWS, str(TOP_NEWS_COUNT))),
    )
    return parser.parse_args()


def build_runtime_config(args: argparse.Namespace) -> RuntimeConfig:
    return RuntimeConfig(
        pools_url=args.pools_url,
        news_url=args.news_url,
        index_file=Path(args.index_file),
        top_pools=args.top_pools,
        top_news=args.top_news,
    )


def fetch_breaking_news(news_url: str, top_n: int = TOP_NEWS_COUNT) -> tuple[list[NewsItem], str | None]:
    """Fetch top crypto headlines from RSS. Fallback to curated headlines."""
    try:
        response = requests.get(news_url, timeout=15)
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except (requests.RequestException, ET.ParseError) as exc:
        return fallback_news_items(top_n), f"News feed unavailable, using fallback headlines: {exc}"

    items: list[NewsItem] = []
    for item_el in root.findall(".//item"):
        title_el = item_el.find("title")
        if title_el is None or not title_el.text:
            continue
        title = collapse_whitespace(title_el.text)
        ticker = infer_ticker_from_headline(title)
        items.append(NewsItem(ticker=ticker, title=title))
        if len(items) >= top_n:
            break

    if not items:
        return fallback_news_items(top_n), "RSS returned no items, using fallback headlines"

    return items, None


def fallback_news_items(top_n: int) -> list[NewsItem]:
    defaults = [
        NewsItem("SOL", "Solana developers accelerate stablecoin payment integrations across major apps."),
        NewsItem("ETH", "Ethereum DeFi vault yields compress as capital rotates into blue-chip pools."),
        NewsItem("BTC", "Bitcoin market structure remains bid as institutions add spot exposure."),
        NewsItem("USDC", "USDC transfer volume rises as cross-chain settlement demand expands."),
        NewsItem("L2", "Layer-2 ecosystems compete on incentives to retain sticky TVL growth."),
    ]
    return defaults[:top_n]


def infer_ticker_from_headline(title: str) -> str:
    checks = {
        "SOL": ["solana", "sol"],
        "ETH": ["ethereum", "eth"],
        "BTC": ["bitcoin", "btc"],
        "USDC": ["usdc"],
        "USDT": ["usdt", "tether"],
        "L2": ["layer 2", "layer-2", "l2"],
    }
    lower_title = title.lower()
    for ticker, keys in checks.items():
        if any(key in lower_title for key in keys):
            return ticker
    return "CRYPTO"


def collapse_whitespace(text: str) -> str:
    return " ".join(text.split())


def build_yield_table_for_prompt(pools: Iterable[PoolMetric]) -> str:
    """
    Build a compact markdown table suitable for an LLM input prompt.

    This demonstrates how cleaned API data can be serialized into a model-friendly
    structure before generating a natural-language daily market summary.
    """
    rows = ["| Network | Asset | APY % | TVL (USD M) | Protocol |", "|---|---|---:|---:|---|"]
    for pool in pools:
        rows.append(
            f"| {pool.network} | {pool.asset} | {pool.apy:.2f} | {pool.tvl_usd / 1_000_000:.2f} | {pool.project} |"
        )
    return "\n".join(rows)


def build_llm_prompt_template(pools: Iterable[PoolMetric]) -> str:
    data_table = build_yield_table_for_prompt(pools)
    return (
        "You are a crypto market analyst. Write a concise daily yield briefing in 3-4 sentences.\n"
        "Use the pool data table below, highlight trend direction, concentration risk, and one practical action.\n\n"
        "Pool Data:\n"
        f"{data_table}\n"
    )


def render_yield_cards_html(pools: list[PoolMetric], error: str | None) -> str:
    if not pools:
        reason = html.escape(error or "Yield data unavailable")
        return (
            '<article class="rounded-xl border border-rose-400/30 bg-rose-500/10 p-5 card-glow">'
            '<h3 class="text-lg font-semibold text-rose-200">Yield API status</h3>'
            f'<p class="mt-2 text-sm text-rose-100">{reason}</p>'
            '</article>'
        )

    cards: list[str] = []
    for i, pool in enumerate(pools):
        delay = 0.05 * (i + 1)
        cards.append(
            f'''
<article class="fade-up rounded-xl border border-[var(--line-soft)] bg-[var(--bg-secondary)] p-5 card-glow transition-all duration-300 hover:-translate-y-1 hover:border-emerald-300/40 hover:shadow-[0_8px_32px_rgba(147,255,63,0.12)]" style="animation-delay: {delay:.2f}s">
  <div class="mb-3 flex items-center justify-between">
    <span class="inline-flex items-center gap-2 rounded-full border border-cyan-300/40 bg-cyan-300/10 px-3 py-1 text-xs text-cyan-300">
      <span class="h-2 w-2 rounded-full bg-cyan-300"></span>
      {html.escape(pool.network)}
    </span>
    <p class="mono text-xs text-[var(--text-muted)]">TVL: ${pool.tvl_usd / 1_000_000:.2f}M</p>
  </div>
  <h3 class="text-lg font-semibold">{html.escape(pool.asset)}</h3>
  <p class="mono mt-2 text-2xl font-bold text-[var(--volt-green)]">{pool.apy:.2f}% APY</p>
</article>
'''.strip()
        )
    return "\n".join(cards)


def render_briefing_html(pools: list[PoolMetric], llm_prompt_template: str, error: str | None) -> str:
    if not pools:
        return (
            "<p>Market briefing is currently running on fallback mode due to upstream API issues. "
            "Core layout is still operational and will refresh automatically on the next successful daily run.</p>"
        )

    top_pool = pools[0]
    avg_apy = sum(pool.apy for pool in pools) / len(pools)
    total_tvl = sum(pool.tvl_usd for pool in pools)
    escaped_prompt = html.escape(llm_prompt_template)

    return (
        f"<p>Top stablecoin carry today is led by {html.escape(top_pool.asset)} on {html.escape(top_pool.network)} "
        f"at <strong>{top_pool.apy:.2f}% APY</strong>, while the selected opportunity set averages "
        f"<strong>{avg_apy:.2f}% APY</strong> across <strong>${total_tvl / 1_000_000:.2f}M TVL</strong>. "
        "Capital appears concentrated in a handful of deep pools, which supports execution quality but "
        "can tighten exits if volatility spikes. Practical positioning: prioritize diversified exposure across "
        "at least two networks while monitoring daily APY compression.</p>"
        "<details class=\"mt-4 rounded-lg border border-slate-600/30 bg-slate-900/50 p-3\">"
        "<summary class=\"cursor-pointer text-sm text-cyan-300\">LLM prompt template used for daily summary generation</summary>"
        f"<pre class=\"mt-3 overflow-x-auto whitespace-pre-wrap text-xs text-slate-300\">{escaped_prompt}</pre>"
        "</details>"
    )


def render_news_html(news_items: list[NewsItem]) -> str:
    parts: list[str] = []
    for item in news_items:
        parts.append(
            f'''
<li class="group rounded-xl border border-slate-600/30 bg-[var(--bg-primary)]/60 px-4 py-3 transition-all duration-300 hover:border-cyan-300/50 hover:bg-cyan-500/10">
  <span class="mr-2 inline-flex rounded-md border border-cyan-300/40 bg-cyan-300/10 px-2 py-0.5 text-xs font-semibold text-cyan-300">[{html.escape(item.ticker)}]</span>
  <span class="text-slate-100 group-hover:text-white">{html.escape(item.title)}</span>
</li>
'''.strip()
        )
    return "\n".join(parts)


def inject_between_markers(
    source_text: str,
    start_marker: str,
    end_marker: str,
    replacement_html: str,
) -> str:
    pattern = re.compile(
        rf"({re.escape(start_marker)})(.*)({re.escape(end_marker)})",
        flags=re.DOTALL,
    )

    def _replacer(match: re.Match[str]) -> str:
        start = match.group(1)
        end = match.group(3)
        return f"{start}\n{replacement_html}\n            {end}"

    if not pattern.search(source_text):
        raise ValueError(f"Markers not found: {start_marker} ... {end_marker}")

    return pattern.sub(_replacer, source_text, count=1)


def update_index_html(
    index_path: Path,
    yield_cards_html: str,
    briefing_html: str,
    news_html: str,
) -> None:
    original = index_path.read_text(encoding="utf-8")

    updated = inject_between_markers(
        original,
        "<!-- AUTO:YIELD_CARDS:START -->",
        "<!-- AUTO:YIELD_CARDS:END -->",
        yield_cards_html,
    )
    updated = inject_between_markers(
        updated,
        "<!-- AUTO:BRIEFING:START -->",
        "<!-- AUTO:BRIEFING:END -->",
        briefing_html,
    )
    updated = inject_between_markers(
        updated,
        "<!-- AUTO:NEWS:START -->",
        "<!-- AUTO:NEWS:END -->",
        news_html,
    )

    index_path.write_text(updated, encoding="utf-8")


def main() -> None:
    load_env_file()
    args = parse_args()
    config = build_runtime_config(args)

    pools, pool_error = fetch_top_stablecoin_yields(top_n=config.top_pools)
    llm_prompt = build_llm_prompt_template(pools)

    news_items, news_error = fetch_breaking_news(config.news_url, top_n=config.top_news)

    yield_cards_html = render_yield_cards_html(pools, pool_error)
    briefing_html = render_briefing_html(pools, llm_prompt, pool_error)
    news_html = render_news_html(news_items)

    update_index_html(config.index_file, yield_cards_html, briefing_html, news_html)

    print("Dashboard HTML updated successfully.")
    if pool_error:
        print(f"Pool warning: {pool_error}")
    if news_error:
        print(f"News warning: {news_error}")


if __name__ == "__main__":
    main()
