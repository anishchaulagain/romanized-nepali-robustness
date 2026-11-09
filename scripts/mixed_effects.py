"""Mixed-effects models for the paper's main claims (uses the same answers as analyze_results.py).

A. Does the script cost accuracy once question difficulty and model are accounted for?
   correct ~ condition + model + (1 | question)            Bayesian logistic mixed model (variational fit)
   and, as a frequentist check, a conditional logistic regression within each (question, model) pair.
B. In human typing (R-nat), is the variation about the writer (some people's typing is harder) or about the
   particular typed version of a question?
   correct ~ model + (1 | question) + (1 | writer) + (1 | question:writer)
   Writer SD near zero with a clearly larger question:writer SD means: no writer is harder overall, but each
   person's typing of a given question can help or hurt.

Usage: python scripts/mixed_effects.py
"""
import math
from itertools import combinations

import numpy as np
import pandas as pd
from statsmodels.discrete.conditional_models import ConditionalLogit
from statsmodels.genmod.bayes_mixed_glm import BinomialBayesMixedGLM

from analyze_results import load

CONDS = ['D', 'R_tool', 'R_std', 'R_nat']


def frame():
    rows, _ = load({'W1', 'W2'}, {'gemini-3.5-flash'})
    df = pd.DataFrame([{'model': r['model'], 'item': r['item_id'], 'condition': r['condition'],
                        'writer': r.get('writer') or '-', 'correct': int(bool(r['correct']))} for r in rows])
    return df[df.condition.isin(CONDS)]


def model_a(df):
    print('A. Effect of the script (odds ratio vs Devanagari; < 1 means lower odds of a correct answer)')
    d = df.assign(condition=pd.Categorical(df.condition, CONDS))
    glmm = BinomialBayesMixedGLM.from_formula('correct ~ C(condition) + C(model)', {'question': '0 + C(item)'}, d)
    fit = glmm.fit_vb()
    names = glmm.exog_names
    print('   Mixed model, random intercept per question (posterior mean, 95% interval):')
    for i, n in enumerate(names):
        if n.startswith('C(condition)'):
            m, s = fit.fe_mean[i], fit.fe_sd[i]
            print(f'     {n.split("T.")[1].rstrip("]"):<8} OR {math.exp(m):.2f} [{math.exp(m - 1.96 * s):.2f}-'
                  f'{math.exp(m + 1.96 * s):.2f}]')
    print(f'     question SD (logit) {math.exp(fit.vcp_mean[0]):.2f}: questions differ a lot in difficulty')

    # Conditional logit: compares conditions only within the same question and model.
    x = pd.get_dummies(d.condition, drop_first=True).astype(float)
    groups = (d.item + '|' + d.model).factorize()[0]
    cl = ConditionalLogit(d.correct.values, x.values, groups=groups).fit(disp=0)
    print('   Conditional logistic regression within (question, model):')
    for n, b, se, p in zip(x.columns, cl.params, cl.bse, cl.pvalues):
        print(f'     {n:<8} OR {math.exp(b):.2f} [{math.exp(b - 1.96 * se):.2f}-{math.exp(b + 1.96 * se):.2f}]'
              f'  p = {p:.1e}')
    # R-nat vs R-tool directly
    sub = d[d.condition.isin(['R_tool', 'R_nat'])]
    x2 = (sub.condition == 'R_nat').astype(float).values[:, None]
    g2 = (sub.item + '|' + sub.model).factorize()[0]
    c2 = ConditionalLogit(sub.correct.values, x2, groups=g2).fit(disp=0)
    b, se, p = c2.params[0], c2.bse[0], c2.pvalues[0]
    print(f'     R_nat vs R_tool OR {math.exp(b):.2f} [{math.exp(b - 1.96 * se):.2f}-{math.exp(b + 1.96 * se):.2f}]'
          f'  p = {p:.2f}\n')


def model_b(df):
    print('B. Human typing (R-nat): where does the variation come from? (SD on the logit scale, 95% interval)')
    d = df[df.condition == 'R_nat'].copy()
    d['version'] = d.item + '|' + d.writer
    vc = {'question': '0 + C(item)', 'writer': '0 + C(writer)', 'typed version': '0 + C(version)'}
    glmm = BinomialBayesMixedGLM.from_formula('correct ~ C(model)', vc, d)
    fit = glmm.fit_vb()
    for name, m, s in zip(glmm.vcp_names, fit.vcp_mean, fit.vcp_sd):
        print(f'     {name:<14} SD {math.exp(m):.2f} [{math.exp(m - 1.96 * s):.2f}-{math.exp(m + 1.96 * s):.2f}]')
    print(f'   {d.item.nunique()} questions, {d.writer.nunique()} writers, {d.version.nunique()} typed versions, '
          f'{d.model.nunique()} models, {len(d)} answers')
    print('   For scale: a logit SD of 0.5 moves a 50% question to roughly 38-62% for one SD either way.')
    print('   (A variational fit can shrink small variance components towards zero: see the check below.)\n')


def shared_difficulty(df, reps=2000):
    """Is a typed version that is hard for one model hard for the others too? For each pair of writers on the same
    question, count models right on A but wrong on B, and the reverse. If versions had no shared difficulty, which
    version a model gets right would be a coin flip per model; compare with random sign flips."""
    print('C. Do models agree on which writer\'s version is harder? (permutation test)')
    n = df[df.condition == 'R_nat']
    rng = np.random.default_rng(0)
    pairs = []
    for _, g in n.groupby('item'):
        piv = g.pivot_table(index='model', columns='writer', values='correct')
        for a, b in combinations(piv.columns, 2):
            d = (piv[a] - piv[b]).dropna().values
            if len(d) >= 8:
                pairs.append(d[d != 0])  # models that split on this pair: +1 right on A only, -1 right on B only

    def stats(ps):
        lean = np.mean([abs(d.sum()) for d in ps])
        many = [d for d in ps if len(d) >= 3]
        agree = np.mean([max((d > 0).sum(), (d < 0).sum()) / len(d) for d in many])
        return lean, agree

    obs = stats(pairs)
    null = np.array([stats([d * rng.choice([-1, 1], len(d)) for d in pairs]) for _ in range(reps)])
    many = sum(len(d) >= 3 for d in pairs)
    print(f'   {len(pairs)} writer pairs; {many} where 3 or more models split')
    print(f'   models agreeing on the harder version (pairs with 3+ splits): {100 * obs[1]:.0f}% '
          f'(chance {100 * null[:, 1].mean():.0f}%, p = {np.mean(null[:, 1] >= obs[1]):.4f})')
    print(f'   mean lean towards one version: {obs[0]:.2f} models (chance {null[:, 0].mean():.2f}, '
          f'p = {np.mean(null[:, 0] >= obs[0]):.4f})\n')


def main():
    df = frame()
    print(f'{len(df)} answers, {df.model.nunique()} models, {df.item.nunique()} questions\n')
    model_a(df)
    model_b(df)
    shared_difficulty(df)


if __name__ == '__main__':
    np.random.seed(0)
    main()
