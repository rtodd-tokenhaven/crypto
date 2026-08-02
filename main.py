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
# DeFiLlama occasionally reports pools with absurd, non-representative APY
# (temporary incentive spikes, bugged pools, etc). Anything above this is
# treated as noise rather than a real yield opportunity.
MAX_SANE_APY = 1_000.0
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

        if apy <= 0 or apy > MAX_SANE_APY:
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

    ranked = _select_diversified_pools(filtered, top_n)
    if not ranked:
        return [], "No stablecoin pools met the filter constraints"

    return ranked, None


def _select_diversified_pools(pools: list[PoolMetric], top_n: int) -> list[PoolMetric]:
    """
    Pick up to top_n pools while giving every stablecoin asset a fair shot.

    A flat "sort everything by APY, take the top N" tends to be swept
    entirely by whichever asset (usually USDC) has the most >$1M-TVL pools
    on-chain, since it simply has more chances to land a high APY. Instead,
    this round-robins across assets — best pool from each asset first, then
    second-best from each, and so on — so USDT, USDS, etc. still surface
    when they're competitive, not just when they happen to top the whole list.
    """
    by_asset: dict[str, list[PoolMetric]] = {}
    for pool in pools:
        by_asset.setdefault(pool.asset, []).append(pool)

    for asset_pools in by_asset.values():
        asset_pools.sort(key=lambda p: p.apy, reverse=True)

    # Visit assets in order of their own best APY, so a strong asset's top
    # pool still outranks a weak asset's top pool on the first pass.
    assets_by_strength = sorted(
        by_asset.keys(), key=lambda asset: by_asset[asset][0].apy, reverse=True
    )

    selected: list[PoolMetric] = []
    round_index = 0
    max_round = max((len(bucket) for bucket in by_asset.values()), default=0)
    while len(selected) < top_n and round_index < max_round:
        for asset in assets_by_strength:
            if len(selected) >= top_n:
                break
            bucket = by_asset[asset]
            if round_index < len(bucket):
                selected.append(bucket[round_index])
        round_index += 1

    return selected


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
            '<article class="panel border-[var(--red)]/40 p-5">'
            '<h3 class="text-lg font-semibold" style="color: var(--red)">Yield API status</h3>'
            f'<p class="mt-2 text-sm text-[var(--text-muted)]">{reason}</p>'
            '</article>'
        )

    cards: list[str] = []
    for i, pool in enumerate(pools):
        delay = 0.05 * (i + 1)
        cards.append(
            f'''
<article class="yield-card fade-up panel p-5" style="animation-delay: {delay:.2f}s">
  <div class="mb-3 flex items-center justify-between">
    <span class="badge">
      <span class="dot"></span>
      {html.escape(pool.network)}
    </span>
    <p class="mono text-xs text-[var(--text-muted)]">TVL: ${pool.tvl_usd / 1_000_000:.2f}M</p>
  </div>
  <h3 class="text-lg font-semibold">{html.escape(pool.asset)}</h3>
  <p class="mono mt-2 text-2xl font-bold text-[var(--gold)]">{pool.apy:.2f}% APY</p>
  <div class="yield-mini-chart mt-3"></div>
</article>
'''.strip()
        )
    return "\n".join(cards)


def render_briefing_html(pools: list[PoolMetric], llm_prompt_template: str, error: str | None) -> str:
    # Note: llm_prompt_template is intentionally not rendered to the page.
    # Shipping the raw analyst prompt to end users doesn't help them and
    # reads as an internal debugging artifact left in a production page.
    del llm_prompt_template

    if not pools:
        return (
            "<p>Market briefing is currently running on fallback mode due to upstream API issues. "
            "Core layout is still operational and will refresh automatically on the next successful daily run.</p>"
        )

    top_pool = pools[0]
    avg_apy = sum(pool.apy for pool in pools) / len(pools)
    total_tvl = sum(pool.tvl_usd for pool in pools)

    return (
        f"<p>Top stablecoin carry today is led by {html.escape(top_pool.asset)} on {html.escape(top_pool.network)} "
        f"at <strong>{top_pool.apy:.2f}% APY</strong>, while the selected opportunity set averages "
        f"<strong>{avg_apy:.2f}% APY</strong> across <strong>${total_tvl / 1_000_000:.2f}M TVL</strong>. "
        "Capital appears concentrated in a handful of deep pools, which supports execution quality but "
        "can tighten exits if volatility spikes. Practical positioning: prioritize diversified exposure across "
        "at least two networks while monitoring daily APY compression.</p>"
    )


def render_news_html(news_items: list[NewsItem]) -> str:
    parts: list[str] = []
    for item in news_items:
        parts.append(
            f'''
<li class="group border border-[var(--line)] bg-[var(--bg-void)]/50 px-4 py-3 transition-colors duration-200 hover:border-[var(--line-strong)]" style="border-radius: 3px;">
  <span class="badge mr-2">[{html.escape(item.ticker)}]</span>
  <span class="text-[var(--text-primary)]">{html.escape(item.title)}</span>
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
