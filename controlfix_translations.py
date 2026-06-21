#!/usr/bin/env python3

import argparse
import json
import re
from pathlib import Path

from pcs_text import Charmap


TOKEN_RE = re.compile(
    r"\\CC(?:[0-9A-Fa-f]{2})+"
    r"|\\btn[0-9A-Fa-f]{2}"
    r"|\\![0-9A-Fa-f\s]+"
    r"|\\\\[0-9A-Fa-f]{2}"
    r"|\\\?[0-9A-Fa-f]{2}"
    r"|\\9[0-9A-Fa-f]{2}"
    r"|\\F[0-9A-Fa-f]"
    r"|\\(?:pk|mn|Po|Ke|Bl|Lo|Ck|Lv|qo|qc|sm|sf|au|ad|al|ar|pn|n|l|p|e|d|\.|<|>|\+|r)"
    r"|\[[A-Za-z0-9_]+\]"
)

LAYOUT_TOKENS = {"\\n", "\\p", "\\l", "\\pn"}
QUOTE_TOKENS = {"\\qo", "\\qc"}
COLOR_TOKENS = {
    "[white]",
    "[white2]",
    "[black]",
    "[grey]",
    "[gray]",
    "[red]",
    "[orange]",
    "[green]",
    "[lightgreen]",
    "[blue]",
    "[lightblue]",
    "[white3]",
    "[lightblue2]",
    "[cyan]",
    "[lightblue3]",
    "[navyblue]",
    "[darknavyblue]",
}


def iter_entries(data):
    for table in data.get("tables", []):
        for entry in table.get("entries", []):
            yield entry
    for entry in data.get("free_texts", []):
        yield entry
    for entry in data.get("entries", []):
        yield entry


def strip_hma_quotes(text):
    if isinstance(text, str) and len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1]
    return text or ""


def source_originals(path):
    if not path:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {entry["id"]: entry.get("original", "") for entry in iter_entries(data)}


def token_spans(text, predicate=None):
    spans = []
    for match in TOKEN_RE.finditer(text):
        token = match.group(0)
        if predicate is None or predicate(token):
            spans.append((match.start(), match.end(), token))
    return spans


def critical_token(token):
    return token not in LAYOUT_TOKENS


def replace_token_family(text, original, predicate):
    original_tokens = [token for _start, _end, token in token_spans(original, predicate)]
    translated_spans = token_spans(text, predicate)
    if not original_tokens or len(original_tokens) != len(translated_spans):
        return text, False

    changed = False
    pieces = []
    last = 0
    for (start, end, current), wanted in zip(translated_spans, original_tokens):
        pieces.append(text[last:start])
        pieces.append(wanted)
        last = end
        changed = changed or current != wanted
    pieces.append(text[last:])
    return "".join(pieces), changed


def leading_critical_tokens(text):
    i = 0
    result = []
    while i < len(text):
        match = TOKEN_RE.match(text, i)
        if match and critical_token(match.group(0)):
            result.append(match.group(0))
            i = match.end()
            continue
        if match and match.group(0) in LAYOUT_TOKENS:
            i = match.end()
            continue
        if text[i].isspace():
            i += 1
            continue
        break
    return result


def remove_leading_color_tokens(text):
    changed = True
    while changed:
        changed = False
        stripped = text.lstrip()
        leading_spaces = text[: len(text) - len(stripped)]
        match = TOKEN_RE.match(stripped)
        if match and match.group(0) in COLOR_TOKENS:
            text = leading_spaces + stripped[match.end() :]
            changed = True
    return text


def ensure_original_prefix(text, original):
    prefix = leading_critical_tokens(original)
    if not prefix:
        return text, False

    prefix_text = "".join(prefix)
    if text.lstrip().startswith(prefix_text):
        return text, False

    # Fullscreen/system text often depends on a leading color token. Replace a
    # translated leading color with the original one instead of stacking colors.
    if prefix and prefix[0] in COLOR_TOKENS:
        text = remove_leading_color_tokens(text)

    return prefix_text + text.lstrip(), True


def normalize_braced_controls(text):
    # Keep raw byte placeholders such as {B4}. Remove braces only around actual
    # PCS/HMA control codes that LLMs often wrap in braces.
    text = re.sub(r"\{(\[[A-Za-z0-9_]+\])\}", r"\1", text)
    text = re.sub(
        r"\{(\\(?:CC[0-9A-Fa-f]+|btn[0-9A-Fa-f]{2}|\?[0-9A-Fa-f]{2}|9[0-9A-Fa-f]{2}|F[0-9A-Fa-f]|[pnlr.]|qo|qc))\}",
        r"\1",
        text,
    )
    return text


def normalize_outer_quotes(text):
    text = strip_hma_quotes(text)
    text = re.sub(r'^"\s*(?=(?:\[[A-Za-z0-9_]+\]|\\))', "", text)
    if text.endswith('"') and (
        len(text) == 1
        or text.endswith('."')
        or text.endswith('!"')
        or text.endswith('?"')
        or text.endswith("\\p\"")
        or text.endswith("\\n\"")
        or text.endswith("\\l\"")
    ):
        text = text[:-1]
    return text


def repair_split_controls(text):
    # LLMs sometimes turn quote/control markers into layout + marker, e.g.
    # \nqo, \pqc, \nCC0818. These are not line breaks; they are broken controls.
    text = re.sub(r"\\[np](qo|qc)", lambda m: "\\" + m.group(1), text)
    text = re.sub(r"\\[np](CC[0-9A-Fa-f]{2,})", lambda m: "\\" + m.group(1), text)
    text = re.sub(r"\\[np](btn[0-9A-Fa-f]{2})", lambda m: "\\" + m.group(1), text)
    text = re.sub(r"\\[np](\?[0-9A-Fa-f]{2})", lambda m: "\\" + m.group(1), text)
    text = re.sub(r"\\[np](![0-9A-Fa-f]{2})", lambda m: "\\" + m.group(1), text)
    text = re.sub(r"\\\\(qo|qc)", lambda m: "\\" + m.group(1), text)
    text = re.sub(r"\\\\(CC[0-9A-Fa-f]{2,})", lambda m: "\\" + m.group(1), text)
    text = re.sub(r"\\\\(btn[0-9A-Fa-f]{2})", lambda m: "\\" + m.group(1), text)
    return text


def repair_control_sequences(text, original):
    changed = False

    text, did_change = replace_token_family(text, original, lambda token: token in QUOTE_TOKENS)
    changed = changed or did_change

    text, did_change = replace_token_family(text, original, lambda token: token in COLOR_TOKENS)
    changed = changed or did_change

    original_critical = [token for _s, _e, token in token_spans(original, critical_token)]
    translated_critical = [token for _s, _e, token in token_spans(text, critical_token)]
    if len(original_critical) == len(translated_critical):
        text, did_change = replace_token_family(text, original, critical_token)
        changed = changed or did_change

    text, did_change = ensure_original_prefix(text, original)
    changed = changed or did_change

    return text, changed


def collapse_duplicate_state_controls(text):
    pieces = []
    last_index = 0
    previous_token = None
    changed = False

    for start, end, token in token_spans(text):
        between = text[last_index:start]
        if between:
            previous_token = None
        pieces.append(between)

        duplicate = token == previous_token and (
            token in COLOR_TOKENS or token.startswith("\\CC")
        )
        if duplicate:
            changed = True
        else:
            pieces.append(token)
            previous_token = token

        last_index = end

    pieces.append(text[last_index:])
    return "".join(pieces), changed


def raw_placeholder(cmap, ch):
    encoded = cmap.encode_char(ch)
    if encoded and len(encoded) == 1:
        return f"{{{encoded[0]:02X}}}"
    return ch


def escape_hex_text_after_cc(text, original, cmap):
    changed = False
    original_cc_tokens = {
        token for _start, _end, token in token_spans(original) if token.startswith("\\CC")
    }

    for token in sorted(original_cc_tokens, key=len, reverse=True):
        pattern = re.compile(rf"({re.escape(token)})([0-9A-Fa-f])")

        def repl(match):
            nonlocal changed
            changed = True
            return match.group(1) + raw_placeholder(cmap, match.group(2))

        text = pattern.sub(repl, text)

    return text, changed


def protect_raw_placeholders(text):
    placeholders = []

    def repl(match):
        key = f"\x00RAW{len(placeholders)}\x00"
        placeholders.append((key, match.group(0)))
        return key

    return re.sub(r"\{[0-9A-Fa-f]{2}\}", repl, text), placeholders


def restore_raw_placeholders(text, placeholders):
    for key, value in placeholders:
        text = text.replace(key, value)
    return text


def fix_apostrophes(text):
    protected, placeholders = protect_raw_placeholders(text)
    protected = protected.replace("’", "{B4}")
    protected = protected.replace("‘", "{B3}")
    protected = protected.replace("'", "{B4}")
    return restore_raw_placeholders(protected, placeholders)


def control_sequence(text):
    return [token for _s, _e, token in token_spans(text, critical_token)]


def main():
    parser = argparse.ArgumentParser(
        description="Repair translated JSON control codes and apostrophes."
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="unbound-texts-it-untrimmed.json",
        help="Translated JSON to fix.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="unbound-texts-it-untrimmed-controlfix.json",
        help="Fixed output JSON.",
    )
    parser.add_argument(
        "--source",
        default="unbound-texts.json",
        help="Optional untranslated JSON used as original-control reference.",
    )
    parser.add_argument(
        "--report",
        help="Optional JSON report listing entries whose critical controls still differ.",
    )
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    originals = source_originals(args.source)
    cmap = Charmap(target_lang="it")

    stats = {
        "entries": 0,
        "translated": 0,
        "changed": 0,
        "braced_controls": 0,
        "split_controls": 0,
        "sequence_repairs": 0,
        "deduped_controls": 0,
        "cc_hex_escapes": 0,
        "apostrophe_repairs": 0,
        "remaining_control_mismatches": 0,
    }
    remaining = []

    for entry in iter_entries(data):
        stats["entries"] += 1
        translated = entry.get("translated")
        if not translated:
            continue
        stats["translated"] += 1

        original = strip_hma_quotes(originals.get(entry.get("id"), entry.get("original", "")))
        before = translated

        text = translated

        text = normalize_outer_quotes(text)

        next_text = normalize_braced_controls(text)
        stats["braced_controls"] += int(next_text != text)
        text = next_text

        next_text = repair_split_controls(text)
        stats["split_controls"] += int(next_text != text)
        text = next_text

        next_text, sequence_changed = repair_control_sequences(text, original)
        stats["sequence_repairs"] += int(sequence_changed)
        text = next_text

        next_text, deduped = collapse_duplicate_state_controls(text)
        stats["deduped_controls"] += int(deduped)
        text = next_text

        next_text, cc_escaped = escape_hex_text_after_cc(text, original, cmap)
        stats["cc_hex_escapes"] += int(cc_escaped)
        text = next_text

        next_text = fix_apostrophes(text)
        stats["apostrophe_repairs"] += int(next_text != text)
        text = next_text

        if text != before:
            entry["translated"] = text
            stats["changed"] += 1

        if control_sequence(text) != control_sequence(original):
            stats["remaining_control_mismatches"] += 1
            if len(remaining) < 200:
                remaining.append(
                    {
                        "id": entry.get("id"),
                        "category": entry.get("category"),
                        "original_controls": control_sequence(original),
                        "translated_controls": control_sequence(text),
                    }
                )

    Path(args.output).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if args.report:
        Path(args.report).write_text(
            json.dumps({"stats": stats, "remaining": remaining}, indent=2, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )

    for key, value in stats.items():
        print(f"{key}: {value}")
    print(f"output: {args.output}")


if __name__ == "__main__":
    main()
