# ACE 2 Pro protocol notes

What `ace: 2pro` (the units' `protocol: ace2`) is built on, with a source for every fact. None of it
has run on hardware with this driver; the driver side is checked against a
simulated unit (`tools/test_ace2.py`).

## Sources

| Short name | What | Read at |
|---|---|---|
| **hakimio** | [firmware analysis gist](https://gist.github.com/hakimio/4916ff69add458fdc51aeea76f21efb9) (Kobra S1 gklib + ACE 2 firmware V1.1.31), and his working ACE 2 driver, [SnapmakerU1-Extended-Firmware `ace-2`](https://github.com/hakimio/SnapmakerU1-Extended-Firmware/tree/ace-2) (`39-ace-support/.../ace_device/`) | gist 2026-05-13, driver `42abfa4` |
| **Simon-CR** | [ace2-pro-firmware-research](https://github.com/Simon-CR/ace2-pro-firmware-research): `protocol-findings.md`, `docs/05`–`08`, `protocol/ace2-v1.1.31.proto` and `descriptor-dump.txt` (recovered from the firmware image), measurements on a unit | 2026-09-20 |
| **ACEPRO** | [Kobra-S1/ACEPRO](https://github.com/Kobra-S1/ACEPRO), GPL-3.0: `protocol_ace2.py`, `ace2_bus.py`, `manager.py` | fork [WojciechBednarski/ACEPRO](https://github.com/WojciechBednarski/ACEPRO) `547d57c` |
| **multiACE** | [decay71/multiACE](https://github.com/decay71/multiACE), GPL-3.0: `ace_protocol_v2.py` | 2026-10-21 |
| **ace2k** | [tobecwb/ace2k](https://github.com/tobecwb/ace2k) open firmware: `docs/hardware.md`, `firmware/tools/ace2k_flash.py` | 2026-10-09 |

hakimio's driver, ACEPRO and multiACE all run on hardware. Where the sources
differ, the driver follows ACEPRO, the only one that drives several units on
one bus.

## Link and frame

- RS-485 half duplex, 230400 8N1, through a CH343 (`1a86:55d3`) moulded into
  Anycubic's cable; the unit has no USB of its own (all five sources; ace2k
  `hardware.md` for the cable). ACEPRO: only the KS1/K3 conversion cable
  works. The chain port carries the same pair, so chained units share one
  bus (ace2k).
- `FF AA | flags | seq lo | seq hi | cmd | len | protobuf | crc lo | crc hi | FE`
  (hakimio's driver, ACEPRO, multiACE, ace2k). `len` is one byte.
- CRC-16 init `0xFFFF`, reflected poly `0x8408`, over flags..payload: the ACE
  Pro's MCRF4XX, which the others call "Kermit" (`tools/test_ace2.py` checks
  they are the same function).
- Replies: bit 7 of `flags` set, `seq` echoed (hakimio's driver matches
  replies by seq).

**Disagreement, header layout.** hakimio's gist gives a second layout in its
MCU section (`SEQ:1, TYPE:2, CMD`). Every working driver uses the one above.

**Disagreement, `flags` on requests.** ACEPRO puts the assigned bus id in the
low 7 bits. hakimio's driver assigns id 1 and then sends 0; multiACE and ace2k
send 0 and never assign. All work on one unit; only ACEPRO's form addresses
one unit among several, so the driver uses it.

## Bus setup

1. **DISCOVER (0)**, flags 0: every unit answers with its 96-bit MCU UID,
   fields 1–3. All units answer the same broadcast, so the driver repeats it
   once more than the number of configured units and keeps every reply
   (ACEPRO does the same).
2. **ASSIGN (1)**: UID + id in field 4; GenericResponse code 0 on success.
3. **SET_PRINTER_STATUS (20)**, bool 0, see *Preload*.

`unit_index` N takes the Nth-lowest UID and bus id N+1. Once bound, a unit
keeps its UID: with a sibling missing, bus order would hand it the wrong
unit. A unit that misses 3 replies loses its id and is re-assigned (a
power-cycled unit forgets it; inferred). Units still answering are never
re-assigned.

**Open, ASSIGN field 4.** hakimio's gist reads it as the unit's expected
sequence counter; ACEPRO as the bus id, with one rising sequence shared by all
units, and that works on hardware. If replies stop after ASSIGN, look here.

## Commands the driver sends

Numbers and message types from Simon-CR's descriptor dump (firmware V1.1.31),
matching hakimio, ACEPRO and multiACE.

| ACE Pro method | ACE 2 | Payload | Notes |
|---|---|---|---|
| `get_status` | 6 | none | below |
| `feed_filament` / `unwind_filament` | 8 FEED_OR_ROLLBACK | index, speed, length, mode 0 / 1 | speed capped at 100 (firmware PARAM_ERROR above) |
| `start_feed_assist` | 9 then 8 | mode 2 | see *Feed assist* |
| any stop | 9 STOP_FEED_OR_ROLLBACK | index | the only stop; ends every mode (Simon-CR) |
| `drying` | 11 (0, 0) then 11 | temp, duration (min), auto_roll 0 | see *Dryer* |
| `drying_stop` | 11 | 0, 0 | |
| RFID per slot | 13 GET_RFID_CACHE | index | replies a FilamentInfoResponse |

GenericResponse field 1: 0 SUCCESS, 1 PARAM_ERROR, 2 FORBIDDEN, 3 FAILED.
Cmd 13 is named `GET_FILAMENT_INFO` in ACEPRO and multiACE; the firmware's
`GET_FILAMENT_INFO` is 68. Same opcode on the wire.

### Motion

- **FORBIDDEN** means the command did not run: the slot or the unit's
  second operation channel is busy (Simon-CR docs/05). The driver resends a
  feed, retract or assist every 0.3 s for up to 30 s, polling the other units
  meanwhile and never after the caller gave up. A toolchange can wait there.
- **Lost STOP.** A STOP that lands within ~200 ms of the move starting is
  dropped and the move runs its full length (Simon-CR docs/05, two races in
  the firmware). The driver holds a STOP until 250 ms after that slot's last
  accepted move, and every halt confirms idle from status (as on the ACE Pro).
- **Admission** (Simon-CR): feed from ready, assisting or error; rollback from
  ready, rollback-assisting or error; assist from ready or error. The driver
  stops assist before every unload's rollback.
- A STOP that answers an error counts as done if status then reads the slot
  idle; whether a STOP to an idle slot answers 0 is unknown.

### Feed assist

- Mode 2 runs at a fixed 50 mm/s whatever speed is sent, until the ACE's own
  internal buffer pushes back (Simon-CR docs/05, 08). The buffer is inside the
  unit, so it works on any printer.
- A slot reading `ready` may still hold a live assist (hakimio's driver), and
  a second start is refused, so the driver sends STOP first.
- **Assist error (131)** about 1 s after the extruder stops pulling; only a new
  start clears it (hakimio). The driver re-arms it, and arms it after a
  reconnect or at startup, only while the extruder is moving forward
  (`live_extruder_velocity` > 0, as hakimio's driver). "While printing" is
  not enough: heat-ups and M109 waits count as printing, and an assist armed
  on a still extruder pushes into stopped gears, then errors, every poll.
  For the same reason a load arms it directly only when an extruder-only
  pull follows the sync load (the toolhead path); otherwise (the runout
  path, a tail push) the poll arms it once the purge extrudes.

### Preload

Inserting a spool starts a feed the host never sent: up to 1700 mm at
50 mm/s while the RFID reader works, capped at **750 mm** when printer status
is 0 and 1100 mm otherwise (Simon-CR docs/08, bounds proven from the image).
The driver sends status 0 on connect. **The tube from the ACE to the hub or
merger must be longer than 750 mm**, or a preload can push into the shared
path. The slot reads busy while preloading; loads wait for it. On the
toolhead path the first load after an insert assumes the tip may already be
750 mm out: its fast phase ends that much earlier and the rest runs at the
approach speed.

### Dryer

- DRYING accepts 15–65 °C (the driver caps at 65) and always answers code 0,
  even when it rejects the value (Simon-CR docs/07).
- DRYING sent mid-cycle keeps the old start time, so it can end at once: the
  driver stops first.
- auto_roll stays off (factory setting; multiACE).

## GET_STATUS reply

| Field | Meaning | Driver |
|---|---|---|
| 1 | work state | unused |
| 2 | dryer: state, target °C, duration s, remaining s (absent when idle) | state 1/2 = drying (low nibble, as multiACE), times in seconds as on the ACE Pro |
| 3, 4 | temperature °C, humidity % | as is |
| 7, 8 | assist count, continuous assist time **ms** | ms ÷ 1000 |
| 9 | per slot: state, filament | `slots` |

- Slot state: 0 ready, 1 feeding, 2 rollback, 3 assisting, 4
  rollback-assisting, 5 preloading, 6 upgrading, 129–135 errors (all
  sources). The driver reports 1/2/5 as moving; assist and error states as
  idle, since they accept the next command.
- Filament state: 0 empty, 1 present, 2 RFID identified, 3 identifying
  (hakimio's driver, multiACE; ACEPRO treats 0 as empty too).
- Runout: the firmware's per-lane EMPTY inputs are stubbed out; a slot reads
  empty when filament leaves the insert sensor (Simon-CR docs/08).

## RFID

Cmd 13 fields: 1 index, 3 sku, 4 type, 5 colors (RGBA, R in the top byte), 12
code (0 = tag read). The tag is read while the spool turns, so it can arrive
well after insert; the driver fetches it once per spool when the slot reaches
filament state 2 and applies it whenever it changes.

## Not used

GET_INFO (7), UPDATE_SPEED (10), SET_FEED_CHECK (19), GET_FEED_INFO (76),
mode 3 rollback-assist, OTA (2–5). Never send SET_DRY_POWER (65) or
SET_PTC_TEMP (75): they bypass every dryer safety (Simon-CR docs/07).
