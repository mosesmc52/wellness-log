"""The canonical habit catalogue used by the UI and reports."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Habit:
    key: str
    name: str
    group: str


HABITS: tuple[Habit, ...] = (
    Habit("morning_brush", "Brush Teeth", "Morning"),
    Habit("morning_exercise", "Morning Exercise", "Morning"),
    Habit("walked", "Walked Today", "Daytime"),
    Habit("evening_brush", "Brush Teeth", "Evening"),
    Habit("evening_journal", "Journal", "Evening"),
    Habit("evening_sleep_prep", "Prep for Sleep", "Evening"),
    Habit("slept_7_hours", "Slept at Least 7 Hours", "Sleep"),
)

HABIT_KEYS = frozenset(habit.key for habit in HABITS)
GROUPS: tuple[str, ...] = ("Morning", "Daytime", "Evening", "Sleep")


def grouped_habits() -> dict[str, tuple[Habit, ...]]:
    return {
        group: tuple(habit for habit in HABITS if habit.group == group)
        for group in GROUPS
    }
