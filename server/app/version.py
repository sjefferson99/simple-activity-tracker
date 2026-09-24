"""The release version this build was made from — see docs/VERSIONING.md §1.

CI bakes it into the image as ``SAT_BUILD_VERSION`` (``container.yml`` passes
the ``APP_VERSION`` build arg): ``1.3.0`` for a ``v1.3.0`` tag build,
``1.3.0+4.gabc1234`` for a ``main`` build four commits past that tag. A local
build without the arg, and the test suite, report ``dev``. It is for display
only — compatibility decisions use the API level in ``app/api_compat.py``,
never this string.
"""

import os

APP_VERSION = os.environ.get("SAT_BUILD_VERSION", "").strip() or "dev"
