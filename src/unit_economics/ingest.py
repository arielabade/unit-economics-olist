"""Read the Tecelã Tecidos e-commerce data into local Parquet files.

The source is the sibling ``ecommerce`` repository, which is only ever read:

* ``--source mysql`` (default): the MySQL that ``make mysql`` brings up there;
* ``--source csv``: the CSVs ``make dados`` writes to ``ecommerce/data/csv``.

Both produce the same files. Rows are written in primary-key order and every
table is checked against the row counts and control sums the generator
produces at its fixed seed (see ``config.EXPECTED_ROWS``), so a different
seed, a different scale or a half-loaded database stops the run instead of
quietly changing the results.

Personal data does not leave the source: the CPF, needed only to merge two
accounts of the same person, is replaced by its SHA-256, and the e-mail by
the one fact the analysis uses (whether it is a staff test account).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd

from .config import ECOMMERCE_DIR, EXPECTED_ROWS, EXPECTED_SUMS, ROOT, mysql_settings

DATA_DIR = ROOT / "data" / "raw"

#: table -> (primary-key order, columns). Only what the analysis reads.
TABLES: dict[str, tuple[str, list[str]]] = {
    "clientes": ("cliente_id", [
        "cliente_id", "tipo_cliente", "tipo_pessoa", "cadastrado_em", "origem_cadastro",
        "{cpf_hash} AS cpf_hash",
        "email LIKE 'teste.%@tecelatecidos.example' AS conta_teste",
    ]),
    "cupons": ("cupom_id", ["cupom_id", "codigo", "tipo_desconto", "canal", "valido_de", "valido_ate"]),
    "pedidos": ("pedido_id", [
        "pedido_id", "cliente_id", "sessao_id", "cupom_id", "canal_venda", "status", "criado_em",
        "subtotal", "desconto", "frete", "total", "pedido_teste",
    ]),
    "itens_pedido": ("item_pedido_id", [
        "item_pedido_id", "pedido_id", "variante_id", "quantidade", "preco_unitario", "custo_unitario", "total_item",
    ]),
    "pagamentos": ("pagamento_id", ["pagamento_id", "pedido_id", "tentativa", "metodo", "parcelas", "valor", "status"]),
    "fretes": ("frete_id", ["frete_id", "pedido_id", "valor_cobrado", "custo_real", "frete_gratis"]),
    "devolucoes": ("devolucao_id", [
        "devolucao_id", "pedido_id", "item_pedido_id", "motivo", "quantidade", "valor_reembolsado", "status",
    ]),
    "movimentacoes_estoque": ("movimentacao_id", ["movimentacao_id", "tipo", "quantidade", "pedido_id", "devolucao_id"]),
    "atribuicoes": ("atribuicao_id", [
        "atribuicao_id", "pedido_id", "modelo", "sessao_id", "posicao", "canal",
        "meta_campanha_id", "google_campanha_id", "peso", "receita_atribuida",
    ]),
    "meta_campanhas": ("campanha_id", ["campanha_id", "nome", "objetivo", "estrategia", "inicio", "fim"]),
    "meta_conjuntos": ("conjunto_id", ["conjunto_id", "campanha_id"]),
    "meta_anuncios": ("anuncio_id", ["anuncio_id", "conjunto_id"]),
    "meta_metricas_diarias": ("data, anuncio_id", [
        "data", "anuncio_id", "investimento", "impressoes", "cliques_link", "compras", "valor_compras",
    ]),
    "google_campanhas": ("campanha_id", ["campanha_id", "nome", "tipo_canal", "campanha_marca", "inicio", "fim"]),
    "google_grupos_anuncio": ("grupo_id", ["grupo_id", "campanha_id"]),
    "google_metricas_diarias": ("data, grupo_id", [
        "data", "grupo_id", "investimento", "impressoes", "cliques", "conversoes", "valor_conversao",
    ]),
}

_CPF_HASH = {"mysql": "SHA2(cpf, 256)", "csv": "sha256(cpf)"}

# Meta IDs have 18 digits: integers survive, float64 would not (the dataset's
# imperfection #14). Money columns arrive as Decimal and become float.
_ID_SUFFIXES = ("_id",)
# DATE in MySQL; read_csv infers TIMESTAMP. Both are written as DATE.
_DATE_COLUMNS = ("data", "inicio", "fim", "valido_de", "valido_ate")


def _select(table: str, dialect: str, source: str) -> str:
    order, columns = TABLES[table]
    cols = ", ".join(c.format(cpf_hash=_CPF_HASH[dialect]) for c in columns)
    return f"SELECT {cols} FROM {source} ORDER BY {order}"


def _normalise(frame: pd.DataFrame) -> pd.DataFrame:
    for column in frame.columns:
        series = frame[column]
        if column.endswith(_ID_SUFFIXES) or column in ("posicao", "tentativa", "parcelas", "impressoes",
                                                         "cliques", "cliques_link", "compras"):
            frame[column] = pd.array(pd.to_numeric(series), dtype="Int64")
        elif series.dtype == object and series.map(lambda v: v.__class__.__name__ == "Decimal").any():
            frame[column] = pd.to_numeric(series).astype("float64")
        elif column in _DATE_COLUMNS:
            frame[column] = pd.to_datetime(series).dt.date
        elif column in ("conta_teste", "pedido_teste", "frete_gratis", "campanha_marca"):
            frame[column] = pd.to_numeric(series).astype("int8")
    return frame


def _from_mysql() -> dict[str, pd.DataFrame]:
    import pymysql

    settings = mysql_settings()
    connection = pymysql.connect(charset="utf8mb4", **settings)
    frames = {}
    try:
        with connection.cursor() as cursor:
            for table in TABLES:
                cursor.execute(_select(table, "mysql", table))
                names = [d[0] for d in cursor.description]
                frames[table] = _normalise(pd.DataFrame(list(cursor.fetchall()), columns=names))
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                (source_rows,) = cursor.fetchone()
                if source_rows != len(frames[table]):
                    raise ValueError(f"{table}: read {len(frames[table])} of {source_rows} rows")
    finally:
        connection.close()
    return frames


def _from_csv(csv_dir: Path) -> dict[str, pd.DataFrame]:
    con = duckdb.connect()
    frames = {}
    for table in TABLES:
        path = csv_dir / f"{table}.csv"
        if not path.exists():
            raise FileNotFoundError(f"{path} missing; run `make dados` in the ecommerce repository")
        source = f"read_csv('{path}', header = true, nullstr = '\\N', all_varchar = false)"
        frames[table] = _normalise(con.execute(_select(table, "csv", source)).df())
    con.close()
    return frames


def export(source: str = "mysql", csv_dir: Path | None = None, out_dir: Path = DATA_DIR) -> Path:
    """Read every table in ``TABLES`` and write it to ``out_dir``."""
    frames = _from_mysql() if source == "mysql" else _from_csv(csv_dir or ECOMMERCE_DIR / "data" / "csv")
    out_dir.mkdir(parents=True, exist_ok=True)
    for table, frame in frames.items():
        frame.to_parquet(out_dir / f"{table}.parquet", index=False)
    return out_dir


def verify(data_dir: Path = DATA_DIR) -> dict[str, int]:
    """Fail loudly unless the files are the ones the seeded generator makes."""
    con = duckdb.connect()
    counts = {}
    for table, expected in EXPECTED_ROWS.items():
        path = data_dir / f"{table}.parquet"
        if not path.exists():
            raise FileNotFoundError(f"{path} missing; run `python -m unit_economics.ingest`")
        (rows,) = con.execute(f"SELECT COUNT(*) FROM read_parquet('{path}')").fetchone()
        if rows != expected:
            raise ValueError(f"{table}: expected {expected:,} rows, found {rows:,}")
        counts[table] = rows
    for (table, column), expected in EXPECTED_SUMS.items():
        path = data_dir / f"{table}.parquet"
        (total,) = con.execute(f"SELECT ROUND(SUM({column}), 2) FROM read_parquet('{path}')").fetchone()
        if abs(total - expected) > 0.005:
            raise ValueError(f"{table}.{column}: expected a sum of {expected:,.2f}, found {total:,.2f}")
    con.close()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", choices=("mysql", "csv"), default="mysql")
    parser.add_argument("--csv-dir", type=Path, default=None)
    args = parser.parse_args()
    export(args.source, args.csv_dir)
    for table, rows in verify().items():
        print(f"{table:26} {rows:>9,} rows  ok")
    print(f"control sums ok ({len(EXPECTED_SUMS)} columns)")


if __name__ == "__main__":
    main()
