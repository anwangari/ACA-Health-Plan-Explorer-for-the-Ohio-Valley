# Deploying Marketplace Lens to Railway

A step-by-step guide to get a live, interactive URL for the presentation.
Approach: **Postgres on Railway, data loaded on deploy via a one-time API pull**
(your "Option B"). Built so a flaky live API call can't crash the demo.

> Timing: budget ~25-30 minutes the first time, plus ~5-10 min for the first
> deploy's build + data load. Do this well before you present.

---

## What these files do

| File | Purpose |
|------|---------|
| `requirements.txt` | Your existing deps **plus `gunicorn`** (the production web server). |
| `seed.py` | Release-phase script. Populates the DB **once**, reuses the cache after, and never hard-fails the deploy. Put this in the **repo root**. |
| `Procfile` | Tells Railway: run `python seed.py` on release, then serve with gunicorn. |
| `nixpacks.toml` | Forces `pip install -e .` so your `src/` package imports correctly. |
| `railway.json` | Pins the start command and a sane restart policy. |

Copy all five into your repository root (next to `pyproject.toml`), commit, push.

---

## Step 0 — One safety net first (do this on your laptop)

You said your pipeline runs locally. Before touching Railway, confirm it still
produces data end to end, because that same code runs on deploy:

```bash
python -m marketplace --no-extract   # reuse cache if you have one
# or a full run if you don't:
python -m marketplace
```

If that works locally, the deploy will work. If the live demo's API pull ever
misbehaves, you always have the local app (`python -m marketplace dashboard`)
as a fallback — same dashboard, just on your machine.

---

## Step 1 — Add the deployment files to your repo

From your repo root:

1. Replace `requirements.txt` with the one provided (it just adds `gunicorn`).
2. Add `seed.py`, `Procfile`, `nixpacks.toml`, `railway.json` to the root.
3. Commit and push to GitHub:

```bash
git add requirements.txt seed.py Procfile nixpacks.toml railway.json
git commit -m "Add Railway deployment config"
git push
```

> Your `data/` stays gitignored — that's fine. The DB is filled on Railway by
> `seed.py`, not from committed data.

---

## Step 2 — Create the Railway project + Postgres

1. Go to **railway.com**, log in, and link your GitHub account when prompted.
2. **New Project -> Deploy from GitHub repo -> pick your repo.**
   - Railway starts building immediately. It will likely **fail or crash-loop on
     this first attempt** because there's no database yet — that's expected.
3. In the project canvas: **Add -> Database -> PostgreSQL.** Railway provisions a
   managed Postgres service in a few seconds.

---

## Step 3 — Wire up environment variables

Your web service needs two variables. Click the **web service** tile -> **Variables**:

1. **`DATABASE_URL`** — reference Railway's Postgres. Railway exposes it as a
   variable on the Postgres service. In the web service, add a variable and use
   the reference picker, or paste the value. **Important:** your code uses the
   SQLAlchemy driver prefix `postgresql+psycopg2://`. Railway's default
   `DATABASE_URL` starts with `postgresql://`. Two clean options:

   - **Easiest:** add a variable named `DATABASE_URL` whose value is the Railway
     Postgres URL but with the scheme changed to `postgresql+psycopg2://`.
     You can reference the host/credentials Railway provides and just prepend the
     driver, e.g.
     `postgresql+psycopg2://${{Postgres.PGUSER}}:${{Postgres.PGPASSWORD}}@${{Postgres.RAILWAY_PRIVATE_DOMAIN}}:5432/${{Postgres.PGDATABASE}}`
   - The private domain (`RAILWAY_PRIVATE_DOMAIN`) keeps DB traffic internal and
     off your usage bill. Use it rather than the public proxy URL.

2. **`MARKETPLACE_API`** — your CMS Marketplace API key. `config.py` reads this
   exact name. Without it, the seed step can't pull plans.

> Sanity check: `config.py` reads `MARKETPLACE_API` and `DATABASE_URL`. Those are
> the only two names that matter.

---

## Step 4 — Generate a public URL

1. Web service -> **Settings -> Networking -> Generate Domain.**
2. Railway gives you a `*.up.railway.app` URL. That's the link you'll share /
   open during the presentation.

---

## Step 5 — Trigger a clean deploy and watch it seed

1. With Postgres added and variables set, redeploy: open the Command Palette
   (**Cmd/Ctrl + K -> Deploy Latest Commit**), or push any commit.
2. Watch the **Deploy logs**. You should see, in order:
   - Build: pip install + `pip install -e .`
   - **Release:** `[seed] Seeding database (skip_extract=False) ...` followed by
     extract -> transform -> load -> validate logs. This is the slow part
     (several hundred API calls); give it a few minutes.
   - `[seed] Pipeline complete and validated.`
   - **Web:** gunicorn boots and binds to the port.
3. Open your generated URL. The dashboard should load with real data.

---

## Step 6 — Verify before you present

- Open the URL in an incognito window (proves it works without your session).
- Set an age/income, pick a county, confirm the charts and table populate.
- Open it on your **phone** too — that's often how people in the room will try it.

---

## If something goes wrong

**Build fails on import (`No module named marketplace`)**
`nixpacks.toml` didn't run the editable install. Confirm the file is in the repo
root and committed. As a fallback, set the service **Start Command** in Settings
to exactly the gunicorn line from `railway.json`.

**Release/seed step errors but web still starts**
By design. The app falls back rather than crash-loop. If the DB ended up empty,
the dashboard shows empty states. Fix the cause (usually a missing
`MARKETPLACE_API` or a bad `DATABASE_URL` scheme), then **Deploy Latest Commit**
again — `seed.py` will retry.

**`could not translate host name` / DB connection refused**
The `DATABASE_URL` scheme or host is wrong. Make sure it's
`postgresql+psycopg2://...` and points at the Postgres service's private domain.

**Seeding is too slow / rate-limited live**
Pre-seed instead: from your laptop, set `DATABASE_URL` to Railway's **public**
Postgres URL (Settings -> Connect on the Postgres service) and run
`python -m marketplace --no-extract` locally. That fills Railway's DB from your
machine. Then `seed.py` sees the DB is already populated and skips the pull on
deploy. This is the safest path if you have 15 minutes before presenting.

**App loads but shows no data**
The DB is empty. Check the release logs for the seed result. Re-run the seed by
redeploying, or pre-seed from your laptop as above.

---

## Cost note

Railway has **no permanent free tier**. A new account gets a one-time **$5
credit (30 days)** and requires a payment method. A web service + small Postgres
can use a few dollars over a month, but for a single evening's demo the cost is
negligible. After the trial, services pause (data preserved) until you upgrade to
Hobby ($5/mo). If you only need it for tonight, you can delete the project
afterward to avoid any further usage.

---

## After the presentation (optional cleanup)

Project **Settings -> Danger -> Delete Project** removes the web service and
Postgres so nothing keeps accruing usage.
