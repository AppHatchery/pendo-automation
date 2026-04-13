# Pendo MAU Dashboard

A weekly-refreshed Monthly Active Users dashboard covering all AppHatchery Pendo subscriptions. Hosted on Cloudflare Pages with email-gated access via Cloudflare Zero Trust.

## Architecture

```
Pendo MCP (via Claude)
        │
        ▼
  data.json  ──►  generate_dashboard.py  ──►  index.html
                                                   │
                                            git push (manual)
                                                   │
                                            Cloudflare Pages
                                            (auto-deploys on push)
                                                   │
                                        Cloudflare Zero Trust Access
                                        (email allowlist, free tier)
```

**Why this setup?** The Pendo REST API aggregation endpoint requires a premium plan. Instead, a Claude scheduled task runs every Sunday night using the Pendo MCP tool to query MAU data directly, writes `data.json`, and regenerates `index.html`. The user reviews locally and runs `git push` Monday morning to publish.

## Weekly Refresh Flow

1. **Sunday ~10 PM local** — Claude scheduled task runs automatically:
   - Queries MAU for all apps across 4 windows (last 3 complete months + current MTD)
   - Writes `data.json`
   - Runs `python generate_dashboard.py --data data.json` to regenerate `index.html`
   - Makes a local git commit (does **not** push)

2. **Monday morning** — Review and publish:
   ```bash
   cd ~/GitHub/pendo-automation
   git log --oneline -3   # verify the commit looks right
   git push               # triggers Cloudflare Pages deployment
   ```

3. **Cloudflare Pages** auto-deploys within ~1 minute of the push.

## Manual Dashboard Regeneration

```bash
# From the repo root:
python generate_dashboard.py --data data.json
```

Or re-run the Claude scheduled task manually:
- Open Claude Code → sidebar → Scheduled Tasks → `pendo-mau-dashboard` → Run now

## Subscriptions & Apps

| Subscription | Apps | Pendo Sub ID |
|---|---|---|
| Trial Connection | iOS, Android | 4906408059535360 |
| MealPlanR | iOS, Android | 5306235578679296 |
| HomeTown | Hometown, HomeTown | 5407896868093952 |
| TB Guide | Android, iOS | 4781793898004480 |
| PulseOX *(AppHatchery)* | iOS, Android | 6552462672592896 |
| Fabla *(AppHatchery)* | Android, iOS | 6552462672592896 |
| LEP | iOS, Android | 4734766210416640 |
| AppHatchery-Tonsillectomy | iOS, Android | 5673257672966144 |
| TypeU | iOS, Android | 4744881717968896 |

> PulseOX and Fabla share the AppHatchery Pendo subscription but are displayed as separate sections in the dashboard.

## Cloudflare Setup

### Pages (hosting)

1. Go to **Cloudflare Dashboard → Workers & Pages → Create → Pages → Connect to Git**
2. Select the `AppHatchery/pendo-automation` repo
3. **Build settings:**
   - Framework preset: `None`
   - Build command: *(leave blank)*
   - Build output directory: *(leave blank — do NOT set to `.`)*
4. Save and deploy

The dashboard is served from `index.html` at the repo root. Cloudflare Pages detects it automatically when the build output directory field is empty.

**Issue encountered:** Setting the build output directory to `.` caused a *"Could not detect static files"* error. Fix: clear the field entirely and leave it blank.

### Zero Trust Access (email gate)

1. Go to **Cloudflare Zero Trust → Access → Applications → Add an application → Self-hosted**
2. Set the domain to your Pages URL (e.g. `pendo-automation.apphatcheryatemory.workers.dev`)
3. Under **Policies**, add an `Allow` rule with condition: `Emails → [list of allowed emails]`
4. Save

When a user visits the URL, they are prompted for their email. Cloudflare sends a one-time PIN. No passwords or accounts needed. Free for up to 50 users.

**Why not GitHub Pages?** GitHub Pages requires a paid plan for private repositories. Cloudflare Pages is free and works with both public and private repos.

## generate_dashboard.py Modes

### Mode 1 — Data file (used by the Claude scheduled task)

```bash
python generate_dashboard.py --data data.json
```

Reads pre-fetched MAU data from `data.json` (written by the Claude scheduled task). No API keys needed.

### Mode 2 — REST API (requires Pendo premium)

```bash
export PENDO_KEY_TRIAL_CONNECTION="..."
# ... set remaining keys ...
python generate_dashboard.py
```

Required env vars: `PENDO_KEY_TRIAL_CONNECTION`, `PENDO_KEY_MEALPLANR`, `PENDO_KEY_HOMETOWN`, `PENDO_KEY_TB_GUIDE`, `PENDO_KEY_APPHATCHERY`, `PENDO_KEY_LEP`, `PENDO_KEY_APPHATCHERY_TONSILLECTOMY`, `PENDO_KEY_TYPEU`.

The GitHub Actions workflow (`.github/workflows/weekly-dashboard.yml`) has this step commented out since the Pendo aggregation API requires a premium subscription.

## data.json Format

```json
{
  "generated": "YYYY-MM-DD",
  "windows": [
    ["Jan", false],
    ["Feb", false],
    ["Mar", false],
    ["Apr*", true]
  ],
  "apps": [
    {
      "sub": "Trial Connection",
      "color": "#0052cc",
      "name": "iOS",
      "plat": "ios",
      "mau": [3, 10, 15, 13]
    }
  ]
}
```

`plat` values: `"ios"`, `"android"`, `"none"`. The last `windows` entry with `true` is the current month-to-date.

## Known Issues & Notes

- **LEP Android app** (appId `6008038726107136`) shows zero MAU across all months — the app appears inactive in Pendo.
- **Tonsillectomy iOS** paused activity after January 2026, likely reflecting a study cycle gap. Android remains active.
- **HomeTown** apps have near-zero MAU; the subscription appears dormant.
- **Data ordering bug (resolved):** When querying all 80+ app×window combinations in a single parallel batch, Pendo MCP results returned out of order, causing app data to be assigned to the wrong app slots. Fixed by querying each app individually. The Claude scheduled task queries windows sequentially (all apps in parallel per window) to avoid this.
