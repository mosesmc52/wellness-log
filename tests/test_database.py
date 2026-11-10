from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from wellness_log.database import get_db
from wellness_log.habits import HABITS
from wellness_log.main import app
from wellness_log.models import HabitLog


def test_uniqueness_and_nullable_state(session):
    day = date(2025, 1, 10)
    session.add(HabitLog(date=day, habit_key="walked", completed=None))
    session.commit()
    stored = session.scalar(select(HabitLog))
    assert stored.completed is None

    session.add(HabitLog(date=day, habit_key="walked", completed=False))
    with pytest.raises(IntegrityError):
        session.commit()


def test_save_and_edit_current_day(test_engine, monkeypatch):
    factory = sessionmaker(bind=test_engine, expire_on_commit=False)

    def override_db():
        with factory() as database_session:
            yield database_session

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr("wellness_log.main.init_db", lambda: None)
    monkeypatch.setattr("wellness_log.main.today_local", lambda: date(2025, 1, 15))
    try:
        with TestClient(app) as client:
            response = client.post(
                "/save",
                data={
                    "walked": "no",
                    "morning_brush": "yes",
                },
                follow_redirects=False,
            )
            assert response.status_code == 303
            response = client.post(
                "/save",
                data={"walked": "yes"},
                follow_redirects=False,
            )
            assert response.status_code == 303

        with factory() as database_session:
            logs = database_session.scalars(
                select(HabitLog).where(HabitLog.date == date(2025, 1, 15))
            ).all()
            answers = {log.habit_key: log.completed for log in logs}
            assert len(logs) == 7
            assert answers["walked"] is True
            assert answers["morning_brush"] is False
            assert answers["evening_journal"] is False
    finally:
        app.dependency_overrides.clear()


def test_page_only_displays_current_date(test_engine, monkeypatch):
    factory = sessionmaker(bind=test_engine)

    def override_db():
        with factory() as database_session:
            yield database_session

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr("wellness_log.main.init_db", lambda: None)
    monkeypatch.setattr("wellness_log.main.today_local", lambda: date(2025, 1, 15))
    try:
        with TestClient(app) as client:
            response = client.get("/?date_value=2025-01-16")
            assert response.status_code == 200
            assert "<h1>Wellness Log</h1>" in response.text
            assert "DAILY CHECK-IN" in response.text
            assert "</strong><br><span>Wednesday, January 15, 2025</span>" in response.text
            assert "Wednesday, January 15, 2025" in response.text
            assert 'type="date"' not in response.text
            assert "2025-01-16" not in response.text
            assert 'id="set-all-toggle"' in response.text
            assert ">Set all to Yes</button>" in response.text
            assert ">Clear</button>" not in response.text
            assert 'id="walked-no" name="walked" value="no" checked' in response.text
    finally:
        app.dependency_overrides.clear()


def test_page_offers_set_all_to_no_when_every_habit_is_yes(test_engine, monkeypatch):
    factory = sessionmaker(bind=test_engine)
    day = date(2025, 1, 15)
    with factory() as database_session:
        database_session.add_all(
            HabitLog(date=day, habit_key=habit.key, completed=True)
            for habit in HABITS
        )
        database_session.commit()

    def override_db():
        with factory() as database_session:
            yield database_session

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr("wellness_log.main.init_db", lambda: None)
    monkeypatch.setattr("wellness_log.main.today_local", lambda: day)
    try:
        with TestClient(app) as client:
            response = client.get("/")
            assert response.status_code == 200
            assert ">Set all to No</button>" in response.text
    finally:
        app.dependency_overrides.clear()
