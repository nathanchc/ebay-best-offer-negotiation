"""Part 5: sample size for the proposed experiment, using baselines measured in Parts 1-2.

Proposed test: when a buyer is about to send an offer, show a prompt to add a short message (treatment) or not (control).
Primary metric: share of negotiations that end in a deal. Guardrails: deal price as share of list price, seller reply rate,
share ending unanswered.

Two randomisation units are compared:
  * buyer-level: simple and powerful, but buyers on the same listing compete (Part 4), so a treated buyer's win can be a
    control buyer's loss and the measured lift overstates the marketplace gain;
  * listing-level (all buyers on a listing get the same arm): removes within-listing competition between arms, at the
    cost of clustering (design effect).
Usage (repo root): python -I scripts/06_experiment_design.py
"""
import pathlib, math
import duckdb
import pandas as pd
from statsmodels.stats.power import NormalIndPower
from statsmodels.stats.proportion import proportion_effectsize

ROOT = pathlib.Path(__file__).resolve().parents[1]
T = ROOT / "reports" / "tables"
kpi = pd.read_csv(T / "p1_kpis.csv").set_index("segment")

con = duckdb.connect()
con.execute("SET enable_progress_bar=false")
# Mean buyers per listing and intra-listing correlation of the deal outcome, for the listing-level design effect.
stats = con.sql(f"""
WITH s AS (SELECT anon_item_id, deal, clothing FROM read_parquet('{ROOT}/data/processed/negotiations.parquet')
           WHERE open_msg IS NOT NULL AND list_price > 0),
     l AS (SELECT anon_item_id, any_value(clothing) clothing, count(*) m, avg(deal) p FROM s GROUP BY 1)
SELECT clothing, avg(m) AS mean_buyers, sum(m * m) / sum(m) AS size_weighted_buyers,
       (SELECT avg(deal) FROM s) AS p_all
FROM l GROUP BY ROLLUP (clothing)""").df()
print(stats)

power = NormalIndPower()
rows = []
for seg in ["All categories", "Clothing, Shoes & Acc."]:
    p0 = float(kpi.loc[seg, "deal_rate"])
    for lift_pp in (0.5, 1.0, 2.0):
        es = proportion_effectsize(p0 + lift_pp / 100, p0)
        n = power.solve_power(effect_size=es, alpha=0.05, power=0.8, ratio=1.0, alternative="two-sided")
        rows.append({"segment": seg, "baseline_deal_rate": p0, "minimum_detectable_lift_pp": lift_pp,
                     "negotiations_per_arm_buyer_level": math.ceil(n)})
out = pd.DataFrame(rows)

# Listing-level: design effect = 1 + (m_bar - 1) * ICC. ICC of 'deal' within listing is negative-ish because only one
# buyer can win; we bound it conservatively with ICC in {0.0, 0.1} and use the size-weighted mean cluster size.
m_bar = float(stats.loc[stats["clothing"].isna(), "size_weighted_buyers"].iloc[0])
for icc in (0.0, 0.1):
    out[f"negotiations_per_arm_listing_level_icc{icc}"] = (out["negotiations_per_arm_buyer_level"] * (1 + (m_bar - 1) * icc)).round().astype(int)
out["size_weighted_buyers_per_listing"] = round(m_bar, 2)
out.to_csv(T / "p5_sample_size.csv", index=False)
print(out.to_string(index=False))
