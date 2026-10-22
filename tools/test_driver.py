"""afcACE with AFC stubbed out: broken-filament detection on both sensor
paths, and the runout-path early feed + resumed load. python tools/test_driver.py"""
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def stub(name, **attrs):
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    sys.modules[name] = mod
    return mod


stub("extras")
stub("extras.AFC_utils", ERROR_STR="{import_lib} {trace}")
stub("extras.AFC_lane", AFCLaneState=types.SimpleNamespace(TOOL_LOADING="loading", TOOL_LOADED="loaded"), ONLY_LOAD_TYPES=[], EXCLUDE_TYPES=[])
stub("extras.AFC_unit", afcUnit=object)
stub("extras.AFC_OpenAMS", _ams_box_logo=None, _ams_box_logo_error=None)
sys.path.insert(0, ROOT)
import AFC_ACE  # noqa: E402


class Sensor:
    def __init__(self, present):
        self.runout_helper = types.SimpleNamespace(filament_present=present)


def run(path, frame, tool, enable_tool_runout=False, tail=False):
    calls = []
    ace = object.__new__(AFC_ACE.afcACE)
    ace._last_prep, ace._tail_pending = {0: True}, ({"lane1"} if tail else set())
    ace._last_rfid = {}
    ace.hub_sensor_name = "filament_sensor" if path == "runout" else None
    ace.toolhead_sensor_name = None
    ace.logger = types.SimpleNamespace(error=print, info=print)
    ace.printer = types.SimpleNamespace(
        lookup_object=lambda n: Sensor(frame))
    hub = types.SimpleNamespace(is_virtual_pin=lambda: True, enable_runout=False, state=True)
    extruder = types.SimpleNamespace(
        tool_start="hotend:PB2" if path == "toolhead" else None,
        enable_runout=enable_tool_runout)
    lane = types.SimpleNamespace(
        name="lane1", hub_obj=hub, extruder_obj=extruder, tool_loaded=True,
        prep_state=True, loaded_to_hub=True,
        get_toolhead_pre_sensor_state=lambda: tool,
        handle_load_runout=lambda t, state: None,
        handle_toolhead_runout=lambda sensor=None: calls.append(sensor))
    ace.monitor_only = False
    ace.name = "ACE_1"
    ace._sync_lane("lane1", lane, 0, {"slots": [{"status": "ready"}]}, 0.0)
    return calls


# runout path: frame sensor empty with the spool still in -> break pause
assert run("runout", frame=False, tool=None) == ["hub"]
assert run("runout", frame=True, tool=None) == []
# an endless-spool tail passing the sensor is not a break
assert run("runout", frame=False, tool=None, tail=True) == []
# toolhead path: same on the toolhead sensor
assert run("toolhead", frame=None, tool=False) == ["tool_start"]
assert run("toolhead", frame=None, tool=True) == []
# AFC's own toolhead runout armed -> AFC handles it, not the driver
assert run("toolhead", frame=None, tool=False, enable_tool_runout=True) == []
print("ok")


# Runout path, TOOL_LOAD split in two: the early (cold) feed homes on the
# frame sensor and does the blind bowden push; the resumed call only engages
# the gears. It used to restart the load and refuse on the lit sensor.
def load(frame_after_feed=True):
    feeds, state = [], {"frame": False}
    ace = object.__new__(AFC_ACE.afcACE)
    ace.name, ace.monitor_only = "ACE_1", False
    ace.hub_sensor_name, ace.toolhead_sensor_name = "filament_sensor", None
    ace.hub_clear_mm, ace.bowden_overshoot, ace.feed_speed = 110, 300, 50
    ace.sync_load_mm = None
    ace._slot_map, ace._early_feed, ace._operation_active = {"lane1": 0}, None, False
    ace._assist_slot = None
    ace.logger = types.SimpleNamespace(error=print, info=print, warning=print)
    ace.printer = types.SimpleNamespace(
        lookup_object=lambda n: Sensor(state["frame"]))
    ace.afc = types.SimpleNamespace(
        afcDeltaTime=types.SimpleNamespace(log_with_time=lambda m: None),
        move_e_pos=lambda *a, **k: None, save_vars=lambda: None,
        function=types.SimpleNamespace(in_print=lambda: False))
    ace._get_status = lambda **k: {"slots": [{"status": "ready"}]}
    ace.lane_loading = lambda lane: None
    ace._park = lambda ext: None
    ace._set_assist = lambda slot, on: None
    ace._sync_load = lambda slot, ext, mm: (feeds.append(("sync", mm)), (True, ""))[1]

    def feed_until(slot, fn, length, speed, extend=True):
        feeds.append(("homed" if fn else "blind", length))
        if fn:
            state["frame"] = frame_after_feed
        return True, ""
    ace._feed_until = feed_until
    hub = types.SimpleNamespace(is_virtual_pin=lambda: True, afc_bowden_length=810)
    ext = types.SimpleNamespace(tool_start=None, enable_runout=True, tool_stn=5,
                                tool_load_speed=8, tool_end=None)
    lane = types.SimpleNamespace(name="lane1", hub_obj=hub, extruder_obj=ext,
                                 dist_hub=1200, sync_to_extruder=lambda: None)
    ace._tail_in_bowden = lambda l: False
    assert ace._load_inner(lane, ext, to_sensor=True)
    early = list(feeds)
    feeds.clear()
    ace._early_feed = ("lane1", True)
    assert ace.unit_load_lane(lane, ext)
    return early, feeds


early, resumed = load()
assert early == [("homed", 1500), ("blind", 810)], early
assert resumed == [("sync", 5)], resumed
print("ok")
