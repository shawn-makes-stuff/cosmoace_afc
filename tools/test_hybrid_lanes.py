#!/usr/bin/env python3
"""On-printer hybrid path smoke test for all ACE lanes.

Assumes CosmoACE hybrid: one shared hub switch after the 4-in-1, one
toolhead sensor on the single bowden. No per-lane filament sensors.

Waits until the requested lanes show spool present + Ready (parked behind
the hub), then for each lane runs AFC_ACE_CALIBRATE_HUB PARK=1 (feed to
shared hub, park CLEAR mm behind). Hub must clear between lanes.

  python tools/test_hybrid_lanes.py --host 10.0.0.23
  python tools/test_hybrid_lanes.py --host 10.0.0.23 --lanes 1,2,3,4 --wait 600
  python tools/test_hybrid_lanes.py --host 10.0.0.23 --skip-motion   # status only

Does not TOOL_LOAD / heat the extruder.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Sequence, Tuple


DEFAULT_HOST = "10.0.0.23"
UNIT = "ACE_1"
HUB = "ACE_1"
TOOL_SENSOR = "filament_switch_sensor extruder_tool_start"


def _url(host: str, path: str) -> str:
    return f"http://{host}{path}"


def get_json(host: str, path: str, timeout: float = 10.0) -> Dict[str, Any]:
    req = urllib.request.Request(_url(host, path), method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def post_json(host: str, path: str, body: Dict[str, Any],
              timeout: float = 600.0) -> Dict[str, Any]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        _url(host, path), data=data, method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def printer_ready(host: str) -> bool:
    try:
        info = get_json(host, "/printer/info")
        return str(info.get("result", {}).get("state", "")).lower() == "ready"
    except Exception:
        return False


def query(host: str, objects: Sequence[str]) -> Dict[str, Any]:
    path = "/printer/objects/query?" + "&".join(
        o.replace(" ", "%20") for o in objects)
    return get_json(host, path).get("result", {}).get("status", {})


def lane_obj(n: int) -> str:
    return f"AFC_lane lane{n}"


def hub_obj() -> str:
    return f"AFC_hub {HUB}"


def run_gcode(host: str, script: str, timeout: float = 600.0) -> None:
    post_json(host, "/printer/gcode/script", {"script": script}, timeout=timeout)


def lane_snapshot(status: Dict[str, Any], n: int) -> Dict[str, Any]:
    lane = status.get(lane_obj(n), {})
    hub = status.get(hub_obj(), {})
    tool = status.get(TOOL_SENSOR, {})
    return {
        "lane": n,
        "prep": bool(lane.get("prep")),
        "load": bool(lane.get("load")),
        "loaded_to_hub": bool(lane.get("loaded_to_hub")),
        "tool_loaded": bool(lane.get("tool_loaded")),
        "filament_status": lane.get("filament_status"),
        "status": lane.get("status"),
        "hub_state": bool(hub.get("state")),
        "tool_detected": bool(tool.get("filament_detected")),
        "afc_bowden_length": hub.get("afc_bowden_length"),
    }


def fmt_snap(s: Dict[str, Any]) -> str:
    return (f"lane{s['lane']}: prep={s['prep']} load={s['load']} "
            f"status={s['filament_status']!r}/{s['status']!r} "
            f"tool_loaded={s['tool_loaded']} "
            f"hub={s['hub_state']} toolhead={s['tool_detected']}")


def wait_lanes_ready(host: str, lanes: Sequence[int], wait_s: float,
                     poll_s: float = 2.0) -> Tuple[bool, List[Dict[str, Any]]]:
    """Wait until every lane is prep+load (Ready behind hub), hub/tool clear."""
    deadline = time.time() + wait_s
    last: List[Dict[str, Any]] = []
    while True:
        objs = [lane_obj(n) for n in lanes] + [hub_obj(), TOOL_SENSOR]
        status = query(host, objs)
        last = [lane_snapshot(status, n) for n in lanes]
        ok = all(
            s["prep"] and s["load"] and not s["tool_loaded"]
            and not s["hub_state"] and not s["tool_detected"]
            for s in last
        )
        print(time.strftime("%H:%M:%S"), "|", " | ".join(fmt_snap(s) for s in last))
        if ok:
            return True, last
        if time.time() >= deadline:
            return False, last
        time.sleep(poll_s)


def stage_and_park(host: str, n: int, clear_mm: float, cap: float) -> Dict[str, Any]:
    """Feed to shared hub then park CLEAR behind it (insert-stage equivalent)."""
    lane = f"lane{n}"
    print(f"=== lane{n}: CALIBRATE_HUB PARK=1 CLEAR={clear_mm:.0f} ===")
    run_gcode(
        host,
        f"AFC_ACE_CALIBRATE_HUB UNIT={UNIT} LANE={lane} PARK=1 "
        f"CLEAR={clear_mm:.0f} CAP={cap:.0f}",
        timeout=600.0,
    )
    status = query(host, [lane_obj(n), hub_obj(), TOOL_SENSOR])
    snap = lane_snapshot(status, n)
    print("    result:", fmt_snap(snap))
    if snap["hub_state"]:
        raise RuntimeError(f"lane{n}: hub still triggered after park")
    if snap["tool_detected"]:
        raise RuntimeError(f"lane{n}: toolhead sensor lit after park")
    if not snap["prep"]:
        raise RuntimeError(f"lane{n}: prep lost after park")
    return snap


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--lanes", default="1,2,3,4",
                    help="Comma-separated lane numbers (default 1,2,3,4)")
    ap.add_argument("--wait", type=float, default=900.0,
                    help="Seconds to wait for all lanes Ready (default 900)")
    ap.add_argument("--clear", type=float, default=80.0,
                    help="Park mm behind hub (default 80)")
    ap.add_argument("--cap", type=float, default=1500.0,
                    help="Feed-to-hub safety cap mm (default 1500)")
    ap.add_argument("--skip-motion", action="store_true",
                    help="Only wait/verify Ready status; do not feed")
    ap.add_argument("--pause-between", type=float, default=2.0,
                    help="Seconds between lane motions (default 2)")
    args = ap.parse_args()

    lanes = [int(x.strip()) for x in args.lanes.split(",") if x.strip()]
    if not lanes:
        print("No lanes given", file=sys.stderr)
        return 2

    print(f"Host {args.host}  lanes={lanes}  clear={args.clear}mm")
    if not printer_ready(args.host):
        print("Printer not ready (Klipper not up?)", file=sys.stderr)
        return 1

    print(f"Waiting up to {args.wait:.0f}s for prep+Ready, hub/tool clear...")
    ok, snaps = wait_lanes_ready(args.host, lanes, args.wait)
    if not ok:
        print("TIMEOUT waiting for all lanes Ready behind hub:", file=sys.stderr)
        for s in snaps:
            print(" ", fmt_snap(s), file=sys.stderr)
        return 1

    print("All lanes Ready behind hub.")
    hub = query(args.host, [hub_obj()]).get(hub_obj(), {})
    print(f"afc_bowden_length={hub.get('afc_bowden_length')}")

    if args.skip_motion:
        print("OK (status-only)")
        return 0

    failures: List[str] = []
    for n in lanes:
        try:
            st = query(args.host, [hub_obj(), TOOL_SENSOR])
            if st.get(hub_obj(), {}).get("state"):
                raise RuntimeError("hub occupied before lane motion — clear path")
            if st.get(TOOL_SENSOR, {}).get("filament_detected"):
                raise RuntimeError("toolhead sensor lit before lane motion")
            stage_and_park(args.host, n, args.clear, args.cap)
        except Exception as exc:
            msg = f"lane{n}: {exc}"
            print("FAIL", msg, file=sys.stderr)
            failures.append(msg)
            st = query(args.host, [hub_obj()])
            if st.get(hub_obj(), {}).get("state"):
                print("Hub still triggered — aborting remaining lanes",
                      file=sys.stderr)
                break
        time.sleep(args.pause_between)

    print("--- final ---")
    status = query(
        args.host, [lane_obj(n) for n in lanes] + [hub_obj(), TOOL_SENSOR])
    for n in lanes:
        print(fmt_snap(lane_snapshot(status, n)))

    if failures:
        print(f"FAILED ({len(failures)}):", "; ".join(failures), file=sys.stderr)
        return 1
    print("OK: all lanes fed to shared hub and parked behind it")
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
