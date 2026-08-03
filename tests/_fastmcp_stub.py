"""Minimal stand-in for the `fastmcp` package, used only so tests can run
without the real dependency installed (fastmcp requires Python >=3.10; this
repo's test suite should also run on older Python for local development).

If the real `fastmcp` package is importable, it is used instead - this stub
is only injected into sys.modules when the import would otherwise fail.
"""
import sys
import types


def ensure_fastmcp_available():
    try:
        import fastmcp  # noqa: F401

        return
    except ImportError:
        pass

    module = types.ModuleType("fastmcp")

    class FastMCP:
        def __init__(self, *args, **kwargs):
            self.tools = {}

        def tool(self, fn=None, **kwargs):
            if fn is not None and callable(fn):
                self.tools[fn.__name__] = fn
                return fn

            def decorator(f):
                self.tools[f.__name__] = f
                return f

            return decorator

        def run(self, *args, **kwargs):
            pass

    module.FastMCP = FastMCP
    sys.modules["fastmcp"] = module
