"""App <-> server compatibility levels — see docs/VERSIONING.md §2.

Bump ``API_LEVEL`` in the same PR as any change to ``openapi.json``'s paths or
components (CI enforces this), and add a row to the level table in
docs/VERSIONING.md. The mobile app's ``kAppApiLevel`` must match it (a mobile
test reads this file).

Bump ``MIN_APP_API_LEVEL`` only when the server stops supporting something an
older app sends or reads — CI requires it for any change oasdiff classes as
breaking. Prefer making the change non-breaking instead.
"""

API_LEVEL = 1
MIN_APP_API_LEVEL = 0
