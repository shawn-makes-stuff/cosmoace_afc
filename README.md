# cosmoace_afc

Run an Anycubic ACE Pro as a multi-colour unit on an Elegoo Centauri Carbon 1
or 2 with [COSMOS](https://github.com/OpenCentauri/cosmos). It plugs the ACE
into COSMOS's built-in [AFC](https://github.com/ArmoredTurtle/AFC-Klipper-Add-On),
so you get AFC's toolchanges (`T0`–`T7`), endless spool, Spoolman, OrcaSlicer
filament sync and the AFC panels in Mainsail, Fluidd and grumpyscreen.

> **Work in progress.** Not part of AFC. See [Status](#status) for what has
> run on real hardware. Watch your first loads.

## What you need

- A Centauri Carbon 1 or 2 on COSMOS from October 2026 or newer (it needs
  Klipper plugins).
- `elegoo_canvas = False` in `cosmos.conf`, even with a CANVAS toolhead.
- One or more ACE units, either:
  - **ACE Pro:** pins 3 and 4 swapped on the 4-pin end of its cable (or an
    adapter), USB plugged into the printer. A second ACE Pro chains into the
    first for 8 colours.
  - **ACE 2 Pro** (experimental, see [Status](#status)): Anycubic's KS1/K3
    RS-485-to-USB cable, and every tube from the ACE to the hub or merger
    longer than 750 mm. Set `ace: 2pro`.
- CosmoACE removed if you had it (its `uninstall.sh`).
- A way into the printer's filament path, one of:
  - **Runout sensor path (default, CC1 and CC2):** a
    [hub adapter](https://www.printables.com/model/1820714-anycubic-filament-hub-to-elegoo-centauri-carbon-fi)
    on the printer's own filament runout sensor. No other parts.
  - **Toolhead sensor path (optional extra):** the ACE's tubes go into a
    filament merger on a toolhead with a sensor before the gears. On a CC1
    that means fitting the CANVAS toolhead kit; on a CC2 the stock toolhead
    already has the sensor.

## Setup

1. **Install** over SSH (`root`, no password):

   ```sh
   git clone https://github.com/shawn-makes-stuff/cosmoace_afc /etc/klipper/plugins/AFC_ACE
   ```

   The folder must be called `AFC_ACE`.

2. **Include the config for your setup.** In `printer.cfg`, add one line
   right below `[include klipper-readonly/*.cfg]`:

   | | Runout sensor path | Toolhead sensor path |
   |---|---|---|
   | CC1 | `[include ../plugins/AFC_ACE/config/cc1-runout.cfg]` | `[include ../plugins/AFC_ACE/config/cc1-toolhead.cfg]` |
   | CC2 | `[include ../plugins/AFC_ACE/config/cc2-runout.cfg]` | `[include ../plugins/AFC_ACE/config/cc2-toolhead.cfg]` |

3. **Set your values** in `printer.cfg`, below that include: usually just
   `[AFC_ACE]` with `ace:` and `dist_hub:` (next section).

4. **Restart Klipper** from SSH: `/etc/init.d/klipper restart`. A gcode
   `RESTART` is not enough: it keeps the old driver code loaded.

5. **Check it:** the console shows `SPOOL READY` for each lane with a spool.
   Load one with `T0`.

Update: `git -C /etc/klipper/plugins/AFC_ACE pull`, then restart. Remove:
delete the include line and the folder, then restart.

## Settings to set for your setup

Everything goes in **one section**, `[AFC_ACE]`, in `printer.cfg` below the
include. The ACEs are found when Klipper starts: one gives lanes 1–4 (T0–T3),
a second chained one lanes 5–8 (T4–T7). No unit or lane sections to write.

```ini
[AFC_ACE]
ace: pro            # pro = ACE Pro, 2pro = ACE 2 Pro
dist_hub: 500       # see your path below
```

Never edit the files in the plugin folder: updates overwrite them.

### Runout sensor path

| Setting | Shipped | Set it to | Why |
|---|---|---|---|
| `[AFC_hub ACE_1]` `afc_bowden_length` | `810` | your length from the runout sensor to just short of the extruder gears | The ACE homes on the runout sensor, then pushes this far blind. Too short and the gears never grab (the purge runs dry). Too long and the ACE pushes into gears that aren't turning. 810 is 5 mm short of the 815 mm measured on a CC1; not measured on a CC2. |
| `[AFC_ACE]` `dist_hub` | `1200` | leave it, or anything longer than your slot-to-sensor tube | Only a limit: the sensor stops the feed. |

Measuring the bowden length: push a lane to the gears by hand, retract it with
one long `LANE_MOVE` until the sensor clears, and add up the distance. Each ACE
move loses about 1 mm, so use as few moves as you can. Try values live with
`SET_BOWDEN_LENGTH HUB=ACE_1 LENGTH=+10`, then write the result in `printer.cfg`.

### Toolhead sensor path

| Setting | Shipped | Set it to | Why |
|---|---|---|---|
| `[AFC_ACE]` `dist_hub` | `500` | your tube length from an ACE slot to the merger, rounded down | A fresh spool's first load runs fast for this distance, then slows down to meet the sensor. If it is longer than the real tube, the filament hits the sensor at full speed. |

The toolhead lengths (`tool_stn` 51.5, `afc_bowden_length` 8,
`afc_unload_bowden_length` 45) are COSMOS's own values for this head: leave them.

### Only if needed

| Setting | Shipped | When to change it |
|---|---|---|
| One lane's tube length | `[AFC_ACE]` `dist_hub` | A lane whose tube differs: `[AFC_lane lane5]` with `dist_hub: 650`. |
| `[AFC_ACE]` `units` | `auto` | `auto` counts the ACEs when Klipper starts; a unit that is off then has no lanes until the next restart. Set a number (`units: 2`) to always have that many; a missing one then shows as not connected. |
| `[AFC_ACE]` `serial` | `auto` | Only if `auto` picks the wrong USB device: the first ACE's `/dev/serial/by-path/...` name (not `ttyACM*`, it changes between boots). Another unit: `[AFC_ACE ACE_2]` with its own `serial:`. |
| `[AFC_ACE ACE_2]` (any key) | from `[AFC_ACE]` | One unit different from the others. Every key it doesn't set comes from `[AFC_ACE]`. |

All other settings, with their defaults, are listed in [All settings](#all-settings).

## OrcaSlicer

| Field | Gcode |
|---|---|
| Machine start gcode | `PRINT_START EXTRUDER=[nozzle_temperature_initial_layer] BED=[bed_temperature_initial_layer_single] CHAMBER=0 TOOL={initial_extruder}` |
| Change filament gcode | `T{next_extruder} PURGE_LENGTH={flush_length}` |

## Commands

AFC's own commands work on the ACE lanes (`T0`, `TOOL_LOAD`, `TOOL_UNLOAD`,
`SET_COLOR`, ...). This adds:

| Command | What it does |
|---|---|
| `AFC_ACE_STATUS UNIT=ACE_1` | Print the ACE's raw status. |
| `AFC_ACE_DRYER_START UNIT=ACE_1 [TEMP=45] [DURATION=240]` | Run the ACE's dryer (°C, minutes). It also shows as a heater in the UI. |
| `AFC_ACE_DRYER_STOP UNIT=ACE_1` | Stop the dryer. |
| `AFC_ACE_RESET UNIT=ACE_1 LANE=lane1` | Clear a stuck lane: if the head sensor sees filament it heats, cuts and pulls it out of the gears, then the ACE retracts it and parks it. |
| `AFC_ACE_STOP UNIT=ACE_1 LANE=lane1` | Stop all ACE motion on a lane. |
| `AFC_ACE_BYPASS ENABLE=1` / `ENABLE=0` | Print from a spool fed straight into the printer, not through the ACE. Also the `AFC_ACE_BYPASS_ON` / `_OFF` macros. |
| `AFC_ACE_PANEL ACTION=INSTALL` / `REMOVE` | Add or remove the optional ACE Pro panel in Mainsail. |

**Bypass:** turning it on unloads the loaded lane and gives the path sensor its
runout pause back. Feed your spool through the sensor to the extruder, heat
the nozzle and extrude until it flows. To go back: `UNLOAD_FILAMENT`, pull the
filament out, then turn bypass off. Not during a print.

**Panel:** Mainsail's AFC panel is the default. `ACTION=INSTALL` adds an ACE
Pro panel (spools per lane, colour editor, dryer), which replaces the AFC panel
once you reload Mainsail. `ACTION=REMOVE` brings the AFC panel back. Run the
install again after updating.

## Status

| | |
|---|---|
| CC1, runout sensor path | works |
| CC1, toolhead sensor path | works |
| CC2, both paths | not run on hardware yet |
| Bypass, panel | works |
| ACE 2 Pro | tested only against a simulated unit, see [`docs/ACE2_PROTOCOL.md`](docs/ACE2_PROTOCOL.md) |

Each ACE move command loses about 1 mm, whatever its length. That matters when
measuring the runout path's bowden length.

## All settings

`[AFC_ACE]` (all units; `[AFC_ACE ACE_N]` overrides one unit):

| Key | Default | |
|---|---|---|
| `ace` | `pro` | `pro` = ACE Pro, `2pro` = ACE 2 Pro |
| `units` | `auto` | how many ACEs: counted at startup, or a number |
| `dist_hub` | `1200` runout / `500` toolhead | tube length for every lane; `[AFC_lane laneN]` overrides one |
| `serial` | `auto` | USB device (ACE Pro: the first unit's; ACE 2 Pro: the bus) |
| `unit_index` | `0`, `1`, ... | per unit: which ACE, in USB order (ACE 2: by hardware ID) |
| `feed_speed` / `retract_speed` | `50` / `75` | mm/s |
| `hub_clear_mm` | `110` runout / `65` toolhead | how far behind the sensor an unloaded lane parks |
| `sensor_approach_mm` / `sensor_approach_speed` | `30` / `15` | toolhead path: slow final approach to the sensor |
| `sync_load_mm` | `8` toolhead | how much the ACE pushes together with the extruder when threading the gears |
| `purge_park_cmd` | `_AFC_ACE_PURGE_SPOT` | where loads extrude: COSMOS's purge spot, off the tray's v-slot |
| `dryer_temp` / `dryer_duration` | `45` / `240` | dryer defaults, °C / minutes |
| `optional` | `False` | a missing unit is reported instead of failing startup |
| `monitor_only` | `False` | status, RFID and dryer only, no filament motion |
| `bypass_runout_distance` | `770` | runout path, bypass: mm printed after the sensor clears before pausing |

Developer checks: `python tools/check_configs.py <cosmos checkout>`, `python tools/test_setup.py <cosmos checkout>`,
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
