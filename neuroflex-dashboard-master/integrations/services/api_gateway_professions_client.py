from integrations.services.neuroflex_api_client import (
    NeuroflexApiClient,
    NeuroflexApiInvalidResponseError,
    NeuroflexApiNetworkError,
    NeuroflexApiResponseError,
)


DEFAULT_PROFESSION_ID = "sin-profesion"
DEFAULT_PROFESSION_NAME = "Sin profesion asignada"


class ApiGatewayProfessionsClientError(Exception):
    pass


class ApiGatewayProfessionsNotFoundError(ApiGatewayProfessionsClientError):
    pass


class ApiGatewayProfessionsInvalidResponseError(ApiGatewayProfessionsClientError):
    pass


class ApiGatewayProfessionsServiceError(ApiGatewayProfessionsClientError):
    pass


class ApiGatewayProfessionsClient:
    def __init__(self, api_client=None):
        self.api_client = api_client or NeuroflexApiClient()

    def list_professions(self, token, is_active=None):
        params = {}
        if is_active is not None:
            params["is_active"] = str(is_active).lower()
        return self._parse_page(
            self._call(self.api_client.get, "/professions", token=token, params=params)
        )

    def create_profession(self, token, name):
        payload = self._call(
            self.api_client.post,
            "/professions",
            token=token,
            json_body={"name": name},
        )
        return self._parse_profession(payload)

    def delete_profession(self, token, profession_id, reassign_to=None):
        params = {}
        if reassign_to is not None:
            params["reassign_to"] = reassign_to
        payload = self._call(
            self.api_client.delete,
            f"/professions/{profession_id}",
            token=token,
            params=params,
        )
        return self._parse_deletion(payload)

    @staticmethod
    def _call(method, *args, **kwargs):
        try:
            return method(*args, **kwargs)
        except NeuroflexApiResponseError as exc:
            if exc.status_code == 404:
                raise ApiGatewayProfessionsNotFoundError() from exc
            raise ApiGatewayProfessionsServiceError() from exc
        except NeuroflexApiNetworkError as exc:
            raise ApiGatewayProfessionsServiceError() from exc
        except NeuroflexApiInvalidResponseError as exc:
            raise ApiGatewayProfessionsInvalidResponseError() from exc

    @classmethod
    def _parse_profession(cls, payload):
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("profession_id"), str)
            or not payload["profession_id"]
            or not isinstance(payload.get("name"), str)
            or not payload["name"]
        ):
            raise ApiGatewayProfessionsInvalidResponseError()
        return {
            **payload,
            "is_default": bool(payload.get("is_default", False)),
            "is_active": bool(payload.get("is_active", True)),
            "created_at": payload.get("created_at", 0),
        }

    @classmethod
    def _parse_page(cls, payload):
        if not isinstance(payload, dict) or not isinstance(
            payload.get("professions"), list
        ):
            raise ApiGatewayProfessionsInvalidResponseError()
        return [cls._parse_profession(item) for item in payload["professions"]]

    @staticmethod
    def _parse_deletion(payload):
        if not isinstance(payload, dict) or not isinstance(
            payload.get("profession_id"), str
        ):
            raise ApiGatewayProfessionsInvalidResponseError()
        return {
            "profession_id": payload["profession_id"],
            "reassigned_users": int(payload.get("reassigned_users", 0)),
            "reassigned_to": payload.get("reassigned_to", ""),
        }
