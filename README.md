# cosmoace_afc

The Anycubic ACE Pro as a native [AFC](https://github.com/ArmoredTurtle/AFC-Klipper-Add-On)
unit on [COSMOS](https://github.com/OpenCentauri/cosmos), for the Elegoo
Centauri Carbon 1 and 2. The ACE gets everything AFC offers: `T0`–`T7`
toolchanges, endless spool, Spoolman, OrcaSlicer filament sync, and the AFC
panels in Mainsail, Fluidd and grumpyscreen. ACE 2 Pro support is
experimental.

> **Work in progress.** Not part of AFC, and much of it has not run on
> hardware yet (see [Status](#status)). Watch your first loads.

Replaces [CosmoACE](https://github.com/shawn-makes-stuff/cosmoace-integration).
Uninstall that first: both want the ACE's port.

## Hardware

Pick a filament path. Each lane homes on one sensor:

| Path | ACE tubes go to | CC1 | CC2 |
|---|---|---|---|
| **Runout sensor** | a hub adapter on the frame runout sensor | ✓ | ✓ |
| **Toolhead sensor** | a merger on the toolhead | with the CANVAS toolhead kit | stock |

<img width="320" alt="Filament hub adapter on the Centauri Carbon's runout sensor" src="https://github.com/user-attachments/assets/08e2b6c4-4dfd-4131-bc70-6a60aec7596f" />

*Runout sensor path: [hub adapter](https://www.printables.com/model/1820714-anycubic-filament-hub-to-elegoo-centauri-carbon-fi) on the frame sensor.*

- **ACE Pro:** swap pins 3 and 4 on the 4-pin end of its cable (or use an
  adapter), and plug the USB end into the printer. A second ACE chains into
  the first for 8 lanes.
- **ACE 2 Pro:** Anycubic's KS1/K3 RS-485-to-USB cable. Each tube from the ACE
  to the hub or merger must be **longer than 750 mm**: the ACE 2 feeds a newly
  inserted spool up to that far by itself.

## Install

COSMOS with Klipper plugins (October 2026 or newer) and
`elegoo_canvas = False` in `cosmos.conf`. Over SSH (`root`, no password):

```sh
git clone https://github.com/shawn-makes-stuff/cosmoace_afc /etc/klipper/plugins/AFC_ACE
```

Then add one line to `printer.cfg`, below `[include klipper-readonly/*.cfg]`:

| | Runout sensor | Toolhead sensor |
|---|---|---|
| CC1 | `[include ../plugins/AFC_ACE/config/cc1-runout.cfg]` | `[include ../plugins/AFC_ACE/config/cc1-toolhead.cfg]` |
| CC2 | `[include ../plugins/AFC_ACE/config/cc2-runout.cfg]` | `[include ../plugins/AFC_ACE/config/cc2-toolhead.cfg]` |

and restart: `/etc/init.d/klipper restart` (a gcode `RESTART` keeps the old
code loaded).

- **Update:** `git -C /etc/klipper/plugins/AFC_ACE pull`, then restart.
- **Remove:** delete the include line and the folder, then restart.
- **From the old `extras/AFC` overlay:** delete `/etc/init.d/afc-ace-extras`
  and `/etc/rc*.d/S93afc-ace-extras`, reboot, and drop its includes.

## Configuration

Don't edit the plugin folder: updates replace it. Override in `printer.cfg`,
below the include. A repeated section only changes the keys you give.

```ini
[AFC_hub ACE_1]
afc_bowden_length: 805     # runout path: frame sensor to just short of the gears

[AFC_ACE ACE_1]
protocol: ace2             # an ACE 2 Pro
```

- **Runout path:** tune `afc_bowden_length` (810 shipped; 815 mm measured on
  a CC1). Too short: the gears never grab and the purge runs dry. Too long: the
  ACE pushes into stopped gears. Live: `SET_BOWDEN_LENGTH HUB=ACE_1 LENGTH=+10`.
- **Toolhead path:** `dist_hub` on each lane must not be longer than the
  real tube from the slot to the merger.
- **Second ACE:** copy the commented `ACE_2` block from
  [`config/afc-ace.cfg`](config/afc-ace.cfg) into `printer.cfg`. ACE 2 units
  share one cable; `unit_index` orders them by hardware ID.

| `[AFC_ACE]` key | Default | |
|---|---|---|
| `protocol` | `ace1` | `ace2` for an ACE 2 Pro |
| `serial` | `auto` | pin a `/dev/serial/by-path/` port if auto picks wrong |
| `unit_index` | `0` | which ACE: 0 = plugged in, 1 = chained |
| `feed_speed` / `retract_speed` | `50` / `75` | mm/s |
| `hub_clear_mm` | `110` / `65` | park distance behind the sensor after an unload |
| `optional` | `False` | a missing unit is reported, not a failure |
| `monitor_only` | `False` | status, RFID and dryer only, no motion |
| `dryer_temp` / `dryer_duration` | `45` / `240` | °C / minutes |
| `bypass_runout_distance` | `770` | runout path, bypass: mm printed after the sensor clears before pausing |

## OrcaSlicer

| | |
|---|---|
| Start gcode | `PRINT_START EXTRUDER=[nozzle_temperature_initial_layer] BED=[bed_temperature_initial_layer_single] CHAMBER=0 TOOL={initial_extruder}` |
| Change filament gcode | `T{next_extruder} PURGE_LENGTH={flush_length}` |

## Commands

AFC's commands work on ACE lanes (`T0`, `TOOL_LOAD`, `TOOL_UNLOAD`,
`SET_COLOR`, ...). The driver adds:

| Command | |
|---|---|
| `AFC_ACE_STATUS UNIT=ACE_1` | raw ACE status |
| `AFC_ACE_DRYER_START UNIT=ACE_1 [TEMP=] [DURATION=]` | start the dryer (also a heater in the UI) |
| `AFC_ACE_DRYER_STOP UNIT=ACE_1` | stop it |
| `AFC_ACE_STOP UNIT=ACE_1 LANE=lane1` | stop all motion on a lane |
| `AFC_ACE_RESET UNIT=ACE_1 LANE=lane1` | retract a stuck lane clear of the sensor |
| `AFC_ACE_BYPASS [ENABLE=0\|1]` | print from a spool fed straight in |
| `AFC_ACE_PANEL ACTION=INSTALL\|REMOVE` | optional ACE Mainsail panel |

**Bypass** (also the `AFC_ACE_BYPASS_ON` / `_OFF` macros) unloads the loaded
lane, tells AFC to leave the lanes alone, and turns runout pausing back on at
the path sensor. Feed the spool in and `LOAD_FILAMENT`. To go back,
`UNLOAD_FILAMENT` first. Not during a print.

**Panel:** Mainsail's AFC panel is the default. `AFC_ACE_PANEL ACTION=INSTALL`
adds an ACE panel (spools, color editor, dryer); enable it in Settings >
Dashboard. `ACTION=REMOVE` puts Mainsail back to stock. Re-run the install
after an update.

## Status

| | |
|---|---|
| CC1, runout path | an earlier version ran on hardware; this one not yet |
| CC1 toolhead path, CC2 | not run on hardware |
| Bypass, panel install | not run on hardware |
| ACE 2 Pro | tested against a simulated unit only; see [`docs/ACE2_PROTOCOL.md`](docs/ACE2_PROTOCOL.md) |

Known issues: each ACE move command loses about 1 mm, so one long move beats
many short ones; the toolhead path's `tool_stn` (51.5) is unconfirmed; feed
assist once overfed during a purge
([`docs/FEED_ASSIST_INCIDENT.md`](docs/FEED_ASSIST_INCIDENT.md)).

Checks: `python tools/check_configs.py <cosmos checkout>`,
`python tools/test_driver.py`, `python tools/test_ace2.py`.

## Credits

ACE protocol from [ACEResearch](https://github.com/printers-for-people/ACEResearch)
and CosmoACE. ACE 2 Pro: code partly from
[Kobra-S1/ACEPRO](https://github.com/Kobra-S1/ACEPRO), research by
[hakimio](https://gist.github.com/hakimio/4916ff69add458fdc51aeea76f21efb9),
[Simon-CR](https://github.com/Simon-CR/ace2-pro-firmware-research),
[multiACE](https://github.com/decay71/multiACE) and
[ace2k](https://github.com/tobecwb/ace2k). Built on
[AFC](https://github.com/ArmoredTurtle/AFC-Klipper-Add-On) by ArmoredTurtle and
suchmememanyskill's COSMOS fork.

GPL-3.0, like AFC. See [LICENSE](LICENSE).
