from integrations.services.neuroflex_api_client import (
    NeuroflexApiClient,
    NeuroflexApiInvalidResponseError,
    NeuroflexApiNetworkError,
    NeuroflexApiResponseError,
)


ALLOWED_ROLES = {"Administrator", "Specialist"}


class ApiGatewayUsersClientError(Exception):
    pass


class ApiGatewayUsersNotFoundError(ApiGatewayUsersClientError):
    pass


class ApiGatewayUsersInvalidResponseError(ApiGatewayUsersClientError):
    pass


class ApiGatewayUsersServiceError(ApiGatewayUsersClientError):
    pass


class ApiGatewayUsersClient:
    def __init__(self, api_client=None):
        self.api_client = api_client or NeuroflexApiClient()

    @staticmethod
    def _validate_role(role):
        if not isinstance(role, str) or role not in ALLOWED_ROLES:
            raise ValueError("Remote role is invalid.")
        return role

    def list_users(self, token, role=None, is_active=None, limit=50, next_token=None):
        params = {"limit": limit}
        if role is not None:
            self._validate_role(role)
            params["role"] = role
        if is_active is not None:
            params["is_active"] = str(is_active).lower()
        if next_token is not None:
            params["next_token"] = next_token
        return self._parse_page(
            self._call(self.api_client.get, "/users", token=token, params=params)
        )

    def get_user(self, token, user_id):
        return self._parse_user(
            self._call(self.api_client.get, f"/users/{user_id}", token=token)
        )

    def create_user(self, token, email, role, profession_id=None):
        self._validate_role(role)
        json_body = {"email": email, "role": role}
        if profession_id:
            json_body["profession_id"] = profession_id
        return self._parse_user(
            self._call(
                self.api_client.post,
                "/users",
                token=token,
                json_body=json_body,
            )
        )

    def update_user_status(self, token, user_id, is_active):
        payload = self._call(
            self.api_client.patch,
            f"/users/{user_id}/status",
            token=token,
            json_body={"is_active": is_active},
        )
        return self._parse_user(payload)

    def update_user_role(self, token, user_id, role):
        self._validate_role(role)
        payload = self._call(
            self.api_client.patch,
            f"/users/{user_id}/role",
            token=token,
            json_body={"role": role},
        )
        return self._parse_user(payload)

    def update_user_profession(self, token, user_id, profession_id):
        if not isinstance(profession_id, str) or not profession_id:
            raise ValueError("Remote profession_id is invalid.")
        payload = self._call(
            self.api_client.patch,
            f"/users/{user_id}/profession",
            token=token,
            json_body={"profession_id": profession_id},
        )
        return self._parse_user(payload)

    @staticmethod
    def _call(method, *args, **kwargs):
        try:
            return method(*args, **kwargs)
        except NeuroflexApiResponseError as exc:
            if exc.status_code == 404:
                raise ApiGatewayUsersNotFoundError() from exc
            raise ApiGatewayUsersServiceError() from exc
        except NeuroflexApiNetworkError as exc:
            raise ApiGatewayUsersServiceError() from exc
        except NeuroflexApiInvalidResponseError as exc:
            raise ApiGatewayUsersInvalidResponseError() from exc

    @classmethod
    def _parse_user(cls, payload):
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("user_id"), str)
            or not payload["user_id"]
            or not isinstance(payload.get("email"), str)
            or not payload["email"]
        ):
            raise ApiGatewayUsersInvalidResponseError()
        if "role" in payload:
            role = payload["role"]
            if not isinstance(role, str) or role not in ALLOWED_ROLES:
                raise ApiGatewayUsersInvalidResponseError()
        if "is_active" in payload:
            is_active = payload["is_active"]
            if not isinstance(is_active, bool):
                raise ApiGatewayUsersInvalidResponseError()
        return {
            **payload,
            "onboarding_status": payload.get("onboarding_status", ""),
            "cognito_status": payload.get("cognito_status", ""),
        }

    @classmethod
    def _parse_page(cls, payload):
        if not isinstance(payload, dict) or not isinstance(payload.get("users"), list):
            raise ApiGatewayUsersInvalidResponseError()
        next_token = payload.get("next_token")
        if not isinstance(next_token, (str, type(None))):
            raise ApiGatewayUsersInvalidResponseError()
        return [cls._parse_user(user) for user in payload["users"]], next_token
