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
import hashlib
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
    # Paid (OpenAI): about $0.10 / $0.50 per million tokens, a few cents for a full run. Low reasoning effort.
    'gpt-6-luna': ('openai', 'gpt-6-luna', {'reasoning_effort': 'low'}),
    # Reasoning model (550B MoE), on NVIDIA's free API (build.nvidia.com key); low reasoning effort as for gpt-oss.
    # Its first answers came from the same model on OpenRouter's free tier (see model_id in the results).
    'nemotron-3-ultra': ('nvidia', 'nvidia/nemotron-3-ultra-550b-a55b',
                         {'max_tokens': 4096, 'reasoning_effort': 'low'}),
}
PROVIDERS = {  # endpoint, key name, seconds between calls (free tier)
    'mistral': ('https://api.mistral.ai/v1/chat/completions', 'MISTRAL_API_KEY', 1.2),
    'groq': ('https://api.groq.com/openai/v1/chat/completions', 'GROQ_API_KEY', 3.0),
    'gemini': ('https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent', 'GEMINI_API_KEY', 6.0),
    'openrouter': ('https://openrouter.ai/api/v1/chat/completions', 'OPENROUTER_API_KEY', 3.2),  # free: 20/min
    'nvidia': ('https://integrate.api.nvidia.com/v1/chat/completions', 'NVIDIA_API_KEY', 1.6),   # free: ~40/min
    'openai': ('https://api.openai.com/v1/chat/completions', 'OPENAI_API_KEY', 0.3),           # paid
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
    if 'NVDIA_API_KEY' in env:  # accept the key under this spelling too
        env.setdefault('NVIDIA_API_KEY', env['NVDIA_API_KEY'])
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
            out[-1]['phash'] = phash(out[-1]['prompt'])
    return out


def phash(prompt):
    """Fingerprint of the exact prompt text: a prompt is asked again if its text changes (e.g. a writer edits)."""
    return hashlib.sha1(prompt.encode('utf-8')).hexdigest()[:12]


def latest(path):
    """key -> the newest answer in a results file (a re-asked prompt appends a newer answer)."""
    out = {}
    if path.exists():
        for line in open(path, encoding='utf-8'):
            r = json.loads(line)
            out[r['key']] = r
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
    elif provider == 'openai':  # reasoning models: no temperature, output limit via max_completion_tokens
        body = {'model': model, 'messages': [{'role': 'user', 'content': prompt}], 'max_completion_tokens': 4096,
                **extra}
        headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + env[key_name], 'User-Agent': UA}
    else:
        body = {'model': model, 'messages': [{'role': 'user', 'content': prompt}], 'temperature': 0,
                'max_tokens': 1024, **extra}
        headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + env[key_name], 'User-Agent': UA}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read())
    if provider == 'gemini':
        cand = d.get('candidates', [{}])[0]
        parts = cand.get('content', {}).get('parts', [])
        u = d.get('usageMetadata', {})
        usage = {'input': u.get('promptTokenCount'), 'output': (u.get('candidatesTokenCount') or 0) + (u.get('thoughtsTokenCount') or 0)}
        return ''.join(p.get('text', '') for p in parts if not p.get('thought')), cand.get('finishReason', ''), usage
    choice = d['choices'][0]
    u = d.get('usage') or {}
    usage = {'input': u.get('prompt_tokens'), 'output': u.get('completion_tokens')}
    return choice['message'].get('content') or '', choice.get('finish_reason', ''), usage


def run(name, todo, env):
    provider, model, extra = MODELS[name]
    gap = PROVIDERS[provider][2]
    out_path = RESULTS / f'{name}.jsonl'
    done = latest(out_path)
    changed = sum(1 for p in todo if p['key'] in done and done[p['key']].get('phash') != p['phash'])
    todo = [p for p in todo if done.get(p['key'], {}).get('phash') != p['phash']]
    print(f'{name}: {len(done)} done, {len(todo)} to ask ({changed} of them because the text changed)')
    last = 0.0
    with open(out_path, 'a', encoding='utf-8') as f:
        for i, p in enumerate(todo, 1):
            finish, usage = '', {}
            for attempt in range(6):
                time.sleep(max(0.0, gap - (time.time() - last)))
                last = time.time()
                try:
                    text, finish, usage = ask(provider, model, extra, p['prompt'], env)
                    # An empty reply is asked again, unless the model used up its output limit (for example
                    # reasoning in a loop): that is its real behaviour and is scored as no answer.
                    if not text.strip() and attempt < 2 and str(finish).upper() not in ('MAX_TOKENS', 'LENGTH'):
                        continue
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
                    text, finish = f'<HTTP {e.code}> {e.read()[:200].decode(errors="replace")}', 'error'
                    break
                except Exception as e:  # noqa: BLE001 - network hiccup: retry
                    if attempt < 5:
                        time.sleep(5 * 2 ** attempt)
                        continue
                    text, finish = f'<error> {e}', 'error'
            pred = parse_letter(text)
            rec = {k: p[k] for k in ('key', 'item_id', 'source', 'category', 'condition', 'writer', 'answer', 'phash')}
            rec.update({'model': name, 'model_id': model, 'output': text[:2000], 'pred': pred, 'finish': finish, 'usage': usage,
                        'correct': pred == p['answer'], 'time': time.strftime('%Y-%m-%dT%H:%M:%S')})
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            f.flush()
            if i % 20 == 0:
                print(f'  {i}/{len(todo)}')


def summary():
    rows = [r for p in sorted(RESULTS.glob('*.jsonl')) for r in latest(p).values()]
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
