"""Decode claims out of a Cognito JWT without verifying its signature.

Safe here because the token arrives directly from Cognito over TLS during
login and is only read back from the server-side session - it is never
accepted as untrusted input from the client.
"""

from __future__ import annotations

import base64
import json


def decode_jwt_claims(token):
    """Return the claims dict encoded in a JWT's payload segment.

    Returns an empty dict if the token is malformed.
    """
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        return json.loads(base64.urlsafe_b64decode(payload_b64))
    except (IndexError, ValueError, TypeError):
        return {}
