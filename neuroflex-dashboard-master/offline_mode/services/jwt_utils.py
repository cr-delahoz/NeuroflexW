import base64
import json
import math
import sys
import time


def _decode_payload(token: str) -> dict:
    """Decodifica el payload de un JWT sin verificar la firma."""
    if not isinstance(token, str):
        return {}
    parts = token.split(".")
    if len(parts) != 3:
        return {}
    payload = parts[1]
    # add padding
    payload += "=" * (-len(payload) % 4)
    try:
        decoded = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
    except Exception:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def is_id_token_valid(token: str) -> bool:
    """True si el token tiene ``exp`` vigente (con 30s de margen).

    No verifica la firma: el token proviene de la propia sesión del
    usuario, autenticada previamente contra Cognito.
    """
    payload = _decode_payload(token)
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)):
        return False
    try:
        if not math.isfinite(exp):  # NaN/Infinity: json.loads los acepta
            return False
        if exp > sys.maxsize:  # exp absurdo (p. ej. 1e308): basura, no vigente
            return False
        return int(exp) > time.time() + 30  # 30s de margen
    except (OverflowError, ValueError):
        # math.isfinite(int enorme) y conversiones extremas desbordan
        return False
