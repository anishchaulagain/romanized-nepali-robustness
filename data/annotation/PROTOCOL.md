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

## Design: 600 questions, 6 writers, 3 writers per item

- NeCCo: 75 items × 6 categories = 450 items (question + 4 options each)
- Belebele: 82 passages with all 150 of their questions
- Each unit goes to one of the 20 possible groups of 3 writers (rotating within each category), so every
  unit is written by exactly 3 writers, each writer does half the units, and each pair of writers shares
  about 120 questions.
- 20 NeCCo units (one per writer group) are repeated later under a new number: 10 repeats per writer.
- Per writer: about 300 questions, 1,600 boxes and 7,900 Devanagari words, roughly 8–9 hours of typing.

Why this size: 600 questions lets a paired difference of about 5 accuracy points be detected (McNemar,
α = 0.05, power 0.8, assuming 20% of items flip between conditions); 353 questions would detect only about
6.6 points. Six writers let writer effects be estimated rather than attributed to three individuals.

## Choosing writers

- Six people who **regularly type Nepali in English letters** in chat, ideally from different regions
  (e.g. Kathmandu Valley, eastern hills, western hills, Terai) and a mix of age groups.
- Not linguists or NLP people, and not people who have seen this project's romanized data.
- They must not compare notes with each other until all are done.
- In the app, create them as writers; slots 1–6 are filled in order. If someone drops out, disable them and
  create the replacement in the same slot.

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
