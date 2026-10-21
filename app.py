import uuid
from datetime import date, time

import streamlit as st

from pawpal_system import Frequency, Owner, Pet, Priority, Scheduler, Task

st.set_page_config(page_title="PawPal+", page_icon="🐾", layout="centered")

st.title("🐾 PawPal+")
st.caption("A pet care planning assistant: add pets and tasks, then build a daily schedule.")

# The Owner lives in session_state so data survives Streamlit reruns.
if "owner" not in st.session_state:
    st.session_state.owner = None

CATEGORY_OPTIONS = ["exercise", "feeding", "health", "grooming", "enrichment", "hygiene", "general"]

st.subheader("Owner")
with st.form("owner_form"):
    owner_name = st.text_input("Owner name", value="Jordan")
    available = st.number_input("Available minutes today", min_value=1, max_value=1440, value=120)
    c1, c2 = st.columns(2)
    day_start = c1.time_input("Day start", value=time(8, 0))
    day_end = c2.time_input("Day end", value=time(20, 0))
    prev_prefs = st.session_state.owner.preferences if st.session_state.owner else []
    picked = st.multiselect(
        "Preferred task categories",
        sorted({*CATEGORY_OPTIONS, *prev_prefs}),
        default=prev_prefs,
    )
    extra = st.text_input("Other categories (comma-separated, optional)", value="")
    saved = st.form_submit_button("Save owner")

if saved:
    if day_end <= day_start:
        st.error("Day end must be after day start.")
    else:
        old = st.session_state.owner
        st.session_state.owner = Owner(
            name=owner_name,
            available_minutes=int(available),
            day_start=day_start,
            day_end=day_end,
            preferences=[*picked, *(p.strip() for p in extra.split(",") if p.strip())],
            pets=old.pets if old else [],
        )
        st.success(f"Saved owner {owner_name}.")

owner: Owner | None = st.session_state.owner
if owner is None:
    st.info("Save an owner to get started.")
    st.stop()

st.divider()
st.subheader("Pets")
with st.form("pet_form", clear_on_submit=True):
    c1, c2 = st.columns(2)
    pet_name = c1.text_input("Pet name", value="Mochi")
    species = c2.selectbox("Species", ["dog", "cat", "other"])
    add_pet = st.form_submit_button("Add pet")

if add_pet:
    try:
        owner.add_pet(Pet(name=pet_name.strip(), species=species))
    except ValueError as e:
        st.error(str(e))

if not owner.pets:
    st.info("No pets yet. Add one above.")
    st.stop()

st.write(", ".join(f"{p.name} ({p.species})" for p in owner.pets))

st.divider()
st.subheader("Tasks")
target = st.selectbox("Pet", [p.name for p in owner.pets])
pet = next(p for p in owner.pets if p.name == target)

# Preset tasks: title -> (category, minutes, priority, frequency)
PRESET_TASKS = {
    "Morning walk": ("exercise", 20, "medium", "daily"),
    "Evening walk": ("exercise", 20, "medium", "daily"),
    "Feeding": ("feeding", 10, "high", "daily"),
    "Give medication": ("health", 5, "high", "daily"),
    "Grooming": ("grooming", 30, "low", "weekly"),
    "Playtime": ("enrichment", 15, "low", "daily"),
    "Litter box cleaning": ("hygiene", 10, "medium", "daily"),
    "Vet appointment": ("health", 60, "high", "once"),
}
CUSTOM = "Other (add your own)..."
PRIORITIES = [p.name.lower() for p in Priority]
FREQUENCIES = [f.value for f in Frequency]

prefs = {p.lower() for p in owner.preferences}
# Presets in preferred categories come first (all presets stay available).
preset_names = sorted(PRESET_TASKS, key=lambda n: PRESET_TASKS[n][0] not in prefs)
choice = st.selectbox(
    "Task",
    [*preset_names, CUSTOM],
)
if choice == CUSTOM:
    d_cat, d_min, d_pri, d_freq = "general", 15, "medium", "once"
    title = st.text_input("Custom task name", key="custom_title")
else:
    d_cat, d_min, d_pri, d_freq = PRESET_TASKS[choice]
    title = choice

c1, c2, c3 = st.columns(3)
# Keys include the choice so defaults reset when a different task is picked.
duration = c1.number_input("Duration (minutes)", 1, 240, d_min, key=f"dur_{choice}")
priority = c2.selectbox("Priority", PRIORITIES, index=PRIORITIES.index(d_pri), key=f"pri_{choice}")
cat_options = [*owner.preferences, *(c for c in CATEGORY_OPTIONS if c not in owner.preferences)]
if d_cat not in cat_options:
    cat_options.append(d_cat)
category = c3.selectbox("Category", cat_options, index=cat_options.index(d_cat), key=f"cat_{choice}")
c4, c5 = st.columns(2)
frequency = c4.selectbox("Frequency", FREQUENCIES, index=FREQUENCIES.index(d_freq), key=f"freq_{choice}")
fixed = c5.time_input("Fixed time (optional)", value=None, key=f"fix_{choice}")

if st.button("Add task"):
    try:
        pet.add_task(
            Task(
                id=uuid.uuid4().hex[:8],
                title=title.strip(),
                category=category.strip() or "general",
                duration_minutes=int(duration),
                priority=Priority[priority.upper()],
                frequency=Frequency(frequency),
                fixed_time=fixed,
            )
        )
        st.success(f"Added '{title.strip()}' for {pet.name}.")
    except ValueError as e:
        st.error(str(e))


def _set_priority(p: Pet, task_id: str) -> None:
    new = st.session_state[f"prio_{task_id}"]
    p.edit_task(task_id, {"priority": Priority[new.upper()]})


def _delete_task(p: Pet, task_id: str) -> None:
    task = next((t for t in p.tasks if t.id == task_id), None)
    if task is not None:
        # Remember the dismissal so the sync below doesn't re-add it.
        st.session_state.setdefault("dismissed_pref", set()).add((p.name, task.title))
    p.remove_task(task_id)


def _sync_preferred_tasks() -> None:
    """Auto-add presets in preferred categories to every pet."""
    dismissed = st.session_state.setdefault("dismissed_pref", set())
    for p in owner.pets:
        have = {t.title for t in p.tasks}
        for name, (cat, mins, pri, freq) in PRESET_TASKS.items():
            if cat in prefs and name not in have and (p.name, name) not in dismissed:
                p.add_task(
                    Task(
                        id=uuid.uuid4().hex[:8],
                        title=name,
                        category=cat,
                        duration_minutes=mins,
                        priority=Priority[pri.upper()],
                        frequency=Frequency(freq),
                    )
                )


_sync_preferred_tasks()

st.markdown("**Current tasks**")
any_tasks = False
for p in owner.pets:
    for t in p.get_pending_tasks():
        any_tasks = True
        c1, c2, c3 = st.columns([4, 2, 1])
        c1.write(f"**{t.title}** · {p.name} · {t.duration_minutes} min · {t.frequency.value}")
        c2.selectbox(
            "Priority",
            PRIORITIES,
            index=PRIORITIES.index(t.priority.name.lower()),
            key=f"prio_{t.id}",
            label_visibility="collapsed",
            on_change=_set_priority,
            args=(p, t.id),
        )
        c3.button("🗑️", key=f"del_{t.id}", help="Delete task", on_click=_delete_task, args=(p, t.id))
if not any_tasks:
    st.info("No tasks yet. Add one above.")

st.divider()
st.subheader("Build Schedule")
plan_day = st.date_input("Day", value=date.today())

if st.button("Generate schedule"):
    plan = Scheduler(owner).generate_plan(plan_day)
    names = [p.name for p in owner.pets]
    who = names[0] if len(names) == 1 else ", ".join(names[:-1]) + f" & {names[-1]}"
    st.subheader(f"🐾 {who}'s schedule for {plan_day:%A, %B %d}")
    if plan.items:
        st.success(f"Scheduled {len(plan.items)} task(s), {plan.total_minutes} min total.")
        st.table(plan.to_rows())
    else:
        st.warning("Nothing could be scheduled.")
    if plan.skipped:
        st.warning("Skipped (no time or conflict): " + ", ".join(t.title for t in plan.skipped))
    with st.expander("Plan explanation"):
        st.text(plan.explain())
