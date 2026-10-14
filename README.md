# ISS Data Analytics Internship

Suyog Shrestha · Knox College · International Sibling Society (issNOW.earth)

Three project cycles, each ending in a live General Assembly presentation (Weeks 4, 7, 9).
Cycle 1 studies SDG 7; cycles 2 and 3 will study different SDGs.

| Cycle | Presented | SDG | Focus | Status |
|---|---|---|---|---|
| 1 | Week 4 | SDG 7 — Affordable & Clean Energy | The clean cooking gap | Complete |
| 2 | Week 7 | TBD | — | Not started |
| 3 | Week 9 | TBD | — | Not started |

## Cycle 1 — SDG 7

**Question:** *Since 2015, electricity access has expanded rapidly across the developing world.
Has clean cooking kept pace — and where is the gap widest and still growing?*

**Metric:** `cooking_gap = electricity access % − clean cooking %`, in percentage points.

**Answer:** Globally, yes — clean cooking gained 11 points against electricity's 4.9, and the gap
narrowed from 23 to 17. But that average hides a reversal: Sub-Saharan Africa is the only region
both widest (32.7 pp) and still widening (+7.9). "Widest" and "widening" name largely different
countries — only 3 of 15 overlap.

**Source:** UN SDG Global Indicators Database via API v5, 2015–2024, 228 countries, 16,216 rows.
Underlying providers: World Bank (7.1.1), WHO Global Health Observatory (7.1.2), UN SD / IEA
Energy Balances (7.2.1, 7.3.1).

### Reproducing it

```bash
python3 -m venv .venv && .venv/bin/pip install pandas requests openpyxl matplotlib jupyter
cd cycle1-sdg7
../.venv/bin/python3 scripts/01_fetch_un_sdg.py    # cached; --refresh to re-pull
../.venv/bin/python3 scripts/02_clean_transform.py # 6 spot-checks, fails loudly
../.venv/bin/python3 scripts/03_derive_metrics.py
../.venv/bin/python3 scripts/04_build_excel.py
```

Scripts are idempotent and run in numbered order. Nothing in `data/` is hand-edited.

### Layout

```
cycle1-sdg7/
├── scripts/                     # 01 fetch → 02 clean → 03 metrics → 04 excel
├── notebooks/eda.ipynb          # 6 charts, executed
├── data/raw/                    # cached API responses (gitignored)
├── data/processed/              # 6 CSVs — the Tableau and Excel source
├── outputs/
│   ├── sdg7_cycle1.xlsx         # Data · Top20_Gap · Data_Dictionary · QA
│   ├── matplotlib_figures/      # 6 PNGs
│   └── tableau/                 # 4 view exports + sdg7-cycle1.twbx
└── deck/                        # presentation PDF + speaker_note.txt
```
