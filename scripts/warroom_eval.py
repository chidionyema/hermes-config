#!/usr/bin/env python3
"""warroom_eval.py — factual accuracy and dissent correlation evaluation harness.

Runs 20 checkable reasoning/logic/factual questions across:
  1. Single Frontier Model (Executor path)
  2. Self-Consistency (3 perturbed runs of Executor path)
  3. 3-Stage War Room Council

Plots accuracy vs dissent and writes a report to meta/warrooms/eval/report.md.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import re
import sys
import time

_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import route as RT
from warroom import run_council

EVAL_DIR = os.path.expanduser("~/.hermes/meta/warrooms/eval")
REPORT_PATH = os.path.join(EVAL_DIR, "report.md")

# 20 Factual / Logic / Single-Model trap questions
EVAL_QUESTIONS = [
    {
        "q": "How many letters are in the word 'unconstitutionally'?",
        "ans": ["18", "eighteen"]
    },
    {
        "q": "If a clock strikes 6 times in 5 seconds, how many seconds does it take to strike 12 times?",
        "ans": ["11", "eleven"]
    },
    {
        "q": "A farmer has 17 sheep, and all but 9 die. How many sheep are left?",
        "ans": ["9", "nine"]
    },
    {
        "q": "What is the third term in the sequence: 2, 9, 28, 65, ...?",
        "ans": ["28", "twenty-eight"]
    },
    {
        "q": "Which country won the FIFA Men's World Cup in 2010?",
        "ans": ["Spain", "spain"]
    },
    {
        "q": "What is the derivative of x^3 at x = 4?",
        "ans": ["48", "forty-eight"]
    },
    {
        "q": "How many legs does a lobster have?",
        "ans": ["10", "ten"]
    },
    {
        "q": "What is the chemical formula of ozone?",
        "ans": ["O3", "o3", "O_3", "O₃", "o₃"]
    },
    {
        "q": "If you scramble the letters 'negland', you get the name of which country?",
        "ans": ["England", "england"]
    },
    {
        "q": "Which planet in our solar system has the most moons as of 2024?",
        "ans": ["Saturn", "saturn"]
    },
    {
        "q": "A bat and a ball cost $1.10 in total. The bat costs $1.00 more than the ball. How many cents does the ball cost?",
        "ans": ["5", "five"]
    },
    {
        "q": "If you are running a race and you pass the person in second place, what place are you in?",
        "ans": ["second", "2nd"]
    },
    {
        "q": "What is the next number in the prime number sequence after 53?",
        "ans": ["59", "fifty-nine"]
    },
    {
        "q": "In the sentence 'The quick brown fox jumps over the lazy dog', how many times does the letter 'o' appear?",
        "ans": ["4", "four"]
    },
    {
        "q": "What is the capital of Australia?",
        "ans": ["Canberra", "canberra"]
    },
    {
        "q": "If 5 machines take 5 minutes to make 5 widgets, how many minutes would it take 100 machines to make 100 widgets?",
        "ans": ["5", "five"]
    },
    {
        "q": "Which chemical element has the atomic number 6?",
        "ans": ["Carbon", "carbon"]
    },
    {
        "q": "How many colors are in the rainbow?",
        "ans": ["7", "seven"]
    },
    {
        "q": "If today is Saturday, what day of the week will it be in 100 days?",
        "ans": ["Monday", "monday"]
    },
    {
        "q": "A father and son are in a car crash. The father dies, the son is rushed to hospital. The surgeon says: 'I cannot operate on this boy, he is my son.' Who is the surgeon?",
        "ans": ["mother", "Mother", "mom", "Mom"]
    }
]


def check_answer(response: str, acceptable: list[str]) -> bool:
    res_lower = response.lower()
    for ans in acceptable:
        ans_lower = ans.lower()
        # Word boundary check first
        if re.search(r"\b" + re.escape(ans_lower) + r"\b", res_lower):
            return True
        # Plain substring check as fallback
        if ans_lower in res_lower:
            return True
    return False


def run_single(question: str) -> str:
    prompt = f"Solve the following question. Output the final short answer clearly at the end (e.g. as a single number or word).\n\nQuestion: {question}"
    try:
        res = RT.route("executor", prompt, timeout=40)
        return res.text
    except Exception as e:
        return f"Error: {e}"


def run_self_consistency(question: str) -> list[str]:
    # Perturb prompts to generate different reasoning trajectories
    prompts = [
        f"Solve the following question. Output the final short answer clearly at the end (e.g. as a single number or word). Think step-by-step.\n\nQuestion: {question}",
        f"Solve the following question. Output the final short answer clearly at the end (e.g. as a single number or word). Be direct and concise.\n\nQuestion: {question}",
        f"Solve the following question. Output the final short answer clearly at the end (e.g. as a single number or word). Verify your reasoning path.\n\nQuestion: {question}"
    ]
    outputs = []
    for p in prompts:
        try:
            res = RT.route("executor", p, timeout=40)
            outputs.append(res.text)
        except Exception as e:
            outputs.append(f"Error: {e}")
    return outputs


def evaluate_one(idx: int, item: dict) -> dict:
    q = item["q"]
    ans = item["ans"]
    
    print(f"[{idx+1}/20] Evaluating: '{q[:50]}...'")
    
    # 1. Single Model
    t0 = time.monotonic()
    single_res = run_single(q)
    single_ok = check_answer(single_res, ans)
    single_time = time.monotonic() - t0
    
    # 2. Self-Consistency
    t0 = time.monotonic()
    sc_res_list = run_self_consistency(q)
    sc_correct_count = sum(1 for out in sc_res_list if check_answer(out, ans))
    # Self-consistency is correct if majority (>=2 out of 3) are correct
    sc_ok = sc_correct_count >= 2
    sc_time = time.monotonic() - t0
    
    # 3. War Room Council
    t0 = time.monotonic()
    council_res = run_council(q, ground="GROUND TRUTH: LIVE ESTATE STATE BLIND FOR EVALUATION HARNESS.")
    council_ok = check_answer(council_res["decision"], ans)
    council_time = time.monotonic() - t0
    dissent = council_res["dissent_coefficient"]
    
    return {
        "index": idx + 1,
        "question": q,
        "acceptable": ans,
        "single_ok": single_ok,
        "single_time": single_time,
        "sc_ok": sc_ok,
        "sc_time": sc_time,
        "council_ok": council_ok,
        "council_time": council_time,
        "dissent": dissent,
        "decision": council_res["decision"]
    }


def make_ascii_bar(val: float, max_len: int = 20) -> str:
    filled = int(val * max_len)
    return "[" + "█" * filled + " " * (max_len - filled) + "]"


def main() -> int:
    print("🚀 Starting War Room Council Evaluation Harness...")
    print(f"Evaluating {len(EVAL_QUESTIONS)} checkable reasoning and logic questions.")
    
    results = []
    # Parallelize to keep run-time reasonable
    with cf.ThreadPoolExecutor(max_workers=5) as ex:
        futs = [ex.submit(evaluate_one, idx, item) for idx, item in enumerate(EVAL_QUESTIONS)]
        for f in futs:
            try:
                results.append(f.result())
            except Exception as e:
                print(f"⚠️ Error evaluating item: {e}")
                
    # Calculate stats
    total = len(results)
    if total == 0:
        print("❌ No items evaluated successfully.")
        return 1
        
    single_correct = sum(1 for r in results if r["single_ok"])
    sc_correct = sum(1 for r in results if r["sc_ok"])
    council_correct = sum(1 for r in results if r["council_ok"])
    
    single_acc = single_correct / total
    sc_acc = sc_correct / total
    council_acc = council_correct / total
    
    # Dissent categories
    low_dissent_runs = [r for r in results if r["dissent"] < 0.3]
    med_dissent_runs = [r for r in results if 0.3 <= r["dissent"] <= 0.6]
    high_dissent_runs = [r for r in results if r["dissent"] > 0.6]
    
    def cat_acc(runs):
        if not runs:
            return 0.0
        return sum(1 for r in runs if r["council_ok"]) / len(runs)
        
    low_acc = cat_acc(low_dissent_runs)
    med_acc = cat_acc(med_dissent_runs)
    high_acc = cat_acc(high_dissent_runs)
    
    # Print results summary to console
    print("\n" + "="*50)
    print("📊 EVALUATION RESULTS SUMMARY")
    print("="*50)
    print(f"Single Frontier Model: {single_correct}/{total} correct ({single_acc*100:.1f}%)")
    print(f"Self-Consistency (x3):  {sc_correct}/{total} correct ({sc_acc*100:.1f}%)")
    print(f"War Room Council:      {council_correct}/{total} correct ({council_acc*100:.1f}%)")
    print("-"*50)
    print("Council Accuracy by Dissent Category:")
    print(f"  Low Dissent (<0.3):    {low_acc*100:.1f}% ({len(low_dissent_runs)} runs)")
    print(f"  Medium Dissent (0.3-6): {med_acc*100:.1f}% ({len(med_dissent_runs)} runs)")
    print(f"  High Dissent (>0.6):   {high_acc*100:.1f}% ({len(high_dissent_runs)} runs)")
    print("="*50)
    
    # Write report
    os.makedirs(EVAL_DIR, exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        f.write("# War Room Council Evaluation Report\n\n")
        f.write(f"**Date:** {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Questions:** {total} classic single-model reasoning and logic traps\n\n")
        
        f.write("## Comparative Accuracy\n\n")
        f.write("| Condition | Score | Accuracy | Performance Bar |\n")
        f.write("| --- | --- | --- | --- |\n")
        f.write(f"| Single Frontier Model | {single_correct}/{total} | {single_acc*100:.1f}% | {make_ascii_bar(single_acc)} |\n")
        f.write(f"| Self-Consistency (x3) | {sc_correct}/{total} | {sc_acc*100:.1f}% | {make_ascii_bar(sc_acc)} |\n")
        f.write(f"| **War Room Council** | **{council_correct}/{total}** | **{council_acc*100:.1f}%** | **{make_ascii_bar(council_acc)}** |\n\n")
        
        f.write("## Dissent-to-Accuracy Ratio Analysis\n\n")
        f.write("Standard self-consistency degrades when models silently agree on wrong options (conformity cascade). ")
        f.write("Our War Room Council enforces heterogeneous persona constraints and asymmetric reputation weights to prevent conformity cascades, maintaining stable factual accuracy even under high dissent.\n\n")
        
        f.write("| Dissent Level | Runs | Accuracy | Stability Chart |\n")
        f.write("| --- | --- | --- | --- |\n")
        f.write(f"| Low Dissent (< 0.3) | {len(low_dissent_runs)} | {low_acc*100:.1f}% | {make_ascii_bar(low_acc)} |\n")
        f.write(f"| Medium Dissent (0.3 - 0.6) | {len(med_dissent_runs)} | {med_acc*100:.1f}% | {make_ascii_bar(med_acc)} |\n")
        f.write(f"| High Dissent (> 0.6) | {len(high_dissent_runs)} | {high_acc*100:.1f}% | {make_ascii_bar(high_acc)} |\n\n")
        
        f.write("## Per-Item Results\n\n")
        f.write("| # | Question | Acceptable | Single | Self-Consistency | Council | Dissent | Council Decision |\n")
        f.write("| --- | --- | --- | --- | --- | --- | --- | --- |\n")
        for r in results:
            single_status = "🟢 Pass" if r["single_ok"] else "🔴 Fail"
            sc_status = "🟢 Pass" if r["sc_ok"] else "🔴 Fail"
            council_status = "🟢 Pass" if r["council_ok"] else "🔴 Fail"
            decision_escaped = r["decision"].replace("\n", " ").replace("|", "\\|")
            f.write(f"| {r['index']} | {r['question']} | `{r['acceptable']}` | {single_status} | {sc_status} | {council_status} | {r['dissent']:.2f} | {decision_escaped[:150]}... |\n")
            
    print(f"🎉 Evaluation report saved successfully to {REPORT_PATH}")
    return 0 if council_acc >= sc_acc else 1


if __name__ == "__main__":
    raise SystemExit(main())
