# cosmoace_afc

Anycubic ACE Pro as a native [AFC](https://github.com/ArmoredTurtle/AFC-Klipper-Add-On)
unit on [COSMOS](https://github.com/OpenCentauri/cosmos), for the Elegoo
Centauri Carbon 1 and 2.

> **Work in progress.** The ACE is not supported by AFC upstream, and this
> driver is not part of AFC or reviewed by its developers. Parts of it have
> not run on hardware yet (see [Status](#status)). Watch the first loads and
> toolchanges closely.

COSMOS ships AFC in its image. This adds the ACE Pro as an AFC unit type, so
the ACE gets everything AFC offers: `T0`–`T7` toolchanges, endless spool,
Spoolman, `AFC_STATS`, lane colors and materials synced to OrcaSlicer, and
the AFC panels in Mainsail, Fluidd and grumpyscreen. The driver registers
itself with AFC on import; no AFC file is edited.

It replaces [CosmoACE](https://github.com/shawn-makes-stuff/cosmoace-integration),
the shell-macro version. The two cannot run together.

## Contents

- [Supported setups](#supported-setups)
- [Requirements](#requirements)
- [Install](#install)
- [Configuration](#configuration)
- [Slicer](#slicer)
- [Using it](#using-it)
- [How loads and unloads work](#how-loads-and-unloads-work)
- [Status](#status)
- [Credits and license](#credits-and-license)

## Supported setups

The ACE feeds the printer along one of two paths. Each lane homes on exactly
one sensor:

| Path | ACE tubes go to | Feeds home on |
|---|---|---|
| **Runout sensor** | a hub adapter on the printer's frame runout sensor | the frame sensor, then a blind push to the extruder gears |
| **Toolhead sensor** | a filament merger on the toolhead | the sensor just before the extruder gears |

Both paths work on both machines:

| | Centauri Carbon 1 | Centauri Carbon 2 |
|---|---|---|
| Runout sensor | `PC0`, from COSMOS's machine config | the serial filament sensor board, from COSMOS's machine config; its jam encoder stays active |
| Toolhead sensor | the CANVAS toolhead kit, sensor `hotend:PB2` | stock toolhead, sensor `hotend:PB1` |

One ACE gives 4 lanes; a second ACE chained into the first gives 8.

## Requirements

- A Centauri Carbon 1 or 2 on a COSMOS build with Klipper plugins
  (`/etc/klipper/plugins`, from October 2026).
- `elegoo_canvas = False` in `cosmos.conf`, also with the CANVAS toolhead:
  that setting loads COSMOS's config for the CANVAS unit itself.
- CosmoACE removed (run its `uninstall.sh`). Both define `T0`–`T3` and both
  want the ACE's serial port.
- An Anycubic ACE Pro, or an ACE 2 Pro (experimental, see
  [ACE 2 Pro](#ace-2-pro)).

### Hardware

- **ACE Pro cable:** pins 3 and 4 on the 4-pin end of the ACE cable must be
  swapped, by modifying the cable or with an adapter. The USB end goes into
  one of the printer's USB ports.
- **Runout sensor path:** a filament hub adapter on the Centauri's runout
  sensor, for example
  [this one](https://www.printables.com/model/1820714-anycubic-filament-hub-to-elegoo-centauri-carbon-fi).
- **Toolhead sensor path:** a merger on the toolhead taking the ACE's tubes.
  On a CC1 that means the CANVAS toolhead kit.

## Install

### With the COSMOS addon manager

COSMOS's addon manager (`addon`) is not merged yet
([OpenCentauri/cosmos#424](https://github.com/OpenCentauri/cosmos/pull/424)).
Once it is, and this addon is in its list:

```sh
addon install cosmoace-afc
```

### By hand, until then

This does the same as the addon manager: a git clone into Klipper's plugin
folder. Over SSH (`root`, empty password):

```sh
git clone https://github.com/shawn-makes-stuff/cosmoace_afc /etc/klipper/plugins/AFC_ACE
```

The folder must be named `AFC_ACE`: Kalico loads a plugin by the name of its
config section. To update: `git -C /etc/klipper/plugins/AFC_ACE pull`.

### Then, either way

Add **one** line to `printer.cfg`, below `[include klipper-readonly/*.cfg]`,
for your machine and path:

| | Runout sensor | Toolhead sensor |
|---|---|---|
| CC1 | `[include ../plugins/AFC_ACE/config/cc1-runout.cfg]` | `[include ../plugins/AFC_ACE/config/cc1-toolhead.cfg]` |
| CC2 | `[include ../plugins/AFC_ACE/config/cc2-runout.cfg]` | `[include ../plugins/AFC_ACE/config/cc2-toolhead.cfg]` |

Then restart Klipper from SSH with `/etc/init.d/klipper restart`. A gcode
`RESTART` keeps the old driver code loaded. The console shows AFC's `PREP`
output; `AFC_ACE_STATUS UNIT=ACE_1` prints the ACE's raw status.

### Removing it

Delete the include line, then `addon remove cosmoace-afc` or
`rm -rf /etc/klipper/plugins/AFC_ACE`, and restart Klipper. AFC keeps its lane
data in `AFC.var`.

### Coming from the old `extras/AFC` driver in cosmoace-integration

That version mounted an overlay over Klipper's extras folder. Kalico refuses
to start when the driver is found in both places, so first remove
`/etc/init.d/afc-ace-extras` and `/etc/rc*.d/S93afc-ace-extras`, reboot, and
delete the old includes plus `afc-ace.cfg` / `afc-ace-macros.cfg` from the
config folder.

## Configuration

Never edit the files in the plugin folder: updates replace them. Put your own
values in `printer.cfg`, **below** the include. A repeated section only
changes the keys you give:

```ini
[AFC_hub ACE_1]
afc_bowden_length: 805

[AFC_ACE ACE_1]
serial: /dev/serial/by-path/platform-4200000.usb-usb-0:1.4.3:1.0
```

### The ACE's serial port

`serial: auto` (the default) finds the ACE by its USB product string. Pin a
port only if that picks the wrong unit, and use a `/dev/serial/by-path/`
name: `ttyACM` numbering changes between boots.

### Runout sensor path: the bowden length

`afc_bowden_length` on `[AFC_hub ACE_1]` is the one number to tune: the blind
push from the frame sensor to just short of the extruder gears. The shipped
810 is 5 mm short of the 815 mm measured on a CC1. It has not been measured
on a CC2. `tool_stn` (5) then pushes the last few mm with the extruder
turning, and the purge pulls the filament on to the nozzle.

- Too short: the gears never grab the filament (dry purge, air on the first
  layer).
- Too long: the ACE pushes filament into gears that are not turning.

To measure it, push a lane to the gears by hand, then retract it with one long
`LANE_MOVE` plus short steps until the sensor clears. Subtract about 1 mm per
command (see [Status](#status)). Tune it live with
`SET_BOWDEN_LENGTH HUB=ACE_1 LENGTH=+10`, then write the value into
`printer.cfg`.

### Toolhead sensor path

The lengths are COSMOS's own CANVAS values for that toolhead. `dist_hub` on
each lane (500) is the tube length from the ACE slot to the merger; it must
not be longer than the real tube (see
[How loads and unloads work](#how-loads-and-unloads-work)).

### A second ACE

Chain it into the first unit's spare USB port. Copy the commented
`[AFC_ACE ACE_2]` and `lane5`–`lane8` block from
[`config/afc-ace.cfg`](config/afc-ace.cfg) into `printer.cfg` and uncomment
it. The filament path needs a hub or merger with eight inputs. A second unit
has had far less testing than a single one.

### ACE 2 Pro

**Untested on hardware.** The ACE 2 Pro speaks a different protocol
(protobuf over RS-485). The driver supports it from the published reverse
engineering; see [`docs/ACE2_PROTOCOL.md`](docs/ACE2_PROTOCOL.md) for the
sources and what is still open. To try it:

```ini
[AFC_ACE ACE_1]
protocol: ace2
```

- It needs Anycubic's KS1/K3 ACE 2 conversion cable (RS-485 to USB, USB id
  `1a86:55d3`) in a printer USB port. `serial: auto` finds that cable.
- Several ACE 2 units chain on one bus through that one cable. Each gets its
  own `[AFC_ACE]` section with the same `serial:`; `unit_index` orders them
  by hardware ID (0 = lowest), not by where they are plugged in. Swap the
  `unit_index` values if two units come up the wrong way round.
- RFID: the ACE 2 reads a tag only once the spool turns, so a tagged spool's
  material and color can appear after the first feed, not at insert.
- `AFC_ACE_STATUS` prints the ACE 2 status in the same layout as the ACE Pro's.

### Main settings

| Section | Key | Default | What |
|---|---|---|---|
| `[AFC_ACE ACE_1]` | `protocol` | `ace1` | `ace1` = ACE Pro, `ace2` = ACE 2 Pro |
| | `serial` | `auto` | ACE serial port (ACE 2: the conversion cable) |
| | `unit_index` | `0` | which ACE: 0 = plugged into the printer, 1 = chained (ACE 2: by hardware ID) |
| | `feed_speed` / `retract_speed` | `50` / `75` | ACE speeds, mm/s |
| | `hub_clear_mm` | `110` runout / `65` toolhead | park distance behind the sensor after an unload |
| | `sensor_approach_mm` / `_speed` | `30` / `15` | slow final approach to the toolhead sensor |
| | `sync_load_mm` | all of `tool_stn` / `8` | how much the ACE pushes together with the extruder |
| | `optional` | `False` | an absent unit is reported, not a startup failure |
| | `monitor_only` | `False` | status, RFID and dryer only; filament motion is refused |
| | `dryer_temp` / `dryer_duration` | `45` / `240` | dryer defaults, °C / minutes |
| | `bypass_runout_distance` | `770` | runout path, bypass: mm printed after the frame sensor clears before the pause |
| `[AFC_hub ACE_1]` | `afc_bowden_length` | `810` runout / `8` toolhead | see above |
| `[AFC_lane laneN]` | `dist_hub` | `1200` runout / `500` toolhead | ACE slot to the sensor (runout) or merger (toolhead) |

## Slicer

OrcaSlicer start gcode, in place of your `PRINT_START` line:

```
M400
PRINT_START EXTRUDER=[nozzle_temperature_initial_layer] BED=[bed_temperature_initial_layer_single] CHAMBER=0 TOOL={initial_extruder}
```

COSMOS's `PRINT_START` loads `T{TOOL}` itself when AFC is present.

Change filament gcode:

```
T{next_extruder} PURGE_LENGTH={flush_length}
```

Purges use COSMOS's `PURGE` over the tray (200 mm by default, in 100 mm
rounds); the shipped copy only adds a move to the tray before heating a cold
nozzle. Lane colors and materials are published to OrcaSlicer's
"Synchronize filament list" through AFC.

## Using it

Standard AFC commands work on ACE lanes: `T0`–`T7`, `CHANGE_TOOL`,
`TOOL_LOAD`, `TOOL_UNLOAD`, `LANE_MOVE`, `SET_COLOR`, `SET_MATERIAL`,
`SET_MAP`. The driver adds:

| Command | What |
|---|---|
| `AFC_ACE_STATUS UNIT=ACE_1` | print the ACE's raw status |
| `AFC_ACE_DRYER_START UNIT=ACE_1 [TEMP=45] [DURATION=240] [FAN_SPEED=7000]` | run the ACE's timed dry cycle |
| `AFC_ACE_DRYER_STOP UNIT=ACE_1` | stop it |
| `AFC_ACE_STOP UNIT=ACE_1 LANE=lane1` | stop all ACE motion for a lane |
| `AFC_ACE_RESET UNIT=ACE_1 LANE=lane1` | retract a lane until its sensor clears and park it |
| `AFC_ACE_PANEL ACTION=INSTALL` / `REMOVE` | add or remove the optional ACE Pro Mainsail panel |
| `AFC_ACE_BYPASS [ENABLE=0\|1]` | feed a spool directly, bypassing the ACE (see [Bypass](#bypass-a-spool-fed-straight-in)) |

- **Dryer:** also shows as a heater (`ace_dryer_ACE_1`) in any UI's
  temperature list. A dry cycle runs its full duration; `TURN_OFF_HEATERS`
  does not stop it.
- **RFID:** an Anycubic RFID spool sets its lane's material and color when
  inserted.
- **Spool runs out:** the ACE reports the slot empty, the tail is printed
  out, and AFC's endless spool switches to the lane's runout lane once the
  tail passes the sensor.
- **Filament breaks** (spool still in its slot, sensor empty): AFC's
  break/jam pause, on either path. On a CC2 with the runout sensor path,
  COSMOS's encoder also pauses on a jam.
- **A lane stuck mid-path:** `AFC_ACE_RESET`. `AFC_RESET` refuses when no lane
  is loaded in the toolhead, so call the driver's command directly.

### Bypass: a spool fed straight in

To print from a spool without the ACE (a material it can't feed, a quick
test), turn bypass on: click **AFC_ACE_BYPASS_ON** in Mainsail's macro panel,
or send `AFC_ACE_BYPASS ENABLE=1`.

1. A loaded lane is unloaded first (AFC refuses bypass while one is loaded).
2. AFC's virtual bypass turns on: AFC loads and changes no lanes. A `T`
   command, including the one COSMOS's `PRINT_START` sends, is skipped with
   a message and the print goes on with the bypass spool.
3. The path sensor gets its runout protection back:
   - frame runout sensor path: COSMOS's stock behaviour, a `PAUSE` 770 mm
     (`bypass_runout_distance`) after the sensor clears;
   - toolhead sensor path: AFC's toolhead runout pause.

Then take the spool's tube to the path sensor (the frame sensor, or the
toolhead merger) and load it with `LOAD_FILAMENT`.

To go back: unload the spool (`UNLOAD_FILAMENT`, which runs COSMOS's manual
unload while bypass is on), then **AFC_ACE_BYPASS_OFF** or
`AFC_ACE_BYPASS ENABLE=0`. It refuses while the path sensor still sees
filament. `AFC_ACE_BYPASS` without `ENABLE` toggles. Both refuse during a
print.

Bypass survives a restart (AFC saves it). The `virtual_bypass` switch in
Mainsail's sensor list is the same switch: flipping it there works too, but
skips the unload and the check above. The ACE itself stays connected (status,
RFID and dryer keep working); it just isn't asked to move filament.

### Mainsail panel

Mainsail's own AFC panel works as it is and stays the default.

[`webui/`](webui) also holds an optional "ACE Pro" dashboard panel: a spool
per lane, the active lane, a color-wheel editor for manual spools and a dryer
control per unit. Nothing installs it automatically. To add it, either:

- in Mainsail's macro panel, click **AFC_ACE_PANEL_INSTALL** (or send
  `AFC_ACE_PANEL ACTION=INSTALL` from the console), or
- over SSH: `sh /etc/klipper/plugins/AFC_ACE/webui/setup-panel.sh install`.

Then reload the browser and turn the panel on in Settings > Dashboard.
**AFC_ACE_PANEL_REMOVE** (or `setup-panel.sh remove`) takes it out and puts
Mainsail back to stock. After a driver update, run the install again to pick
up a newer panel.

On COSMOS builds without the Mainsail Panel Extender, the install also adds a
small loader and a boot script (`/etc/init.d/afc-ace-webui`). They are removed
with the panel unless another addon panel still uses them.

## How loads and unloads work

**Runout sensor path**

1. The ACE feeds until the frame sensor sees the filament (`dist_hub` is only
   a limit).
2. It pushes `afc_bowden_length` blind, to just short of the gears.
3. The ACE and the extruder push `tool_stn` together to thread the gears,
   then feed assist turns on and the purge pulls the filament to the nozzle.

An unload cuts, the extruder pulls the filament out of the gears, and the ACE
retracts until the frame sensor clears, then parks `hub_clear_mm` behind it.

**Toolhead sensor path**

1. Cold, before the hotend heats: a lane parked by its last unload is found
   with a slow feed. A first load from the slot runs fast for `dist_hub`
   minus `sensor_approach_mm`, then slowly until the sensor sees the
   filament. If `dist_hub` is longer than the real tube, the sensor is
   reached at full speed and a warning is logged.
2. When hot: the ACE pushes `sync_load_mm` with the extruder turning, then
   the extruder pulls the rest of `tool_stn` with feed assist on.

An unload cuts, the extruder pulls `tool_stn_unload` out of the gears, and the
ACE retracts until the sensor clears, then parks `hub_clear_mm` behind it,
clear of the merger.

Every unload retract is capped at `afc_unload_bowden_length` (or
`afc_bowden_length`) + `tool_stn` + `hub_clear_mm`. Unwinding further would
run the filament out of the ACE.

## Status

| | |
|---|---|
| CC1, runout sensor path | ran on an earlier version (PREP, RFID, loads, toolchanges, dryer); this version not yet run |
| CC1, toolhead sensor path | not run on hardware |
| CC2, either path | not run on hardware |
| Install as a Klipper plugin | not run on hardware |
| Mainsail panel | optional, `AFC_ACE_PANEL ACTION=INSTALL`; install script not run on hardware |
| Bypass (`AFC_ACE_BYPASS`) | not run on hardware; checked against AFC and Kalico source |
| ACE 2 Pro | written from the reverse engineering, tested only against a simulated unit; not run on hardware |

Known issues:

- **About 1 mm lost per ACE move command**, whatever its length. One long
  move is accurate; a sum of short `LANE_MOVE` steps is not.
- **The ACE drops its USB link** about 3.5 s after the last message it
  received. The driver keeps it alive, so nothing else may hold the port.
- **Toolhead path `tool_stn`:** 51.5 (COSMOS's 8 synced + 43.5) is not yet
  confirmed.
- **Feed assist overfeed:** once, during a purge with feed assist on, the ACE
  kept pushing and a PTFE tube popped; see
  [`docs/FEED_ASSIST_INCIDENT.md`](docs/FEED_ASSIST_INCIDENT.md).

Checks in the repo, runnable on a computer:

```sh
python tools/check_configs.py <path to a COSMOS checkout>   # resolves all four entry configs
python tools/test_driver.py                                 # driver logic with AFC stubbed
python tools/test_ace2.py                                   # ACE 2 transport, simulated units
```

## Credits and license

- ACE protocol knowledge from
  [printers-for-people/ACEResearch](https://github.com/printers-for-people/ACEResearch)
  and CosmoACE.
- ACE 2 Pro support ports code from
  [Kobra-S1/ACEPRO](https://github.com/Kobra-S1/ACEPRO) (GPL-3.0), and rests on
  the reverse engineering of [hakimio](https://gist.github.com/hakimio/4916ff69add458fdc51aeea76f21efb9),
  [Simon-CR](https://github.com/Simon-CR/ace2-pro-firmware-research),
  [multiACE](https://github.com/decay71/multiACE) and
  [ace2k](https://github.com/tobecwb/ace2k). Details in
  [`docs/ACE2_PROTOCOL.md`](docs/ACE2_PROTOCOL.md).
- Built on [AFC](https://github.com/ArmoredTurtle/AFC-Klipper-Add-On) by
  ArmoredTurtle, and the COSMOS AFC fork by suchmememanyskill.

GPL-3.0, the same license as AFC. See [LICENSE](LICENSE).
