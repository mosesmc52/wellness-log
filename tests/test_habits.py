from wellness_log.habits import HABITS, grouped_habits


def test_all_seven_habits_are_in_the_expected_groups():
    groups = grouped_habits()
    assert len(HABITS) == 7
    assert [habit.key for habit in groups["Morning"]] == [
        "morning_brush",
        "morning_exercise",
    ]
    assert [habit.key for habit in groups["Daytime"]] == ["walked"]
    assert [habit.key for habit in groups["Evening"]] == [
        "evening_brush",
        "evening_journal",
        "evening_sleep_prep",
    ]
    assert [habit.key for habit in groups["Sleep"]] == ["slept_7_hours"]
