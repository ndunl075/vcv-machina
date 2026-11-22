"""Regression tests for deid/olez.py (F1: raw passes never touch compressed blocks, F2: unsorted patches, budgets).
Run: python tests/test_olez.py  (needs olefile; no registry)."""
import os, struct, sys, zlib
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import olefile
from deid import olez
from deid.matcher import Matcher


def make_cfb(stream: bytes, name="Data") -> bytes:
    """Minimal CFB v3: sector 0 FAT, sector 1 directory, then one big stream (>= 4096 bytes, regular sectors)."""
    assert len(stream) >= 4096
    nsec = (len(stream) + 511) // 512
    END, FATSECT, FREE = 0xFFFFFFFE, 0xFFFFFFFD, 0xFFFFFFFF
    fat = [FATSECT, END] + [2 + i + 1 for i in range(nsec - 1)] + [END]
    fat += [FREE] * (128 - len(fat))
    hdr = bytearray(512)
    hdr[0:8] = bytes.fromhex("d0cf11e0a1b11ae1")
    struct.pack_into("<HHHHH", hdr, 24, 0x3E, 3, 0xFFFE, 9, 6)
    struct.pack_into("<IIIIIIII", hdr, 44, 1, 1, 0, 4096, END, 0, END, 0)
    struct.pack_into("<I", hdr, 76, 0)
    for i in range(1, 109):
        struct.pack_into("<I", hdr, 76 + 4 * i, FREE)

    def entry(n, typ, left, right, child, start, size):
        e = bytearray(128)
        nm = n.encode("utf-16le") + b"\0\0"
        e[:len(nm)] = nm
        struct.pack_into("<HBB", e, 64, len(nm), typ, 1)
        struct.pack_into("<III", e, 68, left, right, child)
        struct.pack_into("<I", e, 116, start)
        struct.pack_into("<Q", e, 120, size)
        return bytes(e)
    d = entry("Root Entry", 5, FREE, FREE, 1, END, 0) + entry(name, 2, FREE, FREE, FREE, 2, len(stream)) + b"\0" * 256
    body = stream + b"\0" * (nsec * 512 - len(stream))
    return bytes(hdr) + struct.pack("<128I", *fat) + d + body


def test_f2_unsorted_patches():
    class M:      # patches in the order Matcher.patches returns them: ASCII ones first, then UTF-16 ones
        def patches(self, data):
            return [(4, b"BBBB"), (46, b"CCCC"), (22, b"AAAA")]
    data = b"x" * 60
    out, n = olez.apply_patches_outside(M(), data, [])
    assert n == 3 and out[4:8] == b"BBBB" and out[22:26] == b"AAAA" and out[46:50] == b"CCCC", (n, out)


def test_f1_blocks_never_patched():
    text = b"hello secretname world " * 4
    block = zlib.compress(text, 0)                        # level 0: stored, the text sits literally in the block
    stream = b"plain secretname head " + block + b" tail secretname" + b"\0" * 5000
    cfb = make_cfb(stream)
    o = olefile.OleFileIO(cfb)
    d = o.openstream("Data").read()
    spans = [(s, e) for s, e, _ in olez.find_blocks(d)]
    assert len(spans) == 1
    m = Matcher([("secretname", "pseudoname")])
    prot = olez.container_spans(cfb, {("Data",): spans})
    out, n = olez.patch_container(m, cfb, prot)
    d2 = olefile.OleFileIO(out).openstream("Data").read()
    assert n == 2, n                                       # head and tail text patched, block text not
    assert d2[spans[0][0]:spans[0][1]] == block and zlib.decompress(d2[spans[0][0]:spans[0][1]]) == text
    assert b"pseudoname" in d2[:20] and b"secretname" in d2[spans[0][0]:spans[0][1]]
    # the unprotected raw pass would have corrupted the block (the old behaviour)
    bad, _ = m.replace_bytes(cfb)
    try:
        zlib.decompress(olefile.OleFileIO(bad).openstream("Data").read()[spans[0][0]:spans[0][1]])
        raise AssertionError("expected a corrupt block")
    except zlib.error:
        pass


def test_rewrite_blocks_exact_span():
    text = (b"user secretname saved this file; " * 40)
    block = zlib.compress(text, 6)
    d = b"\0" * 10 + block + b"\0" * 7
    m = Matcher([("secretname", "pseudoname")])
    new, st, spans = olez.rewrite_blocks(d, m, {"left": 20.0})
    assert len(new) == len(d) and st["rewritten"] + st["nofit"] == 1
    if st["rewritten"]:
        assert zlib.decompress(new[10:10 + len(block)]) == text.replace(b"secretname", b"pseudoname")
    assert new[:10] == d[:10] and new[10 + len(block):] == d[10 + len(block):]


def test_budget_exhausted_leaves_block():
    text = os.urandom(300) .hex().encode() * 3 + b" secretname"
    block = zlib.compress(text, 9)
    d = block
    m = Matcher([("secretname", "pseudoname")])
    new, st, _ = olez.rewrite_blocks(d, m, {"left": 0.0})
    assert new == d and st["nofit"] == 1


def test_find_blocks_bounded():
    import time
    t = time.time()
    junk = (b"\x78\x9c" + b"\xff" * 30) * 100000          # 100k false headers
    olez.find_blocks(junk)
    assert time.time() - t < 15


if __name__ == "__main__":
    for k, v in sorted(globals().items()):
        if k.startswith("test_"):
            v(); print("ok", k)
