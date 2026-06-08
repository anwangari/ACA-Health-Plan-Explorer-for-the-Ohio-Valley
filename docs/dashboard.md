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
python -m marketplace                 # full pipeline (extract → … → validate)
python -m marketplace --no-extract    # reuse cached API responses
```

## Start

```bash
python -m marketplace dashboard
# or, directly:
python src/marketplace/dashboard/app.py
```

Then open http://127.0.0.1:8050.

## Using the app

1. **Set the shopper profile.** Drag the **age** slider and choose an **income**
   band (% of the federal poverty level). The italic line beneath the controls
   confirms which stored profile your input mapped to — for example,
   *"Showing the closest available profile: Age 45, 250% FPL (~$37,650/yr)."*
   Income bands match what was loaded, so only age ever snaps.
2. **Read the summary cards.** Plans available, median premium, cheapest Silver,
   and issuer count update for the selected profile (and county, once chosen).
3. **Pick a county** from the dropdown to focus every view on one market.
4. **Filter metal levels** to narrow the plan comparison table.
5. **Compare full vs. after-credit premiums** to see the subsidy's effect, and
   **comparison by issuer** to see which carriers compete.
6. **Sort the plan table** by clicking any column header.

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
> command line (step 2) avoids that.

### Kill (macOS / Linux)

```bash
lsof -ti :8050 | xargs kill -9
```