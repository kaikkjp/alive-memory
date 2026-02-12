import sys
import types


def ensure_aiohttp_stub() -> None:
    """Install a minimal aiohttp stub for test environments without aiohttp."""
    if "aiohttp" in sys.modules:
        return

    class _ClientError(Exception):
        pass

    class _ClientTimeout:
        def __init__(self, total=None):
            self.total = total

    class _ClientSession:
        def __init__(self, timeout=None):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def post(self, *args, **kwargs):
            _ = args
            _ = kwargs
            raise RuntimeError("aiohttp stub: ClientSession.post must be mocked in tests")

    sys.modules["aiohttp"] = types.SimpleNamespace(
        ClientError=_ClientError,
        ClientTimeout=_ClientTimeout,
        ClientSession=_ClientSession,
    )
