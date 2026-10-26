"""Force UTF-8 on stdout/stderr before a script prints anything.

LUNAPOLE's output is full of degree signs, ``+-``, multiplication signs and
arrows (``° ± × → − ≈``). On Windows the default stdout encoding is the ANSI
code page (cp1252 on this machine), so the first such print raises
``UnicodeEncodeError`` -- and because these tend to be summary lines, the
script dies *after* doing all of its work and exits non-zero. ``crop_sites.py``
did exactly that: six crops written, then a crash on the final arrow.

Every entry point imports this module and calls :func:`utf8_streams` before its
first print. The call is a no-op when the streams are already UTF-8.
"""
from __future__ import annotations

import sys

__all__ = ["utf8_streams"]


def utf8_streams() -> bool:
    """Reconfigure stdout/stderr to UTF-8. Returns True if both are usable."""
    ok = True
    for stream in (sys.stdout, sys.stderr):
        if stream is None:                       # pythonw.exe, detached pipes
            ok = False
            continue
        try:
            enc = (stream.encoding or "").lower().replace("-", "")
            if enc != "utf8":
                stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError, OSError):
            # Already replaced by a wrapper, or not a TextIOWrapper: the
            # script can still run, it just may not print Unicode safely.
            ok = False
    return ok
