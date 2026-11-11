"""Lossless capture, torn writes, real FAT/BMP bytes and read-only USB BOT."""
import ctypes as C
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
PIXELS = 240 * 240
MAX_BYTES = 8192 - 16 - 24
WIDE_MAX_BYTES = 16384 - 32 - 24
OWNER = struct.pack('<4I', 0x3143534b, 0xcebcacb4, 0x00f000f0, 0xff0fff0f)
WIDE_OWNER = struct.pack('<4I', 0x3243534b, 0xcdbcacb4, 0x00f000f0, 0xff0fff0f)
PROGRAM = C.CFUNCTYPE(C.c_bool, C.c_uint32, C.c_void_p, C.c_size_t)
ERASE = C.CFUNCTYPE(C.c_bool, C.c_uint32)


class Store(C.Structure):
    _fields_ = [('base', C.c_void_p), ('bytes', C.c_uint32), ('program', PROGRAM), ('erase4k', ERASE)]


class Transaction(C.Structure):
    _fields_ = [('store', C.c_void_p), ('at', C.c_uint32), ('size', C.c_uint32),
                ('written', C.c_uint32), ('failed', C.c_bool)]


def record(payload, sequence=1, committed=True):
    return (struct.pack('<6I', len(payload), ~len(payload) & 0xffffffff, sequence,
                        ~sequence & 0xffffffff, zlib.crc32(payload), 0x31564d43 if committed else 0xffffffff)
            + payload + b'\xff' * (-len(payload) % 4))


def journal(entries=(), second=()):
    sectors = []
    for records in (entries, second):
        data = OWNER + b''.join(records) if records else b''
        assert len(data) <= 8192
        sectors.append(data.ljust(8192, b'\xff'))
    return b''.join(sectors)


def wide_journal(payload, committed=True):
    data = WIDE_OWNER + record(payload, committed=committed)
    assert len(data) <= 16384 - 16
    return data.ljust(16384 - 16, b'\xff') + WIDE_OWNER


class ScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = os.environ.get('KPD_CC') or shutil.which('cc') or shutil.which('clang') or shutil.which('gcc')
        if not cc:
            raise RuntimeError('Native screen checks need KPD_CC or a C11 compiler')
        cls.folder = tempfile.TemporaryDirectory(dir=ROOT / 'artifacts', ignore_cleanup_errors=True)
        binary = Path(cls.folder.name) / ('screen.dll' if sys.platform == 'win32' else 'screen.so')
        args = [cc, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic', '-shared']
        args += ['-Wl,--export-all-symbols'] if sys.platform == 'win32' else ['-fPIC']
        args += ['-I', str(ROOT / 'native')]
        args += [str(ROOT / p) for p in ('native/screen_codec.c', 'native/screen_disk.c',
                                       'native/screen_store.c', 'native/screen_msc.c', 'tests/screen_bridge.c')]
        subprocess.run([*args, '-o', str(binary)], check=True, capture_output=True)
        cls.lib = C.CDLL(str(binary))
        signatures = {
            'screen_context_size': ([], C.c_size_t),
            'screen_name': ([C.c_void_p, C.c_uint, C.c_uint, C.c_void_p], None),
            'screen_encode_height': ([C.c_void_p, C.c_uint, C.c_void_p, C.c_size_t], C.c_size_t),
            'screen_encode': ([C.c_void_p, C.c_void_p, C.c_size_t, C.c_uint], C.c_size_t),
            'screen_encode_sink': ([C.c_void_p, C.c_void_p, C.c_size_t, C.c_uint, C.c_size_t], C.c_size_t),
            'screen_decode': ([C.c_void_p, C.c_size_t, C.c_void_p], C.c_int),
            'screen_mount': ([C.c_void_p, C.c_void_p], C.c_uint),
            'screen_block': ([C.c_void_p, C.c_uint, C.c_void_p], C.c_int),
            'screen_out': ([C.c_void_p, C.c_void_p, C.c_size_t], C.c_int),
            'screen_in': ([C.c_void_p], C.c_int),
            'screen_tx': ([C.c_void_p, C.c_void_p], C.c_uint),
            'screen_phase': ([C.c_void_p], C.c_uint),
            'screen_reset': ([C.c_void_p], None),
            'screen_scan': ([C.c_void_p], C.c_size_t),
            'screen_owned_sector': ([C.c_void_p, C.c_uint], C.c_uint),
            'ksc_store_safe': ([C.POINTER(Store)], C.c_bool),
            'ksc_store_mount': ([C.POINTER(Store), C.c_void_p, C.POINTER(C.c_uint32)], None),
            'ksc_store_append': ([C.POINTER(Store), C.c_void_p, C.c_size_t, C.c_uint32], C.c_bool),
            'ksc_store_clear': ([C.POINTER(Store)], C.c_bool),
            'ksc_store_begin': ([C.POINTER(Store), C.c_size_t, C.c_uint32, C.POINTER(Transaction)], C.c_bool),
            'ksc_store_put': ([C.POINTER(Transaction), C.c_void_p, C.c_size_t], C.c_bool),
            'ksc_store_commit': ([C.POINTER(Transaction), C.c_uint32], C.c_bool),
        }
        for name, (args, result) in signatures.items():
            getattr(cls.lib, name).argtypes = args
            getattr(cls.lib, name).restype = result

    @classmethod
    def tearDownClass(cls):
        if sys.platform != 'win32': cls.folder.cleanup()

    def encode(self, pixels, capacity=MAX_BYTES, chunk=37):
        source = (C.c_uint16 * PIXELS)(*pixels)
        target = C.create_string_buffer(b'\xa5' * (capacity + 16), capacity + 16)
        n = self.lib.screen_encode(source, target, capacity, chunk)
        self.assertEqual(target.raw[capacity:], b'\xa5' * 16)
        return target.raw[:n]

    def decode(self, payload):
        out = (C.c_uint16 * PIXELS)()
        ok = self.lib.screen_decode(payload, len(payload), out)
        return bool(ok), list(out)

    def mount(self, flash):
        self.flash = C.create_string_buffer(flash, len(flash))
        self.ctx = C.create_string_buffer(self.lib.screen_context_size())
        return self.lib.screen_mount(self.ctx, self.flash)

    def store(self, data=b'\xff' * 0x50000):
        self.nor = C.create_string_buffer(b'\xa5' * 4096 + data + b'\x5a' * 4096)
        self.nor_at = C.addressof(self.nor) + 4096
        self.nor_bytes = len(data)
        self.operations, self.fail_operation = [], None

        @PROGRAM
        def program(offset, source, size):
            self.assertLessEqual(offset + size, self.nor_bytes)
            self.assertEqual(C.string_at(self.nor_at + offset, size), b'\xff' * size)
            self.operations.append(('program', offset, size))
            if len(self.operations) == self.fail_operation: return False
            C.memmove(self.nor_at + offset, source, size)
            return True

        @ERASE
        def erase(offset):
            self.assertEqual(offset % 4096, 0)
            self.assertLessEqual(offset + 4096, self.nor_bytes)
            self.operations.append(('erase', offset, 4096))
            if len(self.operations) == self.fail_operation: return False
            C.memset(self.nor_at + offset, 255, 4096)
            return True

        self.program_callback, self.erase_callback = program, erase
        self.storage = Store(self.nor_at, len(data), program, erase)
        return self.storage

    def store_append(self, payload, seq):
        return self.lib.ksc_store_append(C.byref(self.storage), payload, len(payload), seq)

    def store_mount(self, legacy=None):
        self.mount(legacy or b'\xff' * 16384)
        seq = C.c_uint32(1)
        self.lib.ksc_store_mount(C.byref(self.storage), self.ctx, C.byref(seq))
        # Catalog is the first member of the portable test context.
        count_offset = 96 * (C.sizeof(C.c_void_p) + 8)
        return C.c_uint.from_buffer(self.ctx, count_offset).value, seq.value

    def test_external_store_twentyfold_capacity_and_bmp(self):
        self.store()
        pixels = [((x // 20) * 37 + (y // 30) * 3) & 0xffff for y in range(240) for x in range(240)]
        payload = self.encode(pixels)
        self.assertTrue(payload)
        for seq in range(1, 97): self.assertTrue(self.store_append(payload, seq))
        before = self.nor.raw
        self.assertFalse(self.store_append(payload, 97))
        self.assertEqual(self.nor.raw, before)
        self.assertEqual(self.store_mount(), (96, 97))
        self.assertEqual(self.block(153)[66:], struct.pack('<223H', *pixels[:223]))
        self.assertEqual(self.nor.raw[:4096], b'\xa5' * 4096)
        self.assertEqual(self.nor.raw[-4097:-1], b'\x5a' * 4096)

    def test_external_large_images_use_multiple_pairs(self):
        self.store()
        payload = b'x' * WIDE_MAX_BYTES
        for seq in range(1, 21): self.assertTrue(self.store_append(payload, seq))
        before = self.nor.raw
        self.assertFalse(self.store_append(payload, 21))
        self.assertEqual(self.nor.raw, before)
        self.assertEqual(self.store_mount(), (20, 21))
        self.assertTrue(self.lib.ksc_store_clear(C.byref(self.storage)))
        self.assertEqual(C.string_at(self.nor_at, self.nor_bytes), b'\xff' * self.nor_bytes)
        self.assertTrue(all(0 <= at < self.nor_bytes for _, at, _ in self.operations))

    def test_ninety_six_files_mount_across_disjoint_banks_without_extra_catalog_ram(self):
        def bank(size):
            memory = C.create_string_buffer(b'\xa5'*4096+b'\xff'*size+b'\x5a'*4096)
            base = C.addressof(memory)+4096
            @PROGRAM
            def program(offset,source,n):
                self.assertLessEqual(offset+n,size)
                self.assertEqual(C.string_at(base+offset,n),b'\xff'*n)
                C.memmove(base+offset,source,n); return True
            @ERASE
            def erase(offset):
                self.assertEqual(offset%4096,0); self.assertLessEqual(offset+4096,size)
                C.memset(base+offset,255,4096); return True
            return Store(base,size,program,erase),memory,program,erase
        first = bank(0x100000); extra = bank(0x70000)
        for seq in range(1,65):
            self.assertTrue(self.lib.ksc_store_append(C.byref(first[0]),b'x'*WIDE_MAX_BYTES,WIDE_MAX_BYTES,seq))
        before = first[1].raw
        pixels = [0x4321]*PIXELS; payload = self.encode(pixels)
        for seq in range(65,97):
            self.assertTrue(self.lib.ksc_store_append(C.byref(extra[0]),payload,len(payload),seq))
        self.assertEqual(first[1].raw,before)
        self.mount(b'\xff'*16384); seq = C.c_uint32(1)
        for store in (first,extra):self.lib.ksc_store_mount(C.byref(store[0]),self.ctx,C.byref(seq))
        self.assertEqual(C.c_uint.from_buffer(self.ctx,96*(C.sizeof(C.c_void_p)+8)).value,96)
        self.assertEqual(seq.value,97)
        self.assertEqual(self.block(152)[480:491],b'SC000096BMP')
        self.assertEqual(self.block(153+95*2048)[66:],struct.pack('<223H',*pixels[:223]))
        for store in (first,extra):
            self.assertEqual(store[1].raw[:4096],b'\xa5'*4096)
            self.assertEqual(store[1].raw[-4097:-1],b'\x5a'*4096)

    def test_one_mib_bank_holds_sixty_four_maximum_images(self):
        self.store(b'\xff' * 0x100000)
        payload = b'x' * WIDE_MAX_BYTES
        for seq in range(1, 65): self.assertTrue(self.store_append(payload, seq))
        before = self.nor.raw
        self.assertFalse(self.store_append(payload, 65))
        self.assertEqual(self.nor.raw, before)
        self.assertEqual(self.store_mount(), (64, 65))

    def test_external_unknown_data_blocks_all_mutations(self):
        data = bytearray(b'\xff' * 0x50000); data[-4097] = 17
        self.store(bytes(data))
        self.assertFalse(self.lib.ksc_store_safe(C.byref(self.storage)))
        self.assertFalse(self.store_append(b'test', 1))
        self.assertFalse(self.lib.ksc_store_clear(C.byref(self.storage)))
        self.assertFalse(self.operations)

    def test_external_torn_append_preserves_previous_capture(self):
        self.store()
        payload = self.encode([0x1234] * PIXELS)
        self.assertTrue(self.store_append(payload, 1))
        self.fail_operation = len(self.operations) + 3  # CRC/commit publication fails
        self.assertFalse(self.store_append(payload, 2))
        self.assertEqual(self.store_mount(), (1, 3))
        self.fail_operation = None
        self.assertTrue(self.store_append(payload, 3))
        self.assertEqual(self.store_mount(), (2, 4))
        self.assertFalse(self.store_append(payload, 2))

    def test_external_clear_failure_keeps_ownership_for_retry(self):
        for wide in (False, True):
            with self.subTest(wide=wide):
                self.store()
                self.assertTrue(self.store_append(b'x' * (12000 if wide else 6000), 1))
                self.fail_operation = len(self.operations) + (4 if wide else 2)
                self.assertFalse(self.lib.ksc_store_clear(C.byref(self.storage)))
                self.assertTrue(self.lib.ksc_store_safe(C.byref(self.storage)))
                self.fail_operation = None
                self.assertTrue(self.lib.ksc_store_clear(C.byref(self.storage)))
                self.assertEqual(C.string_at(self.nor_at, self.nor_bytes), b'\xff' * self.nor_bytes)

    def test_external_catalog_combines_legacy_and_sorts(self):
        self.store()
        payload = self.encode([0x4321] * PIXELS)
        self.assertTrue(self.store_append(payload, 2))
        legacy = journal([record(payload, 1)])
        self.assertEqual(self.store_mount(legacy), (2, 3))
        root = self.block(129)
        self.assertEqual(root[96:107], b'SC000001BMP')
        self.assertEqual(root[224:235], b'SC000002BMP')

    def test_offline_external_export_reads_all_pairs(self):
        from tools.export_screen207 import export
        pixels = [0x4321] * PIXELS
        payload = self.encode(pixels)
        # One record in each pair exercises the full bank, including its end.
        bank = b''.join(journal([record(payload, seq)]) for seq in range(1, 65))
        with tempfile.TemporaryDirectory(dir=ROOT / 'artifacts', ignore_cleanup_errors=True) as tmp:
            folder = Path(tmp) / 'external'
            report = export(bank, folder, external=True)
            self.assertFalse(report['issues'])
            self.assertEqual(len(report['files']), 64)
            self.assertEqual((folder / 'SC000064.BMP').read_bytes()[66:], struct.pack('<57600H', *pixels))

    def block(self, number):
        out = C.create_string_buffer(512)
        self.assertEqual(self.lib.screen_block(self.ctx, number, out), 1)
        return out.raw

    def test_compact_names_do_not_truncate_hundreds_or_maximum_sequence(self):
        data = b'KSN1' + struct.pack('<HH', 240, 240) + b'USBCEMARKER'.ljust(24, b'\0')
        for seq, name in ((1,'USBCEMARKER01.BMP'), (99,'USBCEMARKER99.BMP'),
                          (100,'USBCEMARKER100.BMP'), (999999,'USBCEMARKER999999.BMP')):
            out = C.create_string_buffer(36)
            self.lib.screen_name(data,len(data),seq,out)
            self.assertEqual(out.value.decode(),name)
        out = C.create_string_buffer(36)
        self.lib.screen_name(b'KL\2',3,41,out)
        self.assertEqual(out.value,b'SC000041.BMP')

    def test_named_tall_image_fat_chain_lfn_and_lossless_pixels(self):
        height = 683
        pixels = [(y // 7 * 53 + x // 17 * 91) & 65535 for y in range(height) for x in range(240)]
        source = (C.c_uint16 * len(pixels))(*pixels)
        target = C.create_string_buffer(len(pixels) * 4)
        n = self.lib.screen_encode_height(source, height, target, len(target))
        self.assertGreater(n, 0)
        metadata = b'KSN1' + struct.pack('<HH', height, 240) + b'USBCEMARKER'.ljust(24, b'\0')
        payload = metadata + target.raw[:n]
        self.store(b'\xff' * 0x100000)
        self.assertTrue(self.store_append(payload, 32))
        self.assertEqual(self.store_mount(), (1, 33))
        root = self.block(129)
        self.assertEqual(root[96:108], b'SC000032BMP\x01')
        entries = [root[i:i+32] for i in range(0, 96, 32) if root[i] != 0xe5]
        self.assertEqual([e[0] for e in entries], [0x42, 1])
        checksum = 0
        for c in b'SC000032BMP': checksum = (((checksum & 1) << 7) + (checksum >> 1) + c) & 255
        self.assertTrue(all(e[11] == 15 and e[13] == checksum and e[12] == 0 and e[26:28] == b'\0\0' for e in entries))
        name = b''.join(bytes(e[j:j+2]) for e in reversed(entries) for j in (1,3,5,7,9,14,16,18,20,22,24,28,30)).decode('utf-16le').split('\0')[0]
        self.assertEqual(name, 'USBCEMARKER32.BMP')
        size = 66 + len(pixels) * 2
        self.assertEqual(struct.unpack_from('<I', root, 124)[0], size)
        bmp = b''.join(self.block(153 + i) for i in range((size + 511)//512))[:size]
        self.assertEqual(struct.unpack_from('<ii', bmp, 18), (240, -height))
        self.assertEqual(bmp[66:], struct.pack('<' + str(len(pixels)) + 'H', *pixels))
        fat = b''.join(self.block(i) for i in range(1, 65))
        clusters = (size + 8191)//8192
        self.assertEqual(struct.unpack_from('<H', fat, (clusters+1)*2)[0], 0xffff)
        self.assertEqual(struct.unpack_from('<H', fat, (clusters+2)*2)[0], 0)
        from tools.export_screen207 import export
        with tempfile.TemporaryDirectory(dir=ROOT/'artifacts', ignore_cleanup_errors=True) as tmp:
            folder = Path(tmp)/'export'
            report = export(C.string_at(self.nor_at,self.nor_bytes),folder,external=True)
            self.assertFalse(report['issues'])
            self.assertEqual((folder/name).read_bytes(),bmp)

    def test_large_reservations_torn_writes_and_clear_retries(self):
        payload = bytes((i * 31 + i // 71) & 255 for i in range(27000))
        for failed in range(1, 7):
            with self.subTest(program=failed):
                self.store(); self.fail_operation = failed
                self.assertFalse(self.store_append(payload,1))
                self.assertEqual(self.store_mount()[0],0)
                self.assertTrue(self.lib.ksc_store_safe(C.byref(self.storage)))
                self.fail_operation = None
                self.assertTrue(self.store_append(payload,2))
                self.assertEqual(self.store_mount(),(1,3))
                self.assertTrue(self.lib.ksc_store_clear(C.byref(self.storage)))
                self.assertEqual(C.string_at(self.nor_at,self.nor_bytes),b'\xff'*self.nor_bytes)
        for failed in range(1,9):
            with self.subTest(erase=failed):
                self.store(); self.assertTrue(self.store_append(payload,1))
                self.fail_operation = len(self.operations) + failed
                self.assertFalse(self.lib.ksc_store_clear(C.byref(self.storage)))
                self.assertTrue(self.lib.ksc_store_safe(C.byref(self.storage)))
                self.fail_operation = None
                self.assertTrue(self.lib.ksc_store_clear(C.byref(self.storage)))
                self.assertEqual(C.string_at(self.nor_at,self.nor_bytes),b'\xff'*self.nor_bytes)

    def test_large_reservations_never_cross_foreign_data_or_bank_end(self):
        data = bytearray(b'\xff' * 0x100000); data[-1] = 13
        self.store(bytes(data)); before = self.nor.raw
        self.assertFalse(self.store_append(b'x'*27000,1))
        self.assertEqual(self.nor.raw,before)
        self.store()
        self.assertFalse(self.store_append(b'x'*131017,1))
        for i in range(1,11): self.assertTrue(self.store_append(b'x'*27000,i))
        before = self.nor.raw
        self.assertFalse(self.store_append(b'x'*27000,11))
        self.assertEqual(self.nor.raw,before)

    def test_maximum_height_last_file_slot_and_three_lfn_entries(self):
        height = 2048; source = (C.c_uint16 * (height * 240))()
        target = C.create_string_buffer(131016)
        n = self.lib.screen_encode_height(source,height,target,len(target))
        self.assertGreater(n,0)
        payload = b'KSN1'+struct.pack('<HH',height,240)+b'ABCDEFGHIJKLMNOPQRSTUVW\0'+target.raw[:n]
        self.store(b'\xff'*0x100000)
        for seq in range(1,96): self.assertTrue(self.store_append(b'old',seq))
        self.assertTrue(self.store_append(payload,999999)); self.assertEqual(self.store_mount(),(96,1000000))
        root = self.block(152); self.assertEqual([root[i] for i in (384,416,448)],[0x43,2,1])
        size = 66 + height*480
        self.assertEqual(struct.unpack_from('<I',root,508)[0],size)
        start = 153+95*2048; last = start+(size-1)//512
        self.assertLess(last,262143)
        self.assertEqual(self.block(last),bytes(512))
        boot = self.block(0)
        self.assertEqual(struct.unpack_from('<I',boot,32)[0],262144)
        self.assertEqual((262144-153)//16,16374)  # FAT16 cluster-count range.

    def tx(self):
        out = C.create_string_buffer(512)
        n = self.lib.screen_tx(self.ctx, out)
        return out.raw[:n]

    def cbw(self, command, length=0, input=True, tag=123):
        p = struct.pack('<IIIBBB', 0x43425355, tag, length, 0x80 if input else 0, 0, len(command))
        p += command.ljust(16, b'\0')
        self.assertEqual(self.lib.screen_out(self.ctx, p, len(p)), 1)

    def finish_in(self):
        packets = []
        for _ in range(17000):
            if self.lib.screen_phase(self.ctx) in (0, 4, 5): return packets
            packets.append(self.tx())
            self.lib.screen_in(self.ctx)
        self.fail('Unbounded BOT response')

    def test_lossless_full_color_streaming_and_chunk_boundaries(self):
        rng = random.Random(207)
        fixtures = [[0] * PIXELS, [0xffff] * PIXELS,
                    [(x * 277) & 65535 for y in range(240) for x in range(240)],
                    [rng.randrange(65536) for _ in range(PIXELS)]]
        for pixels in fixtures:
            for chunk in (1, 37, 2400, PIXELS):
                with self.subTest(chunk=chunk, first=pixels[0]):
                    payload = self.encode(pixels, PIXELS * 4, chunk)
                    self.assertTrue(payload)
                    self.assertEqual(self.decode(payload), (True, pixels))
        self.assertFalse(self.encode(fixtures[-1]))

    def test_forward_only_sink_matches_buffer_and_propagates_failure(self):
        rng = random.Random(214)
        pixels = [rng.randrange(65536) if y < 10 else (x // 10) * 31 for y in range(240) for x in range(240)]
        expected = self.encode(pixels, PIXELS * 4)
        source = (C.c_uint16 * PIXELS)(*pixels)
        for chunk in (1, 127, 2400):
            out = C.create_string_buffer(b'\xa5' * (len(expected) + 16))
            n = self.lib.screen_encode_sink(source, out, len(expected), chunk, len(expected))
            self.assertEqual(out.raw[:n], expected)
            self.assertEqual(out.raw[len(expected):len(expected) + 16], b'\xa5' * 16)
        for failed in (0, 2, 126, 127, 255, len(expected) - 1):
            out = C.create_string_buffer(b'\xa5' * (len(expected) + 16))
            self.assertEqual(self.lib.screen_encode_sink(source, out, len(expected), 37, failed), 0)
            self.assertEqual(out.raw[failed:len(expected) + 16], b'\xa5' * (len(expected) + 16 - failed))

    def test_stream_transaction_requires_complete_matching_crc(self):
        self.store()
        payload = self.encode([0x1234] * PIXELS)
        self.assertTrue(self.store_append(payload, 1))
        original = C.string_at(self.nor_at, 16 + len(record(payload)))
        txn = Transaction()
        self.assertTrue(self.lib.ksc_store_begin(C.byref(self.storage), len(payload), 2, C.byref(txn)))
        self.assertTrue(self.lib.ksc_store_put(C.byref(txn), payload[:3], 3))
        self.assertEqual(self.store_mount(), (1, 3))
        self.assertFalse(self.lib.ksc_store_commit(C.byref(txn), zlib.crc32(payload)))
        self.assertFalse(self.lib.ksc_store_put(C.byref(txn), payload[3:], len(payload) - 3))
        self.assertEqual(self.store_mount(), (1, 3))
        self.assertTrue(self.lib.ksc_store_begin(C.byref(self.storage), len(payload), 3, C.byref(txn)))
        for at in range(0, len(payload), 7):
            piece = payload[at:at + 7]
            self.assertTrue(self.lib.ksc_store_put(C.byref(txn), piece, len(piece)))
        self.assertFalse(self.lib.ksc_store_commit(C.byref(txn), zlib.crc32(payload) ^ 1))
        self.assertEqual(self.store_mount(), (1, 4))
        self.assertTrue(self.lib.ksc_store_begin(C.byref(self.storage), len(payload), 4, C.byref(txn)))
        self.assertTrue(self.lib.ksc_store_put(C.byref(txn), payload, len(payload)))
        self.assertTrue(self.lib.ksc_store_commit(C.byref(txn), zlib.crc32(payload)))
        self.assertFalse(self.lib.ksc_store_commit(C.byref(txn), zlib.crc32(payload)))
        self.assertEqual(self.store_mount(), (2, 5))
        self.assertEqual(C.string_at(self.nor_at, len(original)), original)

    def test_bad_streams_fail_closed(self):
        good = self.encode([0xf800] * PIXELS)
        for data in (good[:-1], good + b'\0', b'\xc1\x01', b'\xc1\0', b'\xc0', b'\xff', b'\x80'):
            with self.subTest(data=data[:4]): self.assertFalse(self.decode(data)[0])
        for data in (b'KL\1\x80\0', b'KL\1\x7f\0', b'KL\1\0\xff', b'KL\1\0\xc1',
                     b'KL\2\x7f', b'KL\2\x7f\0', b'KL\2\x7f\0\1', b'KL\3\0\0'):
            self.assertFalse(self.decode(data)[0])
        for capacity in range(40):
            payload = self.encode([1] * PIXELS, capacity=capacity)
            if payload: self.assertTrue(self.decode(payload)[0])

    def test_previous_capture_format_remains_readable(self):
        # 900 primary tokens repeating 64 black pixels, carried by KL1's
        # original short-distance copy packets, including an overlapping copy.
        legacy = b'KL\1\0\x7f' + b'\xff\0' * 6 + b'\xf4\0'
        self.assertEqual(self.decode(legacy), (True, [0] * PIXELS))
        self.assertEqual(self.mount(journal([record(legacy)])), 1)
        self.assertEqual(self.block(153)[66:], bytes(512 - 66))

    def test_repeated_glyph_rows_use_long_distance_copies(self):
        rng = random.Random(210)
        glyphs = [[rng.randrange(65536) for _ in range(32)] for _ in range(3)]
        pixels = [p for y in range(240) for p in glyphs[y % 3] + [0] * 208]
        for chunk in (1, 37, 2400, PIXELS):
            payload = self.encode(pixels, chunk=chunk)
            self.assertEqual(payload[:3], b'KL\2')
            self.assertEqual(self.decode(payload), (True, pixels))
            at, distances = 3, []
            while at < len(payload):
                tag = payload[at]; at += 1
                if tag == 127:
                    low, high = payload[at:at + 2]; at += 2
                    distances.append((((high & 3) << 8) | low) + 1)
                elif tag < 128: at += tag + 1
                else: at += 1
            self.assertTrue(any(256 < d <= 1024 for d in distances))

    def test_count_only_matches_exact_allocation(self):
        rng = random.Random(211)
        pixels = [rng.randrange(65536) if y < 12 else 0 for y in range(240) for x in range(240)]
        source = (C.c_uint16 * PIXELS)(*pixels)
        payload = self.encode(pixels, capacity=WIDE_MAX_BYTES)
        self.assertGreater(len(payload), MAX_BYTES)
        self.assertLessEqual(len(payload), WIDE_MAX_BYTES)
        for chunk in (1, 37, 2400):
            count = self.lib.screen_encode(source, None, WIDE_MAX_BYTES, chunk)
            self.assertEqual(count, len(payload))
            self.assertEqual(self.encode(pixels, capacity=count, chunk=chunk), payload)
        self.assertFalse(self.encode(pixels))

    def test_spanning_capture_bmp_and_offline_export(self):
        rng = random.Random(212)
        pixels = [rng.randrange(65536) if y < 12 else 0 for y in range(240) for x in range(240)]
        payload = self.encode(pixels, capacity=WIDE_MAX_BYTES)
        self.assertGreater(len(payload), MAX_BYTES)
        image = wide_journal(payload)
        self.assertEqual(self.mount(image), 1)
        self.assertEqual([self.lib.screen_owned_sector(image, s) for s in range(3)], [1, 1, 0])
        bmp = b''.join(self.block(153 + n) for n in range((115266 + 511) // 512))[:115266]
        self.assertEqual(bmp[66:], struct.pack('<57600H', *pixels))
        from tools.export_screen207 import export
        with tempfile.TemporaryDirectory(dir=ROOT / 'artifacts') as directory:
            folder = Path(directory) / 'export'
            report = export(image, folder)
            self.assertEqual(report['issues'], [])
            self.assertTrue(report['spanning_capture_storage'])
            self.assertEqual((folder / report['files'][0]['file']).read_bytes(), bmp)

    def test_spanning_capture_requires_both_owners_crc_and_commit(self):
        payload = self.encode([0x07e0] * PIXELS)
        good = wide_journal(payload)
        self.assertEqual(self.mount(good), 1)
        for at in (0, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 16368, 16372, 16376, 16380):
            corrupt = bytearray(good); corrupt[at] ^= 1
            self.assertEqual(self.mount(bytes(corrupt)), 0)
        self.assertEqual(self.mount(wide_journal(payload, committed=False)), 0)
        missing_tail = good[:-16] + b'\xff' * 16
        self.assertEqual(self.mount(missing_tail), 0)
        self.assertEqual(self.lib.screen_owned_sector(missing_tail, 0), 1)
        self.assertEqual(self.lib.screen_owned_sector(missing_tail, 1), 0)

    def test_journal_torn_append_crc_and_ownership(self):
        payload = self.encode([0x07e0] * PIXELS)
        first = record(payload, 2)
        second = record(payload, 1)
        self.assertEqual(self.mount(journal([first], [second])), 2)
        torn = record(payload, 3, committed=False)
        self.assertEqual(self.mount(journal([first, torn, record(payload, 4)])), 2)
        bad = bytearray(first); bad[-8] ^= 1
        self.assertEqual(self.mount(journal([bytes(bad), record(payload, 5)])), 1)
        for cut in (1, 4, 8, 12, 16, 20, 24, 24 + len(payload) - 1):
            raw = (OWNER + first[:cut]).ljust(8192, b'\xff')
            self.assertEqual(self.mount(raw + b'\xff' * 8192), 0)
        unknown = bytearray(journal([first])); unknown[0] ^= 1
        self.assertEqual(self.mount(bytes(unknown)), 0)
        raw = journal([first]); self.assertGreater(self.lib.screen_scan(raw), 16)
        torn_header = (OWNER + first + b'\x12\0\0\0').ljust(8192, b'\xff')
        self.assertEqual(self.lib.screen_scan(torn_header), 0)
        self.assertEqual(self.mount(torn_header + b'\xff' * 8192), 1)

    def test_fat16_two_copies_and_random_bmp_reads(self):
        pixels = [(x * 277) & 65535 for y in range(240) for x in range(240)]
        payload = self.encode(pixels)
        self.assertTrue(payload)
        self.assertEqual(self.mount(journal([record(payload)])), 1)
        boot = self.block(0)
        self.assertEqual(boot[510:], b'\x55\xaa')
        self.assertEqual(struct.unpack_from('<H', boot, 11)[0], 512)
        fat = b''.join(self.block(i) for i in range(1, 65))
        self.assertEqual(fat, b''.join(self.block(i) for i in range(65, 129)))
        root = self.block(129)
        self.assertEqual(root[96:108], b'SC000001BMP\x01')
        size = struct.unpack_from('<I', root, 124)[0]
        data = b''.join(self.block(i) for i in range(153, 153 + (size + 511) // 512))[:size]
        self.assertEqual(data[:2], b'BM')
        self.assertEqual(struct.unpack_from('<ii', data, 18), (240, -240))
        self.assertEqual(data[66:], struct.pack('<57600H', *pixels))
        order = list(range((size + 511) // 512)); random.Random(4).shuffle(order)
        for n in order:
            self.assertEqual(self.block(153 + n)[:min(512, size - n * 512)], data[n * 512:(n + 1) * 512])
        out = C.create_string_buffer(512)
        self.assertEqual(self.lib.screen_block(self.ctx, 262144, out), 0)

    def test_usb_enumeration_commands_and_read(self):
        self.mount(journal())
        self.cbw(b'\x12\0\0\0\x24\0', 36)
        packets = self.finish_in()
        self.assertEqual(len(packets[0]), 36)
        self.assertIn(b'SCREEN CAPTURES', packets[0])
        self.assertEqual(struct.unpack('<IIIB', packets[-1]), (0x53425355, 123, 0, 0))
        self.cbw(b'\x1a\0\x3f\0\x04\0', 4)
        self.assertEqual(self.finish_in()[0], b'\x03\0\x80\0')
        self.cbw(bytes([0x25]) + bytes(9), 8)
        self.assertEqual(self.finish_in()[0], struct.pack('>II', 262143, 512))
        self.cbw(bytes.fromhex('28000000000000000200'), 1024)
        packets = self.finish_in()
        self.assertEqual(packets[0], self.block(0)); self.assertEqual(packets[1], self.block(1))
        self.assertEqual(struct.unpack_from('<I', packets[-1], 8)[0], 0)

    def test_usb_writes_are_discarded_and_report_write_protection(self):
        image = journal([record(self.encode([0xffff] * PIXELS))])
        self.mount(image)
        self.cbw(bytes.fromhex('2a000000000000000200'), 1024, input=False)
        self.assertEqual(self.lib.screen_phase(self.ctx), 4)
        for _ in range(2): self.assertEqual(self.lib.screen_out(self.ctx, b'\0' * 512, 512), 1)
        self.assertEqual(struct.unpack('<IIIB', self.finish_in()[-1]), (0x53425355, 123, 1024, 1))
        self.assertEqual(self.flash.raw, image)
        self.cbw(bytes.fromhex('030000001200'), 18)
        sense = self.finish_in()[0]; self.assertEqual((sense[2], sense[12]), (7, 0x27))
        self.cbw(bytes.fromhex('28000004000000000100'), 512)
        packets = self.finish_in(); self.assertEqual(packets[0], b'')
        self.assertEqual(packets[-1][-1], 1)
        self.assertEqual(self.lib.screen_out(self.ctx, b'\0' * 31, 31), 0)
        self.assertEqual(self.lib.screen_phase(self.ctx), 5)
        self.lib.screen_reset(self.ctx)
        self.cbw(bytes(6)); self.assertEqual(self.finish_in()[-1][-1], 0)


if __name__ == '__main__': unittest.main()
