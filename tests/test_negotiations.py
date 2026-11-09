"""Toy-data checks for the negotiation build: unit, opening offer, deal and price definitions."""
import datetime as dt
import duckdb
import pytest
from src.negotiations import build

T0 = dt.datetime(2013, 1, 1, 12, 0)
H = dt.timedelta(hours=1)

# item, buyer, seller, type, status, price, offer_ts, response_ts, msg, byr_hist, slr_hist
OFFERS = [
    # Item 1 / buyer 10: opens with message at 60, seller counters 80, buyer accepts the counter -> deal at 80
    (1, 10, 100, 0, 7, 60.0, T0,         T0 + 48 * H, 1, 5, 50),  # 48h placeholder, as in the release
    (1, 10, 100, 2, 1, 80.0, T0 + 2 * H, T0 + 3 * H, 0, 5, 50),
    # Item 1 / buyer 11: opens without message, loses because buyer 10's deal closed (status 8)
    (1, 11, 100, 0, 8, 70.0, T0 + H,     T0 + 3 * H, 0, None, 50),
    # Item 2 / buyer 10 (same buyer, other item; reused thread ids must not merge these): auto-declined, re-opens, auto-accepted
    (2, 10, 200, 0, 6, 10.0, T0,         T0,         0, 6, 3),
    (2, 10, 200, 0, 9, 18.0, T0 + 5 * H, T0 + 5 * H, 1, 6, 3),
    # Item 3 / buyer 12: expires after 48h
    (3, 12, 300, 0, 0, 40.0, T0,         T0 + 48 * H, 0, 1, 0),
]
LISTS = [  # documentation only; the fixture builds the same rows in SQL: item, seller, meta, list price, decline, accept
    (1, 100, 11450, 100.0, None, None),
    (2, 200, 281, 20.0, 12.0, 17.0),
    (3, 300, 11450, 50.0, None, None),
]


@pytest.fixture(scope="module")
def neg():
    con = duckdb.connect()
    con.execute("""CREATE TABLE threads (anon_item_id BIGINT, anon_byr_id BIGINT, anon_slr_id BIGINT,
        offr_type_id TINYINT, status_id TINYINT, offr_price DOUBLE, offer_ts TIMESTAMP, response_ts TIMESTAMP,
        any_mssg TINYINT, byr_hist BIGINT, slr_hist BIGINT)""")
    con.executemany("INSERT INTO threads VALUES (?,?,?,?,?,?,?,?,?,?,?)", OFFERS)
    con.execute("""CREATE TABLE lists AS SELECT * FROM (VALUES
        (1::BIGINT, 100::BIGINT, 11450, 100.0, NULL::DOUBLE, NULL::DOUBLE),
        (2, 200, 281, 20.0, 12.0, 17.0),
        (3, 300, 11450, 50.0, NULL, NULL)) v(anon_item_id, anon_slr_id, meta_categ_id, start_price_usd, decline_price, accept_price)""")
    for col, typ in [("leaf_categ_id", "BIGINT"), ("start_dt", "DATE"), ("end_dt", "DATE"), ("ref_price1", "DOUBLE"),
                     ("item_cndtn_id", "INT"), ("photo_count", "INT"), ("view_item_count", "INT"), ("wtchr_count", "INT"),
                     ("slr_fdbk_score", "DOUBLE"), ("slr_fdbk_pstv", "DOUBLE"), ("store", "TINYINT"), ("sold", "TINYINT"),
                     ("item_price", "DOUBLE")]:
        con.execute(f"ALTER TABLE lists ADD COLUMN {col} {typ}")
    df = build(con, "threads", "lists").df()
    return {(r.anon_item_id, r.anon_byr_id): r for r in df.itertuples()}


def test_unit_is_item_buyer(neg):
    assert set(neg) == {(1, 10), (1, 11), (2, 10), (3, 12)}


def test_counter_accepted_is_a_deal_at_counter_price(neg):
    r = neg[(1, 10)]
    assert (r.deal, r.deal_price, r.open_price, r.open_msg) == (1, 80.0, 60.0, 1)
    assert r.deal_ratio == pytest.approx(0.8) and r.open_ratio == pytest.approx(0.6)
    assert r.n_offers == 2 and r.n_seller_counters == 1 and r.clothing == 1


def test_losing_to_another_buyer(neg):
    r = neg[(1, 11)]
    import pandas as pd
    assert r.deal == 0 and r.lost_to_other_buyer == 1 and pd.isna(r.byr_hist)


def test_reopening_uses_first_opening_offer(neg):
    r = neg[(2, 10)]
    assert (r.open_price, r.open_msg, r.open_status, r.n_openings) == (10.0, 0, 6, 2)
    assert (r.deal, r.deal_auto, r.deal_price, r.any_buyer_msg) == (1, 1, 18.0, 1)
    assert r.has_auto_decline == 1


def test_expired_offer(neg):
    r = neg[(3, 12)]
    assert r.deal == 0 and r.open_status == 0 and r.open_resp_hrs == pytest.approx(48.0)


def test_countered_reply_time_uses_counter_arrival(neg):
    # response_time on countered offers is a 48h placeholder; the counter arrived after 2h
    assert neg[(1, 10)].open_resp_hrs == pytest.approx(2.0)
