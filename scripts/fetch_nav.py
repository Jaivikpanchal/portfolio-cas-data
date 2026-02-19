#!/usr/bin/env python3
"""
fetch_nav.py
------------
Reads all CSVs from data/history/, fetches live NAV from mfapi.in,
and writes:
  - data/nav.json         -> live NAV per scheme code
  - data/portfolio.json   -> full portfolio summary for the dashboard
"""

import csv
import json
import requests
from datetime import datetime
from pathlib import Path

# ── Fund Config ────────────────────────────────────────────────────────────────
# mfapi.in scheme codes - find yours at https://api.mfapi.in/mf/search?q=FUND+NAME
FUND_CONFIG = [
    {
        "match": "kotak arbitrage",
        "code":  "119771",
        "isin":  "INF174K01LC6",
        "short": "KA",
        "color": "#3d8bff",
        "house": "Kotak",
    },
    {
        "match": "icici prudential multi",
        "code":  "120334",
        "isin":  "INF109K015K4",
        "short": "MA",
        "color": "#fbbf24",
        "house": "ICICI",
    },
    {
        "match": "icici prudential equity savings",
        "code":  "133054",
        "isin":  "INF109KA11J9",
        "short": "ES",
        "color": "#34d399",
        "house": "ICICI",
    },
]

MFAPI_BASE = "https://api.mfapi.in/mf"


def get_fund_config(fund_name):
    name_lower = fund_name.lower()
    for entry in FUND_CONFIG:
        if entry["match"] in name_lower:
            return entry
    return None


def fetch_nav_for_code(code):
    url = f"{MFAPI_BASE}/{code}/latest"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data  = resp.json()
        entry = data.get("data", [{}])[0]
        nav   = float(entry.get("nav", 0))
        date  = entry.get("date", "")
        if nav > 0:
            print(f"    OK code={code}  NAV=Rs.{nav}  date={date}")
            return nav, date
    except Exception as e:
        print(f"    FAIL code={code}  error={e}")
    return None


def read_transactions(history_dir):
    transactions = []
    csv_files = sorted(history_dir.glob("*.csv"), reverse=True)
    if not csv_files:
        print(f"  WARNING: No CSV files in {history_dir}")
        return transactions
    for csv_file in csv_files:
        print(f"  Reading {csv_file.name}")
        try:
            with open(csv_file, newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader, None)
                for row in reader:
                    if len(row) < 8 or not any(row):
                        continue
                    try:
                        transactions.append({
                            "date":            row[0].strip(),
                            "folio":           row[1].strip(),
                            "fundHouse":       row[2].strip(),
                            "fundName":        row[3].strip().replace('"', ''),
                            "invested":        float(row[4]),
                            "units":           float(row[5]),
                            "historicalNAV":   float(row[6]),
                            "historicalValue": float(row[7]),
                        })
                    except (ValueError, IndexError) as e:
                        print(f"    Skipping bad row: {e}")
        except Exception as e:
            print(f"  ERROR: {e}")
    print(f"  Total transactions: {len(transactions)}")
    return transactions


def aggregate_holdings(transactions):
    holdings = {}
    for txn in transactions:
        key = txn["fundName"]
        if key not in holdings:
            cfg = get_fund_config(key) or {
                "code": None, "isin": None,
                "short": key[:2].upper(), "color": "#6b7385", "house": "Unknown"
            }
            holdings[key] = {
                "fundName":  key,
                "fundHouse": txn["fundHouse"],
                "folio":     txn["folio"],
                "code":      cfg.get("code"),
                "isin":      cfg.get("isin"),
                "short":     cfg.get("short", key[:2].upper()),
                "color":     cfg.get("color", "#6b7385"),
                "units":     0.0,
                "invested":  0.0,
                "liveNAV":   None,
                "liveValue": 0.0,
                "navDate":   None,
            }
        holdings[key]["units"]    += txn["units"]
        holdings[key]["invested"] += txn["invested"]
    return holdings


def apply_navs(holdings, nav_data):
    for fund in holdings.values():
        code = fund.get("code")
        if code and code in nav_data:
            nd = nav_data[code]
            fund["liveNAV"]   = nd["nav"]
            fund["navDate"]   = nd["date"]
            fund["liveValue"] = round(fund["units"] * nd["nav"], 2)
        else:
            fund["liveValue"] = fund["invested"]
    return holdings


def build_portfolio_json(holdings, transactions):
    funds = list(holdings.values())
    total_invested = round(sum(f["invested"]  for f in funds), 2)
    total_value    = round(sum(f["liveValue"] for f in funds), 2)
    total_gain     = round(total_value - total_invested, 2)
    gain_pct       = round((total_gain / total_invested * 100), 2) if total_invested else 0

    dates, xirr = [], None
    for t in transactions:
        try:
            dates.append(datetime.strptime(t["date"], "%Y-%m-%d"))
        except ValueError:
            pass
    if dates and total_invested > 0:
        earliest = min(dates)
        years = (datetime.now() - earliest).days / 365.25
        if years > 0.01:
            xirr = round((((total_value / total_invested) ** (1 / years)) - 1) * 100, 2)

    for f in funds:
        f["portfolioPct"] = round((f["invested"] / total_invested * 100), 1) if total_invested else 0
        f["gain"]         = round(f["liveValue"] - f["invested"], 2)
        f["gainPct"]      = round((f["gain"] / f["invested"] * 100), 2) if f["invested"] else 0
        f["avgNAV"]       = round(f["invested"] / f["units"], 4) if f["units"] else 0

    return {
        "generatedAt": datetime.now().isoformat(),
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
    repo_root   = Path(__file__).parent.parent
    history_dir = repo_root / "data" / "history"
    out_dir     = repo_root / "data"
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 52)
    print("  Portfolio NAV Updater  (mfapi.in)")
    print("=" * 52)

    print("\n[1/4] Reading transactions...")
    transactions = read_transactions(history_dir)
    if not transactions:
        print("No transactions found. Exiting.")
        return

    print("\n[2/4] Aggregating holdings...")
    holdings = aggregate_holdings(transactions)
    print(f"  {len(holdings)} unique funds")

    print("\n[3/4] Fetching NAVs from mfapi.in...")
    nav_data, seen = {}, set()
    for fund in holdings.values():
        code = fund.get("code")
        if code and code not in seen:
            seen.add(code)
            result = fetch_nav_for_code(code)
            if result:
                nav_data[code] = {"nav": result[0], "date": result[1]}

    nav_out = out_dir / "nav.json"
    with open(nav_out, "w") as f:
        json.dump({"fetchedAt": datetime.now().isoformat(), "navs": nav_data}, f, indent=2)
    print(f"  Saved {nav_out}")

    print("\n[4/4] Building portfolio.json...")
    holdings  = apply_navs(holdings, nav_data)
    portfolio = build_portfolio_json(holdings, transactions)

    portfolio_out = out_dir / "portfolio.json"
    with open(portfolio_out, "w") as f:
        json.dump(portfolio, f, indent=2, ensure_ascii=False)
    print(f"  Saved {portfolio_out}")

    s = portfolio["summary"]
    print("\n── Summary " + "-"*40)
    print(f"  Invested : Rs.{s['totalInvested']:,.0f}")
    print(f"  Value    : Rs.{s['totalValue']:,.0f}")
    print(f"  Gain     : Rs.{s['totalGain']:,.0f}  ({s['gainPct']}%)")
    if s["xirr"]:
        print(f"  XIRR     : {s['xirr']}% p.a.")
    print("=" * 52)
    print("Done!")


if __name__ == "__main__":
    main()
