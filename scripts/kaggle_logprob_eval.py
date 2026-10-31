"""Score open-weight models on the benchmark from answer-letter probabilities (free Kaggle GPU, 2x T4).

For each prompt the model reads the question (with its chat template) and we take the probability it gives to the
next token being A, B, C or D. The most probable letter is its answer and its probability is its confidence, which
the calibration analysis needs; there is nothing to parse. Output rows match scripts/run_eval.py, plus 'probs'.

On Kaggle: new notebook -> Accelerator "GPU T4 x2" -> add data/collected/prompts.jsonl as a dataset ->
  !pip install -q -U transformers accelerate
  from kaggle_secrets import UserSecretsClient; import os
  os.environ['HF_TOKEN'] = UserSecretsClient().get_secret('HF_TOKEN')   # Llama and Gemma need their licence accepted
  !python kaggle_logprob_eval.py --model meta-llama/Llama-3.1-8B-Instruct --prompts /kaggle/input/<dataset>/prompts.jsonl
The output file is resumable: rerun the same command after a session ends and it continues.

Make prompts.jsonl with:  python scripts/run_eval.py --export-prompts data/collected/prompts.jsonl
"""
import argparse
import json
import os
import time
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

LETTERS = ['A', 'B', 'C', 'D']


def letter_ids(tok):
    """Token ids that spell each letter as the next token, with or without a leading space."""
    ids = {}
    for letter in LETTERS:
        cands = set()
        for text in (letter, ' ' + letter):
            t = tok.encode(text, add_special_tokens=False)
            if len(t) == 1:
                cands.add(t[0])
        ids[letter] = sorted(cands)
    return ids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', required=True)
    ap.add_argument('--prompts', required=True)
    ap.add_argument('--out', default=None)
    ap.add_argument('--batch', type=int, default=4)
    args = ap.parse_args()

    name = args.model.split('/')[-1]
    out = Path(args.out or f'/kaggle/working/{name}.jsonl')
    done = {}
    if out.exists():  # the newest answer per prompt; a prompt whose text changed (new fingerprint) is scored again
        for line in open(out, encoding='utf-8'):
            r = json.loads(line)
            done[r['key']] = r.get('phash')
    todo = [p for p in map(json.loads, open(args.prompts, encoding='utf-8')) if done.get(p['key'], '-') != p.get('phash')]
    print(f'{name}: {len(done)} done, {len(todo)} to score')

    tok = AutoTokenizer.from_pretrained(args.model, token=os.environ.get('HF_TOKEN'))
    tok.padding_side = 'left'
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    if torch.cuda.is_available():  # spread over all GPUs (Kaggle: 2x T4)
        model = AutoModelForCausalLM.from_pretrained(args.model, dtype=torch.float16, device_map='auto',
                                                     token=os.environ.get('HF_TOKEN'))
    else:  # local check with a small model
        model = AutoModelForCausalLM.from_pretrained(args.model, dtype=torch.float32,
                                                     token=os.environ.get('HF_TOKEN'))
    model.eval()
    ids = letter_ids(tok)

    def chat(p):
        # enable_thinking=False: Qwen3 would otherwise start with a reasoning block instead of the answer letter.
        # Templates that do not use the variable ignore it. The reply is started with "Answer:" for every model,
        # so the next token is the letter (some models otherwise begin with the word "Answer" first).
        return tok.apply_chat_template([{'role': 'user', 'content': p['prompt']}], tokenize=False,
                                       add_generation_prompt=True, enable_thinking=False) + 'Answer:'

    # Some models (Qwen3) write the letter in bold, "**D**": count "**" followed by a letter as that letter.
    bold = tok.encode(' **', add_special_tokens=False)
    bold = bold[0] if len(bold) == 1 else None

    def next_logp(texts):
        enc = tok(texts, return_tensors='pt', padding=True, add_special_tokens=False).to(model.device)
        with torch.no_grad():
            return torch.log_softmax(model(**enc).logits[:, -1, :].float(), dim=-1)

    def letter_scores(row):
        return torch.stack([torch.logsumexp(row[ids[l]], dim=0) for l in LETTERS])

    with open(out, 'a', encoding='utf-8') as f:
        for start in range(0, len(todo), args.batch):
            batch = todo[start:start + args.batch]
            logp = next_logp([chat(p) for p in batch])
            if bold is not None:
                after_bold = next_logp([chat(p) + ' **' for p in batch])
            for j, (p, row) in enumerate(zip(batch, logp)):
                scores = letter_scores(row)
                if bold is not None:  # P(letter) = P(" L") + P(" **") * P("L" | " **")
                    scores = torch.logaddexp(scores, row[bold] + letter_scores(after_bold[j]))
                probs = torch.softmax(scores, dim=0).tolist()  # renormalised over the four letters
                pred = LETTERS[max(range(4), key=lambda i: probs[i])]
                rec = {k: p.get(k) for k in ('key', 'item_id', 'source', 'category', 'condition', 'writer', 'answer',
                                             'phash')}
                rec.update({'model': name, 'model_id': args.model, 'output': '', 'pred': pred,
                            'correct': pred == p['answer'], 'probs': dict(zip(LETTERS, probs)),
                            'letter_mass': float(torch.exp(torch.logsumexp(scores, dim=0))),  # how much the model
                            'time': time.strftime('%Y-%m-%dT%H:%M:%S')})                      # wanted a letter at all
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
            f.flush()
            if (start // args.batch) % 25 == 0:
                print(f'  {start + len(batch)}/{len(todo)}')


if __name__ == '__main__':
    main()
