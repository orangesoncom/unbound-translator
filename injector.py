#!/usr/bin/env python3

import argparse
import json
import re
from pathlib import Path

from pcs_text import Charmap, fc_arg_count


GBA_POINTER_BASE = 0x08000000
DEFAULT_MIN_ADDRESS = 0x100
TERMINATOR = 0xFF


def parse_address(value):
    if isinstance(value, int):
        address = value
    elif isinstance(value, str):
        address = int(value, 16) if value.lower().startswith("0x") else int(value)
    else:
        raise ValueError(f"Invalid address: {value!r}")

    if address >= GBA_POINTER_BASE:
        address -= GBA_POINTER_BASE
    return address


def strip_hma_quotes(text):
    if isinstance(text, str) and len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1]
    return text or ""


def byte_placeholders(values):
    return "".join(f"{{{value:02X}}}" for value in values)


def normalize_text_escapes(text):
    """Convert legacy HMA escape forms to raw byte placeholders.

    The local PCS encoder handles common escapes such as "\\n", "\\p",
    "\\CC0602", "\\btn05", and bracket macros directly. Some existing
    translation entries also use raw-byte forms:
      - \\!XX       -> raw byte XX
      - \\?XX       -> F7 XX
      - \\9XX       -> F9 XX
      - \\\\XX      -> FD XX
      - \\FX        -> raw byte FX
    Converting those to {XX} raw placeholders keeps older translation files
    compatible with the local encoder.
    """

    # FD escape: two literal backslashes followed by one byte.
    text = re.sub(
        r"\\\\([0-9A-Fa-f]{2})",
        lambda m: byte_placeholders((0xFD, int(m.group(1), 16))),
        text,
    )

    # Raw byte escape.  Allow whitespace between \! and the byte because LLMs
    # sometimes split these tokens across a line.
    def raw_bytes(match):
        hex_text = re.sub(r"\s+", "", match.group(1))
        if len(hex_text) % 2:
            hex_text = hex_text[:-1]
        values = [int(hex_text[i : i + 2], 16) for i in range(0, len(hex_text), 2)]
        return byte_placeholders(values)

    text = re.sub(r"\\!((?:\s*[0-9A-Fa-f]{2})+)", raw_bytes, text)

    # F7 and F9 two-byte escape families.
    text = re.sub(
        r"\\\?([0-9A-Fa-f]{2})",
        lambda m: byte_placeholders((0xF7, int(m.group(1), 16))),
        text,
    )
    text = re.sub(
        r"\\9([0-9A-Fa-f]{2})",
        lambda m: byte_placeholders((0xF9, int(m.group(1), 16))),
        text,
    )

    # Single raw F* byte, used by some HMA-style output.
    text = re.sub(
        r"\\F([0-9A-Fa-f])",
        lambda m: byte_placeholders((int("F" + m.group(1), 16),)),
        text,
    )

    return text


def encode_text(cmap, text):
    return bytes(cmap.encode(normalize_text_escapes(strip_hma_quotes(text))))


def truncate_encoded(encoded, max_size):
    if max_size <= 0:
        return b""
    if len(encoded) <= max_size and encoded.endswith(bytes((TERMINATOR,))):
        return encoded
    if max_size == 1:
        return bytes((TERMINATOR,))

    limit = max_size - 1
    out = bytearray()
    i = 0

    while i < len(encoded):
        b = encoded[i]
        if b == TERMINATOR:
            break

        token_len = 1
        if b == 0xFC and i + 1 < len(encoded):
            token_len = 2 + fc_arg_count(encoded[i + 1])
        elif b in (0xF7, 0xF8, 0xF9, 0xFD):
            token_len = 2

        if i + token_len > len(encoded) or len(out) + token_len > limit:
            break

        out.extend(encoded[i : i + token_len])
        i += token_len

    out.append(TERMINATOR)
    return bytes(out)


def fit_to_slot(encoded, max_size, pad_byte):
    if len(encoded) > max_size or not encoded.endswith(bytes((TERMINATOR,))):
        encoded = truncate_encoded(encoded, max_size)
    return encoded.ljust(max_size, bytes((pad_byte,)))


def iter_entries(data):
    for table in data.get("tables", []):
        for entry in table.get("entries", []):
            yield entry
    for entry in data.get("free_texts", []):
        yield entry
    for entry in data.get("entries", []):
        yield entry


def sorted_non_overlapping_entries(entries, min_address):
    prepared = []
    skipped_unsafe = 0

    for index, entry in enumerate(entries):
        try:
            address = parse_address(entry["address"])
            byte_length = int(entry["byte_length"])
        except Exception:
            skipped_unsafe += 1
            continue

        if address < min_address or byte_length <= 0:
            skipped_unsafe += 1
            continue

        prepared.append((address, -byte_length, index, entry))

    prepared.sort()

    result = []
    occupied_until = 0
    seen_slots = set()
    skipped_overlap = 0

    for address, neg_length, _index, entry in prepared:
        byte_length = -neg_length
        slot = (address, byte_length)
        if slot in seen_slots:
            skipped_overlap += 1
            continue
        if address < occupied_until:
            skipped_overlap += 1
            continue

        seen_slots.add(slot)
        occupied_until = address + byte_length
        result.append(entry)

    return result, skipped_unsafe, skipped_overlap


def main():
    parser = argparse.ArgumentParser(
        description="Inject translations in-place without expanding the ROM."
    )
    parser.add_argument("rom", help="Source GBA ROM")
    parser.add_argument("json", help="Translations JSON")
    parser.add_argument("-o", "--output", default="patched.gba", help="Output GBA ROM")
    parser.add_argument("--target-lang", default="it", help="Target language hint for text cleanup")
    parser.add_argument(
        "--pad-byte",
        default="FF",
        help="Byte used to pad shorter strings, as hex. Default: FF",
    )
    parser.add_argument(
        "--min-address",
        default=hex(DEFAULT_MIN_ADDRESS),
        help="Skip entries below this ROM offset. Default protects the GBA header.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do all parsing/encoding work but do not write the output ROM.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print every truncated entry instead of only a short sample.",
    )

    args = parser.parse_args()

    rom_path = Path(args.rom)
    json_path = Path(args.json)
    output_path = Path(args.output)
    pad_byte = int(args.pad_byte, 16)
    min_address = parse_address(args.min_address)

    if not 0 <= pad_byte <= 0xFF:
        raise ValueError("--pad-byte must be between 00 and FF")

    rom = bytearray(rom_path.read_bytes())
    data = json.loads(json_path.read_text(encoding="utf-8"))
    cmap = Charmap(target_lang=args.target_lang)

    all_entries = list(iter_entries(data))
    entries, skipped_unsafe, skipped_overlap = sorted_non_overlapping_entries(
        all_entries, min_address
    )

    patched = 0
    skipped_empty = 0
    skipped_bounds = 0
    unchanged = 0
    truncated = 0
    truncation_samples = []
    encode_errors = 0

    for entry in entries:
        translated = strip_hma_quotes(entry.get("translated", ""))
        if not translated:
            skipped_empty += 1
            continue

        original = strip_hma_quotes(entry.get("original", ""))
        if translated == original:
            unchanged += 1
            continue

        address = parse_address(entry["address"])
        max_size = int(entry["byte_length"])

        if address + max_size > len(rom):
            skipped_bounds += 1
            continue

        try:
            encoded = encode_text(cmap, translated)
        except Exception as e:
            encode_errors += 1
            print(f"[ENCODE ERROR] {entry.get('id', '?')}: {e}")
            continue

        if len(encoded) > max_size:
            truncated += 1
            message = f"[TRUNCATED] {entry.get('id', '?')}: {len(encoded)} -> {max_size}"
            if args.verbose:
                print(message)
            elif len(truncation_samples) < 20:
                truncation_samples.append(message)

        fitted = fit_to_slot(encoded, max_size, pad_byte)
        if not args.dry_run:
            rom[address : address + max_size] = fitted
        patched += 1

    if not args.dry_run:
        output_path.write_bytes(rom)

    print()
    print("===================================")
    print(f"Input entries       : {len(all_entries)}")
    print(f"Patch candidates    : {len(entries)}")
    print(f"Patched             : {patched}")
    print(f"Unchanged           : {unchanged}")
    print(f"Skipped empty       : {skipped_empty}")
    print(f"Skipped unsafe      : {skipped_unsafe}")
    print(f"Skipped overlaps    : {skipped_overlap}")
    print(f"Skipped out-of-ROM  : {skipped_bounds}")
    print(f"Encode errors       : {encode_errors}")
    print(f"Truncated           : {truncated}")
    if truncation_samples:
        print("Truncation sample   :")
        for message in truncation_samples:
            print(f"  {message}")
    print(f"Output ROM          : {'(dry run)' if args.dry_run else output_path}")
    print("===================================")


if __name__ == "__main__":
    main()
