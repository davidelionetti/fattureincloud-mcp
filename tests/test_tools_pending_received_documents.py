"""Unit tests for list_pending_received_documents and
get_pending_received_document."""

import asyncio
import importlib
import json
import sys

import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def server_module(tmp_path, monkeypatch):
    monkeypatch.setenv("FIC_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("FIC_CACHE_DISABLED", raising=False)
    monkeypatch.setenv("FIC_ACCESS_TOKEN", "test_token")
    monkeypatch.setenv("FIC_COMPANY_ID", "100")
    monkeypatch.setenv("FIC_SENDER_EMAIL", "test@example.invalid")

    for mod in ("server", "cache"):
        if mod in sys.modules:
            del sys.modules[mod]

    yield importlib.import_module("server")


def _doc(**kw):
    d = {
        "id": 1, "date": "2026-01-15", "subject": "Fattura 42",
        "filename": "IT123_abc.xml", "type": "agyo", "document_type": "expense",
        "supplier_name": "Acme Srl", "amount_net": 100.0, "amount_vat": 22.0,
        "amount_gross": 122.0,
    }
    d.update(kw)
    m = MagicMock()
    m.to_dict.return_value = d
    return m


def _list_response(docs):
    r = MagicMock()
    r.data = docs
    return r


def _call(server, name, args):
    result = asyncio.run(server.call_tool(name, args))
    return result[0].text


def test_list_default_type_agyo(server_module):
    server = server_module
    with patch.object(server.received_api, "list_pending_received_documents",
                      return_value=_list_response([_doc()])) as m:
        rows = json.loads(_call(server, "list_pending_received_documents", {}))
    m.assert_called_once_with(company_id=100, type="agyo", per_page=100, fieldset="detailed")
    assert rows[0]["supplier"] == "Acme Srl"
    assert rows[0]["total"] == 122.0
    assert rows[0]["document_type"] == "expense"


def test_list_type_mail(server_module):
    server = server_module
    with patch.object(server.received_api, "list_pending_received_documents",
                      return_value=_list_response([])) as m:
        _call(server, "list_pending_received_documents", {"type": "mail"})
    assert m.call_args.kwargs["type"] == "mail"


def test_list_query_filter(server_module):
    server = server_module
    docs = [
        _doc(id=1, supplier_name="Acme Srl"),
        _doc(id=2, supplier_name="Other", subject="Canone Hosting"),
        _doc(id=3, supplier_name="Other", subject="x", filename="HOSTING.xml"),
        _doc(id=4, supplier_name="Other", subject="x", filename="y.xml"),
    ]
    with patch.object(server.received_api, "list_pending_received_documents",
                      return_value=_list_response(docs)):
        rows = json.loads(_call(server, "list_pending_received_documents", {"query": "HoStInG"}))
        assert [r["id"] for r in rows] == [2, 3]
        rows = json.loads(_call(server, "list_pending_received_documents", {"query": "acme"}))
        assert [r["id"] for r in rows] == [1]


def test_list_optional_fields_only_when_set(server_module):
    server = server_module
    docs = [_doc(id=1), _doc(id=2, cost_center="CC1", import_error="boom")]
    with patch.object(server.received_api, "list_pending_received_documents",
                      return_value=_list_response(docs)):
        rows = json.loads(_call(server, "list_pending_received_documents", {}))
    assert "cost_center" not in rows[0] and "import_error" not in rows[0]
    assert rows[1]["cost_center"] == "CC1" and rows[1]["import_error"] == "boom"


def test_list_data_none(server_module):
    server = server_module
    with patch.object(server.received_api, "list_pending_received_documents",
                      return_value=_list_response(None)):
        assert json.loads(_call(server, "list_pending_received_documents", {})) == []


def test_get_maps_fields(server_module):
    server = server_module
    d = _doc(
        emssion_date="2026-01-10", currency={"id": "EUR"}, category="Servizi",
        attachment_url="https://tmp/x", other_attachments=None,
        payments_list=[{"amount": 122.0, "due_date": "2026-02-15", "status": "not_paid", "paid_date": None}],
    )
    resp = MagicMock()
    resp.data = d
    with patch.object(server.received_api, "get_pending_received_document", return_value=resp) as m:
        r = json.loads(_call(server, "get_pending_received_document", {"document_id": 1}))
    m.assert_called_once_with(company_id=100, document_id=1, fieldset="detailed")
    assert r["supplier"] == "Acme Srl"
    assert r["emission_date"] == "2026-01-10"
    assert r["source"] == "agyo"
    assert r["currency"] == "EUR"
    assert r["payments"] == [{"amount": 122.0, "due_date": "2026-02-15", "status": "not_paid", "paid_date": None}]
    assert r["other_attachments"] == []
    assert "cost_center" not in r and "import_error" not in r


def test_get_optional_fields_and_missing_dates(server_module):
    server = server_module
    d = _doc(cost_center="CC1", import_error="boom")
    resp = MagicMock()
    resp.data = d
    with patch.object(server.received_api, "get_pending_received_document", return_value=resp):
        r = json.loads(_call(server, "get_pending_received_document", {"document_id": 1}))
    assert r["cost_center"] == "CC1" and r["import_error"] == "boom"
    assert r["emission_date"] is None
    assert r["currency"] is None


def test_sdk_error(server_module):
    server = server_module
    with patch.object(server.received_api, "list_pending_received_documents",
                      side_effect=RuntimeError("down")):
        assert _call(server, "list_pending_received_documents", {}).startswith("Errore:")
