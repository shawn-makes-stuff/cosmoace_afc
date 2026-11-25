#!/usr/bin/env python3
"""Heat, then TOOL_LOAD / TOOL_UNLOAD a list of lanes via Moonraker.

  python tools/run_toolchange_smoke.py --host 10.0.0.23 --lanes 1,2,4
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Sequence


DEFAULT_HOST = "10.0.0.23"
TOOL_SENSOR = "filament_switch_sensor extruder_tool_start"


def get_json(host: str, path: str, timeout: float = 30.0) -> Dict[str, Any]:
    req = urllib.request.Request(f"http://{host}{path}", method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def post_json(host: str, path: str, body: Dict[str, Any],
              timeout: float = 900.0) -> Dict[str, Any]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"http://{host}{path}", data=data, method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def gcode(host: str, script: str, timeout: float = 900.0) -> None:
    print(time.strftime("%H:%M:%S"), "GCODE:", script, flush=True)
    post_json(host, "/printer/gcode/script", {"script": script}, timeout=timeout)
    print(time.strftime("%H:%M:%S"), "  ok", flush=True)


def query(host: str, objects: Sequence[str]) -> Dict[str, Any]:
    path = "/printer/objects/query?" + "&".join(
        o.replace(" ", "%20") for o in objects)
    return get_json(host, path).get("result", {}).get("status", {})


def summarize(host: str, lanes: Sequence[int]) -> None:
    objs = [f"AFC_lane lane{n}" for n in lanes] + [
        "AFC_hub ACE_1", "extruder", TOOL_SENSOR]
    st = query(host, objs)
    hub = st.get("AFC_hub ACE_1", {})
    ex = st.get("extruder", {})
    tool = st.get(TOOL_SENSOR, {})
    print(
        f"  hub={hub.get('state')} toolhead={tool.get('filament_detected')} "
        f"nozzle={ex.get('temperature')}->{ex.get('target')} "
        f"can_extrude={ex.get('can_extrude')}",
        flush=True,
    )
    for n in lanes:
        lane = st.get(f"AFC_lane lane{n}", {})
        print(
            f"  lane{n}: prep={lane.get('prep')} load={lane.get('load')} "
            f"tool_loaded={lane.get('tool_loaded')} "
            f"status={lane.get('filament_status')!r}/{lane.get('status')!r}",
            flush=True,
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--lanes", default="1,2,4")
    ap.add_argument("--temp", type=float, default=210.0)
    ap.add_argument("--skip-home", action="store_true")
    args = ap.parse_args()
    lanes = [int(x.strip()) for x in args.lanes.split(",") if x.strip()]

    info = get_json(args.host, "/printer/info")
    state = str(info.get("result", {}).get("state", "")).lower()
    if state != "ready":
        print(f"Printer not ready ({state})", file=sys.stderr)
        return 1

    print("Initial:", flush=True)
    summarize(args.host, lanes)

    if not args.skip_home:
        gcode(args.host, "G28", timeout=300)
    gcode(args.host, f"M109 S{args.temp:.0f}", timeout=400)

    failures: List[str] = []
    for n in lanes:
        lane = f"lane{n}"
        try:
            print(f"=== LOAD {lane} ===", flush=True)
            gcode(args.host, f"TOOL_LOAD LANE={lane}", timeout=900)
            summarize(args.host, lanes)
            st = query(args.host, [f"AFC_lane {lane}"])
            if not st.get(f"AFC_lane {lane}", {}).get("tool_loaded"):
                raise RuntimeError(f"{lane} not tool_loaded after TOOL_LOAD")

            print(f"=== UNLOAD {lane} ===", flush=True)
            gcode(args.host, "TOOL_UNLOAD", timeout=900)
            summarize(args.host, lanes)
            st = query(args.host, [f"AFC_lane {lane}", "AFC_hub ACE_1", TOOL_SENSOR])
            lane_st = st.get(f"AFC_lane {lane}", {})
            if lane_st.get("tool_loaded"):
                raise RuntimeError(f"{lane} still tool_loaded after TOOL_UNLOAD")
            if st.get("AFC_hub ACE_1", {}).get("state"):
                raise RuntimeError("hub still triggered after unload")
            if st.get(TOOL_SENSOR, {}).get("filament_detected"):
                raise RuntimeError("toolhead sensor still lit after unload")
        except Exception as exc:
            msg = f"{lane}: {exc}"
            print("FAIL", msg, file=sys.stderr, flush=True)
            failures.append(msg)
            summarize(args.host, lanes)
            break

    gcode(args.host, "M104 S0", timeout=30)
    print("Final:", flush=True)
    summarize(args.host, lanes)
    if failures:
        print("FAILED:", "; ".join(failures), file=sys.stderr)
        return 1
    print("OK: load/unload sequence complete")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.URLError as exc:
        print(f"HTTP error: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        sys.exit(130)
