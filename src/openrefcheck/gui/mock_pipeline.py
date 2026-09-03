"""Stage labels for the Upload screen's processing view.

The pipeline itself (real_pipeline.run_real_pipeline, driven by check_runner.py) has
no notion of named stages — it just reports (done, total) counts — so this list is
the single source of truth for the three stage labels shown alongside that progress.
"""

from __future__ import annotations

STAGES = ["Extracting references", "Querying OpenAlex/Crossref", "Scoring"]
