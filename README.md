# cosmoace_afc

Anycubic ACE Pro (and, experimentally, ACE 2 Pro) as a native
[AFC](https://github.com/ArmoredTurtle/AFC-Klipper-Add-On) unit on
[COSMOS](https://github.com/OpenCentauri/cosmos), for the Elegoo Centauri
Carbon 1 and 2. You get AFC's toolchanges, endless spool, Spoolman, OrcaSlicer
filament sync and the AFC panels in Mainsail, Fluidd and grumpyscreen.

> **Work in progress**, not part of AFC. Much of it has not run on hardware
> (see [Status](#status)). Watch the first loads closely.

Replaces [CosmoACE](https://github.com/shawn-makes-stuff/cosmoace-integration);
uninstall that first (both want the ACE's port).

## Setups

| Path | ACE tubes go to | CC1 | CC2 |
|---|---|---|---|
| **Runout sensor** | a [hub adapter](https://www.printables.com/model/1820714-anycubic-filament-hub-to-elegoo-centauri-carbon-fi) on the frame runout sensor | ✓ | ✓ |
| **Toolhead sensor** | a merger on the toolhead | CANVAS toolhead kit | stock toolhead |

One ACE = 4 lanes, two chained = 8.

**Requirements:** COSMOS with Klipper plugins (October 2026 or later),
`elegoo_canvas = False` in `cosmos.conf`. ACE Pro: swap pins 3 and 4 on the
cable's 4-pin end. ACE 2 Pro: Anycubic's KS1/K3 RS-485-to-USB cable.

## Install

Over SSH (`root`, empty password):

```sh
git clone https://github.com/shawn-makes-stuff/cosmoace_afc /etc/klipper/plugins/AFC_ACE
```

The folder must be named `AFC_ACE`. Once COSMOS's addon manager lands, this
becomes `addon install cosmoace-afc`.

Add **one** line to `printer.cfg`, below `[include klipper-readonly/*.cfg]`:

| | Runout sensor | Toolhead sensor |
|---|---|---|
| CC1 | `[include ../plugins/AFC_ACE/config/cc1-runout.cfg]` | `[include ../plugins/AFC_ACE/config/cc1-toolhead.cfg]` |
| CC2 | `[include ../plugins/AFC_ACE/config/cc2-runout.cfg]` | `[include ../plugins/AFC_ACE/config/cc2-toolhead.cfg]` |

Restart with `/etc/init.d/klipper restart` (a gcode `RESTART` keeps old
driver code). Update: `git -C /etc/klipper/plugins/AFC_ACE pull`. Remove:
delete the include and the folder.

Coming from the old `extras/AFC` overlay: delete `/etc/init.d/afc-ace-extras`
and `/etc/rc*.d/S93afc-ace-extras`, reboot, and remove its includes.

## Configuration

Don't edit the plugin folder. Override in `printer.cfg`, below the include;
a repeated section only changes the keys you give:

```ini
[AFC_hub ACE_1]
afc_bowden_length: 805
```

**Runout path:** `afc_bowden_length` is the one number to tune, the blind
push from the frame sensor to just short of the gears (810 shipped, 815
measured on a CC1, unmeasured on a CC2). Too short: dry purge. Too long: the
ACE shoves into stopped gears. Tune live with
`SET_BOWDEN_LENGTH HUB=ACE_1 LENGTH=+10`.

**Toolhead path:** `dist_hub` (500) must not be longer than the real tube
from slot to merger.

**Second ACE:** uncomment the `ACE_2` / `lane5`–`lane8` block from
[`config/afc-ace.cfg`](config/afc-ace.cfg) into `printer.cfg`.

**ACE 2 Pro** (untested on hardware): `protocol: ace2` under `[AFC_ACE ACE_1]`.
Chained units share the one cable; `unit_index` orders them by hardware ID.
A tagged spool's RFID shows up after the spool first turns. Sources and open
questions: [`docs/ACE2_PROTOCOL.md`](docs/ACE2_PROTOCOL.md).

| `[AFC_ACE ACE_1]` key | Default | |
|---|---|---|
| `protocol` | `ace1` | `ace2` for an ACE 2 Pro |
| `serial` | `auto` | pin a `/dev/serial/by-path/` port if auto picks wrong |
| `unit_index` | `0` | which ACE: 0 = plugged in, 1 = chained |
| `feed_speed` / `retract_speed` | `50` / `75` | mm/s |
| `hub_clear_mm` | `110` / `65` | park distance behind the sensor after unload |
| `optional` | `False` | a missing unit is reported, not a failure |
| `monitor_only` | `False` | status, RFID and dryer only, no motion |
| `dryer_temp` / `dryer_duration` | `45` / `240` | °C / minutes |
| `bypass_runout_distance` | `770` | runout path, bypass: mm after the sensor clears before pausing |

## Slicer (OrcaSlicer)

Start gcode: `PRINT_START EXTRUDER=[nozzle_temperature_initial_layer] BED=[bed_temperature_initial_layer_single] CHAMBER=0 TOOL={initial_extruder}`

Change filament gcode: `T{next_extruder} PURGE_LENGTH={flush_length}`

## Commands

AFC's own commands work on ACE lanes (`T0`–`T7`, `TOOL_LOAD`, `TOOL_UNLOAD`,
`SET_COLOR`, ...). The driver adds:

| Command | |
|---|---|
| `AFC_ACE_STATUS UNIT=ACE_1` | raw ACE status |
| `AFC_ACE_DRYER_START UNIT=ACE_1 [TEMP=] [DURATION=]` / `AFC_ACE_DRYER_STOP UNIT=ACE_1` | dryer (also a heater in the UI) |
| `AFC_ACE_STOP UNIT=ACE_1 LANE=lane1` | stop all motion on a lane |
| `AFC_ACE_RESET UNIT=ACE_1 LANE=lane1` | retract a stuck lane clear of the sensor |
| `AFC_ACE_BYPASS [ENABLE=0\|1]` | feed a spool directly, see below |
| `AFC_ACE_PANEL ACTION=INSTALL\|REMOVE` | optional ACE Pro Mainsail panel, see below |

**Bypass** (`AFC_ACE_BYPASS_ON` / `_OFF` macros): unloads the loaded lane,
switches on AFC's bypass so lanes are left alone, and restores runout pausing
on the path sensor. Feed the spool in and use `LOAD_FILAMENT`. To turn it off,
`UNLOAD_FILAMENT` first. Refused during a print.

**Panel:** Mainsail's AFC panel is the default. `AFC_ACE_PANEL ACTION=INSTALL`
adds an ACE-specific panel (spools, color editor, dryer); turn it on in
Settings > Dashboard. `ACTION=REMOVE` restores stock Mainsail. Re-run the
install after updating. Over SSH: `webui/setup-panel.sh install|remove`.

## Status

| | |
|---|---|
| CC1, runout path | earlier version ran on hardware; this one not yet |
| CC1 toolhead path, CC2 | not run on hardware |
| Bypass, panel install | not run on hardware |
| ACE 2 Pro | simulated unit only |

Known issues: about 1 mm is lost per ACE move command (one long move beats
many short ones); toolhead path `tool_stn` (51.5) is unconfirmed; feed assist
once overfed during a purge
([`docs/FEED_ASSIST_INCIDENT.md`](docs/FEED_ASSIST_INCIDENT.md)).

Checks: `python tools/check_configs.py <cosmos checkout>`,
`python tools/test_driver.py`, `python tools/test_ace2.py`.

## Credits

ACE protocol from [ACEResearch](https://github.com/printers-for-people/ACEResearch)
and CosmoACE. ACE 2 Pro code partly ported from
[Kobra-S1/ACEPRO](https://github.com/Kobra-S1/ACEPRO), built on research by
[hakimio](https://gist.github.com/hakimio/4916ff69add458fdc51aeea76f21efb9),
[Simon-CR](https://github.com/Simon-CR/ace2-pro-firmware-research),
[multiACE](https://github.com/decay71/multiACE) and
[ace2k](https://github.com/tobecwb/ace2k). Built on
[AFC](https://github.com/ArmoredTurtle/AFC-Klipper-Add-On) by ArmoredTurtle
and suchmememanyskill's COSMOS fork.

GPL-3.0, like AFC. See [LICENSE](LICENSE).
