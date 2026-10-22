"""[AFC_ACE] setup end to end, through a stand-in for Kalico's config loader
and AFC's unit and lane classes: units made per ACE, lanes made per unit,
defaults inherited, your own unit/lane sections as overrides, old explicit
configs unchanged, and Kalico's unused-option check.

  python tools/test_setup.py <cosmos checkout>
"""
import configparser
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import check_configs  # noqa: E402  (its resolver reads the shipped configs)


class ConfigError(Exception):
    pass


class Wrapper:
    """Kalico's ConfigWrapper as the driver and AFC use it: reads mark the
    option accessed; a missing option with a default is not marked."""

    def __init__(self, printer, fileconfig, access, section):
        self.printer, self.fileconfig, self.access, self.section = printer, fileconfig, access, section
        self.error = ConfigError

    def get_printer(self):
        return self.printer

    def get_name(self):
        return self.section

    def getsection(self, section):
        return Wrapper(self.printer, self.fileconfig, self.access, section)

    def _get(self, option, default, parse):
        if not self.fileconfig.has_option(self.section, option):
            if default is KeyError:
                raise ConfigError(f"Option '{option}' in section '{self.section}' must be specified")
            return default
        value = parse(self.fileconfig.get(self.section, option).split("#")[0].strip())
        self.access.add((self.section.lower(), option.lower()))
        return value

    def get(self, option, default=KeyError):
        return self._get(option, default, str)

    def getint(self, option, default=KeyError, **kw):
        return self._get(option, default, lambda v: int(float(v)))

    def getfloat(self, option, default=KeyError, **kw):
        return self._get(option, default, float)

    def getboolean(self, option, default=KeyError):
        return self._get(option, default, lambda v: v.lower() in ("1", "true", "yes", "on"))

    def getchoice(self, option, choices, default=KeyError):
        value = self.get(option, default)
        if value not in choices:
            raise ConfigError(f"Choice '{value}' for option '{option}' is not valid")
        return choices[value]


class Printer:
    """Kalico's load_object/add_object: an existing object is returned, the
    module's load_config / load_config_prefix builds a missing one and its
    result is stored under the section name."""

    def __init__(self, fileconfig):
        self.fileconfig, self.access, self.objects = fileconfig, set(), {}
        self.modules = {}

    def config(self):
        return Wrapper(self, self.fileconfig, self.access, "printer")

    def add_object(self, name, obj):
        if name in self.objects:
            raise ConfigError(f"Printer object '{name}' already created")
        self.objects[name] = obj

    def lookup_object(self, name, default=None):
        return self.objects.get(name, default)

    def load_object(self, config, section, default=KeyError):
        if section in self.objects:
            return self.objects[section]
        module = section.split()[0]
        if module not in self.modules:
            self.objects[section] = Stub()
            return self.objects[section]
        mod = self.modules[module]
        init = mod.load_config if section == module else mod.load_config_prefix
        self.objects[section] = init(config.getsection(section))
        return self.objects[section]

    def register_event_handler(self, *a):
        pass

    def unused_options(self):
        return [(s, o) for s in self.fileconfig.sections() for o in self.fileconfig.options(s)
                if s.startswith(("AFC_ACE", "AFC_lane ")) and (s.lower(), o.lower()) not in self.access]


class Stub:
    """Anything the driver asks Klipper or AFC for that this test ignores."""

    def __init__(self):
        self.heaters, self.available_heaters, self.available_sensors = {}, [], []

    def __getattr__(self, name):
        return lambda *a, **k: None


class FakeUnit:
    """afcUnit's constructor as far as config goes: the keys it reads."""

    def __init__(self, config):
        self.printer = config.get_printer()
        self.name = config.get_name().split()[-1]
        self.gcode = Stub()
        self.afc = self.printer.load_object(config, "AFC")
        for key in ("screen_mac", "hub", "extruder", "buffer"):
            setattr(self, key, config.get(key, None))
        self.lanes = {}


BUILT_LANES = []


class FakeLane:
    """AFC_lane's constructor: reads its keys and, like _get_steppers, loads
    its unit object right away (that is what makes the build order matter)."""

    def __init__(self, config):
        self.name = config.get_name().split()[-1]
        self.unit_ref = config.get("unit")
        self.map = config.get("map", None)
        self.load_to_hub = config.get("load_to_hub", None)
        self.dist_hub = config.getfloat("dist_hub", 60.0)
        for key in ("hub", "extruder", "buffer"):
            config.get(key, None)
        unit = self.unit_ref.split(":")[0]
        section = next(s for s in config.fileconfig.sections()
                       if s.startswith("AFC_") and s.split()[-1] == unit and not s.startswith("AFC_lane"))
        self.unit_obj = config.get_printer().load_object(config, section)
        BUILT_LANES.append(self)


def stub(name, **attrs):
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    sys.modules[name] = mod
    return mod


stub("extras")
stub("extras.AFC_utils", ERROR_STR="{import_lib} {trace}")
lane_mod = stub("extras.AFC_lane", AFCLaneState=types.SimpleNamespace(), ONLY_LOAD_TYPES=[],
                EXCLUDE_TYPES=[], load_config_prefix=lambda config: FakeLane(config))
stub("extras.AFC_unit", afcUnit=FakeUnit)
stub("extras.AFC_OpenAMS", _ams_box_logo=None, _ams_box_logo_error=None)
sys.path.insert(0, ROOT)
import AFC_ACE  # noqa: E402

AFC_ACE.error = ConfigError
lane_mod.AFCLane = FakeLane
AFC_ACE._afc_lane_mod = lane_mod


def boot(sections, found=1):
    """Load `sections` ({name: {key: value}} in file order) the way Kalico's
    startup loop does: each section in order, skipping built objects."""
    BUILT_LANES.clear()
    AFC_ACE.count_ace_units = lambda protocol, port: found
    fc = configparser.RawConfigParser()
    for name, keys in sections.items():
        fc.add_section(name)
        for k, v in keys.items():
            fc.set(name, k, v)
    printer = Printer(fc)
    printer.modules = {"AFC_ACE": AFC_ACE, "AFC_lane": lane_mod}
    config = printer.config()
    for name in list(fc.sections()):  # the list is taken once, as Kalico does
        printer.load_object(config, name)
    units = {n: o for n, o in printer.objects.items() if n.startswith("AFC_ACE ")}
    lanes = {l.name: l for l in BUILT_LANES}
    assert len(BUILT_LANES) == len(lanes), "a lane was built twice"
    return printer, units, lanes


def shipped(cosmos, machine, sensor):
    """The resolved shipped config, only the sections this test loads."""
    c = check_configs.resolve(cosmos, machine, sensor)
    return {n: dict(k) for n, k in c.items() if n.startswith(("AFC_ACE", "AFC_lane "))}


def main():
    cosmos = sys.argv[1]

    # 1. Two ACE Pros found, CC1 toolhead path, the user's own overrides
    cfg = shipped(cosmos, "cc1", "toolhead")
    assert "AFC_ACE" in cfg and not any(n.startswith("AFC_lane") for n in cfg), cfg.keys()
    cfg["AFC_ACE ACE_1"] = {"serial": "/dev/serial/by-path/ace1"}
    cfg["AFC_lane lane1"] = {"dist_hub": "800"}
    printer, units, lanes = boot(cfg, found=2)
    assert sorted(units) == ["AFC_ACE ACE_1", "AFC_ACE ACE_2"], units
    a1, a2 = units["AFC_ACE ACE_1"], units["AFC_ACE ACE_2"]
    assert (a1.serial_port, a1.ace_unit_index, a1.optional) == ("/dev/serial/by-path/ace1", 0, False)
    assert (a2.serial_port, a2.ace_unit_index, a2.optional) == ("auto", 1, True)
    for u in (a1, a2):  # the toolhead path's head values reach both units
        assert (u.protocol, u.hub, u.extruder, u.hub_clear_mm, u.sync_load_mm, u.purge_park_cmd) == \
            ("ace1", "ACE_1", "extruder", 65.0, 8.0, "_AFC_ACE_PURGE_SPOT"), vars(u)
    assert sorted(lanes) == [f"lane{n}" for n in range(1, 9)], sorted(lanes)
    for n in range(1, 9):
        lane = lanes[f"lane{n}"]
        assert lane.unit_ref == f"ACE_{(n - 1) // 4 + 1}:{(n - 1) % 4 + 1}", lane.unit_ref
        assert lane.map == f"T{n - 1}" and lane.load_to_hub == "False"
        assert lane.dist_hub == (800.0 if n == 1 else 500.0), (n, lane.dist_hub)
        assert lane.unit_obj is units[f"AFC_ACE ACE_{(n - 1) // 4 + 1}"]
    assert printer.unused_options() == [], printer.unused_options()

    # 2. Nothing found at startup: still one unit, runout path values
    printer, units, lanes = boot(shipped(cosmos, "cc2", "runout"), found=0)
    assert list(units) == ["AFC_ACE ACE_1"] and sorted(lanes) == ["lane1", "lane2", "lane3", "lane4"]
    u = units["AFC_ACE ACE_1"]
    assert (u.hub_sensor_name, u.hub_clear_mm) == ("filament_sensor", 110.0)
    assert all(l.dist_hub == 1200.0 for l in lanes.values())
    assert printer.unused_options() == [], printer.unused_options()

    # 3. units: 2 fixed, ACE 2 Pro: no count, both units on the bus port
    cfg = shipped(cosmos, "cc1", "runout")
    cfg["AFC_ACE"].update({"ace": "2pro", "units": "2", "serial": "/dev/ttyACM9"})
    AFC_ACE_count = AFC_ACE.count_ace_units
    printer, units, lanes = boot(cfg, found=99)
    assert sorted(units) == ["AFC_ACE ACE_1", "AFC_ACE ACE_2"], "units: 2 must not count"
    assert all(u.protocol == "ace2" and u.serial_port == "/dev/ttyACM9" for u in units.values())
    assert printer.unused_options() == [], printer.unused_options()

    # 4. The old explicit style (no [AFC_ACE]): unchanged, no extra lanes
    old = {"AFC_ACE ACE_1": {"serial": "auto", "hub": "ACE_1", "extruder": "extruder"}}
    for n in range(1, 5):
        old[f"AFC_lane lane{n}"] = {"unit": f"ACE_1:{n}", "map": f"T{n - 1}",
                                    "dist_hub": "500", "load_to_hub": "False"}
    printer, units, lanes = boot(old)
    assert list(units) == ["AFC_ACE ACE_1"] and sorted(lanes) == ["lane1", "lane2", "lane3", "lane4"]
    assert all(l.unit_obj is units["AFC_ACE ACE_1"] for l in lanes.values())
    # ... also with the lanes before the unit in the file
    printer, units, lanes = boot({**{k: v for k, v in old.items() if k != "AFC_ACE ACE_1"},
                                  "AFC_ACE ACE_1": old["AFC_ACE ACE_1"]})
    assert len(units) == 1 and len(lanes) == 4

    # 5. A lane named for another unit's slot is refused, not silently shared
    cfg = shipped(cosmos, "cc1", "toolhead")
    cfg["AFC_lane lane1"] = {"unit": "ACE_9:1"}
    try:
        boot(cfg)
    except ConfigError as exc:
        assert "lane1" in str(exc)
    else:
        raise AssertionError("conflicting lane1 accepted")
    print("ok")


if __name__ == "__main__":
    main()
