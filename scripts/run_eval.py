"""Ask models the benchmark questions in every condition, on free API tiers, and score the answers.

Each (item, condition, writer) becomes one prompt: D, R-tool and R-std are the same for all writers of an item, R-nat
has one version per writer. Answers are appended to results/<model>.jsonl as they arrive, so a run can be stopped
and resumed (and spread over several days of free quota) without asking anything twice. Each provider is called no
faster than its free-tier limit, with retries and back-off on rate-limit and server errors.

Usage:
  python scripts/run_eval.py --models ministral-8b gpt-oss-20b [--items data/collected/eval_items.jsonl] [--limit N]
  python scripts/run_eval.py --summary            # accuracy per model and condition, paired on the same items
API keys are read from .env at the repository root or from apps/romanized-data-collection/backend/.env.
"""
import argparse
import json
import re
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / 'results'
OPTIONS = ['A', 'B', 'C', 'D']
UA = 'Mozilla/5.0 (research evaluation script)'

# name: (provider, model id, extra request fields). Model ids are pinned to versions where the provider offers them.
MODELS = {
    'ministral-8b': ('mistral', 'ministral-8b-2512', {}),
    'gpt-oss-20b': ('groq', 'openai/gpt-oss-20b', {'reasoning_effort': 'low'}),
    'qwen3.8-27b': ('groq', 'qwen/qwen3.8-27b', {'reasoning_effort': 'none'}),
    'gemma-4-26b-a4b': ('gemini', 'gemma-4-26b-a4b-it', {'maxOutputTokens': 4096}),  # thinks before answering
    'gemini-3.5-flash': ('gemini', 'gemini-3.5-flash', {'thinkingConfig': {'thinkingLevel': 'low'}}),
    'gemini-3.1-flash-lite': ('gemini', 'gemini-3.1-flash-lite', {}),
}
PROVIDERS = {  # endpoint, key name, seconds between calls (free tier)
    'mistral': ('https://api.mistral.ai/v1/chat/completions', 'MISTRAL_API_KEY', 1.2),
    'groq': ('https://api.groq.com/openai/v1/chat/completions', 'GROQ_API_KEY', 3.0),
    'gemini': ('https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent', 'GEMINI_API_KEY', 6.0),
    'openrouter': ('https://openrouter.ai/api/v1/chat/completions', 'OPENROUTER_API_KEY', 1.0),
}

INSTRUCTION = ('The following is a multiple-choice question in Nepali. Answer with only the letter of the correct '
               'option (A, B, C or D).')


def load_env():
    env = {}
    for path in (ROOT / 'apps/romanized-data-collection/backend/.env', ROOT / '.env'):
        if path.exists():
            for line in path.read_text(encoding='utf-8').splitlines():
                if '=' in line and not line.strip().startswith('#'):
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip().strip('"\'')
    return env


def prompts(items_path):
    """Unique prompts: one per (item, condition) for D / R-tool / R-std and one per (item, writer) for R-nat."""
    seen, out = set(), []
    for line in open(items_path, encoding='utf-8'):
        r = json.loads(line)
        for cond in ('D', 'R_tool', 'R_std', 'R_nat'):
            v = r.get(cond)
            if not v:
                continue
            writer = r['writer'] if cond == 'R_nat' else ''
            key = f"{r['item_id']}|{cond}|{writer}"
            if key in seen:
                continue
            seen.add(key)
            text = (f"Passage: {v['passage']}\n\n" if v.get('passage') else '') + f"Question: {v['question']}\n" + \
                '\n'.join(f'{k}. {v["options"][k]}' for k in OPTIONS)
            out.append({'key': key, 'item_id': r['item_id'], 'source': r['source'], 'category': r['category'],
                        'condition': cond, 'writer': writer, 'answer': r['answer'],
                        'prompt': f'{INSTRUCTION}\n\n{text}\nAnswer:'})
    return out


def parse_letter(text):
    """The chosen option: a bare letter, an explicit 'answer: X', or else the last standalone A-D."""
    t = (text or '').strip()
    if re.fullmatch(r'\(?([ABCD])[).:]?', t):
        return re.sub(r'[^ABCD]', '', t)
    m = re.findall(r'answer\s*(?:is)?\s*[:\-]?\s*\(?([ABCD])\b', t, re.I)
    if m:
        return m[-1].upper()
    m = re.findall(r'(?<![A-Za-z])([ABCD])(?![A-Za-z])', t)
    return m[-1] if m else None


def ask(provider, model, extra, prompt, env):
    url, key_name, _ = PROVIDERS[provider]
    if provider == 'gemini':
        url = url.format(model=model) + '?key=' + env[key_name]
        cfg = {'temperature': 0, 'maxOutputTokens': 1024, **extra}
        body = {'contents': [{'parts': [{'text': prompt}]}], 'generationConfig': cfg}
        headers = {'Content-Type': 'application/json', 'User-Agent': UA}
    else:
        body = {'model': model, 'messages': [{'role': 'user', 'content': prompt}], 'temperature': 0,
                'max_tokens': 1024, **extra}
        headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + env[key_name], 'User-Agent': UA}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read())
    if provider == 'gemini':
        parts = d.get('candidates', [{}])[0].get('content', {}).get('parts', [])
        return ''.join(p.get('text', '') for p in parts if not p.get('thought'))
    return d['choices'][0]['message'].get('content') or ''


def run(name, todo, env):
    provider, model, extra = MODELS[name]
    gap = PROVIDERS[provider][2]
    out_path = RESULTS / f'{name}.jsonl'
    done = {json.loads(l)['key'] for l in open(out_path, encoding='utf-8')} if out_path.exists() else set()
    todo = [p for p in todo if p['key'] not in done]
    print(f'{name}: {len(done)} done, {len(todo)} to ask')
    last = 0.0
    with open(out_path, 'a', encoding='utf-8') as f:
        for i, p in enumerate(todo, 1):
            for attempt in range(6):
                time.sleep(max(0.0, gap - (time.time() - last)))
                last = time.time()
                try:
                    text = ask(provider, model, extra, p['prompt'], env)
                    if not text.strip() and attempt < 2:
                        continue  # the API occasionally returns an empty answer: ask again
                    break
                except urllib.error.HTTPError as e:
                    if e.code in (429, 500, 502, 503, 504) and attempt < 5:
                        wait = float(e.headers.get('retry-after') or 0) or min(120, 5 * 2 ** attempt)
                        print(f'  {e.code}, waiting {wait:.0f}s')
                        time.sleep(wait)
                        continue
                    if e.code == 429:
                        print('  daily quota reached; run again later to continue')
                        return
                    text = f'<HTTP {e.code}> {e.read()[:200].decode(errors="replace")}'
                    break
                except Exception as e:  # noqa: BLE001 - network hiccup: retry
                    if attempt < 5:
                        time.sleep(5 * 2 ** attempt)
                        continue
                    text = f'<error> {e}'
            pred = parse_letter(text)
            rec = {k: p[k] for k in ('key', 'item_id', 'source', 'category', 'condition', 'writer', 'answer')}
            rec.update({'model': name, 'model_id': model, 'output': text[:2000], 'pred': pred,
                        'correct': pred == p['answer'], 'time': time.strftime('%Y-%m-%dT%H:%M:%S')})
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            f.flush()
            if i % 20 == 0:
                print(f'  {i}/{len(todo)}')


def summary():
    rows = [json.loads(l) for p in sorted(RESULTS.glob('*.jsonl')) for l in open(p, encoding='utf-8')]
    if not rows:
        print('no results yet')
        return
    by = defaultdict(dict)  # (model, item, writer-or-'') -> condition -> correct
    for r in rows:
        by[(r['model'], r['item_id'])].setdefault(r['condition'], []).append(r['correct'])
    conds = ['D', 'R_tool', 'R_std', 'R_nat']
    print('Accuracy (%) on items answered in every listed condition; R-nat averaged over writers')
    print(f"{'model':<24}{'items':>6}" + ''.join(f'{c:>9}' for c in conds) + f"{'unparsed':>10}")
    for model in sorted({r['model'] for r in rows}):
        items = [v for (m, _), v in by.items() if m == model and all(c in v for c in ('D', 'R_tool', 'R_nat'))]
        acc = {c: [sum(v[c]) / len(v[c]) for v in items if c in v] for c in conds}
        unparsed = sum(r['pred'] is None for r in rows if r['model'] == model)
        print(f'{model:<24}{len(items):>6}' + ''.join(
            f'{100 * sum(a) / len(a):>9.1f}' if a else f'{"-":>9}' for a in acc.values()) + f'{unparsed:>10}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--models', nargs='*', default=[])
    ap.add_argument('--items', default=str(ROOT / 'data' / 'collected' / 'eval_items.jsonl'))
    ap.add_argument('--limit', type=int, default=0, help='only the first N prompts (for a quick check)')
    ap.add_argument('--summary', action='store_true')
    ap.add_argument('--export-prompts', help='write the prompts as JSONL (for scripts/kaggle_logprob_eval.py) and stop')
    args = ap.parse_args()
    if args.summary:
        return summary()
    if args.export_prompts:
        with open(args.export_prompts, 'w', encoding='utf-8') as f:
            for p in prompts(args.items):
                f.write(json.dumps(p, ensure_ascii=False) + '\n')
        return print(f'wrote {args.export_prompts}')
    RESULTS.mkdir(exist_ok=True)
    env = load_env()
    todo = prompts(args.items)
    if args.limit:
        todo = todo[:args.limit]
    for name in args.models:
        run(name, todo, env)
    summary()


if __name__ == '__main__':
    main()
