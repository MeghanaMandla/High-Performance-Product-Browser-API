"""
cursor.py — Helpers for keyset pagination cursors.

A "cursor" tells the API where to continue fetching from.
We store the last row's (created_at, id) inside a cursor string.

We use base64 encoding so the cursor is safe to put in a URL.
"""

import base64
import json


def encode(created_at, row_id: int) -> str:
    """
    Turn a (created_at, id) pair into a short cursor string.

    Example:
        encode("2024-01-15", 42)  →  "eyJjcmVhdGVkX..."
    """
    # Step 1: put the values into a dictionary
    data = {
        "created_at": str(created_at),
        "id": row_id
    }

    # Step 2: convert the dictionary to a JSON string
    json_string = json.dumps(data)

    # Step 3: encode the JSON string to bytes, then to base64
    # base64 is a way to represent any data as safe URL characters
    cursor_bytes  = json_string.encode()          # str  → bytes
    base64_bytes  = base64.urlsafe_b64encode(cursor_bytes)  # bytes → base64
    cursor_string = base64_bytes.decode()         # bytes → str

    # Remove trailing "=" padding characters (not needed in URLs)
    cursor_string = cursor_string.rstrip("=")

    return cursor_string


def decode(cursor_string: str) -> tuple:
    """
    Turn a cursor string back into (created_at, id).

    Example:
        decode("eyJjcmVhdGVkX...")  →  ("2024-01-15", 42)
    """
    # Step 1: add back the "=" padding that we removed in encode()
    # base64 strings must have a length that is a multiple of 4
    missing_padding = 4 - len(cursor_string) % 4
    if missing_padding != 4:
        cursor_string += "=" * missing_padding

    # Step 2: decode base64 back to bytes, then to a JSON string
    cursor_bytes = base64.urlsafe_b64decode(cursor_string)
    json_string  = cursor_bytes.decode()

    # Step 3: parse the JSON string back into a dictionary
    data = json.loads(json_string)

    created_at = data["created_at"]
    row_id     = int(data["id"])

    return created_at, row_id
