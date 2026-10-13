#!/usr/bin/env python3
"""Render compare.py's JSON as a self-contained HTML report.

Example: python3 tools/compare/report.py build/compare.json build/compare.html
"""
import html, json, sys
from pathlib import Path

LANGUAGES = ('dyn', 'go', 'c', 'odin')
NAMES = {'dyn': 'Dyn', 'go': 'Go', 'c': 'C (clang)', 'odin': 'Odin'}
MODES = (('check', 'Check'), ('debug', 'Debug build'), ('release', 'Release build'))


def bars(groups, value_format, unit, width=560, bar=14, gap=2, group_gap=18, label_width=92):
    """Horizontal grouped bars on one linear axis. groups: [(label, {lang: value})]."""
    top = max((v for _, g in groups for v in g.values()), default=1) or 1
    plot = width - label_width - 76
    rows = []
    y = 4
    for label, values in groups:
        present = [l for l in LANGUAGES if l in values]
        height = len(present) * (bar + gap) - gap
        rows.append(f'<text class="group" x="0" y="{y + height / 2 + 4:.1f}">{html.escape(label)}</text>')
        for i, language in enumerate(present):
            value = values[language]
            length = max(8.0, value / top * plot)
            by = y + i * (bar + gap)
            tip = f'{NAMES[language]} · {label}: {value_format(value)} {unit}'
            rows.append(
                f'<g class="mark" data-tip="{html.escape(tip)}">'
                f'<rect class="hit" x="{label_width}" y="{by - 1}" width="{plot + 76}" height="{bar + 2}"/>'
                f'<path class="s-{language}" d="M{label_width},{by} h{length - 4:.1f} a4,4 0 0 1 4,4 v{bar - 8} a4,4 0 0 1 -4,4 h{-(length - 4):.1f} z"/>'
                f'<text class="value" x="{label_width + length + 6:.1f}" y="{by + bar - 3}">{value_format(value)}</text></g>')
        y += height + group_gap
    return (f'<svg class="chart" viewBox="0 0 {width} {y - group_gap + 8}" role="img">'
            f'<line class="axis" x1="{label_width}" x2="{label_width}" y1="0" y2="{y - group_gap + 6}"/>'
            + ''.join(rows) + '</svg>')


def legend():
    return '<div class="legend">' + ''.join(
        f'<span><i class="s-{l}"></i>{NAMES[l]}</span>' for l in LANGUAGES) + '</div>'


def table(head, rows):
    out = ['<table><thead><tr>' + ''.join(f'<th>{html.escape(h)}</th>' for h in head) + '</tr></thead><tbody>']
    for row in rows:
        out.append('<tr>' + ''.join(f'<td>{html.escape(str(c))}</td>' for c in row) + '</tr>')
    return ''.join(out) + '</tbody></table>'


def seconds(v):
    return f'{v:.2f}' if v < 10 else f'{v:.1f}'


def main():
    data = json.loads(Path(sys.argv[1]).read_text())
    output = Path(sys.argv[2])
    scale = data['scale']
    sizes = sorted({r['target_lines'] for r in scale})
    big = sizes[-1]
    by = {(r['target_lines'], r['language']): r for r in scale}
    sections = []

    # Compile throughput at the largest size, one panel per mode.
    panels = []
    for mode, title in MODES:
        groups = [(f'{size // 1000}k lines', {l: by[(size, l)][mode]['seconds'] for l in LANGUAGES if (size, l) in by})
                  for size in sizes]
        panels.append(f'<figure><figcaption>{title} — seconds, fresh, lower is better</figcaption>'
                      + bars(groups, seconds, 's') + '</figure>')
    rows = []
    for size in sizes:
        for l in LANGUAGES:
            r = by.get((size, l))
            if r:
                rows.append([f'{size:,}', NAMES[l], f"{r['lines']:,}"] +
                            [f"{r[m]['seconds']:.2f} s · {r['lines'] / r[m]['seconds'] / 1000:,.0f}k lines/s" for m, _ in MODES])
    sections.append('<section><h2>Compile and check time</h2>'
                    '<p class="note">The same generated program in each language: chains of modules, 40 functions each, '
                    'with loops, branches and calls. Go\'s check is <code>go vet</code>, which also runs analyzers. '
                    'C compiles one file per process in parallel; Dyn, Go and Odin use their own parallelism.</p>'
                    + legend() + '<div class="grid3">' + ''.join(panels) + '</div>'
                    '<details><summary>Table</summary>' + table(['Target lines', 'Language', 'Actual lines'] + [t for _, t in MODES], rows) + '</details></section>')

    # Compiler memory at the largest size.
    groups = [(title, {l: by[(big, l)][mode]['rss_mib'] for l in LANGUAGES if (big, l) in by}) for mode, title in MODES]
    rows = [[f'{size:,}', NAMES[l]] + [f"{by[(size, l)][m]['rss_mib']:.0f} MiB" for m, _ in MODES]
            for size in sizes for l in LANGUAGES if (size, l) in by]
    sections.append(f'<section><h2>Compiler peak memory at {big // 1000}k lines</h2>' + legend()
                    + '<figure><figcaption>Peak resident memory of the whole compiler process tree, MiB, lower is better</figcaption>'
                    + bars(groups, lambda v: f'{v:,.0f}', 'MiB') + '</figure>'
                    '<details><summary>Table, every size</summary>' + table(['Target lines', 'Language'] + [t for _, t in MODES], rows) + '</details></section>')

    # Run time and memory per benchmark.
    bench = data.get('benchmarks', [])
    programs = sorted({b['program'] for b in bench})
    bb = {(b['program'], b['language']): b for b in bench}
    describe = {'fib': 'recursive fib(38): calls', 'sieve': 'sieve to 100M: array loops',
                'sort': 'quicksort 10M u64: branches and swaps', 'hashmap': 'open-addressing table, 4M inserts and 8M lookups',
                'mandelbrot': '3000² Mandelbrot: float math', 'trees': 'binary trees to depth 18: allocation'}
    run_panels = ''.join(
        f'<figure><figcaption>{html.escape(describe.get(p, p))}</figcaption>'
        + bars([('run', {l: bb[(p, l)]['run_seconds'] for l in LANGUAGES if (p, l) in bb})], lambda v: f'{v:.3f}', 's', width=420, label_width=40)
        + '</figure>' for p in programs)
    mem_panels = ''.join(
        f'<figure><figcaption>{html.escape(p)}</figcaption>'
        + bars([('peak', {l: bb[(p, l)]['run_rss_mib'] for l in LANGUAGES if (p, l) in bb})], lambda v: f'{v:.1f}', 'MiB', width=420, label_width=40)
        + '</figure>' for p in programs)
    rows = [[p, NAMES[l], f"{bb[(p, l)]['run_seconds']:.3f} s", f"{bb[(p, l)]['run_rss_mib']:.1f} MiB",
             f"{bb[(p, l)]['binary_kib']:,.0f} KiB", bb[(p, l)]['output']] for p in programs for l in LANGUAGES if (p, l) in bb]
    sections.append('<section><h2>Run time</h2><p class="note">Release builds (Dyn <code>--release</code>, Go default, '
                    'clang <code>-O2</code>, Odin <code>-o:speed</code>), fastest of three runs. Every language prints the same answer. '
                    'Dyn and Odin keep bounds checks in release; Dyn also keeps overflow checks. Trees uses each language\'s usual '
                    'allocation: Dyn and Odin arenas, Go\'s GC, C malloc/free.</p>' + legend()
                    + '<div class="grid3">' + run_panels + '</div></section>')
    sections.append('<section><h2>Run-time peak memory</h2>' + legend() + '<div class="grid3">' + mem_panels + '</div>'
                    '<details><summary>Table, with binary sizes</summary>' + table(['Program', 'Language', 'Run time', 'Peak memory', 'Binary', 'Output'], rows) + '</details></section>')

    import re
    versions = ' · '.join(html.escape(re.sub(r' \(http[^)]*\)|/\S*/|version ', '', v)) for v in data['versions'].values())
    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Dyn vs Go, C and Odin</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>
.viz-root{{color-scheme:light;--surface-1:#fcfcfb;--text-primary:#0b0b0b;--text-secondary:#52514e;--grid:#e4e3df;
--s-dyn:#2a78d6;--s-go:#eb6834;--s-c:#1baf7a;--s-odin:#eda100}}
@media (prefers-color-scheme:dark){{:root:where(:not([data-theme="light"])) .viz-root{{color-scheme:dark;--surface-1:#1a1a19;
--text-primary:#f0efec;--text-secondary:#c3c2b7;--grid:#3a3a37;--s-dyn:#3987e5;--s-go:#d95926;--s-c:#199e70;--s-odin:#c98500}}}}
:root[data-theme="dark"] .viz-root{{color-scheme:dark;--surface-1:#1a1a19;--text-primary:#f0efec;--text-secondary:#c3c2b7;
--grid:#3a3a37;--s-dyn:#3987e5;--s-go:#d95926;--s-c:#199e70;--s-odin:#c98500}}
body{{margin:0}}.viz-root{{color:var(--text-primary);font:14px/1.45 system-ui,sans-serif}}
h1{{font-size:20px;margin:0 0 4px}}h2{{font-size:16px;margin:20px 0 6px}}h2:first-of-type{{margin-top:8px}}.note,.meta{{color:var(--text-secondary);max-width:900px}}
.meta{{font-size:12px}}figure{{margin:8px 0}}figcaption{{color:var(--text-secondary);font-size:12px;margin-bottom:4px}}
.grid3{{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:12px 24px}}
.chart{{width:100%;height:auto}}.chart text{{font-size:11px;fill:var(--text-secondary)}}.chart .group{{fill:var(--text-primary)}}
.chart .value{{fill:var(--text-primary)}}.axis{{stroke:var(--grid)}}.hit{{fill:transparent}}.mark:hover path{{opacity:.8}}
.s-dyn{{fill:var(--s-dyn);background:var(--s-dyn)}}.s-go{{fill:var(--s-go);background:var(--s-go)}}
.s-c{{fill:var(--s-c);background:var(--s-c)}}.s-odin{{fill:var(--s-odin);background:var(--s-odin)}}
.legend{{display:flex;gap:16px;font-size:12px;color:var(--text-secondary);margin:6px 0}}.legend i{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}}
table{{border-collapse:collapse;font-size:12px;margin-top:6px}}td,th{{border-bottom:1px solid var(--grid);padding:3px 10px;text-align:left}}
summary{{cursor:pointer;color:var(--text-secondary);font-size:12px;margin-top:6px}}
#tip{{position:fixed;pointer-events:none;background:var(--text-primary);color:var(--surface-1);padding:4px 8px;border-radius:4px;font-size:12px;display:none}}
</style></head><body><div class="viz-root">
<p class="meta">{versions} · {data['cpus']} CPUs · fresh builds, no caches</p>{''.join(sections)}<div id="tip"></div></div>
<script>const tip=document.getElementById('tip');document.querySelectorAll('.mark').forEach(m=>{{
m.addEventListener('mousemove',e=>{{tip.textContent=m.dataset.tip;tip.style.display='block';tip.style.left=(e.clientX+12)+'px';tip.style.top=(e.clientY+12)+'px'}});
m.addEventListener('mouseleave',()=>tip.style.display='none')}})</script></body></html>'''
    output.write_text(page)
    print(f'wrote {output}')


if __name__ == '__main__':
    main()
