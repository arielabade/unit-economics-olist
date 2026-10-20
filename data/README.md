# Data

This directory is populated by the pipeline and is intentionally not committed.

```
data/raw/        16 tables of the ecommerce database as Parquet, written by `python -m unit_economics.ingest`
data/processed/  analysis tables written by `python -m unit_economics.pipeline`
```

## Source

The sibling `ecommerce` repository (Tecelã Tecidos), a **simulated** online fabric store generated
deterministically (seed `20231001`, scale `1.0`). Bring it up with `make ambiente && make dados && make mysql`
there; the ingest reads its MySQL, or its CSV exports with `--source csv`, and never writes to it.

`ingest.verify()` asserts every table's row count and the control sums of the money columns against what the
generator produces, so a different seed, a different scale or a half-loaded database fails the run instead of
quietly changing the results.

Nothing in this project is simulated: acquisition channel and media spend come from the dataset. The two
assumed costs (payment fees and handling per order) live in `src/unit_economics/config.py`. The full map of
tables and fields is in [docs/DATA_SOURCE.md](../docs/DATA_SOURCE.md).
