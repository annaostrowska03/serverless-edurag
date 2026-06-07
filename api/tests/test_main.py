"""
Unit tests for api/main.py.

All external cloud / ML dependencies are mocked via conftest.py before
api/main.py is imported, so no real GCP credentials are needed.
"""
import base64
import json
from unittest.mock import MagicMock, patch

import pytest

import importlib.util as _iu
import os as _os
import sys as _sys

_key = "api_main"
if _key not in _sys.modules:
    _spec = _iu.spec_from_file_location(_key, _os.path.join(_os.path.dirname(__file__), "..", "main.py"))
    _m = _iu.module_from_spec(_spec)
    _sys.modules[_key] = _m
    _spec.loader.exec_module(_m)
main = _sys.modules[_key]


# Helpers

def _auth(token="tok"):
    return {"Authorization": f"Bearer {token}"}


def _make_doc(content="Some text", filename="notes.pdf", page=0, subject="Math", doc_id="doc1"):
    doc = MagicMock()
    doc.page_content = content
    doc.metadata = {
        "filename": filename,
        "page": page,
        "subject": subject,
        "doc_id": doc_id,
    }
    return doc


def _parse_sse(data: bytes) -> list[dict]:
    """Parse raw SSE bytes into a list of JSON payloads."""
    events = []
    for line in data.decode().splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


# Fixtures

@pytest.fixture
def client():
    main.app.config["TESTING"] = True
    with main.app.test_client() as c:
        yield c


@pytest.fixture
def authed(client):
    """Client with firebase auth returning uid='uid_test'."""
    with patch.object(main, "verify_token", return_value="uid_test"):
        yield client


# Utility-function tests

class TestSanitize:
    def test_clean_string_unchanged(self):
        assert main.sanitize("Math_101") == "Math_101"

    def test_spaces_replaced(self):
        assert main.sanitize("Linear Algebra") == "Linear_Algebra"

    def test_special_chars_replaced(self):
        # trailing punctuation-turned-underscore is stripped by .strip("_")
        assert main.sanitize("Signals & Systems!") == "Signals___Systems"

    def test_empty_becomes_general(self):
        assert main.sanitize("") == "General"

    def test_strips_leading_trailing_underscores(self):
        result = main.sanitize("__hello__")
        assert not result.startswith("_")
        assert not result.endswith("_")


class TestNormalizeReferenceText:
    def test_lowercases(self):
        assert main.normalize_reference_text("Hello World") == "hello world"

    def test_strips_special_chars(self):
        assert main.normalize_reference_text("notes.pdf") == "notes pdf"

    def test_none_returns_empty(self):
        assert main.normalize_reference_text(None) == ""

    def test_collapses_multiple_separators(self):
        result = main.normalize_reference_text("file--name__test")
        assert "  " not in result


class TestGetFilenameAliases:
    def test_returns_filename_and_stem(self):
        aliases = main.get_filename_aliases("calculus.pdf")
        assert "calculus.pdf" in aliases or "calculus" in aliases

    def test_none_returns_empty_set(self):
        assert main.get_filename_aliases(None) == set()

    def test_empty_returns_empty_set(self):
        assert main.get_filename_aliases("") == set()

    def test_no_extension(self):
        aliases = main.get_filename_aliases("notes")
        assert len(aliases) > 0


class TestGetReferencedDocIds:
    def test_returns_empty_when_no_doc_ids(self):
        result = main.get_referenced_doc_ids("tell me about calculus", "uid1", [])
        assert result == []

    def test_matches_filename_in_question(self):
        mock_snap = MagicMock()
        mock_snap.exists = True
        mock_snap.to_dict.return_value = {"filename": "calculus.pdf", "storage_path": "uploads/uid1/Math/calculus.pdf"}

        with patch.object(main, "build_doc_ref") as mock_ref:
            mock_ref.return_value.get.return_value = mock_snap
            result = main.get_referenced_doc_ids(
                "summarize calculus for me", "uid1", ["doc1"]
            )
        assert "doc1" in result

    def test_no_match_returns_empty(self):
        mock_snap = MagicMock()
        mock_snap.exists = True
        mock_snap.to_dict.return_value = {"filename": "thermodynamics.pdf", "storage_path": ""}

        with patch.object(main, "build_doc_ref") as mock_ref:
            mock_ref.return_value.get.return_value = mock_snap
            result = main.get_referenced_doc_ids(
                "tell me about calculus", "uid1", ["doc1"]
            )
        assert result == []


# POST /ask

class TestAskEndpoint:
    def test_no_auth_returns_401(self, client):
        resp = client.post("/ask", json={"question": "What is entropy?"})
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self, client):
        with patch.object(main, "verify_token", return_value=None):
            resp = client.post("/ask", json={"question": "Q"}, headers=_auth())
        assert resp.status_code == 401

    def test_missing_question_returns_400(self, authed):
        resp = authed.post("/ask", json={}, headers=_auth())
        assert resp.status_code == 400
        assert b"required" in resp.data.lower()

    def test_no_relevant_docs_streams_empty_context(self, authed):
        with patch.object(main, "vector_store") as mock_vs:
            mock_vs.similarity_search.return_value = []

            with patch.object(main, "llm") as mock_llm:
                chunk = MagicMock()
                chunk.content = "There is no context."
                mock_llm.stream.return_value = iter([chunk])

                resp = authed.post("/ask", json={"question": "Explain entropy"}, headers=_auth())

        assert resp.status_code == 200
        assert resp.content_type.startswith("text/event-stream")
        events = _parse_sse(resp.data)
        token_events = [e for e in events if "token" in e]
        done_events = [e for e in events if e.get("done")]
        assert len(token_events) >= 1
        assert len(done_events) == 1

    def test_with_docs_includes_sources_in_final_event(self, authed):
        doc = _make_doc("Entropy is disorder.", "thermo.pdf", page=1)

        with patch.object(main, "vector_store") as mock_vs:
            mock_vs.similarity_search.return_value = [doc]

            with patch.object(main, "llm") as mock_llm:
                chunk = MagicMock()
                chunk.content = "Entropy measures disorder."
                mock_llm.stream.return_value = iter([chunk])

                resp = authed.post("/ask", json={"question": "What is entropy?"}, headers=_auth())

        events = _parse_sse(resp.data)
        done_event = next(e for e in events if e.get("done"))
        assert len(done_event["sources"]) == 1
        assert done_event["sources"][0]["filename"] == "thermo.pdf"
        assert done_event["sources"][0]["page"] == 2  # page+1

    def test_with_doc_ids_uses_similarity_search_with_score(self, authed):
        doc = _make_doc("Kirchhoff's law", "circuits.pdf")

        with patch.object(main, "vector_store") as mock_vs:
            mock_vs.similarity_search_with_score.return_value = [(doc, 0.1)]

            with patch.object(main, "llm") as mock_llm:
                chunk = MagicMock()
                chunk.content = "Kirchhoff"
                mock_llm.stream.return_value = iter([chunk])

                with patch.object(main, "build_doc_ref") as mock_ref:
                    snap = MagicMock()
                    snap.exists = True
                    snap.to_dict.return_value = {"filename": "circuits.pdf", "storage_path": ""}
                    mock_ref.return_value.get.return_value = snap

                    resp = authed.post(
                        "/ask",
                        json={"question": "explain circuits.pdf", "doc_ids": ["doc1"]},
                        headers=_auth(),
                    )

        assert resp.status_code == 200
        mock_vs.similarity_search_with_score.assert_called()

    def test_deduplicates_sources(self, authed):
        """Two chunks from the same file+page produce one source."""
        doc1 = _make_doc("Text A", "notes.pdf", page=0)
        doc2 = _make_doc("Text B", "notes.pdf", page=0)

        with patch.object(main, "vector_store") as mock_vs:
            mock_vs.similarity_search.return_value = [doc1, doc2]

            with patch.object(main, "llm") as mock_llm:
                chunk = MagicMock(); chunk.content = "."
                mock_llm.stream.return_value = iter([chunk])

                resp = authed.post("/ask", json={"question": "Q"}, headers=_auth())

        done_event = next(e for e in _parse_sse(resp.data) if e.get("done"))
        assert len(done_event["sources"]) == 1

    def test_llm_error_streams_error_event(self, authed):
        with patch.object(main, "vector_store") as mock_vs:
            mock_vs.similarity_search.return_value = []

            with patch.object(main, "llm") as mock_llm:
                def _boom():
                    raise RuntimeError("LLM unavailable")
                    yield  # make it a generator
                mock_llm.stream.side_effect = RuntimeError("LLM unavailable")

                resp = authed.post("/ask", json={"question": "Q"}, headers=_auth())

        # Should return 200 with an error event in the stream
        assert resp.status_code == 200
        events = _parse_sse(resp.data)
        error_events = [e for e in events if "error" in e]
        assert len(error_events) >= 1


# POST /generate-upload-url

class TestGenerateUploadUrl:
    def _setup_google_auth_mock(self):
        """Return a mock credentials object that generate_upload_url expects."""
        creds = MagicMock()
        creds.token = "access_token_xyz"
        creds.service_account_email = "sa@project.iam.gserviceaccount.com"
        return creds

    def test_no_auth_returns_401(self, client):
        resp = client.post("/generate-upload-url", json={"filename": "notes.pdf"})
        assert resp.status_code == 401

    def test_missing_filename_returns_400(self, authed):
        resp = authed.post("/generate-upload-url", json={}, headers=_auth())
        assert resp.status_code == 400

    def test_success_returns_expected_fields(self, authed):
        creds = self._setup_google_auth_mock()

        with patch("google.auth.default", return_value=(creds, "project")):
            with patch("google.auth.transport.requests.Request", return_value=MagicMock()):
                with patch.object(main, "storage_client") as mock_sc:
                    mock_blob = MagicMock()
                    mock_blob.generate_signed_url.return_value = "https://signed.url/upload"
                    mock_sc.bucket.return_value.blob.return_value = mock_blob

                    with patch.object(main, "db") as mock_db:
                        mock_db.collection.return_value.document.return_value.collection\
                            .return_value.document.return_value.set = MagicMock()

                        resp = authed.post(
                            "/generate-upload-url",
                            json={"filename": "lecture1.pdf", "subject": "Physics"},
                            headers=_auth(),
                        )

        assert resp.status_code == 200
        data = resp.get_json()
        assert "upload_url" in data
        assert "document_id" in data
        assert "user_id" in data
        assert data["user_id"] == "uid_test"

    def test_doc_id_derived_from_path(self, authed):
        creds = self._setup_google_auth_mock()

        with patch("google.auth.default", return_value=(creds, "project")):
            with patch("google.auth.transport.requests.Request", return_value=MagicMock()):
                with patch.object(main, "storage_client") as mock_sc:
                    mock_sc.bucket.return_value.blob.return_value\
                        .generate_signed_url.return_value = "https://u"

                    with patch.object(main, "db"):
                        resp = authed.post(
                            "/generate-upload-url",
                            json={"filename": "notes.pdf", "subject": "Math"},
                            headers=_auth(),
                        )

        data = resp.get_json()
        # doc_id = gcs_path.replace('/', '_')  ->  uploads_uid_test_Math_notes.pdf
        assert "_" in data["document_id"]
        assert "notes.pdf" in data["document_id"]

    def test_firestore_document_is_created(self, authed):
        creds = self._setup_google_auth_mock()
        mock_set = MagicMock()

        with patch("google.auth.default", return_value=(creds, "project")):
            with patch("google.auth.transport.requests.Request", return_value=MagicMock()):
                with patch.object(main, "storage_client") as mock_sc:
                    mock_sc.bucket.return_value.blob.return_value\
                        .generate_signed_url.return_value = "https://u"

                    with patch.object(main, "db") as mock_db:
                        mock_db.collection.return_value.document.return_value.collection\
                            .return_value.document.return_value.set = mock_set

                        authed.post(
                            "/generate-upload-url",
                            json={"filename": "notes.pdf"},
                            headers=_auth(),
                        )

        mock_set.assert_called_once()
        call_args = mock_set.call_args[0][0]
        assert call_args["status"] == "Uploading"
        assert call_args["filename"] == "notes.pdf"


# DELETE /documents/<doc_id>

class TestDeleteDocument:
    def _make_firestore_doc(self, exists=True, data=None):
        snap = MagicMock()
        snap.exists = exists
        snap.to_dict.return_value = data or {
            "storage_path": "uploads/uid_test/Math/notes.pdf",
            "subject": "Math",
            "filename": "notes.pdf",
        }
        return snap

    def test_no_auth_returns_401(self, client):
        resp = client.delete("/documents/doc123")
        assert resp.status_code == 401

    def test_document_not_found_returns_404(self, authed):
        with patch.object(main, "build_doc_ref") as mock_ref:
            mock_ref.return_value.get.return_value = self._make_firestore_doc(exists=False)
            resp = authed.delete("/documents/doc123", headers=_auth())
        assert resp.status_code == 404

    def test_success_returns_deleted_id(self, authed):
        snap = self._make_firestore_doc()

        with patch.object(main, "build_doc_ref") as mock_ref:
            mock_ref.return_value.get.return_value = snap

            with patch.object(main, "chroma_client") as mock_chroma:
                mock_collection = MagicMock()
                mock_collection.get.return_value = {"ids": ["chunk1", "chunk2"]}
                mock_chroma.get_collection.return_value = mock_collection

                with patch.object(main, "storage_client") as mock_sc:
                    mock_blob = MagicMock()
                    mock_blob.exists.return_value = True
                    mock_sc.bucket.return_value.blob.return_value = mock_blob

                    resp = authed.delete("/documents/doc123", headers=_auth())

        assert resp.status_code == 200
        assert resp.get_json()["deleted"] == "doc123"

    def test_chromadb_chunks_are_deleted(self, authed):
        snap = self._make_firestore_doc()

        with patch.object(main, "build_doc_ref") as mock_ref:
            mock_ref.return_value.get.return_value = snap

            with patch.object(main, "chroma_client") as mock_chroma:
                mock_collection = MagicMock()
                mock_collection.get.return_value = {"ids": ["c1"]}
                mock_chroma.get_collection.return_value = mock_collection

                with patch.object(main, "storage_client") as mock_sc:
                    mock_sc.bucket.return_value.blob.return_value.exists.return_value = False

                    authed.delete("/documents/doc123", headers=_auth())

        mock_collection.delete.assert_called_once_with(ids=["c1"])

    def test_gcs_blob_is_deleted(self, authed):
        snap = self._make_firestore_doc()
        mock_blob = MagicMock()
        mock_blob.exists.return_value = True

        with patch.object(main, "build_doc_ref") as mock_ref:
            mock_ref.return_value.get.return_value = snap

            with patch.object(main, "chroma_client") as mock_chroma:
                mock_chroma.get_collection.return_value.get.return_value = {"ids": []}

                with patch.object(main, "storage_client") as mock_sc:
                    mock_sc.bucket.return_value.blob.return_value = mock_blob

                    authed.delete("/documents/doc123", headers=_auth())

        mock_blob.delete.assert_called_once()

    def test_chromadb_error_does_not_abort_deletion(self, authed):
        """ChromaDB errors are logged but deletion continues."""
        snap = self._make_firestore_doc()

        with patch.object(main, "build_doc_ref") as mock_ref:
            mock_ref.return_value.get.return_value = snap

            with patch.object(main, "chroma_client") as mock_chroma:
                mock_chroma.get_collection.side_effect = Exception("chroma down")

                with patch.object(main, "storage_client") as mock_sc:
                    mock_sc.bucket.return_value.blob.return_value.exists.return_value = False

                    resp = authed.delete("/documents/doc123", headers=_auth())

        assert resp.status_code == 200

    def test_firestore_document_is_deleted(self, authed):
        snap = self._make_firestore_doc()
        mock_doc_ref = MagicMock()
        mock_doc_ref.get.return_value = snap

        with patch.object(main, "build_doc_ref", return_value=mock_doc_ref):
            with patch.object(main, "chroma_client") as mock_chroma:
                mock_chroma.get_collection.return_value.get.return_value = {"ids": []}

                with patch.object(main, "storage_client") as mock_sc:
                    mock_sc.bucket.return_value.blob.return_value.exists.return_value = False

                    authed.delete("/documents/doc123", headers=_auth())

        mock_doc_ref.delete.assert_called_once()

    def test_post_method_also_deletes(self, authed):
        """Endpoint accepts POST as well as DELETE (legacy support)."""
        snap = self._make_firestore_doc()

        with patch.object(main, "build_doc_ref") as mock_ref:
            mock_ref.return_value.get.return_value = snap

            with patch.object(main, "chroma_client") as mock_chroma:
                mock_chroma.get_collection.return_value.get.return_value = {"ids": []}

                with patch.object(main, "storage_client") as mock_sc:
                    mock_sc.bucket.return_value.blob.return_value.exists.return_value = False

                    resp = authed.post("/documents/doc123", headers=_auth())

        assert resp.status_code == 200
