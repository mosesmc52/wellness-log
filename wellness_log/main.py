"""FastAPI web application."""

import os
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db, init_db
from .habits import HABITS, grouped_habits
from .models import HabitLog

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def app_timezone() -> ZoneInfo:
    name = os.getenv("APP_TIMEZONE", "America/New_York")
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise RuntimeError(f"Invalid APP_TIMEZONE: {name}") from exc


def today_local() -> date:
    from datetime import datetime

    return datetime.now(app_timezone()).date()


def format_display_date(value: date) -> str:
    return f"{value:%A}, {value:%B} {value.day}, {value.year}"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="wellness-log", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/")
def index(
    request: Request,
    saved: bool = False,
    db: Session = Depends(get_db),
):
    today = today_local()
    logs = db.scalars(select(HabitLog).where(HabitLog.date == today)).all()
    answers = {log.habit_key: log.completed for log in logs}
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "groups": grouped_habits(),
            "answers": answers,
            "all_yes": all(answers.get(habit.key) is True for habit in HABITS),
            "display_date": format_display_date(today),
            "saved": saved,
        },
    )


@app.post("/save")
async def save(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    log_date = today_local()
    existing = {
        log.habit_key: log
        for log in db.scalars(select(HabitLog).where(HabitLog.date == log_date)).all()
    }
    for habit in HABITS:
        raw_value = form.get(habit.key)
        if raw_value not in {None, "", "yes", "no"}:
            raise HTTPException(status_code=400, detail=f"Invalid value for {habit.key}")
        completed = raw_value == "yes"
        if habit.key in existing:
            existing[habit.key].completed = completed
        else:
            db.add(HabitLog(date=log_date, habit_key=habit.key, completed=completed))
    db.commit()
    return RedirectResponse(url="/?saved=true", status_code=status.HTTP_303_SEE_OTHER)
