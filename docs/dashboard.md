# Running the Dashboard Server

The Dash app serves the loaded data on **http://127.0.0.1:8050** (Dash's default
port). It reads from PostgreSQL, falling back to `data/tidy/*.parquet` when
`DATABASE_URL` is unset.

## Start

```bash
python -m marketplace dashboard
# or, directly:
python src/marketplace/dashboard/app.py
```

In debug mode (`app.run(debug=True)`), Dash's auto-reloader runs **two** Python
processes: a parent reloader and a child worker. Both must be killed to free the
port (see below).

## Kill (Windows / PowerShell)

```powershell
# 1. Find the process(es) listening on port 8050
Get-NetTCPConnection -State Listen -LocalPort 8050 |
    Select-Object LocalAddress, LocalPort, OwningProcess

# 2. Kill the dashboard process(es) by command line — this gets both the
#    reloader parent and the worker child, so the port isn't re-bound:
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
> reloader parent will respawn the worker and the port stays bound. Killing by
> command line (step 2) avoids that.

## Kill (macOS / Linux)

```bash
# find and kill whatever is listening on 8050
lsof -ti :8050 | xargs kill -9
```
