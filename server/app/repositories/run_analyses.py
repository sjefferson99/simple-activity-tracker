from typing import Protocol

from sqlalchemy.orm import Session

from app.models.run_analysis import RunAnalysis


class RunAnalysisRepository(Protocol):
    def get_by_run_id(self, run_id: str) -> RunAnalysis | None: ...
    def add(self, analysis: RunAnalysis) -> None: ...
    def delete(self, analysis: RunAnalysis) -> None: ...


class SqlAlchemyRunAnalysisRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_run_id(self, run_id: str) -> RunAnalysis | None:
        return self._session.get(RunAnalysis, run_id)

    def add(self, analysis: RunAnalysis) -> None:
        self._session.add(analysis)

    def delete(self, analysis: RunAnalysis) -> None:
        self._session.delete(analysis)
