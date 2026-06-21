#!/usr/bin/env python3

import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from queue import Empty, Queue


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
MAX_API_ATTEMPTS = 3

LANGUAGE_NAMES = {
    "de": "German",
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "it": "Italian",
    "pt": "Portuguese",
    "pt-br": "Brazilian Portuguese",
}


class TranslationError(RuntimeError):
    pass


class RetryableTranslationError(TranslationError):
    pass


class OutputTokenLimitError(TranslationError):
    pass


class SkippedTranslation:
    def __init__(self, entry_id, reason):
        self.entry_id = entry_id
        self.reason = reason


class RateLimiter:
    def __init__(self, calls_per_minute):
        self.interval = 60.0 / calls_per_minute if calls_per_minute > 0 else 0.0
        self.lock = threading.Lock()
        self.next_call_at = 0.0

    def wait(self):
        if self.interval <= 0:
            return

        with self.lock:
            now = time.monotonic()
            wait_seconds = max(0.0, self.next_call_at - now)
            self.next_call_at = max(now, self.next_call_at) + self.interval

        if wait_seconds > 0:
            time.sleep(wait_seconds)


def iter_entries(data):
    for table in data.get("tables", []):
        for entry in table.get("entries", []):
            yield entry
    for entry in data.get("free_texts", []):
        yield entry
    for entry in data.get("entries", []):
        yield entry


def iter_entry_refs(data):
    for index, entry in enumerate(iter_entries(data)):
        yield index, entry


def strip_hma_quotes(text):
    if isinstance(text, str) and len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        return text[1:-1]
    return text or ""


def entry_key(index, entry):
    entry_id = entry.get("id")
    if isinstance(entry_id, str) and entry_id:
        return entry_id
    return f"@entry_{index}"


def has_translation(entry):
    translated = entry.get("translated")
    return isinstance(translated, str) and translated.strip() != ""


def collect_existing_translations(data):
    translations = {}
    for index, entry in iter_entry_refs(data):
        if has_translation(entry):
            translations[entry_key(index, entry)] = entry["translated"]
    return translations


def apply_existing_translations(data, existing_data):
    existing = collect_existing_translations(existing_data)
    applied = 0
    for index, entry in iter_entry_refs(data):
        key = entry_key(index, entry)
        if key in existing and not has_translation(entry):
            entry["translated"] = existing[key]
            applied += 1
    return applied


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path, data):
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(f".{output_path.name}.tmp")
    tmp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(output_path)


def target_language_name(target):
    return LANGUAGE_NAMES[target.lower()]


def make_system_prompt(target):
    return (
        "You translate text extracted from Pokemon Unbound.\n"
        f"Translate every item into {target}.\n"
        "Use established official Pokemon terminology for the target language "
        "whenever it exists, especially for moves, items, abilities, types, "
        "Pokemon descriptions, battle text, menu labels, and common franchise phrases.\n"
        "If your environment has access to web pages or retrieval tools, consult "
        "reputable Pokemon references such as Bulbapedia or Pokemon Database for "
        "localized names and descriptions. If you do not have web access, rely on "
        "known official localized terminology and keep uncertain proper nouns unchanged.\n"
        "Return only valid JSON in this exact shape:\n"
        '{"translations":[{"id":"same id","translated":"translated text"}]}\n'
        "Rules:\n"
        "- Return one translation for every input item.\n"
        "- Keep the same ids. Do not invent, omit, merge, or reorder ids.\n"
        "- Preserve all control codes, placeholders, tags, and hex escapes exactly.\n"
        "- Examples of protected tokens include \\n, \\p, \\l, \\CC12, \\btn01, "
        "[red], [blue], {B4}, and {PLAYER}.\n"
        "- Do not add outer quotes unless they are part of the source text.\n"
        "- Keep Pokemon species names, move names, item names, and proper nouns "
        "unchanged when there is no natural translation.\n"
    )


def make_user_prompt(batch, target):
    items = [
        {
            "id": item["id"],
            "category": item["category"],
            "text": item["text"],
        }
        for item in batch
    ]
    return json.dumps(
        {
            "target_language": target,
            "items": items,
        },
        ensure_ascii=False,
    )


def make_single_system_prompt(target):
    return (
        f"Translate one Pokemon Unbound text into {target}.\n"
        "Use established official Pokemon terminology when it exists.\n"
        "Preserve all control codes, placeholders, tags, and hex escapes exactly.\n"
        "Return only valid JSON in this exact shape:\n"
        '{"translated":"translated text"}\n'
    )


def make_single_user_prompt(item, target):
    return json.dumps(
        {
            "target_language": target,
            "id": item["id"],
            "category": item["category"],
            "text": item["text"],
        },
        ensure_ascii=False,
    )


def make_plain_single_system_prompt(target):
    return (
        f"Translate one Pokemon Unbound text into {target}.\n"
        "Use established official Pokemon terminology when it exists.\n"
        "Preserve all control codes, placeholders, tags, and hex escapes exactly.\n"
        "Return only the translated text. Do not return JSON. Do not explain.\n"
    )


def api_endpoint(api_base):
    base = api_base.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def read_response_content(choice):
    message = choice.get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
        return "".join(parts)
    return ""


def parse_model_json(content):
    content = content.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        content = "\n".join(lines).strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for start, char in enumerate(content):
            if char not in "{[":
                continue
            try:
                parsed, _end = decoder.raw_decode(content[start:])
                return parsed
            except json.JSONDecodeError:
                continue
    raise RetryableTranslationError("API returned invalid JSON.")


def validate_translations(payload, batch):
    if isinstance(payload, dict):
        translations = payload.get("translations")
    elif isinstance(payload, list):
        translations = payload
    else:
        translations = None

    if not isinstance(translations, list):
        raise RetryableTranslationError("API response JSON does not contain a translations array.")

    if len(translations) != len(batch):
        raise TranslationError(
            f"API returned {len(translations)} translations for a batch of {len(batch)}; "
            "this is probably a partial response."
        )

    expected_ids = [item["id"] for item in batch]
    received = {}
    for row in translations:
        if not isinstance(row, dict):
            raise RetryableTranslationError("API returned a non-object item in translations.")
        row_id = row.get("id")
        translated = row.get("translated")
        if not isinstance(row_id, str) or not isinstance(translated, str):
            raise RetryableTranslationError(
                "API translation items must contain string id and translated fields."
            )
        if row_id in received:
            raise TranslationError(f"API returned duplicate translation id: {row_id}")
        received[row_id] = translated

    missing = [entry_id for entry_id in expected_ids if entry_id not in received]
    extra = [entry_id for entry_id in received if entry_id not in expected_ids]
    if missing or extra:
        detail = []
        if missing:
            detail.append(f"missing ids: {', '.join(missing[:5])}")
        if extra:
            detail.append(f"unexpected ids: {', '.join(extra[:5])}")
        raise TranslationError("API returned a mismatched batch; " + "; ".join(detail))

    return [received[entry_id] for entry_id in expected_ids]


def validate_single_translation(payload):
    if not isinstance(payload, dict):
        raise RetryableTranslationError("API single-item response is not a JSON object.")
    translated = payload.get("translated")
    if not isinstance(translated, str):
        raise RetryableTranslationError("API single-item response does not contain translated text.")
    return translated


def clean_plain_translation(content):
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None

    if isinstance(parsed, dict) and isinstance(parsed.get("translated"), str):
        return parsed["translated"]
    if isinstance(parsed, str):
        return parsed
    if not text:
        raise RetryableTranslationError("API returned an empty plain translation.")
    return text


class OpenAICompatibleClient:
    def __init__(
        self,
        api_base,
        api_key,
        model,
        max_tokens,
        temperature,
        timeout,
        user_agent,
        rate_limiter,
    ):
        self.endpoint = api_endpoint(api_base)
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        self.user_agent = user_agent
        self.rate_limiter = rate_limiter

    def translate_batch(self, batch, target):
        try:
            return self.translate_batch_with_retries(batch, target)
        except OutputTokenLimitError:
            if len(batch) > 1:
                translations = []
                for item in batch:
                    translations.append(self.translate_single_or_skip(item, target))
                return translations
            return [self.translate_single_or_skip(batch[0], target)]

    def translate_single_or_skip(self, item, target):
        try:
            return self.translate_single_item(item, target)
        except OutputTokenLimitError as exc:
            return SkippedTranslation(item["id"], str(exc))

    def translate_batch_with_retries(self, batch, target):
        last_error = None
        for attempt in range(1, MAX_API_ATTEMPTS + 1):
            try:
                return self.translate_batch_once(batch, target)
            except RetryableTranslationError as exc:
                last_error = exc
                if attempt == MAX_API_ATTEMPTS:
                    break
                time.sleep(min(2 ** (attempt - 1), 8))

        raise TranslationError(
            f"API request failed after {MAX_API_ATTEMPTS} attempts: {last_error}"
        ) from last_error

    def translate_batch_once(self, batch, target):
        content = self.chat(
            [
                {"role": "system", "content": make_system_prompt(target)},
                {"role": "user", "content": make_user_prompt(batch, target)},
            ],
            self.max_tokens,
        )
        parsed = parse_model_json(content)
        return validate_translations(parsed, batch)

    def translate_single_item(self, item, target):
        try:
            return self.translate_single_item_with_retries(item, target)
        except OutputTokenLimitError:
            return self.translate_single_item_plain(item, target)

    def translate_single_item_with_retries(self, item, target):
        last_error = None
        for attempt in range(1, MAX_API_ATTEMPTS + 1):
            try:
                return self.translate_single_item_once(item, target)
            except RetryableTranslationError as exc:
                last_error = exc
                if attempt == MAX_API_ATTEMPTS:
                    break
                time.sleep(min(2 ** (attempt - 1), 8))

        raise TranslationError(
            f"API single-item request failed after {MAX_API_ATTEMPTS} attempts: {last_error}"
        ) from last_error

    def translate_single_item_once(self, item, target):
        content = self.chat(
            [
                {"role": "system", "content": make_single_system_prompt(target)},
                {"role": "user", "content": make_single_user_prompt(item, target)},
            ],
            self.single_item_max_tokens(),
        )
        parsed = parse_model_json(content)
        return validate_single_translation(parsed)

    def translate_single_item_plain(self, item, target):
        last_error = None
        for attempt in range(1, MAX_API_ATTEMPTS + 1):
            try:
                content = self.chat(
                    [
                        {"role": "system", "content": make_plain_single_system_prompt(target)},
                        {"role": "user", "content": make_single_user_prompt(item, target)},
                    ],
                    self.single_item_max_tokens(),
                )
                return clean_plain_translation(content)
            except OutputTokenLimitError:
                raise
            except RetryableTranslationError as exc:
                last_error = exc
                if attempt == MAX_API_ATTEMPTS:
                    break
                time.sleep(min(2 ** (attempt - 1), 8))

        raise TranslationError(
            f"API plain single-item request failed after {MAX_API_ATTEMPTS} attempts: {last_error}"
        ) from last_error

    def single_item_max_tokens(self):
        return max(self.max_tokens + 1024, self.max_tokens * 2)

    def chat(self, messages, max_tokens):
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": max_tokens,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": self.user_agent,
            },
            method="POST",
        )

        self.rate_limiter.wait()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            message = f"API HTTP {exc.code}: {detail[:1000]}"
            if exc.code in {401, 403, 429} or 400 <= exc.code < 500:
                raise TranslationError(message) from exc
            raise RetryableTranslationError(message) from exc
        except urllib.error.URLError as exc:
            raise RetryableTranslationError(f"API request failed: {exc}") from exc

        try:
            response_data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RetryableTranslationError("API returned a non-JSON HTTP response.") from exc

        choices = response_data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RetryableTranslationError("API response does not contain choices.")

        choice = choices[0]
        finish_reason = choice.get("finish_reason")
        if finish_reason and finish_reason != "stop":
            if finish_reason == "length":
                raise OutputTokenLimitError("API response hit the output token limit.")
            raise TranslationError(f"API response finished with reason {finish_reason!r}.")

        content = read_response_content(choice)
        if not content.strip():
            raise RetryableTranslationError("API returned an empty message.")

        return content


def build_work_items(data):
    work = []
    skipped_empty = 0
    already_translated = 0

    for index, entry in iter_entry_refs(data):
        if has_translation(entry):
            already_translated += 1
            continue

        original = strip_hma_quotes(entry.get("original", ""))
        if not original:
            skipped_empty += 1
            continue

        work.append(
            {
                "id": entry_key(index, entry),
                "category": entry.get("category", ""),
                "text": original,
                "entry": entry,
            }
        )

    return work, already_translated, skipped_empty


def chunked(items, size):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def progress_bar(completed, total, width=36):
    if total <= 0:
        percent = 100.0
        filled = width
    else:
        percent = completed / total * 100
        filled = round(width * completed / total)
    empty = width - filled
    return f"[{'#' * filled}{'.' * empty}] {percent:6.2f}% ({completed}/{total})"


def render_progress(completed, total):
    sys.stdout.write("\r" + progress_bar(completed, total))
    sys.stdout.flush()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Translate extracted Pokemon Unbound text with an OpenAI-compatible API."
    )
    parser.add_argument("input", help="Extracted JSON file to translate.")
    parser.add_argument(
        "-o",
        "--output",
        help="Output JSON path. Defaults to <input-stem>-<target>.json.",
    )
    parser.add_argument(
        "--target",
        required=True,
        choices=sorted(LANGUAGE_NAMES),
        help="Target Latin-script language code. Supported: %(choices)s.",
    )
    parser.add_argument(
        "--api-base",
        default=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        help="OpenAI-compatible API base URL. Defaults to OPENAI_BASE_URL or OpenAI v1.",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("OPENAI_API_KEY"),
        help="API key. Defaults to OPENAI_API_KEY.",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("OPENAI_MODEL"),
        help="Model name. Defaults to OPENAI_MODEL.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Parallel API workers. Default: 1.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=20,
        help="Sentences per API call. Default: 20.",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=4096,
        help="Maximum output tokens per API call. Default: 4096.",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.2,
        help="Sampling temperature. Default: 0.2.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="HTTP timeout in seconds. Default: 120.",
    )
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        help="HTTP User-Agent header. Some gateways reject Python's default client.",
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=0.0,
        help="Maximum API calls per minute across all workers. Use 0 to disable. Default: 0.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from an existing output JSON and translate only missing entries.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing output JSON instead of resuming from it.",
    )
    return parser.parse_args()


def validate_args(args, output_path):
    if not args.api_key:
        raise SystemExit("error: --api-key is required or OPENAI_API_KEY must be set")
    if not args.model:
        raise SystemExit("error: --model is required or OPENAI_MODEL must be set")
    if args.workers < 1:
        raise SystemExit("error: --workers must be >= 1")
    if args.batch_size < 1:
        raise SystemExit("error: --batch-size must be >= 1")
    if args.max_tokens < 1:
        raise SystemExit("error: --max-tokens must be >= 1")
    if args.timeout <= 0:
        raise SystemExit("error: --timeout must be > 0")
    if args.rate_limit < 0:
        raise SystemExit("error: --rate-limit must be >= 0")
    if output_path.exists() and not args.resume and not args.overwrite:
        raise SystemExit(
            f"error: {output_path} already exists; use --resume to continue or --overwrite to replace it"
        )
    if args.resume and args.overwrite:
        raise SystemExit("error: --resume and --overwrite cannot be used together")


def main():
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path.with_name(
        f"{input_path.stem}-{args.target}.json"
    )
    validate_args(args, output_path)

    data = load_json(input_path)
    if args.resume and output_path.exists():
        applied = apply_existing_translations(data, load_json(output_path))
        print(f"resume: restored {applied} completed translations from {output_path}")
    elif args.resume:
        print(f"resume: {output_path} does not exist yet; starting from input JSON")

    work, already_translated, skipped_empty = build_work_items(data)
    total_entries = sum(1 for _index, _entry in iter_entry_refs(data))
    total_translatable = already_translated + len(work)

    print(f"entries: {total_entries}")
    print(f"translatable entries: {total_translatable}")
    print(f"already translated: {already_translated}")
    print(f"missing translations: {len(work)}")
    print(f"skipped empty originals: {skipped_empty}")

    if not work:
        save_json(output_path, data)
        render_progress(total_translatable, total_translatable)
        print()
        print(f"output: {output_path}")
        return 0

    target = target_language_name(args.target)
    batches = list(enumerate(chunked(work, args.batch_size), start=1))
    batch_queue = Queue()
    for batch_number, batch in batches:
        batch_queue.put((batch_number, batch))

    client = OpenAICompatibleClient(
        args.api_base,
        args.api_key,
        args.model,
        args.max_tokens,
        args.temperature,
        args.timeout,
        args.user_agent,
        RateLimiter(args.rate_limit),
    )

    lock = threading.Lock()
    stop_event = threading.Event()
    errors = []
    translated_this_run = 0
    skipped_token_limit = 0
    completed_total = already_translated

    render_progress(completed_total, total_translatable)

    def worker():
        nonlocal completed_total, skipped_token_limit, translated_this_run
        while not stop_event.is_set():
            try:
                _batch_number, batch = batch_queue.get_nowait()
            except Empty:
                return

            try:
                translations = client.translate_batch(batch, target)
                if stop_event.is_set():
                    return

                with lock:
                    batch_translated = 0
                    for item, translated in zip(batch, translations):
                        if isinstance(translated, SkippedTranslation):
                            skipped_token_limit += 1
                            sys.stdout.write("\n")
                            print(
                                f"warning: skipped {translated.entry_id} due to output token limit"
                            )
                            continue
                        item["entry"]["translated"] = translated
                        batch_translated += 1
                    translated_this_run += batch_translated
                    completed_total += batch_translated
                    save_json(output_path, data)
                    render_progress(completed_total, total_translatable)
            except Exception as exc:
                with lock:
                    if not errors:
                        errors.append(exc)
                    stop_event.set()
                return
            finally:
                batch_queue.task_done()

    threads = [
        threading.Thread(target=worker, name=f"translator-{index + 1}")
        for index in range(min(args.workers, len(batches)))
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    print()
    if errors:
        print(f"error: {errors[0]}", file=sys.stderr)
        print(
            "stopped: completed batches were saved; rerun with --resume after fixing the issue",
            file=sys.stderr,
        )
        return 1

    print(f"translated this run: {translated_this_run}")
    if skipped_token_limit:
        print(f"skipped due to output token limit: {skipped_token_limit}")
    print(f"output: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
