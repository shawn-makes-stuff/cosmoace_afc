"""Resolve each entry config (cc1-/cc2- x runout/toolhead) the way COSMOS's
Kalico reads it from the addon clone: includes relative to the including file
(absolute ones as-is), a repeated section merges key by key, [!section]
deletes.

  python tools/check_configs.py <cosmos checkout>

Absolute /etc/klipper/config/extras-readonly/ includes are served from the
COSMOS checkout (afc.cfg, canvas-toolhead.cfg). Prints the merged sections
that matter and fails on a missing include or a wrong per-machine value.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
READONLY = "/etc/klipper/config/extras-readonly/"


def parse(path, out, readonly):
    section = None
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        m = re.match(r"^\[(.+)\]\s*(#.*)?$", line)
        if m:
            name = m.group(1).strip()
            if name.startswith("include "):
                spec = name[8:].strip()
                inc = (readonly[spec[len(READONLY):]] if spec.startswith(READONLY)
                       else os.path.join(os.path.dirname(path), spec))
                if not os.path.exists(inc):
                    raise SystemExit(f"{path}: missing include {spec}")
                parse(inc, out, readonly)
                section = None
            elif name.startswith("!"):
                out.pop(name[1:].strip(), None)
                section = None
            else:
                section = out.setdefault(name, {})
            continue
        m = re.match(r"^([A-Za-z_][\w]*)\s*[:=]\s*(.*?)\s*(#.*)?$", line)
        if m and section is None:
            # Kalico parses each file on its own: this stops it starting
            raise SystemExit(f"{path}: '{m.group(1)}' outside any section")
        if m:
            section[m.group(1)] = m.group(2)


def resolve(cosmos, machine, sensor):
    files = os.path.join(cosmos, "meta-opencentauri/recipes-apps/klipper/files")
    readonly = {"afc.cfg": os.path.join(cosmos, "meta-opencentauri/recipes-data/klipper-afc-addon/files/afc.cfg")}
    if machine == "cc1":
        readonly["canvas-toolhead.cfg"] = os.path.join(files, "centauri-carbon-1/canvas-toolhead.cfg")
    # stock sections the overrides apply to / delete
    out = {"filament_switch_sensor filament_sensor": {"switch_pin": "STOCK"}, "extruder": {}}
    if machine == "cc2":
        out["canvas_filament_sensor"] = {}
        out["filament_motion_sensor filament_motion"] = {}
    parse(os.path.join(ROOT, "config", f"{machine}-{sensor}.cfg"), out, readonly)
    return out


def main():
    cosmos = sys.argv[1]
    pins = {"cc1": "!hotend:PB2", "cc2": "!hotend:PB1"}
    for machine in pins:
        for sensor in ("runout", "toolhead"):
            c = resolve(cosmos, machine, sensor)
            ext, hub, unit = c["AFC_extruder extruder"], c["AFC_hub ACE_1"], c["AFC_ACE ACE_1"]
            print(f"{machine} {sensor}: tool_stn={ext.get('tool_stn')} "
                  f"pin={ext.get('pin_tool_start')} bowden={hub.get('afc_bowden_length')} "
                  f"hub_sensor={unit.get('hub_sensor_name')} park={unit.get('hub_clear_mm')} "
                  f"dist_hub={c['AFC_lane lane1'].get('dist_hub')} "
                  f"KICK={'variable_cool_ms' in c.get('gcode_macro KICK', {})} "
                  f"park_pre_load={c['AFC'].get('park_pre_load')}")
            assert c["AFC"]["park_pre_load"] == "False"
            assert ("variable_cool_ms" in c.get("gcode_macro KICK", {})) == (machine == "cc1")
            if sensor == "runout":
                assert c["filament_switch_sensor filament_sensor"]["switch_pin"] == "STOCK"
                assert unit["hub_sensor_name"] == "filament_sensor"
                assert "pin_tool_start" not in ext
            else:
                assert ext["pin_tool_start"] == pins[machine]
                assert "filament_switch_sensor filament_sensor" not in c
                assert "hub_sensor_name" not in unit
                if machine == "cc1":
                    assert c["extruder"].get("pulldown_resistor") == "100000"
                else:
                    assert "filament_motion_sensor filament_motion" not in c
                    assert "canvas_filament_sensor" not in c
    print("ok")


if __name__ == "__main__":
    main()
