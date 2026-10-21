"""PawPal+ scheduling system, see diagrams/uml.mmd."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, time
from enum import Enum


class Priority(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3


class Frequency(Enum):
    ONCE = "once"
    DAILY = "daily"
    WEEKLY = "weekly"


def _minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _to_time(minutes: int) -> time:
    minutes = min(minutes, 23 * 60 + 59)
    return time(minutes // 60, minutes % 60)


@dataclass
class Task:
    id: str
    title: str
    category: str
    duration_minutes: int
    priority: Priority
    frequency: Frequency = Frequency.ONCE
    fixed_time: time | None = None
    completed: bool = False
    last_completed: date | None = None

    def validate(self) -> None:
        if not self.title.strip():
            raise ValueError("Task title must not be empty")
        if self.duration_minutes <= 0:
            raise ValueError("Task duration must be positive")

    def is_due(self, day: date) -> bool:
        if self.frequency == Frequency.ONCE:
            return not self.completed
        if self.last_completed is None:
            return True
        if self.frequency == Frequency.DAILY:
            return self.last_completed < day
        return (day - self.last_completed).days >= 7

    def mark_complete(self, day: date | None = None) -> None:
        self.last_completed = day or date.today()
        if self.frequency == Frequency.ONCE:
            self.completed = True


@dataclass
class Pet:
    name: str
    species: str
    breed: str = ""
    age: int = 0
    tasks: list[Task] = field(default_factory=list)

    def add_task(self, task: Task) -> None:
        task.validate()
        if any(t.id == task.id for t in self.tasks):
            raise ValueError(f"Duplicate task id: {task.id}")
        self.tasks.append(task)

    def edit_task(self, task_id: str, changes: dict) -> Task:
        task = next((t for t in self.tasks if t.id == task_id), None)
        if task is None:
            raise KeyError(task_id)
        updated = replace(task, **changes)
        updated.validate()
        for name in changes:
            setattr(task, name, getattr(updated, name))
        return task

    def remove_task(self, task_id: str) -> None:
        before = len(self.tasks)
        self.tasks = [t for t in self.tasks if t.id != task_id]
        if len(self.tasks) == before:
            raise KeyError(task_id)

    def get_pending_tasks(self) -> list[Task]:
        return [t for t in self.tasks if not t.completed]


@dataclass
class Owner:
    name: str
    available_minutes: int
    day_start: time
    day_end: time
    preferences: list[str] = field(default_factory=list)
    pets: list[Pet] = field(default_factory=list)

    def add_pet(self, pet: Pet) -> None:
        if any(p.name == pet.name for p in self.pets):
            raise ValueError(f"Duplicate pet name: {pet.name}")
        self.pets.append(pet)

    def remove_pet(self, pet_name: str) -> None:
        before = len(self.pets)
        self.pets = [p for p in self.pets if p.name != pet_name]
        if len(self.pets) == before:
            raise KeyError(pet_name)

    def get_all_tasks(self) -> list[Task]:
        return [t for p in self.pets for t in p.get_pending_tasks()]


@dataclass
class ScheduledItem:
    task: Task
    pet: Pet
    start: time
    end: time
    reason: str = ""

    def overlaps(self, other: ScheduledItem) -> bool:
        return _minutes(self.start) < _minutes(other.end) and _minutes(other.start) < _minutes(self.end)


@dataclass
class DailyPlan:
    day: date
    items: list[ScheduledItem] = field(default_factory=list)
    skipped: list[Task] = field(default_factory=list)
    total_minutes: int = 0

    def add_item(self, item: ScheduledItem) -> None:
        self.items.append(item)
        self.items.sort(key=lambda i: _minutes(i.start))
        self.total_minutes += item.task.duration_minutes

    def explain(self) -> str:
        lines = [f"Plan for {self.day.isoformat()} ({self.total_minutes} min scheduled):"]
        for i in self.items:
            lines.append(f"- {i.start:%H:%M}-{i.end:%H:%M} {i.pet.name}: {i.task.title} ({i.reason})")
        for t in self.skipped:
            lines.append(f"- Skipped: {t.title} (no time or conflict)")
        return "\n".join(lines)

    def to_rows(self) -> list[dict]:
        return [
            {
                "Start": f"{i.start:%H:%M}",
                "End": f"{i.end:%H:%M}",
                "Pet": i.pet.name,
                "Task": i.task.title,
                "Priority": i.task.priority.name,
                "Reason": i.reason,
            }
            for i in self.items
        ]


class Scheduler:
    def __init__(self, owner: Owner) -> None:
        self.owner = owner

    def _pet_for(self, task: Task) -> Pet:
        return next(p for p in self.owner.pets if any(t is task for t in p.tasks))

    def generate_plan(self, day: date) -> DailyPlan:
        plan = DailyPlan(day=day)
        due = self.filter_due_tasks(self.owner.get_all_tasks(), day)
        ordered = self.apply_preferences(self.sort_tasks(due))
        fitted, skipped = self.fit_to_time(ordered)
        plan.skipped.extend(skipped)

        start, end = _minutes(self.owner.day_start), _minutes(self.owner.day_end)
        fixed = [t for t in fitted if t.fixed_time is not None]
        flexible = [t for t in fitted if t.fixed_time is None]

        # Fixed-time tasks go in first, so flexible ones fill the gaps around them.
        for task in sorted(fixed, key=lambda t: _minutes(t.fixed_time)):
            s = _minutes(task.fixed_time)
            item = ScheduledItem(
                task, self._pet_for(task), _to_time(s), _to_time(s + task.duration_minutes), "fixed time"
            )
            if s < start or s + task.duration_minutes > end or any(item.overlaps(i) for i in plan.items):
                plan.skipped.append(task)
            else:
                plan.add_item(item)

        for task in flexible:
            slot = self._first_gap(plan.items, task.duration_minutes, start, end)
            if slot is None:
                plan.skipped.append(task)
                continue
            plan.add_item(
                ScheduledItem(
                    task,
                    self._pet_for(task),
                    _to_time(slot),
                    _to_time(slot + task.duration_minutes),
                    f"{task.priority.name.lower()} priority",
                )
            )
        return plan

    @staticmethod
    def _first_gap(items: list[ScheduledItem], duration: int, start: int, end: int) -> int | None:
        cursor = start
        for i in sorted(items, key=lambda i: _minutes(i.start)):
            if _minutes(i.start) - cursor >= duration:
                return cursor
            cursor = max(cursor, _minutes(i.end))
        return cursor if end - cursor >= duration else None

    def sort_tasks(self, tasks: list[Task]) -> list[Task]:
        return sorted(tasks, key=lambda t: (-t.priority.value, t.duration_minutes))

    def filter_due_tasks(self, tasks: list[Task], day: date) -> list[Task]:
        return [t for t in tasks if t.is_due(day)]

    def fit_to_time(self, tasks: list[Task]) -> tuple[list[Task], list[Task]]:
        """Greedily keep tasks, in the given order, within the owner's time budget."""
        fitted, skipped, used = [], [], 0
        for t in tasks:
            if used + t.duration_minutes <= self.owner.available_minutes:
                fitted.append(t)
                used += t.duration_minutes
            else:
                skipped.append(t)
        return fitted, skipped

    def detect_conflicts(self, items: list[ScheduledItem]) -> list[tuple]:
        return [(a, b) for n, a in enumerate(items) for b in items[n + 1:] if a.overlaps(b)]

    def apply_preferences(self, tasks: list[Task]) -> list[Task]:
        """Within the same priority, put tasks in preferred categories first."""
        prefs = {p.lower() for p in self.owner.preferences}
        return sorted(tasks, key=lambda t: (-t.priority.value, t.category.lower() not in prefs))
