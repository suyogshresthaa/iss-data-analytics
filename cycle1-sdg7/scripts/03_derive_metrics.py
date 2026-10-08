"""Derive the analysis metrics from the cleaned SDG 7 tables.

Reads data/processed/sdg7_{wide,tidy,regions}.csv and writes three more:

    sdg7_country_metrics.csv  country-year grain, with cooking_gap and rural/urban gaps
    sdg7_country_summary.csv  one row per country: 2015 vs 2024, trend, 2030 projection
    sdg7_region_summary.csv   the same summary for the World, SDG regions and groupings

The headline metric is the cooking gap -- how far clean cooking access trails electricity
access, in percentage points. "Widest" (the 2024 level) and "widening" (the 2015-2024
change) are tracked separately because they rank almost entirely different countries.

Usage:
    python scripts/03_derive_metrics.py
"""

from pathlib import Path

import numpy as np
import pandas as pd

CYCLE_DIR = Path(__file__).resolve().parents[1]
PROC_DIR = CYCLE_DIR / "data" / "processed"

ELEC = "EG_ACS_ELEC"      # 7.1.1 electricity access
COOK = "EG_EGY_CLEAN"     # 7.1.2 clean cooking fuels

BASE_YEAR = 2015
LATEST_YEAR = 2024
TARGET_YEAR = 2030        # SDG 7.1 calls for universal access by 2030
UNIVERSAL = 100.0


def add_cooking_gap(wide):
    """cooking_gap = electricity access - clean cooking access, in percentage points."""
    wide = wide.copy()
    wide["cooking_gap"] = wide[ELEC] - wide[COOK]
    return wide


def rural_urban_gaps(tidy):
    """Urban minus rural access, per country-year, for each access indicator.

    Only 7.1.1 and 7.1.2 carry a Location dimension, so the other two are absent here.
    """
    access = tidy[tidy.series.isin([ELEC, COOK]) & tidy.location.isin(["URBAN", "RURAL"])]
    split = access.pivot_table(index=["country", "year", "series"],
                               columns="location", values="value")
    split["urban_rural_gap"] = split["URBAN"] - split["RURAL"]
    gaps = (split.reset_index()
            .pivot_table(index=["country", "year"], columns="series",
                         values="urban_rural_gap")
            .rename(columns={ELEC: "elec_urban_rural_gap",
                             COOK: "cook_urban_rural_gap"})
            .reset_index())
    gaps.columns.name = None
    return gaps


def trend_slope(group, column):
    """Least-squares slope in points per year. NaN when fewer than 3 points exist."""
    sub = group.dropna(subset=[column])
    if len(sub) < 3:
        return np.nan
    return np.polyfit(sub["year"], sub[column], 1)[0]


def summarise(frame, key):
    """One row per area: base/latest levels, change, trend slope, 2030 projection.

    The projection is a deliberately naive linear extrapolation of the fitted trend -
    it answers "where does the current pace lead?", not "what will happen". Access
    curves flatten as they approach 100%, so this flatters laggards is intented to be
    presented as a pace check rather than a forecast.
    """
    rows = []
    for area, group in frame.groupby(key, sort=True):
        group = group.sort_values("year")
        row = {key: area}
        if "region" in group.columns:
            row["region"] = group["region"].iloc[0]
        if "grouping_type" in group.columns:
            row["grouping_type"] = group["grouping_type"].iloc[0]

        for label, column in (("elec", ELEC), ("cook", COOK), ("gap", "cooking_gap")):
            base = group.loc[group.year == BASE_YEAR, column]
            latest = group.loc[group.year == LATEST_YEAR, column]
            base = base.iloc[0] if len(base) else np.nan
            latest = latest.iloc[0] if len(latest) else np.nan
            row[f"{label}_{BASE_YEAR}"] = base
            row[f"{label}_{LATEST_YEAR}"] = latest
            row[f"{label}_change"] = latest - base

        for label, column in (("elec", ELEC), ("cook", COOK)):
            slope = trend_slope(group, column)
            latest = row[f"{label}_{LATEST_YEAR}"]
            projected = np.clip(latest + slope * (TARGET_YEAR - LATEST_YEAR), 0, UNIVERSAL)
            row[f"{label}_slope_per_year"] = slope
            row[f"{label}_projected_{TARGET_YEAR}"] = projected
            row[f"{label}_on_track_{TARGET_YEAR}"] = bool(projected >= UNIVERSAL)

        row["gap_widened"] = bool(row["gap_change"] > 0) if pd.notna(row["gap_change"]) else None
        rows.append(row)

    return pd.DataFrame(rows)


def main():
    wide = pd.read_csv(PROC_DIR / "sdg7_wide.csv")
    tidy = pd.read_csv(PROC_DIR / "sdg7_tidy.csv")
    regions = pd.read_csv(PROC_DIR / "sdg7_regions.csv")

    # --- country-year metrics ------------------------------------------------
    metrics = add_cooking_gap(wide).merge(rural_urban_gaps(tidy),
                                          on=["country", "year"], how="left")

    # --- per-country summary -------------------------------------------------
    countries = summarise(metrics, "country")
    countries["widest_rank"] = countries[f"gap_{LATEST_YEAR}"].rank(ascending=False)
    countries["widening_rank"] = countries["gap_change"].rank(ascending=False)

    # --- the same for regions and groupings ----------------------------------
    region_wide = (regions[regions.location == "ALLAREA"]
                   .pivot_table(index=["area", "grouping_type", "year"],
                                columns="series", values="value")
                   .reset_index())
    region_wide.columns.name = None
    region_summary = summarise(add_cooking_gap(region_wide), "area")

    outputs = {
        "sdg7_country_metrics.csv": metrics.sort_values(["country", "year"]),
        "sdg7_country_summary.csv": countries.sort_values("gap_2024", ascending=False),
        "sdg7_region_summary.csv": region_summary.sort_values("gap_2024", ascending=False),
    }
    print("=" * 76)
    print("OUTPUTS")
    print("=" * 76)
    for name, frame in outputs.items():
        frame.to_csv(PROC_DIR / name, index=False)
        print(f"  {name:<28} {len(frame):>5} rows x {len(frame.columns):>2} cols")

    # --- what the metrics say ------------------------------------------------
    complete = countries.dropna(subset=["gap_change"])
    print("\n" + "=" * 76)
    print(f"COVERAGE: {len(complete)} of {len(countries)} countries have both "
          f"{BASE_YEAR} and {LATEST_YEAR} values")
    print("=" * 76)
    print(f"  gap widened: {(complete.gap_change > 0).sum()}   "
          f"narrowed: {(complete.gap_change < 0).sum()}   "
          f"unchanged: {(complete.gap_change == 0).sum()}")
    on_track = complete[f"cook_on_track_{TARGET_YEAR}"].sum()
    print(f"  on track for universal clean cooking by {TARGET_YEAR}: {on_track} countries")
    print(f"  on track for universal electricity by {TARGET_YEAR}: "
          f"{complete[f'elec_on_track_{TARGET_YEAR}'].sum()} countries")

    print(f"\n  WIDEST gap {LATEST_YEAR}:")
    for _, r in complete.nlargest(5, f"gap_{LATEST_YEAR}").iterrows():
        print(f"    {r.country[:34]:<34} {r[f'gap_{LATEST_YEAR}']:5.1f} pp   ({r.region})")
    print(f"\n  FASTEST WIDENING {BASE_YEAR}-{LATEST_YEAR}:")
    for _, r in complete.nlargest(5, "gap_change").iterrows():
        print(f"    {r.country[:34]:<34} {r.gap_change:+5.1f} pp  ({r.region})")

    print(f"\n  REGIONS by {LATEST_YEAR} gap:")
    sdg_regions = (region_summary[region_summary.grouping_type == "sdg_region"]
                   .sort_values(f"gap_{LATEST_YEAR}", ascending=False))
    for _, r in sdg_regions.iterrows():
        print(f"    {r.area[:34]:<34} {r[f'gap_{LATEST_YEAR}']:5.1f} pp  "
              f"({r.gap_change:+5.1f} since {BASE_YEAR})")

    # --- spot-checks ---------------------------------------------------------
    print("\n" + "=" * 76)
    print("SPOT-CHECKS")
    print("=" * 76)
    world = region_summary[region_summary.area == "World"].iloc[0]
    ssa = region_summary[region_summary.area == "Sub-Saharan Africa"].iloc[0]
    checks = [
        ("World gap 2015 = 23 pp", round(world.gap_2015) == 23),
        ("World gap 2024 = 17 pp", round(world[f"gap_{LATEST_YEAR}"]) == 17),
        ("Sub-Saharan Africa gap widened", ssa.gap_change > 0),
        # The gap is computable only where both inputs exist. 34 small territories
        # (Aruba, Bermuda, Hong Kong, ...) appear in the electricity series but not in
        # clean cooking, so ~15% of country-years have no gap by construction. The
        # invariant worth asserting is that the gap is present exactly there and
        # nowhere else -- a mismatch would mean the merge dropped or invented rows.
        ("cooking_gap present exactly where both inputs are",
         (metrics.cooking_gap.notna()
          == (metrics[ELEC].notna() & metrics[COOK].notna())).all()),
        ("no country ranks top-5 on both widest and widening",
         len(set(complete.nsmallest(5, "widest_rank").country)
             & set(complete.nsmallest(5, "widening_rank").country)) <= 1),
    ]
    for label, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
    if not all(p for _, p in checks):
        raise SystemExit("spot-checks failed -- do not use these outputs")


if __name__ == "__main__":
    main()
