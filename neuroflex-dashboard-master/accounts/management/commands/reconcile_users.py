from django.core.management.base import BaseCommand, CommandError

from accounts.models import CustomUser
from accounts import services
from integrations.services.api_gateway_users_client import ApiGatewayUsersClient


class Command(BaseCommand):
    help = "Reconcile local Django users with remote Cognito/DynamoDB users"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--resolve", choices=["update", "report"], default="update"
        )
        parser.add_argument("--skip-orphans", action="store_true")
        parser.add_argument("--token", type=str, default=None)

    def handle(self, *args, **options):
        token = options["token"]
        if not token:
            self.stdout.write(self.style.ERROR("Missing reconciliation token."))
            raise CommandError("No token provided. Use --token <cognito_id_token>.")

        client = ApiGatewayUsersClient()
        remote_users = []
        next_token = None
        errors = 0

        while True:
            try:
                users, next_token = client.list_users(
                    token, limit=50, next_token=next_token
                )
            except Exception as exc:
                errors += 1
                self.stdout.write(self.style.ERROR(f"Remote user fetch error: {exc}"))
                break
            remote_users.extend(users)
            if next_token is None:
                break

        reconciled = 0
        for remote_user in remote_users:
            user_id = remote_user.get("user_id") if isinstance(remote_user, dict) else None
            email = remote_user.get("email") if isinstance(remote_user, dict) else None
            exists = (
                CustomUser.objects.filter(cognito_sub=user_id).exists()
                or CustomUser.objects.filter(email__iexact=email).exists()
                or CustomUser.objects.filter(username__iexact=email).exists()
            )
            action = "update" if exists else "create"
            details = (
                f"user_id={user_id} email={email} "
                f"role={remote_user.get('role')} is_active={remote_user.get('is_active')}"
            )
            if options["dry_run"] or options["resolve"] == "report":
                reconciled += 1
                self.stdout.write(f"Would {action}: {details}")
                continue
            try:
                services.sync_local_user_from_remote_user(remote_user)
            except Exception as exc:
                errors += 1
                self.stdout.write(self.style.ERROR(f"{action.title()} error: {details}: {exc}"))
            else:
                reconciled += 1
                self.stdout.write(self.style.SUCCESS(f"{action.title()}d: {details}"))

        remote_subs = {
            remote_user.get("user_id")
            for remote_user in remote_users
            if isinstance(remote_user, dict) and remote_user.get("user_id")
        }
        orphans = list(
            CustomUser.objects.exclude(cognito_sub__isnull=True)
            .exclude(cognito_sub="")
            .exclude(cognito_sub__in=remote_subs)
        )
        if not options["skip_orphans"]:
            for user in orphans:
                self.stdout.write(
                    f"Orphan: id={user.pk} cognito_sub={user.cognito_sub} email={user.email}"
                )

        self.stdout.write(f"Total remote users: {len(remote_users)}")
        self.stdout.write(f"Created/updated: {reconciled}")
        self.stdout.write(f"Errors: {errors}")
        self.stdout.write(f"Orphans: {len(orphans)}")
