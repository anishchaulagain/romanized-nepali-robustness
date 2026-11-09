"""Figures for Paper 1 (print, one IEEE column wide), from the same answers as analyze_results.py.

  fig_accuracy.png  accuracy per model in Devanagari and as typed by writers (R-nat), sorted by Devanagari accuracy
  fig_writers.png   per model, % of pairs of two writers' versions of a question answered one right, one wrong

Usage: python scripts/make_figures.py [--out paper1/figures]
"""
import argparse
from itertools import combinations
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

from mixed_effects import frame  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BLUE, ORANGE = '#2a78d6', '#eb6834'          # validated categorical slots 1-2 (dataviz reference palette)
INK, MUTED, GRID = '#0b0b0b', '#52514e', '#e4e3df'
NAMES = {'gpt-6-luna': 'GPT-6 Luna', 'gemini-3.1-flash-lite': 'Gemini 3.1 Flash-Lite',
         'gemma-4-26b-a4b': 'Gemma 4 26B-A4B', 'nemotron-3-ultra': 'Nemotron 3 Ultra', 'qwen3.8-27b': 'Qwen3.8-27B',
         'Qwen3-8B': 'Qwen3-8B', 'gpt-oss-20b': 'gpt-oss-20b', 'ministral-8b': 'Ministral 8B',
         'Phi-4-mini-instruct': 'Phi-4-mini', 'Qwen2.5-7B-Instruct': 'Qwen2.5-7B'}

plt.rcParams.update({'font.family': 'serif', 'font.serif': ['Times New Roman', 'DejaVu Serif'], 'font.size': 7.5,
                     'axes.edgecolor': MUTED, 'axes.labelcolor': INK, 'xtick.color': MUTED, 'ytick.color': INK,
                     'axes.spines.top': False, 'axes.spines.right': False})


def accuracy_figure(df, out):
    acc = 100 * df.groupby(['model', 'condition']).correct.mean().unstack()
    acc = acc.sort_values('D')
    # the gap label is the paired difference over writer versions, as in the paper's table
    d_item = df[df.condition == 'D'].set_index(['model', 'item']).correct
    nat = df[df.condition == 'R_nat']
    gap = {m: 100 * (g.correct.values - d_item.loc[[(m, i) for i in g.item]].values).mean()
           for m, g in nat.groupby('model')}
    y = range(len(acc))
    fig, ax = plt.subplots(figsize=(3.4, 2.5), dpi=300)
    ax.axvline(25, color=MUTED, lw=0.8, ls=(0, (3, 3)), zorder=0)
    ax.text(25.8, len(acc) - 0.45, 'chance', color=MUTED, fontsize=6.5, va='top')
    for i, (_, r) in zip(y, acc.iterrows()):
        ax.plot([r.R_nat, r.D], [i, i], color='#c3c2b7', lw=2, solid_capstyle='round', zorder=1)
    ax.scatter(acc.D, y, s=22, color=BLUE, edgecolor='white', linewidth=0.8, zorder=3, label='Devanagari (D)')
    ax.scatter(acc.R_nat, y, s=22, color=ORANGE, edgecolor='white', linewidth=0.8, zorder=3,
               label='Typed by writers (R-nat)')
    for i, (_, r) in zip(y, acc.iterrows()):
        ax.text(r.D + 1.8, i, f'{gap[r.name]:+.1f}'.replace('-', '−'), va='center', fontsize=6.5, color=MUTED)
    ax.set_yticks(list(y), [NAMES.get(m, m) for m in acc.index])
    ax.set_xlim(20, 90)
    ax.set_xlabel('Accuracy (%)')
    ax.grid(axis='x', color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    ax.legend(loc='lower center', bbox_to_anchor=(0.42, 1.0), ncol=2, frameon=False, fontsize=6.8,
              handletextpad=0.2, columnspacing=1.0)
    fig.tight_layout(pad=0.3)
    fig.savefig(out / 'fig_accuracy.png')
    plt.close(fig)
    return acc.index.tolist()


def writer_figure(df, order, out):
    n = df[df.condition == 'R_nat']
    split = {}
    for m, g in n.groupby('model'):
        piv = g.pivot_table(index='item', columns='writer', values='correct')
        pairs = [(piv[a] != piv[b])[piv[a].notna() & piv[b].notna()] for a, b in combinations(piv.columns, 2)]
        k = sum(int(p.sum()) for p in pairs)
        split[m] = 100 * k / sum(len(p) for p in pairs)
    vals = [split[m] for m in order]
    fig, ax = plt.subplots(figsize=(3.4, 2.2), dpi=300)
    ax.barh(range(len(order)), vals, height=0.62, color=BLUE, edgecolor='white', linewidth=0.8)
    for i, v in enumerate(vals):
        ax.text(v + 0.6, i, f'{v:.0f}%', va='center', fontsize=6.5, color=MUTED)
    ax.set_yticks(range(len(order)), [NAMES.get(m, m) for m in order])
    ax.set_xlim(0, 33)
    ax.set_xlabel('Writer pairs answered one right, one wrong (%)')
    ax.grid(axis='x', color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    fig.tight_layout(pad=0.3)
    fig.savefig(out / 'fig_writers.png')
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=str(ROOT / 'paper1' / 'figures'))
    out = Path(ap.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    df = frame()
    order = accuracy_figure(df, out)
    writer_figure(df, order, out)
    print('wrote', out / 'fig_accuracy.png', out / 'fig_writers.png')


if __name__ == '__main__':
    main()
