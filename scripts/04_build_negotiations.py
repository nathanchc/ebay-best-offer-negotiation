"""Build data/processed/negotiations.parquet: one row per (listing, buyer) negotiation, joined to listing attributes.
Usage (repo root): python -I scripts/04_build_negotiations.py"""
import sys, pathlib, duckdb
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from src.negotiations import build

con = duckdb.connect()
con.execute("SET memory_limit='5GB'; SET temp_directory='data/processed/tmp'; SET preserve_insertion_order=false; SET enable_progress_bar=false")
build(con, "read_parquet('data/processed/threads.parquet')", "read_parquet('data/processed/lists_bo.parquet')",
      out="data/processed/negotiations.parquet")
print(con.sql("""SELECT count(*) negotiations, count(list_price) matched_listing, round(avg(deal)*100,1) pct_deal,
                 sum(clothing) clothing FROM 'data/processed/negotiations.parquet'"""))
