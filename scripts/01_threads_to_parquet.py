"""Convert the NBER eBay Best Offer threads file to Parquet (read once, query fast)."""
import sys, duckdb
raw, out = sys.argv[1], sys.argv[2]
con = duckdb.connect()
con.execute(f"""
COPY (
  SELECT anon_item_id, anon_thread_id, anon_byr_id, anon_slr_id,
         offr_type_id::TINYINT AS offr_type_id, status_id::TINYINT AS status_id,
         offr_price::DOUBLE AS offr_price,
         strptime(src_cre_date, '%d%b%Y %H:%M:%S') AS offer_ts,
         try_strptime(response_time, '%d%b%Y %H:%M:%S') AS response_ts,
         slr_hist, byr_hist, coalesce(any_mssg, 0)::TINYINT AS any_mssg,
         fdbk_score_src, fdbk_pstv_src, byr_us
  FROM read_csv('{raw}', header=true, all_varchar=false, sample_size=-1)
) TO '{out}' (FORMAT parquet, COMPRESSION zstd)
""")
print(con.execute(f"SELECT count(*), count(DISTINCT anon_thread_id), count(DISTINCT anon_item_id) FROM '{out}'").fetchall())
