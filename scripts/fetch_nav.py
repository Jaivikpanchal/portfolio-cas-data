#!/usr/bin/env python3
"""
fetch_nav.py
------------
Reads all CSVs from data/history/, fetches live NAV from AMFI,
and writes two output files:
  - data/nav.json          → live NAV per ISIN
  - data/portfolio.json    → full portfolio summary for the dashboard
"""

import csv
import json
import os
import requests
from datetime import datetime
from pathlib import Path
from collections import defaultdict

# ── ISIN Map (fund name substring → ISIN) ─────────────────────────────────────
ISIN_MAP = [
    {
        "match": "kotak arbitrage",
        "isin": "INF174K01LC6",
        "short": "KA",
        "color": "#3d8bff",
        "house": "Kotak"
    },
    {
        "match": "icici prudential multi",
        "isin": "INF109K015K4",
        "short": "MA",
        "color": "#fbbf24",
        "house": "ICICI"
    },
    {
        "match": "icici prudential equity savings",
        "isin": "INF109KA11J9",
        "short": "ES",
        "color": "#34d399",
        "house": "ICICI"
    },
]

AMFI_URL = "https://www.amfiindia.com/spages/NAVAll.txt"


def get_isin(fund_name: str) -> dict | None:
    """Return the metadata dict for a fund based on its name."""
    name_lower = fund_name.lower()
    for entry in ISIN_MAP:
        if entry["match"] in name_lower:
            return entry
    return None


def fetch_amfi_navs(isins_needed: set[str]) -> dict:
    """
    Download NAVAll.txt from AMFI and parse NAVs for the requested ISINs.
    Returns dict: { isin: { "nav": float, "date": str } }
    """
    print("Fetching NAV data from AMFI…")
    try:
        resp = requests.get(AMFI_URL, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"  ERROR: Could not fetch AMFI data: {e}")
        return {}

    nav_data = {}
    # NAVAll.txt format (semicolon-separated):
    # SchemeCode;ISIN-Div-Reinvest;ISIN-Div-Payout;SchemeName;NAVDate;NAV
    for line in resp.text.splitlines():
        parts = line.strip().split(";")
        if len(parts) < 6:
            continue
        isin1 = parts[1].strip()
        isin2 = parts[2].strip()
        nav_date = parts[4].strip()
        try:
            nav = float(parts[5].strip())
        except ValueError:
            continue
        for isin in (isin1, isin2):
            if isin and isin in isins_needed:
                nav_data[isin] = {"nav": nav, "date": nav_date}

    print(f"  Found {len(nav_data)} / {len(isins_needed)} ISINs in AMFI data")
    return nav_data


def read_transactions(history_dir: Path) -> list[dict]:
    """Read all CSV files from data/history/ and return list of transaction dicts."""
    transactions = []
    csv_files = sorted(history_dir.glob("*.csv"), reverse=True)

    if not csv_files:
        print(f"  WARNING: No CSV files found in {history_dir}")
        return transactions

    for csv_file in csv_files:
        print(f"  Reading {csv_file.name}…")
        try:
            with open(csv_file, newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader, None)  # skip header
                for row in reader:
                    if len(row) < 8 or not any(row):
                        continue
                    try:
                        txn = {
                            "date":           row[0].strip(),
                            "folio":          row[1].strip(),
                            "fundHouse":      row[2].strip(),
                            "fundName":       row[3].strip().replace('"', ''),
                            "invested":       float(row[4]),
                            "units":          float(row[5]),
                            "historicalNAV":  float(row[6]),
                            "historicalValue":float(row[7]),
                        }
                        transactions.append(txn)
                    except (ValueError, IndexError) as e:
                        print(f"    Skipping bad row: {row} ({e})")
        except Exception as e:
            print(f"  ERROR reading {csv_file.name}: {e}")

    print(f"  Total transactions loaded: {len(transactions)}")
    return transactions


def aggregate_holdings(transactions: list[dict]) -> dict:
    """
    Aggregate transactions by fund name.
    Returns dict keyed by fundName with summed units & invested.
    """
    holdings = {}
    for txn in transactions:
        key = txn["fundName"]
        if key not in holdings:
            meta = get_isin(key) or {"isin": None, "short": key[:2].upper(), "color": "#6b7385", "house": "Unknown"}
            holdings[key] = {
                "fundName":   key,
                "fundHouse":  txn["fundHouse"],
                "folio":      txn["folio"],
                "isin":       meta.get("isin"),
                "short":      meta.get("short", key[:2].upper()),
                "color":      meta.get("color", "#6b7385"),
                "units":      0.0,
                "invested":   0.0,
                "liveNAV":    None,
                "liveValue":  0.0,
                "navDate":    None,
            }
        holdings[key]["units"]    += txn["units"]
        holdings[key]["invested"] += txn["invested"]
    return holdings


def apply_navs(holdings: dict, nav_data: dict) -> dict:
    """Merge live NAV into holdings and compute live values."""
    for fund in holdings.values():
        isin = fund["isin"]
        if isin and isin in nav_data:
            nd = nav_data[isin]
            fund["liveNAV"]   = nd["nav"]
            fund["navDate"]   = nd["date"]
            fund["liveValue"] = round(fund["units"] * nd["nav"], 2)
        else:
            # Fall back: use invested amount so gain shows 0 rather than -100%
            fund["liveValue"] = fund["invested"]
    return holdings


def build_portfolio_json(holdings: dict, transactions: list[dict]) -> dict:
    """Build the final portfolio summary dict."""
    funds = list(holdings.values())

    total_invested = round(sum(f["invested"] for f in funds), 2)
    total_value    = round(sum(f["liveValue"] for f in funds), 2)
    total_gain     = round(total_value - total_invested, 2)
    gain_pct       = round((total_gain / total_invested * 100), 2) if total_invested else 0

    # Approx CAGR (simple)
    dates = []
    for t in transactions:
        try:
            dates.append(datetime.strptime(t["date"], "%Y-%m-%d"))
        except ValueError:
            pass
    xirr = None
    if dates and total_invested > 0:
        earliest = min(dates)
        years = (datetime.now() - earliest).days / 365.25
        if years > 0.01:
            xirr = round((((total_value / total_invested) ** (1 / years)) - 1) * 100, 2)

    # Add portfolio weight to each fund
    for f in funds:
        f["portfolioPct"] = round((f["invested"] / total_invested * 100), 1) if total_invested else 0
        f["gain"]         = round(f["liveValue"] - f["invested"], 2)
        f["gainPct"]      = round((f["gain"] / f["invested"] * 100), 2) if f["invested"] else 0
        f["avgNAV"]       = round(f["invested"] / f["units"], 4) if f["units"] else 0

    return {
        "generatedAt":   datetime.now().isoformat(),
        "summary": {
            "totalInvested": total_invested,
            "totalValue":    total_value,
            "totalGain":     total_gain,
            "gainPct":       gain_pct,
            "xirr":          xirr,
            "fundCount":     len(funds),
            "txnCount":      len(transactions),
        },
        "holdings":     funds,
        "transactions": sorted(transactions, key=lambda x: x["date"], reverse=True),
    }


def main():
    # Resolve paths relative to repo root (script lives in scripts/)
    repo_root   = Path(__file__).parent.parent
    history_dir = repo_root / "data" / "history"
    out_dir     = repo_root / "data"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 50)
    print("Portfolio NAV Updater")
    print("=" * 50)

    # 1. Read transactions
    print("\n[1/4] Reading transactions…")
    transactions = read_transactions(history_dir)
    if not transactions:
        print("No transactions found. Exiting.")
        return

    # 2. Aggregate into holdings
    print("\n[2/4] Aggregating holdings…")
    holdings = aggregate_holdings(transactions)
    print(f"  {len(holdings)} unique funds found")

    # 3. Fetch live NAVs
    print("\n[3/4] Fetching live NAVs from AMFI…")
    isins_needed = {f["isin"] for f in holdings.values() if f["isin"]}
    nav_data = fetch_amfi_navs(isins_needed)

    # Write raw NAV file
    nav_out = out_dir / "nav.json"
    with open(nav_out, "w") as f:
        json.dump({"fetchedAt": datetime.now().isoformat(), "navs": nav_data}, f, indent=2)
    print(f"  NAV data written → {nav_out}")

    # 4. Build and write portfolio JSON
    print("\n[4/4] Building portfolio summary…")
    holdings = apply_navs(holdings, nav_data)
    portfolio = build_portfolio_json(holdings, transactions)

    portfolio_out = out_dir / "portfolio.json"
    with open(portfolio_out, "w") as f:
        json.dump(portfolio, f, indent=2, ensure_ascii=False)
    print(f"  Portfolio data written → {portfolio_out}")

    # Print summary
    s = portfolio["summary"]
    print("\n── Summary ──────────────────────────────────")
    print(f"  Invested : ₹{s['totalInvested']:,.0f}")
    print(f"  Value    : ₹{s['totalValue']:,.0f}")
    print(f"  Gain     : ₹{s['totalGain']:,.0f} ({s['gainPct']}%)")
    if s["xirr"]:
        print(f"  XIRR     : {s['xirr']}% p.a.")
    print("=" * 50)
    print("Done ✓")


if __name__ == "__main__":
    main()
