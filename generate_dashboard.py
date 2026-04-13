#!/usr/bin/env python3
"""
Pendo MAU Dashboard Generator
==============================
Two modes:

  1. Data-file mode (no API key needed — used by the Claude scheduled task):
       python generate_dashboard.py --data data.json

     data.json format:
       {
         "generated": "2026-04-13",
         "windows": [["Jan", false], ["Feb", false], ["Mar", false], ["Apr*", true]],
         "apps": [
           {"sub": "Trial Connection", "color": "#0052cc",
            "name": "iOS", "plat": "ios", "mau": [3, 10, 15, 13]},
           ...
         ]
       }

  2. REST API mode (requires Pendo Integration API keys as env vars):
       python generate_dashboard.py

     Required environment variables:
       PENDO_KEY_TRIAL_CONNECTION, PENDO_KEY_MEALPLANR, PENDO_KEY_HOMETOWN,
       PENDO_KEY_TB_GUIDE, PENDO_KEY_APPHATCHERY, PENDO_KEY_LEP,
       PENDO_KEY_APPHATCHERY_TONSILLECTOMY, PENDO_KEY_TYPEU

Each key is found in Pendo under Settings → Integrations → API Keys.
"""

import calendar
import json
import os
import sys
from datetime import date, datetime, timezone

import requests

# ── Pendo endpoint ────────────────────────────────────────────────────────────
PENDO_AGGREGATION_URL = "https://app.pendo.io/api/v1/aggregation"
REQUEST_TIMEOUT = 30  # seconds

# ── Subscription / App catalog ────────────────────────────────────────────────
# appId values are stable; update only if you add/rename apps in Pendo.
CATALOG = [
    {
        "sub": "Trial Connection",
        "key_env": "PENDO_KEY_TRIAL_CONNECTION",
        "color": "#0052cc",
        "apps": [
            {"name": "iOS",     "appId": "6477767009042432", "plat": "ios"},
            {"name": "Android", "appId": "5776628160593920", "plat": "android"},
        ],
    },
    {
        "sub": "MealPlanR",
        "key_env": "PENDO_KEY_MEALPLANR",
        "color": "#36b37e",
        "apps": [
            {"name": "iOS",     "appId": "6073576902033408", "plat": "ios"},
            {"name": "Android", "appId": "6337677410631680", "plat": "android"},
        ],
    },
    {
        "sub": "HomeTown",
        "key_env": "PENDO_KEY_HOMETOWN",
        "color": "#ff8b00",
        "apps": [
            {"name": "Hometown", "appId": "4823276791398400", "plat": "none"},
            {"name": "HomeTown", "appId": "5848057001148416", "plat": "none"},
        ],
    },
    {
        "sub": "TB Guide",
        "key_env": "PENDO_KEY_TB_GUIDE",
        "color": "#6554c0",
        "apps": [
            {"name": "Android", "appId": "4715680644333568", "plat": "android"},
            {"name": "iOS",     "appId": "5777661572808704", "plat": "ios"},
        ],
    },
    {
        "sub": "AppHatchery",
        "key_env": "PENDO_KEY_APPHATCHERY",
        "color": "#00b8d9",
        "apps": [
            {"name": "PulseOX iOS",     "appId": "5744659150209024", "plat": "ios"},
            {"name": "PulseOX Android", "appId": "6210778495516672", "plat": "android"},
            {"name": "Fabla Android", "appId": "6261117648699392", "plat": "android"},
            {"name": "Fabla iOS",     "appId": "6332690795659264", "plat": "ios"},
        ],
    },
    {
        "sub": "LEP",
        "key_env": "PENDO_KEY_LEP",
        "color": "#de350b",
        "apps": [
            {"name": "iOS",     "appId": "5661434429112320", "plat": "ios"},
            {"name": "Android", "appId": "6008038726107136", "plat": "android"},
        ],
    },
    {
        "sub": "AppHatchery-Tonsillectomy",
        "key_env": "PENDO_KEY_APPHATCHERY_TONSILLECTOMY",
        "color": "#e35a00",
        "apps": [
            {"name": "iOS",     "appId": "6170654446518272", "plat": "ios"},
            {"name": "Android", "appId": "6301989379047424", "plat": "android"},
        ],
    },
    {
        "sub": "TypeU",
        "key_env": "PENDO_KEY_TYPEU",
        "color": "#8777d9",
        "apps": [
            {"name": "iOS",     "appId": "6227084461277184", "plat": "ios"},
            {"name": "Android", "appId": "6266562190049280", "plat": "android"},
        ],
    },
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def to_epoch_ms(d: date) -> int:
    """Convert a date to UTC midnight epoch milliseconds."""
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


def last_day_of(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def get_month_windows(n_complete: int = 3):
    """
    Return (n_complete) full calendar months + the current MTD window.
    Each entry: (label, start_date, end_date, is_mtd)
    """
    today = date.today()
    windows = []

    # Walk back n_complete months
    year, month = today.year, today.month
    for _ in range(n_complete):
        month -= 1
        if month == 0:
            month = 12
            year -= 1
        start = date(year, month, 1)
        end   = last_day_of(year, month)
        windows.insert(0, (start.strftime("%b"), start, end, False))

    # Current month MTD
    mtd_start = date(today.year, today.month, 1)
    windows.append((today.strftime("%b") + "*", mtd_start, today, True))
    return windows


def query_mau(api_key: str, app_id: str, start: date, end: date) -> int:
    """
    Query Pendo for unique active visitor count for app_id in [start, end].
    Uses the aggregation pipeline: visitors source → timeSeries filter → count.
    """
    payload = {
        "response": {"mimeType": "application/json"},
        "request": {
            "pipeline": [
                {
                    "source": {
                        "visitors": {"appId": app_id},
                        "timeSeries": {
                            "first":  to_epoch_ms(start),
                            "last":   to_epoch_ms(end),
                            "period": "dayRange",
                        },
                    }
                },
                {"count": None},
            ]
        },
    }
    try:
        resp = requests.post(
            PENDO_AGGREGATION_URL,
            headers={
                "X-Pendo-Integration-Key": api_key,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        if not resp.ok:
            print(
                f"  [WARN] HTTP {resp.status_code} for appId={app_id} "
                f"({start}→{end}): {resp.text[:200]}",
                file=sys.stderr,
            )
            return 0
        data = resp.json()
        return data.get("results", [{}])[0].get("count", 0)
    except Exception as exc:
        print(f"  [ERROR] appId={app_id} ({start}→{end}): {exc}", file=sys.stderr)
        return 0


# ── Data collection ───────────────────────────────────────────────────────────

def collect(windows):
    """Query every app for every window. Returns flat list of app result dicts."""
    results = []
    for sub_def in CATALOG:
        api_key = os.environ.get(sub_def["key_env"], "")
        sub_name = sub_def["sub"]

        if not api_key:
            print(
                f"[WARN] Missing secret {sub_def['key_env']} — "
                f"{sub_name} will show zeros.",
                file=sys.stderr,
            )

        for app in sub_def["apps"]:
            mau_list = []
            for label, start, end, is_mtd in windows:
                if api_key:
                    print(
                        f"  Querying {sub_name}/{app['name']}  {start} → {end}",
                        file=sys.stderr,
                    )
                    count = query_mau(api_key, app["appId"], start, end)
                else:
                    count = 0
                mau_list.append(count)

            results.append(
                {
                    "sub":   sub_name,
                    "color": sub_def["color"],
                    "name":  app["name"],
                    "plat":  app["plat"],
                    "mau":   mau_list,
                }
            )
    return results


# ── HTML generation ───────────────────────────────────────────────────────────

def build_html(app_data: list, windows: list) -> str:
    today_str   = date.today().strftime("%b %d, %Y")
    month_labels = [w[0] for w in windows]
    is_mtd_last  = windows[-1][3]

    # Compute summary totals
    totals   = [sum(a["mau"][i] for a in app_data) for i in range(len(windows))]
    # Jan–Mar trend (first 3 windows are complete months)
    pct_change = []
    for i in range(1, len(windows) - 1):  # skip MTD
        prev = totals[i - 1]
        curr = totals[i]
        pct  = round((curr - prev) / prev * 100, 1) if prev else 0
        pct_change.append((month_labels[i], curr, pct))

    active_apps = sum(1 for a in app_data if any(v > 0 for v in a["mau"]))

    sub_order = [s["sub"] for s in CATALOG]

    apps_json   = json.dumps(app_data)
    months_json = json.dumps(month_labels)
    totals_json = json.dumps(totals)
    colors_json = json.dumps({s["sub"]: s["color"] for s in CATALOG})

    # Summary cards for each window
    cards_html = ""
    for i, (label, start, end, is_mtd) in enumerate(windows):
        sub_line = ""
        if i > 0 and not is_mtd:
            prev = totals[i - 1]
            curr = totals[i]
            if prev:
                pct = round((curr - prev) / prev * 100, 1)
                sign = "+" if pct >= 0 else ""
                sub_line = f"{sign}{pct}% vs {month_labels[i-1]}"
            else:
                sub_line = "&nbsp;"
        elif is_mtd:
            sub_line = f"through {end.strftime('%b %d')}"
        else:
            sub_line = "All apps combined"

        cards_html += f"""
        <div class="sum-card">
          <div class="lbl">{label} MAU</div>
          <div class="val">{totals[i]:,}</div>
          <div class="sub">{sub_line}</div>
        </div>"""

    cards_html += f"""
        <div class="sum-card">
          <div class="lbl">Active Apps</div>
          <div class="val">{active_apps}</div>
          <div class="sub">of {len(app_data)} with any MAU</div>
        </div>"""

    mtd_note = f'<div class="apr-note">{month_labels[-1][:-1]} data is MTD (through {windows[-1][2].strftime("%b %d")})</div>' if is_mtd_last else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Pendo MAU Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #f0f2f5; color: #172b4d; }}
    header {{ background: #fff; border-bottom: 1px solid #dfe1e6; padding: 18px 32px;
              display: flex; align-items: center; justify-content: space-between; }}
    .brand {{ display: flex; align-items: center; gap: 12px; }}
    header h1 {{ font-size: 1.15rem; font-weight: 700; }}
    header .meta {{ font-size: 0.75rem; color: #6b778c; margin-top: 2px; }}
    .apr-note {{ font-size: 0.72rem; background: #fffae6; color: #974f0c;
                 border: 1px solid #ffe380; border-radius: 4px; padding: 5px 10px; }}
    main {{ max-width: 1280px; margin: 0 auto; padding: 24px 24px 52px; }}
    .section-label {{ font-size: 0.68rem; font-weight: 700; letter-spacing: 0.9px;
                      text-transform: uppercase; color: #6b778c; margin: 24px 0 10px; }}
    .summary-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
                    gap: 12px; margin-bottom: 4px; }}
    .sum-card {{ background: #fff; border: 1px solid #dfe1e6; border-radius: 10px; padding: 16px 18px; }}
    .sum-card .lbl {{ font-size: 0.68rem; font-weight: 700; text-transform: uppercase;
                      letter-spacing: 0.5px; color: #6b778c; }}
    .sum-card .val {{ font-size: 1.8rem; font-weight: 800; color: #172b4d; margin-top: 4px; line-height: 1; }}
    .sum-card .sub {{ font-size: 0.72rem; color: #6b778c; margin-top: 4px; }}
    .trend-box {{ background: #fff; border: 1px solid #dfe1e6; border-radius: 10px;
                  padding: 20px 24px; margin-bottom: 4px; }}
    .trend-box h3 {{ font-size: 0.85rem; font-weight: 700; margin-bottom: 14px; }}
    .sub-section {{ margin-bottom: 28px; }}
    .cards-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }}
    .app-card {{ background: #fff; border: 1px solid #dfe1e6; border-radius: 10px;
                 padding: 14px 16px 12px; border-top: 3px solid #dfe1e6; }}
    .app-card-top {{ display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px; }}
    .app-name {{ font-size: 0.82rem; font-weight: 700; color: #172b4d; }}
    .plat-badge {{ font-size: 0.62rem; font-weight: 700; padding: 2px 7px; border-radius: 10px;
                   letter-spacing: 0.2px; white-space: nowrap; }}
    .p-ios     {{ background: #e6f0ff; color: #0052cc; }}
    .p-android {{ background: #e3fcef; color: #006644; }}
    .p-none    {{ background: #f4f5f7; color: #6b778c; }}
    .mau-stat {{ display: flex; align-items: baseline; gap: 6px; margin-bottom: 10px; }}
    .mau-num {{ font-size: 1.6rem; font-weight: 800; line-height: 1; }}
    .mau-label {{ font-size: 0.7rem; color: #6b778c; }}
    .trend-pill {{ font-size: 0.68rem; font-weight: 700; padding: 2px 7px; border-radius: 10px; margin-left: auto; align-self: center; }}
    .up   {{ background: #e3fcef; color: #006644; }}
    .down {{ background: #ffebe6; color: #bf2600; }}
    .flat {{ background: #f4f5f7; color: #6b778c; }}
    .chart-wrap {{ height: 56px; position: relative; }}
    .month-labels {{ display: flex; justify-content: space-between; margin-top: 4px; }}
    .month-labels span {{ font-size: 0.6rem; color: #97a0af; }}
    .inactive-card {{ opacity: 0.45; }}
    .inactive-badge {{ font-size: 0.62rem; color: #97a0af; font-style: italic; }}
    footer {{ text-align: center; font-size: 0.7rem; color: #97a0af; margin-top: 32px; }}
    @media (max-width: 600px) {{ .summary-row {{ grid-template-columns: repeat(2,1fr); }} }}
  </style>
</head>
<body>
<header>
  <div class="brand">
    <svg width="30" height="30" viewBox="0 0 32 32" fill="none">
      <rect width="32" height="32" rx="8" fill="#FF4F00"/>
      <path d="M9 22V10h7a5 5 0 0 1 0 10h-3v2H9zm4-6h3a1 1 0 0 0 0-2h-3v2z" fill="#fff"/>
    </svg>
    <div>
      <h1>Monthly Active Users — All Subscriptions</h1>
      <div class="meta">3-month MAU trend &nbsp;·&nbsp; 8 subscriptions &nbsp;·&nbsp; {len(app_data)} apps &nbsp;·&nbsp; Updated {today_str}</div>
    </div>
  </div>
  {mtd_note}
</header>
<main>
  <div class="section-label">Overview</div>
  <div class="summary-row">{cards_html}</div>

  <div class="section-label">Combined MAU Trend</div>
  <div class="trend-box">
    <h3>Total MAU across all apps</h3>
    <canvas id="overallChart" height="70"></canvas>
  </div>

  <div id="subscriptions"></div>

  <footer>
    Pendo Automation &nbsp;·&nbsp; Generated {today_str}
    &nbsp;·&nbsp; Complete months shown in full; {month_labels[-1]} = month-to-date
  </footer>
</main>
<script>
const MONTHS  = {months_json};
const APPS    = {apps_json};
const TOTALS  = {totals_json};
const COLORS  = {colors_json};
const SUB_ORDER = {json.dumps([s["sub"] for s in CATALOG])};

// Overall bar chart
const barColors = MONTHS.map((_, i) => i === MONTHS.length - 1
  ? "rgba(255,143,0,0.18)" : "rgba(0,82,204,0.15)");
const borderColors = MONTHS.map((_, i) => i === MONTHS.length - 1 ? "#ff8b00" : "#0052cc");
new Chart(document.getElementById("overallChart"), {{
  type: "bar",
  data: {{
    labels: MONTHS,
    datasets: [{{
      label: "Total MAU", data: TOTALS,
      backgroundColor: barColors, borderColor: borderColors,
      borderWidth: 2, borderRadius: 5,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }},
      tooltip: {{ callbacks: {{ label: ctx => ` ${{ctx.parsed.y.toLocaleString()}} MAU` }} }} }},
    scales: {{
      y: {{ beginAtZero: true, ticks: {{ font: {{ size: 11 }} }}, grid: {{ color: "#f4f5f7" }} }},
      x: {{ ticks: {{ font: {{ size: 12 }} }}, grid: {{ display: false }} }}
    }}
  }}
}});

// Per-subscription app cards
const container = document.getElementById("subscriptions");
SUB_ORDER.forEach(subName => {{
  const apps = APPS.filter(a => a.sub === subName);
  if (!apps.length) return;
  const color = COLORS[subName] || "#6b778c";

  const lbl = document.createElement("div");
  lbl.className = "section-label";
  lbl.textContent = subName;
  container.appendChild(lbl);

  const grid = document.createElement("div");
  grid.className = "cards-grid";

  apps.forEach((app, idx) => {{
    const inactive = app.mau.every(v => v === 0);
    const latest   = app.mau[app.mau.length - 2]; // last complete month
    const prev     = app.mau[app.mau.length - 3];
    const change   = prev > 0 ? Math.round((latest - prev) / prev * 100) : null;
    let trendClass = "flat", trendText = "—";
    if (change !== null) {{
      if (change > 0)      {{ trendClass = "up";   trendText = `+${{change}}%`; }}
      else if (change < 0) {{ trendClass = "down";  trendText = `${{change}}%`; }}
      else                  {{ trendClass = "flat";  trendText = "0%"; }}
    }}
    const platLabel = app.plat === "ios" ? "iOS" : app.plat === "android" ? "Android" : "";
    const platClass = app.plat === "ios" ? "p-ios" : app.plat === "android" ? "p-android" : "p-none";

    const card = document.createElement("div");
    card.className = "app-card" + (inactive ? " inactive-card" : "");
    card.style.borderTopColor = color;
    card.innerHTML = `
      <div class="app-card-top">
        <div class="app-name">${{app.name}}</div>
        ${{platLabel ? `<span class="plat-badge ${{platClass}}">${{platLabel}}</span>` : ""}}
      </div>
      <div class="mau-stat">
        <span class="mau-num">${{inactive ? "—" : latest.toLocaleString()}}</span>
        <span class="mau-label">${{inactive ? "" : MONTHS[MONTHS.length-2] + " MAU"}}</span>
        ${{inactive
          ? `<span class="inactive-badge">no activity</span>`
          : `<span class="trend-pill ${{trendClass}}">${{trendText}}</span>`
        }}
      </div>
      <div class="chart-wrap"><canvas id="c-${{subName.replace(/\\s+/g,'-')}}-${{idx}}"></canvas></div>
      <div class="month-labels">${{MONTHS.map(m => `<span>${{m}}</span>`).join("")}}</div>
    `;
    grid.appendChild(card);

    requestAnimationFrame(() => {{
      const ctx = card.querySelector("canvas").getContext("2d");
      const maxVal = Math.max(...app.mau, 1);
      new Chart(ctx, {{
        type: "line",
        data: {{
          labels: MONTHS,
          datasets: [{{
            data: app.mau,
            borderColor: inactive ? "#dfe1e6" : color,
            borderWidth: 2,
            pointRadius: app.mau.map((_, i) => i === app.mau.length - 2 ? 3 : 2),
            pointBackgroundColor: inactive ? "#dfe1e6" : color,
            fill: true,
            backgroundColor: inactive ? "rgba(220,220,220,0.08)" : hexRgba(color, 0.08),
            tension: 0.3,
          }}]
        }},
        options: {{
          responsive: true, maintainAspectRatio: false,
          plugins: {{ legend: {{ display: false }}, tooltip: {{ enabled: !inactive }} }},
          scales: {{
            x: {{ display: false }},
            y: {{ display: false, beginAtZero: true, suggestedMax: maxVal * 1.2 }}
          }},
          animation: {{ duration: 300 }}
        }}
      }});
    }});
  }});

  container.appendChild(grid);
}});

function hexRgba(hex, a) {{
  const r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16);
  return `rgba(${{r}},${{g}},${{b}},${{a}})`;
}}
</script>
</body>
</html>"""


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", metavar="FILE",
                        help="Path to pre-fetched data.json (skips Pendo REST API calls)")
    args = parser.parse_args()

    if args.data:
        # ── Data-file mode (Claude scheduled task) ────────────────────────────
        print(f"Loading data from {args.data}…", file=sys.stderr)
        with open(args.data, encoding="utf-8") as fh:
            payload = json.load(fh)

        app_data = payload["apps"]
        # Reconstruct windows as (label, start_date, end_date, is_mtd)
        # We only need label + is_mtd for build_html; use dummy dates for the rest
        windows = []
        for label, is_mtd in payload["windows"]:
            windows.append((label, date.today(), date.today(), is_mtd))

    else:
        # ── REST API mode ─────────────────────────────────────────────────────
        print("Computing month windows…", file=sys.stderr)
        windows = get_month_windows(n_complete=3)
        for label, start, end, is_mtd in windows:
            print(f"  {label}: {start} → {end}{' (MTD)' if is_mtd else ''}", file=sys.stderr)

        print("\nQuerying Pendo…", file=sys.stderr)
        app_data = collect(windows)

    print("\nGenerating index.html…", file=sys.stderr)
    html = build_html(app_data, windows)

    out_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"Wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
