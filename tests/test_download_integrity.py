"""Fresh-clone acquisition must verify the committed dataset snapshot offline."""
import hashlib
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest


def test_changed_official_pdf_rejected_before_saving(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "scripts/download_pilot.py"
    spec = importlib.util.spec_from_file_location("pilot_downloader", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    catalog_path = tmp_path / "catalog.json"
    original_digest = hashlib.sha256(b"pinned synthetic fixture").hexdigest()
    catalog_path.write_text(json.dumps({"documents": [
        {"document_id": f"fixture{i}", "source_file": f"fixture{i}.pdf",
         "direct_pdf_url": f"https://www.fsb.org/fixture{i}.pdf", "sha256": original_digest}
        for i in range(5)
    ]}))
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.url = "https://www.fsb.org/fixture0.pdf"
    response.status_code = 200
    response.headers = {"Content-Type": "application/pdf"}
    response.iter_content.return_value = [b"%PDF-changed synthetic fixture"]
    get = Mock(return_value=response)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "CATALOG", catalog_path)
    monkeypatch.setattr(module.requests, "get", get)
    with pytest.raises(ValueError, match="checksum differs from the pinned catalog"):
        module.main()
    get.assert_called_once()
    assert not list((tmp_path / "data/raw").glob("*.pdf"))
    stored = json.loads(catalog_path.read_text())["documents"][0]
    assert stored["sha256"] == original_digest and stored["status"] == "failed"
