#!/usr/bin/env python3
"""Simulador de Quest para NeuroFlex Dashboard (consola interactiva).

Simula el flujo completo del visor Quest contra un dashboard LAN real,
sin necesidad de headset: discovery UDP, emparejamiento con PIN,
términos y condiciones, creación de sesión y envío de métricas.

El flujo completo (opción 7) respeta las pausas reales del visor:
    1. Busca el dashboard y reintenta hasta que el especialista pulse
       "Iniciar busqueda" en el Panel de control.
    2. Muestra el PIN y espera a que el especialista lo ingrese.
    3. Acepta los términos y crea la sesión (queda PENDIENTE).
    4. Espera a que el especialista pulse "Vincular sesion".
    5. Simula la duración de la sesión y recién entonces envía las métricas.
Ctrl+C cancela cualquier espera y vuelve al menú.

Solo usa la librería estándar. Ejecutar con:
    python tools/QuestSim/quest_simulator.py
"""

import json
import os
import random
import socket
import sys
import time
import urllib.error
import urllib.request
import uuid

DISCOVERY_PORT = 48100
DISCOVERY_TIMEOUT = 3.0
POLL_INTERVAL = 2.0         # segundos entre consultas de estado
SEARCH_RETRY = 3.0          # segundos entre reintentos mientras el dashboard no busca
SEARCH_TIMEOUT = 300        # espera máxima a que el especialista inicie la búsqueda
LINK_TIMEOUT = 600          # espera máxima a que el especialista vincule la sesión
DEFAULT_PLAY_SECONDS = 10   # duración simulada de la sesión en el visor
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".quest_sim_state.json")

METRIC_KEYS = [
    "TiempoRespuestaPararse",
    "Precision",
    "TiempoActivoTarea",
    "CantAciertasTotales",
    "ObjetosInteractuadosCorrectamente",
    "TiempoRespuestaPregunta1",
    "TiempoRespuestaPregunta2",
    "TiempoRespuestaPregunta3",
    "TiempoCapturarNumero",
    "TiempoTutorial",
    "TipoEscena",
]


class DeviceState:
    def __init__(self):
        self.data = {
            "device_id": "",
            "device_name": "",
            "device_token": "",
            "acceptance_token": "",
            "session_id": "",
            "metrics_token": "",
            "dashboard_url": "",
        }
        self.load()

    def load(self):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                self.data.update(json.load(f))
        except (OSError, ValueError):
            pass

    def save(self):
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)

    def ensure_identity(self):
        if not self.data["device_id"]:
            self.data["device_id"] = str(uuid.uuid4())
        if not self.data["device_name"]:
            self.data["device_name"] = "Quest-Sim-" + uuid.uuid4().hex[:6].upper()
        self.save()

    def reset(self):
        for key in self.data:
            self.data[key] = ""
        self.save()


state = DeviceState()


def hr():
    print("-" * 62)


def pause():
    input("\n[Enter] para volver al menu... ")


def http(method, url, payload=None, token=None, metrics_token=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if metrics_token:
        req.add_header("X-Metrics-Token", metrics_token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(body)
        except ValueError:
            return e.code, {"raw": body}
    except urllib.error.URLError as e:
        return 0, {"error": "Sin conexion: " + str(e.reason)}


def udp_discover():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(DISCOVERY_TIMEOUT)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        probe = "NEUROFLEX_DISCOVER|v1|" + (state.data["device_name"] or "Quest-Sim")
        sock.sendto(probe.encode("ascii"), ("255.255.255.255", DISCOVERY_PORT))
        try:
            reply, _ = sock.recvfrom(1024)
        except socket.timeout:
            return None
        parts = reply.decode("utf-8").split("|")
        if len(parts) >= 4 and parts[0] == "NEUROFLEX_HERE":
            return "http://" + parts[2] + ":" + parts[3]
        return None
    finally:
        sock.close()


def discover_dashboard(interactive=True):
    print("\nEnviando broadcast UDP (puerto %d)..." % DISCOVERY_PORT)
    url = udp_discover()
    if url:
        state.data["dashboard_url"] = url
        state.save()
        print("[OK] Dashboard descubierto:", url)
        return url
    if interactive:
        print("[--] Ningun dashboard respondio al broadcast.")
        manual = input("URL manual (ej. http://192.168.1.50:8000, vacio para cancelar): ").strip()
        if manual:
            state.data["dashboard_url"] = manual.rstrip("/")
            state.save()
            print("[OK] Dashboard manual:", state.data["dashboard_url"])
            return state.data["dashboard_url"]
    else:
        print("[--] Ningun dashboard respondio al broadcast.")
    return None


def ensure_dashboard():
    if state.data["dashboard_url"]:
        return state.data["dashboard_url"]
    return discover_dashboard()


def _request_pairing(url, pin):
    """Envía pair/request. Mientras el dashboard no esté buscando (403) reintenta,
    igual que el visor, hasta que el especialista pulse "Iniciar busqueda"."""
    deadline = time.time() + SEARCH_TIMEOUT
    last_error = None
    while True:
        code, body = http("POST", url + "/api/lan/pair/request", {
            "device_id": state.data["device_id"],
            "device_name": state.data["device_name"],
            "pin": pin,
        })
        if code == 201:
            if last_error:
                print()
            return body
        if code == 403:
            error = body.get("error", "El dashboard no esta aceptando emparejamientos")
            if error != last_error:
                print("\n[--] %s" % error)
                print("     En el Panel de control pulsa \"Iniciar busqueda\" (Ctrl+C para cancelar).")
                last_error = error
            if time.time() >= deadline:
                print("\n[FAIL] El dashboard no inicio la busqueda a tiempo.")
                return None
            remaining = int(deadline - time.time())
            print("\rBuscando dashboard... reintento cada %ds (%3ds restantes)" % (SEARCH_RETRY, remaining), end="", flush=True)
            time.sleep(SEARCH_RETRY)
            continue
        if code == 409:
            print("[FAIL] Ya hay otra solicitud de emparejamiento activa en el dashboard.")
            print("       Cancela el emparejamiento en el panel o espera a que expire.")
            return None
        if code == 0:
            print("[FAIL] %s" % body.get("error"))
            return None
        print("[FAIL] pair/request -> %s %s" % (code, json.dumps(body, ensure_ascii=False)))
        return None


def do_pair():
    """Empareja el dispositivo. Devuelve True si quedó con token válido."""
    state.ensure_identity()
    url = ensure_dashboard()
    if not url:
        return False
    pin = str(random.randint(100000, 999999))
    body = _request_pairing(url, pin)
    if body is None:
        return False

    print()
    hr()
    print("  PIN DE EMPAREJAMIENTO:  %s" % pin)
    print("  Ingresalo en el Panel de control (Vincular dispositivo).")
    hr()

    expires_in = body.get("expires_in", 180)
    deadline = time.time() + expires_in
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)
        code, body2 = http("GET", url + "/api/lan/pair/status/" + body["pairing_id"])
        if code == 200 and body2.get("status") == "confirmed":
            token = body2.get("device_token", "")
            if not token:
                print("\n[FAIL] Confirmado, pero el token ya fue entregado. Reinicia el emparejamiento.")
                return False
            state.data["device_token"] = token
            state.save()
            print("\n[OK] Emparejamiento confirmado. Token guardado.")
            return True
        if code == 200 and body2.get("status") == "expired":
            print("\n[FAIL] El PIN expiro o la busqueda fue cancelada en el dashboard.")
            return False
        if code == 404:
            print("\n[FAIL] Solicitud no encontrada en el dashboard.")
            return False
        remaining = int(deadline - time.time())
        print("\rEsperando confirmacion del especialista... (%3ds)" % remaining, end="", flush=True)
    print("\n[FAIL] Tiempo de emparejamiento agotado.")
    return False


def ensure_paired(url):
    """Reutiliza el token guardado si el dashboard aún lo acepta; si no, empareja."""
    if state.data["device_token"]:
        code, body = http("GET", url + "/api/lan/device/ping", token=state.data["device_token"])
        if code == 200:
            print("[OK] Dispositivo ya emparejado, se reutiliza el token guardado.")
            return True
        if code == 401:
            print("[--] El dashboard no reconoce el token (revocado o reinstalado). Se vuelve a emparejar.")
            state.data["device_token"] = ""
            state.save()
        else:
            print("[FAIL] No se pudo verificar el emparejamiento: %s %s" % (code, body.get("error", "")))
            return False
    return do_pair()


def do_terms_menu():
    state.ensure_identity()
    url = ensure_dashboard()
    if not url:
        return
    code, body = http("GET", url + "/api/lan/terms/current", token=state.data["device_token"])
    if code != 200:
        print("[FAIL] terms/current -> %s %s" % (code, json.dumps(body, ensure_ascii=False)))
        if code == 401:
            print("      (El dispositivo no esta emparejado o su token es invalido)")
        return

    print()
    hr()
    print("  TERMINOS Y CONDICIONES (version %s)" % body.get("version_id"))
    hr()
    content = body.get("content", "")
    preview = content if len(content) <= 400 else content[:400] + "..."
    print(preview)
    hr()
    choice = input("Presiona 1 para ACEPTAR, 2 para RECHAZAR: ").strip()
    if choice == "1":
        code, resp = http("POST", url + "/api/lan/terms/accept", {
            "version_id": body.get("version_id"),
            "content_hash": body.get("content_hash", ""),
            "application_version": "sim-1.0.0",
        }, token=state.data["device_token"])
        if code == 200 and resp.get("acceptance_token"):
            state.data["acceptance_token"] = resp["acceptance_token"]
            state.save()
            print("[OK] Terminos aceptados. acceptance_token guardado.")
        else:
            print("[FAIL] terms/accept -> %s %s" % (code, json.dumps(resp, ensure_ascii=False)))
    elif choice == "2":
        print("[--] Terminos rechazados (no se crea session).")
    else:
        print("[--] Opcion invalida.")


def do_create_session():
    """Crea la sesión (queda PENDIENTE hasta que el especialista la vincule)."""
    state.ensure_identity()
    url = ensure_dashboard()
    if not url:
        return False
    if not state.data["acceptance_token"]:
        print("[--] Primero acepta los terminos (opcion 3).")
        return False
    code, resp = http("POST", url + "/api/lan/sessions", {
        "acceptance_token": state.data["acceptance_token"],
        "patient_info": {"notes": "Sesion simulada por quest_simulator"},
    }, token=state.data["device_token"])
    if code == 201:
        state.data["session_id"] = resp.get("session_id", "")
        state.data["metrics_token"] = resp.get("metrics_token", "")
        # El acceptance_token es de un solo uso: ya quedo consumido.
        state.data["acceptance_token"] = ""
        state.save()
        print("[OK] Sesion creada: %s (pendiente de vincular)" % state.data["session_id"])
        return True
    print("[FAIL] sessions -> %s %s" % (code, json.dumps(resp, ensure_ascii=False)))
    return False


def _session_status(url):
    """Devuelve (codigo_http, estado_en_minusculas_o_None)."""
    code, resp = http("GET", url + "/api/lan/sessions/" + state.data["session_id"] + "/status",
                      metrics_token=state.data["metrics_token"])
    return code, (resp.get("status") if code == 200 else None)


def wait_for_link(url):
    """Pausa hasta que el especialista pulse "Vincular sesion" en el dashboard.

    Devuelve "confirmed", "gone" (sesion eliminada), "timeout" o el estado
    inesperado reportado por el dashboard.
    """
    print()
    hr()
    print("  Sesion creada en el visor. Falta que el especialista la vincule:")
    print("  en el Panel de control, \"Sesiones en curso\" -> \"Vincular sesion\".")
    print("  (Ctrl+C para cancelar la espera)")
    hr()
    deadline = time.time() + LINK_TIMEOUT
    while time.time() < deadline:
        code, status = _session_status(url)
        if code == 404:
            print("\n[FAIL] La sesion ya no existe en el dashboard (eliminada o token invalido).")
            return "gone"
        if code == 200:
            if status == "confirmed":
                print("\n[OK] Sesion vinculada por el especialista.")
                return "confirmed"
            if status != "pending":
                print("\n[--] Estado inesperado de la sesion: %s" % status)
                return status
        remaining = int(deadline - time.time())
        if code == 0:
            print("\rSin conexion con el dashboard, reintentando... (%3ds)  " % remaining, end="", flush=True)
        else:
            print("\rEsperando que el especialista vincule la sesion... (%3ds)  " % remaining, end="", flush=True)
        time.sleep(POLL_INTERVAL)
    print("\n[FAIL] Tiempo de espera agotado: la sesion no fue vinculada.")
    return "timeout"


def simulate_play(seconds):
    """Simula el tiempo que el paciente pasa dentro de la sesión VR."""
    print("\nSesion en curso en el visor (%ds simulados, Ctrl+C para cancelar)..." % seconds)
    for left in range(seconds, 0, -1):
        print("\rJugando... (%3ds)" % left, end="", flush=True)
        time.sleep(1)
    print("\rSesion terminada en el visor.        ")


def do_session_status():
    url = ensure_dashboard()
    if not url:
        return
    if not state.data["session_id"] or not state.data["metrics_token"]:
        print("[--] No hay sesion activa. Crea una sesion (opcion 4).")
        return
    code, resp = http("GET", url + "/api/lan/sessions/" + state.data["session_id"] + "/status",
                      metrics_token=state.data["metrics_token"])
    print("[...] status -> %s %s" % (code, json.dumps(resp, ensure_ascii=False)))
    if code == 200 and resp.get("status") == "pending":
        print("      Pendiente: el especialista debe pulsar \"Vincular sesion\" en el panel.")


def _simulated_metrics():
    metrics = {key: 0.0 for key in METRIC_KEYS}
    metrics["TiempoRespuestaPararse"] = round(random.uniform(1.0, 8.0), 2)
    metrics["Precision"] = round(random.uniform(70.0, 100.0), 2)
    metrics["TiempoActivoTarea"] = round(random.uniform(120.0, 420.0), 2)
    metrics["CantAciertasTotales"] = random.randint(1, 3)
    metrics["ObjetosInteractuadosCorrectamente"] = random.randint(1, 3)
    metrics["TiempoRespuestaPregunta1"] = round(random.uniform(2.0, 15.0), 2)
    metrics["TiempoRespuestaPregunta2"] = round(random.uniform(2.0, 15.0), 2)
    metrics["TiempoRespuestaPregunta3"] = round(random.uniform(2.0, 15.0), 2)
    metrics["TiempoCapturarNumero"] = round(random.uniform(1.5, 10.0), 2)
    metrics["TiempoTutorial"] = round(random.uniform(30.0, 180.0), 2)
    metrics["TipoEscena"] = random.randint(1, 2)
    return metrics


def do_send_metrics(wait_if_pending=True):
    """Envía métricas. El dashboard solo las acepta si la sesión ya fue vinculada."""
    url = ensure_dashboard()
    if not url:
        return False
    if not state.data["session_id"] or not state.data["metrics_token"]:
        print("[--] No hay sesion activa. Crea una sesion (opcion 4).")
        return False
    if wait_if_pending:
        code, status = _session_status(url)
        if code == 200 and status == "pending":
            print("[--] La sesion sigue pendiente: el especialista aun no la vincula.")
            if input("Esperar a que la vincule? (s/n): ").strip().lower() != "s":
                return False
            if wait_for_link(url) != "confirmed":
                return False
    metrics = _simulated_metrics()
    code, resp = http("POST", url + "/api/lan/sessions/" + state.data["session_id"] + "/metrics",
                      metrics, metrics_token=state.data["metrics_token"])
    if code == 200:
        print("[OK] Metricas enviadas:", json.dumps(metrics, ensure_ascii=False))
        state.data["metrics_token"] = ""
        state.save()
        return True
    if code == 409:
        print("[FAIL] La sesion no esta vinculada (o ya termino). El especialista debe pulsar \"Vincular sesion\".")
    elif code == 404:
        print("[FAIL] La sesion ya no existe en el dashboard (fue eliminada).")
    else:
        print("[FAIL] metrics -> %s %s" % (code, json.dumps(resp, ensure_ascii=False)))
    return False


def _ask_play_seconds():
    raw = input("Duracion simulada de la sesion en segundos [%d]: " % DEFAULT_PLAY_SECONDS).strip()
    if raw.isdigit() and int(raw) >= 0:
        return int(raw)
    return DEFAULT_PLAY_SECONDS


def do_full_flow():
    print("\n=== FLUJO COMPLETO ===")
    print("Se detiene cuando necesita al especialista: iniciar la busqueda,")
    print("ingresar el PIN y vincular la sesion en el Panel de control.")
    play_seconds = _ask_play_seconds()

    state.ensure_identity()
    url = ensure_dashboard()
    if not url:
        return

    print("\n[1/5] Busqueda y emparejamiento")
    if not ensure_paired(url):
        print("[--] Sin emparejamiento: flujo cancelado.")
        return

    print("\n[2/5] Terminos y condiciones (aceptacion automatica)")
    code, body = http("GET", url + "/api/lan/terms/current", token=state.data["device_token"])
    if code != 200:
        print("[FAIL] No se pudieron obtener los terminos: %s %s" % (code, body.get("error", "")))
        return
    code, resp = http("POST", url + "/api/lan/terms/accept", {
        "version_id": body.get("version_id"),
        "content_hash": body.get("content_hash", ""),
        "application_version": "sim-1.0.0",
    }, token=state.data["device_token"])
    if code != 200 or not resp.get("acceptance_token"):
        print("[FAIL] terms/accept -> %s %s" % (code, json.dumps(resp, ensure_ascii=False)))
        return
    state.data["acceptance_token"] = resp["acceptance_token"]
    state.save()
    print("[OK] Terminos aceptados.")

    print("\n[3/5] Creacion de sesion")
    if not do_create_session():
        return

    print("\n[4/5] Esperando la vinculacion del especialista")
    if wait_for_link(url) != "confirmed":
        print("[--] Flujo cancelado: la sesion no fue vinculada.")
        return

    print("\n[5/5] Sesion en el visor y envio de metricas")
    simulate_play(play_seconds)
    if do_send_metrics(wait_if_pending=False):
        print("\n=== FLUJO COMPLETO TERMINADO ===")
    else:
        print("\n=== FLUJO INTERRUMPIDO: las metricas no se enviaron ===")


def do_show_state():
    hr()
    print("  Estado del dispositivo simulado")
    hr()
    for key, value in state.data.items():
        shown = value if value else "(vacio)"
        if key == "device_token" and value:
            shown = value[:8] + "..." + value[-4:]
        print("  %-16s %s" % (key + ":", shown))
    hr()


MENU = """
============== NeuroFlex Quest Simulator ==============
 1) Descubrir dashboard (UDP broadcast)
 2) Emparejarse con dashboard (muestra PIN)
 3) Terminos y condiciones (1 = aceptar / 2 = rechazar)
 4) Crear sesion
 5) Consultar estado de sesion
 6) Enviar metricas simuladas
 7) Flujo completo (con pausas para el especialista)
 8) Ver estado del dispositivo
 9) Reset identidad del dispositivo
 0) Salir
=======================================================
"""


def main():
    print("NeuroFlex Quest Simulator - simula el visor VR en consola.")
    while True:
        print(MENU)
        opt = input("Opcion: ").strip()
        try:
            if opt == "1":
                state.ensure_identity()
                discover_dashboard()
            elif opt == "2":
                do_pair()
            elif opt == "3":
                do_terms_menu()
            elif opt == "4":
                do_create_session()
            elif opt == "5":
                do_session_status()
            elif opt == "6":
                do_send_metrics()
            elif opt == "7":
                do_full_flow()
            elif opt == "8":
                do_show_state()
            elif opt == "9":
                confirm = input("Esto borra la identidad y tokens. Confirmar (s/n): ").strip().lower()
                if confirm == "s":
                    state.reset()
                    print("[OK] Identidad reseteada.")
            elif opt == "0":
                print("Hasta luego.")
                return
            else:
                print("[--] Opcion no reconocida.")
        except KeyboardInterrupt:
            print("\n[--] Operacion cancelada.")
        except Exception as exc:
            print("[ERROR] %s: %s" % (type(exc).__name__, exc))


if __name__ == "__main__":
    main()
