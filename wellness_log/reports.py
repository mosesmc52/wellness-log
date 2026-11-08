"""Weekly/monthly report calculation, rendering, and command-line entry point."""

import argparse
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import SessionLocal, init_db
from .email_service import send_report
from .habits import HABITS
from .main import today_local
from .models import HabitLog, ReportDelivery

logger = logging.getLogger(__name__)
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
template_environment = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html"])
)


@dataclass(frozen=True)
class HabitStats:
    key: str
    name: str
    yes: int
    no: int
    unanswered: int
    completion_percentage: float
    previous_percentage: float | None = None

    @property
    def change(self) -> float | None:
        if self.previous_percentage is None:
            return None
        return self.completion_percentage - self.previous_percentage


@dataclass(frozen=True)
class Report:
    report_type: str
    period_start: date
    period_end: date
    habits: tuple[HabitStats, ...]
    overall_percentage: float
    previous_overall_percentage: float | None
    most_consistent: tuple[str, ...] = ()
    least_consistent: tuple[str, ...] = ()

    @property
    def days(self) -> int:
        return (self.period_end - self.period_start).days + 1

    @property
    def overall_change(self) -> float | None:
        if self.previous_overall_percentage is None:
            return None
        return self.overall_percentage - self.previous_overall_percentage


def _period_values(
    session: Session, period_start: date, period_end: date
) -> tuple[dict[str, tuple[int, int]], bool]:
    logs = session.scalars(
        select(HabitLog).where(HabitLog.date >= period_start, HabitLog.date <= period_end)
    ).all()
    counts = {habit.key: [0, 0] for habit in HABITS}
    for log in logs:
        if log.habit_key not in counts:
            continue
        if log.completed is True:
            counts[log.habit_key][0] += 1
        elif log.completed is False:
            counts[log.habit_key][1] += 1
    return {key: (value[0], value[1]) for key, value in counts.items()}, bool(logs)


def calculate_report(
    session: Session,
    report_type: str,
    period_start: date,
    period_end: date,
    previous_start: date | None = None,
    previous_end: date | None = None,
) -> Report:
    if period_end < period_start:
        raise ValueError("period_end must not be before period_start")
    days = (period_end - period_start).days + 1
    current, _ = _period_values(session, period_start, period_end)
    previous: dict[str, tuple[int, int]] | None = None
    previous_days = 0
    if previous_start and previous_end:
        candidate, has_previous_logs = _period_values(session, previous_start, previous_end)
        if has_previous_logs:
            previous = candidate
            previous_days = (previous_end - previous_start).days + 1

    stats: list[HabitStats] = []
    total_yes = 0
    previous_total_yes = 0
    for habit in HABITS:
        yes, no = current[habit.key]
        total_yes += yes
        previous_percentage = None
        if previous is not None:
            previous_yes, _ = previous[habit.key]
            previous_total_yes += previous_yes
            previous_percentage = previous_yes / previous_days * 100
        stats.append(
            HabitStats(
                key=habit.key,
                name=habit.name,
                yes=yes,
                no=no,
                unanswered=max(0, days - yes - no),
                completion_percentage=yes / days * 100,
                previous_percentage=previous_percentage,
            )
        )

    overall = total_yes / (days * len(HABITS)) * 100
    previous_overall = (
        previous_total_yes / (previous_days * len(HABITS)) * 100
        if previous is not None
        else None
    )
    most: tuple[str, ...] = ()
    least: tuple[str, ...] = ()
    if report_type == "monthly" and stats:
        high = max(item.completion_percentage for item in stats)
        low = min(item.completion_percentage for item in stats)
        most = tuple(item.name for item in stats if item.completion_percentage == high)
        least = tuple(item.name for item in stats if item.completion_percentage == low)
    return Report(
        report_type=report_type,
        period_start=period_start,
        period_end=period_end,
        habits=tuple(stats),
        overall_percentage=overall,
        previous_overall_percentage=previous_overall,
        most_consistent=most,
        least_consistent=least,
    )


def weekly_period(reference_date: date) -> tuple[date, date, date, date]:
    start = reference_date - timedelta(days=reference_date.weekday())
    end = start + timedelta(days=6)
    return start, end, start - timedelta(days=7), end - timedelta(days=7)


def monthly_period(reference_date: date) -> tuple[date, date, date, date]:
    current_month_start = reference_date.replace(day=1)
    end = current_month_start - timedelta(days=1)
    start = end.replace(day=1)
    previous_end = start - timedelta(days=1)
    previous_start = previous_end.replace(day=1)
    return start, end, previous_start, previous_end


def render_report(report: Report) -> tuple[str, str, str]:
    label = report.report_type.capitalize()
    subject = f"wellness-log {label} Report: {report.period_start} to {report.period_end}"
    html = template_environment.get_template("email_report.html").render(report=report, subject=subject)
    lines = [
        subject,
        "",
        f"Overall completion: {report.overall_percentage:.1f}%",
    ]
    if report.overall_change is not None:
        lines.append(f"Change from previous period: {report.overall_change:+.1f} percentage points")
    lines.extend(["", "Habits:"])
    for item in report.habits:
        comparison = f", change {item.change:+.1f} points" if item.change is not None else ""
        lines.append(
            f"- {item.name} ({item.key}): Yes {item.yes}, No {item.no}, "
            f"Unanswered {item.unanswered}, completion {item.completion_percentage:.1f}%{comparison}"
        )
    if report.report_type == "monthly":
        lines.extend(
            [
                "",
                f"Most consistent: {', '.join(report.most_consistent)}",
                f"Least consistent: {', '.join(report.least_consistent)}",
            ]
        )
    return subject, "\n".join(lines) + "\n", html


def build_report(session: Session, report_type: str, reference_date: date) -> Report:
    if report_type == "weekly":
        start, end, previous_start, previous_end = weekly_period(reference_date)
    elif report_type == "monthly":
        start, end, previous_start, previous_end = monthly_period(reference_date)
    else:
        raise ValueError(f"Unsupported report type: {report_type}")
    return calculate_report(
        session, report_type, start, end, previous_start, previous_end
    )


def deliver_report(session: Session, report: Report, dry_run: bool = False) -> str:
    subject, text_body, html_body = render_report(report)
    if dry_run:
        print(text_body, end="")
        return "dry-run"

    delivery = ReportDelivery(
        report_type=report.report_type,
        period_start=report.period_start,
        period_end=report.period_end,
        status="pending",
    )
    session.add(delivery)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        logger.info("Report already delivered or in progress: %s", subject)
        return "duplicate"

    try:
        send_report(subject, text_body, html_body)
    except Exception:
        session.delete(delivery)
        session.commit()
        logger.exception("Email delivery failed; claim removed so it can be retried")
        raise
    delivery.status = "sent"
    delivery.sent_at = datetime.now(timezone.utc)
    session.commit()
    logger.info("Report delivered: %s", subject)
    return "sent"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate wellness-log reports")
    parser.add_argument("report_type", choices=("weekly", "monthly"))
    parser.add_argument("--dry-run", action="store_true", help="render to stdout without sending")
    parser.add_argument("--date", type=date.fromisoformat, help="override today's local date")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    init_db()
    with SessionLocal() as session:
        report = build_report(session, args.report_type, args.date or today_local())
        result = deliver_report(session, report, dry_run=args.dry_run)
    logger.info("%s report result: %s", args.report_type, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
