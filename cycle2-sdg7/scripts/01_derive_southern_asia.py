"""Derive the Cycle 2 tables: Southern Asia, one level below the SDG region.

Cycle 1 ranked Central and Southern Asia as the second-fastest narrowing region
(-12.7 pp). Cycle 2 asks whether that was the region or whether it was India, and then
looks at two things the regional figure cannot show: where the remaining deficit sits
inside countries, and what the renewable-share indicator is actually counting.

Reads Cycle 1's outputs -- nothing is re-fetched and nothing is copied:

    ../cycle1-sdg7/data/processed/sdg7_country_metrics.csv   country-year, all 4 series
    ../cycle1-sdg7/data/processed/sdg7_country_summary.csv   slopes, projections, ranks
    ../cycle1-sdg7/data/raw/{EG_ACS_ELEC,EG_EGY_CLEAN}.json  the UN's own sub-aggregates
    ../cycle1-sdg7/data/raw/geoarea_tree.json                Southern Asia membership

Writes four tables to data/processed/:

    sa_country_year.csv      9 countries x 10 years, both access series + gap + splits
    sa_country_summary.csv   per country: levels, change, slope, projection, plateau
    sa_subregion_year.csv    UN aggregates by year + the unweighted median country
    rnew_vs_cooking_2023.csv global cross-section, n=192, for the renewables finding

Why the raw JSON is read for the aggregates: Cycle 1's step 2 kept only the seven SDG
regions, so Southern Asia and Central Asia were filtered out. They are published by the
UN as population-weighted aggregates and must be taken as given -- a regional figure
cannot be rebuilt by averaging its countries, which is the whole point of Finding A.

Usage:  python scripts/01_derive_southern_asia.py
"""

import json
from pathlib import Path

import pandas as pd

CYCLE2 = Path(__file__).resolve().parents[1]
CYCLE1 = CYCLE2.parent / "cycle1-sdg7"
PROC1 = CYCLE1 / "data" / "processed"
RAW1 = CYCLE1 / "data" / "raw"
OUT = CYCLE2 / "data" / "processed"

ELEC = "EG_ACS_ELEC"      # 7.1.1 electricity access, %
COOK = "EG_EGY_CLEAN"     # 7.1.2 clean cooking fuels, %
RNEW = "EG_FEC_RNEW"      # 7.2.1 renewable share of final energy consumption, %
PRIM = "EG_EGY_PRIM"      # 7.3.1 energy intensity, MJ per constant 2021 PPP GDP

BASE_YEAR = 2015
LATEST_YEAR = 2024

# 7.2.1 and 7.3.1 come from IEA/UNSD energy balances, which lag the access series by a
# year: 2024 has 84 of 226 countries for RNEW against 226 for every earlier year. The
# renewables finding is therefore anchored to the last complete year, not to 2024.
RNEW_YEAR = 2023

# The SDG regional hierarchy. The tree carries the same areas under continental and MDG
# roots too, so the root is named explicitly to avoid matching a node three times.
SDG_ROOT = "World (total) by SDG regions"
SUBREGION = "Southern Asia"
SIBLING = "Central Asia"
PARENT = "Central and Southern Asia"

# Clean cooking is near-universal in a few of these countries, so "stopped improving"
# and "finished" look identical in the data. Anything at or above this level is treated
# as at the ceiling rather than stalled.
CEILING = 95.0


# ----------------------------------------------------------------------- geo membership

def subregion_members(root_name, region_name):
    """Country names under one region of one hierarchy, by the tree's own `type` field.

    Leaf-ness is not a usable test for countries -- Cycle 1 found childless nodes typed
    `Region` and `Other areas` -- so only nodes typed `Country` are taken.
    """
    tree = json.loads((RAW1 / "geoarea_tree.json").read_text())

    def find(nodes, target, path=()):
        for node in nodes:
            name = node.get("geoAreaName")
            if name == target and path and path[0] == root_name:
                return node
            hit = find(node.get("children") or [], target, path + (name,))
            if hit is not None:
                return hit
        return None

    node = find(tree, region_name)
    if node is None:
        raise SystemExit(f"{region_name!r} not found under {root_name!r}")
    members = [c["geoAreaName"] for c in (node.get("children") or [])
               if c.get("type") == "Country"]
    if not members:
        raise SystemExit(f"{region_name!r} has no children typed Country")
    return node, members


# --------------------------------------------------------------------- UN sub-aggregates

def un_aggregates(areas):
    """All-areas values for named aggregate areas, straight from the cached raw JSON.

    Values arrive as strings and missing ones as the literal "NaN", so every value goes
    through to_numeric(errors="coerce"). The Location dimension has to be pinned to
    ALLAREA or the urban and rural rows triple every figure.
    """
    frames = []
    for code in (ELEC, COOK):
        rows = json.loads((RAW1 / f"{code}.json").read_text())["data"]
        frame = pd.DataFrame(rows)
        frame["location"] = frame["dimensions"].apply(
            lambda d: (d or {}).get("Location") or "ALLAREA")
        frame = frame[frame.geoAreaName.isin(areas) & (frame.location == "ALLAREA")]
        frames.append(pd.DataFrame({
            "area": frame.geoAreaName,
            "year": pd.to_numeric(frame.timePeriodStart, errors="coerce").astype("Int64"),
            "series": code,
            "value": pd.to_numeric(frame.value, errors="coerce"),
        }))

    long = pd.concat(frames, ignore_index=True).dropna(subset=["value"])

    dupes = long.duplicated(subset=["area", "year", "series"]).sum()
    if dupes:
        raise SystemExit(f"{dupes} duplicate area-year-series rows -- pivot would average them")

    wide = (long.pivot(index=["area", "year"], columns="series", values="value")
            .reset_index())
    wide.columns.name = None
    wide["gap"] = wide[ELEC] - wide[COOK]
    return wide


# ------------------------------------------------------------------------ derived columns

def no_gain_since(series_by_year):
    """Earliest year whose clean cooking value the latest year has not beaten.

    A country at 31% in 2018 and 31% in 2024 has had no net gain for six years even
    though intermediate years were higher. Returns NA when the latest year is the
    highest, i.e. the country is still climbing.
    """
    latest = series_by_year.get(LATEST_YEAR)
    if pd.isna(latest):
        return pd.NA
    for year in sorted(series_by_year.index):
        if year < LATEST_YEAR and pd.notna(series_by_year[year]) \
                and series_by_year[year] >= latest:
            return year
    return pd.NA


def country_summary(country_year, cycle1_summary, members):
    """Per-country summary: Cycle 1's slopes and projections plus Cycle 2's own columns."""
    carry = [
        "country", "elec_2015", "elec_2024", "elec_change",
        "cook_2015", "cook_2024", "cook_change",
        "gap_2015", "gap_2024", "gap_change",
        "cook_slope_per_year", "cook_projected_2030", "cook_on_track_2030",
        "elec_slope_per_year", "elec_on_track_2030", "gap_widened",
        "widest_rank", "widening_rank",
    ]
    summary = (cycle1_summary[cycle1_summary.country.isin(members)][carry]
               .copy().reset_index(drop=True))

    cook_by_year = country_year.pivot(index="country", columns="year", values=COOK)
    summary["cook_no_gain_since"] = summary.country.map(
        cook_by_year.apply(no_gain_since, axis=1))
    summary["cook_at_ceiling"] = summary.cook_2024 >= CEILING

    latest = country_year[country_year.year == LATEST_YEAR].set_index("country")
    for column in ("elec_urban_rural_gap", "cook_urban_rural_gap", RNEW):
        summary[f"{column}_{LATEST_YEAR}"] = summary.country.map(latest[column])
    summary[f"{RNEW}_{RNEW_YEAR}"] = summary.country.map(
        country_year[country_year.year == RNEW_YEAR].set_index("country")[RNEW])

    # Rank within Southern Asia, widest 2024 gap first, so the deck can say "worst of
    # the nine" without the reader having to hold the global rank in mind.
    summary["sa_widest_rank"] = summary.gap_2024.rank(ascending=False, method="min")
    return summary.sort_values("gap_2024", ascending=False).reset_index(drop=True)


def rnew_cross_section(metrics):
    """Global renewable-share vs clean-cooking cross-section for the last complete year."""
    frame = (metrics[metrics.year == RNEW_YEAR][["country", "region", RNEW, COOK, ELEC]]
             .dropna(subset=[RNEW, COOK])
             .rename(columns={RNEW: "renewable_share", COOK: "clean_cooking",
                              ELEC: "electricity"})
             .reset_index(drop=True))
    frame["in_southern_asia"] = frame.country.isin(SA_MEMBERS)
    return frame.sort_values("renewable_share", ascending=False).reset_index(drop=True)


# -------------------------------------------------------------------------------- main

def main():
    OUT.mkdir(parents=True, exist_ok=True)

    _, members = subregion_members(SDG_ROOT, SUBREGION)
    _, siblings = subregion_members(SDG_ROOT, SIBLING)
    global SA_MEMBERS
    SA_MEMBERS = members
    print(f"Southern Asia membership from the geo tree ({len(members)}): "
          f"{', '.join(members)}")

    metrics = pd.read_csv(PROC1 / "sdg7_country_metrics.csv")
    cycle1_summary = pd.read_csv(PROC1 / "sdg7_country_summary.csv")

    missing = set(members) - set(metrics.country)
    if missing:
        raise SystemExit(f"countries in the tree but not in Cycle 1's metrics: {missing}")

    country_year = (metrics[metrics.country.isin(members)]
                    .drop(columns=["region"])
                    .sort_values(["country", "year"])
                    .reset_index(drop=True))
    summary = country_summary(country_year, cycle1_summary, members)
    subregion = un_aggregates([SUBREGION, SIBLING, PARENT, "World"])
    cross = rnew_cross_section(metrics)

    # Finding A in one number: the UN's population-weighted aggregate against the
    # unweighted median of the same nine countries. If the two disagree, the regional
    # figure is being set by the big countries rather than by the typical one.
    median_gap = (country_year.groupby("year").cooking_gap.median()
                  .rename("median_country_gap").reset_index())
    median_gap["area"] = f"{SUBREGION} (unweighted median)"
    median_gap = median_gap.rename(columns={"median_country_gap": "gap"})
    subregion = pd.concat([subregion, median_gap], ignore_index=True)

    tables = {
        "sa_country_year.csv": country_year,
        "sa_country_summary.csv": summary,
        "sa_subregion_year.csv": subregion,
        f"rnew_vs_cooking_{RNEW_YEAR}.csv": cross,
    }
    print("\nWROTE")
    for name, frame in tables.items():
        frame.to_csv(OUT / name, index=False)
        print(f"  {name:<28} {len(frame):>5} rows x {len(frame.columns):>2} cols")

    # ---------------------------------------------------------------- what they say
    sa_2015 = subregion[(subregion.area == SUBREGION) & (subregion.year == BASE_YEAR)].iloc[0]
    sa_2024 = subregion[(subregion.area == SUBREGION) & (subregion.year == LATEST_YEAR)].iloc[0]
    med_2015 = median_gap[median_gap.year == BASE_YEAR].gap.iloc[0]
    med_2024 = median_gap[median_gap.year == LATEST_YEAR].gap.iloc[0]

    print("\n" + "=" * 76)
    print("FINDING A -- was it the region, or was it India?")
    print("=" * 76)
    print(f"  UN population-weighted {SUBREGION} gap: "
          f"{sa_2015.gap:.1f} -> {sa_2024.gap:.1f} pp "
          f"({sa_2024.gap - sa_2015.gap:+.1f})")
    print(f"  Unweighted median of the same {len(members)} countries: "
          f"{med_2015:.1f} -> {med_2024:.1f} pp ({med_2024 - med_2015:+.1f})")
    widened = summary[summary.gap_change > 0]
    print(f"  countries whose gap widened: {len(widened)} of {len(summary)} "
          f"({', '.join(widened.country)})")
    print(f"\n  {'country':<28}{'gap15':>7}{'gap24':>7}{'change':>8}"
          f"{'cook24':>8}{'pp/yr':>7}")
    for _, r in summary.iterrows():
        print(f"  {r.country[:27]:<28}{r.gap_2015:>7.1f}{r.gap_2024:>7.1f}"
              f"{r.gap_change:>+8.1f}{r.cook_2024:>8.0f}{r.cook_slope_per_year:>7.2f}")

    print("\n" + "=" * 76)
    print("FINDING B -- the grid reached the villages; clean cooking did not")
    print("=" * 76)
    print(f"  {'country':<28}{'elec u-r':>10}{'cook u-r':>10}{'ratio':>8}")
    for _, r in summary.sort_values(f"cook_urban_rural_gap_{LATEST_YEAR}",
                                   ascending=False).iterrows():
        elec_ur = r[f"elec_urban_rural_gap_{LATEST_YEAR}"]
        cook_ur = r[f"cook_urban_rural_gap_{LATEST_YEAR}"]
        ratio = f"{cook_ur / elec_ur:>8.1f}" if pd.notna(elec_ur) and elec_ur > 0.5 else "       -"
        print(f"  {r.country[:27]:<28}{elec_ur:>10.1f}{cook_ur:>10.1f}{ratio}")

    print("\n" + "=" * 76)
    print(f"FINDING C -- what the renewable-share indicator is counting ({RNEW_YEAR})")
    print("=" * 76)
    pearson = cross.renewable_share.corr(cross.clean_cooking)
    spearman = cross.renewable_share.corr(cross.clean_cooking, method="spearman")
    print(f"  global n={len(cross)}   pearson={pearson:.3f}   spearman={spearman:.3f}")
    print(f"  {'country':<28}{'renew%':>8}{'cook%':>8}")
    for _, r in (cross[cross.in_southern_asia]
                 .sort_values("renewable_share", ascending=False).iterrows()):
        print(f"  {r.country[:27]:<28}{r.renewable_share:>8.1f}{r.clean_cooking:>8.0f}")

    print("\n  clean cooking has not gained since:")
    for _, r in summary[summary.cook_no_gain_since.notna()].iterrows():
        tag = " (at ceiling)" if r.cook_at_ceiling else ""
        print(f"    {r.country[:27]:<28}{int(r.cook_no_gain_since)}"
              f"   cook {LATEST_YEAR} = {r.cook_2024:.0f}%{tag}")

    # -------------------------------------------------------------------- spot-checks
    print("\n" + "=" * 76)
    print("SPOT-CHECKS")
    print("=" * 76)
    india = summary[summary.country == "India"].iloc[0]
    lanka = summary[summary.country == "Sri Lanka"].iloc[0]
    nepal = cross[cross.country == "Nepal"].iloc[0]
    parent_2015 = subregion[(subregion.area == PARENT) & (subregion.year == BASE_YEAR)].iloc[0]

    checks = [
        # Membership must be the UN's, not a hand-built list: 9 Southern Asia + 5
        # Central Asia has to reconstitute the 14 Cycle 1 put in the parent region.
        (f"{SUBREGION} has 9 countries, {SIBLING} 5",
         len(members) == 9 and len(siblings) == 5),
        ("sub-aggregates partition Cycle 1's parent region",
         len(members) + len(siblings) ==
         (pd.read_csv(PROC1 / "sdg7_country_summary.csv").region == PARENT).sum()),
        # Cycle 1 recorded the parent region's 2015 gap as 39.8 pp. Reading it back out
        # of the raw cache is the check that this script's aggregate path agrees with
        # the one step 2 used.
        ("parent region 2015 gap matches Cycle 1's 39.8 pp",
         round(parent_2015.gap, 1) == 39.8),
        ("every country-year has exactly 10 years",
         (country_year.groupby("country").year.nunique() == 10).all()),
        ("no duplicate country-year rows",
         not country_year.duplicated(subset=["country", "year"]).any()),
        # Finding A only stands if the two measures of the same nine countries move in
        # opposite directions. If the median also fell, the region really did improve.
        ("A: weighted aggregate narrows while median does not",
         (sa_2024.gap - sa_2015.gap) < -5 and (med_2024 - med_2015) > -1),
        ("A: India is the fastest clean-cooking gain of the nine",
         india.cook_slope_per_year == summary.cook_slope_per_year.max()),
        ("A: 4 of 9 widened", len(widened) == 4),
        # Finding B is a contrast, so it needs both halves: electricity essentially
        # equalised, cooking not remotely.
        ("B: electricity urban-rural gap under 2 pp in 5+ countries",
         (summary[f"elec_urban_rural_gap_{LATEST_YEAR}"].abs() < 2).sum() >= 5),
        ("B: cooking urban-rural gap over 25 pp in 6+ countries",
         (summary[f"cook_urban_rural_gap_{LATEST_YEAR}"] > 25).sum() >= 6),
        # Scoped to countries that still have a cooking deficit. The Maldives is at
        # 100% on both series, so both of its splits are 0.0 and a strict comparison
        # fails on a country that has nothing left to split. Loosening the test to >=
        # instead would pass trivially on those zeros and would stop catching a real
        # inversion, so the ceiling cases are excluded rather than the test weakened.
        ("B: cooking split exceeds electricity split wherever cooking is incomplete",
         (lambda below: (below[f"cook_urban_rural_gap_{LATEST_YEAR}"]
                         > below[f"elec_urban_rural_gap_{LATEST_YEAR}"]).all()
          and len(below) >= 7)(summary[~summary.cook_at_ceiling])),
        # Finding C anchors on a complete year and must not be an outlier artefact,
        # so Spearman has to agree with Pearson.
        (f"C: {RNEW_YEAR} cross-section covers 190+ countries", len(cross) >= 190),
        ("C: correlation negative on both Pearson and Spearman",
         pearson < -0.5 and spearman < -0.5),
        ("C: Nepal is high-renewable and low-clean-cooking",
         nepal.renewable_share > 60 and nepal.clean_cooking < 60),
        # Sri Lanka is the case the deck leans on: universal electricity, clean cooking
        # level with Afghanistan's, and no net gain for years.
        ("C: Sri Lanka at universal electricity but stalled cooking",
         lanka.elec_2024 >= 99 and pd.notna(lanka.cook_no_gain_since)
         and not lanka.cook_at_ceiling),
    ]
    for label, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
    if not all(p for _, p in checks):
        raise SystemExit("spot-checks failed -- do not use these outputs")


if __name__ == "__main__":
    main()
