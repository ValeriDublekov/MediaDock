"""Backend test package."""

import sys
import unittest
from unittest.mock import MagicMock

# If third-party modules are not installed in the local execution environment,
# install lightweight stubs so that the unit test suite and fake-repository tests can run.
for mod_name in [
    "requests",
    "feedparser",
    "firebase_admin",
    "firebase_admin.credentials",
    "firebase_admin.firestore",
    "google",
    "google.cloud",
    "google.cloud.firestore",
    "google.cloud.firestore_v1",
    "google.cloud.firestore_v1.field_path",
    "google.genai",
    "google.genai.types",
    "google.genai.errors",
]:
    if mod_name not in sys.modules:
        try:
            __import__(mod_name)
        except ImportError:
            stub = MagicMock()
            sys.modules[mod_name] = stub
