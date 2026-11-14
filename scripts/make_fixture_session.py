"""Write sessions/golden/fixture.jsonl: a schema-valid FIXTURE crew session for frontend development."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from api import fixtures  # noqa: E402
from crew.schemas import ROLE_TITLES, Event, SpecialistReport, Claim  # noqa: E402

SID = "fixture"
out = pathlib.Path(__file__).resolve().parent.parent / "sessions" / "golden" / "fixture.jsonl"
ev = []
t = 0.0


def add(type_, role=None, dt=0.0, **data):
    global t
    t = round(t + dt, 3)
    ev.append(Event(type=type_, session_id=SID, t=t, role=role, data=data))


add("session.start", target={"body": "moon", "lat": -89.5, "lon": 0.0, "label": "[fixture] Shackleton rim"}, mode="replay")
specs = ["terrain", "light", "logistics", "testlead"]
for r in specs:
    add("agent.start", r, 0.2, title=ROLE_TITLES[r], model="fixture")
for r in specs:
    add("tool.result", r, 0.3, name="evidence", ref="twin:earth-fx0", digest="[fixture] top Earth twin, terrain_sim 0.95")
for i in range(6):
    for r in specs:
        add("agent.delta", r, 0.4, text=f"[fixture] {ROLE_TITLES[r]} thinking, chunk {i + 1}. ")
for r in specs:
    rep = SpecialistReport(role=r, summary=f"[fixture] {ROLE_TITLES[r]} report",
                           claims=[Claim(text="[fixture] twin 1 has terrain_sim 0.95", refs=["twin:earth-fx0"])],
                           proposed_sites=["earth-fx0"])
    add("agent.report", r, 0.5, report=rep.model_dump())
add("agent.start", "director", 0.3, title=ROLE_TITLES["director"], model="fixture")
for i in range(8):
    add("director.delta", "director", 0.4, text=f"[fixture] Director synthesis chunk {i + 1}. ")
add("plan.final", "director", 0.5, plan=fixtures.plan().model_dump())
add("session.end", None, 0.1, wall_s=t, status="ok")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text("\n".join(e.model_dump_json() for e in ev) + "\n")
print(out, len(ev), "events", t, "s")
