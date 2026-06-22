import base64
import json


def encode(created_at, row_id: int) -> str:
    payload = json.dumps({'created_at': str(created_at), 'id': row_id})
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip('=')


def decode(cursor: str) -> tuple:
    pad = 4 - len(cursor) % 4
    if pad != 4:
        cursor += '=' * pad
    data = json.loads(base64.urlsafe_b64decode(cursor))
    return data['created_at'], int(data['id'])
