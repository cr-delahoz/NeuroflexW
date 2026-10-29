import os
import socket
import sys
import threading
import time
from pathlib import Path

import ctypes
import requests
import webview
from integrations.services.runtime_config import RuntimeConfig


_mutex_handle = None


def get_http_port() -> str:
    """Return the configured LAN HTTP port.

    The launcher runs before Django loads its settings, so the port is read
    straight from the environment (same variable config.settings consumes).
    """
    return os.environ.get("LAN_HTTP_PORT", "8000")


SERVER_URL = f"http://127.0.0.1:{get_http_port()}"
SERVER_STARTUP_TIMEOUT_SECONDS = 30
SERVER_POLL_INTERVAL_SECONDS = 0.25
NEUROFLEX_APP_MARKER = "NeuroFlex"
SW_RESTORE = 9


def is_already_running() -> bool:
    global _mutex_handle
    kernel32 = ctypes.windll.kernel32
    ERROR_ALREADY_EXISTS = 183
    _mutex_handle = kernel32.CreateMutexW(None, False, "Local\\NeuroFlexSingleInstance")
    return kernel32.GetLastError() == ERROR_ALREADY_EXISTS


def activate_existing_window():
    try:
        user32 = ctypes.windll.user32
        window_handle = user32.FindWindowW(None, "NeuroFlex Dashboard")
        if window_handle:
            user32.ShowWindow(window_handle, SW_RESTORE)
            if user32.SetForegroundWindow(window_handle):
                return
    except OSError:
        pass

    user32.MessageBoxW(
        None,
        "NeuroFlex Dashboard ya se esta ejecutando.",
        "NeuroFlex Dashboard",
        0x40,
    )


def _is_null_stream(stream) -> bool:
    """Return True if the stream is missing or writes to the null device.

    In frozen windowed builds, sys.stdout/sys.stderr start as None, but
    importing webview replaces them with a file opened on os.devnull
    (webview/http.py) before main() runs. A truthiness check alone never
    sees that replacement, so the null-device name must be checked too.
    """
    if not stream:
        return True
    return str(getattr(stream, "name", "") or "").lower() in ("nul", "/dev/null")


def redirect_stdout_if_frozen():
    if not getattr(sys, "frozen", False):
        return
    if _is_null_stream(sys.stdout) or _is_null_stream(sys.stderr):
        log_path = (
            Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
            / "NeuroFlex"
            / "launcher_stdout.log"
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        f = open(log_path, "a", encoding="utf-8")
        sys.stdout = f
        sys.stderr = f


def get_data_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        local_app_data = str(Path.home())
    return Path(local_app_data) / "NeuroFlex" / "data"


def setup_environment():
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    os.environ["NEUROFLEX_DATA_DIR"] = str(data_dir)
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"

    # Guardia de descubrimiento LAN: el listener UDP (offline_mode/apps.py)
    # SOLO arranca si esta variable de entorno esta presente, y este launcher
    # es el unico lugar que la setea. Debe definirse ANTES de que Django cargue
    # settings (django.setup()) para que AppConfig.ready() la vea. Nunca
    # agregarla a .env ni a config/settings.py: asi `manage.py runserver` y
    # despliegues en produccion nunca inician el discovery UDP sin intencion.
    os.environ.setdefault("LAN_HTTP_PORT", "8000")
    os.environ["LAN_DISCOVERY_FORCE"] = "1"

    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else Path(sys.executable).parent
        os.environ["PYTHONPATH"] = str(base)


def ensure_secret_key(data_dir: Path):
    env_file = data_dir / ".env"
    if not env_file.exists():
        return
    content = env_file.read_text(encoding="utf-8")
    if "DJANGO_SECRET_KEY=change-me" not in content:
        return
    import secrets as _secrets
    new_key = _secrets.token_urlsafe(50)
    content = content.replace(
        "DJANGO_SECRET_KEY=change-me",
        f"DJANGO_SECRET_KEY={new_key}",
    )
    env_file.write_text(content, encoding="utf-8")


def validate_critical_env():
    """Validate critical environment variables before Django starts.

    COGNITO_CLIENT_ID and NEUROFLEX_API_BASE_URL are required for login; if
    they are missing or still "change-me", the configuration was likely lost
    during an update and the user must reinstall the application. GITHUB_TOKEN
    is optional and only affects update checks, so a missing token only warns.
    """
    from dotenv import load_dotenv

    load_dotenv(get_data_dir() / ".env", override=False)

    runtime_config = RuntimeConfig()
    client_id = runtime_config.get_cognito_client_id()
    api_base_url = runtime_config.get_neuroflex_api_base_url()
    github_token = runtime_config.get_github_token()

    if not github_token:
        print(
            "[launcher] Advertencia: GITHUB_TOKEN no configurado; "
            "las comprobaciones de actualizacion no estaran disponibles.",
            file=sys.stderr,
        )

    missing = []
    if not client_id or client_id == "change-me":
        missing.append("COGNITO_CLIENT_ID")
    if not api_base_url or api_base_url == "change-me":
        missing.append("NEUROFLEX_API_BASE_URL")

    if not missing:
        return

    message = (
        "NeuroFlex Dashboard no puede iniciarse porque la configuracion "
        "se perdio durante una actualizacion.\n\n"
        "Faltan las siguientes variables de configuracion:\n"
        + "\n".join(f"- {name}" for name in missing)
        + "\n\n"
        "Debe reinstalar la aplicacion para restaurar la configuracion."
    )
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, message, "NeuroFlex Dashboard", 0x10)
    else:
        print(message, file=sys.stderr)
    sys.exit(1)


def is_webview2_runtime_available() -> bool:
    """Return whether the Windows WebView2 Runtime registry entry is present."""
    if sys.platform != "win32":
        return True

    try:
        import winreg

        runtime_keys = (
            (
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients"
                r"\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
            ),
            (
                winreg.HKEY_CURRENT_USER,
                r"SOFTWARE\Microsoft\EdgeUpdate\Clients"
                r"\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
            ),
        )
        for root_key, sub_key in runtime_keys:
            try:
                with winreg.OpenKey(root_key, sub_key):
                    return True
            except OSError:
                continue
    except OSError:
        return False
    return False


def show_webview2_runtime_error():
    message = (
        "NeuroFlex Dashboard requiere Microsoft Edge WebView2 Runtime.\n\n"
        "Descarguelo desde:\n"
        "https://developer.microsoft.com/microsoft-edge/webview2/"
    )
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, message, "NeuroFlex Dashboard", 0x10)
    else:
        print(message, file=sys.stderr)


def is_server_port_available() -> bool:
    """Return whether the local Django server port can be bound."""
    port = int(get_http_port())
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
            server_socket.bind(("0.0.0.0", port))
    except OSError:
        return False
    return True


def show_server_port_error():
    message = (
        f"NeuroFlex Dashboard no puede iniciarse porque el puerto {get_http_port()} ya esta en uso.\n\n"
        "Cierre la otra aplicacion que usa ese puerto e intente nuevamente."
    )
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(None, message, "NeuroFlex Dashboard", 0x10)
    else:
        print(message, file=sys.stderr)


def wait_for_server() -> bool:
    deadline = time.monotonic() + SERVER_STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            response = requests.get(SERVER_URL, timeout=1)
            if response.status_code < 500:
                if NEUROFLEX_APP_MARKER not in response.text:
                    print(
                        "[launcher] El servicio en 127.0.0.1:"
                        f"{get_http_port()} no es NeuroFlex Dashboard.",
                        file=sys.stderr,
                    )
                    return False
                return True
        except requests.RequestException:
            pass
        time.sleep(SERVER_POLL_INTERVAL_SECONDS)
    return False


def run_django_server(stop_event: threading.Event, call_command):
    """Run Django in-process until shutdown begins or the process exits."""
    port = get_http_port()
    while not stop_event.is_set():
        call_command(
            "runserver",
            f"0.0.0.0:{port}",
            use_reloader=False,
            insecure=True,
        )
        break


def on_window_close(stop_event: threading.Event):
    stop_event.set()


def main():
    try:
        redirect_stdout_if_frozen()

        if is_already_running():
            print("[launcher] NeuroFlex ya esta en ejecucion.")
            activate_existing_window()
            return

        setup_environment()

        ensure_secret_key(get_data_dir())

        validate_critical_env()

        import django
        django.setup()

        from django.core.management import call_command

        call_command("migrate", verbosity=0)

        if not is_webview2_runtime_available():
            show_webview2_runtime_error()
            return

        if not is_server_port_available():
            show_server_port_error()
            return

        stop_event = threading.Event()
        server_thread = threading.Thread(
            target=run_django_server,
            args=(stop_event, call_command),
            daemon=True,
        )
        server_thread.start()

        if not wait_for_server():
            stop_event.set()
            raise RuntimeError("El servidor Django no inicio dentro del tiempo esperado.")

        window = webview.create_window(
            "NeuroFlex Dashboard",
            SERVER_URL,
            maximized=True,
            resizable=True,
            menu=[],
        )
        window.events.closing += lambda *_: on_window_close(stop_event)
        webview.settings["ALLOW_DOWNLOADS"] = True
        webview.start()
        sys.exit(0)
    except Exception:
        import traceback

        log_path = (
            Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
            / "NeuroFlex"
            / "launcher_error.log"
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(traceback.format_exc(), encoding="utf-8")
        print(traceback.format_exc())
        print(f"Log escrito en: {log_path}")
        if sys.stdin and sys.stdin.isatty():
            try:
                input("Presiona Enter para cerrar...")
            except EOFError:
                pass
        raise


if __name__ == "__main__":
    main()
