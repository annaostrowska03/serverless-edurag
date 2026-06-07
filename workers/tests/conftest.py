"""
Patch all external cloud / ML dependencies before workers/main.py is imported.
"""
import os
import sys
from unittest.mock import MagicMock

# Make workers/ importable as a flat package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# chromadb
sys.modules["chromadb"] = MagicMock()

# langchain
sys.modules["langchain_chroma"] = MagicMock()
sys.modules["langchain_google_vertexai"] = MagicMock()

_loader_mod = MagicMock()
sys.modules["langchain_community"] = MagicMock()
sys.modules["langchain_community.document_loaders"] = _loader_mod

sys.modules["langchain_text_splitters"] = MagicMock()

# google.cloud.firestore / storage
_mock_firestore = MagicMock()
_mock_firestore.SERVER_TIMESTAMP = "SERVER_TIMESTAMP"
_mock_storage = MagicMock()

sys.modules["google.cloud.firestore"] = _mock_firestore
sys.modules["google.cloud.storage"] = _mock_storage

try:
    import google.cloud as _gcloud
    _gcloud.firestore = _mock_firestore
    _gcloud.storage = _mock_storage
except Exception:
    pass
