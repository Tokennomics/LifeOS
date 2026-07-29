import pytest
from tools.db_verify import verify_database


def test_database_verification_tool(cfg):
    report = verify_database(cfg)
    assert "status" in report
    assert report["integrity_check"] == "ok"
    assert "tables" in report
    assert report["tables"]["entities"] >= 0
    assert report["tables"]["edges"] >= 0
    assert report["orphaned_edges_count"] == 0
