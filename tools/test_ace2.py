"""ACE 2 transport against two simulated ACE 2 units on one bus: discovery,
id assignment, status + RFID decode, commands, a FORBIDDEN reply and a
power-cycled unit. Not a hardware test. python tools/test_ace2.py"""
import os
import sys
import time
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_driver  # noqa: E402,F401  (stubs AFC, imports AFC_ACE)
AFC_ACE = sys.modules["AFC_ACE"]
AFC_ACE.RPC_REPLY_S = AFC_ACE.STOP_REPLY_S = 0.3

# The firmware's CRC as hakimio and multiACE write it (bitwise, poly 0x8408,
# init 0xFFFF): the driver's table-free ACE Pro CRC must be the same function
def crc_kermit(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc


assert all(AFC_ACE._crc16_mcrf4xx(bytes([i, 255 - i, 7] * i)) == crc_kermit(bytes([i, 255 - i, 7] * i))
           for i in range(64))
# FEED_OR_ROLLBACK {index 1, speed 50, length 100, mode 0}, device 2, seq 0x0102,
# laid out as ACEPRO's serialize_request_frame builds it
frame = AFC_ACE._ace2_frame(2, 0x0102, 8, AFC_ACE._pb_msg(1, 50, 100, 0))
inner = bytes([2, 0x02, 0x01, 8, 8, 0x08, 1, 0x10, 50, 0x18, 100, 0x20, 0])
assert frame == b"\xFF\xAA" + inner + crc_kermit(inner).to_bytes(2, "little") + b"\xFE", frame.hex()
print("ok")


def field(num, value):
    if isinstance(value, bytes):
        return AFC_ACE._pb_varint(num << 3 | 2) + AFC_ACE._pb_varint(len(value)) + value
    return AFC_ACE._pb_varint(num << 3) + AFC_ACE._pb_varint(value)


class Unit:
    def __init__(self, uid, slots):
        self.uid, self.slots, self.id = uid, slots, None
        self.got, self.forbid, self.stop_code, self.bad_rfid = [], 0, 0, False

    def handle(self, cmd, fields):
        get = lambda n: fields.get(n, [0])[0]
        if cmd == 6:
            dry = field(1, 2) + field(2, 50) + field(3, 7200) + field(4, 3600)
            return (field(1, 1) + field(2, dry) + field(3, 31) + field(4, 22)
                    + b"".join(field(9, field(1, s) + field(2, f)) for s, f in self.slots))
        if cmd == 13:
            if self.bad_rfid:
                return b"\x2a\xff"  # field 5, truncated
            red = 0xFF << 24 | 0x20 << 16 | 0x10 << 8 | 0xFF  # RGBA
            return field(1, get(1)) + field(4, b"PLA") + field(5, field(1, red))
        self.got.append((cmd, [get(n) for n in range(1, 5)]))
        if cmd == 8 and self.forbid:
            self.forbid -= 1
            return field(1, 2)
        return field(1, self.stop_code if cmd == 9 else 0)


units = [Unit((7, 7, 7), [(0, 0)] * 4),                       # higher UID: unit_index 1
         Unit((1, 2, 3), [(0, 2), (0, 0), (1, 1), (129, 1)])]  # lower UID: unit_index 0


class Bus:
    """pyserial stand-in: a frame written is answered at once by every unit
    it addresses, after our own echo (RS-485 adapters echo what they send)."""
    def __init__(self, port, baud, **kw):
        assert port == "/dev/ttyFAKE" and baud == 230400
        self.rx, self.is_open = bytearray(), True

    def write(self, data):
        self.rx += data  # echo
        flags, seq, cmd, size = data[2], data[3] | data[4] << 8, data[5], data[6]
        assert AFC_ACE._crc16_mcrf4xx(data[2:7 + size]) == int.from_bytes(data[7 + size:9 + size], "little")
        fields = AFC_ACE._pb_decode(data[7:7 + size])
        for u in units:
            if cmd == 0 and flags == 0:
                reply = field(1, u.uid[0]) + field(2, u.uid[1]) + field(3, u.uid[2])
            elif cmd == 1 and tuple(fields[n][0] for n in (1, 2, 3)) == u.uid:
                u.id = fields[4][0]
                reply = field(1, 0)
            elif flags and flags == u.id:
                reply = u.handle(cmd, fields)
            else:
                continue
            self.rx += AFC_ACE._ace2_frame(0x80 | (u.id or 0), seq, cmd, reply)

    def read(self, n):
        out = bytes(self.rx[:n])
        del self.rx[:n]
        if not out:
            time.sleep(0.002)
        return out

    def reset_input_buffer(self):
        self.rx.clear()

    def flush(self): pass
    def close(self): pass


AFC_ACE.serial = types.SimpleNamespace(Serial=Bus)


def wait(cond, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def rpc(t, method, params=None):
    result, done, _ = t.submit(method, params)
    assert done.wait(5)
    return result


t0 = AFC_ACE.Ace2Transport("/dev/ttyFAKE", 0)
t1 = AFC_ACE.Ace2Transport("/dev/ttyFAKE", 1)
t0.start()
t1.start()
assert t0._bus is t1._bus  # one bus, one port
wait(lambda: t0.connected and t1.connected)
assert (units[1].id, units[0].id) == (1, 2)  # bus ids by UID order
# each told printer status 0 after its id (pins the insert preload cap)
assert units[0].got == units[1].got == [(20, [0, 0, 0, 0])]
units[0].got.clear()
units[1].got.clear()

# Status in the ACE Pro's shape, the tag in it from the very first one (a
# first status without it would read as the tag changing when it arrived)
wait(lambda: t0.cached_status()[0] is not None)
assert t0.cached_status()[0]["slots"][0].get("type") == "PLA"
st = t0.cached_status()[0]
assert [s["status"] for s in st["slots"]] == ["ready", "empty", "feeding", "ready"], st["slots"]
assert st["status"] == "busy" and st["slots"][0]["color"] == [0xFF, 0x20, 0x10]
assert st["dryer_status"] == {"status": "drying", "target_temp": 50, "duration": 7200, "remain_time": 3600}
assert (st["temp"], st["humidity"]) == (31, 22)

# Commands go to the addressed unit only, speed clamped to the firmware's 100.
# Assist and dry start with a stop; a stop waits until its move has run
# long enough for the firmware to take it.
assert rpc(t0, "feed_filament", {"index": 2, "length": 100, "speed": 150})["ok"]
assert rpc(t0, "unwind_filament", {"index": 2, "length": 40, "speed": 75, "mode": 0})["ok"]
assert rpc(t0, "start_feed_assist", {"index": 0})["ok"]
started = time.monotonic()
assert rpc(t0, "stop_feed_assist", {"index": 0})["ok"]
assert time.monotonic() - started >= AFC_ACE.ACE2_STOP_AFTER_START_S - 0.02
assert rpc(t0, "drying", {"temp": 55, "fan_speed": 7000, "duration": 240})["ok"]
assert rpc(t0, "drying_stop")["ok"]
assert units[1].got == [(8, [2, 100, 100, 0]), (8, [2, 75, 40, 1]),
                        (9, [0, 0, 0, 0]), (8, [0, 10, 0, 2]), (9, [0, 0, 0, 0]),
                        (11, [0, 0, 0, 0]), (11, [55, 240, 0, 0]), (11, [0, 0, 0, 0])], units[1].got
assert units[0].got == []

# FORBIDDEN = still busy, not run: resent until accepted (once only)
units[1].got.clear()
units[1].forbid = 2
assert rpc(t0, "feed_filament", {"index": 1, "length": 10, "speed": 10})["ok"]
assert units[1].got == [(8, [1, 10, 10, 0])] * 3, units[1].got
# ... and still FORBIDDEN after the wait: an ACE error the unit code reports
AFC_ACE.ACE2_FORBIDDEN_WAIT_S, units[1].forbid = 0.5, 99
res = rpc(t0, "feed_filament", {"index": 1, "length": 10, "speed": 10})
assert not res["ok"] and "FORBIDDEN" in res["error"], res
# A caller that gives up during the wait: nothing more goes out after it
AFC_ACE.ACE2_FORBIDDEN_WAIT_S, units[1].forbid = 30.0, 99
units[1].got.clear()
result, done, cancelled = t0.submit("feed_filament", {"index": 1, "length": 10, "speed": 10})
time.sleep(0.5)
cancelled.set()
assert done.wait(5) and not result["ok"]
sent = len(units[1].got)
time.sleep(0.8)
assert len(units[1].got) == sent, units[1].got
units[1].forbid = 0

# A stop answered with an error, on a slot that is idle: done
units[1].stop_code = 3
assert rpc(t0, "stop_feed_filament", {"index": 1}).get("assumed_success")
# ... on a slot still moving (slot 2 reads feeding): a real failure
assert not rpc(t0, "stop_feed_filament", {"index": 2})["ok"]
units[1].stop_code = 0

# Garbage RFID reply: the slot gets no tag, the bus stays up
units[0].bad_rfid = True
units[0].slots[0] = (0, 2)
wait(lambda: 0 in t1._rfid)
assert t1._rfid[0] == {} and t1.connected

# Unknown method: refused, nothing sent
assert not rpc(t0, "get_info")["ok"]

# Unit 1 power-cycles (forgets its id): rediscovered, generation bumped;
# unit 0, still answering, is left alone (its feed assist is not re-armed)
gen, gen0 = t1.generation, t0.generation
units[0].id = None
wait(lambda: t1.generation > gen and t1.connected, timeout=10)
assert rpc(t1, "get_status")["ok"]
assert t0.generation == gen0

# Unit 0 unplugged: unit 1 is now the lowest UID on the bus, but unit 0
# keeps its pinned UID and waits; unit 1 is untouched. Back: reconnects.
gone, gen = units.pop(1), t1.generation
wait(lambda: not t0.connected, timeout=10)
time.sleep(2.5)  # several discovery rounds
assert not t0.connected and t1.connected and t1.generation == gen
assert units[0].id == 2  # never re-addressed to unit 0's id
gone.id = None
units.append(gone)
t0._bus._discover_at = 0.0
wait(lambda: t0.connected, timeout=10)
assert gone.id == 1 and t1.generation == gen

t0.stop()
t1.stop()
assert t0._bus._shutdown.is_set() and not AFC_ACE._ACE2_BUSES
print("ok")
