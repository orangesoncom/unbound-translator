#!/usr/bin/env python3

import argparse
import json
import re
from pathlib import Path

from injector import Charmap, encode_text, strip_hma_quotes


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

WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ']+")

EXACT_OVERRIDES = {
    "tbl_menu_pc_03741": "Scegli un tema.",
    "tbl_menu_pc_03743": r"\?00 scelto.",
    "tbl_menu_pc_03744": "Vai a quale Box?",
    "tbl_menu_pc_03745": "In quale Box?",
    "tbl_menu_pc_03746": r"\?00 deposto.",
    "tbl_menu_pc_03748": "Libera Pokémon?",
    "tbl_menu_pc_03749": r"\?00 liberato.",
    "tbl_menu_pc_03751": "Segna Pokémon.",
    "tbl_menu_pc_03753": "Squadra piena!",
    "tbl_menu_pc_03756": "Non puoi liberare Uovo.",
    "tbl_menu_pc_03757": "Continuare Box?",
    "tbl_menu_pc_03761": "Rimuovi il Messaggio.",
    "tbl_menu_pc_03763": "Dare al Pokémon?",
    "tbl_menu_pc_03764": "Oggetto nel Cubo.",
    "tbl_menu_pc_03766": "Mettere nel Cubo?",
    "tbl_menu_pc_03767": r"\?00 tenuto.",
    "tbl_menu_pc_03769": "Lettera non archiviabile!",
    "tbl_menu_pokemon_03773": "Scegli Pokémon.",
    "tbl_menu_pokemon_03774": "Scegli o Annulla.",
    "tbl_menu_pokemon_03775": "Scegli e conferma.",
    "tbl_menu_pokemon_03777": "A chi insegnarla?",
    "tbl_menu_pokemon_03778": "Su chi usarlo?",
    "tbl_menu_pokemon_03779": "A chi darlo?",
    "tbl_menu_pokemon_03780": "Niente da Taglio.",
    "tbl_menu_pokemon_03781": "Qui niente Surf!",
    "tbl_menu_pokemon_03782": "Stai già surfando.",
    "tbl_menu_pokemon_03783": "Corrente troppo forte!",
    "tbl_menu_pokemon_03784": "Goditi la bici!",
    "tbl_menu_pokemon_03785": "Già in uso.",
    "tbl_menu_pokemon_03786": "Qui non si usa.",
    "tbl_menu_pokemon_03787": "Qui non si lotta!",
    "tbl_menu_pokemon_03789": "PS scarsi",
    "tbl_menu_pokemon_03790": "Servono [buffer1] Pokémon.",
    "tbl_menu_pokemon_03791": "Ne servono due.",
    "tbl_menu_pokemon_03792": r"\pk\mn diversi.",
    "tbl_menu_pokemon_03793": "Strum. diversi!",
    "tbl_menu_pokemon_03795": r"Che fare con \pk\mn?",
    "tbl_menu_pokemon_03796": "Quale mossa?",
    "tbl_menu_pokemon_03797": "PP a quale?",
    "tbl_menu_pokemon_03798": "Che fare con ogg.?",
    "tbl_menu_pokemon_03799": "Che fare con lettera?",
    "tbl_menu_pokemon_options_03812": "Scheda",
    "tbl_menu_pokemon_options_03813": "Scamb.",
    "tbl_menu_pokemon_options_03814": "Esci",
    "tbl_menu_pokemon_options_03815": "Item",
    "tbl_menu_pokemon_options_03817": "Togli",
    "tbl_menu_pokemon_options_03818": "Mail",
    "tbl_menu_pokemon_options_03819": "Togli",
    "tbl_menu_pokemon_options_03820": "Legg",
    "tbl_menu_pokemon_options_03821": "Esci",
    "tbl_menu_pokemon_options_03822": "Muovi",
    "tbl_menu_pokemon_options_03825": "Blocca",
    "tbl_menu_pokemon_options_03826": "Poni",
    "tbl_menu_pokemon_options_03828": "Trade",
    "tbl_menu_pokemon_options_03829": "Trade",
    "tbl_menu_pokemon_options_03830": "Move",
    "tbl_menu_options_03732": "Vel. testo",
    "tbl_menu_options_03736": "Mod. tasti",
    "tbl_menu_options_03737": "Corn.",
    "tbl_menu_options_03738": "OK",
    "tbl_trade_messages_03831": "Non è il Pokémon richiesto.",
    "tbl_trade_messages_03833": "Pokémon non scambiabile ora.",
    "tbl_trade_messages_03834": "Pokémon non scambiabile ora.",
    "tbl_trade_messages_03835": "Pokémon altrui non scambiabile.",
    "tbl_trade_messages_03836": "Uovo non scambiabile ora.",
    "tbl_trade_messages_03837": "L'altro All. non lo accetta ora.",
    "tbl_trade_messages_03838": "Scambio con quell'All. negato.",
    "tbl_trade_messages_03839": "Scambio con quell'All. negato.",
    "tbl_menu_pause_03807": "Save",
    "tbl_menu_pause_03808": "Opz.",
    "tbl_menu_pause_03810": "Ritira",
    "tbl_menu_item_storage_03800": "Preleva ogg.",
    "tbl_menu_item_storage_03801": "Dep. ogg.",
    "tbl_menu_item_storage_03802": "Esci",
    "tbl_menu_pcoptions_03770": "Box ogg.",
    "tbl_habitat_names_03723": "Prateria",
    "tbl_habitat_names_03724": "Bosco",
    "tbl_habitat_names_03725": "Riva",
    "tbl_habitat_names_03726": "Mare",
    "tbl_habitat_names_03727": "Grotta",
    "tbl_habitat_names_03728": "Monte",
    "tbl_habitat_names_03729": "Roccia",
    "tbl_habitat_names_03730": "Città",
    "tbl_habitat_names_03731": "Raro",
    "tbl_ability_descriptions_02717": "Nessuna abilità.",
    "tbl_ability_descriptions_02718": "Respinge Pokémon selvatici.",
}

MOVE_REPLACEMENTS = [
    ("L'utilizzatore", "Chi usa"),
    ("Il nemico viene", "Il nemico è"),
    ("Il bersaglio viene", "Il bersaglio è"),
    ("Il nemico ", ""),
    ("Il bersaglio ", ""),
    ("Questo attacco", "Quest'att."),
    ("attacco fisico", "att. fisico"),
    ("attacco speciale", "att. spec."),
    ("attacco", "colpo"),
    ("viene attaccato", "è colpito"),
    ("viene colpito", "è colpito"),
    ("viene schiaffeggiato", "è schiaff."),
    ("viene costretto", "è costretto"),
    ("ripetutamente", "più volte"),
    ("da due a cinque volte", "2-5 volte"),
    ("da due a tre volte", "2-3 volte"),
    ("da uno a cinque volte", "1-5 volte"),
    ("brutto colpo", "colpo crit."),
    ("molto alta", "alta"),
    ("molto alto", "alto"),
    ("notevolmente", "molto"),
    ("leggermente", "poco"),
    ("statistica", "stat."),
    ("statistiche", "stat."),
    ("probabilità", "prob."),
    ("Può lasciare il", "Può dare"),
    ("può lasciare il", "può dare"),
    ("Può lasciare la", "Può dare"),
    ("può lasciare la", "può dare"),
    ("Può lasciare", "Può dare"),
    ("potrebbe lasciare", "può dare"),
    ("Può anche", "Può"),
    ("potrebbe", "può"),
    ("viene usato", "usato"),
    ("durante la lotta", "in lotta"),
    ("nel turno successivo", "turno dopo"),
    ("nel turno seguente", "turno dopo"),
    ("per tre turni", "per 3 turni"),
    ("per cinque turni", "per 5 turni"),
    ("per il resto della lotta", "fino a fine lotta"),
    ("in combattimento", "in lotta"),
    ("Aumenta", "Alza"),
    ("Diminuisce", "Riduce"),
]

MOVE_WORD_REPLACEMENTS = [
    ("effettuato", "fatto"),
    ("effettuata", "fatta"),
    ("effettuati", "fatti"),
    ("effettuate", "fatte"),
    ("anteriore", "ant."),
    ("anteriori", "ant."),
    ("utilizzatore", "utente"),
    ("utilizzato", "usato"),
    ("utilizzata", "usata"),
    ("utilizzati", "usati"),
    ("utilizzate", "usate"),
    ("avversario", "nemico"),
    ("avversari", "nemici"),
    ("probabilità", "prob."),
    ("danneggia", "colpisce"),
    ("danneggiano", "colpiscono"),
    ("infligge", "causa"),
    ("infliggere", "causare"),
    ("riducendo", "riduce"),
    ("abbassando", "abbassa"),
]

GENERIC_REPLACEMENTS = [
    ("Per favore, ", ""),
    ("per favore, ", ""),
    ("Cosa vuoi fare?", "Che fare?"),
    ("Continuare le operazioni del Box", "Continuare Box"),
    ("È così ", "È "),
    ("molto più ", "più "),
    ("molto ", ""),
    (" davvero ", " "),
    (" proprio ", " "),
    (" abbastanza ", " "),
    (" soltanto ", " "),
    (" solamente ", " "),
    ("già ", "gia "),
    ("Allenatore", "All."),
    ("Allenatori", "All."),
    ("allenatore", "all."),
    ("allenatori", "all."),
    ("abilità", "abil."),
    ("speciale", "spec."),
    ("speciali", "spec."),
    ("battaglia", "lotta"),
    ("battaglie", "lotte"),
    ("combattimento", "lotta"),
    ("combattimenti", "lotte"),
    ("difficile", "diff."),
    ("difficili", "diff."),
    ("facile", "fac."),
    ("facili", "fac."),
    ("facilmente", "facilm."),
    ("normale", "norm."),
    ("normali", "norm."),
    ("operazioni", "operaz."),
    ("immediatamente", "subito"),
    ("velocemente", "rapido"),
    ("rapidamente", "rapido"),
    ("probabilità", "prob."),
    ("statistica", "stat."),
    ("statistiche", "stat."),
    ("Pokémon", "Poké."),
    ("strumento", "ogg."),
    ("strumenti", "ogg."),
    ("oggetto", "ogg."),
    ("oggetti", "ogg."),
    ("messaggio", "msg"),
    ("messaggi", "msg"),
    ("bicicletta", "bici"),
    ("Medaglia", "Med."),
    ("Palestra", "Palestra"),
]

GENERIC_WORD_REPLACEMENTS = [
    ("registrati", "reg."),
    ("registrato", "reg."),
    ("registrata", "reg."),
    ("registrate", "reg."),
    ("registrare", "reg."),
    ("dovresti", "devi"),
    ("dovrebbe", "deve"),
    ("dovrebbero", "devono"),
    ("potresti", "puoi"),
    ("potrebbe", "può"),
    ("potrebbero", "possono"),
    ("attraversare", "passare"),
    ("attraversarlo", "passarlo"),
    ("attraversarla", "passarla"),
    ("attraverso", "tramite"),
    ("mantenere", "tenere"),
    ("mantenerti", "tenerti"),
    ("mantenuto", "tenuto"),
    ("mantenuta", "tenuta"),
    ("difficoltà", "diff."),
    ("normalmente", "di norma"),
    ("facilmente", "facilm."),
]

STOPWORDS = [
    " davvero ",
    " proprio ",
    " allora ",
    " quindi ",
    " anche ",
    " molto ",
    " tanto ",
    " tutti ",
    " tutte ",
    " tutto ",
    " della ",
    " delle ",
    " degli ",
    " dello ",
    " della ",
    " del ",
    " dei ",
    " degli ",
    " dell'",
    " della ",
    " il ",
    " lo ",
    " la ",
    " le ",
    " gli ",
    " i ",
    " un ",
    " uno ",
    " una ",
]

ENDINGS = [
    ("mente", "m."),
    ("zione", "z."),
    ("zioni", "z."),
    ("zione.", "z."),
    ("zioni.", "z."),
    ("azione", "az."),
    ("azioni", "az."),
    ("atore", "at."),
    ("atori", "at."),
    ("atrice", "atr."),
    ("atrici", "atr."),
    ("ibile", "ib."),
    ("ibili", "ib."),
    ("amente", "am."),
]


def iter_entries(data):
    for table in data.get("tables", []):
        for entry in table.get("entries", []):
            yield entry
    for entry in data.get("free_texts", []):
        yield entry
    for entry in data.get("entries", []):
        yield entry


def protect(text):
    codes = []

    def repl(match):
        placeholder = f"\x00{len(codes)}\x00"
        codes.append(match.group(0))
        return placeholder

    return TOKEN_RE.sub(repl, text), codes


def restore(text, codes):
    for i, code in enumerate(codes):
        text = text.replace(f"\x00{i}\x00", code)
    return text


def normalize_spacing(text):
    text = text.replace("\r\n", "\n")
    text = re.sub(r"\s*\\n\s*", r"\\n", text)
    text = re.sub(r"\s*\\p\s*", r"\\p", text)
    text = re.sub(r"\s*\\l\s*", r"\\l", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = re.sub(r"\s+([,.;!?])", r"\1", text)
    text = re.sub(r"([(\[])\s+", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def encoded_length(cmap, text):
    return len(encode_text(cmap, text))


def fits(cmap, text, max_len):
    return encoded_length(cmap, text) <= max_len


def apply_simple_replacements(text, replacements):
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def apply_word_replacements(text, replacements):
    protected, codes = protect(text)
    for old, new in replacements:
        protected = re.sub(rf"\b{re.escape(old)}\b", new, protected)
    return restore(protected, codes)


def drop_stopword_once(text, word):
    return text.replace(word, " ")


def shorten_word(word, aggressive=False):
    original = word
    lower = word.lower()

    for old, new in ENDINGS:
        if lower.endswith(old):
            word = word[: len(word) - len(old)] + new
            return word

    if len(word) >= 8:
        first = word[:2]
        middle = word[2:-1]
        last = word[-1]
        middle = re.sub(r"[aeiouàèéìòóùAEIOUÀÈÉÌÒÓÙ]", "", middle)
        candidate = first + middle + last
        if len(candidate) < len(word):
            word = candidate

    if aggressive and len(word) >= 6 and word[-1].lower() in "aeiouàèéìòóù":
        word = word[:-1]

    if aggressive and len(word) >= 7:
        word = word[: max(4, len(word) - 2)] + "."

    return word if word else original


def shorten_longest_word(text, aggressive=False):
    protected, codes = protect(text)
    words = list(WORD_RE.finditer(protected))
    if not words:
        return text, False

    words.sort(key=lambda m: len(m.group(0)), reverse=True)
    for match in words:
        word = match.group(0)
        if "\x00" in word or len(word) <= 4:
            continue
        shorter = shorten_word(word, aggressive=aggressive)
        if shorter != word:
            protected = protected[: match.start()] + shorter + protected[match.end() :]
            return restore(protected, codes), True
    return text, False


def remove_trailing_text(text):
    protected, codes = protect(text)
    words = list(WORD_RE.finditer(protected))
    if not words:
        return text, False
    match = words[-1]
    protected = protected[: match.start()] + protected[match.end() :]
    protected = re.sub(r"\s+([,.;!?])", r"\1", protected)
    protected = re.sub(r"\s{2,}", " ", protected).strip(" ,.;!?")
    return restore(protected, codes), True


def hard_trim(text, cmap, max_len):
    while text and not fits(cmap, text, max_len):
        new_text, changed = remove_trailing_text(text)
        if changed and new_text != text:
            text = new_text
            continue
        text = text[:-1].rstrip()
    return text


def category_rules(entry, text):
    category = entry.get("category")
    if category == "move_descriptions":
        text = apply_simple_replacements(text, MOVE_REPLACEMENTS)
        text = apply_word_replacements(text, MOVE_WORD_REPLACEMENTS)
    return text


def generic_rules(text):
    text = apply_simple_replacements(text, GENERIC_REPLACEMENTS)
    text = apply_word_replacements(
        text,
        GENERIC_WORD_REPLACEMENTS
        + [
            ("questo", "sto"),
            ("questa", "sta"),
            ("questi", "sti"),
            ("queste", "ste"),
            ("quello", "quel"),
            ("quella", "quella"),
            ("quelli", "quei"),
            ("quelle", "quelle"),
            ("essere", "esser"),
            ("qualcosa", "qcs."),
            ("qualcuno", "qcn."),
            ("qualsiasi", "qualunq."),
        ],
    )
    return text


def squeeze_to_fit(entry, text, cmap):
    max_len = int(entry["byte_length"])

    text = normalize_spacing(text)
    if fits(cmap, text, max_len):
        return text

    text = category_rules(entry, text)
    text = normalize_spacing(text)
    if fits(cmap, text, max_len):
        return text

    text = generic_rules(text)
    text = normalize_spacing(text)
    if fits(cmap, text, max_len):
        return text

    for stopword in STOPWORDS:
        if fits(cmap, text, max_len):
            break
        text = drop_stopword_once(text, stopword)
        text = normalize_spacing(text)

    aggressive = False
    for _ in range(80):
        if fits(cmap, text, max_len):
            return text
        text, changed = shorten_longest_word(text, aggressive=aggressive)
        text = normalize_spacing(text)
        if not changed:
            aggressive = True
            break

    for _ in range(80):
        if fits(cmap, text, max_len):
            return text
        text, changed = shorten_longest_word(text, aggressive=True)
        text = normalize_spacing(text)
        if not changed:
            break

    text = hard_trim(text, cmap, max_len)
    return normalize_spacing(text)


def main():
    parser = argparse.ArgumentParser(description="Shorten translated text to fit byte slots.")
    parser.add_argument("json_path")
    parser.add_argument("-o", "--output")
    parser.add_argument("--target-lang", default="it")
    args = parser.parse_args()

    path = Path(args.json_path)
    output = Path(args.output) if args.output else path
    data = json.loads(path.read_text(encoding="utf-8"))
    cmap = Charmap(target_lang=args.target_lang)

    changed = 0
    fitted = 0
    unchanged = 0

    for entry in iter_entries(data):
        translated = strip_hma_quotes(entry.get("translated", ""))
        if not translated:
            continue

        original = translated
        if entry.get("id") in EXACT_OVERRIDES:
            translated = EXACT_OVERRIDES[entry["id"]]

        translated = squeeze_to_fit(entry, translated, cmap)

        if translated != original:
            entry["translated"] = translated
            changed += 1
        else:
            unchanged += 1

        if fits(cmap, translated, int(entry["byte_length"])):
            fitted += 1

    output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"changed={changed}")
    print(f"unchanged={unchanged}")
    print(f"fitted={fitted}")


if __name__ == "__main__":
    main()
