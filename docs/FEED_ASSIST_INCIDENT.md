# Feed assist overfeed, 2026-10-11

Research notes, not yet acted on. Nothing in the driver or on the printer was
changed for this.

## What happened

T0 change mid-print (lane4 -> lane1), from AFC.log and klippy.log:

| Time | Event |
|---|---|
| 19:39:55 | lane4 cut, unloaded, retracted (normal) |
| 19:40:35 | lane1 fed to the frame sensor (19.5 s) |
| 19:40:56 | blind 810 mm + 5 mm extruder-synced push done, "Filament loaded to nozzle" |
| 19:40:56 | driver sends `start_feed_assist` for slot 1, AFC starts `POOP` 274 mm at 5 mm/s |
| 19:41:32 | user's emergency stop, 36 s in (~180 mm of extruder movement) |

The ACE kept pushing slot 1 during the purge until a PTFE tube popped out.
The filament was in the extruder gears. No ACE error was logged, and no feed or
unwind command was running: the only ACE activity was feed assist. Earlier in
the same print, the T3 load ran the identical sequence and purged fine.

After the Klipper restart the driver re-armed assist on slot 1 (lane1 still
showed tool-loaded); `AFC_ACE_STOP UNIT=ACE_1 LANE=lane1` cleared it. lane1 was
then cut and unloaded with `TOOL_UNLOAD` and is parked behind the sensor.

## How feed assist works (sources below)

- `start_feed_assist {index}` / `stop_feed_assist {index}` take only the slot.
  There is no length, speed or force parameter. Assist runs until stopped.
- Assist is closed-loop on the ACE's buffer: filament pressure pushes a
  spring-loaded slider with a magnet, and a sensor reads the slider position
  and sets the feed speed. Pressure from a stopped extruder should push the
  slider over and stop the feed, so assist pushes only as hard as that spring.
- The ACE reports `feed_assist_count` and `cont_assist_time` (seconds of
  continuous pumping) in `get_status`. Our driver does not read or log either.
- ACE 1 firmware gives up a *starved* assist (pumping but no filament arriving:
  tangle or empty spool) after ~5 s continuous, then unwinds. That covers the
  spool side only; nothing documents a limit for pushing into a blocked head.
- CosmoACE, ACEPRO and our driver all turn assist on before the purge, so
  purging with assist on is the normal sequence, not something we invented.

## Likely causes, unconfirmed

1. **Slot 1's buffer did not report "full".** A stuck slider, debris in the
   buffer channel, or a sensor that didn't see the magnet would let the ACE keep
   feeding: the filament is moving, so the starved give-up never fires. This
   fits slot 4 working and slot 1 failing, if the slots have separate buffers
   (true for the ACE 2 Pro; not confirmed for the gen-1 ACE Pro). Anycubic
   lists a stuck buffer as a known fault: brittle PLA fragments, or a tip
   caught in the channel.
2. **The buffer worked, but a tube joint held less than the buffer spring.**
   Worth checking if it popped at a printed part such as the hub adapter.

Which tube popped, and whether the nozzle was extruding during the purge,
would tell these apart.

## Proposed changes (not done)

- Log `feed_assist_count` and `cont_assist_time` from every heartbeat while
  assist is on.
- Guard: if the ACE pumps continuously while the extruder isn't drawing that
  much (`cont_assist_time` past a threshold, as ACEPRO's tangle detector does),
  stop assist and pause.
- Purge without assist: feed the purge in ACE chunks matched to the extruder
  (the 5 mm `_sync_load` path), and turn assist on only after the purge, for the
  print itself.
- Hardware check: open slot 1's buffer per Anycubic's guide, confirm the slider
  moves freely, clear debris; compare with slot 4.

## Sources

- Anycubic wiki, ACE Pro main functions and core components:
  https://wiki.anycubic.com/en/fdm-3d-printer/ace-pro/ace-pro-introduction-tomain-functions-and-core-components
- Anycubic wiki, ACE 2 Pro components:
  https://wiki.anycubic.com/en/fdm-3d-printer/ace-2-pro/component-introduction
- Anycubic wiki, buffer mechanism material blockage:
  https://wiki.anycubic.com/en/fdm-3d-printer/ace-2-pro/buffer-mechanism-material-blockage
- ACEPRO driver (justinh-rahb/ACEPRO @1f54a8d): PROTOCOL.md (get_status fields),
  ARCHITECTURE.md (tangle detection, ACE 1 starved-assist give-up),
  extras/ace/instance.py `_feed_to_toolhead_with_extruder_assist` (assist on
  before purge).
- DuckACE `ace.py`: park-to-toolhead uses assist alone and waits for
  `feed_assist_count` to stop increasing.
