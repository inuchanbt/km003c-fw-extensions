"""Private exact-stock LVGL capture/USB ABI emulation; never opens USB.

Native LVGL runs against an owner's ROM, SRAM/heap and NOR snapshots. The LCD
flush is completed without MMIO. EFM and USB endpoints are explicit models;
this is not evidence of physical flash writes or Windows USB enumeration.
Requires unicorn==2.1.3: 2.1.4 misexecuted conditional Thumb instructions in
this private regression, including returning the allocator's high-water mark.
"""
import argparse
import hashlib
import json
import random
from pathlib import Path
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pdinfo.overlay207 import STOCK_HASH
from tools.check_native_arm import load_elf


def decode(data):
    height = 240
    if data[:4] == b'KSN1':
        height, width = struct.unpack_from('<HH', data, 4)
        assert width == 240 and 240 <= height <= 2048
        data = data[32:]
    assert data[:3] in (b'KL\1', b'KL\2')
    version = data[2]
    raw, at = bytearray(), 3
    while at < len(data):
        tag = data[at]; at += 1
        if version == 2 and tag == 127:
            assert at + 2 <= len(data)
            low, high = data[at:at + 2]; at += 2
            distance = (((high & 3) << 8) | low) + 1
            assert distance <= len(raw)
            for _ in range((high >> 2) + 4): raw.append(raw[-distance])
        elif tag < 128:
            assert at + tag + 1 <= len(data)
            raw.extend(data[at:at + tag + 1]); at += tag + 1
        else:
            distance = data[at] + 1; at += 1; assert distance <= len(raw)
            for _ in range(tag - 128 + 3): raw.append(raw[-distance])
        assert len(raw) <= 240 * height * 3
    data = bytes(raw)
    colors, above, previous, pixels = [0] * 64, [0] * 240, 0, []
    at = 0
    while at < len(data):
        tag = data[at]; at += 1
        count, copy = 1, False
        if tag < 64: p = colors[tag]
        elif tag < 128: p = previous; count = tag - 64 + 1
        elif tag < 192:
            r, g, b = (previous >> 11) + ((tag >> 4) & 3) - 2, ((previous >> 5) & 63) + ((tag >> 2) & 3) - 2, (previous & 31) + (tag & 3) - 2
            assert 0 <= r < 32 and 0 <= g < 64 and 0 <= b < 32
            p = (r << 11) | (g << 5) | b
        elif tag == 192: p = int.from_bytes(data[at:at + 2], 'little'); at += 2
        elif tag == 193:
            assert len(pixels) >= 240
            count = data[at]; at += 1; copy = True; assert count
        else: raise AssertionError('Bad capture token')
        for _ in range(count):
            if copy: p = above[len(pixels) % 240]
            above[len(pixels) % 240] = p
            colors[((p >> 11) * 3 + ((p >> 5) & 63) * 5 + (p & 31) * 7) & 63] = p
            pixels.append(p); previous = p
    assert at == len(data) and len(pixels) == 240 * height
    return struct.pack('<' + str(len(pixels)) + 'H', *pixels)


def function_extent(image, wanted):
    """Find one portable leaf function so its tight loop needs no block log.

    Its ARM instructions and memory hooks still execute normally.
    """
    shoff = struct.unpack_from('<I', image, 32)[0]
    width, count = struct.unpack_from('<HH', image, 46)
    sections = [struct.unpack_from('<10I', image, shoff + i * width) for i in range(count)]
    for section in sections:
        if section[1] != 2: continue
        strings_section = sections[section[6]]
        strings = image[strings_section[4]:strings_section[4] + strings_section[5]]
        for at in range(section[4], section[4] + section[5], section[9]):
            name, value, size, info, _, _ = struct.unpack_from('<IIIBBH', image, at)
            label = strings[name:strings.index(b'\0', name)]
            matches = label.startswith(wanted[:-1].encode()) if wanted.endswith('*') else label == wanted.encode()
            if info & 15 == 2 and matches:
                return value & ~1, size
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stock', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--nor', type=Path, required=True)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tall', action='store_true', help='Exercise one long capture and native scroll restoration')
    parser.add_argument('--extra-bank', action='store_true', help='Qualify and capture into the extra bank; requires --capture-only')
    parser.add_argument('--adapter-only', action='store_true', help='Exercise the final extra-bank page and erase boundary without capture')
    parser.add_argument('--capture-only', action='store_true', help='Check one native capture without the separate USB/erase models')
    parser.add_argument('--tall-height', type=int, help='Model a longer native Modules page using the qualified size API')
    parser.add_argument('--release-long', action='store_true', help='Recognize a long capture even when the next keypad sample is release')
    parser.add_argument('--doom-prefix', type=Path, help='Private approved 1 MiB game pack, for explicit reclaim model')
    args = parser.parse_args()
    if args.output.exists() or not args.output.resolve().is_relative_to((ROOT / 'artifacts').resolve()):
        parser.error('Choose a new private output directory in artifacts/')
    rom = args.stock.read_bytes()
    if hashlib.sha256(rom).hexdigest() != STOCK_HASH: parser.error('Exact stock build required')
    meta = json.loads((args.snapshot / 'gui-snapshot.json').read_text())
    assert meta['sram_base'] == 0x1fff8000 and meta['lvgl_heap_base'] == 0x200091e0
    import unicorn
    if unicorn.__version__ != '2.1.3': parser.error('Private stock/LVGL verification requires unicorn==2.1.3')
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_READ, UC_HOOK_BLOCK
    from unicorn.arm_const import UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R9, UC_CPU_ARM_CORTEX_M4
    cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
    cpu.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_M4)
    cpu.mem_map(0, 0x80000); cpu.mem_write(0, b'\xff' * 0x80000); cpu.mem_write(0x4000, rom)
    cpu.mem_map(0x1fff8000, 0x2f000)
    initial_ram = (args.snapshot / 'sram.bin').read_bytes()
    initial_heap = (args.snapshot / 'lvgl-heap.bin').read_bytes()
    cpu.mem_write(0x1fff8000, initial_ram)
    cpu.mem_write(0x200091e0, initial_heap)
    nor = args.nor.read_bytes(); assert len(nor) == 0x400000
    if not args.extra_bank:
        foreign = bytearray(nor); foreign[0x380000] = 17; nor = bytes(foreign)
    cpu.mem_map(0x98000000, len(nor)); cpu.mem_write(0x98000000, nor)
    bank, bank_bytes = 0x98000000, 0x100000
    # Model a completed, explicitly requested format. This does not modify
    # the supplied NOR file or touch a physical meter.
    cpu.mem_write(bank, b'\xff' * bank_bytes)
    cpu.mem_map(0x21000000, 0x10000)
    for base, n in ((0x42a70000, 0x1000), (0x40049000, 0x1000), (0x40010000, 0x1000), (0x40054000, 0x1000), (0xe000e000, 0x1000), (0x400c0000, 0x20000), (0x9c000000, 0x1000)):
        cpu.mem_map(base, n)
    elf = (args.build / 'overlay207-offline.elf').read_bytes()
    symbols = load_elf(cpu, elf)
    cpu.mem_write(0x74000, (args.build / 'extension.bin').read_bytes())
    entry = struct.unpack_from('<I', cpu.mem_read(0x74000 + 20, 4))[0]
    normal_entry = entry
    cpu.mem_write(0x39a18, bytes.fromhex('7047'))
    cpu.mem_write(0x468c2, bytes.fromhex('00207047'))
    cpu.mem_write(0x1fffba0c, b'\0')
    cpu.mem_write(0x1fff8000, struct.pack('<HHI', 0x4b00, 0x4718, 0x2a697))
    cpu.mem_write(0x40010410, struct.pack('<I', 0x110))
    cpu.mem_write(0x40010408, struct.pack('<I', 0x10050))
    writes, erases, pending_flash, recent, notices = [], [], [], [], []
    rendered_bands = []
    flash_error = [0]
    native_reads, watchdog_writes, notice_details = [], [], []
    usb_rx, usb_tx, model_usb = [], [], [False]
    force_large = [False]
    change_second_render, writing_render = [False], [False]
    bus_locked, spi_active, write_enable = [False], [False], [False]
    spi, nor_programs, nor_erases, status_polls = [], [], [], [0]
    fail_nor_erase = [None]
    # Execute the actual stock command routines. Only RTOS scheduling/delay
    # and electrical QSPI behavior are models, with the exact bus handle.
    for at in (0x4cbe6, 0x4ccec, 0x4cffc): cpu.mem_write(at, bytes.fromhex('7047'))
    noise_rows = [6]
    rng = random.Random(211)
    noise_pixels = struct.pack('<' + 'H' * (240 * 6), *(rng.randrange(65536) for _ in range(240 * 6)))
    low_sp = 0x2100fff0

    def word(at): return struct.unpack('<I', cpu.mem_read(at, 4))[0]

    def memory_write(uc, access, address, n, value, user):
        if address in (0x9c000000, 0x9c000010):
            assert bus_locked[0], 'QSPI command issued without native bus lock'
            assert n == 4
            if address == 0x9c000010:
                assert spi_active[0]
                spi.append(value & 255)
            else:
                active = bool(value & 0x20)
                if active and not spi_active[0]: spi.clear()
                if not active and spi_active[0]:
                    command = spi[0]; assert command in (6, 2, 0x20, 5)
                    if command == 6:
                        assert len(spi) == 1; write_enable[0] = True
                    elif command in (2, 0x20):
                        assert write_enable[0] and len(spi) >= 4
                        at = int.from_bytes(bytes(spi[1:4]), 'big')
                        assert 0 <= at < bank_bytes or (args.extra_bank and 0x380000 <= at < 0x3f0000), 'NOR mutation outside qualified banks'
                        write_enable[0] = False
                        if command == 2:
                            data = bytes(spi[4:]); assert data and len(data) <= 256 - (at & 255)
                            assert at + len(data) <= (bank_bytes if at < bank_bytes else 0x3f0000)
                            assert bytes(uc.mem_read(0x98000000 + at, len(data))) == b'\xff' * len(data)
                            uc.mem_write(0x98000000 + at, data); nor_programs.append((at, len(data)))
                        else:
                            assert len(spi) == 4 and at % 4096 == 0
                            if fail_nor_erase[0] == at: fail_nor_erase[0] = None
                            else: uc.mem_write(0x98000000 + at, b'\xff' * 4096)
                            nor_erases.append(at)
                    else: assert len(spi) == 1
                spi_active[0] = active
        if address == 0x40049008:
            assert n == 4 and value in (0x0123, 0x3210)
            watchdog_writes.append(value)
        if address == 0x40010414:
            uc.mem_write(0x40010410, struct.pack('<I', word(0x40010410) & ~value))
        if address == 0x4001040c:
            previous = word(address)
            old_mode, new_mode = previous >> 4 & 7, value >> 4 & 7
            assert new_mode in (0, 1, 4), 'Only readonly, single program and sector erase are allowed'
            if old_mode != new_mode:
                assert previous & 1, 'PEMODE permission must be enabled before changing PEMOD'
                assert not pending_flash, 'Mode changed while flash was still busy'
        if address == 0xe000ed0c:
            raise AssertionError('Unexpected reset while modeling a completing/rejected flash operation')
        if address < 0x80000:
            assert 0x78000 <= address < 0x7c000 and n == 4
            assert 0x200091e0 <= uc.reg_read(UC_ARM_REG_PC) < 0x200111e0, 'Flash operation did not run from owned RAM'
            mode = word(0x4001040c) >> 4 & 7
            if mode == 4:
                assert address % 8192 == 0
                if not flash_error[0]: erases.append(address)
            else:
                assert mode == 1 and word(address) == 0xffffffff
                if not flash_error[0]: writes.append(address)
            assert not pending_flash
            pending_flash.append([address, mode, word(address), flash_error[0], 3])
            uc.mem_write(0x40010410, bytes(4))
        if address == 0x40010400 and value == 0x3210:
            pass  # Nonzero FAPRT models successful native two-key unlock.

    def memory_read(uc, access, address, n, value, user):
        if bank <= address < bank + bank_bytes or bank + 0x380000 <= address < bank + 0x3f0000:
            assert bus_locked[0], 'Mapped capture data read without native bus lock'
        if address == 0x9c000010:
            assert bus_locked[0] and spi_active[0] and spi == [5]
            status_polls[0] += 1
            uc.mem_write(address, bytes(4))  # Model completed WIP after native delay.

    def trace(uc, address, size, user):
        nonlocal low_sp
        if address == (symbols.get('render_capture', 0) & ~1):
            writing_render[0] = bool(uc.reg_read(UC_ARM_REG_R2))
        if address in (0x4cbe6, 0x4ccec):
            assert uc.reg_read(UC_ARM_REG_R0) == 0x1fffb4c4
            if address == 0x4cbe6:
                assert not bus_locked[0], 'Recursive native bus acquisition'
                bus_locked[0] = True
            else:
                assert bus_locked[0]; bus_locked[0] = False
        if address == 0x24606: native_reads.append(address)
        if force_large[0] and address == (symbols['flush_capture'] & ~1):
            area = struct.unpack('<4h', uc.mem_read(uc.reg_read(UC_ARM_REG_R1), 8))
            pixels = uc.reg_read(UC_ARM_REG_R2)
            for y in range(max(0, area[1]), min(noise_rows[0], area[3] + 1)):
                uc.mem_write(pixels + (y - area[1]) * 480, noise_pixels[y * 480:(y + 1) * 480])
        if change_second_render[0] and writing_render[0] and address == (symbols['flush_capture'] & ~1):
            pixels = uc.reg_read(UC_ARM_REG_R2)
            pixel = bytes(uc.mem_read(pixels, 1))[0]
            uc.mem_write(pixels, bytes([pixel ^ 1]))
        if address == (symbols.get('notice', 0) & ~1):
            notices.append(bytes(uc.mem_read(uc.reg_read(UC_ARM_REG_R1), 32)).split(b'\0')[0].decode())
            notice_details.append(bytes(uc.mem_read(uc.reg_read(UC_ARM_REG_R2), 32)).split(b'\0')[0].decode())
        if args.tall and address == (symbols['flush_capture'] & ~1):
            area = struct.unpack('<4h', uc.mem_read(uc.reg_read(UC_ARM_REG_R1), 8))
            rendered_bands.append((area, bytes(uc.mem_read(uc.reg_read(UC_ARM_REG_R2), (area[3] - area[1] + 1) * 480))))
        if model_usb[0] and address in (0x510ee, 0x5120c):
            ep, ptr, n = (uc.reg_read(r) for r in (UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3))
            if address == 0x510ee: usb_rx.append((ep, ptr, n))
            else: usb_tx.append((ep, bytes(uc.mem_read(ptr, n))))
        if pending_flash:
            operation = pending_flash[0]; operation[4] -= 1
            if not operation[4]:
                at, mode, before, error, _ = pending_flash.pop()
                if error: uc.mem_write(at, struct.pack('<I', before))
                elif mode == 4: uc.mem_write(at, b'\xff' * 8192)
                uc.mem_write(0x40010410, struct.pack('<I', 0x100 | (error or 0x10)))
        low_sp = min(low_sp, uc.reg_read(UC_ARM_REG_SP))
        recent.append(address)
        if len(recent) > 8: del recent[0]

    cpu.hook_add(UC_HOOK_MEM_WRITE, memory_write)
    cpu.hook_add(UC_HOOK_MEM_READ, memory_read, begin=bank, end=bank + bank_bytes - 1)
    cpu.hook_add(UC_HOOK_MEM_READ, memory_read, begin=bank + 0x380000, end=bank + 0x3f0000 - 1)
    cpu.hook_add(UC_HOOK_MEM_READ, memory_read, begin=0x9c000010, end=0x9c000013)
    crc_extent = function_extent(elf, 'ksc_crc_update')
    quiet_extents = [extent for name in ('ksc_crc_update', 'blank', 'blank.*', 'erased')
                     if (extent := function_extent(elf, name))]
    if quiet_extents:
        # Keep actual ARM CRC execution and write monitoring. Logging every
        # bitwise CRC loop block dominates the private two-redraw test time.
        cursor = 0
        for start, size in sorted(quiet_extents):
            first = struct.unpack('<H', cpu.mem_read(start, 2))[0]
            leaf_stack = ((first & 255).bit_count() + ((first >> 8) & 1)) * 4 if first & 0xfe00 == 0xb400 else 0
            def leaf_entry(uc, address, size, user, stack=leaf_stack):
                nonlocal low_sp
                assert not pending_flash, 'Portable read began while flash was busy'
                low_sp = min(low_sp, uc.reg_read(UC_ARM_REG_SP) - stack)
            if cursor < start: cpu.hook_add(UC_HOOK_BLOCK, trace, begin=cursor, end=start - 1)
            cpu.hook_add(UC_HOOK_BLOCK, leaf_entry, begin=start, end=start)
            cursor = start + size
        cpu.hook_add(UC_HOOK_BLOCK, trace, begin=cursor, end=0xffffffff)
    else:
        cpu.hook_add(UC_HOOK_BLOCK, trace)

    def call(at, *arguments):
        direct_disk = at in (symbols.get('ksc_disk_read'), symbols.get('ksc207_nor_doom'), symbols.get('ksc207_nor_reclaim_doom'),symbols.get('extra_program'),symbols.get('extra_erase'))
        if direct_disk:
            assert not bus_locked[0]; bus_locked[0] = True  # Unit caller owns the read lock.
        cpu.reg_write(UC_ARM_REG_SP, 0x2100fff0); cpu.reg_write(UC_ARM_REG_LR, 0x101)
        for reg, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), arguments): cpu.reg_write(reg, value)
        try: cpu.emu_start(at | 1, 0x100, count=300_000_000 if args.tall_height else 80_000_000,
                           timeout=300_000_000 if args.tall_height else 110_000_000)
        except Exception as exc: raise RuntimeError(f'ARM stopped near {[hex(x) for x in recent]}') from exc
        assert cpu.reg_read(UC_ARM_REG_PC) == 0x100, f'ARM did not return near {[hex(x) for x in recent]}'
        assert cpu.reg_read(UC_ARM_REG_SP) == 0x2100fff0
        if direct_disk: bus_locked[0] = False
        assert not bus_locked[0] and not spi_active[0], 'Native bus was not released'
        return cpu.reg_read(UC_ARM_REG_R0)

    def set_keys(keys=(), now=0):
        for key, at in ((27, 0x42a7021c), (10, 0x42a7022c), (20, 0x42a70220), (19, 0x42a70224)):
            cpu.mem_write(at, struct.pack('<I', int(key not in keys)))
        cpu.mem_write(0x1fffba20, struct.pack('<I', now & 0xffffffff))

    # Run the exact native raw-GPIO chord predicates, which bypass LVGL.
    set_keys((27, 10)); assert call(0x9130) == 1
    set_keys((20, 19)); assert call(0x9130) == call(0x9148) == 0
    set_keys((10,)); assert call(0x9130) == call(0x9148) == 0
    set_keys(); assert call(symbols['kpd207_choose_callback']) == normal_entry
    cpu.reg_write(UC_ARM_REG_R9, 1); call(entry); assert cpu.reg_read(UC_ARM_REG_R9) == 0
    input_device = call(0x30ab4, 0); reader = word(input_device + 4)
    assert reader != 0x24607
    owner = word(input_device + 12)
    assert 0x200091e4 <= owner < 0x200111e0 and word(owner) == 0x3253434b
    if args.adapter_only:
        assert args.extra_bank and word(owner+928) == 7
        source = bytes(range(256)); cpu.mem_write(0x21009000,source)
        assert call(symbols['extra_program'],0x6ff00,0x21009000,256) == 1
        assert bytes(cpu.mem_read(bank+0x3eff00,256)) == source
        assert bytes(cpu.mem_read(bank+0x3f0000,0x10000)) == nor[0x3f0000:]
        assert bytes(cpu.mem_read(bank+bank_bytes,0x280000)) == nor[bank_bytes:0x380000]
        assert call(symbols['extra_erase'],0x6f000) == 1
        assert bytes(cpu.mem_read(bank+0x380000,0x70000)) == b'\xff'*0x70000
        assert bytes(cpu.mem_read(bank,bank_bytes)) == b'\xff'*bank_bytes
        assert bytes(cpu.mem_read(bank+0x3f0000,0x10000)) == nor[0x3f0000:]
        args.output.mkdir()
        report=dict(hardware_test=False,native_spi_commands=True,extra_final_page_program=True,
            extra_final_sector_erase=True,protected_ranges_unchanged=True,bus_lock_verified=True)
        (args.output/'verified.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report));return
    set_keys((20, 19), 1)
    for n in range(6): assert call(word(0x1fffb4fc + n * 16)) == 0
    set_keys((), 2); call(word(0x1fffb4fc))
    set_keys((20,), 3); assert call(word(0x1fffb4fc + 32)) == 0
    set_keys((20,), 152); assert call(word(0x1fffb4fc + 32)) == 0
    set_keys((20,), 153); assert call(word(0x1fffb4fc + 32)) == 1
    set_keys((), 154); call(word(0x1fffb4fc))
    display = call(0x2a6a4)
    original_flush = word(display + 12)
    original_group = word(input_device + 0x5c)
    if args.tall_height:
        assert args.tall and 300 <= args.tall_height <= 2048
        # Find the real retained Modules window, then extend only its native
        # scrollable container. This fixture is an explicit emulator model.
        root = word(display + 0x48); win = call(0x34cd0, root, 0)
        assert word(win + 28) == 0x3c9f9
        page = word(word(win + 36)); scroll = word(word(page + 36) + 4)
        top = struct.unpack('<h', cpu.mem_read(page + 18, 2))[0]
        # Disable auto-fit/layout only in this explicit synthetic fixture;
        # the production overlay never changes either native container flag.
        cpu.mem_write(word(scroll+36),bytes(4))
        call(0x35c04,scroll,240,args.tall_height-top)

    def keys(keys=(), now=0):
        count = len(watchdog_writes)
        set_keys(keys, now); call(reader, input_device, 0x21000000)
        assert watchdog_writes[count:] == [0x0123, 0x3210], 'Every native or suppressed keypad read must refresh WDT exactly once'
        return bytes(cpu.mem_read(0x21000000, 16))

    before_chord = len(native_reads)
    keys((20, 19), 100); keys((20, 19), 599); call(entry)
    assert len(native_reads) == before_chord, 'Native reader side effects ran before chord suppression'
    assert not writes and not nor_programs
    keys((20,), 599); keys((), 599); call(entry); assert not writes and not nor_programs
    keys((20, 19), 0xffffff00); keys((20, 19), 0xffffff00 + 499); call(entry); assert not writes and not nor_programs
    before_gui = bytes(cpu.mem_read(0x200091e0, 0x8000))
    keys(() if args.release_long else (20, 19), 0xffffff00 + (2000 if args.tall else 500))
    if not args.tall: keys((), 0xffffff00 + 501)
    call(entry)
    assert nor_programs and not nor_erases and not writes and not erases, f'Capture did not save: {notices}'
    assert word(display + 12) == original_flush and word(input_device + 0x5c) == original_group
    assert word(0x40010400) == 0 and word(0x40010408) == 0x10050
    capture_bank = bank + (0x380000 if args.extra_bank else 0)
    flash = bytes(cpu.mem_read(capture_bank, 16384))
    assert flash[:4] in (b'KSC1', b'KSC2', b'KSC3')
    n, complement, sequence, seq_check, crc, committed = struct.unpack_from('<6I', flash, 16)
    assert n ^ complement == sequence ^ seq_check == 0xffffffff and sequence == 1 and committed == 0x31564d43
    payload = bytes(cpu.mem_read(capture_bank + 40, n)); assert zlib.crc32(payload) == crc
    print('Native GUI captured to modeled NOR; command bounds and readback passed.', flush=True)
    height = struct.unpack_from('<H', payload, 4)[0] if payload[:4] == b'KSN1' else 240
    if args.tall_height: assert height >= args.tall_height - 2, height
    assert word(owner + 892) == 240 * height and word(owner + 896) == n
    assert word(owner + 900) == 0 and word(owner + 904) >= 2
    rgb = decode(payload)
    colors = len(set(struct.unpack('<' + str(240 * height) + 'H', rgb)))
    assert colors > 2, 'Expected a real native color GUI, not a blank or synthetic capture'
    if args.extra_bank:
        assert args.capture_only and word(owner+928) == 7
        assert bytes(cpu.mem_read(bank,bank_bytes)) == b'\xff'*bank_bytes
        assert bytes(cpu.mem_read(bank+bank_bytes,0x280000)) == nor[bank_bytes:0x380000]
        assert bytes(cpu.mem_read(bank+0x3f0000,0x10000)) == nor[0x3f0000:]
    if args.capture_only:
        assert word(owner + 924) == 0, 'Capture plan must never outlive its stack frame'
        args.output.mkdir(); (args.output/'screen.rgb565').write_bytes(rgb)
        (args.output/'capture-sectors.bin').write_bytes(bytes(cpu.mem_read(bank,bank_bytes)))
        if args.extra_bank: (args.output/'extra-bank.bin').write_bytes(bytes(cpu.mem_read(bank+0x380000,0x70000)))
        report = dict(schema=1,usb_access=False,hardware_test=False,native_gui_capture=True,
            extra_bank=args.extra_bank,extra_status=word(owner+928),catalog_arm_bytes=776,protected_ranges_unchanged=True,height=height,encoded_bytes=n,name=payload[8:32].split(b'\0')[0].decode(),stack_bytes=0x2100fff0-low_sp)
        (args.output/'verified.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report));return
    if args.tall:
        assert height > 240, 'Fixture must contain a vertically overflowing native page'
        frames = []
        for area, pixels in rendered_bands:
            if area[1] == 0: frames.append(bytearray())
            frames[-1].extend(pixels)
        assert len(frames) % 2 == 0 and len(frames) >= 4
        assert all(len(f) == 115200 for f in frames)
        assert frames[:len(frames)//2] == frames[len(frames)//2:]
        # Every original object's geometry must be restored, including the
        # native page and all offscreen descendants. Ignore newly allocated
        # capture notice/state; inspect the qualified old native heap blocks.
        at = 0
        after_gui = bytes(cpu.mem_read(0x200091e0, 0x8000))
        changed_coordinates = []
        while at < 0x7ffc:
            header = struct.unpack_from('<I', before_gui, at)[0]; size = header >> 1
            if not size or at + 4 + size > len(before_gui): break
            if header & 1 and size >= 56:
                callback = struct.unpack_from('<I', before_gui, at + 4 + 28)[0]
                if callback & 1 and 0x10000 < callback < 0x738c0:
                    if before_gui[at+20:at+28] != after_gui[at+20:at+28]: changed_coordinates.append(hex(0x200091e0+at+4))
            at += 4 + size
        assert not changed_coordinates, changed_coordinates
        # First viewport includes its header once. This fixture fits in two
        # positions; retain only the previously unseen tail of position two.
        # Each additional viewport contributes at most its page body. The
        # final view may clamp at the bottom; crop only the unseen tail.
        top = 32  # Qualified Modules window header in the retained fixture.
        expected = bytes(frames[0]); remaining = height - 240
        for frame in frames[1:len(frames)//2]:
            rows = min(remaining,240-top); expected += frame[-rows*480:]; remaining -= rows
        assert remaining == 0 and rgb == expected
        args.output.mkdir(); (args.output/'native-rgb565.bin').write_bytes(rgb)
        (args.output/'capture-sectors.bin').write_bytes(bytes(cpu.mem_read(bank, bank_bytes)))
        report = dict(schema=1, usb_access=False, hardware_test=False, tall_native_capture=True,
            height=height, encoded_bytes=n, name=payload[8:32].split(b'\0')[0].decode(),
            scroll_restored=True, two_redraws_equal=True, stitched_pixels_equal=True,
            stack_bytes=0x2100fff0-low_sp, colors=colors)
        (args.output/'verified.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report));return
    count = len(nor_programs)
    # Native dialogs may clean every child of the system layer. Input-owned
    # state must survive, clean its notice exactly once, and remain normal.
    layer = call(0x2a6fe, 0)
    for _ in range(64):
        obj = call(0x34cd0, layer, 0)
        if not obj: break
        call(0x34a0a, obj)
    assert word(input_device + 12) == owner and word(input_device + 4) == reader
    call(entry)
    assert not word(0x400c0804) & 2
    keys((20, 19), 2000); call(entry); assert len(nor_programs) == count
    keys((20,), 2001); call(entry); assert len(nor_programs) == count
    keys((), 2002); call(entry)
    keys((20, 19), 3000); keys((20, 19), 3500); keys((), 3501); call(entry); assert len(nor_programs) > count
    assert word(display + 12) == original_flush
    saved_flash = bytes(cpu.mem_read(bank, bank_bytes))
    if 'stream_bytes' in symbols:
        # A changed second frame may reserve/write bytes, but must never
        # publish a BMP or alter either previously committed image.
        change_second_render[0] = True
        count = len(nor_programs)
        keys((), 3600); keys((20, 19), 4000); keys((20, 19), 4500); keys((), 4501); call(entry)
        change_second_render[0] = False
        assert len(nor_programs) > count and notices[-1] == 'CAPTURE FAILED'
        assert notice_details[-1] == 'DISPLAY CHANGED / RETRY'
        after = bytes(cpu.mem_read(bank, bank_bytes))
        for at, size in nor_programs[count:]:
            assert saved_flash[at:at + size] == b'\xff' * size, 'Uncommitted frame overwrote prior data'
        saved_flash = after

    def boot(held=()):
        nonlocal entry
        cpu.mem_write(0x1fff8000, initial_ram); cpu.mem_write(0x200091e0, initial_heap)
        cpu.mem_write(0x468c2, bytes.fromhex('00207047')); cpu.mem_write(0x1fffba0c, b'\0')
        cpu.mem_write(0x1fff8000, struct.pack('<HHI', 0x4b00, 0x4718, 0x2a697))
        set_keys(held, 0); entry = call(symbols['kpd207_choose_callback'])
        assert entry == normal_entry
        cpu.reg_write(UC_ARM_REG_R9, 1); call(entry)
        assert cpu.reg_read(UC_ARM_REG_R9) == 0

    # The real native registration and setup dispatch run. Only the endpoint
    # transfers are modeled; no claim of electrical USB enumeration is made.
    cpu.mem_write(0x510ee, bytes.fromhex('00207047'))
    cpu.mem_write(0x5120c, bytes.fromhex('00207047'))
    # Model the already initialized native EP1 IN FIFO (at least 64 bytes).
    cpu.mem_write(0x400c0104, struct.pack('<I', (32 << 16) | 128))
    model_usb[0] = True
    boot((19, 20)); assert word(0x400c0804) & 2
    set_keys((), 249); call(entry); assert word(0x20008df0 + 0x18) == 0x1fff8b34
    set_keys((), 250); call(entry); assert not word(0x400c0804) & 2
    usb_interface = word(0x20008df0 + 0x234)
    assert usb_interface and word(0x20008df0 + 0x18) != 0x1fff8b34

    def setup(request):
        cpu.mem_write(0x21001000, request)
        cpu.mem_write(0x21001020, struct.pack('<II', 0x21001100, 512))
        result = call(0x517f8, 0, 0x21001000, 0x21001020, 0x21001024)
        return result, bytes(cpu.mem_read(word(0x21001020), word(0x21001024))) if result == 1 else b''

    result, device_descriptor = setup(bytes.fromhex('8006000100001200'))
    assert result == 1 and len(device_descriptor) == 18 and device_descriptor[4:7] == bytes(3)
    assert device_descriptor[8:12] == bytes.fromhex('c95f07d2'), 'Capture PID must differ from factory APP/DFU'
    result, configuration = setup(bytes.fromhex('800600020000ff00'))
    assert result == 1 and len(configuration) == 32 and configuration[14:17] == bytes.fromhex('080650')
    assert setup(bytes.fromhex('0009010000000000'))[0] == 1
    call(entry)
    result, lun = setup(bytes.fromhex('a1fe000000000100'))
    assert result == 1 and lun == b'\0'
    assert setup(bytes.fromhex('a1fe000001000100'))[0] == 0
    usb_state = word(0x20008df0 + 0x234)
    # The optional trace lives in free space, leaving FAT and BMP layout intact.
    assert call(symbols['ksc_disk_read'], usb_state + 44, 262143, 0x21003000) == 1
    diagnostic_sector = bytes(cpu.mem_read(0x21003000, 512))
    from tools.read_screen207_diagnostic import decode as decode_diagnostic
    diagnostic_report = decode_diagnostic(diagnostic_sector)
    assert diagnostic_report['boot_token'] == 1 and diagnostic_report['mode'] == 1
    assert diagnostic_report['file_count'] == 2 and diagnostic_report['capture_calls'] == 0
    event_callback = word(0x20008df0 + 0x308)
    call(event_callback, 0, 7); call(entry)
    assert usb_rx[-1][0] == 1 and usb_rx[-1][2] == 64
    out_callback = word(0x20008df0 + 0x2c8 + 12)
    in_callback = word(0x20008df0 + 0x280 + 12)
    cbw = struct.pack('<IIIBBB', 0x43425355, 17, 512, 0x80, 0, 10) + bytes.fromhex('28000000000000000100') + bytes(6)
    cpu.mem_write(usb_rx[-1][1], cbw); call(out_callback, 0, 1, 31); call(entry)
    assert usb_tx[-1][0] == 0x81 and len(usb_tx[-1][1]) == 512 and usb_tx[-1][1][510:] == b'\x55\xaa'
    call(in_callback, 0, 0x81, 512); call(entry)
    assert usb_tx[-1] == (0x81, struct.pack('<IIIB', 0x53425355, 17, 0, 0))
    call(in_callback, 0, 0x81, 13); call(entry)
    assert usb_rx[-1][2] == 64
    # USB and clear suppress native dialog side effects for arbitrarily long
    # periods. Keep the native WDT refresh that lives in the reader prologue.
    usb_input = call(0x30ab4, 0)
    usb_reader = word(usb_input + 4)
    for mode in range(1, 6):
        usb_owner = word(usb_input + 12)
        cpu.mem_write(usb_owner + 836, bytes([mode]))
        for now in (150000, 300000):
            set_keys((), now); count = len(watchdog_writes); reads = len(native_reads)
            call(usb_reader, usb_input, 0x21000000)
            assert watchdog_writes[count:] == [0x0123, 0x3210]
            assert len(native_reads) == reads and cpu.mem_read(0x21000000 + 14, 1) == b'\0'
    cpu.mem_write(usb_owner + 836, b'\x01')
    assert call(symbols['ksc_disk_read'], usb_state + 44, 262143, 0x21003000) == 1
    diagnostic_sector = bytes(cpu.mem_read(0x21003000, 512))
    diagnostic_report = decode_diagnostic(diagnostic_sector)
    assert diagnostic_report['watchdog_refreshes'] >= 10 and diagnostic_report['watchdog_last_refresh_ms'] == 300000
    result, _ = setup(bytes.fromhex('21ff000000000000'))
    assert result == 1; call(entry)
    assert bytes(cpu.mem_read(bank, bank_bytes)) == saved_flash

    # Clear is entered using OK alone on the export screen. The drive must
    # disconnect and settle before a separate release + two-second confirm.
    set_keys((10,), 1000); call(entry); set_keys((10,), 2999); call(entry)
    assert not word(0x400c0804) & 2 and not erases
    set_keys((10,), 3000); call(entry); assert word(0x400c0804) & 2 and not erases
    set_keys((10,), 3250); call(entry); set_keys((), 3251); call(entry)
    set_keys((10,), 3300); call(entry); set_keys((10,), 5299); call(entry); assert not erases
    set_keys((10,), 5300); call(entry)
    assert nor_erases and not erases and bytes(cpu.mem_read(bank, bank_bytes)) == b'\xff' * bank_bytes
    cleared_blocks = len(nor_erases)
    assert word(0x40010400) == 0 and word(0x40010408) == 0x10050
    # A sector without the exact capture ownership is preserved, even on clear.
    unknown = bytearray(saved_flash); unknown[0] ^= 1
    cpu.mem_write(bank, bytes(unknown)); boot((19, 20))
    set_keys((), 250); call(entry)
    set_keys((10,), 1000); call(entry); set_keys((10,), 3000); call(entry)
    set_keys((10,), 3250); call(entry); set_keys((), 3251); call(entry)
    set_keys((10,), 3300); call(entry); set_keys((10,), 5300); call(entry)
    assert len(nor_erases) == cleared_blocks and bytes(cpu.mem_read(bank, bank_bytes)) == unknown
    flash_code = symbols['ksc207_flash_start'] & ~1
    code = bytes(cpu.mem_read(flash_code, symbols['ksc207_flash_end'] - flash_code))
    cpu.mem_write(0x21002000, code)
    for at, mode in ((0x74000, 0), (0x7c000, 0), (0x78001, 0), (0x78004, 1), (0x78000, 2)):
        assert call(0x21002001, at, 0, mode) == 0
    # Recreating a native driver while a runtime chord is down cannot turn
    # it into export. Test both a consumed token and a restarted late task.
    for token in (0, 1):
        boot()
        cpu.mem_write(0x400c0804, bytes(4))
        current = call(0x30ab4, 0)
        cpu.mem_write(current + 4, struct.pack('<I', 0x24607))
        cpu.mem_write(current + 12, bytes(4))
        for i, fn in enumerate((0x90e9, 0x90fb, 0x910d, 0x911f, 0x9131, 0x9149)):
            cpu.mem_write(0x1fffb4fc + i * 16, struct.pack('<I', fn))
        set_keys((19, 20), 6000); cpu.reg_write(UC_ARM_REG_R9, token); call(entry)
        assert not word(0x400c0804) & 2
    # Force a deterministic larger native redraw. It must span both blank
    # sectors, expose the same pixels, preserve an existing image, and clear
    # only when both sector ownership markers remain valid.
    cpu.mem_write(bank, b'\xff' * bank_bytes); boot()
    noise_rows[0] = 2 if n > 6000 else 6
    force_large[0] = True
    keys((20, 19), 100); keys((20, 19), 600); keys((), 601); call(entry)
    force_large[0] = False
    wide_flash = bytes(cpu.mem_read(bank, 16384))
    assert wide_flash[:4] == wide_flash[-16:-12] == b'KSC2', f'Wide capture did not save: {list(zip(notices, notice_details))}'
    wide_n, inverse, sequence, seq_inverse, wide_crc, commit = struct.unpack_from('<6I', wide_flash, 16)
    assert 8152 < wide_n <= 16328 and wide_n ^ inverse == sequence ^ seq_inverse == 0xffffffff
    assert commit == 0x31564d43 and zlib.crc32(wide_flash[40:40 + wide_n]) == wide_crc
    wide_rgb = decode(wide_flash[40:40 + wide_n])
    noise_bytes = noise_rows[0] * 480
    assert wide_rgb[:noise_bytes] == noise_pixels[:noise_bytes] and wide_rgb[noise_bytes:] == rgb[noise_bytes:]
    count = len(nor_programs)
    keys((), 601); keys((20, 19), 1000); keys((20, 19), 1500); keys((), 1501); call(entry)
    assert len(nor_programs) > count and bytes(cpu.mem_read(bank, 16384)) == wide_flash
    boot((19, 20)); set_keys((), 250); call(entry)
    wide_usb = word(0x20008df0 + 0x234)
    wide_catalog = word(wide_usb + 44)
    assert word(wide_catalog + 768) == 2 and word(wide_catalog + 4) == wide_n
    assert call(symbols['ksc_disk_read'], wide_usb + 44, 153, 0x21003000) == 1
    assert bytes(cpu.mem_read(0x21003000, 2)) == b'BM'
    assert bytes(cpu.mem_read(0x21003000 + 66, 446)) == wide_rgb[:446]
    set_keys((10,), 1000); call(entry); set_keys((10,), 3000); call(entry)
    set_keys((10,), 3250); call(entry); set_keys((), 3251); call(entry)
    set_keys((10,), 3300); call(entry); set_keys((10,), 5300); call(entry)
    assert len(nor_erases) > cleared_blocks and bytes(cpu.mem_read(bank, bank_bytes)) == b'\xff' * bank_bytes
    cleared_blocks = len(nor_erases)
    unknown_wide = bytearray(wide_flash); unknown_wide[-16] ^= 1
    cpu.mem_write(bank, bytes(unknown_wide)); boot((19, 20)); set_keys((), 250); call(entry)
    set_keys((10,), 1000); call(entry); set_keys((10,), 3000); call(entry)
    set_keys((10,), 3250); call(entry); set_keys((), 3251); call(entry)
    set_keys((10,), 3300); call(entry); set_keys((10,), 5300); call(entry)
    assert len(nor_erases) == cleared_blocks and bytes(cpu.mem_read(bank, 16384)) == unknown_wide
    # A rejected write may report RDY + an error without OPTEND. It must
    # return failure from owned RAM, restore controls and preserve bytes.
    cpu.mem_write(0x78000, b'\xff' * 16384)
    ram_code = call(0x32a94, len(code)); assert ram_code
    cpu.mem_write(ram_code, code); flash_error[0] = 2
    cpu.mem_write(0x40010410, struct.pack('<I', 0x100))
    assert call(ram_code | 1, 0x78000, 0x12345678, 0) == 0
    assert word(0x78000) == 0xffffffff and word(0x40010410) == 0x102
    assert word(0x40010400) == 0 and word(0x4001040c) == 0 and word(0x40010408) == 0x10050
    flash_error[0] = 0; call(0x32b80, ram_code)
    if args.doom_prefix:
        doom = args.doom_prefix.read_bytes(); assert len(doom) == bank_bytes
        cpu.mem_write(bank, doom)
        assert call(symbols['ksc207_nor_doom']) == 1
        fail_nor_erase[0] = 0x2000
        assert call(symbols['ksc207_nor_reclaim_doom']) == 0
        assert call(symbols['ksc207_nor_doom']) == 1, 'Interrupted reclamation lost ownership'
        assert call(symbols['ksc207_nor_reclaim_doom']) == 1
        assert bytes(cpu.mem_read(bank, bank_bytes)) == b'\xff' * bank_bytes
        foreign = bytearray(doom); foreign[64] ^= 1
        cpu.mem_write(bank, bytes(foreign)); mutations = len(nor_erases) + len(nor_programs)
        assert call(symbols['ksc207_nor_reclaim_doom']) == 0
        assert len(nor_erases) + len(nor_programs) == mutations
    assert bytes(cpu.mem_read(bank + bank_bytes, 0x400000 - bank_bytes)) == nor[bank_bytes:]
    args.output.mkdir()
    (args.output / 'screen.rgb565').write_bytes(rgb)
    (args.output / 'capture-sectors.bin').write_bytes(saved_flash)
    (args.output / 'wide-capture-sectors.bin').write_bytes(wide_flash)
    (args.output / 'trace-sector.bin').write_bytes(diagnostic_sector)
    report = dict(schema=1, usb_access=False, hardware_test=False, native_gui_capture=True,
                  width=240, height=240, encoded_bytes=n, colors=colors, flash_word_writes=len(writes),
                  erase_operations=len(erases), callback_restored=True, native_input_group_preserved=True,
                  native_usb_setup_dispatch=True, modeled_bulk_read=True, confirmed_clear=True,
                  unknown_sector_preserved=True, flash_address_guards=True,
                  native_reserved_chords_avoided=True, clear_disconnect_before_confirmation=True,
                  raw_chord_filtered=True, state_survives_native_layer_cleanup=True,
                  export_mode_latched_after_native_input_init=True, emulator_version=unicorn.__version__,
                  native_reader_side_effects_suppressed=True, task_boot_token_consumed=True,
                  recreated_driver_cannot_select_export=True, private_diagnostic_sector=True,
                  single_word_program_mode=True, permission_before_mode=True,
                  modeled_busy_and_flag_clear=True, rejected_write_without_optend_returns=True,
                  native_and_suppressed_keypad_refresh_watchdog=True,
                  usb_and_clear_modes_refresh_watchdog=True,
                  compressed_size_and_pixel_crc_verified=True, spanning_capture=True,
                  streamed_compressed_output='stream_bytes' in symbols,
                  changed_second_frame_uncommitted='stream_bytes' in symbols,
                  wide_encoded_bytes=wide_n, spanning_overwrite_refused=True,
                  spanning_clear_preflights_both_owners=True,
                  portable_crc_executes_without_inner_block_log=bool(crc_extent),
                  external_storage_bytes=bank_bytes, native_nor_single_page_commands=True,
                  nor_program_operations=len(nor_programs), nor_erase_operations=len(nor_erases),
                  native_bus_arbitration_enforced=True, nor_status_polls=status_polls[0],
                  outside_nor_partition_unchanged=True, multiple_large_captures=True,
                  approved_doom_reclaim_and_retry=bool(args.doom_prefix),
                  observed_stack_bytes=0x2100fff0-low_sp,
                  limits='EFM and LCD completion are models. Physical persistence and USB/Windows mounting need hardware validation.')
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
