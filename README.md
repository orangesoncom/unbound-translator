# unbound-translator

`unbound-translator` is a project aimed at translating the game Pokémon Unbound into other languages.

## Preview

![Pokémon Unbound Italian Screenshot](resources/showcase.png)

The project was previously based on [Olcmyk/Meowth-GBA-Translator](https://github.com/Olcmyk/Meowth-GBA-Translator), but it quickly transitioned to custom scripts because of how that translator works. Meowth expands the ROM to 32 MB and writes all translated text into a dedicated area. That approach cannot work cleanly with Pokémon Unbound, because Unbound is already a 32 MB GBA ROM.

## How It Works

The current injector uses a hybrid strategy:

- Short translated strings that still fit their original slots are written in place.
- Longer pointer-based strings are relocated into free space inside the existing ROM.
- Free space is found by scanning for contiguous `0xFF` blocks.
- Script pointers are then updated to point at the relocated translated text.

This avoids expanding the ROM while still allowing longer translations where the original text was pointer-based.

## Free Space

This relocation approach was possible because Pokémon Unbound still has `1,102,003` bytes of free space available in the ROM. Those regions are detected by scanning for contiguous `0xFF` blocks and are used as targets for translated strings that no longer fit in their original locations.

## Workflow

Put the source ROM somewhere in the repo, for example:

```bash
rom/unbound.gba
```

The ROM used for this project has MD5:

```text
9cad8e771940e7f7094d13911552cef0
```

### 1. Extract Text

```bash
./extract_unbound_text.py rom/unbound.gba -o out/unbound-texts.json
```

Translate the generated JSON while preserving its structure. Each entry should keep its `original` field and receive a `translated` field.

### 2. Repair Control Codes

Run the control-fix script after translation:

```bash
./controlfix_translations.py out/unbound-texts-translated.json \
  -o out/unbound-texts-translated-controlfix.json \
  --source out/unbound-texts.json \
  --report out/controlfix-report.json
```

This step is still needed. It repairs common translation damage such as broken control codes, misplaced braces, outer quotes, and apostrophes.

### 3. Inject Translation

```bash
./hybrid_injector.py rom/unbound.gba out/unbound-texts-translated-controlfix.json \
  -o out/unbound-translated.gba \
  --map-output out/hybrid-map.json
```

The output ROM will be written to:

```bash
out/unbound-translated.gba
```

## Ready Translations

In the `ready-translations` folder you can find pre-translated text in both JSON and BPS patch format. For now, only Italian is included.

The ready translations currently included in the repo were made using DeepSeek V4 Flash.

## Known Issues

This repo is in a very early stage, so bugs can occur. Some text may glitch out of the screen, or the screen may flash red or other colors in some places.

The scripts have been tested with the Italian language. Support for other languages can be added, for example German.

## TODO

- LLM powered translation script
- Polishing

## Notes

- The injector does not expand the ROM.
- Pointer-based text may be relocated into existing `0xFF` free space.
- Fixed-size text that cannot be relocated may still need shorter translations.
- `hybrid-map.json` records relocation decisions and injection stats.
- Issues and pull requests are welcome.
- Yes, this repo is vibecoded, I'm sorry but I don't have time to manually work on this...
