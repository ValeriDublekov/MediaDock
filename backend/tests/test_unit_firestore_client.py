import os
import unittest
from unittest.mock import patch

try:
    from . import _test_stubs
except ImportError:
    import _test_stubs

from google.auth.credentials import AnonymousCredentials

import movies_feed.firestore_repository as firestore_repository
from movies_feed.firestore_repository import get_firestore_client


class FirestoreClientTests(unittest.TestCase):
    def test_emulator_uses_anonymous_credentials_and_requested_database(self) -> None:
        emulator_client = object()

        with (
            patch.dict(
                os.environ,
                {"FIRESTORE_EMULATOR_HOST": "127.0.0.1:8080"},
                clear=True,
            ),
            patch.object(
                firestore_repository.cloud_firestore,
                "Client",
                return_value=emulator_client,
            ) as cloud_client,
            patch.object(firestore_repository.firebase_admin, "initialize_app") as initialize_app,
            patch("firebase_admin.credentials.Certificate") as certificate,
            patch("subprocess.run") as subprocess_run,
        ):
            result = get_firestore_client(
                project_id="demo-mediadock",
                database_id="catalog",
            )

        self.assertIs(result, emulator_client)
        cloud_client.assert_called_once()
        call_kwargs = cloud_client.call_args.kwargs
        self.assertEqual(call_kwargs["project"], "demo-mediadock")
        self.assertEqual(call_kwargs["database"], "catalog")
        self.assertIsInstance(call_kwargs["credentials"], AnonymousCredentials)
        initialize_app.assert_not_called()
        certificate.assert_not_called()
        subprocess_run.assert_not_called()

    def test_default_database_ids_use_the_default_emulator_database(self) -> None:
        for database_id in ("(default)", "%28default%29", ""):
            with self.subTest(database_id=database_id):
                with (
                    patch.dict(
                        os.environ,
                        {"FIRESTORE_EMULATOR_HOST": "127.0.0.1:8080"},
                        clear=True,
                    ),
                    patch.object(
                        firestore_repository.cloud_firestore,
                        "Client",
                        return_value=object(),
                    ) as cloud_client,
                ):
                    get_firestore_client(
                        project_id="demo-mediadock",
                        database_id=database_id,
                    )

                self.assertNotIn("database", cloud_client.call_args.kwargs)

    def test_production_branch_initializes_firebase_admin_and_creates_client(self) -> None:
        production_client = object()

        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(firestore_repository.firebase_admin, "_apps", {}),
            patch.object(firestore_repository.firebase_admin, "initialize_app") as initialize_app,
            patch.object(
                firestore_repository.firestore,
                "client",
                return_value=production_client,
            ) as firestore_client,
        ):
            result = get_firestore_client(
                project_id="production-project",
                database_id="catalog",
            )

        self.assertIs(result, production_client)
        initialize_app.assert_called_once_with()
        firestore_client.assert_called_once_with(database_id="catalog")

    def test_default_database_ids_use_the_default_production_database(self) -> None:
        for database_id in ("(default)", "%28default%29", ""):
            with self.subTest(database_id=database_id):
                with (
                    patch.dict(os.environ, {}, clear=True),
                    patch.object(firestore_repository.firebase_admin, "_apps", {}),
                    patch.object(
                        firestore_repository.firebase_admin,
                        "initialize_app",
                    ) as initialize_app,
                    patch.object(
                        firestore_repository.firestore,
                        "client",
                        return_value=object(),
                    ) as firestore_client,
                ):
                    get_firestore_client(
                        project_id="production-project",
                        database_id=database_id,
                    )

                initialize_app.assert_called_once_with()
                firestore_client.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()