"""Cut a SoundFont (SF2 or SF3) down to the presets the app plays.

    uv run python tools/soundfont/trim_sf3.py MuseScore_General.sf3 \
        apps/mobile/assets/viewer/musescore-guitars.sf3

The app's score viewer (alphaTab) plays guitar from MuseScore_General (GM programs 24-30) and its
metronome click (percussion bank 128, key 33); piano and everything else stay on the small
Sonivox font, which the viewer loads first (a later font's presets win). MuseScore_General is
40 MB (its piano alone is 15 MB); the guitars and the click are about 2 MB. Samples are copied
byte for byte (SF3 keeps each as Ogg Vorbis), so nothing is re-encoded: only the preset,
instrument and sample tables are rebuilt with new indices and offsets. See the SoundFont 2.04
spec, section 7 ("hydra").
"""

import argparse
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

KEEP = {(0, p) for p in (24, 25, 26, 27, 28, 29, 30)} | {(128, 0)}
PERCUSSION_KEYS = {33}  # alphaTab's metronome click (SynthConstants.MetronomeKey)
GEN_KEY_RANGE, GEN_INSTRUMENT, GEN_SAMPLE_ID = 43, 41, 53
COMPRESSED = 0x10  # SF3: sample data is an Ogg Vorbis stream; start/end are byte offsets

# Record layouts of the hydra sub-chunks (little-endian).
PHDR = struct.Struct("<20sHHHIII")
BAG = struct.Struct("<HH")
MOD = struct.Struct("<HHhHH")
GEN = struct.Struct("<HH")
INST = struct.Struct("<20sH")
SHDR = struct.Struct("<20sIIIIIBbHH")
Row = tuple[Any, ...]  # one unpacked record


@dataclass
class Chunk:
    tag: bytes
    data: bytes


def read_chunks(data: bytes) -> list[Chunk]:
    chunks, pos = [], 0
    while pos + 8 <= len(data):
        tag, size = data[pos : pos + 4], struct.unpack_from("<I", data, pos + 4)[0]
        chunks.append(Chunk(tag, data[pos + 8 : pos + 8 + size]))
        pos += 8 + size + (size & 1)
    return chunks


def chunk(tag: bytes, data: bytes) -> bytes:
    return tag + struct.pack("<I", len(data)) + data + (b"\0" if len(data) & 1 else b"")


def records(data: bytes, layout: struct.Struct) -> list[Row]:
    return [layout.unpack_from(data, i) for i in range(0, len(data), layout.size)]


def trim(font: bytes) -> bytes:
    assert font[:4] == b"RIFF" and font[8:12] == b"sfbk", "not a SoundFont"
    lists = {
        c.data[:4]: read_chunks(c.data[4:]) for c in read_chunks(font[12:]) if c.tag == b"LIST"
    }
    smpl = next(c.data for c in lists[b"sdta"] if c.tag == b"smpl")
    hydra = {c.tag: c.data for c in lists[b"pdta"]}
    phdr, pbag = records(hydra[b"phdr"], PHDR), records(hydra[b"pbag"], BAG)
    pmod, pgen = records(hydra[b"pmod"], MOD), records(hydra[b"pgen"], GEN)
    inst, ibag = records(hydra[b"inst"], INST), records(hydra[b"ibag"], BAG)
    imod, igen = records(hydra[b"imod"], MOD), records(hydra[b"igen"], GEN)
    shdr = records(hydra[b"shdr"], SHDR)

    def zones(bags: list[Row], start: int, end: int) -> list[tuple[range, range]]:
        """(generator indices, modulator indices) of bags start..end-1."""
        return [
            (range(bags[b][0], bags[b + 1][0]), range(bags[b][1], bags[b + 1][1]))
            for b in range(start, end)
        ]

    def key_range(gens: list[Row], zone: range) -> tuple[int, int] | None:
        for g in zone:
            if gens[g][0] == GEN_KEY_RANGE:
                return gens[g][1] & 0xFF, gens[g][1] >> 8
        return None

    def wanted(gens: list[Row], zone: range, percussion: bool) -> bool:
        span = key_range(gens, zone)
        return (
            not percussion or span is None or any(span[0] <= k <= span[1] for k in PERCUSSION_KEYS)
        )

    out_phdr: list[Row] = []
    out_pbag: list[Row] = []
    out_pmod: list[Row] = []
    out_pgen: list[Row] = []
    out_inst: list[Row] = []
    out_ibag: list[Row] = []
    out_imod: list[Row] = []
    out_igen: list[Row] = []
    inst_map: dict[tuple[int, bool], int] = {}
    sample_map: dict[int, int] = {}
    kept_samples: list[int] = []

    def keep_instrument(i: int, percussion: bool) -> int:
        if (i, percussion) in inst_map:
            return inst_map[(i, percussion)]
        new_index = len(out_inst)
        out_inst.append((inst[i][0], len(out_ibag)))
        for gen_range, mod_range in zones(ibag, inst[i][1], inst[i + 1][1]):
            if not wanted(igen, gen_range, percussion):
                continue
            out_ibag.append((len(out_igen), len(out_imod)))
            out_imod.extend(imod[m] for m in mod_range)
            for g in gen_range:
                oper, amount = igen[g]
                if oper == GEN_SAMPLE_ID:
                    if amount not in sample_map:
                        sample_map[amount] = len(kept_samples)
                        kept_samples.append(amount)
                    amount = sample_map[amount]
                out_igen.append((oper, amount))
        inst_map[(i, percussion)] = new_index
        return new_index

    for p in range(len(phdr) - 1):  # the last record is the terminal "EOP"
        name, preset, bank, bag_index, library, genre, morphology = phdr[p]
        if (bank, preset) not in KEEP:
            continue
        percussion = bank == 128
        out_phdr.append((name, preset, bank, len(out_pbag), library, genre, morphology))
        for gen_range, mod_range in zones(pbag, bag_index, phdr[p + 1][3]):
            if not wanted(pgen, gen_range, percussion):
                continue
            out_pbag.append((len(out_pgen), len(out_pmod)))
            out_pmod.extend(pmod[m] for m in mod_range)
            for g in gen_range:
                oper, amount = pgen[g]
                if oper == GEN_INSTRUMENT:
                    amount = keep_instrument(amount, percussion)
                out_pgen.append((oper, amount))

    # Samples: copy each one's data and give it new offsets. Compressed (SF3) samples are byte
    # ranges with loop points relative to the sample; plain SF2 samples are 16-bit frame ranges
    # with absolute loop points and need 46 zero frames after each (spec 7.10).
    new_smpl = bytearray()
    out_shdr: list[Row] = []
    for old in kept_samples:
        name, start, end, loop_start, loop_end, rate, pitch, correction, link, kind = shdr[old]
        if kind & COMPRESSED:
            offset = len(new_smpl)
            new_smpl += smpl[start:end]
            out_shdr.append((name, offset, offset + end - start, loop_start, loop_end, rate, pitch,
                             correction, sample_map.get(link, 0), kind))  # fmt: skip
        else:
            offset = len(new_smpl) // 2
            new_smpl += smpl[start * 2 : end * 2] + b"\0" * 92
            shift = offset - start
            out_shdr.append((name, offset, end + shift, loop_start + shift, loop_end + shift, rate,
                             pitch, correction, sample_map.get(link, 0), kind))  # fmt: skip

    # Terminal records point one past the last real entry (spec 7.2-7.10).
    out_phdr.append((b"EOP".ljust(20, b"\0"), 0, 0, len(out_pbag), 0, 0, 0))
    out_pbag.append((len(out_pgen), len(out_pmod)))
    out_pmod.append((0, 0, 0, 0, 0))
    out_pgen.append((0, 0))
    out_inst.append((b"EOI".ljust(20, b"\0"), len(out_ibag)))
    out_ibag.append((len(out_igen), len(out_imod)))
    out_imod.append((0, 0, 0, 0, 0))
    out_igen.append((0, 0))
    out_shdr.append((b"EOS".ljust(20, b"\0"), 0, 0, 0, 0, 0, 0, 0, 0, 0))

    def table(layout: struct.Struct, rows: list[Row]) -> bytes:
        return b"".join(layout.pack(*row) for row in rows)

    info = b"".join(chunk(c.tag, c.data) for c in lists[b"INFO"])
    sdta = chunk(b"smpl", bytes(new_smpl))
    pdta = b"".join(
        [
            chunk(b"phdr", table(PHDR, out_phdr)),
            chunk(b"pbag", table(BAG, out_pbag)),
            chunk(b"pmod", table(MOD, out_pmod)),
            chunk(b"pgen", table(GEN, out_pgen)),
            chunk(b"inst", table(INST, out_inst)),
            chunk(b"ibag", table(BAG, out_ibag)),
            chunk(b"imod", table(MOD, out_imod)),
            chunk(b"igen", table(GEN, out_igen)),
            chunk(b"shdr", table(SHDR, out_shdr)),
        ]
    )
    body = b"sfbk" + chunk(b"LIST", b"INFO" + info) + chunk(b"LIST", b"sdta" + sdta)
    body += chunk(b"LIST", b"pdta" + pdta)
    return chunk(b"RIFF", body)


def preset_names(font: bytes) -> list[tuple[int, int, str]]:
    """(bank, program, name) of every preset in a SoundFont."""
    pdta = next(c for c in read_chunks(font[12:]) if c.tag == b"LIST" and c.data[:4] == b"pdta")
    phdr = next(c.data for c in read_chunks(pdta.data[4:]) if c.tag == b"phdr")
    return [
        (bank, preset, name.rstrip(b"\0").decode("latin-1"))
        for name, preset, bank, *_ in records(phdr, PHDR)[:-1]
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("source")
    parser.add_argument("target")
    args = parser.parse_args()
    trimmed = trim(Path(args.source).read_bytes())
    Path(args.target).write_bytes(trimmed)
    presets = sorted((bank, preset, name) for bank, preset, name in preset_names(trimmed))
    print(f"{len(trimmed) / 1e6:.1f} MB, presets: {presets}")


if __name__ == "__main__":
    main()
