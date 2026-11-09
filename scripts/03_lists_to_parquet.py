"""Listings that received at least one Best Offer -> parquet (selected columns).
Usage: python -I scripts/03_lists_to_parquet.py data/raw/anon_bo_lists.csv.gz data/processed/threads.parquet data/processed/lists_bo.parquet
"""
import sys, duckdb
raw, threads, out = sys.argv[1], sys.argv[2], sys.argv[3]
con = duckdb.connect()
con.execute("SET memory_limit='6GB'; SET preserve_insertion_order=false;")
con.execute(f"""
COPY (
  SELECT l.anon_item_id::BIGINT AS anon_item_id,
         l.anon_slr_id::BIGINT AS anon_slr_id,
         l.anon_leaf_categ_id::BIGINT AS leaf_categ_id,
         l.meta_categ_id::INT AS meta_categ_id,
         strptime(l.auct_start_dt, '%d%b%Y')::DATE AS start_dt,
         strptime(l.auct_end_dt, '%d%b%Y')::DATE AS end_dt,
         l.start_price_usd::DOUBLE AS start_price_usd,
         l.item_price::DOUBLE AS item_price,
         l.bo_ck_yn::TINYINT AS sold,
         l.decline_price::DOUBLE AS decline_price,
         l.accept_price::DOUBLE AS accept_price,
         l.ref_price1::DOUBLE AS ref_price1,
         l.item_cndtn_id::INT AS item_cndtn_id,
         l.photo_count::INT AS photo_count,
         l.view_item_count::INT AS view_item_count,
         l.wtchr_count::INT AS wtchr_count,
         l.fdbk_score_start::DOUBLE AS slr_fdbk_score,
         l.fdbk_pstv_start::DOUBLE AS slr_fdbk_pstv,
         l.store::TINYINT AS store,
         l.slr_us::TINYINT AS slr_us
  FROM read_csv('{raw}', header=true, all_varchar=true) l
  SEMI JOIN (SELECT DISTINCT anon_item_id FROM read_parquet('{threads}')) t
    ON l.anon_item_id::BIGINT = t.anon_item_id
) TO '{out}' (FORMAT parquet, COMPRESSION zstd)
""")
print(con.execute(f"SELECT count(*), count(DISTINCT meta_categ_id) FROM read_parquet('{out}')").fetchall())
