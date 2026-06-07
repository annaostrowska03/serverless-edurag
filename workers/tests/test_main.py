"""
Unit tests for workers/main.py.

External cloud / ML services are mocked via conftest.py before import.
"""
import base64
import json
from unittest.mock import MagicMock, call, patch

import pytest

import importlib.util as _iu
import os as _os
import sys as _sys

_key = "workers_main"
if _key not in _sys.modules:
    _spec = _iu.spec_from_file_location(_key, _os.path.join(_os.path.dirname(__file__), "..", "main.py"))
    _m = _iu.module_from_spec(_spec)
    _sys.modules[_key] = _m
    _spec.loader.exec_module(_m)
main = _sys.modules[_key]


# parse_storage_path

class TestParseStoragePath:
    def test_full_path_returns_user_subject_filename(self):
        user, subject, filename = main.parse_storage_path("uploads/user123/Math/notes.pdf")
        assert user == "user123"
        assert subject == "Math"
        assert filename == "notes.pdf"

    def test_nested_filename_is_preserved(self):
        user, subject, filename = main.parse_storage_path("uploads/u1/Physics/ch1/lecture.pdf")
        assert user == "u1"
        assert subject == "Physics"
        assert filename == "ch1/lecture.pdf"

    def test_legacy_two_part_path(self):
        user, subject, filename = main.parse_storage_path("uploads/notes.pdf")
        assert user == "legacy"
        assert subject == "General"
        assert filename == "notes.pdf"

    def test_unknown_prefix_falls_back_to_legacy(self):
        user, subject, filename = main.parse_storage_path("other/some/path.pdf")
        assert user == "legacy"
        assert subject == "General"
        assert filename == "path.pdf"

    def test_exact_four_parts(self):
        user, subject, filename = main.parse_storage_path("uploads/abc/Biology/exam.pdf")
        assert user == "abc"
        assert subject == "Biology"
        assert filename == "exam.pdf"


# POST / (process_document)

def _pubsub_body(bucket: str, name: str) -> dict:
    """Build a Pub/Sub push envelope for a GCS event."""
    payload = json.dumps({"bucket": bucket, "name": name}).encode()
    return {
        "message": {
            "data": base64.b64encode(payload).decode(),
        }
    }


@pytest.fixture
def client():
    main.app.config["TESTING"] = True
    with main.app.test_client() as c:
        yield c


@pytest.fixture
def mock_db():
    doc_ref = MagicMock()
    existing_snap = MagicMock()
    existing_snap.exists = True
    existing_snap.to_dict.return_value = {"filename": "notes.pdf"}
    doc_ref.get.return_value = existing_snap
    with patch.object(main, "db") as mock:
        # db.collection("users").document(uid).collection("documents").document(doc_id)
        mock.collection.return_value.document.return_value \
            .collection.return_value.document.return_value = doc_ref
        yield mock, doc_ref


class TestProcessDocumentEndpoint:

    # Bad requests

    def test_no_json_returns_400(self, client):
        resp = client.post("/", data="not json", content_type="application/json")
        assert resp.status_code == 400

    def test_empty_body_returns_400(self, client):
        resp = client.post("/", json={})
        assert resp.status_code == 400

    def test_missing_data_in_message_returns_400(self, client):
        resp = client.post("/", json={"message": {}})
        assert resp.status_code == 400

    def test_missing_bucket_or_name_returns_200_noop(self, client):
        """Malformed GCS events should be silently ignored (return 200)."""
        payload = base64.b64encode(json.dumps({}).encode()).decode()
        resp = client.post("/", json={"message": {"data": payload}})
        assert resp.status_code == 200

    def test_invalid_base64_returns_400(self, client):
        resp = client.post("/", json={"message": {"data": "!!!not-base64!!!"}})
        assert resp.status_code == 400

    # Happy path

    def test_successful_processing_returns_ok(self, client, mock_db):
        _, doc_ref = mock_db
        mock_chunk = MagicMock()
        mock_chunk.metadata = {}

        with patch.object(main, "storage_client") as mock_sc:
            mock_sc.bucket.return_value.blob.return_value.download_to_filename = MagicMock()

            with patch.object(main, "vector_store") as mock_vs:
                with patch.object(main, "PyPDFLoader") as MockLoader:
                    MockLoader.return_value.load.return_value = [MagicMock()]

                    with patch.object(main, "RecursiveCharacterTextSplitter") as MockSplitter:
                        MockSplitter.return_value.split_documents.return_value = [mock_chunk]

                        resp = client.post(
                            "/", json=_pubsub_body("my-bucket", "uploads/u1/Math/notes.pdf")
                        )

        assert resp.status_code == 200
        assert resp.data == b"OK"

    def test_status_progresses_to_ready(self, client, mock_db):
        _, doc_ref = mock_db
        mock_chunk = MagicMock()
        mock_chunk.metadata = {}

        with patch.object(main, "storage_client") as mock_sc:
            mock_sc.bucket.return_value.blob.return_value.download_to_filename = MagicMock()

            with patch.object(main, "vector_store"):
                with patch.object(main, "PyPDFLoader") as MockLoader:
                    MockLoader.return_value.load.return_value = [MagicMock()]

                    with patch.object(main, "RecursiveCharacterTextSplitter") as MockSplitter:
                        MockSplitter.return_value.split_documents.return_value = [mock_chunk]

                        client.post(
                            "/", json=_pubsub_body("bucket", "uploads/u1/Math/notes.pdf")
                        )

        update_statuses = [c.args[0].get("status") for c in doc_ref.update.call_args_list if c.args]
        assert "Chunking" in update_statuses
        assert "Vectorizing" in update_statuses
        assert "Ready" in update_statuses

    def test_chunks_have_correct_metadata_injected(self, client, mock_db):
        _, doc_ref = mock_db
        mock_chunk = MagicMock()
        mock_chunk.metadata = {}

        with patch.object(main, "storage_client") as mock_sc:
            mock_sc.bucket.return_value.blob.return_value.download_to_filename = MagicMock()

            with patch.object(main, "vector_store") as mock_vs:
                with patch.object(main, "PyPDFLoader") as MockLoader:
                    MockLoader.return_value.load.return_value = [MagicMock()]

                    with patch.object(main, "RecursiveCharacterTextSplitter") as MockSplitter:
                        MockSplitter.return_value.split_documents.return_value = [mock_chunk]

                        client.post(
                            "/", json=_pubsub_body("bucket", "uploads/uid42/Chemistry/lab.pdf")
                        )

        assert mock_chunk.metadata["user_id"] == "uid42"
        assert mock_chunk.metadata["subject"] == "Chemistry"
        assert mock_chunk.metadata["filename"] == "notes.pdf"  # from existing Firestore doc

    def test_chunks_are_added_to_vector_store(self, client, mock_db):
        mock_chunk = MagicMock()
        mock_chunk.metadata = {}

        with patch.object(main, "storage_client") as mock_sc:
            mock_sc.bucket.return_value.blob.return_value.download_to_filename = MagicMock()

            with patch.object(main, "vector_store") as mock_vs:
                with patch.object(main, "PyPDFLoader") as MockLoader:
                    MockLoader.return_value.load.return_value = [MagicMock()]

                    with patch.object(main, "RecursiveCharacterTextSplitter") as MockSplitter:
                        MockSplitter.return_value.split_documents.return_value = [mock_chunk]

                        client.post("/", json=_pubsub_body("bucket", "uploads/u/S/f.pdf"))

        mock_vs.add_documents.assert_called_once_with([mock_chunk])

    # Error handling

    def test_gcs_download_failure_sets_failed_status(self, client, mock_db):
        _, doc_ref = mock_db

        with patch.object(main, "storage_client") as mock_sc:
            mock_sc.bucket.return_value.blob.return_value.download_to_filename.side_effect = (
                Exception("GCS unavailable")
            )

            resp = client.post("/", json=_pubsub_body("bucket", "uploads/u/S/f.pdf"))

        assert resp.status_code == 500
        last_update = doc_ref.update.call_args_list[-1]
        assert last_update.args[0]["status"] == "Failed"

    def test_pdf_parse_failure_sets_failed_status(self, client, mock_db):
        _, doc_ref = mock_db

        with patch.object(main, "storage_client") as mock_sc:
            mock_sc.bucket.return_value.blob.return_value.download_to_filename = MagicMock()

            with patch.object(main, "PyPDFLoader") as MockLoader:
                MockLoader.return_value.load.side_effect = Exception("corrupt PDF")

                resp = client.post("/", json=_pubsub_body("bucket", "uploads/u/S/f.pdf"))

        assert resp.status_code == 500
        last_update = doc_ref.update.call_args_list[-1]
        assert last_update.args[0]["status"] == "Failed"

    def test_tmp_file_cleaned_up_on_success(self, client, mock_db):
        mock_chunk = MagicMock()
        mock_chunk.metadata = {}

        with patch.object(main, "storage_client") as mock_sc:
            mock_sc.bucket.return_value.blob.return_value.download_to_filename = MagicMock()

            with patch.object(main, "vector_store"):
                with patch.object(main, "PyPDFLoader") as MockLoader:
                    MockLoader.return_value.load.return_value = [MagicMock()]

                    with patch.object(main, "RecursiveCharacterTextSplitter") as MockSplitter:
                        MockSplitter.return_value.split_documents.return_value = [mock_chunk]

                        with patch.object(main.os, "remove") as mock_remove, \
                             patch.object(main.os.path, "exists", return_value=True):
                            client.post("/", json=_pubsub_body("bucket", "uploads/u/S/f.pdf"))

        mock_remove.assert_called_once()

    def test_tmp_file_cleaned_up_on_failure(self, client, mock_db):
        with patch.object(main, "storage_client") as mock_sc:
            mock_sc.bucket.return_value.blob.return_value.download_to_filename.side_effect = (
                Exception("fail")
            )
            with patch.object(main.os, "remove") as mock_remove, \
                 patch.object(main.os.path, "exists", return_value=True):
                client.post("/", json=_pubsub_body("bucket", "uploads/u/S/f.pdf"))

        mock_remove.assert_called_once()
