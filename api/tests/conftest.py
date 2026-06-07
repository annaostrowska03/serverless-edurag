"""
Patch all external cloud / ML dependencies BEFORE api/main.py is imported.
This module-level code runs when pytest collects conftest.py, which happens
before any test file imports anything from the api package.
"""
import os
import sys
from unittest.mock import MagicMock

# Make api/ importable as a flat package (for `import main`, `import prompts`)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# firebase_admin
_fb_auth = MagicMock()
_fb = MagicMock()
_fb.auth = _fb_auth
sys.modules["firebase_admin"] = _fb
sys.modules["firebase_admin.auth"] = _fb_auth

# flask_cors
sys.modules["flask_cors"] = MagicMock()

# chromadb
sys.modules["chromadb"] = MagicMock()

# langchain
sys.modules["langchain_chroma"] = MagicMock()
sys.modules["langchain_google_vertexai"] = MagicMock()

# langchain_core must look like a package (__path__) so sub-imports work
_lc_core = MagicMock()
_lc_core.__path__ = []

_lc_messages = MagicMock()
_lc_messages.AIMessage = MagicMock
_lc_messages.HumanMessage = MagicMock
_lc_messages.SystemMessage = MagicMock

sys.modules["langchain_core"] = _lc_core
sys.modules["langchain_core.messages"] = _lc_messages
sys.modules["langchain_core.prompts"] = MagicMock()  # used by api/prompts.py

# google.cloud.firestore / storage
_mock_firestore = MagicMock()
_mock_firestore.SERVER_TIMESTAMP = "SERVER_TIMESTAMP"
_mock_storage = MagicMock()

sys.modules["google.cloud.firestore"] = _mock_firestore
sys.modules["google.cloud.storage"] = _mock_storage

# Also set as attributes on the real google.cloud namespace package so that
# `from google.cloud import firestore, storage` resolves to our mocks.
try:
    import google.cloud as _gcloud  # noqa: E402
    _gcloud.firestore = _mock_firestore
    _gcloud.storage = _mock_storage
except Exception:
    pass

# google.auth (used inside generate_upload_url)
_mock_google_auth = MagicMock()
_mock_google_auth_transport = MagicMock()
_mock_google_auth_transport_requests = MagicMock()
sys.modules["google.auth"] = _mock_google_auth
sys.modules["google.auth.transport"] = _mock_google_auth_transport
sys.modules["google.auth.transport.requests"] = _mock_google_auth_transport_requests
try:
    import google  # noqa: E402
    google.auth = _mock_google_auth
except Exception:
    pass
