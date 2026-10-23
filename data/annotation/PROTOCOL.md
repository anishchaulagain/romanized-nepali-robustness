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

## Design: 600 questions, 3 writers per item, any number of writers

- NeCCo: 75 items × 6 categories = 450 items (question + 4 options each)
- Belebele: 82 passages with all 150 of their questions
- The app shares the units among the active writers so that every unit is written by exactly 3 of them, the
  work per writer is even, and pairs of writers overlap evenly. When writers join or leave, units nobody has
  started are shared out again.
- 20 NeCCo units are repeated later under a new number, to the same writers as the original.
- Per writer with 4 writers: about 2,400 boxes, roughly 12 hours of typing (every pair shares about 265 units).
  With 6 writers: about 1,600 boxes, 8–9 hours (every pair shares about 105 units).

Why this size: 600 questions lets a paired difference of about 5 accuracy points be detected (McNemar,
α = 0.05, power 0.8, assuming 20% of items flip between conditions); 353 questions would detect only about
6.6 points. More writers make writer effects easier to estimate rather than attribute to a few individuals;
six or more is the target, and four is workable.

## Choosing writers

- Six people who **regularly type Nepali in English letters** in chat, ideally from different regions
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
