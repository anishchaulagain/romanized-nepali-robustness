# Runs on the Kaggle kernel (sent by scripts/kaggle_remote.py run-file): score models one after another.
import os
import subprocess
import sys

from kaggle_secrets import UserSecretsClient

os.environ['HF_HOME'] = '/tmp/hf'  # /kaggle/working is only ~19 GB; /tmp has plenty for model weights
os.environ['HF_TOKEN'] = UserSecretsClient().get_secret('HF_TOKEN')
os.environ['HF_HUB_ENABLE_HF_TRANSFER'] = '0'

MODELS = ['Qwen/Qwen3-8B', 'microsoft/Phi-4-mini-instruct', 'Qwen/Qwen2.5-7B-Instruct']  # no licence approval needed

for model in MODELS:
    print(f'=== {model}', flush=True)
    proc = subprocess.Popen([sys.executable, '/kaggle/working/kaggle_logprob_eval.py', '--model', model,
                             '--prompts', '/kaggle/working/prompts.jsonl', '--batch', '4'],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd='/kaggle/working')
    for line in proc.stdout:
        if 'it/s]' in line or 'Fetching' in line or 'Warning' in line:
            continue  # download progress bars and warnings
        print(line, end='', flush=True)
    print(f'exit code {proc.wait()}', flush=True)
