from typing import Protocol

from sqlalchemy.orm import Session

from app.models.activity_analysis import ActivityAnalysis


class ActivityAnalysisRepository(Protocol):
    def get_by_activity_id(self, activity_id: str) -> ActivityAnalysis | None: ...
    def add(self, analysis: ActivityAnalysis) -> None: ...
    def delete(self, analysis: ActivityAnalysis) -> None: ...


class SqlAlchemyActivityAnalysisRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_activity_id(self, activity_id: str) -> ActivityAnalysis | None:
        return self._session.get(ActivityAnalysis, activity_id)

    def add(self, analysis: ActivityAnalysis) -> None:
        self._session.add(analysis)

    def delete(self, analysis: ActivityAnalysis) -> None:
        self._session.delete(analysis)
