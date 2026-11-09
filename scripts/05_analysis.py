"""Parts 1-4 of the case. Reads data/processed/negotiations.parquet, writes reports/tables/*.csv.

Part 1  KPI definitions and baseline values (all categories vs Clothing, Shoes & Accessories)
Part 2  Is a message on the opening offer associated with closing the deal?  Three comparisons, each stricter:
          a) raw gap
          b) cell-matched gap: same category x list-price band x opening-discount band x buyer and seller
             experience x condition, weighted to the message senders
          c) same-listing comparison: buyers bargaining over the SAME listing (listing fixed effects),
             controlling for the opening discount and buyer experience; SE clustered by seller
Part 3  Where negotiations are lost (funnel of opening-offer outcomes, near-miss auto-declines, reply speed)
Part 4  Seller side: price concession with vs without a message, and competition between buyers on one listing

Usage (repo root): python -I scripts/05_analysis.py
"""
import json, os, pathlib
import duckdb
import numpy as np
import pandas as pd
import statsmodels.api as sm

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "tables"
OUT.mkdir(parents=True, exist_ok=True)
con = duckdb.connect()
con.execute(f"SET memory_limit='5GB'; SET temp_directory='{ROOT}/data/processed/tmp'; SET enable_progress_bar=false")
# SMOKE=1 runs everything on a 1% sample of listings (fast code check); tables then go to reports/tables_smoke/.
SMOKE = os.environ.get("SMOKE") == "1"
if SMOKE:
    OUT = ROOT / "reports" / "tables_smoke"; OUT.mkdir(parents=True, exist_ok=True)
con.execute(f"""CREATE VIEW n AS SELECT * FROM read_parquet('{ROOT}/data/processed/negotiations.parquet')
               {"WHERE hash(anon_item_id) % 100 = 7" if SMOKE else ""}""")

# Analysis sample: opening offer observed, listing matched, positive list price, opening offer at or below list price.
con.execute("""
CREATE VIEW s AS SELECT *,
  CASE WHEN byr_hist IS NULL THEN 'unknown' WHEN byr_hist < 10 THEN '1-9' WHEN byr_hist < 50 THEN '10-49' ELSE '50+' END AS byr_exp,
  CASE WHEN slr_hist < 10 THEN '0-9' WHEN slr_hist < 100 THEN '10-99' WHEN slr_hist < 1000 THEN '100-999' ELSE '1000+' END AS slr_exp,
  CASE WHEN list_price < 10 THEN '<$10' WHEN list_price < 25 THEN '$10-24' WHEN list_price < 50 THEN '$25-49'
       WHEN list_price < 100 THEN '$50-99' WHEN list_price < 250 THEN '$100-249' ELSE '$250+' END AS price_band,
  least(floor(open_ratio * 10), 9)::INT AS disc_band,          -- opening offer as share of list price, deciles 0-9
  (item_cndtn_id < 2000)::INT AS is_new
FROM n
WHERE list_price > 0 AND open_price > 0 AND open_ratio <= 1 AND open_msg IS NOT NULL
""")
results = {}


def save(df: pd.DataFrame, name: str) -> pd.DataFrame:
    df.to_csv(OUT / f"{name}.csv", index=False)
    print(f"\n== {name}\n{df.to_string(index=False)}")
    return df


# ---------------------------------------------------------------- Part 1: KPIs
kpi = con.sql("""
SELECT CASE WHEN clothing = 1 THEN 'Clothing, Shoes & Acc.' ELSE 'Other categories' END AS segment,
  count(*)                                                   AS negotiations,
  avg(deal)                                                  AS deal_rate,
  median(open_ratio)                                         AS median_opening_offer_pct_of_list,
  median(deal_ratio) FILTER (WHERE deal = 1)                 AS median_deal_price_pct_of_list,
  avg(n_offers)                                              AS avg_offers_per_negotiation,
  avg((n_seller_counters > 0)::INT)                          AS share_with_seller_counter,
  avg((last_status = 0)::INT)                                AS share_ending_unanswered,
  median(open_resp_hrs) FILTER (WHERE open_status IN (1, 2)) AS median_hrs_to_manual_reply,
  avg((open_status IN (6, 9))::INT)                          AS share_opening_handled_automatically,
  avg(open_msg)                                              AS share_opening_with_message
FROM s GROUP BY ROLLUP (1) ORDER BY 1 NULLS LAST
""").df()
kpi["segment"] = kpi["segment"].fillna("All categories")
save(kpi, "p1_kpis")

# ---------------------------------------------------------------- Part 2a: raw gap
raw = con.sql("""
SELECT CASE WHEN clothing = 1 THEN 'Clothing' ELSE 'Other' END AS segment, open_msg,
       count(*) AS negotiations, avg(deal) AS deal_rate, median(open_ratio) AS median_open_ratio
FROM s GROUP BY ALL ORDER BY ALL""").df()
save(raw, "p2a_raw_gap")

# ---------------------------------------------------------------- Part 2b: cell-matched gap (weighted to message senders)
CELL = "meta_categ_id, price_band, disc_band, byr_exp, slr_exp, is_new"


def matched_gap(where: str = "TRUE") -> dict:
    r = con.sql(f"""
    WITH c AS (
      SELECT {CELL},
             count(*) FILTER (WHERE open_msg = 1) AS n1, avg(deal) FILTER (WHERE open_msg = 1) AS p1,
             count(*) FILTER (WHERE open_msg = 0) AS n0, avg(deal) FILTER (WHERE open_msg = 0) AS p0
      FROM s WHERE {where} GROUP BY ALL)
    SELECT sum(n1 * (p1 - p0)) / sum(n1)                              AS gap,
           sqrt(sum(n1 * n1 * (p1 * (1 - p1) / n1 + p0 * (1 - p0) / n0)) / pow(sum(n1), 2)) AS se,
           sum(n1) AS n_msg_matched,
           (SELECT count(*) FROM s WHERE open_msg = 1 AND {where}) AS n_msg_total,
           count(*) AS cells
    FROM c WHERE n1 > 0 AND n0 > 0""").df().iloc[0]
    return {k: float(v) for k, v in r.items()}


rows = []
for label, where in [("All categories", "TRUE"), ("Clothing", "clothing = 1"), ("Other", "clothing = 0"),
                     ("List price < $25", "list_price < 25"), ("List price $25-99", "list_price >= 25 AND list_price < 100"),
                     ("List price $100+", "list_price >= 100")]:
    raw_gap = con.sql(f"SELECT avg(deal) FILTER (WHERE open_msg=1) - avg(deal) FILTER (WHERE open_msg=0) FROM s WHERE {where}").fetchall()[0][0]
    m = matched_gap(where)
    rows.append({"segment": label, "raw_gap": raw_gap, "matched_gap": m["gap"], "matched_se": m["se"],
                 "share_msg_senders_matched": m["n_msg_matched"] / m["n_msg_total"], "cells": int(m["cells"])})
save(pd.DataFrame(rows), "p2b_matched_gap")

# ---------------------------------------------------------------- Part 2c: same-listing comparison (listing fixed effects)
# Listings with 2+ negotiations and both message and no-message openings. A 1-in-5 hash sample of such listings keeps
# memory within an 8 GB laptop; listings (not negotiations) are sampled so each listing keeps all its buyers.
con.execute("""
CREATE TEMP TABLE fe AS
WITH m AS (
  SELECT anon_item_id FROM s GROUP BY 1
  HAVING count(*) >= 2 AND min(open_msg) = 0 AND max(open_msg) = 1 AND hash(anon_item_id::VARCHAR || '-fe') % 5 = 0)
SELECT s.anon_item_id, s.anon_slr_id, s.clothing, s.deal, s.open_msg, s.disc_band, s.byr_exp, s.list_price, s.open_ts,
       row_number() OVER (PARTITION BY s.anon_item_id ORDER BY s.open_ts) AS arrival_order
FROM s JOIN m USING (anon_item_id)
""")


def within_listing(df: pd.DataFrame) -> dict:
    X = pd.get_dummies(df[["disc_band", "byr_exp"]].astype(str), drop_first=True, dtype=float)
    X["open_msg"] = df["open_msg"].astype(float)
    X["first_to_arrive"] = (df["arrival_order"] == 1).astype(float)
    y = df["deal"].astype(float)
    g = df["anon_item_id"]
    Xd = X - X.groupby(g).transform("mean")
    yd = y - y.groupby(g).transform("mean")
    fit = sm.OLS(yd, Xd).fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(df["anon_slr_id"])[0]})
    return {"coef": float(fit.params["open_msg"]), "se": float(fit.bse["open_msg"]),
            "negotiations": int(len(df)), "listings": int(g.nunique()),
            "base_rate_no_msg": float(y[df["open_msg"] == 0].mean())}


fe = con.sql("SELECT * FROM fe").df()
rows = []
for label, mask in [("All categories", np.ones(len(fe), bool)), ("Clothing", fe["clothing"] == 1),
                    ("List price < $25", fe["list_price"] < 25), ("List price $25-99", fe["list_price"].between(25, 99.9999)),
                    ("List price $100+", fe["list_price"] >= 100)]:
    rows.append({"segment": label, **within_listing(fe[mask].reset_index(drop=True))})
save(pd.DataFrame(rows), "p2c_same_listing")
del fe

# ---------------------------------------------------------------- Part 3: where negotiations are lost
funnel = con.sql("""
SELECT CASE open_status WHEN 1 THEN 'Accepted by seller' WHEN 9 THEN 'Auto-accepted (above seller threshold)'
         WHEN 6 THEN 'Auto-declined (below seller threshold)' WHEN 2 THEN 'Declined by seller'
         WHEN 7 THEN 'Seller countered' WHEN 0 THEN 'No reply within 48h'
         WHEN 8 THEN 'Lost: seller accepted another buyer' END AS opening_offer_outcome,
       count(*) AS negotiations, count(*) / sum(count(*)) OVER () AS share,
       avg(deal) AS eventual_deal_rate, avg((n_openings > 1)::INT) AS share_buyer_reopened
FROM s GROUP BY 1 ORDER BY negotiations DESC""").df()
save(funnel, "p3_opening_funnel")

near = con.sql("""
SELECT CASE WHEN open_price >= 0.9 * decline_price THEN 'within 10% of threshold'
            WHEN open_price >= 0.75 * decline_price THEN '10-25% below'
            ELSE 'more than 25% below' END AS distance_to_auto_decline_threshold,
       count(*) AS auto_declined_openings, avg((n_openings > 1)::INT) AS share_reopened, avg(deal) AS eventual_deal_rate
FROM s WHERE open_status = 6 AND decline_price > 0 GROUP BY 1 ORDER BY 1""").df()
save(near, "p3_near_miss_auto_declines")

counter = con.sql("""
SELECT CASE WHEN last_status = 0 AND last_offer_type = 2 THEN 'Buyer never answered seller counter'
            WHEN deal = 1 THEN 'Deal' WHEN lost_to_other_buyer = 1 THEN 'Lost to another buyer'
            ELSE 'Declined / other' END AS outcome_after_seller_counter,
       count(*) AS negotiations, count(*) / sum(count(*)) OVER () AS share
FROM s WHERE open_status = 7 GROUP BY 1 ORDER BY 2 DESC""").df()
save(counter, "p3_after_seller_counter")

speed = con.sql("""
SELECT CASE WHEN open_resp_hrs < 1 THEN 'a <1h' WHEN open_resp_hrs < 6 THEN 'b 1-6h' WHEN open_resp_hrs < 24 THEN 'c 6-24h'
            ELSE 'd 24-48h' END AS seller_reply_time,
       open_status, count(*) AS negotiations, avg(deal) AS eventual_deal_rate
FROM s WHERE open_status IN (1, 2, 7) GROUP BY ALL ORDER BY open_status, 1""").df()
save(speed, "p3_reply_speed")

# ---------------------------------------------------------------- Part 4: seller side
price = con.sql(f"""
WITH c AS (
  SELECT {CELL},
    count(*) FILTER (WHERE open_msg = 1) n1, avg(deal_ratio) FILTER (WHERE open_msg = 1) r1,
    count(*) FILTER (WHERE open_msg = 0) n0, avg(deal_ratio) FILTER (WHERE open_msg = 0) r0
  FROM s WHERE deal = 1 AND deal_ratio <= 1 GROUP BY ALL)
SELECT 'Deal price as share of list price' AS metric,
       (SELECT avg(deal_ratio) FROM s WHERE deal = 1 AND deal_ratio <= 1 AND open_msg = 0) AS no_msg_raw,
       (SELECT avg(deal_ratio) FROM s WHERE deal = 1 AND deal_ratio <= 1 AND open_msg = 1) AS msg_raw,
       sum(n1 * (r1 - r0)) / sum(n1) AS matched_diff
FROM c WHERE n1 > 0 AND n0 > 0""").df()
save(price, "p4_price_concession")

comp = con.sql("""
WITH l AS (SELECT anon_item_id, count(*) AS buyers, max(deal) AS sold_via_offer, max(open_msg) AS any_msg FROM s GROUP BY 1)
SELECT CASE WHEN buyers = 1 THEN '1 buyer' WHEN buyers = 2 THEN '2 buyers' WHEN buyers <= 4 THEN '3-4 buyers' ELSE '5+ buyers' END AS buyers_on_listing,
       count(*) AS listings, sum(buyers) AS negotiations, avg(sold_via_offer) AS listing_sold_via_offer
FROM l GROUP BY 1 ORDER BY 1""").df()
save(comp, "p4_competition")

# Negotiation-level vs listing-level gap among multi-buyer listings: if a message mostly moves the sale from one buyer to
# another, the per-negotiation gap overstates what the listing (the seller) gains. Same cells, listing-level outcome.
inter = con.sql("""
WITH l AS (
  SELECT anon_item_id, any_value(meta_categ_id) meta_categ_id, any_value(price_band) price_band, count(*) buyers,
         max(open_msg) any_msg, max(deal) sold_via_offer
  FROM s GROUP BY 1 HAVING count(*) BETWEEN 2 AND 4),
c AS (
  SELECT meta_categ_id, price_band, buyers,
    count(*) FILTER (WHERE any_msg = 1) n1, avg(sold_via_offer) FILTER (WHERE any_msg = 1) p1,
    avg(sold_via_offer) FILTER (WHERE any_msg = 0) p0
  FROM l GROUP BY ALL)
SELECT 'Listing sold via offer: listings with any message vs none (2-4 buyers)' AS comparison,
       sum(n1 * (p1 - p0)) / sum(n1) AS matched_gap
FROM c WHERE p0 IS NOT NULL AND p1 IS NOT NULL""").df()
save(inter, "p4_listing_level_gap")

lost = con.sql("""SELECT avg(lost_to_other_buyer) AS share_lost_to_other_buyer,
                         avg(lost_to_other_buyer) FILTER (WHERE clothing = 1) AS share_lost_clothing FROM s""").df()
save(lost, "p4_lost_to_other_buyer")
