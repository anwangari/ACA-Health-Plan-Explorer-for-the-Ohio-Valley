# Running and Using the Dashboard

The Dash app serves on **http://127.0.0.1:8050** (Dash's default port). It reads
from PostgreSQL, falling back to `data/tidy/*.parquet` when `DATABASE_URL` is
unset — so it runs with or without a live database.

## Prerequisites

```bash
pip install -e .          # installs dash-bootstrap-components and the rest
```

A populated database (or the tidy Parquet files) must exist first. If you
haven't run the pipeline yet:

```bash
python -m marketplace                 # full pipeline (extract -> ... -> validate)
python -m marketplace --no-extract    # reuse cached API responses
```

## Start

```bash
python -m marketplace dashboard
# or, directly:
python src/marketplace/dashboard/app.py
```

Then open http://127.0.0.1:8050.

## Layout

The page is a single 1200px-wide column:

1. **Header** — title and the question the project answers.
2. **Controls** — age, income (% FPL), county, and metal-level filters.
3. **Five KPI cards** — plans available, median premium, cheapest Silver,
   cheapest Silver after credit, and the best-value plan's estimated annual cost.
4. **A 2x2 chart grid** — median premium by county, plans by metal level,
   premium vs. deductible, and estimated annual cost.
5. **Plan comparison table** — all plans for the selection, sortable.

## Using the app

1. **Set the shopper profile.** Drag the **age** slider and choose an **income**
   band (% of the federal poverty level). The italic line beneath the controls
   confirms which stored profile your input mapped to — for example,
   *"Closest available profile: Age 45, 250% FPL (~$37,650/yr)."* Income bands
   match what was loaded, so only age ever snaps. Every chart and card responds
   to both age and income.
2. **Read the cards.** Each shows a value and a one-line description of what it
   means. They update for the selected profile and county.
3. **Pick a county** to focus the supporting charts and the plan table on one
   market. On the "Median premium by county" chart, your selection is
   **highlighted** in context — all counties stay visible so you can see where
   yours ranks.
4. **Filter metal levels** to narrow every view (including the county chart's
   medians) to the tiers you care about.
5. **Find the best value.** The **premium vs. deductible** scatter plots each
   plan as a dot (colored and shaped by metal level); plans toward the
   bottom-left give the most coverage for the least cost. The **estimated annual
   cost** chart ranks plans by `premium x 12 + deductible`, which often tells a
   different story than premium alone — a cheap-premium plan with a big
   deductible can be the worst annual value.
6. **Sort the plan table** by clicking any column header. The table scrolls
   horizontally within its card if needed, so it never overflows the page.

> **Note on the annual-cost estimate.** It is illustrative: it assumes you meet
> the plan's deductible over the year. Actual cost depends on the care you use.
> The figure is built only from stored premium and deductible values — there is
> no predictive model.

> **Note on profiles.** The dashboard never calls the CMS API at runtime. It
> reads pre-computed quotes for a fixed grid of profiles loaded by the pipeline,
> and snaps your input to the nearest one. To widen the grid, edit
> `PROFILE_AGES` / `PROFILE_FPL_BANDS` in `config.py` and re-run the pipeline.

## In debug mode

`app.run(debug=True)` runs **two** Python processes (a reloader parent and a
worker child). Both must be killed to free the port.

### Kill (Windows / PowerShell)

```powershell
# 1. Find the process(es) listening on port 8050
Get-NetTCPConnection -State Listen -LocalPort 8050 |
    Select-Object LocalAddress, LocalPort, OwningProcess

# 2. Kill by command line — gets both the reloader parent and the worker child,
#    so the port isn't re-bound:
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*marketplace dashboard*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

# 3. Verify the port is free
if (Get-NetTCPConnection -State Listen -LocalPort 8050 -ErrorAction SilentlyContinue) {
    "still listening"
} else {
    "port 8050 free"
}
```

> If you only `Stop-Process` the PID shown by `Get-NetTCPConnection`, the debug
> reloader parent respawns the worker and the port stays bound. Killing by
> command line (step 2) avoids that. This matters when applying code changes:
> if the old process keeps serving, you'll see stale behavior.

### Kill (macOS / Linux)

```bash
lsof -ti :8050 | xargs kill -9
```