"""Offline export of PRIVATE capture sectors or a complete internal readback.

Never opens USB, writes firmware, clears storage or relaxes updater checks.
This also checks that a hardware readback changed only in capture storage.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.check_screen207 import decode

BASE, CAPTURE, END = 0x4000, 0x78000, 0x7c000
OWNER = (0x3143534b, 0xcebcacb4, 0x00f000f0, 0xff0fff0f)
WIDE_OWNER = (0x3243534b, 0xcdbcacb4, 0x00f000f0, 0xff0fff0f)


def export(data, output, expected=None, external=False, extra=None):
    if external:
        if expected is not None or not 0x100000 <= len(data) <= 0x400000:
            raise ValueError('External export needs at least the first 1 MiB; check internal bytes separately')
        data = data[:0x100000]
        if extra is not None:
            if len(extra) != 0x70000: raise ValueError('Extra bank must be exactly 448 KiB')
            data += extra
    elif len(data) == 0x80000 - BASE:
        if expected is not None:
            if len(expected) != len(data) or data[:CAPTURE - BASE] != expected[:CAPTURE - BASE] or data[END - BASE:] != expected[END - BASE:]:
                raise ValueError('Internal bytes outside capture storage differ')
        data = data[CAPTURE - BASE:END - BASE]
    elif len(data) != END - CAPTURE:
        raise ValueError('Expected the 16 KiB capture region or full 0x4000..0x80000 readback')
    elif expected is not None:
        raise ValueError('Checking protected bytes requires a full internal readback')
    files, issues = [], []
    regions, any_wide = [], False
    base = 0
    while base < len(data):
        pair = data[base:base + 16384]
        tag, inverse, span, inverse_span = struct.unpack_from('<4I', pair)
        if tag == 0x3343534b and tag ^ inverse == 0xffffffff and span ^ inverse_span == 0xffffffff and \
                16384 <= span <= 131072 and span % 16384 == 0 and base + span <= len(data):
            any_wide = True
            region = data[base:base + span]
            owner = (tag, inverse, span, inverse_span)
            if struct.unpack_from('<4I', region, span - 16) == owner:
                regions.append((base // 8192, region[:-16], span - 56, owner))
            else: issues.append(dict(sector=base // 8192, reason='incomplete long capture ownership'))
            base += span; continue
        elif struct.unpack_from('<4I', pair) == WIDE_OWNER:
            any_wide = True
            if struct.unpack_from('<4I', pair, len(pair) - 16) == WIDE_OWNER:
                regions.append((base // 8192, pair[:-16], 16328, WIDE_OWNER))
            else:
                issues.append(dict(sector=base // 8192 + 1, reason='incomplete spanning capture ownership'))
        else:
            regions.extend((base // 8192 + s, pair[s * 8192:(s + 1) * 8192], 8152, OWNER) for s in range(2))
        base += 16384
    for sector, p, maximum, owner in regions:
        if p == b'\xff' * len(p):
            continue
        if struct.unpack_from('<4I', p) != owner:
            issues.append(dict(sector=sector, reason='no complete capture ownership'))
            continue
        at = 16
        while at + 24 <= len(p):
            n, inverse, seq, seq_inverse, crc, commit = struct.unpack_from('<6I', p, at)
            if n == 0xffffffff:
                if p[at:] != b'\xff' * (len(p) - at):
                    issues.append(dict(sector=sector, offset=at, reason='nonblank unreserved tail'))
                break
            if not 0 < n <= maximum or n ^ inverse != 0xffffffff or at + 24 + ((n + 3) & ~3) > len(p):
                issues.append(dict(sector=sector, offset=at, reason='incomplete or damaged length reservation'))
                break
            payload = p[at + 24:at + 24 + n]
            if commit == 0x31564d43 and seq ^ seq_inverse == 0xffffffff and 0 < seq <= 999999:
                if zlib.crc32(payload) != crc:
                    issues.append(dict(sector=sector, offset=at, reason='CRC mismatch'))
                else:
                    pixels = decode(payload)
                    header = bytearray(66)
                    struct.pack_into('<2sI4xI', header, 0, b'BM', 66 + len(pixels), 66)
                    struct.pack_into('<IiiHHII', header, 14, 40, 240, -(len(pixels) // 480), 1, 16, 3, len(pixels))
                    struct.pack_into('<III', header, 54, 0xf800, 0x07e0, 0x001f)
                    prefix = ''.join(chr(c) for c in payload[8:32].split(b'\0')[0] if 65 <= c <= 90 or 48 <= c <= 57) if payload[:4] == b'KSN1' else None
                    name = f'{prefix or "SCREEN"}{seq:02d}.BMP' if prefix is not None else f'SC{seq:06d}.BMP'
                    files.append((seq, bytes(header) + pixels, n, name))
            else:
                issues.append(dict(sector=sector, offset=at, reason='uncommitted record'))
            at += 24 + ((n + 3) & ~3)
            if owner != OWNER: break
    if len({seq for seq, _, _, _ in files}) != len(files):
        raise ValueError('Duplicate capture sequence numbers')
    report = dict(schema=1, usb_access=False, firmware_writes=0, capture_region_sha256=hashlib.sha256(data).hexdigest(),
                  protected_internal_bytes_match=True if expected is not None else None,
                  spanning_capture_storage=any_wide, external_storage=external, files=[], issues=issues)
    output.mkdir()
    for seq, bmp, n, name in sorted(files):
        with (output / name).open('xb') as handle:
            handle.write(bmp)
        report['files'].append(dict(file=name, bytes=len(bmp), encoded_bytes=n, sha256=hashlib.sha256(bmp).hexdigest()))
    (output / 'export.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--expected-internal', type=Path)
    parser.add_argument('--external', action='store_true', help='Export the first 1 MiB NOR capture bank')
    parser.add_argument('--extra-input', type=Path, help='Qualified 448 KiB extra bank at NOR 0x380000')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or not args.output.resolve().is_relative_to((ROOT / 'artifacts').resolve()):
        parser.error('Choose a new private directory inside artifacts/')
    expected = args.expected_internal.read_bytes() if args.expected_internal else None
    if args.extra_input and not args.external: parser.error('Extra input requires --external')
    print(json.dumps(export(args.input.read_bytes(), args.output, expected, args.external,
                            args.extra_input.read_bytes() if args.extra_input else None), indent=2))


if __name__ == '__main__':
    main()
