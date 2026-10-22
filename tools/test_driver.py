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


# Bypass: AFC's virtual bypass gives the path sensor its runout pause back,
# and turning it off restores the ACE's muted setup. Two units on one path
# apply it once.
class GcmdError(Exception):
    pass


def bypass_unit(path, afc_state, frame):
    ace = object.__new__(AFC_ACE.afcACE)
    ace.name, ace.bypass_runout_distance = "ACE_1", 770.0
    ace.hub_sensor_name = "filament_sensor" if path == "runout" else None
    ace.toolhead_sensor_name = None
    ace.logger = types.SimpleNamespace(error=print, info=lambda m: None)
    fila = types.SimpleNamespace(runout_helper=types.SimpleNamespace(sensor_enabled=False))
    ext = types.SimpleNamespace(tool_start="hotend:PB2" if path == "toolhead" else None,
                                enable_runout=False, enable_runout_in_bypass=False,
                                fila_tool_start=fila if path == "toolhead" else None)
    hub = types.SimpleNamespace(is_virtual_pin=lambda: True)
    lane = types.SimpleNamespace(name="lane1", extruder_obj=ext, hub_obj=hub,
                                 get_toolhead_pre_sensor_state=lambda: frame.filament_present)
    ace.lanes, ace._slot_map = {"lane1": lane}, {"lane1": 0}
    ace.printer = types.SimpleNamespace(lookup_object=lambda n: types.SimpleNamespace(runout_helper=frame))
    ace.afc = afc_state
    return ace, ext, fila


frame = types.SimpleNamespace(runout_gcode="stock", runout_distance=0, sensor_enabled=False,
                              filament_present=False)
scripts = []
afc = types.SimpleNamespace(state=False, current=None, printing=False)
afc.get_bypass_state = lambda: afc.state
afc.bypass = types.SimpleNamespace(name="virtual_bypass")
afc.function = types.SimpleNamespace(in_print=lambda: afc.printing)
a1, _, _ = bypass_unit("runout", afc, frame)
a2, _, _ = bypass_unit("runout", afc, frame)
for a in (a1, a2):
    a._sync_bypass()
assert frame.runout_gcode == "stock" and not frame.sensor_enabled
afc.state = True
for a in (a1, a2):
    a._sync_bypass()
assert frame.sensor_enabled and frame.runout_distance == 770.0
assert frame.runout_gcode.render().endswith("\nPAUSE")
frame.filament_present = True  # refilled within the runout distance
assert frame.runout_gcode.render() == ""
afc.state = False
for a in (a1, a2):
    a._sync_bypass()
assert (frame.runout_gcode, frame.runout_distance, frame.sensor_enabled) == ("stock", 0, False)
assert not hasattr(frame, "_afc_ace_saved")

t, ext, fila = bypass_unit("toolhead", afc, frame)
afc.state = True
t._sync_bypass()
assert ext.enable_runout and ext.enable_runout_in_bypass and fila.runout_helper.sensor_enabled
afc.state = False
t._sync_bypass()
assert not (ext.enable_runout or ext.enable_runout_in_bypass or fila.runout_helper.sensor_enabled)


# AFC_ACE_BYPASS: unloads a loaded lane first, refuses mid-print and while
# the bypass spool is still in the path sensor
def run_bypass(enable, current=None, printing=False, present=False):
    frame.filament_present, afc.current, afc.printing = present, current, printing
    del scripts[:]

    def script(s):
        scripts.append(s)
        if s == "TOOL_UNLOAD":
            afc.current = None
        if s.startswith("SET_FILAMENT_SENSOR"):
            afc.state = s.endswith("1")
    a1.gcode = types.SimpleNamespace(run_script_from_command=script)
    gcmd = types.SimpleNamespace(get_int=lambda k, d, **kw: d if enable is None else enable,
                                 respond_info=lambda m: None,
                                 error=GcmdError)
    try:
        a1.cmd_AFC_ACE_BYPASS(gcmd)
    except GcmdError as e:
        return str(e)
    return scripts


afc.state = False
assert run_bypass(1, current="lane2") == ["TOOL_UNLOAD", "SET_FILAMENT_SENSOR SENSOR=virtual_bypass ENABLE=1"]
assert frame.sensor_enabled  # applied at once, not at the next poll
assert "still in the path sensor" in run_bypass(0, present=True)
assert run_bypass(None) == ["SET_FILAMENT_SENSOR SENSOR=virtual_bypass ENABLE=0"]  # toggles
assert not frame.sensor_enabled
assert "Not during a print" in run_bypass(1, printing=True)
print("ok")
