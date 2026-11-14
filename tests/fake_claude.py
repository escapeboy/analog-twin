"""Stand-in for `claude -p ... --output-format stream-json` used by tests (CLAUDE_BIN). Behaviour via FAKE_MODE:
ok | exit1 | hang | badref_once | badref_always | auth. Reads the evidence pack from stdin and cites real refs."""
import json
import os
import sys
import time

args = sys.argv[1:]
system = args[args.index("--append-system-prompt") + 1] if "--append-system-prompt" in args else ""
model = args[args.index("--model") + 1] if "--model" in args else ""
stdin = sys.stdin.read()
mode = os.environ.get("FAKE_MODE", "ok")


def out(obj):
    print(json.dumps(obj), flush=True)


def reply(text):
    out({"type": "system", "subtype": "init", "model": model})
    for i in range(0, len(text), 40):
        out({"type": "stream_event", "event": {"type": "content_block_delta", "index": 0,
                                               "delta": {"type": "text_delta", "text": text[i:i + 40]}}})
        time.sleep(0.01)
    out({"type": "result", "subtype": "success", "is_error": False, "result": text})


if mode == "exit1":
    sys.stderr.write("boom\n")
    sys.exit(1)
if mode == "hang":
    time.sleep(60)
if mode == "auth":
    out({"type": "result", "subtype": "success", "is_error": True, "result": "Not logged in. Please run /login"})
    sys.exit(1)

if "ROLE:" not in system:
    reply("OK")
    sys.exit(0)

role = system.split("ROLE:")[1].split()[0]
pack = json.loads(stdin.split("EVIDENCE PACK:\n", 1)[1].split("\n", 1)[0])
twins = [i for i in pack["items"] if i["kind"] == "twin"]
earth = [t for t in twins if t["data"]["body"] == "earth"] or twins
retry = "PREVIOUS ANSWER WAS REJECTED" in stdin
bad = (mode == "badref_always") or (mode == "badref_once" and not retry)

if role == "director":
    plan = {
        "target": {"body": "mars", "lat": 1, "lon": 2, "label": "model-made-up"},
        "sites": [{"label": f"Site {i}", "lat": 99.0, "lon": 99.0, "terrain_sim": 0.123, "light_sim": 0.456, "window": "x",
                   "context": "", "role_in_campaign": "primary traverse site", "refs": [t["ref"]]} for i, t in enumerate(earth[:2])],
        "tests": [{"name": "Low-sun navigation", "why": "sun stays near the horizon", "site": "Site 0", "window": None,
                   "refs": [earth[0]["ref"]]}],
        "disagreements": [{"between": ["terrain", "logistics"], "about": "primary site", "resolution": "split between the two sites"}],
        "not_reproducible_on_earth": ["reduced gravity", "vacuum"],
        "limitations": [],
    }
    reply("Synthesis done.\n```json\n" + json.dumps(plan) + "\n```")
else:
    t = earth[0]
    claims = [{"text": f"Top site has terrain_sim {t['data']['terrain_sim']}.", "refs": [t["ref"]]}]
    if bad and role == "terrain":
        claims.append({"text": "Invented site is great.", "refs": ["twin:does-not-exist"]})
        claims.append({"text": "Uncited statement.", "refs": []})
        claims.append({"text": "Invented number 77.77 shows up.", "refs": [t["ref"]]})
    rep = {"role": role, "summary": f"{role} summary", "claims": claims, "proposed_sites": [t["ref"]]}
    if role == "testlead":
        rep["not_reproducible_on_earth"] = ["reduced gravity", "vacuum"]
    reply("Reasoning.\n```json\n" + json.dumps(rep) + "\n```")
