#!/usr/bin/env python3
"""Build a responsive, portable HTML dashboard from Scanner 5.0 JSON outputs.

Example:
  python trader-india/dashboard.py \
    --input "NSE Daily=trader/india-daily.json" \
    --input "NSE Intraday=trader/india-intraday.json" \
    --input "BSE Daily=trader/bse-daily.json" \
    --input "BSE Intraday=trader/bse-intraday.json" \
    --output trader/scanner-dashboard.html
"""
import argparse
import datetime
import html
import json
import os


def _load_rows(path):
    with open(path, encoding="utf-8") as source:
        data = json.load(source)

    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = data.get("results", data.get("signals", data.get("rows", [])))
        if isinstance(rows, dict):
            rows = list(rows.values())
        if not isinstance(rows, list):
            rows = [data] if data else []
    else:
        rows = []

    return [row for row in rows if isinstance(row, dict)]


def _scalar_columns(rows):
    return sorted({
        key
        for row in rows
        for key, value in row.items()
        if isinstance(value, (str, int, float, bool)) or value is None
    })


def _render_section(label, path):
    rows = _load_rows(path)
    columns = _scalar_columns(rows)
    safe_label = html.escape(label)
    safe_path = html.escape(path)

    if columns:
        headings = "".join(f"<th>{html.escape(str(column))}</th>" for column in columns)
        body_rows = []
        for row in rows:
            cells = []
            for column in columns:
                value = row.get(column, "")
                if value is None:
                    value = ""
                cells.append(f"<td>{html.escape(str(value))}</td>")
            body_rows.append("<tr>" + "".join(cells) + "</tr>")
        table = (
            "<div class='table-wrap'><table><thead><tr>"
            + headings
            + "</tr></thead><tbody>"
            + "".join(body_rows)
            + "</tbody></table></div>"
        )
    else:
        table = "<p class='empty'>No tabular records found in this input.</p>"

    return (
        "<section class='panel' data-label='"
        + safe_label.lower()
        + "'><div class='panel-head'><div><p class='eyebrow'>SCAN OUTPUT</p><h2>"
        + safe_label
        + "</h2><p class='source'>"
        + safe_path
        + "</p></div><span class='count'>"
        + str(len(rows))
        + " records</span></div>"
        + table
        + "</section>",
        len(rows),
    )


def build_dashboard(inputs, output):
    sections = []
    total_records = 0
    for label, path in inputs:
        section, count = _render_section(label, path)
        sections.append(section)
        total_records += count

    generated = html.escape(datetime.datetime.now().astimezone().strftime("%d %b %Y, %I:%M:%S %p %Z"))
    section_count = len(sections)
    document = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>Scanner 5.0 | Market Dashboard</title>
<style>
:root{font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#172033;background:#f3f6fb}
*{box-sizing:border-box}body{margin:0;min-width:320px}
.topbar{background:#101b31;color:#fff;padding:25px clamp(16px,4vw,48px)}
.topbar-inner,.content{max-width:1440px;margin:auto}
.brand{font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:#9fb4d8;font-weight:700}
h1{font-size:clamp(25px,4vw,38px);margin:8px 0 5px;letter-spacing:-.04em}
.subtitle{color:#c2cde0;margin:0;font-size:14px}
.content{padding:22px clamp(12px,3vw,36px) 40px}
.metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-bottom:18px}
.metric,.panel,.toolbar{background:#fff;border:1px solid #e4eaf3;border-radius:14px;box-shadow:0 4px 18px rgba(23,32,51,.045)}
.metric{padding:16px 18px}.metric-label{font-size:12px;color:#64748b;font-weight:650;text-transform:uppercase;letter-spacing:.06em}
.metric-value{font-size:27px;font-weight:750;margin-top:5px;letter-spacing:-.03em}
.toolbar{display:flex;gap:12px;align-items:center;justify-content:space-between;padding:12px;margin-bottom:16px;flex-wrap:wrap}
.tabs{display:flex;gap:7px;flex-wrap:wrap}
button{border:1px solid #dbe3ef;background:#f8fafc;color:#334155;border-radius:9px;padding:9px 13px;font:inherit;font-size:13px;font-weight:650;cursor:pointer}
button.active{background:#172b4d;color:#fff;border-color:#172b4d}
input{width:min(100%,310px);padding:10px 12px;border:1px solid #dbe3ef;border-radius:9px;font:inherit;font-size:13px;outline:none}
input:focus{border-color:#6687bc;box-shadow:0 0 0 3px #6687bc22}
.panel{padding:18px;margin-bottom:15px;overflow:hidden}
.panel-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:14px}
.eyebrow{font-size:10px;letter-spacing:.14em;color:#73839b;font-weight:750;margin:0 0 5px}
h2{font-size:18px;margin:0;letter-spacing:-.02em}
.source{font-size:11px;color:#8290a5;margin:5px 0 0;overflow-wrap:anywhere}
.count{font-size:12px;font-weight:700;color:#405574;background:#eef3fa;padding:7px 10px;border-radius:20px;white-space:nowrap}
.table-wrap{overflow:auto;max-width:100%;border:1px solid #e8edf4;border-radius:9px}
table{border-collapse:collapse;width:100%;font-size:12px}
th,td{padding:10px 12px;border-bottom:1px solid #e9eef5;text-align:left;white-space:nowrap}
th{position:sticky;top:0;background:#f1f5fa;color:#43536c;font-weight:750}
tbody tr:hover{background:#f8faff}tbody tr:last-child td{border-bottom:0}
.empty{color:#718096;font-size:13px;padding:10px 0}
.notice{font-size:12px;color:#68778d;line-height:1.6;margin:18px 2px 0}
footer{color:#8995a7;font-size:11px;margin-top:18px}
.hidden{display:none!important}
@media(max-width:640px){.metrics{grid-template-columns:1fr}.metric{padding:13px 15px}.metric-value{font-size:23px}.panel{padding:13px}.panel-head{align-items:flex-start}.toolbar{align-items:stretch}input{width:100%}}
</style>
</head>
<body>
<header class="topbar"><div class="topbar-inner">
<div class="brand">Scanner 5.0 · Research workspace</div>
<h1>Market Scanner Dashboard</h1>
<p class="subtitle">US · NSE · BSE | Daily scans, intraday signals and research outputs</p>
</div></header>
<main class="content">
<div class="metrics">
<div class="metric"><div class="metric-label">Data sections</div><div class="metric-value">"""
    document += str(section_count) + """</div></div>
<div class="metric"><div class="metric-label">Total records</div><div class="metric-value">"""
    document += str(total_records) + """</div></div>
<div class="metric"><div class="metric-label">Generated</div><div class="metric-value" style="font-size:17px;line-height:1.5">"""
    document += generated + """</div></div>
</div>
<div class="toolbar"><div class="tabs" role="group" aria-label="Filter exchange">
<button class="active" data-filter="all">All markets</button>
<button data-filter="nse">NSE</button><button data-filter="bse">BSE</button>
<button data-filter="us">US</button><button data-filter="other">Other</button>
</div><input id="search" type="search" placeholder="Search signals, symbols or values…" aria-label="Search dashboard"></div>
<div id="sections">"""
    document += "".join(sections)
    document += """</div>
<p class="notice"><strong>Data and execution notice:</strong> This dashboard displays the JSON files supplied to it; it does not fetch or verify live exchange data. Market data may be delayed, incomplete or unavailable depending on the upstream provider. Signals are research outputs, not guaranteed trade recommendations. Paper mode only - no orders are placed or transmitted.</p>
<footer>Scanner 5.0 · Offline HTML report · Generated """ + generated + """</footer>
</main>
<script>
const panels=[...document.querySelectorAll('.panel')];
const buttons=[...document.querySelectorAll('[data-filter]')];
const search=document.getElementById('search');
let filter='all';
function refresh(){
 const term=search.value.trim().toLowerCase();
 panels.forEach(panel=>{
  const label=panel.dataset.label||'';
  const market=label.includes('nse')?'nse':label.includes('bse')?'bse':(label.includes('us')||label.includes('nyse')||label.includes('nasdaq')?'us':'other');
  const marketMatch=filter==='all'||filter===market;
  const textMatch=!term||panel.textContent.toLowerCase().includes(term);
  panel.classList.toggle('hidden',!(marketMatch&&textMatch));
 });
}
buttons.forEach(button=>button.addEventListener('click',()=>{
 filter=button.dataset.filter;
 buttons.forEach(item=>item.classList.toggle('active',item===button));
 refresh();
}));
search.addEventListener('input',refresh);
</script>
</body></html>"""

    output_dir = os.path.dirname(os.path.abspath(output))
    os.makedirs(output_dir, exist_ok=True)
    with open(output, "w", encoding="utf-8") as target:
        target.write(document)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the Scanner 5.0 offline market dashboard.")
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        metavar="LABEL=PATH",
        help="JSON input with a display label; repeat for NSE, BSE or US outputs.",
    )
    parser.add_argument("--output", default="trader/scanner-dashboard.html")
    args = parser.parse_args(argv)

    pairs = []
    for item in args.input:
        if "=" not in item:
            parser.error("--input must use LABEL=PATH format")
        label, path = item.split("=", 1)
        if not label.strip() or not path.strip():
            parser.error("--input label and path cannot be empty")
        if not os.path.isfile(path):
            parser.error(f"input file does not exist: {path}")
        pairs.append((label.strip(), path.strip()))

    print(build_dashboard(pairs, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
