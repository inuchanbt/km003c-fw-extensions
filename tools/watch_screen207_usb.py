"""Read-only PRIVATE capture of a briefly appearing KM003C USB volume.

Qualifies size and boot metadata before reading trace/BMP content. Other
removable volumes are skipped. Never writes to a device or changes drivers.
"""
import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.read_screen207_diagnostic import decode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--expected', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=300)
    parser.add_argument('--observe-seconds', type=int, default=0,
                        help='Keep reading traces for this long after the first qualified mount')
    args = parser.parse_args()
    if sys.platform != 'win32' or not 1 <= args.seconds <= 900:
        parser.error('Windows required; choose 1..900 seconds')
    if not 0 <= args.observe_seconds < args.seconds:
        parser.error('Observation must be shorter than the overall wait')
    if args.output.exists() or not args.output.resolve().is_relative_to((ROOT / 'artifacts').resolve()):
        parser.error('Choose a new private output directory inside artifacts/')
    expected = {entry['file']: entry for entry in json.loads((args.expected / 'export.json').read_text())['files']}
    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.GetLogicalDrives.restype = C.c_uint32
    kernel.GetDriveTypeW.argtypes = [C.c_wchar_p]
    kernel.GetDriveTypeW.restype = C.c_uint
    kernel.GetDiskFreeSpaceExW.argtypes = [C.c_wchar_p, C.POINTER(C.c_ulonglong), C.POINTER(C.c_ulonglong), C.POINTER(C.c_ulonglong)]
    kernel.GetDiskFreeSpaceExW.restype = C.c_int
    args.output.mkdir()
    started = time.monotonic(); copied = set(); traces = 0; last_drive = None
    mounted_at = None; first_uptime = None; previous_uptime = None; copied_all = False
    log = (args.output / 'events.jsonl').open('x', encoding='utf-8')

    def event(kind, **values):
        record = dict(elapsed_ms=round((time.monotonic() - started) * 1000), event=kind, **values)
        log.write(json.dumps(record) + '\n'); log.flush()
        if kind != 'trace' or traces % 50 == 1:
            print(json.dumps(record), flush=True)

    event('waiting_for_qualified_volume')
    while time.monotonic() - started < args.seconds:
        mask = kernel.GetLogicalDrives(); found = False
        for number in range(26):
            if not mask & (1 << number): continue
            drive = chr(65 + number) + ':'; root = drive + '\\'
            if kernel.GetDriveTypeW(root) != 2: continue
            available, total, free = C.c_ulonglong(), C.c_ulonglong(), C.c_ulonglong()
            if not kernel.GetDiskFreeSpaceExW(root, C.byref(available), C.byref(total), C.byref(free)): continue
            if total.value not in (8376320, 67059712, 134135808): continue
            try:
                with open('\\\\.\\' + drive, 'rb', buffering=0) as volume:
                    boot = volume.read(512)
                    if len(boot) != 512 or boot[3:11] != b'KM003C  ' or boot[510:] != b'\x55\xaa' or \
                            struct.unpack_from('<H', boot, 11)[0] != 512 or \
                            (struct.unpack_from('<H', boot, 19)[0] or struct.unpack_from('<I', boot, 32)[0]) not in (16384, 131072, 262144) or \
                            struct.unpack_from('<I', boot, 39)[0] != 0x3143534b:
                        continue
                    found = True
                    if drive != last_drive: event('meter_volume_found', drive=drive); last_drive = drive
                    blocks = struct.unpack_from('<H', boot, 19)[0] or struct.unpack_from('<I', boot, 32)[0]
                    volume.seek((blocks - 1) * 512); sector = volume.read(512)
                trace = decode(sector); traces += 1
                if mounted_at is None:
                    mounted_at = time.monotonic(); first_uptime = trace['uptime_ms']
                if previous_uptime is not None and trace['uptime_ms'] < previous_uptime:
                    event('uptime_rolled_back', previous=previous_uptime, current=trace['uptime_ms'])
                    raise RuntimeError('Meter rebooted during observation')
                previous_uptime = trace['uptime_ms']
                (args.output / f'trace-{traces:04d}.bin').write_bytes(sector)
                (args.output / 'latest-trace.json').write_text(json.dumps(trace, indent=2) + '\n')
                event('trace', uptime_ms=trace['uptime_ms'], mode=trace['mode'], files=trace['file_count'],
                      initial_keys=trace['initial_keys'], token=trace['boot_token'],
                      reset_flags=trace['reset_flags'], tagged_states=len(trace['tagged_states']),
                      cfsr=trace['cfsr'], hfsr=trace['hfsr'],
                      heap_free_bytes=trace.get('heap_free_bytes'), heap_largest_bytes=trace.get('heap_largest_bytes'),
                      usb_rx_events=trace.get('usb_rx_events'), usb_tx_events=trace.get('usb_tx_events'),
                      last_nonread=trace.get('last_nonread'), usb_last_event=trace.get('usb_last_event'),
                      watchdog_refreshes=trace.get('watchdog_refreshes'),
                      watchdog_last_refresh_ms=trace.get('watchdog_last_refresh_ms'))
                copied_before = len(copied)
                for name, metadata in expected.items():
                    if name in copied: continue
                    event('copy_start', file=name)
                    data = (Path(root) / name).read_bytes()
                    digest = hashlib.sha256(data).hexdigest()
                    if len(data) != metadata['bytes'] or digest != metadata['sha256']:
                        (args.output / (name + '.mismatch.bin')).write_bytes(data)
                        raise ValueError('USB BMP differs from qualified internal readback')
                    (args.output / name).write_bytes(data); copied.add(name)
                    event('copy_verified', file=name, bytes=len(data), sha256=digest)
                if len(copied) == len(expected):
                    if not copied_all:
                        event('all_files_verified', copied=len(copied)); copied_all = True
                    # A large copy can itself exceed the observation time.
                    # Take another live trace after it instead of reporting
                    # the stale sample collected before file transfer.
                    if time.monotonic() - mounted_at >= args.observe_seconds and copied_before == len(expected):
                        event('observation_complete', copied=len(copied), first_uptime_ms=first_uptime,
                              final_uptime_ms=trace['uptime_ms'], traces=traces)
                        log.close(); return
            except (OSError, ValueError) as exc:
                event('read_error', drive=drive, error=str(exc))
        if not found and last_drive is not None:
            event('meter_volume_disappeared', drive=last_drive); last_drive = None
            if args.observe_seconds:
                log.close()
                raise RuntimeError('Qualified meter volume disappeared during observation')
        time.sleep(0.15)
    event('finished', copied=len(copied), traces=traces); log.close()
    raise SystemExit('Timed out before verification and observation completed')


if __name__ == '__main__':
    main()
