#!/usr/bin/env python3
"""Flash Anycubic ACE Pro (Gen 1) firmware from a COSMOS CC1/CC2 over SSH.

Gen1 IAP (from RE of V1.3.863 / Godless50 ace_flash.py):
  frame: FF AA | len(u16 LE) | payload | crc16(payload) | FE
  payload[0] == 0x55 -> IAP chunk: 55 | addr(u32 LE) | n(u8) | data[n]
  otherwise          -> JSON-RPC (iap_upgrade / iap_upgrade_finish / ...)
Staging base 0x08024000; max chunk 64 bytes. CRC-16/MCRF4XX.

v1 requires Klipper stopped so nothing holds the ACE tty:
  /etc/init.d/klipper stop
  python tools/ace1_flash.py flash --bin /path/to/ACE_V….bin
  /etc/init.d/klipper start

A later AFC_ACE_FW_RELEASE path can keep Klipper up; not implemented here.

Stock ACE drops USB if idle ~3.3s with no frame — the chunk stream keeps
the link busy. OpenCubic no-watchdog CFW does not need that.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import time
from typing import Dict, List, Optional, Tuple

FLASH_BASE = 0x08024000
CHUNK = 64
DEFAULT_ANNOUNCE = "1.3.863"
BAUD = 115200


def crc16_mcrf4xx(buf: bytes) -> int:
    crc = 0xFFFF
    for b in buf:
        d = b ^ (crc & 0xFF)
        d ^= (d & 0x0F) << 4
        crc = ((d << 8) | (crc >> 8)) ^ (d >> 4) ^ (d << 3)
        crc &= 0xFFFF
    return crc


def frame(payload: bytes) -> bytes:
    return (
        b"\xff\xaa"
        + struct.pack("<H", len(payload))
        + payload
        + struct.pack("<H", crc16_mcrf4xx(payload))
        + b"\xfe"
    )


def _usb_path_key(path: str) -> list:
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", path)]


def scan_ace_ports() -> Dict[str, str]:
    """{usb sysfs path: /dev/tty*} — same idea as AFC_ACE.scan_ace_ports."""
    found: Dict[str, str] = {}
    for dev in glob.glob("/sys/bus/usb/devices/*/"):
        try:
            with open(os.path.join(dev, "product"), encoding="utf-8",
                      errors="replace") as f:
                product = f.read()
        except OSError:
            continue
        if "ACE" not in product.upper():
            continue
        for tty in glob.glob(os.path.join(dev, "*", "tty", "tty*")):
            found[dev.rstrip("/")] = "/dev/" + os.path.basename(tty)
    return found


def ordered_units() -> List[Tuple[str, str]]:
    ports = scan_ace_ports()
    return [(p, ports[p]) for p in sorted(ports.keys(), key=_usb_path_key)]


def klipper_running() -> bool:
    """Best-effort: COSMOS uses /etc/init.d/klipper."""
    try:
        r = subprocess.run(
            ["/etc/init.d/klipper", "status"],
            capture_output=True, text=True, timeout=5)
        out = (r.stdout or "") + (r.stderr or "")
        low = out.lower()
        if "not running" in low or "stopped" in low:
            return False
        if r.returncode == 0 and ("running" in low or "started" in low):
            return True
        if r.returncode == 0:
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    # Fallback: any klippy process
    try:
        r = subprocess.run(["pgrep", "-f", "klippy"], capture_output=True)
        return r.returncode == 0
    except (FileNotFoundError, OSError):
        return False


def require_klipper_stopped(force: bool) -> None:
    if force:
        return
    if klipper_running():
        sys.exit(
            "Klipper appears to be running and likely holds the ACE serial "
            "port.\nStop it first:\n  /etc/init.d/klipper stop\n"
            "Then re-run this tool. After flashing:\n"
            "  /etc/init.d/klipper start\n"
            "(Use --force to skip this check.)"
        )


class Ace:
    def __init__(self, dev: str, baud: int = BAUD, tries: int = 20):
        self.dev = dev
        self.baud = baud
        self.tries = tries
        self.buf = b""
        self.id = 0
        self.ser = None
        self._open()

    def _open(self) -> None:
        try:
            import serial
        except ImportError:
            sys.exit("pyserial is required (COSMOS normally has it with Klipper)")
        last: Optional[BaseException] = None
        for _ in range(self.tries):
            try:
                try:
                    self.ser = serial.Serial(
                        self.dev, self.baud, timeout=0.3,
                        rtscts=True, exclusive=True)
                except TypeError:
                    self.ser = serial.Serial(
                        self.dev, self.baud, timeout=0.3, rtscts=True)
                return
            except Exception as e:
                last = e
                time.sleep(1)
        raise SystemExit(
            "cannot open %s: %s\nIs Klipper stopped? Is the ACE powered "
            "and plugged in?" % (self.dev, last))

    def reopen(self) -> None:
        self.close()
        self.buf = b""
        self._open()

    def prime(self, tries: int = 40) -> bool:
        for _ in range(tries):
            try:
                if self.rpc("get_status", timeout=1.0) is not None:
                    return True
            except Exception:
                pass
            time.sleep(0.3)
        return False

    def _extract(self) -> list:
        out = []
        while True:
            i = self.buf.find(b"\xff\xaa")
            if i < 0:
                self.buf = b""
                break
            self.buf = self.buf[i:]
            if len(self.buf) < 7:
                break
            ln = struct.unpack("<H", self.buf[2:4])[0]
            total = 4 + ln + 3
            if len(self.buf) < total:
                break
            out.append(self.buf[4:4 + ln])
            self.buf = self.buf[total:]
        return out

    def pump(self, dur: float) -> list:
        t = time.time()
        out = []
        while time.time() - t < dur:
            d = self.ser.read(4096)
            if d:
                self.buf += d
            out += self._extract()
        return out

    def rpc(self, method: str, params=None, timeout: float = 4.0):
        self.id += 1
        rid = self.id
        req = {"id": rid, "method": method}
        if params is not None:
            req["params"] = params
        p = json.dumps(req, separators=(",", ":")).encode()
        self.ser.reset_input_buffer()
        self.buf = b""
        self.ser.write(frame(p))
        self.ser.flush()
        t = time.time()
        while time.time() - t < timeout:
            for f in self.pump(0.2):
                try:
                    j = json.loads(f)
                except Exception:
                    continue
                if j.get("id") == rid:
                    return j
        return None

    def chunk(self, addr: int, data: bytes) -> None:
        p = bytes([0x55]) + struct.pack("<I", addr) + bytes([len(data)]) + data
        self.ser.write(frame(p))
        self.ser.flush()

    def close(self) -> None:
        try:
            if self.ser is not None:
                self.ser.close()
        except Exception:
            pass


def resolve_unit(unit: int, port: Optional[str] = None) -> Tuple[str, str]:
    if port:
        return (port, port)
    units = ordered_units()
    if not units:
        sys.exit(
            "no ACE Pro found on USB (product string containing 'ACE').\n"
            "On Windows, pass the COM port explicitly, e.g. --port COM13")
    if unit < 0 or unit >= len(units):
        sys.exit("unit %d not found (%d ACE(s) present)" % (unit, len(units)))
    return units[unit]


def cmd_list(_args: argparse.Namespace) -> None:
    units = ordered_units()
    if not units:
        print("no ACE units found")
        return
    for i, (path, tty) in enumerate(units):
        print("%d  %s  %s" % (i, tty, path))


def cmd_version(args: argparse.Namespace) -> None:
    require_klipper_stopped(args.force)
    _path, tty = resolve_unit(args.unit, getattr(args, "port", None))
    ace = Ace(tty)
    try:
        if not ace.prime():
            print("warning: prime failed (no get_status yet)", flush=True)
        print("tty        :", tty)
        print("get_info   :", ace.rpc("get_info"))
        print("iap_version:", ace.rpc("iap_version"))
        print("get_status :", ace.rpc("get_status"))
    finally:
        ace.close()


def cmd_soak(args: argparse.Namespace) -> None:
    """Ping get_status on a fixed interval; stock idle drop is ~3.3s."""
    require_klipper_stopped(args.force)
    _path, tty = resolve_unit(args.unit, getattr(args, "port", None))
    duration_s = max(1.0, float(args.minutes) * 60.0)
    interval_s = max(0.5, float(args.interval))
    print("soak      : %s for %.1f min, ping every %.1fs"
          % (tty, duration_s / 60.0, interval_s), flush=True)
    print("note      : stock ACE drops USB after ~3.3s idle — "
          "gaps >3.3s stress that; no-watchdog CFW should hold", flush=True)
    ace = Ace(tty)
    ok = fail = reopen = 0
    first_fail_at: Optional[float] = None
    t0 = time.time()
    try:
        info = ace.rpc("get_info", timeout=3.0)
        print("get_info  :", info, flush=True)
        while True:
            elapsed = time.time() - t0
            if elapsed >= duration_s:
                break
            ping_t = time.time()
            try:
                st = ace.rpc("get_status", timeout=2.0)
            except Exception as e:
                st = None
                err = str(e)
            else:
                err = None
            if st is not None:
                ok += 1
                age = time.time() - t0
                if ok == 1 or ok % 10 == 0 or interval_s >= 4.0:
                    print("[%6.1fs] ok #%d  status=%s"
                          % (age, ok, st.get("result", st)), flush=True)
            else:
                fail += 1
                if first_fail_at is None:
                    first_fail_at = time.time() - t0
                print("[%6.1fs] FAIL #%d  %s"
                      % (time.time() - t0, fail,
                         err or "no get_status reply"), flush=True)
                try:
                    ace.reopen()
                    reopen += 1
                    if ace.prime(tries=10):
                        print("           reopened + primed", flush=True)
                    else:
                        print("           reopen but prime failed",
                              flush=True)
                except Exception as e2:
                    print("           reopen failed: %s" % e2, flush=True)
            # Sleep the remainder of the interval (idle gap on the wire).
            slept = time.time() - ping_t
            wait = interval_s - slept
            if wait > 0:
                time.sleep(wait)
    finally:
        ace.close()
    elapsed = time.time() - t0
    print("--- soak summary ---", flush=True)
    print("elapsed  : %.1fs (%.1f min)" % (elapsed, elapsed / 60.0))
    print("ok       : %d" % ok)
    print("fail     : %d" % fail)
    print("reopen   : %d" % reopen)
    if first_fail_at is not None:
        print("first_fail_at: %.1fs" % first_fail_at)
    if fail == 0:
        print("result   : PASS — no disconnects observed")
    else:
        print("result   : FAIL — %d missed reply(ies)" % fail)
        sys.exit(1)


def cmd_flash(args: argparse.Namespace) -> None:
    require_klipper_stopped(args.force)
    imgpath = args.bin
    if not os.path.isfile(imgpath):
        sys.exit("firmware file not found: %s" % imgpath)
    data = open(imgpath, "rb").read()
    if not data:
        sys.exit("firmware file is empty")
    c = crc16_mcrf4xx(data)
    md5 = hashlib.md5(data).hexdigest()
    print("image   : %s" % imgpath)
    print("size    : %d bytes" % len(data))
    print("md5     : %s" % md5)
    print("crc16   : 0x%04X" % c)
    print("announce: %s" % args.announce)
    if args.dry:
        print("dry run: nothing sent")
        return
    if not args.yes:
        ans = input("Type yes to flash this image: ").strip()
        if ans != "yes":
            sys.exit("aborted")
    _path, tty = resolve_unit(args.unit, getattr(args, "port", None))
    print("target  : %s" % tty, flush=True)
    ace = Ace(tty)
    try:
        _do_flash(ace, data, c, args.announce, args.attempts)
    finally:
        ace.close()


def _do_flash(ace: Ace, data: bytes, image_crc: int, announce: str,
              attempts: int) -> None:
    for attempt in range(1, attempts + 1):
        print("=== attempt %d/%d ===" % (attempt, attempts), flush=True)
        sent_all = False
        try:
            if not ace.prime():
                print("prime: no link yet, reopening", flush=True)
                ace.reopen()
                continue
            info = ace.rpc("get_info", timeout=3.0)
            print("get_info   :", info, flush=True)
            if info is None:
                ace.reopen()
                continue
            ver = ace.rpc("iap_version", timeout=3.0)
            print("iap_version:", ver, flush=True)
            up = ace.rpc(
                "iap_upgrade",
                {"size": len(data), "crc": image_crc, "version": announce},
                timeout=6.0)
            print("iap_upgrade:", up, flush=True)
            if up is None:
                ace.reopen()
                continue
            code = (up.get("code") if isinstance(up, dict) else None)
            if code not in (None, 0):
                print("iap_upgrade rejected: %s" % up, flush=True)
                continue
            t0 = time.time()
            for off in range(0, len(data), CHUNK):
                ace.chunk(FLASH_BASE + off, data[off:off + CHUNK])
                time.sleep(0.01)
                if (off // CHUNK) % 256 == 0:
                    print("  %6d / %d (%.1fs)" % (
                        off, len(data), time.time() - t0), flush=True)
            print("  sent %d bytes in %.1fs" % (
                len(data), time.time() - t0), flush=True)
            sent_all = True
            time.sleep(0.3)
            try:
                fin = ace.rpc("iap_upgrade_finish", {}, timeout=10)
                print("iap_upgrade_finish:", fin, flush=True)
            except Exception as e:
                # USB often drops on commit; transfer already done.
                print("iap_upgrade_finish: %s (often expected)" % e,
                      flush=True)
            alive = 0
            for i in range(40):
                try:
                    s = ace.rpc("get_status", timeout=2.0)
                except Exception:
                    s = None
                    try:
                        ace.reopen()
                    except Exception:
                        pass
                ok = s is not None
                if ok:
                    alive += 1
                print("  poll %d alive=%s" % (i, ok), flush=True)
                if alive >= 2:
                    info = ace.rpc("get_info", timeout=3.0)
                    print("post-flash get_info:", info, flush=True)
                    print("flash ok")
                    return
                time.sleep(0.5)
            print("image sent; unit did not answer get_status yet — "
                  "power-cycle ACE and check with: "
                  "python tools/ace1_flash.py version", flush=True)
            return
        except Exception as e:
            if sent_all:
                print("transfer completed; post-upload disconnect is expected",
                      flush=True)
                return
            print("attempt %d failed: %s" % (attempt, e), flush=True)
            try:
                ace.reopen()
            except Exception as e2:
                print("reopen failed: %s" % e2, flush=True)
            time.sleep(3)
    sys.exit("flash failed after %d attempts" % attempts)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Flash ACE Pro (Gen 1) firmware on a COSMOS printer "
                    "(stop Klipper first).")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--force", action="store_true",
        help="skip the Klipper-running check")
    common.add_argument(
        "--unit", type=int, default=0,
        help="ACE index in USB order (0 = first / directly connected)")
    common.add_argument(
        "--port", default=None,
        help="serial device path (e.g. COM13 or /dev/ttyACM0); "
             "skips USB auto-detect — use on Windows)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list ACE USB paths and ttys")

    sub.add_parser("version", parents=[common],
                   help="print get_info / iap_version / get_status")

    s = sub.add_parser(
        "soak", parents=[common],
        help="timed get_status pings to catch USB idle drops")
    s.add_argument("--minutes", type=float, default=5.0,
                   help="how long to run (default 5)")
    s.add_argument("--interval", type=float, default=5.0,
                   help="seconds between get_status pings "
                        "(default 5; stock idle drop ~3.3s)")

    f = sub.add_parser("flash", parents=[common],
                       help="flash a raw ACE_V*.bin image")
    f.add_argument("--bin", required=True, dest="bin",
                   help="path to Gen1 .bin")
    f.add_argument("--announce", default=DEFAULT_ANNOUNCE,
                   help="version string sent in iap_upgrade "
                        "(default %s)" % DEFAULT_ANNOUNCE)
    f.add_argument("--dry", action="store_true",
                   help="print hashes only, do not write")
    f.add_argument("--yes", action="store_true",
                   help="skip interactive yes confirmation")
    f.add_argument("--attempts", type=int, default=5,
                   help="retry count on soft failures")
    return p


def main(argv: Optional[List[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    if args.cmd == "list":
        cmd_list(args)
    elif args.cmd == "version":
        cmd_version(args)
    elif args.cmd == "soak":
        cmd_soak(args)
    elif args.cmd == "flash":
        cmd_flash(args)
    else:
        sys.exit("unknown command")


if __name__ == "__main__":
    main()
