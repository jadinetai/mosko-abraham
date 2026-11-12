"""Compare two ELF64 files section by section (SHA-256 of each section's file bytes).

  python -I tools/g3/compare_sections.py <reference.elf> <candidate.elf>

Exit 0 only if every section with SHF_ALLOC (i.e. everything the loader maps) is identical.
Non-allocated sections (.symtab, .strtab, .shstrtab) are reported but do not decide.
"""
import hashlib
import json
import struct
import sys

SHF_ALLOC = 0x2
SHT_NOBITS = 8


def sections(path):
    d = open(path, "rb").read()
    shoff, = struct.unpack_from("<Q", d, 0x28)
    shentsize, shnum, shstrndx = struct.unpack_from("<HHH", d, 0x3A)
    sh = [struct.unpack_from("<IIQQQQIIQQ", d, shoff + i * shentsize) for i in range(shnum)]
    names = sh[shstrndx][4]
    out = {}
    for name_off, kind, flags, addr, offset, size, *_ in sh:
        name = d[names + name_off:d.index(b"\0", names + name_off)].decode() or "<null>"
        body = b"" if kind == SHT_NOBITS else d[offset:offset + size]
        out[name] = {"alloc": bool(flags & SHF_ALLOC), "addr": hex(addr), "size": size,
                     "sha256": hashlib.sha256(body).hexdigest()}
    return out


ref, cand = sections(sys.argv[1]), sections(sys.argv[2])
report = {n: {"alloc": r["alloc"], "same": cand.get(n) == r, "reference": r, "candidate": cand.get(n)}
          for n, r in ref.items()}
extra = sorted(set(cand) - set(ref))
alloc_same = all(v["same"] for v in report.values() if v["alloc"]) and not extra
print(json.dumps({"loaded_sections_identical": alloc_same, "extra_sections_in_candidate": extra,
                  "sections": {n: {"alloc": v["alloc"], "same": v["same"]} for n, v in report.items()}}, indent=1))
sys.exit(0 if alloc_same else 1)
