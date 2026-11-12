"""Print an ELF64 kernel's entry, load segments, sections and key symbols (stdlib only).

  python tools/elfinfo.py build/abraham-kernel.elf
"""

import json
import struct
import sys

KEY_SYMBOLS = ("abr_entry", "abr_kmain", "abr_trap", "abr_isr_table", "abr_isr_spurious", "abr_df_stack_top")


def info(path):
    data = open(path, "rb").read()
    if data[:4] != b"\x7fELF" or data[4] != 2:
        raise SystemExit("not an ELF64 file")
    (e_type, e_machine, _, entry, phoff, shoff, _, _, phentsize, phnum,
     shentsize, shnum, shstrndx) = struct.unpack_from("<HHIQQQIHHHHHH", data, 16)
    segments = []
    for i in range(phnum):
        p_type, flags, _, vaddr, _, filesz, memsz, align = struct.unpack_from("<IIQQQQQQ", data, phoff + i * phentsize)
        perms = ("R" if flags & 4 else "-") + ("W" if flags & 2 else "-") + ("X" if flags & 1 else "-")
        segments.append({"type": hex(p_type), "flags": perms, "vaddr": hex(vaddr),
                         "filesz": filesz, "memsz": memsz, "align": align})
    sections = [struct.unpack_from("<IIQQQQIIQQ", data, shoff + i * shentsize) for i in range(shnum)]
    strtab = sections[shstrndx][4]

    def name(table_offset, offset):
        end = data.index(b"\0", table_offset + offset)
        return data[table_offset + offset:end].decode()

    section_list = [{"name": name(strtab, s[0]), "addr": hex(s[3]), "size": s[5]} for s in sections if s[0]]
    symbols = {}
    for s in sections:
        if s[1] == 2:  # SHT_SYMTAB
            names = sections[s[6]][4]
            for j in range(s[5] // 24):
                st_name, _, _, _, value, _ = struct.unpack_from("<IBBHQQ", data, s[4] + j * 24)
                symbol = name(names, st_name)
                if symbol in KEY_SYMBOLS:
                    symbols[symbol] = hex(value)
    return {"type": e_type, "machine": hex(e_machine), "entry": hex(entry), "segments": segments,
            "sections": section_list, "symbols": symbols, "size": len(data)}


if __name__ == "__main__":
    print(json.dumps(info(sys.argv[1]), indent=1))
