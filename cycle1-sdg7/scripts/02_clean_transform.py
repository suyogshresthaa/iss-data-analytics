"""Clean and reshape the cached SDG 7 raw data into CSV tables.

Reads the JSON cached by 01_fetch_un_sdg.py and writes three CSVs to data/processed/:

    sdg7_tidy.csv     → long format, countries only, one row per country-year-indicator-location
    sdg7_regions.csv  → long format, World + the 7 SDG regions 
    sdg7_wide.csv     → one row per country-year, one column per indicator (all-areas only)

The important job here is separating real countries from regional aggregates. The API's
`Reporting Type` field does NOT do this - every row is "G". So the geographic tree is the 
only reliable signal: any node with children is an aggregate, leaves are countries.

An aggregate is a row where the "area" isn't a single country. It's a group of countries 
already summed up into one number by the UN.

Hierarchy: World → Sub-Saharan Africa (aggregate) → Eastern Africa (aggregate) → Rwanda (country)

Usage:
    python scripts/02_clean_transform.py
"""

import json
from pathlib import Path

import pandas as pd

CYCLE_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = CYCLE_DIR / "data" / "raw"
OUT_DIR = CYCLE_DIR / "data" / "processed"

# The tree's first root holds the official SDG regional hierarchy.
SDG_ROOT = "World (total) by SDG regions"

# Aggregates that appear in the data but not in the tree with matching spelling (the tree says
# "Least Developed Countries (LDC)", the data says "...(LDCs)"), plus "World", which is
# only ever a root label in the tree.
EXTRA_AGGREGATES = {
    "World",
    "Least Developed Countries (LDCs)",
    "Landlocked developing countries (LLDCs)",
    "Small island developing States (SIDS)",
}

# Development groupings worth charting alongside the SDG regions.
EXTRA_GROUPINGS = [
    "Least Developed Countries (LDCs)",
    "Landlocked developing countries (LLDCs)",
    "Small island developing States (SIDS)",
]

# Columns carried through to the tidy output, mapped to friendlier names.
KEEP = {
    "series": "series",
    "indicator": "indicator",
    "geoAreaCode": "m49_code",
    "geoAreaName": "area",
    "timePeriodStart": "year",
    "value": "value",
    "lowerBound": "lower_bound",
    "upperBound": "upper_bound",
    "dimensions.Location": "location",
    "attributes.Nature": "nature",
    "attributes.Units": "units",
    "source": "source",
}


def build_geo_lookup(tree):
    """Takes the geographic tree and returns:
        1. country -> SDG region (maps each country to its SDG region)
        2. set of every aggregate name

    Aggregates are collected from every root grouping (SDG regions, LDC, SIDS, ...) so
    that a name like "Least Developed Countries" is never mistaken for a country.
    """
    country_to_region = {}
    aggregates = set()

    def walk(node, region):
        children = node.get("children") or []
        if children:
            aggregates.add(node["geoAreaName"])
            for child in children:
                walk(child, region)
        elif node.get("type") != "Country":
            # A childless node is not automatically a country. The tree types a handful
            # of leaves "Region" (Channel Islands) or "Other areas" (Belgium and
            # Luxembourg) -- groupings with no children listed. 
            aggregates.add(node["geoAreaName"])
        elif region is not None:
            # A real country. Only record a region if we are inside the SDG hierarchy;
            # other roots would overwrite it with the wrong grouping.
            country_to_region.setdefault(node["geoAreaName"], region)

    for root in tree:
        inside_sdg = root["geoAreaName"] == SDG_ROOT
        aggregates.add(root["geoAreaName"])
        for region_node in root.get("children") or []:
            walk(region_node, region_node["geoAreaName"] if inside_sdg else None)

    return country_to_region, aggregates | EXTRA_AGGREGATES


def load_tidy():
    """Flatten every cached series into one long DataFrame.
    Loops over the cached "EG_*.json" files in the RAW_DIR and turns each 
    into a single DataFrame.
    """
    frames = []
    for path in sorted(RAW_DIR.glob("EG_*.json")):
        cached = json.loads(path.read_text())
        df = pd.json_normalize(cached["data"])      # flattens nested JSON structure

        # 7.2.1 and 7.3.1 have no urban/rural breakdown; give them the same schema
        # as the access series so every row can be read the same way.
        if "dimensions.Location" not in df.columns:
            df["dimensions.Location"] = "ALLAREA"

        df = df[[c for c in KEEP if c in df.columns]].rename(columns=KEEP)

        # `indicator` arrives as a one-element list; unwrap it so the CSV reads "7.1.1"
        # rather than "['7.1.1']" in Excel and Tableau.
        df["indicator"] = df["indicator"].map(
            lambda v: v[0] if isinstance(v, list) and v else v)
        frames.append(df)
        print(f"  loaded {cached['series_code']:<13} {len(df):>6} rows")

    return pd.concat(frames, ignore_index=True)     # combines all loaded DataFrames into one


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading cached series")
    tidy = load_tidy()
    rows_in = len(tidy)

    tree = json.loads((RAW_DIR / "geoarea_tree.json").read_text())
    country_to_region, aggregates = build_geo_lookup(tree)
    print(f"\nGeography: {len(country_to_region)} countries in the SDG hierarchy, "
          f"{len(aggregates)} aggregate names")

    # The API returns values as strings; everything numeric must be coerced explicitly.
    for col in ("value", "lower_bound", "upper_bound"):
        tidy[col] = pd.to_numeric(tidy[col], errors="coerce")   # convert string values to numeric, coercing errors to NaN
    tidy["year"] = tidy["year"].astype(int)     # convert year to integer
    tidy["area"] = tidy["area"].str.strip()     # remove leading and trailing whitespace from area names

    tidy["region"] = tidy["area"].map(country_to_region)    # map each area to its corresponding region
    tidy["area_type"] = "unclassified"     # initialize area_type as "unclassified" for all rows
    tidy.loc[tidy["area"].isin(aggregates), "area_type"] = "aggregate"     # mark areas that are aggregates
    tidy.loc[tidy["region"].notna(), "area_type"] = "country"     # mark areas that have a corresponding region as countries

    # --- QA -----------------------------------------------------------------
    print("\n" + "=" * 72)
    print("QA")
    print("=" * 72)
    counts = tidy.area_type.value_counts()
    for kind in ("country", "aggregate", "unclassified"):
        n_rows = counts.get(kind, 0)
        n_areas = tidy.loc[tidy.area_type == kind, "area"].nunique()
        print(f"  {kind:<14} {n_rows:>6} rows across {n_areas:>4} areas")

    unknown = sorted(tidy.loc[tidy.area_type == "unclassified", "area"].unique())
    if unknown:
        # Reported, never silently dropped -- these are usually small territories.
        print(f"\n  unclassified areas ({len(unknown)}), excluded from the country table:")
        for name in unknown:
            print(f"    - {name}")

    # The API encodes missing data as the literal string "NaN" (not JSON null, not an
    # empty string), paired with Nature="NA" (not available) or "N" (non-relevant).
    missing = tidy[tidy.value.isna()]
    print(f"\n  missing values dropped: {len(missing)} of {rows_in} rows "
          f"({len(missing) / rows_in:.1%})")
    for series, n in missing.series.value_counts().items():
        total = (tidy.series == series).sum()
        print(f"    {series:<14} {n:>4} of {total:>5} ({n / total:.1%})")
    tidy = tidy.dropna(subset=["value"])

    # Year-on-year jumps larger than this in an access indicator usually mean a
    # methodology revision or a new survey rather than real change on the ground.
    JUMP_PP = 20
    access = tidy[(tidy.area_type == "country") & (tidy.location == "ALLAREA")
                  & tidy.series.isin(["EG_ACS_ELEC", "EG_EGY_CLEAN"])]
    jumps = (access.sort_values("year")
             .assign(step=lambda d: d.groupby(["area", "series"]).value.diff())
             .query("step.abs() > @JUMP_PP"))
    print(f"\n  year-on-year jumps over {JUMP_PP} pp in access indicators: {len(jumps)}")
    for _, row in jumps.nlargest(5, "step", keep="all").head(5).iterrows():
        print(f"    {row.area} {row.series} {row.year - 1}->{row.year}: "
              f"{row.step:+.1f} pp (to {row.value:.1f})")

    # --- split and write ----------------------------------------------------
    # Split the tidy DataFrame into countries, regions, and wide format for output

    # Countries: filter to country rows, rename area -> country
    countries = tidy[tidy.area_type == "country"].copy()
    countries = countries.rename(columns={"area": "country"}).drop(columns="area_type")

    # Regions: filter to world + regions + groupings, keep area and region columns
    region_names = [c["geoAreaName"] for root in tree if root["geoAreaName"] == SDG_ROOT
                    for c in root["children"]]
    regions = tidy[tidy.area.isin(["World"] + region_names + EXTRA_GROUPINGS)].copy()
    regions["grouping_type"] = regions.area.map(
        lambda a: "world" if a == "World"
        else "sdg_region" if a in region_names
        else "development_grouping")
    regions = regions.drop(columns=["region", "area_type"])

    # Wide: all-areas only, one column per indicator. Rural/urban stays in the tidy file.
    wide = (countries[countries.location == "ALLAREA"]
            .pivot_table(index=["m49_code", "country", "region", "year"],
                         columns="series", values="value")
            .reset_index())
    wide.columns.name = None

    outputs = {
        "sdg7_tidy.csv": countries.sort_values(["country", "series", "year", "location"]),
        "sdg7_regions.csv": regions.sort_values(["area", "series", "year", "location"]),
        "sdg7_wide.csv": wide.sort_values(["country", "year"]),
    }
    print("\n" + "=" * 72)
    print("OUTPUTS")
    print("=" * 72)
    for name, frame in outputs.items():
        path = OUT_DIR / name
        frame.to_csv(path, index=False)
        print(f"  {name:<20} {len(frame):>6} rows x {len(frame.columns):>2} cols")

    print(f"\n  rows in: {rows_in}  ->  countries: {len(countries)}  "
          f"regions: {len(regions)}  (aggregates and territories held back)")
    print(f"  wide table covers {wide.country.nunique()} countries, "
          f"{wide.year.min()}-{wide.year.max()}")

    # --- validate against known published values -------------------------
    print("\n" + "=" * 72)
    print("SPOT-CHECKS")
    print("=" * 72)
    nepal = countries[(countries.country == "Nepal") & (countries.year == 2023)
                      & (countries.series == "EG_EGY_CLEAN")].set_index("location").value
    checks = [
        ("Nepal 2023 clean cooking, urban = 63", nepal.get("URBAN") == 63),
        ("Nepal 2023 clean cooking, rural = 24", nepal.get("RURAL") == 24),
        ("Nepal 2023 clean cooking, all areas = 44", nepal.get("ALLAREA") == 44),
        ("no aggregates leaked into the country table",
         not set(countries.country) & aggregates),
        ("every country has exactly one region", countries.region.notna().all()),
        ("every country is typed 'Country' in the tree",
         set(countries.country) <= set(country_to_region)),
    ]
    for label, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {label}")
    if not all(passed for _, passed in checks):
        raise SystemExit("spot-checks failed -- do not use these outputs")


if __name__ == "__main__":
    main()
