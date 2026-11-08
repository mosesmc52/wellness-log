from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from SES import AmazonSES
from wellness_log.email_service import SESConfig, send_report
from wellness_log.habits import HABITS
from wellness_log.models import HabitLog, ReportDelivery
from wellness_log.reports import (
    build_report,
    calculate_report,
    deliver_report,
    monthly_period,
    render_report,
    weekly_period,
)


def add_log(session, day, key, completed):
    session.add(HabitLog(date=day, habit_key=key, completed=completed))


def test_weekly_calculation_counts_no_and_unanswered(session):
    start = date(2025, 1, 6)
    add_log(session, start, "walked", True)
    add_log(session, start + timedelta(days=1), "walked", False)
    for offset in range(7):
        add_log(session, start + timedelta(days=offset), "morning_brush", True)
    session.commit()

    report = calculate_report(session, "weekly", start, start + timedelta(days=6))
    walked = next(item for item in report.habits if item.key == "walked")
    assert (walked.yes, walked.no, walked.unanswered) == (1, 1, 5)
    assert walked.completion_percentage == pytest.approx(100 / 7)
    assert report.overall_percentage == pytest.approx(8 / 49 * 100)


def test_previous_period_comparison_appears_when_data_exists(session):
    start = date(2025, 1, 13)
    previous_start = start - timedelta(days=7)
    add_log(session, previous_start, "walked", True)
    add_log(session, start, "walked", True)
    add_log(session, start + timedelta(days=1), "walked", True)
    session.commit()
    report = calculate_report(
        session,
        "weekly",
        start,
        start + timedelta(days=6),
        previous_start,
        previous_start + timedelta(days=6),
    )
    walked = next(item for item in report.habits if item.key == "walked")
    assert walked.change == pytest.approx(100 / 7)
    assert report.overall_change is not None


def test_calendar_boundaries():
    assert weekly_period(date(2025, 1, 12))[:2] == (date(2025, 1, 6), date(2025, 1, 12))
    assert monthly_period(date(2024, 3, 1)) == (
        date(2024, 2, 1),
        date(2024, 2, 29),
        date(2024, 1, 1),
        date(2024, 1, 31),
    )


def test_monthly_consistency_and_rendering(session):
    for offset in range(31):
        add_log(session, date(2025, 1, 1) + timedelta(days=offset), HABITS[0].key, True)
    session.commit()
    report = build_report(session, "monthly", date(2025, 2, 1))
    assert HABITS[0].name in report.most_consistent
    subject, text, html = render_report(report)
    assert "Monthly Report" in subject
    assert "Most consistent" in text
    assert "Unanswered" in html


def test_duplicate_delivery_is_prevented(session, monkeypatch):
    report = build_report(session, "weekly", date(2025, 1, 12))
    sent = []
    monkeypatch.setattr("wellness_log.reports.send_report", lambda *args: sent.append(args))
    assert deliver_report(session, report) == "sent"
    assert deliver_report(session, report) == "duplicate"
    assert len(sent) == 1
    assert session.scalar(select(func.count()).select_from(ReportDelivery)) == 1


def test_failed_delivery_can_be_retried(session, monkeypatch):
    report = build_report(session, "weekly", date(2025, 1, 12))

    def fail(*_args):
        raise OSError("SES unavailable")

    monkeypatch.setattr("wellness_log.reports.send_report", fail)
    with pytest.raises(OSError):
        deliver_report(session, report)
    assert session.scalar(select(func.count()).select_from(ReportDelivery)) == 0
    monkeypatch.setattr("wellness_log.reports.send_report", lambda *_args: None)
    assert deliver_report(session, report) == "sent"


def test_ses_message_generation_requires_no_live_service():
    class FakeSESClient:
        def __init__(self):
            self.request = None

        def send_email(self, **kwargs):
            self.request = kwargs
            return {"MessageId": "test-message"}

    fake_client = FakeSESClient()
    service = AmazonSES(
        "us-east-1", None, None, "from@example.test", client=fake_client
    )
    response = service.send_email(
        ("one@example.test", "two@example.test"),
        "Subject",
        "plain",
        "<p>html</p>",
    )
    assert response == {"MessageId": "test-message"}
    assert fake_client.request["Destination"]["ToAddresses"] == [
        "one@example.test",
        "two@example.test",
    ]
    assert fake_client.request["Message"]["Body"]["Text"]["Data"] == "plain"
    assert fake_client.request["Message"]["Body"]["Html"]["Data"] == "<p>html</p>"


def test_send_report_uses_ses_configuration(monkeypatch):
    calls = []

    class FakeAmazonSES:
        def __init__(self, **kwargs):
            calls.append(("init", kwargs))

        def send_email(self, *args):
            calls.append(("send", args))

    monkeypatch.setenv("AWS_SES_REGION_NAME", "us-west-2")
    monkeypatch.setenv("FROM_ADDRESS", "from@example.test")
    monkeypatch.setenv(
        "TO_ADDRESSES", "one@example.test, two@example.test, ,three@example.test"
    )
    monkeypatch.delenv("AWS_SES_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SES_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.setattr("wellness_log.email_service.AmazonSES", FakeAmazonSES)

    send_report("Subject", "plain", "<p>html</p>")

    assert calls[0][1]["region"] == "us-west-2"
    assert calls[0][1]["access_key"] is None
    assert calls[1] == (
        "send",
        (
            ("one@example.test", "two@example.test", "three@example.test"),
            "Subject",
            "plain",
            "<p>html</p>",
        ),
    )


def test_ses_config_rejects_partial_static_credentials(monkeypatch):
    monkeypatch.setenv("FROM_ADDRESS", "from@example.test")
    monkeypatch.setenv("TO_ADDRESSES", "to@example.test")
    monkeypatch.setenv("AWS_SES_ACCESS_KEY_ID", "only-one-half")
    monkeypatch.delenv("AWS_SES_SECRET_ACCESS_KEY", raising=False)
    with pytest.raises(RuntimeError, match="must either both be set"):
        SESConfig.from_env()
