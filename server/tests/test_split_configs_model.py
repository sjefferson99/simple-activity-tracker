"""Model/repository/validation tests for saved split configs (issue #126),
written before the API routes exist (see docs/SPLIT-CONFIGS-PLAN.md §6 item
1) — exercises SplitConfig, SqlAlchemySplitConfigRepository and SplitPlanIn
directly against the real DB via the app_client fixture's migrated schema,
same pattern as test_tags.py's direct-repository setup helper.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.api.v1.schemas import SplitPlanIn
from app.db import get_session_factory
from app.models.split_config import SplitConfig
from app.repositories.split_configs import SqlAlchemySplitConfigRepository


def _make_user(email: str = "configs@example.com") -> str:
    from app.auth.passwords import hash_password
    from app.models.user import User
    from app.repositories.users import SqlAlchemyUserRepository

    with get_session_factory()() as session:
        now = datetime.now(UTC)
        user = User(
            email=email,
            password_hash=hash_password("a-password-123"),
            display_name="Configs User",
            is_admin=False,
            sessions_invalidated_at=now,
            created_at=now,
        )
        SqlAlchemyUserRepository(session).add(user)
        session.commit()
        return user.id


def _rolling_plan(**overrides: object) -> dict[str, object]:
    plan = {
        "split_type": "distance_km",
        "split_value": 1,
        "rolling_target_mps": 2.5,
        "custom_splits": [],
        "targets_as": "pace",
    }
    plan.update(overrides)
    return plan


class TestSplitConfigModelAndRepository:
    def test_create_list_get_delete_round_trip(self, app_client):
        user_id = _make_user()
        with get_session_factory()() as session:
            repo = SqlAlchemySplitConfigRepository(session)
            now = datetime.now(UTC)
            config = SplitConfig(
                user_id=user_id,
                name="5k tempo",
                plan=_rolling_plan(),
                created_at=now,
                updated_at=now,
            )
            repo.add(config)
            session.commit()
            config_id = config.id

        with get_session_factory()() as session:
            repo = SqlAlchemySplitConfigRepository(session)
            listed = repo.list_for_user(user_id)
            assert [c.name for c in listed] == ["5k tempo"]

            fetched = repo.get_for_user(user_id, config_id)
            assert fetched is not None
            assert fetched.plan["rolling_target_mps"] == 2.5

            by_name = repo.get_by_name_for_user(user_id, "5k tempo")
            assert by_name is not None
            assert by_name.id == config_id

            assert repo.get_by_name_for_user(user_id, "nonexistent") is None

            repo.delete(fetched)
            session.commit()

        with get_session_factory()() as session:
            repo = SqlAlchemySplitConfigRepository(session)
            assert repo.list_for_user(user_id) == []

    def test_list_for_user_sorted_by_name_and_scoped_per_user(self, app_client):
        user_a = _make_user("a@example.com")
        user_b = _make_user("b@example.com")
        with get_session_factory()() as session:
            repo = SqlAlchemySplitConfigRepository(session)
            now = datetime.now(UTC)
            for name in ["Zebra", "Alpha", "Mid"]:
                repo.add(
                    SplitConfig(
                        user_id=user_a,
                        name=name,
                        plan=_rolling_plan(),
                        created_at=now,
                        updated_at=now,
                    )
                )
            repo.add(
                SplitConfig(
                    user_id=user_b,
                    name="Belongs to b",
                    plan=_rolling_plan(),
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()

        with get_session_factory()() as session:
            repo = SqlAlchemySplitConfigRepository(session)
            names = [c.name for c in repo.list_for_user(user_a)]
            assert names == ["Alpha", "Mid", "Zebra"]
            assert [c.name for c in repo.list_for_user(user_b)] == ["Belongs to b"]

    def test_name_unique_per_user_but_not_across_users(self, app_client):
        user_a = _make_user("unique-a@example.com")
        user_b = _make_user("unique-b@example.com")
        now = datetime.now(UTC)

        with get_session_factory()() as session:
            repo = SqlAlchemySplitConfigRepository(session)
            repo.add(
                SplitConfig(
                    user_id=user_a,
                    name="Same name",
                    plan=_rolling_plan(),
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()

        # Same name, different user: allowed.
        with get_session_factory()() as session:
            repo = SqlAlchemySplitConfigRepository(session)
            repo.add(
                SplitConfig(
                    user_id=user_b,
                    name="Same name",
                    plan=_rolling_plan(),
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()

        # Same name, same user: rejected by the DB unique constraint.
        with get_session_factory()() as session:
            from sqlalchemy.exc import IntegrityError

            repo = SqlAlchemySplitConfigRepository(session)
            repo.add(
                SplitConfig(
                    user_id=user_a,
                    name="Same name",
                    plan=_rolling_plan(),
                    created_at=now,
                    updated_at=now,
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()


class TestSplitPlanInValidation:
    def test_valid_rolling_plan_with_target(self):
        plan = SplitPlanIn.model_validate(_rolling_plan())
        assert plan.rolling_target_mps == 2.5
        assert plan.custom_splits == []

    def test_valid_rolling_plan_without_target(self):
        plan = SplitPlanIn.model_validate(_rolling_plan(rolling_target_mps=None))
        assert plan.rolling_target_mps is None

    def test_valid_custom_plan(self):
        plan = SplitPlanIn.model_validate(
            _rolling_plan(
                rolling_target_mps=None,
                custom_splits=[[400.0, 3.0], [1000.0, None], [200.0, 4.5]],
            )
        )
        assert plan.custom_splits == [(400.0, 3.0), (1000.0, None), (200.0, 4.5)]

    @pytest.mark.parametrize("split_value", [0, -1])
    def test_rejects_non_positive_split_value(self, split_value):
        with pytest.raises(ValidationError):
            SplitPlanIn.model_validate(_rolling_plan(split_value=split_value))

    @pytest.mark.parametrize("target", [0, -1.0])
    def test_rejects_non_positive_rolling_target(self, target):
        with pytest.raises(ValidationError):
            SplitPlanIn.model_validate(_rolling_plan(rolling_target_mps=target))

    def test_rejects_non_positive_custom_split_size(self):
        with pytest.raises(ValidationError):
            SplitPlanIn.model_validate(
                _rolling_plan(rolling_target_mps=None, custom_splits=[[0.0, None]])
            )

    def test_rejects_non_positive_custom_split_target(self):
        with pytest.raises(ValidationError):
            SplitPlanIn.model_validate(
                _rolling_plan(rolling_target_mps=None, custom_splits=[[400.0, -1.0]])
            )

    def test_rejects_non_finite_values(self):
        with pytest.raises(ValidationError):
            SplitPlanIn.model_validate(_rolling_plan(rolling_target_mps=float("inf")))
        with pytest.raises(ValidationError):
            SplitPlanIn.model_validate(
                _rolling_plan(rolling_target_mps=None, custom_splits=[[float("nan"), None]])
            )

    def test_rejects_more_than_max_custom_splits(self):
        too_many = [[100.0, None] for _ in range(51)]
        with pytest.raises(ValidationError):
            SplitPlanIn.model_validate(
                _rolling_plan(rolling_target_mps=None, custom_splits=too_many)
            )

    def test_accepts_exactly_max_custom_splits(self):
        exactly_max = [[100.0, None] for _ in range(50)]
        plan = SplitPlanIn.model_validate(
            _rolling_plan(rolling_target_mps=None, custom_splits=exactly_max)
        )
        assert len(plan.custom_splits) == 50

    def test_rejects_rolling_target_alongside_custom_splits(self):
        # Mirrors mobile's SplitPlan: the two are mutually exclusive.
        with pytest.raises(ValidationError):
            SplitPlanIn.model_validate(
                _rolling_plan(rolling_target_mps=2.5, custom_splits=[[400.0, None]])
            )

    def test_rejects_unknown_split_type(self):
        with pytest.raises(ValidationError):
            SplitPlanIn.model_validate(_rolling_plan(split_type="distance_furlongs"))

    def test_rejects_unknown_fields(self):
        with pytest.raises(ValidationError):
            SplitPlanIn.model_validate(_rolling_plan(unexpected_field=True))

    def test_defaults_targets_as_to_pace(self):
        payload = _rolling_plan(rolling_target_mps=None)
        del payload["targets_as"]
        plan = SplitPlanIn.model_validate(payload)
        assert plan.targets_as == "pace"
