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

## Sample (identical for all three writers, different order)

- NeCCo: 35 items × 6 categories = 210 items (question + 4 options each)
- Belebele: 50 passages with all 143 of their questions
- 15 NeCCo items repeated in the second half under a new code (self-consistency)
- 1,640 rows and about 8,900 Devanagari words per writer, roughly 8–10 hours of typing

## Choosing writers

- Three people who **regularly type Nepali in English letters** in chat, ideally from different
  regions (e.g. Kathmandu Valley, eastern hills, Terai/western) and not all the same age group.
- Not linguists or NLP people, and not people who have seen this project's romanized data.
- They must not compare notes with each other until all three are done.

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
