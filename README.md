# 📊 Portfolio NAV Tracker — GitHub Pages

A fully automated mutual fund portfolio tracker. GitHub Actions fetches live NAV from AMFI daily and pre-computes `data/portfolio.json`. The HTML dashboard just reads that file — **zero CORS issues, zero backend needed**.

## How it works

```
Zapier → pushes CSVs → data/history/*.csv
GitHub Actions (daily) → fetch_nav.py → data/portfolio.json
GitHub Pages → index.html reads portfolio.json → shows dashboard
```

---

## Folder structure

```
your-repo/
├── index.html                        ← Dashboard (deploy to GitHub Pages)
├── scripts/
│   └── fetch_nav.py                  ← Python script (run by GitHub Actions)
├── .github/workflows/
│   └── update_nav.yml                ← Runs fetch_nav.py daily @ 6:30 PM IST
└── data/
    ├── history/                      ← Zapier drops CSVs here
    │   ├── 2025-01.csv
    │   └── 2025-02.csv
    ├── nav.json                      ← Auto-generated (raw AMFI data)
    └── portfolio.json                ← Auto-generated (full computed summary)
```

---

## Setup steps

### 1. CSV format (Zapier should produce this)

`data/history/YYYY-MM.csv`:
```
date,folio,fundHouse,fundName,invested,units,historicalNAV,historicalValue
2025-01-15,42373690,ICICI,"ICICI Prudential Multi-Asset Fund - Direct Plan - Growth",25000,27.475,909.9181,24999.8
```

### 2. Enable GitHub Pages

Go to your repo → **Settings → Pages** → Source: **Deploy from branch `main`, folder `/` (root)**

### 3. Run the first update manually

Go to **Actions tab** → `Update Portfolio NAV` → **Run workflow**

Or run locally first:
```bash
pip install requests
python scripts/fetch_nav.py
git add data/
git commit -m "initial portfolio data"
git push
```

### 4. Add more funds (optional)

Edit the `ISIN_MAP` in `scripts/fetch_nav.py`:
```python
ISIN_MAP = [
    {
        "match": "kotak arbitrage",      # substring of your fund name (lowercase)
        "isin":  "INF174K01LC6",         # ISIN from AMFI / valueresearch
        "short": "KA",                   # 2-letter badge abbreviation
        "color": "#3d8bff",              # hex color for the card
        "house": "Kotak"
    },
    # add more here...
]
```

Find ISINs at: https://www.amfiindia.com/nav-history-download

### 5. Customise goal & SIP

In `index.html`, near the top of the `<script>` block:
```js
const GOAL        = 2000000;            // your target corpus in ₹
const SIP         = 10000;             // your monthly SIP in ₹
const TARGET_DATE = new Date(2027, 11, 6); // your target date
```

---

## Schedule

The GitHub Action runs **Monday–Friday at 6:30 PM IST** (after AMFI updates NAVs at ~7 PM).
To change the schedule, edit `.github/workflows/update_nav.yml`:
```yaml
- cron: "0 13 * * 1-5"   # 13:00 UTC = 18:30 IST
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `portfolio.json` not found | Run the Action manually once |
| NAV shows "unavailable" | Check ISIN in `ISIN_MAP` against AMFI website |
| Fund not aggregated | Make sure the `match` string appears in your fund name (case-insensitive) |
| Action fails | Check Actions tab logs; usually a missing `requests` dep or wrong CSV format |
