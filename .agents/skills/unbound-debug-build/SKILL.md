---
name: unbound-debug-build
description: Run focused Pokemon Unbound debug translation builds. Use when asked to test a small ROM, whitelist ids/categories, verify menu translations quickly, produce a debug translated ROM, or run the extraction prepare translate controlfix inject flow on a limited set.
---

# Unbound Debug Build

Use this for quick feedback without translating the whole ROM. Prefer `/tmp` for experiments unless the user wants `out/debug-*` artifacts.

## Workflow

1. Extract and prepare:

```bash
./001_extract_unbound_text.py rom/unbound.gba -o out/debug-unbound-texts.json
./002_prepare_translation_text.py out/debug-unbound-texts.json -o out/debug-unbound-texts-prepared.json
```

2. Translate a whitelist. Default to user-provided ids/ranges; for menu checks include `--include-category-prefixes menu_`.

```bash
./003_llm_translate.py out/debug-unbound-texts-prepared.json --target it --api-base https://opencode.ai/zen/go/v1 --api-key YOUR_API_KEY --model your-model-name --workers 4 --batch-size 20 --include-category-prefixes menu_ -o out/debug-unbound-texts-it.json --overwrite
```

3. Controlfix and inject:

```bash
./004_controlfix_translations.py out/debug-unbound-texts-it.json -o out/debug-unbound-texts-it-controlfix.json --source out/debug-unbound-texts-prepared.json --report out/debug-controlfix-report.json
./005_hybrid_injector.py rom/unbound.gba out/debug-unbound-texts-it-controlfix.json -o out/debug-unbound-translated.gba --map-output out/debug-hybrid-map.json
```

## Rules

Always run `004_controlfix_translations.py` before injection. Preserve user output files unless explicitly asked to overwrite.
