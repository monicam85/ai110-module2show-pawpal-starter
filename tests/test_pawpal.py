from datetime import date, time

import pytest

from pawpal_system import (
    Frequency, Owner, Pet, Priority, ScheduledItem, Scheduler, Task,
)

DAY = date(2026, 1, 5)


def task(id="t1", minutes=30, priority=Priority.MEDIUM, **kw):
    return Task(id, kw.pop("title", id), kw.pop("category", "care"), minutes, priority, **kw)


def owner_with(*tasks, minutes=240, prefs=None):
    pet = Pet("Rex", "dog")
    for t in tasks:
        pet.add_task(t)
    return Owner("Sam", minutes, time(8), time(18), prefs or [], [pet])


def test_validate_rejects_bad_tasks():
    with pytest.raises(ValueError):
        Pet("Rex", "dog").add_task(task(minutes=0))
    with pytest.raises(ValueError):
        Pet("Rex", "dog").add_task(task(title=" "))


def test_add_edit_remove_task():
    pet = Pet("Rex", "dog")
    pet.add_task(task("a"))
    with pytest.raises(ValueError):
        pet.add_task(task("a"))
    pet.edit_task("a", {"duration_minutes": 10})
    assert pet.tasks[0].duration_minutes == 10
    with pytest.raises(ValueError):
        pet.edit_task("a", {"duration_minutes": -1})
    assert pet.tasks[0].duration_minutes == 10
    pet.remove_task("a")
    assert pet.tasks == []


def test_mark_complete_once_removes_from_pending():
    t = task()
    pet = Pet("Rex", "dog", tasks=[t])
    t.mark_complete(DAY)
    assert pet.get_pending_tasks() == []
    assert not t.is_due(DAY)


def test_daily_and_weekly_recurrence():
    d = task(frequency=Frequency.DAILY)
    w = task(frequency=Frequency.WEEKLY)
    assert d.is_due(DAY) and w.is_due(DAY)
    d.mark_complete(DAY)
    w.mark_complete(DAY)
    assert not d.is_due(DAY) and d.is_due(date(2026, 1, 6))
    assert not w.is_due(date(2026, 1, 11)) and w.is_due(date(2026, 1, 12))


def test_sort_by_priority_then_duration():
    s = Scheduler(owner_with())
    a, b, c = task("a", 20, Priority.LOW), task("b", 50, Priority.HIGH), task("c", 10, Priority.HIGH)
    assert [t.id for t in s.sort_tasks([a, b, c])] == ["c", "b", "a"]


def test_preferences_break_priority_ties_only():
    s = Scheduler(owner_with(prefs=["play"]))
    a = task("a", priority=Priority.MEDIUM, category="walk")
    b = task("b", priority=Priority.MEDIUM, category="play")
    c = task("c", priority=Priority.HIGH, category="walk")
    assert [t.id for t in s.apply_preferences([a, b, c])] == ["c", "b", "a"]


def test_fit_to_time_skips_over_budget():
    s = Scheduler(owner_with(minutes=60))
    fitted, skipped = s.fit_to_time([task("a", 40), task("b", 40), task("c", 20)])
    assert [t.id for t in fitted] == ["a", "c"]
    assert [t.id for t in skipped] == ["b"]


def test_overlaps_and_detect_conflicts():
    pet = Pet("Rex", "dog")

    def mk(s, e):
        return ScheduledItem(task(), pet, time(*s), time(*e))

    a, b, c = mk((9, 0), (10, 0)), mk((9, 30), (10, 30)), mk((10, 0), (11, 0))
    assert a.overlaps(b) and not a.overlaps(c)
    assert Scheduler(owner_with()).detect_conflicts([a, b, c]) == [(a, b), (b, c)]


def test_generate_plan_fills_gaps_around_fixed_task():
    fixed = task("fixed", 30, Priority.LOW, fixed_time=time(8, 0))
    flex = task("flex", 60, Priority.HIGH)
    o = owner_with(fixed, flex)
    plan = Scheduler(o).generate_plan(DAY)
    assert [(i.task.id, i.start) for i in plan.items] == [("fixed", time(8, 0)), ("flex", time(8, 30))]
    assert Scheduler(o).detect_conflicts(plan.items) == []
    assert plan.total_minutes == 90 and not plan.skipped


def test_generate_plan_skips_when_no_time_or_conflict():
    a = task("a", 30, fixed_time=time(9, 0))
    b = task("b", 30, fixed_time=time(9, 15))
    big = task("big", 400)
    plan = Scheduler(owner_with(a, b, big, minutes=100)).generate_plan(DAY)
    assert {t.id for t in plan.skipped} == {"b", "big"}
    assert [i.task.id for i in plan.items] == ["a"]


def test_generate_plan_excludes_not_due_and_explains():
    done = task("done", frequency=Frequency.DAILY)
    done.mark_complete(DAY)
    plan = Scheduler(owner_with(done, task("x"))).generate_plan(DAY)
    assert [i.task.id for i in plan.items] == ["x"]
    assert "x" in plan.explain() and plan.to_rows()[0]["Task"] == "x"
