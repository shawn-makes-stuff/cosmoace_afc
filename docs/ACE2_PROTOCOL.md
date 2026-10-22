# ACE 2 Pro protocol notes

What the driver's ACE 2 support (`protocol: ace2`) is built on, with a source
for each fact. None of it has run on hardware with this driver. The driver's
side is checked only against a simulated unit (`tools/test_ace2.py`).

## Sources

| Short name | What it is | Read at |
|---|---|---|
| **hakimio** | [hakimio, "ACE 2 Pro Firmware Behavior Analysis"](https://gist.github.com/hakimio/4916ff69add458fdc51aeea76f21efb9): decompiled Kobra S1 host firmware (gklib 2.7.0.9) and ACE 2 firmware V1.1.31 | gist as of 2026-05-13 |
| **Simon-CR** | [Simon-CR/ace2-pro-firmware-research](https://github.com/Simon-CR/ace2-pro-firmware-research): `protocol-findings.md` (measured on a unit), `protocol/ace2-v1.1.31.proto` (recovered from the firmware's nanopb descriptors) | 2026-09-20 |
| **ACEPRO** | [Kobra-S1/ACEPRO](https://github.com/Kobra-S1/ACEPRO) Klipper driver: `extras/ace/protocol_ace2.py`, `ace2_bus.py`, `manager.py`. GPL-3.0 | fork [WojciechBednarski/ACEPRO](https://github.com/WojciechBednarski/ACEPRO) at `547d57c`, 2026-09-20 |
| **multiACE** | [decay71/multiACE](https://github.com/decay71/multiACE) (Snapmaker U1): `multiace/klipper/extras/ace_protocol_v2.py`. GPL-3.0 | 2026-10-21 |
| **ace2k** | [tobecwb/ace2k](https://github.com/tobecwb/ace2k), open replacement firmware: `docs/hardware.md`, `docs/protocol.md`, `firmware/tools/ace2k_flash.py` (speaks the stock protocol to flash) | 2026-10-09 |

ACEPRO and multiACE run on hardware; Simon-CR's measurements were taken
through ACEPRO. The driver's code follows ACEPRO wherever the sources differ,
because it is the only one that drives several units on one bus.

## Link

| Fact | Sources |
|---|---|
| RS-485, half duplex, 230400 8N1 | hakimio (firmware `BRR`), ace2k, ACEPRO, multiACE |
| USB side is a CH343 (`1a86:55d3`, "USB Single Serial") inside Anycubic's conversion cable, not in the unit | ace2k `hardware.md`, multiACE, ACEPRO README |
| ACEPRO: only the KS1/K3 conversion cable works; Kobra X / KS1 Max cables do not, nor a self-made USB cable | ACEPRO README |
| The 4-pin chain port carries the same pair: chained units share one bus | ace2k `hardware.md` |
| The unit waits for 100 µs of silence before it answers, and does not hear itself | ace2k (stock behaviour not stated) |

The driver finds the cable by its USB id, opens it once (one `Ace2Bus` for
every ACE 2 unit with the same `serial:`), and ignores any echo of its own
frames.

## Frame

```
FF AA | flags | seq lo | seq hi | cmd | len | protobuf payload | crc lo | crc hi | FE
```

- `len` is one byte, so a payload is at most 255 bytes (multiACE caps at 100).
- CRC-16, init `0xFFFF`, reflected polynomial `0x8408`, no final XOR, over
  `flags` through the payload. That is the ACE Pro's CRC (MCRF4XX); hakimio
  and ace2k call it "Kermit". `tools/test_ace2.py` checks the two are the
  same function.
- Replies set bit 7 of `flags` (ACEPRO, multiACE).

**Disagreement, header bytes 3–5.** hakimio gives two layouts:
- the gklib section: `[flags] [seq_lo seq_hi] [cmd]`;
- the MCU parser section: `[SEQ:1] [TYPE_HI TYPE_LO] [CMD]`, with TYPE big-endian.

ACEPRO, multiACE and ace2k all build `flags, seq (16-bit little-endian),
cmd`, which matches the gklib reading, and ACEPRO and multiACE run on units.
The driver uses that.

**Disagreement, `flags` on requests.** ACEPRO puts the bus device id in the
low 7 bits (0 for DISCOVER and ASSIGN). multiACE and ace2k always send 0, one
unit per port, and never assign. Both work on a single unit. Only ACEPRO's
form can address one unit among several, so the driver uses it.

## Bus setup

1. **DISCOVER (cmd 0)**, empty payload, flags 0: every unit replies with its
   96-bit MCU UID as fields 1–3 (hakimio, Simon-CR's `.proto`, ACEPRO). It is
   a broadcast, so all units answer the same request. ACEPRO sends it once
   per expected unit and keeps every reply; the driver sends one round more
   than the number of configured units.
2. **ASSIGN (cmd 1)**: fields 1–3 the UID, field 4 a number; GenericResponse
   code 0 on success.

**Disagreement, ASSIGN field 4.** ACEPRO names it `device_id` and then
addresses that unit by it in `flags`. hakimio's MCU analysis says the value
becomes the unit's expected sequence counter, and that later frames "must
increment" it. ACEPRO sends one rising sequence shared by every unit on the
bus and works on hardware, so a strict per-unit check seems unlikely. The
driver does what ACEPRO does. **Open**, and the first thing to look at if
replies stop after ASSIGN.

The driver's choices on top of that:
- Units are ordered by UID; `unit_index` N gets device id N+1. UIDs are
  burned into the MCU, so the order is stable without saving anything.
- A unit that misses 3 replies in a row loses its id and the bus
  rediscovers: a power-cycled unit forgets its id (inferred, not measured).

## Commands the driver uses

All command numbers agree across hakimio, Simon-CR, ACEPRO and multiACE.

| ACE Pro method | ACE 2 | Payload fields | Notes |
|---|---|---|---|
| `get_status` | 6 GET_STATUS | none | see below |
| `feed_filament` | 8 FEED_OR_ROLLBACK | 1 index, 2 speed, 3 length, 4 mode 0 | |
| `unwind_filament` | 8 | same, mode 1 | the ACE Pro's `mode` param is dropped |
| `start_feed_assist` | 8 | same, mode 2, length 0, speed 10 | speed 10: ACEPRO and multiACE |
| `stop_feed_filament`, `stop_unwind_filament`, `stop_feed_assist` | 9 STOP_FEED_OR_ROLLBACK | 1 index | the only stop; it ends every mode (Simon-CR 8.3) |
| `drying` | 11 DRYING | 1 temp, 2 duration (minutes), 3 auto_roll = 0 | auto_roll off is the factory setting (multiACE) |
| `drying_stop` | 11 DRYING | temp 0, duration 0 | hakimio: SET_DRY_TEMP (12) does not stop it |
| RFID, per slot | 13 | 1 index | see below |

Every other command returns a GenericResponse: field 1 = code. 0 SUCCESS,
1 PARAM_ERROR, 2 FORBIDDEN, 3 FAILED (Simon-CR 8.5, ACEPRO).

Limits enforced by the firmware (Simon-CR 8.1, from the V1.1.31 image):
index ≤ 3, speed ≤ 100, mode ≤ 3, else PARAM_ERROR. The driver caps speed at
100.

Which slot states admit which mode (Simon-CR 8.1, "strong", not proven):

| Mode | Accepted when the slot is |
|---|---|
| 0 feed | ready, assisting, or in error |
| 1 rollback | ready, rollback-assisting, or in error |
| 2, 3 assist | ready, or in error |

Anything else answers FORBIDDEN. The driver already stops feed assist before
every unload's rollback.

**Disagreement, command names.** hakimio calls 13 `GET_RFID_CACHE` and 68
`GET_FILAMENT_INFO`; ACEPRO and multiACE call 13 `GET_FILAMENT_INFO` and 68
`FILAMENT_IDENTIFY`. Same numbers, so it does not matter on the wire.
Simon-CR says the firmware evidence favours hakimio's names. Gklib reads 13
in normal use (hakimio).

## GET_STATUS reply

Field numbers from Simon-CR's `.proto`, matching ACEPRO and multiACE:

| Field | Meaning | Driver |
|---|---|---|
| 1 | work state: 0 init, 1 ready, 2 busy, 3 upgrading | not used, see below |
| 2 | dryer: 1 state, 2 target °C, 3 duration, 4 remaining | state 1 starting / 2 keeping = drying |
| 3 | temperature, °C | `temp` |
| 4 | humidity, % | `humidity` |
| 5, 6 | rfid1/rfid2 enable (Simon-CR saw both constant 1) | not used |
| 7 | feed_assist_count | as is |
| 8 | cont_assist_time, **milliseconds** (seconds on the ACE Pro) | ÷ 1000 |
| 9 | repeated per slot: 1 slot state, 2 filament state | `slots` |

- **Dryer times are seconds** in the reply, while DRYING takes minutes
  (Simon-CR). The driver passes them on as seconds: the panel reads the ACE
  Pro's `remain_time` as seconds too (from CosmoACE, on hardware). ACEPRO
  prints it as minutes in one place and seconds in another.
- **Dryer state mask**: Simon-CR's custom firmware puts flags in bits 6–7 of
  the dryer state; multiACE masks with `0x0F`. Stock firmware never sets
  them. The driver masks too.
- **Slot state**: 0 ready, 1 feeding, 2 rollback, 3 assisting, 4
  rollback-assisting, 5 preloading, 6 upgrading, 129–135 errors (feed,
  rollback, assist, preload, stuck, tangled, motor). hakimio, Simon-CR,
  ACEPRO, multiACE agree.
- **Filament state**: 0 empty, 1 present (not identified), 2 RFID
  identified, 3 identifying (multiACE). ACEPRO: 0 = empty, anything else
  present.

**Disagreement, filament state 0.** Simon-CR's notes call it "no tag",
which would make an untagged spool look empty. multiACE (1 = present,
untagged) and ACEPRO (0 = empty) both drive loads off it on hardware. The
driver follows them: 0 is an empty slot.

**Busy.** ACEPRO maps "assisting" to busy, so every slot reads busy while
feed assist runs. multiACE derives busy only from slots that are feeding,
rolling back or preloading. The driver does the same as multiACE: feed assist
runs for the whole print and must not make each toolchange wait it out. Error
states read as idle, since they accept the next command.

## RFID

GET_STATUS carries no tag data. Cmd 13 with the slot index returns: 1 index,
2 version, 3 sku, 4 type, 5 colors (repeated, `rgba` packed R in the top
byte), 6 extruder temps, 7 bed temps, 8 diameter, 9 length, 10 icon, 11
remaining, 12 code (Simon-CR `.proto`, ACEPRO, multiACE). Code ≠ 0 means no
usable tag.

- The tag is only read while the spool turns, about one revolution (Simon-CR
  §4), so it can arrive well after the spool goes in. The driver reads cmd 13
  once when a slot reaches filament state 2, drops it when the slot empties,
  and the unit applies a tag whenever it changes, not only on insert.
- The decode is cached until the slot reads empty (Simon-CR).

## Known problems, unresolved

- **FORBIDDEN after a stop.** Simon-CR saw feeds and retracts rejected for
  20–30 s after STOP_FEED_OR_ROLLBACK. Their best explanation is a stopped
  assist still finishing its move. Every unload stops feed assist just
  before its retract, so this would fail toolchanges. FORBIDDEN means the
  command did not run, so the driver resends a feed, retract or assist
  every 0.3 s for up to 30 s, keeping the other units' status polled
  meanwhile, and never resends after the caller has given up. A toolchange
  can stall up to 30 s there. After 30 s it is an ACE error.
- **STOP on an idle slot.** Not known whether it answers SUCCESS. When a stop
  answers an error, the driver reads the status and treats the stop as done
  if the slot is idle (not moving, not assisting).
- **Sequence counter** after ASSIGN (see Bus setup).
- **Feed assist speed.** 10 mm/s comes from the two drivers, not from the
  firmware.
- **Bus collisions.** DISCOVER replies from several units can collide on the
  wire. ACEPRO repeats the broadcast for that reason; so does the driver.

## Not used

GET_INFO (7), UPDATE_SPEED (10), SET_FEED_CHECK (19), GET_FEED_INFO (76,
per-slot measured movement, Simon-CR §1), mode 3 rollback-assist (Simon-CR
§5), and the OTA commands (2–5). GET_FEED_INFO and mode 3 look useful for
later: measured feed lengths, and a retract that follows the extruder.
