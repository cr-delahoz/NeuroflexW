"""Run one synthetic VR session using only Python's standard library.

Credentials are read from environment variables or an interactive prompt.
Only the sanitized execution summary is saved; tokens stay in memory.
"""

import argparse
import base64
import getpass
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from build_collection import METRICS


class ApiError(RuntimeError):
    def __init__(self, step, status, payload):
        super().__init__(f"{step}: HTTP {status}; no se ejecutarán los pasos restantes")
        self.status = status
        self.payload = payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", default=os.getenv("SOFTWARE_USERNAME", ""))
    parser.add_argument("--check-routes-only", action="store_true", help="Probe confirmation routes with an empty body; do not create sessions.")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    collection = json.loads((root / "VR Session Flow - Simulacion.postman_collection.json").read_text(encoding="utf-8"))
    defaults = {entry["key"]: entry["value"] for entry in collection["variable"]}
    base_url = os.getenv("NEUROFLEX_DEV_BASE_URL", defaults["base_url"]).rstrip("/")
    if urllib.parse.urlparse(base_url).scheme != "https" or not urllib.parse.urlparse(base_url).path.endswith("/dev"):
        parser.error("This runner requires an HTTPS development URL ending in /dev.")
    report = {"executed_at_utc": datetime.now(timezone.utc).isoformat(), "synthetic": True, "base_url": base_url, "steps": []}

    def call(name, method, path, body=None, headers=None):
        url = path if path.startswith("https://") else base_url + path
        data = json.dumps(body).encode() if body is not None else None
        request_headers = dict(headers or {})
        if data is not None:
            request_headers.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(url, data=data, method=method, headers=request_headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                status, text = response.status, response.read().decode()
        except urllib.error.HTTPError as error:
            status, text = error.code, error.read().decode()
        except (urllib.error.URLError, TimeoutError) as error:
            report["steps"].append({"name": name, "http": None, "error": "network_error"})
            raise RuntimeError(f"{name}: network_error ({type(error).__name__})") from None
        report["steps"].append({"name": name, "http": status})
        print(f"{name}: HTTP {status}", flush=True)
        if not 200 <= status < 300:
            # Keep the error only in memory; never print arbitrary response bodies.
            try:
                payload = json.loads(text)
            except ValueError:
                payload = {}
            if payload.get("message") == "Missing Authentication Token":
                report["steps"][-1]["gateway_error"] = "Missing Authentication Token"
            raise ApiError(name, status, payload)
        return json.loads(text) if text.strip() else {}

    try:
        terms = call("1 Obtener términos", "GET", "/terms/current")
        report["terms_version"] = terms["version_id"]
        username = args.username or input("Usuario SPECIALIST de Cognito: ")
        password = os.getenv("SOFTWARE_PASSWORD") or getpass.getpass("Contraseña (no se guarda): ")
        region = os.getenv("COGNITO_REGION", defaults["cognito_region"])
        auth = call("0 Autenticación Cognito", "POST", f"https://cognito-idp.{region}.amazonaws.com/", {
            "AuthFlow": "USER_PASSWORD_AUTH",
            "ClientId": os.getenv("COGNITO_CLIENT_ID", defaults["cognito_client_id"]),
            "AuthParameters": {"USERNAME": username, "PASSWORD": password},
        }, {"Content-Type": "application/x-amz-json-1.1", "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth"})
        del password
        if not auth.get("AuthenticationResult", {}).get("IdToken"):
            raise RuntimeError("Cognito requiere challenge: " + auth.get("ChallengeName", "desconocido"))
        token = auth["AuthenticationResult"]["IdToken"]
        encoded_claims = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(encoded_claims + "=" * (-len(encoded_claims) % 4)))
        report["cognito_groups"] = claims.get("cognito:groups", [])
        if args.check_routes_only:
            for route in ("/software/sessions/confirm", "/sessions/confirm"):
                try:
                    call("Probar " + route, "POST", route, {}, {"Authorization": "Bearer " + token})
                except ApiError as error:
                    known = {"Missing Authentication Token", "display_code is required", "Missing display_code", "Invalid display_code"}
                    message = error.payload.get("message") or error.payload.get("error")
                    if isinstance(message, str) and message in known:
                        print("Respuesta:", message, flush=True)
            report["result"] = "routes_probed_without_creating_session"
            return 0
        acceptance = call("2 Aceptar términos de prueba", "POST", "/terms/accept", {
            "version_id": terms["version_id"], "content_hash": terms["content_hash"], "application_version": "postman-sim-1.0.0",
        })
        session = call("3 Crear sesión sintética", "POST", "/sessions", {"acceptance_token": acceptance["acceptance_token"]})
        session_id = session["session_id"]
        report["session_id"] = session_id
        print("session_id:", session_id, flush=True)
        print("display_code:", session["display_code"], flush=True)
        bearer = {"Authorization": "Bearer " + token}
        confirmation = call("4 Confirmar sesión", "POST", os.getenv("CONFIRM_PATH", defaults["confirm_path"]), {"display_code": session["display_code"]}, bearer)
        if confirmation.get("session_id", session_id) != session_id:
            raise RuntimeError("La API devolvió otra sesión al confirmar")
        call("5 Enviar métricas ficticias", "POST", f"/sessions/{session_id}/metrics", METRICS, {"X-Metrics-Token": session["metrics_token"]})
        cursor = None
        for page in range(20):
            params = {"confirmed_by_sub": claims["sub"]}
            if cursor:
                params["cursor"] = cursor
            listing = call("6 Verificar sesión (página " + str(page + 1) + ")", "GET", "/sessions?" + urllib.parse.urlencode(params), headers=bearer)
            found = next((s for s in listing.get("sessions", []) if s.get("session_id") == session_id), None)
            if found:
                report["session_status"] = found.get("status")
                report["metrics_match"] = all(found.get("metrics", {}).get(k) == v for k, v in METRICS.items())
                if report["session_status"] != "completed" or not report["metrics_match"]:
                    raise RuntimeError("La consulta final no confirma estado completed y las once métricas")
                report["result"] = "completed_verified"
                print("Verificado: completed y once métricas coinciden.", flush=True)
                return 0
            cursor = listing.get("next_cursor")
            if not cursor:
                break
        raise RuntimeError("La sesión no aparece en GET /sessions para el usuario que confirmó")
    except (RuntimeError, KeyError, ValueError) as error:
        report["result"] = "incomplete"
        report["error"] = str(error)
        print(str(error), file=sys.stderr, flush=True)
        return 1
    finally:
        (root / "ultima_prueba.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
