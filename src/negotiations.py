"""Build the negotiation-level table.

Unit of analysis: one negotiation = one buyer bargaining over one listing (anon_item_id, anon_byr_id).
Thread ids are reused across items in the anonymised release, and a buyer can open up to three times on
the same listing, so thread ids are not used as the unit.

Codebook (Backus, Blake, Larsen & Tadelis 2020):
  offr_type_id: 0 = buyer's initial offer, 1 = buyer counteroffer, 2 = seller counteroffer
  status_id (the other side's response to this offer):
    0 = expired (no response within 48h), 1 = accepted, 2 = declined, 6 = auto-declined,
    7 = countered, 8 = declined because another buyer's offer on this item was accepted, 9 = auto-accepted
"""

ACCEPTED = (1, 9)

NEGOTIATIONS_SQL = """
SELECT
    anon_item_id,
    anon_byr_id,
    any_value(anon_slr_id)                                                        AS anon_slr_id,
    min(offer_ts)            FILTER (WHERE offr_type_id = 0)                      AS open_ts,
    arg_min(offr_price, offer_ts) FILTER (WHERE offr_type_id = 0)                 AS open_price,
    arg_min(any_mssg, offer_ts)   FILTER (WHERE offr_type_id = 0)                 AS open_msg,
    arg_min(status_id, offer_ts)  FILTER (WHERE offr_type_id = 0)                 AS open_status,
    -- Seller's reply time to the opening offer. For countered offers (status 7) the release records a 48h placeholder
    -- in response_time, so the reply time is taken from the arrival of the seller's first counteroffer instead.
    CASE WHEN arg_min(status_id, offer_ts) FILTER (WHERE offr_type_id = 0) = 7
         THEN epoch(min(offer_ts) FILTER (WHERE offr_type_id = 2) - min(offer_ts) FILTER (WHERE offr_type_id = 0)) / 3600.0
         ELSE arg_min(epoch(response_ts - offer_ts) / 3600.0, offer_ts) FILTER (WHERE offr_type_id = 0)
    END                                                                           AS open_resp_hrs,
    arg_min(byr_hist, offer_ts)   FILTER (WHERE offr_type_id = 0)                 AS byr_hist,
    arg_min(slr_hist, offer_ts)   FILTER (WHERE offr_type_id = 0)                 AS slr_hist,
    count(*)                                                                      AS n_offers,
    count(*)                 FILTER (WHERE offr_type_id = 0)                      AS n_openings,
    count(*)                 FILTER (WHERE offr_type_id = 2)                      AS n_seller_counters,
    count(*)                 FILTER (WHERE offr_type_id = 1)                      AS n_buyer_counters,
    max(any_mssg)            FILTER (WHERE offr_type_id IN (0, 1))                AS any_buyer_msg,
    max((status_id IN (1, 9))::TINYINT)                                           AS deal,
    max((status_id = 9)::TINYINT)                                                 AS deal_auto,
    max(offr_price)          FILTER (WHERE status_id IN (1, 9))                   AS deal_price,
    max((status_id = 8)::TINYINT)                                                 AS lost_to_other_buyer,
    arg_max(status_id, offer_ts)                                                  AS last_status,
    arg_max(offr_type_id, offer_ts)                                               AS last_offer_type
FROM {threads}
GROUP BY anon_item_id, anon_byr_id
"""

ENRICHED_SQL = """
SELECT
    n.*,
    l.meta_categ_id, l.leaf_categ_id, l.start_dt, l.end_dt,
    l.start_price_usd AS list_price, l.decline_price, l.accept_price,
    l.ref_price1, l.item_cndtn_id, l.photo_count, l.view_item_count, l.wtchr_count,
    l.slr_fdbk_score, l.slr_fdbk_pstv, l.store, l.sold, l.item_price,
    n.open_price / nullif(l.start_price_usd, 0)                     AS open_ratio,
    n.deal_price / nullif(l.start_price_usd, 0)                     AS deal_ratio,
    (l.meta_categ_id = 11450)::TINYINT                              AS clothing,
    (l.decline_price IS NOT NULL)::TINYINT                          AS has_auto_decline,
    (l.accept_price IS NOT NULL)::TINYINT                           AS has_auto_accept,
    date_trunc('month', n.open_ts)                                  AS open_month
FROM ({negotiations}) n
LEFT JOIN {lists} l USING (anon_item_id)
WHERE n.open_ts IS NOT NULL
"""


def build(con, threads: str, lists: str, out: str | None = None):
    """threads / lists are DuckDB relation expressions (e.g. "read_parquet('...')" or a table name).
    With `out`, writes parquet; otherwise returns a DuckDB relation."""
    neg = NEGOTIATIONS_SQL.format(threads=threads)
    sql = ENRICHED_SQL.format(negotiations=neg, lists=lists)
    if out:
        con.execute(f"COPY ({sql}) TO '{out}' (FORMAT parquet, COMPRESSION zstd)")
        return None
    return con.sql(sql)
