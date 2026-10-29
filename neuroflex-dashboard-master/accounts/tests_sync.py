from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from integrations.services.api_gateway_users_client import (
    ApiGatewayUsersNotFoundError,
    ApiGatewayUsersServiceError,
)
from accounts.services import (
    reconcile_local_users_from_remote_listing,
    sync_local_user_from_remote_user,
)

User = get_user_model()


class RemoteUserSyncTests(TestCase):
    def test_sync_falls_back_to_email_only_for_unlinked_profile_and_preserves_local_fields(self):
        user = User.objects.create_user(username="old@example.com", email="ana@example.com", password="x", first_name="Ana", last_name="Paz", can_generate_pdf_without_approval=True)

        synced = sync_local_user_from_remote_user({"user_id": "sub-1", "email": "ana@example.com", "role": "Administrator", "is_active": True})

        self.assertEqual(synced.pk, user.pk)
        self.assertEqual(synced.cognito_sub, "sub-1")
        self.assertEqual(synced.username, "ana@example.com")
        self.assertEqual(synced.role, User.Role.ADMIN)
        self.assertTrue(synced.can_generate_pdf_without_approval)

    def test_incomplete_payload_does_not_create_or_modify_local_user(self):
        user = User.objects.create_user(username="ana@example.com", email="ana@example.com", password="x")

        with self.assertRaises(ValueError):
            sync_local_user_from_remote_user({"email": "ana@example.com", "role": "Specialist", "is_active": True})
        with self.assertRaises(ValueError):
            sync_local_user_from_remote_user({"user_id": "sub-1", "role": "Specialist", "is_active": True})

        user.refresh_from_db()
        self.assertIsNone(user.cognito_sub)

    def test_sync_accepts_extra_keys_when_all_required_fields_present(self):
        synced = sync_local_user_from_remote_user({
            "user_id": "sub-1",
            "email": "ana@example.com",
            "role": "Specialist",
            "is_active": True,
            "updated_at": 1787092824,
        })

        self.assertEqual(synced.cognito_sub, "sub-1")
        self.assertTrue(synced.is_active)

    def test_sync_rejects_missing_required_field_even_with_extra_keys(self):
        with self.assertRaises(ValueError):
            sync_local_user_from_remote_user({
                "email": "ana@example.com",
                "role": "Specialist",
                "is_active": True,
                "updated_at": 1787092824,
            })

    def test_sync_accepts_partial_payload_and_preserves_missing_fields(self):
        user = User.objects.create_user(
            username="ana@example.com",
            email="ana@example.com",
            password="x",
            role=User.Role.SPECIALIST,
            is_active=True,
        )

        synced = sync_local_user_from_remote_user({
            "user_id": "sub-1",
            "email": "ana@example.com",
            "is_active": False,
        })

        self.assertEqual(synced.pk, user.pk)
        self.assertEqual(synced.cognito_sub, "sub-1")
        self.assertFalse(synced.is_active)
        self.assertEqual(synced.role, User.Role.SPECIALIST)

    def test_sync_updates_role_when_present_and_preserves_is_active_when_absent(self):
        user = User.objects.create_user(
            username="ana@example.com",
            email="ana@example.com",
            password="x",
            role=User.Role.SPECIALIST,
            is_active=False,
        )

        synced = sync_local_user_from_remote_user({
            "user_id": "sub-1",
            "email": "ana@example.com",
            "role": "Administrator",
        })

        self.assertEqual(synced.role, User.Role.ADMIN)
        self.assertFalse(synced.is_active)

    def test_sync_rejects_invalid_role_when_present(self):
        user = User.objects.create_user(
            username="ana@example.com",
            email="ana@example.com",
            password="x",
            role=User.Role.SPECIALIST,
            is_active=True,
        )

        with self.assertRaises(ValueError):
            sync_local_user_from_remote_user({
                "user_id": "sub-1",
                "email": "ana@example.com",
                "role": "ADMIN",
            })

        user.refresh_from_db()
        self.assertEqual(user.role, User.Role.SPECIALIST)
        self.assertTrue(user.is_active)

    def test_sync_rejects_non_bool_is_active_when_present(self):
        user = User.objects.create_user(
            username="ana@example.com",
            email="ana@example.com",
            password="x",
            role=User.Role.SPECIALIST,
            is_active=True,
        )

        with self.assertRaises(ValueError):
            sync_local_user_from_remote_user({
                "user_id": "sub-1",
                "email": "ana@example.com",
                "is_active": "true",
            })

        user.refresh_from_db()
        self.assertTrue(user.is_active)

    def test_sync_rejects_non_string_role_without_creating_local_user(self):
        with self.assertRaises(ValueError):
            sync_local_user_from_remote_user({
                "user_id": "sub-1",
                "email": "ana@example.com",
                "role": ["Specialist"],
            })

        self.assertFalse(User.objects.filter(cognito_sub="sub-1").exists())
        self.assertFalse(User.objects.filter(email="ana@example.com").exists())

    def test_sync_rejects_non_bool_is_active_without_creating_local_user(self):
        with self.assertRaises(ValueError):
            sync_local_user_from_remote_user({
                "user_id": "sub-1",
                "email": "ana@example.com",
                "is_active": 1,
            })

        self.assertFalse(User.objects.filter(cognito_sub="sub-1").exists())
        self.assertFalse(User.objects.filter(email="ana@example.com").exists())

    def test_sync_allows_missing_role_and_is_active(self):
        user = User.objects.create_user(
            username="ana@example.com",
            email="ana@example.com",
            password="x",
            role=User.Role.SPECIALIST,
            is_active=True,
        )

        synced = sync_local_user_from_remote_user({
            "user_id": "sub-1",
            "email": "ana@example.com",
        })

        self.assertEqual(synced.pk, user.pk)
        self.assertEqual(synced.cognito_sub, "sub-1")
        self.assertEqual(synced.role, User.Role.SPECIALIST)
        self.assertTrue(synced.is_active)

    def test_reconciliation_accepts_extra_keys_in_listing(self):
        client = Mock()
        client.list_users.return_value = ([
            {
                "user_id": "sub-1",
                "email": "one@example.com",
                "role": "Specialist",
                "is_active": True,
                "updated_at": 1787092824,
            },
        ], None)

        users = reconcile_local_users_from_remote_listing("id-token", client)

        self.assertEqual([user.cognito_sub for user in users], ["sub-1"])
        self.assertTrue(users[0].is_active)

    def test_reconciliation_confirms_missing_sub_before_deleting(self):
        stale = User.objects.create_user(username="stale@example.com", password="x", cognito_sub="stale-sub")
        client = Mock()
        client.list_users.side_effect = [
            ([{"user_id": "sub-1", "email": "one@example.com", "role": "Specialist", "is_active": True}], "page-2"),
            ([{"user_id": "sub-2", "email": "two@example.com", "role": "Administrator", "is_active": False}], None),
        ]
        client.get_user.side_effect = ApiGatewayUsersNotFoundError("missing")

        users = reconcile_local_users_from_remote_listing("id-token", client)

        self.assertEqual([user.cognito_sub for user in users], ["sub-1", "sub-2"])
        self.assertFalse(User.objects.filter(pk=stale.pk).exists())
        self.assertEqual(client.list_users.call_count, 2)
        client.get_user.assert_called_once_with("id-token", "stale-sub")

    def test_reconciliation_does_not_delete_when_second_page_fails(self):
        stale = User.objects.create_user(username="stale@example.com", password="x", cognito_sub="stale-sub")
        client = Mock()
        client.list_users.side_effect = [([], "page-2"), ApiGatewayUsersServiceError("offline")]

        with self.assertRaises(ApiGatewayUsersServiceError):
            reconcile_local_users_from_remote_listing("id-token", client)

        self.assertTrue(User.objects.filter(pk=stale.pk).exists())

    def test_reconciliation_preserves_locals_on_repeated_token_or_unconfirmed_absence(self):
        stale = User.objects.create_user(username="stale@example.com", password="x", cognito_sub="stale-sub")
        client = Mock()
        client.list_users.side_effect = [([], "page-1"), ([], "page-1")]

        with self.assertRaises(ApiGatewayUsersServiceError):
            reconcile_local_users_from_remote_listing("id-token", client)

        self.assertTrue(User.objects.filter(pk=stale.pk).exists())

    def test_reconciliation_resolves_conflicts_without_rollback(self):
        blocked = User.objects.create_user(username="blocked@example.com", email="blocked@example.com", password="x", cognito_sub="blocked-sub")
        primary = User.objects.create_user(username="primary@example.com", email="primary@example.com", password="x", cognito_sub="primary-sub")
        stale = User.objects.create_user(username="stale@example.com", password="x", cognito_sub="stale-sub")
        refreshed = User.objects.create_user(username="refreshed@example.com", password="x", cognito_sub="refreshed-sub")
        client = Mock()
        client.list_users.return_value = ([
            {"user_id": "primary-sub", "email": "updated@example.com", "role": "Specialist", "is_active": True},
            {"user_id": "blocked-sub", "email": "blocked@example.com", "role": "Specialist", "is_active": True},
        ], None)
        client.get_user.side_effect = [
            ApiGatewayUsersNotFoundError("missing"),
            {"user_id": "refreshed-sub", "email": "blocked@example.com", "role": "Specialist", "is_active": True},
        ]

        reconcile_local_users_from_remote_listing("id-token", client)

        primary.refresh_from_db()
        refreshed.refresh_from_db()
        self.assertEqual(primary.email, "updated@example.com")
        self.assertTrue(User.objects.filter(pk=blocked.pk).exists())
        self.assertFalse(User.objects.filter(pk=stale.pk).exists())
        self.assertTrue(User.objects.filter(pk=refreshed.pk).exists())
        self.assertEqual(refreshed.email, "blocked@example.com")
        self.assertEqual(refreshed.username, "refreshed@example.com")

    def test_reconciliation_syncs_confirmed_get_and_preserves_transport_failures_and_unlinked(self):
        missing = User.objects.create_user(username="missing@example.com", password="x", cognito_sub="missing-sub")
        uncertain = User.objects.create_user(username="uncertain@example.com", password="x", cognito_sub="uncertain-sub")
        unlinked = User.objects.create_user(username="local@example.com", password="x")
        client = Mock()
        client.list_users.return_value = ([], None)
        client.get_user.side_effect = [
            {"user_id": "missing-sub", "email": "fresh@example.com", "role": "Specialist", "is_active": True},
            ApiGatewayUsersServiceError("timeout"),
        ]

        reconcile_local_users_from_remote_listing("id-token", client)

        missing.refresh_from_db()
        self.assertEqual(missing.email, "fresh@example.com")
        self.assertTrue(User.objects.filter(pk=uncertain.pk).exists())
        self.assertTrue(User.objects.filter(pk=unlinked.pk).exists())
