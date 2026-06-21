# AGENTS.md

This repository is `unbound-translator`, a Python toolchain for translating Pokemon Unbound into other languages.

## Project Context

- Pokemon Unbound is already a 32 MB GBA ROM, so the old Meowth-GBA-Translator approach of expanding the ROM to 32 MB and writing all text into one dedicated area is not suitable here.
- The project now uses custom scripts and a local PCS text codec in `pcs_text.py`.
- Text relocation works because the ROM has `1,102,003` bytes of detected free space. The injector finds this space by scanning contiguous `0xFF` blocks.
- The injection strategy is hybrid: short translated text is written in place, and longer pointer-based text is relocated into detected free space with script pointers updated to the new addresses.
- The source ROM used by this project has MD5 `9cad8e771940e7f7094d13911552cef0`.

## Main Scripts

- `extract_unbound_text.py`: extracts text from the ROM into JSON. The expected output shape is a JSON object containing an `entries` array, though some utilities also tolerate older `tables` and `free_texts` shapes.
- `llm_translate.py`: translates extracted JSON through an OpenAI-compatible chat completions API or a Codex CLI ChatGPT login. It preserves the JSON shape, fills `translated` fields, supports `--resume`, validates returned batches, and stops on partial or malformed model output.
- `controlfix_translations.py`: repairs translated control codes, quote tokens, apostrophes, and other formatting damage caused by translation.
- `hybrid_injector.py`: injects translated text into the ROM using in-place writes and pointer relocation into free `0xFF` space.
- `pcs_text.py`: local PCS charmap and codec. Do not reintroduce Meowth charmap dependencies.

## Workflow

Use this baseline flow:

```bash
./extract_unbound_text.py rom/unbound.gba -o out/unbound-texts.json
./llm_translate.py out/unbound-texts.json --target it --api-base https://opencode.ai/zen/go/v1 --api-key YOUR_API_KEY --model your-model-name --workers 4 --batch-size 20 -o out/unbound-texts-it.json
./controlfix_translations.py out/unbound-texts-it.json -o out/unbound-texts-it-controlfix.json --source out/unbound-texts.json --report out/controlfix-report.json
./hybrid_injector.py rom/unbound.gba out/unbound-texts-it-controlfix.json -o out/unbound-translated.gba --map-output out/hybrid-map.json
```

When resuming LLM translation, use the same input and output paths with `--resume`.

## Extraction Notes

- A healthy baseline extraction currently reports about `13,733` entries and about `8,897` script entries.
- `Pointer text rejected` in extractor output means candidate pointers were checked and discarded because they did not decode as plausible text. It does not mean translations failed.
- Do not blindly accept all rejected pointer candidates. If text is missing, add or refine the pointer-source pattern for the specific game system that owns that text.
- Known strings such as `Choose a character.` and `Choose a skin tone.` are extracted through the script/menu `0x67` pointer pattern.

## Translation Notes

- `llm_translate.py` currently supports Latin-script target languages only: `de`, `en`, `es`, `fr`, `it`, `pt`, and `pt-br`.
- Non-Latin target languages are out of scope for now because they likely require a font patch.
- The LLM prompt asks for established official Pokemon terminology and may ask models with web/retrieval access to consult reputable references such as Bulbapedia or Pokemon Database. Plain OpenAI-compatible chat APIs usually do not browse by themselves.
- To use a ChatGPT subscription login instead of an API key, run `codex login` first or provide `CODEX_ACCESS_TOKEN`, then run `llm_translate.py` with `--auth chatgpt`. This delegates batches to `codex exec`; `--model` is optional in this mode and overrides the Codex default model when provided.
- For OpenCode, use `--api-base https://opencode.ai/zen/go/v1`; `llm_translate.py` appends `/chat/completions` automatically. `API HTTP 403: error code: 1010` means the upstream gateway rejected the HTTP request before the model handled it. The script sends a browser-like `User-Agent` by default and exposes `--user-agent` for overrides.
- Translation progress is shown as a fixed `0` to `100%` bar based on total translatable entries in the full file, not only the entries translated in the current run. During `--rate-limit` sleeps, the bar temporarily shows a shared `waiting for rate limit reset` countdown and clears it after waiting.
- `llm_translate.py` retries transient API failures up to 3 total attempts. It does not retry unauthorized, forbidden, rate-limit, other 4xx client errors, or partial/mismatched translation batches.
- If a batch reaches the API output token limit, `llm_translate.py` falls back to translating entries individually. If a single-entry request still reaches the limit, it uses a compact single-item JSON prompt and then a plain-text prompt with the same model. If the entry still cannot be translated because of the output token limit, it prints a warning with the entry id, leaves the entry untranslated, and continues.
- Use `--rate-limit N` to cap total API calls per minute across all workers and retry attempts. Use `0` to disable the limiter.
- Always run `controlfix_translations.py` after LLM translation before injecting.

## Ready Translations

- `ready-translations/` contains pretranslated assets in JSON and BPS patch format.
- Only Italian is included for now.
- The included ready translations were made using DeepSeek V4 Flash.

## Known Issues

- The repo is in a very early stage.
- Some text may overflow or glitch out of screen.
- Some screens may flash red or other colors.
- The scripts have mainly been tested with Italian. Other Latin-script languages can be added and tested.

## Maintenance Rules

- When an important change is made to scripts, workflow, output JSON structure, supported languages, ROM assumptions, or repository layout, update both `AGENTS.md` and `README.md` in the same change.
- Keep command examples in `README.md` and `AGENTS.md` aligned.
- Do not add new Meowth runtime dependencies.
- Preserve existing user changes in the working tree. Do not revert unrelated edits.
- Prefer small, focused changes and verify Python scripts with `python3 -m py_compile` when editing them.
