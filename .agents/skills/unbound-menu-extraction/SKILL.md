---
name: unbound-menu-extraction
description: Audit and improve Pokemon Unbound menu/UI text extraction. Use when asked to find untranslated menu text, search ROM PCS strings, compare audit hits with extracted entries, add manual menu addresses/ranges, or investigate labels such as Cube V3, Save Game, settings, PC, party, bag, item storage, battle, or options menus.
---

# Unbound Menu Extraction

Use existing project code first: `001_extract_unbound_text.py`, `lib/pcs_text.py`, and prior `audit.log` files.

## Workflow

1. Confirm the target string/category and ROM path, defaulting to `rom/unbound.gba`.
2. Run extraction/audit to `/tmp` unless the user asks for repo outputs:

```bash
./001_extract_unbound_text.py rom/unbound.gba -o /tmp/unbound-texts.json --audit-menu-text --audit-output /tmp/menu-audit.json
```

3. For custom strings, use repeated `--audit-string` or an `--audit-strings-file`.
4. Classify each result as:
   - extracted: injector/space/layout may be the issue.
   - found but not extracted: extractor coverage issue.
   - not found as PCS: likely graphical/tile text, compressed data, or custom encoding.
5. When changing extraction, prefer exact addresses or pointer-source patterns. Use narrow vetted ranges only when strings are contiguous and decode cleanly.
6. Keep extraction lossless. Do not clean translation text in `001`; use `002_prepare_translation_text.py`.

## Output

Return only high-signal data: string, ROM offset, extracted id/category if any, pointer source if known, classification, and next action.
