from typing import Any, Protocol

from app.analysis.track import Track

AnalysisResult = dict[str, Any]


class Analyzer(Protocol):
    version: int

    def analyze(self, track: Track) -> AnalysisResult: ...
