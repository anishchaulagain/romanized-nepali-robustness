# Natural romanization: three-writer protocol

Researcher-facing notes. Collection now runs through the web app in
`apps/romanized-data-collection/` (same sample, same per-writer random order and hidden repeats, plus paste
blocking and active-time logging). The spreadsheets in `sheets/` remain as an offline fallback; writers using
them only need the workbook's Instructions sheet.

## Files

| Path | Who sees it | Contents |
|---|---|---|
| `sheets/romanization_W1.xlsx` … `W3.xlsx` | One writer each | Devanagari segments, empty yellow column to fill |
| `key/manifest.csv` | Researcher only | Maps each row code (`W1-0001`) to source item, field, existing romanization (R-std), gold answer, repeat flag |

Regenerate with `python scripts/prepare_annotation.py` (fixed seed, so it produces the same sample).
Regenerating after sheets have been sent is safe only if nothing in the script changed.

## Design: 241 questions, 3 writers, every writer writes every item

- NeCCo: 30 items × 6 categories = 180 items (question + 4 options each)
- Belebele: 34 passages with all 61 of their questions
- 20 NeCCo units are repeated later under a new number (self-consistency).
- Per writer: about 1,330 boxes and 7,000 Devanagari words, roughly 5–6 hours of typing.
- Chosen with a fixed seed from a pool of 600 questions (`backend/seed/subset.json`); it can be enlarged later.

Why this size: with the pilot's discordance rates, a 10-point paired gap between Devanagari and natural romanization
is detectable for a single model (McNemar, α = 0.05, power 0.8), and a ~3-point gap between tool and natural
romanization when pooling models and writers. Three writers on every item give a fully crossed design for
measuring how much answers change between writers.

## Choosing writers

- Three (or more) people who **regularly type Nepali in English letters** in chat, ideally from different regions
  (e.g. Kathmandu Valley, eastern hills, western hills, Terai) and a mix of age groups.
- Not linguists or NLP people, and not people who have seen this project's romanized data.
- They must not compare notes with each other until all are done.
- In the app, create each person as a writer; the work is shared among however many are active (each item still
  gets 3 writers). If someone drops out, disable them: the items they had not started go to the others.

## Rules writers must follow (already in the Instructions sheet)

- Own spelling, chat-style; same words in the same order; no translating or rephrasing.
- No Google Translate, transliteration keyboards or tools, and no help from others.
- Several short sessions are fine.

## When sheets come back

1. Check the "About You" sheet is filled in and the consent answer is "yes".
2. Check completion (the progress line on the Instructions sheet) and skim for rows that look
   machine-transliterated (e.g. consistent doubled long vowels like `aa`/`ii` everywhere).
3. Save the returned files under `returned/` (do not overwrite `sheets/`).
4. The next script (to be written) merges `returned/*.xlsx` with `key/manifest.csv` into the
   paired dataset and computes between-writer and within-writer variation.

## Still to decide

- Compensation for writers.
- Whether the code-mixed (R-cm) version is a second pass by the same writers or a separate person.
