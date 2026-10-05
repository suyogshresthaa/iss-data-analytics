# ISS Data Analytics Internship

Suyog Shrestha · Knox College · International Sibling Society (issNOW.earth)

Three project cycles, each studying a different UN Sustainable Development Goal. Every cycle
produces a cleaned dataset, a dashboard, a General Assembly slide deck, and a podcast segment.

| Cycle | Weeks | SDG | Focus | Status |
|---|---|---|---|---|
| 1 | 3–4 | SDG 7 — Affordable & Clean Energy | The clean cooking gap | In progress |
| 2 | 6–7 | TBD | — | Not started |
| 3 | 8–9 | TBD | — | Not started |

## Cycle 1 — SDG 7

**Question:** The world is electrifying faster than it is cleaning up its kitchens.
Who is being left behind?

Electricity access (SDG indicator 7.1.1) has risen steadily since 2015, while access to clean
cooking fuels (7.1.2) has stalled across much of South Asia and Sub-Saharan Africa. This project
measures the distance between those two curves — globally, by region, and rural versus urban.

**Primary source:** UN Statistics Division SDG API (v5),
`https://unstats.un.org/sdgs/UNSDGAPIV5/v1/sdg`

### Layout

```
cycle1-sdg7/
├── scripts/      # extraction, cleaning, Excel build — run in numbered order
├── notebooks/    # exploratory analysis
├── data/raw/     # cached API responses (gitignored)
├── data/processed/
├── outputs/figures/
├── deck/         # General Assembly slides
└── podcast/      # script + English summary
```

## Reference

- `project_template.pdf` — ISS deliverable specification (deck structure, protocol, grading)
- `CLAUDE.md` — working context, verified API details, and conventions
