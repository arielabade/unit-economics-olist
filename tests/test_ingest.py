"""The ingest must refuse anything but the seeded dataset, and keep PII out."""

import pandas as pd
import pytest

from unit_economics import ingest
from unit_economics.config import EXPECTED_ROWS, EXPECTED_SUMS


def _fake_source(tmp_path, rows=None, sums=None):
    """One Parquet file per expected table, with the expected count and sums."""
    rows = rows or {}
    sums = sums or {}
    for table, expected in EXPECTED_ROWS.items():
        n = rows.get(table, expected)
        frame = pd.DataFrame({"id": range(n)})
        for (sum_table, column), total in EXPECTED_SUMS.items():
            if sum_table == table:
                total = sums.get((table, column), total)
                frame[column] = [total] + [0.0] * (n - 1)
        frame.to_parquet(tmp_path / f"{table}.parquet", index=False)
    return tmp_path


def test_verify_accepts_the_seeded_dataset(tmp_path):
    counts = ingest.verify(_fake_source(tmp_path))
    assert counts == EXPECTED_ROWS


def test_verify_rejects_a_different_row_count(tmp_path):
    source = _fake_source(tmp_path, rows={"pedidos": EXPECTED_ROWS["pedidos"] - 1})
    with pytest.raises(ValueError, match="pedidos: expected 143,633 rows"):
        ingest.verify(source)


def test_verify_rejects_same_count_with_different_money(tmp_path):
    source = _fake_source(tmp_path, sums={("meta_metricas_diarias", "investimento"): 1.0})
    with pytest.raises(ValueError, match="meta_metricas_diarias.investimento"):
        ingest.verify(source)


def test_verify_names_a_missing_table(tmp_path):
    source = _fake_source(tmp_path)
    (source / "atribuicoes.parquet").unlink()
    with pytest.raises(FileNotFoundError, match="atribuicoes"):
        ingest.verify(source)


def test_every_verified_table_is_read():
    assert set(EXPECTED_ROWS) == set(ingest.TABLES)


def test_personal_data_does_not_leave_the_source():
    for dialect in ("mysql", "csv"):
        sql = ingest._select("clientes", dialect, "clientes")
        for column in ("nome", "telefone", "data_nascimento", "cpf,", "email,"):
            assert f" {column}" not in sql
    assert "SHA2(cpf, 256) AS cpf_hash" in ingest._select("clientes", "mysql", "clientes")
    assert "sha256(cpf) AS cpf_hash" in ingest._select("clientes", "csv", "x")


def test_rows_are_read_in_primary_key_order():
    assert ingest._select("pedidos", "mysql", "pedidos").endswith("ORDER BY pedido_id")
    assert ingest._select("meta_metricas_diarias", "mysql", "m").endswith("ORDER BY data, anuncio_id")
