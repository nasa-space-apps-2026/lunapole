"""LUNAPOLE build pipeline (P2 ephemeris, P3 horizon, P4 maps, P6 bake).

This ``__init__.py`` is load-bearing, not decoration. Without it ``build`` is
a namespace package, and Python prefers a *regular* package found anywhere on
``sys.path`` -- including the unrelated ``build`` distribution on PyPI
(the PEP 517 frontend), which is installed in many environments. The symptom
is confusing: ``from build.lunapole import frames`` raises ``ModuleNotFoundError:
No module named 'build.lunapole'`` even though the files sit right there.
"""
