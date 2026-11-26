"""
Import `hid` (python-hid) even when the native hidapi library is not on the
default macOS search path.

python-hid loads the library by bare name (``libhidapi.dylib``). macOS only
looks for bare names in a few fixed places (/usr/local/lib, /usr/lib) plus the
search path (LC_RPATH) baked into the running Python. Homebrew on Apple Silicon
installs into /opt/homebrew/lib, which is in neither, so with Apple's or
python.org's Python a plain ``import hid`` fails even after
``brew install hidapi``. (A pyenv or Homebrew Python often has /opt/homebrew/lib
in its own search path, which is why it works on some machines and not others.)

Setting DYLD_FALLBACK_LIBRARY_PATH from inside Python is too late -- dyld reads
it at process start -- and loading the library first under its full path does
not help either, because python-hid asks for it again by bare name. So when the
plain import fails on macOS, retry it with ``ctypes.cdll.LoadLibrary`` briefly
redirected from the bare name to a full path in the usual package-manager
prefixes.
"""
import ctypes
import os
import sys

_BARE_NAME = "libhidapi.dylib"


def _macos_candidates():
    prefixes = []
    if os.environ.get("HOMEBREW_PREFIX"):
        prefixes.append(os.environ["HOMEBREW_PREFIX"])
    prefixes += ["/opt/homebrew", "/usr/local", "/opt/local"]   # brew arm64, brew x86, MacPorts
    seen = set()
    for prefix in prefixes:
        path = os.path.join(prefix, "lib", _BARE_NAME)
        if path not in seen and os.path.exists(path):
            seen.add(path)
            yield path


def import_hid():
    """Return the `hid` module, finding Homebrew/MacPorts hidapi on macOS."""
    try:
        import hid
        return hid
    except ImportError as first_error:
        if sys.platform != "darwin":
            raise
        error = first_error

    original = ctypes.cdll.LoadLibrary
    for path in _macos_candidates():
        def load(name, _path=path):
            return original(_path if name == _BARE_NAME else name)
        ctypes.cdll.LoadLibrary = load
        try:
            import hid
            return hid
        except ImportError as exc:   # a failed import leaves nothing in sys.modules
            error = exc
        finally:
            ctypes.cdll.LoadLibrary = original

    raise ImportError(
        "Could not load the native hidapi library. Install it with "
        "`brew install hidapi` (or `port install hidapi`); it was looked for in "
        "/opt/homebrew/lib, /usr/local/lib and /opt/local/lib.\n"
        f"Original error: {error}"
    ) from error
