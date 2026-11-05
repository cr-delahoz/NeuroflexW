"""Export the VR development flow to an importable Postman v2.1 collection."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
METRICS = {
    "TiempoRespuestaPararse": 2.4,
    "Precision": 0.8,
    "TiempoActivoTarea": 120.0,
    "CantAciertasTotales": 8,
    "ObjetosInteractuadosCorrectamente": 8,
    "TiempoRespuestaPregunta1": 3.1,
    "TiempoRespuestaPregunta2": 4.2,
    "TiempoRespuestaPregunta3": 2.8,
    "TiempoCapturarNumero": 5.6,
    "TiempoTutorial": 30.0,
    "TipoEscena": 1,
}


def event(kind, code):
    return {"listen": kind, "script": {"type": "text/javascript", "exec": code.strip().splitlines()}}


def request(name, method, path, body=None, headers=None, before="", after="", description=""):
    result = {
        "name": name,
        "request": {
            "auth": {"type": "noauth"},
            "method": method,
            "header": [{"key": k, "value": v} for k, v in (headers or {}).items()],
            "url": path if path.startswith("https:") else "{{base_url}}" + path,
            "description": description,
        },
        "event": [],
    }
    if body is not None:
        result["request"]["body"] = {
            "mode": "raw", "raw": json.dumps(body, ensure_ascii=False, indent=2),
            "options": {"raw": {"language": "json"}},
        }
        result["request"]["header"].append({"key": "Content-Type", "value": "application/json"})
    if before:
        result["event"].append(event("prerequest", before))
    if after:
        result["event"].append(event("test", after))
    return result


def require(*keys):
    return "\n".join(
        f"if (!pm.variables.get({json.dumps(k)})) throw new Error('Falta la variable {k}; ejecuta el paso anterior.');"
        for k in keys
    )


def capture(mapping, extra=""):
    # The collection-level test validates HTTP and JSON before these scripts run.
    return """
if (pm.response.code < 200 || pm.response.code >= 300) {
    pm.execution.setNextRequest(null);
    throw new Error('Request fallida: HTTP ' + pm.response.code);
}
const data = pm.response.json();
""" + "\n".join(
        f"if (!data[{json.dumps(field)}]) {{ pm.execution.setNextRequest(null); throw new Error('Respuesta sin {field}'); }}"
        for field in mapping
    ) + "\n" + "\n".join(
        f"pm.collectionVariables.set({json.dumps(variable)}, data[{json.dumps(field)}]);"
        for field, variable in mapping.items()
    ) + "\n" + extra


def build():
    bearer = {"Authorization": "Bearer {{id_token}}"}
    auth = request(
        "0 - Software: obtener token Cognito", "POST",
        "https://cognito-idp.{{cognito_region}}.amazonaws.com/",
        headers={"Content-Type": "application/x-amz-json-1.1", "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth"},
        before=require("cognito_region", "cognito_client_id", "software_username", "software_password") + """
['id_token', 'confirmed_by_sub', 'version_id', 'content_hash', 'acceptance_token',
 'session_id', 'display_code', 'metrics_token', 'session_status', 'confirmed_email'].forEach(k => pm.collectionVariables.unset(k));
pm.request.body.update(JSON.stringify({AuthFlow:'USER_PASSWORD_AUTH', ClientId:pm.variables.get('cognito_client_id'),
 AuthParameters:{USERNAME:pm.variables.get('software_username'), PASSWORD:pm.variables.get('software_password')}}));
""",
        after=capture({}, """
if (!data.AuthenticationResult || !data.AuthenticationResult.IdToken) {
    pm.execution.setNextRequest(null);
    throw new Error('Cognito requiere un challenge (' + (data.ChallengeName || 'desconocido') + '); completa el acceso fuera del Runner.');
}
pm.collectionVariables.set('id_token', data.AuthenticationResult.IdToken);
// Decode only to obtain the query parameter; the API validates the JWT.
const payload = data.AuthenticationResult.IdToken.split('.')[1];
const claims = JSON.parse(Buffer.from(payload, 'base64').toString('utf8'));
pm.collectionVariables.set('confirmed_by_sub', claims.sub);
"""),
        description="Usa la cuenta SPECIALIST que debe recibir la sesión. No guarda contraseñas en el archivo ni imprime tokens.",
    )
    auth["request"]["body"] = {"mode": "raw", "raw": "{}", "options": {"raw": {"language": "json"}}}
    flow = [auth,
        request("1 - VR: obtener términos", "GET", "/terms/current", before=require("base_url"),
                after=capture({"version_id": "version_id", "content_hash": "content_hash"})),
        request("2 - VR: aceptar términos de prueba", "POST", "/terms/accept",
                {"version_id": "{{version_id}}", "content_hash": "{{content_hash}}", "application_version": "{{application_version}}"},
                before=require("version_id", "content_hash", "application_version"),
                after=capture({"acceptance_token": "acceptance_token"}),
                description="Simula la aceptación únicamente para esta prueba técnica con datos ficticios."),
        request("3 - VR: crear sesión", "POST", "/sessions", {"acceptance_token": "{{acceptance_token}}"},
                before=require("acceptance_token"),
                after=capture({"session_id": "session_id", "display_code": "display_code", "metrics_token": "metrics_token"},
                              "pm.collectionVariables.set('session_status', data.status || 'created');")),
        request("4 - Software: confirmar sesión", "POST", "{{confirm_path}}", {"display_code": "{{display_code}}"}, bearer,
                before=require("id_token", "display_code", "session_id", "confirm_path"),
                after=capture({}, """
if (data.session_id && data.session_id !== pm.variables.get('session_id')) {
    pm.execution.setNextRequest(null); throw new Error('La API confirmó otra sesión.');
}
pm.collectionVariables.set('session_status', data.status || 'confirmed');
if (data.confirmed_email) pm.collectionVariables.set('confirmed_email', data.confirmed_email);
"""),
                description="Solo se solicita el código de sesión (display_code). Ruta /sessions/confirm verificada contra /dev. Para probar también la asociación SQLite y auditoría de Django, ejecuta 0–3, confirma el código en el dashboard y continúa en 5."),
        request("5 - VR: enviar métricas ficticias", "POST", "/sessions/{{session_id}}/metrics", METRICS,
                {"X-Metrics-Token": "{{metrics_token}}"},
                before=require("session_id", "metrics_token"),
                after="""
if (pm.response.code >= 200 && pm.response.code < 300) {
    pm.collectionVariables.set('session_status', 'metrics_sent');
} else {
    pm.execution.setNextRequest(null); throw new Error('No se aceptaron las métricas: HTTP ' + pm.response.code);
}
""",
                description="Valores sintéticos, no mediciones de una persona. Precision=0.8 es un ejemplo técnico; confirmar la escala con el contrato del visor. No se solicita mano dominante para completar el flujo."),
        request("6 - Software: verificar sesión y métricas", "GET", "/sessions?confirmed_by_sub={{confirmed_by_sub}}", headers=bearer,
                before=require("id_token", "confirmed_by_sub", "session_id"), after=capture({}, """
const sessions = data.sessions || [];
const session = sessions.find(s => s.session_id === pm.variables.get('session_id'));
pm.test('La sesión aparece en esta página', () => pm.expect(session, 'Si hay next_cursor, consultar la página siguiente con cursor').to.exist);
if (!session) {
    pm.execution.setNextRequest(null); throw new Error('Sesión no encontrada en esta página. Revisa next_cursor y el usuario que confirmó.');
}
pm.test('Sesión completada', () => pm.expect(session.status).to.eql('completed'));
const expected = """ + json.dumps(METRICS) + """;
pm.test('Se conservaron las once métricas enviadas', () => {
    Object.keys(expected).forEach(k => pm.expect(session.metrics[k], k).to.eql(expected[k]));
});
pm.collectionVariables.set('session_status', session.status);
"""), description="GET usado por Django. Si devuelve next_cursor y no está la sesión, repetir agregando &cursor=<next_cursor>.")
    ]
    admin = request("ADMIN opcional - crear versión de términos", "POST", "/terms/versions",
                    {"version_id": "{{terms_version}}", "title": "Términos y condiciones de NeuroFlex VR", "content": "", "published": False},
                    {"Authorization": "Bearer {{admin_id_token}}"},
                    before=require("admin_id_token", "terms_version", "terms") + """
pm.request.body.update(JSON.stringify({version_id:pm.variables.get('terms_version'),
 title:'Términos y condiciones de NeuroFlex VR', content:String(pm.variables.get('terms')).replace(/\\r\\n?/g, '\\n'), published:false}));
""", after=capture({"version_id": "created_terms_version"}),
                    description="Ejecutar aparte con token ADMIN solo si hace falta una versión. Se crea sin publicar. No forma parte de cada sesión y no reemplaza los términos vigentes.")
    defaults = {
        "base_url": "https://i1eum0j7lf.execute-api.us-east-1.amazonaws.com/dev",
        "cognito_region": "us-east-1", "cognito_client_id": "65v6nki3fh1sgqbavlepf7gqkc",
        "software_username": "", "software_password": "", "application_version": "postman-sim-1.0.0",
        "confirm_path": "/sessions/confirm", "id_token": "", "confirmed_by_sub": "",
        "version_id": "", "content_hash": "", "acceptance_token": "", "session_id": "",
        "display_code": "", "metrics_token": "", "session_status": "", "confirmed_email": "",
        "admin_id_token": "", "terms_version": "", "terms": "",
    }
    collection = {
        "info": {"name": "VR Session Flow - Simulacion sin visor", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
                 "description": "Ejecutar solo la carpeta 01 en orden. Usa métricas ficticias. Ver postman/README.md. La carpeta 02 es administrativa y se ejecuta por separado."},
        "auth": {"type": "noauth"},
        "variable": [{"key": k, "value": v, "type": "string"} for k, v in defaults.items()],
        "event": [event("test", """
const ok = pm.response.code >= 200 && pm.response.code < 300;
if (!ok) pm.execution.setNextRequest(null);
pm.test('HTTP 2xx', () => pm.expect(ok, 'HTTP ' + pm.response.code).to.be.true);
if (!ok) { pm.execution.setNextRequest(null); throw new Error('Flujo detenido: HTTP ' + pm.response.code); }
if (pm.response.text().trim()) {
    try { pm.response.json(); } catch (e) { pm.execution.setNextRequest(null); throw new Error('La API devolvió una respuesta sin JSON válido'); }
}
""")],
        "item": [{"name": "01 - Flujo VR simulado (ejecutar esta carpeta)", "item": flow},
                 {"name": "02 - Administración opcional (ejecutar aparte)", "item": [admin]}],
    }
    (ROOT / "VR Session Flow - Simulacion.postman_collection.json").write_text(json.dumps(collection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "metricas_ejemplo.json").write_text(json.dumps(METRICS, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    build()
