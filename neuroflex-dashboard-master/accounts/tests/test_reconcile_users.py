from io import StringIO
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase


User = get_user_model()


class ReconcileUsersCommandTests(TestCase):
    @patch("accounts.services.sync_local_user_from_remote_user")
    @patch("accounts.management.commands.reconcile_users.ApiGatewayUsersClient.list_users")
    def test_dry_run_reports_without_syncing(self, mock_list_users, mock_sync):
        mock_list_users.return_value = (
            [{"user_id": "sub-1", "email": "one@example.com", "role": "Specialist", "is_active": True}],
            None,
        )
        output = StringIO()

        call_command("reconcile_users", "--dry-run", "--token=test-token", stdout=output)

        mock_sync.assert_not_called()
        self.assertIn("would update", output.getvalue().lower())

    @patch("accounts.services.sync_local_user_from_remote_user")
    @patch("accounts.management.commands.reconcile_users.ApiGatewayUsersClient.list_users")
    def test_update_mode_syncs_users(self, mock_list_users, mock_sync):
        remote_user = {"user_id": "sub-1", "email": "one@example.com", "role": "Specialist", "is_active": True}
        mock_list_users.return_value = ([remote_user], None)
        mock_sync.return_value = Mock()
        output = StringIO()

        call_command("reconcile_users", "--token=test-token", stdout=output)

        mock_sync.assert_called_once_with(remote_user)
        self.assertIn("total remote users: 1", output.getvalue().lower())

    @patch("accounts.services.sync_local_user_from_remote_user")
    @patch("accounts.management.commands.reconcile_users.ApiGatewayUsersClient.list_users")
    def test_report_mode_reports_without_syncing(self, mock_list_users, mock_sync):
        mock_list_users.return_value = (
            [{"user_id": "sub-1", "email": "one@example.com", "role": "Specialist", "is_active": True}],
            None,
        )

        call_command("reconcile_users", "--resolve=report", "--token=test-token")

        mock_sync.assert_not_called()

    def test_command_exits_without_token(self):
        with self.assertRaises(CommandError):
            call_command("reconcile_users")

    @patch("accounts.management.commands.reconcile_users.ApiGatewayUsersClient.list_users")
    def test_command_reports_orphans(self, mock_list_users):
        User.objects.create_user(
            username="orphan@example.com",
            email="orphan@example.com",
            cognito_sub="orphan-sub",
        )
        mock_list_users.return_value = (
            [{"user_id": "sub-1", "email": "one@example.com", "role": "Specialist", "is_active": True}],
            None,
        )
        output = StringIO()

        call_command("reconcile_users", "--resolve=report", "--token=test-token", stdout=output)

        self.assertIn("orphan@example.com", output.getvalue())

    @patch("accounts.management.commands.reconcile_users.ApiGatewayUsersClient.list_users")
    def test_skip_orphans_hides_orphans(self, mock_list_users):
        User.objects.create_user(
            username="orphan@example.com",
            email="orphan@example.com",
            cognito_sub="orphan-sub",
        )
        mock_list_users.return_value = (
            [{"user_id": "sub-1", "email": "one@example.com", "role": "Specialist", "is_active": True}],
            None,
        )
        output = StringIO()

        call_command(
            "reconcile_users",
            "--resolve=report",
            "--skip-orphans",
            "--token=test-token",
            stdout=output,
        )

        self.assertNotIn("orphan@example.com", output.getvalue())

    @patch("accounts.services.sync_local_user_from_remote_user")
    @patch("accounts.management.commands.reconcile_users.ApiGatewayUsersClient.list_users")
    def test_command_handles_pagination(self, mock_list_users, mock_sync):
        first_user = {"user_id": "sub-1", "email": "one@example.com", "role": "Specialist", "is_active": True}
        second_user = {"user_id": "sub-2", "email": "two@example.com", "role": "Administrator", "is_active": True}
        mock_list_users.side_effect = [([first_user], "next"), ([second_user], None)]

        call_command("reconcile_users", "--token=test-token")

        self.assertEqual(mock_sync.call_count, 2)
        mock_sync.assert_any_call(first_user)
        mock_sync.assert_any_call(second_user)
