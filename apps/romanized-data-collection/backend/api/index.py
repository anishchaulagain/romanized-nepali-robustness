# Vercel Python entry point: every request is rewritten to this function (see vercel.json).
import sys
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app as fastapi_app  # noqa: E402


class RestoreOriginalPath:
    """vercel.json rewrites every request to /api/index?__path=<original path>, and the function then sees the
    rewritten path. Put the original path back before FastAPI routes the request."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope['type'] in ('http', 'websocket'):
            query = parse_qsl(scope.get('query_string', b'').decode('latin-1'), keep_blank_values=True)
            original = next((v for k, v in query if k == '__path'), None)
            if original is not None:
                path = '/' + unquote(original).lstrip('/')
                rest = urlencode([(k, v) for k, v in query if k != '__path'])
                scope = {**scope, 'path': path, 'raw_path': path.encode(), 'query_string': rest.encode('latin-1')}
        await self.inner(scope, receive, send)


app = RestoreOriginalPath(fastapi_app)
