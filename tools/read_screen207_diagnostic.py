"""Read-only PRIVATE trace from a qualified KM003C synthetic volume.

Never opens the firmware updater or writes to a device. A trace sector is in
unused space, separate from the FAT and BMP file contents. Output stays private.
"""
import argparse
import json
from pathlib import Path
import re
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ('build', 'uptime_ms', 'state_created_ms', 'initial_keys', 'boot_token',
          'reset_flags', 'mode', 'capture_stage', 'capture_calls', 'encoded_bytes',
          'state_address', 'input_address', 'input_user_data', 'input_reader',
          'file_count', 'efm_status', 'cfsr', 'hfsr', 'current_keys',
          'extension_crc', 'gui_saved_sp')


def decode(sector):
    if len(sector) != 512 or sector[:8] != b'KSC207D2':
        raise ValueError('Expected the private KSC207D2 trace sector')
    report = dict(zip(FIELDS, struct.unpack_from('<21I', sector, 8)))
    count = struct.unpack_from('<I', sector, 472)[0]
    if count > 5:
        raise ValueError('Invalid tagged-state count')
    report.update(schema=1, read_only=True, private_ram_must_not_be_published=True,
                  raw_key_callbacks=[struct.unpack_from('<I', sector, 96 + i * 16)[0] for i in range(6)],
                  tagged_states=[dict(zip(('address', 'allocated_bytes', 'input', 'created_ms',
                    'keys', 'token', 'mode', 'stage', 'captures', 'encoded_bytes'),
                    struct.unpack_from('<10I', sector, 272 + i * 40))) for i in range(count)])
    if report['build'] >= 8:
        report.update(zip(('heap_free_bytes', 'heap_largest_bytes', 'heap_blocks', 'msc_phase',
            'msc_lba', 'msc_blocks', 'msc_tx_size', 'msc_status_sense_asc', 'last_nonread',
            'usb_rx_events', 'usb_tx_events', 'usb_bus_events', 'usb_last_event', 'usb_flags',
            'native_idle_flag'), struct.unpack_from('<15I', sector, 392)))
    if report['build'] >= 9:
        report.update(zip(('watchdog_control', 'watchdog_status', 'watchdog_refreshes',
            'watchdog_last_refresh_ms', 'current_reset_flags'), struct.unpack_from('<5I', sector, 452)))
    if report['build'] >= 11:
        report.update(zip(('capture_pixels', 'capture_bytes', 'capture_flags', 'capture_flushes',
            'bad_area_start', 'bad_area_end', 'capture_ms', 'render_crc'), struct.unpack_from('<8I', sector, 480)))
    if report['build'] >= 18 and sector[312:316] == b'KXE8':
        report.update(zip(('extra_begin','extra_end','extra_status','extra_crc','catalog_limit','settings_guard_crc'),struct.unpack_from('<6I',sector,316)))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--volume', help='Observed removable meter volume, for example E:')
    source.add_argument('--input', type=Path, help='Previously saved 512-byte sector; no USB access')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or not args.output.resolve().is_relative_to((ROOT / 'artifacts').resolve()):
        parser.error('Choose a new private output directory inside artifacts/')
    if args.volume:
        if sys.platform != 'win32' or not re.fullmatch('[A-Za-z]:', args.volume):
            parser.error('Use a Windows drive letter such as E:')
        with open('\\\\.\\' + args.volume.upper(), 'rb', buffering=0) as volume:
            boot = volume.read(512)
            if len(boot) != 512 or boot[3:11] != b'KM003C  ' or boot[510:] != b'\x55\xaa' or \
                    struct.unpack_from('<H', boot, 11)[0] != 512 or \
                    (struct.unpack_from('<H', boot, 19)[0] or struct.unpack_from('<I', boot, 32)[0]) not in (16384, 131072, 262144) or \
                    struct.unpack_from('<I', boot, 39)[0] != 0x3143534b:
                parser.error('This is not the qualified KM003C synthetic volume')
            blocks = struct.unpack_from('<H', boot, 19)[0] or struct.unpack_from('<I', boot, 32)[0]
            volume.seek((blocks - 1) * 512)
            sector = volume.read(512)
    else:
        sector = args.input.read_bytes()
    report = decode(sector)
    args.output.mkdir()
    (args.output / 'trace-sector.bin').write_bytes(sector)
    (args.output / 'trace.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ('build', 'uptime_ms', 'state_created_ms',
        'initial_keys', 'boot_token', 'reset_flags', 'mode', 'capture_stage',
        'capture_calls', 'encoded_bytes', 'file_count')}))


if __name__ == '__main__':
    main()
