#!/usr/bin/env python3

"""Extract Pokemon Unbound text without Meowth/HMA dependencies."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import json
import re
from pathlib import Path

from pcs_text import DecodeResult, TERMINATOR, decode_pcs, hma_quote, strip_control_tokens


GBA_POINTER_BASE = 0x08000000
DEFAULT_MIN_POINTER_TARGET = 0x100
DEFAULT_MAX_TEXT_LENGTH = 0x800


@dataclass(frozen=True)
class FixedTable:
    category: str
    table_name: str
    start: int
    count: int
    slot_size: int
    stride: int | None = None
    pointer_name: bool = False
    substring_name: bool = False


@dataclass(frozen=True)
class SequentialTable:
    category: str
    table_name: str
    start: int
    count: int


@dataclass(frozen=True)
class PointerTable:
    category: str
    table_name: str
    start: int
    count: int


FIXED_TABLES = [
    FixedTable("pokemon_names", "data.pokemon.names", 0x166A98C, 1294, 11),
    FixedTable("type_names", "data.pokemon.type.names", 0xA4EAD4, 24, 7),
    FixedTable("item_names", "data.items.stats", 0x876200, 729, 13, 44, pointer_name=True),
    FixedTable("move_names", "data.pokemon.moves.names", 0xA40A10, 923, 13),
    FixedTable("ability_names", "data.abilities.names", 0xA36398, 293, 17),
    FixedTable(
        "trainer_classes",
        "data.trainers.classes.names",
        0x23E558,
        107,
        13,
        substring_name=True,
    ),
]

SEQUENTIAL_TABLES = [
    SequentialTable("nature_names", "data.pokemon.natures.names", 0x463DBC, 25),
    SequentialTable("habitat_names", "data.pokedex.habitat.names", 0x415DF7, 9),
]

POINTER_TABLES = [
    PointerTable("ability_descriptions", "data.abilities.descriptions", 0x96DE04, 293),
    PointerTable("move_descriptions", "data.pokemon.moves.descriptions", 0x99F194, 922),
    PointerTable("map_names", "data.maps.names", 0x3F1CAC, 109),
]

MANUAL_TEXT_TABLES = {
    "menu_options": (
        "data.menus.text.options",
        [
            0x419DD3,
            0x419DDE,
            0x419DEB,
            0x419DF8,
            0x419DFE,
            0x419E0A,
            0x419C5A,
        ],
    ),
    "menu_pc": (
        "data.menus.text.pc",
        [
            0x418208,
            0x41821B,
            0x418233,
            0x418248,
            0x41825C,
            0x41826C,
            0x41827F,
            0x418295,
            0x4182A7,
            0x4182B8,
            0x4182CE,
            0x4182DF,
            0x4182EC,
            0x4182FF,
            0x418319,
            0x41832C,
            0x418346,
            0x41835A,
            0x418379,
            0x418392,
            0x4183A0,
            0x4183BA,
            0x4183C5,
            0x41825C,
            0x4183DD,
            0x4183F0,
            0x1F21C2A,
            0x1F21C0F,
            0x418433,
            0x418443,
            0x418452,
        ],
    ),
    "menu_pcoptions": ("data.menus.text.pcoptions", [0x4176F1, 0x4176FE, 0x4176E2]),
    "menu_pokemon": (
        "data.menus.text.pokemon",
        [
            0x4171DF,
            0x417396,
            0x4173B0,
            0x4171F1,
            0x417200,
            0x417215,
            0x41722B,
            0x417258,
            0x417270,
            0x417281,
            0x417299,
            0x4173CC,
            0x4173E4,
            0x417301,
            0x417313,
            0x4173CC,
            0xA4E15D,
            0x4173CC,
            0x417337,
            0x41734D,
            0x41735B,
            0x41736B,
            0x417242,
            0x4172AE,
            0x4172C2,
            0x4172D5,
            0x41737F,
        ],
    ),
    "menu_item_storage": ("data.text.menu.itemStorage", [0x417713, 0x417706, 0x4161C1]),
    "menu_pause": (
        "data.text.menu.pause",
        [0x41627D, 0x415A66, 0x800FC0, 0x41628E, 0x416291, 0x416296, 0x41629D, 0x4162A2, 0x41628E],
    ),
    "menu_pokemon_options": (
        "data.text.menu.pokemon.options",
        [
            0x416994,
            0x41698D,
            0x4161C1,
            0x4161D4,
            0x4161B2,
            0x4161DE,
            0x4161D9,
            0x4169B2,
            0x4169B7,
            0x4161C1,
            0x4169BC,
            0x416994,
            0x41698D,
            0x4161C1,
            0x4161E3,
            0x41B6F4,
            0x4169BC,
            0x4169BC,
            0xA4E1F1,
        ],
    ),
    "trade_messages": (
        "data.text.trade.messages",
        [0x41718C, 0x4171CC, 0x4170BC, 0x4170BC, 0x4170FC, 0x4170E0, 0x417130, 0x417164, 0x417164],
    ),
}


def gba_pointer_to_offset(value: int, rom_size: int) -> int | None:
    if GBA_POINTER_BASE <= value < GBA_POINTER_BASE + rom_size:
        return value - GBA_POINTER_BASE
    return None


def format_offset(offset: int) -> str:
    return f"0x{offset:X}"


def pointer_at(rom: bytes, offset: int) -> int | None:
    if offset + 4 > len(rom):
        return None
    return gba_pointer_to_offset(int.from_bytes(rom[offset : offset + 4], "little"), len(rom))


def visible_text(text: str) -> str:
    return strip_control_tokens(text).replace("\n", " ").strip()


def looks_like_table_text(result: DecodeResult, allow_empty: bool = False) -> bool:
    if not result.terminated or result.raw_count:
        return False
    clean = visible_text(result.text)
    if allow_empty and not clean:
        return True
    return bool(clean)


def looks_like_pointer_text(result: DecodeResult) -> bool:
    if not result.terminated or result.raw_count:
        return False
    if result.byte_length < 3 or result.byte_length > DEFAULT_MAX_TEXT_LENGTH:
        return False

    clean = visible_text(result.text)
    if len(clean) < 2:
        return False
    if _mostly_padding_or_symbols(clean):
        return False
    letters = sum(1 for char in clean if char.isalpha())
    ascii_letters = sum(1 for char in clean if char.isascii() and char.isalpha())
    digits = sum(1 for char in clean if char.isdigit())
    if letters + digits < 2:
        return False
    if ascii_letters < 1:
        return False
    if len(clean) >= 8 and ascii_letters / max(1, len(clean)) < 0.25:
        return False
    return True


def _mostly_padding_or_symbols(text: str) -> bool:
    meaningful = sum(1 for char in text if char.isalnum())
    return meaningful / max(1, len(text)) < 0.35


def score_name_candidate(result: DecodeResult) -> int:
    if not result.terminated or result.raw_count:
        return -10_000
    clean = visible_text(result.text)
    if not clean:
        return -100
    letters = sum(1 for char in clean if char.isalpha())
    spaces = clean.count(" ")
    controls = result.control_count
    leading_penalty = 12 if clean[0].islower() else 0
    return letters * 4 + spaces + controls - leading_penalty


def decode_slot(rom: bytes, offset: int, size: int) -> DecodeResult:
    return decode_pcs(rom[offset : offset + size], 0, size)


def best_substring_slot(rom: bytes, offset: int, size: int) -> tuple[int, DecodeResult]:
    best_delta = 0
    best_result = decode_slot(rom, offset, size)
    best_score = score_name_candidate(best_result)
    for delta in range(1, size):
        result = decode_slot(rom, offset + delta, size - delta)
        score = score_name_candidate(result)
        if score > best_score:
            best_delta = delta
            best_result = result
            best_score = score
    return offset + best_delta, best_result


def make_entry(
    entry_id: str,
    category: str,
    address: int,
    result: DecodeResult,
    byte_length: int,
    is_pointer_based: bool,
    pointer_sources: list[int] | None = None,
    table_name: str | None = None,
    table_index: int | None = None,
) -> dict:
    entry = {
        "id": entry_id,
        "category": category,
        "address": format_offset(address),
        "pointer_sources": [format_offset(source) for source in pointer_sources or []],
        "original": hma_quote(result.text),
        "byte_length": byte_length,
        "is_pointer_based": is_pointer_based,
    }
    if table_name is not None:
        entry["table_name"] = table_name
    if table_index is not None:
        entry["table_index"] = table_index
    return entry


def extract_fixed_table(
    rom: bytes,
    table: FixedTable,
    next_table_id: int,
    known_targets: set[int],
    known_pointer_sources: set[int],
) -> tuple[list[dict], int]:
    entries = []
    stride = table.stride or table.slot_size

    for index in range(table.count):
        slot = table.start + index * stride
        target = None
        pointer_sources: list[int] = []
        byte_length = table.slot_size
        is_pointer_based = False

        if table.pointer_name:
            target = pointer_at(rom, slot)
            if target is not None:
                result = decode_pcs(rom, target, DEFAULT_MAX_TEXT_LENGTH)
                if looks_like_table_text(result):
                    pointer_sources = [slot]
                    known_pointer_sources.add(slot)
                    byte_length = result.byte_length
                    is_pointer_based = True
                else:
                    target = None

        if target is None:
            if table.substring_name:
                target, result = best_substring_slot(rom, slot, table.slot_size)
                byte_length = table.slot_size - (target - slot)
            else:
                target = slot
                result = decode_slot(rom, slot, table.slot_size)
                byte_length = table.slot_size

        known_targets.add(target)
        entries.append(
            make_entry(
                f"tbl_{table.category}_{next_table_id:05d}",
                table.category,
                target,
                result,
                byte_length,
                is_pointer_based,
                pointer_sources,
                table.table_name,
                index,
            )
        )
        next_table_id += 1

    return entries, next_table_id


def extract_sequential_table(
    rom: bytes,
    table: SequentialTable,
    next_table_id: int,
    known_targets: set[int],
) -> tuple[list[dict], int]:
    entries = []
    cursor = table.start
    for index in range(table.count):
        result = decode_pcs(rom, cursor, DEFAULT_MAX_TEXT_LENGTH)
        known_targets.add(cursor)
        entries.append(
            make_entry(
                f"tbl_{table.category}_{next_table_id:05d}",
                table.category,
                cursor,
                result,
                result.byte_length,
                False,
                [],
                table.table_name,
                index,
            )
        )
        cursor += max(result.byte_length, 1)
        next_table_id += 1
    return entries, next_table_id


def extract_pointer_table(
    rom: bytes,
    table: PointerTable,
    next_table_id: int,
    known_targets: set[int],
    known_pointer_sources: set[int],
) -> tuple[list[dict], int]:
    entries = []
    for index in range(table.count):
        source = table.start + index * 4
        target = pointer_at(rom, source)
        known_pointer_sources.add(source)
        if target is None:
            result = DecodeResult("", 0, False, raw_count=1)
            target = 0
            byte_length = 0
        else:
            result = decode_pcs(rom, target, DEFAULT_MAX_TEXT_LENGTH)
            byte_length = result.byte_length
            known_targets.add(target)

        entries.append(
            make_entry(
                f"tbl_{table.category}_{next_table_id:05d}",
                table.category,
                target,
                result,
                byte_length,
                True,
                [source] if target else [],
                table.table_name,
                index,
            )
        )
        next_table_id += 1
    return entries, next_table_id


def extract_manual_tables(
    rom: bytes,
    next_table_id: int,
    known_targets: set[int],
) -> tuple[list[dict], int]:
    entries = []
    for category, (table_name, addresses) in MANUAL_TEXT_TABLES.items():
        for index, address in enumerate(addresses):
            result = decode_pcs(rom, address, DEFAULT_MAX_TEXT_LENGTH)
            known_targets.add(address)
            entries.append(
                make_entry(
                    f"tbl_{category}_{next_table_id:05d}",
                    category,
                    address,
                    result,
                    result.byte_length,
                    False,
                    [],
                    table_name,
                    index,
                )
            )
            next_table_id += 1
    return entries, next_table_id


def scan_pointer_texts(
    rom: bytes,
    known_targets: set[int],
    known_pointer_sources: set[int],
    min_target: int,
    max_length: int,
    start_index: int,
    all_pointers: bool = False,
) -> tuple[list[dict], Counter]:
    sources_by_target: dict[int, list[int]] = defaultdict(list)
    stats = Counter()

    for source in range(0, len(rom) - 3):
        if source in known_pointer_sources:
            continue
        if not all_pointers and not is_script_text_pointer_source(rom, source):
            continue
        target = pointer_at(rom, source)
        if target is None:
            continue
        stats["raw_pointers"] += 1
        if target < min_target or target in known_targets:
            continue
        sources_by_target[target].append(source)

    entries = []
    script_index = 0
    for target in sorted(sources_by_target):
        result = decode_pcs(rom, target, max_length)
        if not looks_like_pointer_text(result):
            stats["rejected_targets"] += 1
            continue
        entries.append(
            make_entry(
                f"scr_{start_index + script_index:05d}",
                "scripts",
                target,
                result,
                result.byte_length,
                True,
                sources_by_target[target],
            )
        )
        script_index += 1
    stats["accepted_targets"] = len(entries)
    stats["accepted_pointer_sources"] = sum(len(entry["pointer_sources"]) for entry in entries)
    return entries, stats


def is_script_text_pointer_source(rom: bytes, source: int) -> bool:
    if source >= 2 and rom[source - 2] == 0x0F and rom[source - 1] <= 0x03:
        return True
    # Unbound also uses script/menu opcode 0x67 followed directly by a text
    # pointer for some late-game systems, including intro character setup.
    # Restrict this broader pattern to the high script bank to avoid random
    # code/data pointers that happen to be preceded by 0x67.
    return source >= 1 and rom[source - 1] == 0x67 and (source >> 20) == 0x1E


def scan_orphan_texts(
    rom: bytes,
    occupied_starts: set[int],
    min_target: int,
    max_length: int,
    start_index: int,
) -> tuple[list[dict], Counter]:
    entries = []
    stats = Counter()
    cursor = min_target

    while cursor < len(rom):
        if cursor in occupied_starts:
            cursor += 1
            continue
        result = decode_pcs(rom, cursor, max_length)
        if looks_like_pointer_text(result):
            entries.append(
                make_entry(
                    f"orphan_{start_index + len(entries):05d}",
                    "orphan_texts",
                    cursor,
                    result,
                    result.byte_length,
                    False,
                    [],
                )
            )
            cursor += max(result.byte_length, 1)
            continue
        stats["rejected_offsets"] += 1
        cursor += 1

    stats["accepted_orphans"] = len(entries)
    return entries, stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract Pokemon Unbound text JSON without Meowth."
    )
    parser.add_argument("rom", nargs="?", default="unbound.gba", help="Source GBA ROM")
    parser.add_argument(
        "-o",
        "--output",
        default="unbound-texts-extracted.json",
        help="Output JSON path",
    )
    parser.add_argument(
        "--min-pointer-target",
        default=hex(DEFAULT_MIN_POINTER_TARGET),
        help="Lowest ROM offset accepted for generic pointer text",
    )
    parser.add_argument(
        "--max-text-length",
        type=lambda value: int(value, 0),
        default=DEFAULT_MAX_TEXT_LENGTH,
        help="Maximum bytes to read for one pointer/orphan string",
    )
    parser.add_argument(
        "--include-orphans",
        action="store_true",
        help="Also scan unreferenced terminated text runs. This is noisy but useful for audits.",
    )
    parser.add_argument(
        "--all-pointers",
        action="store_true",
        help="Scan every GBA pointer instead of only script loadpointer sources. This is very noisy.",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indentation. Use 0 for compact output.",
    )
    args = parser.parse_args()

    rom_path = Path(args.rom)
    output_path = Path(args.output)
    rom = rom_path.read_bytes()
    min_pointer_target = int(args.min_pointer_target, 0)

    known_targets: set[int] = set()
    known_pointer_sources: set[int] = set()
    entries: list[dict] = []
    next_table_id = 0

    for table in FIXED_TABLES:
        table_entries, next_table_id = extract_fixed_table(
            rom, table, next_table_id, known_targets, known_pointer_sources
        )
        entries.extend(table_entries)

    for table in SEQUENTIAL_TABLES:
        table_entries, next_table_id = extract_sequential_table(
            rom, table, next_table_id, known_targets
        )
        entries.extend(table_entries)

    for table in POINTER_TABLES:
        table_entries, next_table_id = extract_pointer_table(
            rom, table, next_table_id, known_targets, known_pointer_sources
        )
        entries.extend(table_entries)

    table_entries, next_table_id = extract_manual_tables(rom, next_table_id, known_targets)
    entries.extend(table_entries)

    script_entries, pointer_stats = scan_pointer_texts(
        rom,
        known_targets,
        known_pointer_sources,
        min_pointer_target,
        args.max_text_length,
        next_table_id,
        args.all_pointers,
    )
    entries.extend(script_entries)

    orphan_stats = Counter()
    if args.include_orphans:
        occupied_starts = {int(entry["address"], 16) for entry in entries if entry["byte_length"]}
        orphan_entries, orphan_stats = scan_orphan_texts(
            rom,
            occupied_starts,
            min_pointer_target,
            args.max_text_length,
            len(script_entries),
        )
        entries.extend(orphan_entries)

    output = {"entries": entries}
    if args.indent == 0:
        text = json.dumps(output, ensure_ascii=False, separators=(",", ":")) + "\n"
    else:
        text = json.dumps(output, ensure_ascii=False, indent=args.indent) + "\n"
    output_path.write_text(text, encoding="utf-8")

    counts = Counter(entry["category"] for entry in entries)
    print(f"ROM: {rom_path}")
    print(f"Output: {output_path}")
    print(f"Entries: {len(entries)}")
    for category, count in counts.most_common():
        print(f"{category}: {count}")
    print(f"Pointer candidates: {pointer_stats['raw_pointers']}")
    print(f"Pointer text accepted: {pointer_stats['accepted_targets']}")
    print(f"Pointer text rejected: {pointer_stats['rejected_targets']}")
    if args.include_orphans:
        print(f"Orphan text accepted: {orphan_stats['accepted_orphans']}")


if __name__ == "__main__":
    main()
