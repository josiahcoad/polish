#!/usr/bin/env python3
"""Time Polish against the installed config: model latency per message, plus the fixed local overhead.

Usage: python3 bench/benchmark.py [runs]   (default 10 runs per message)
"""
import os, statistics, subprocess, sys, time

sys.path.insert(0, os.path.expanduser("~/.config/polish"))
import polish

MESSAGES = {
    "slack": "@maya quick status :rocket:\n- <b>auth fix</b> merged, deploying tmrw am\n"
             "- eval suite still flaky, looking into it\nlmk if u need anything b4 the demo",
    "gmail": "hi sarah\n\nthx for call today. attached the sow, lmk if any q's. we can kick off mon if u sign by fri\n\nbest\njosiah",
    "imessage": "running late srry, traffic is crazy. be there in 15 save me a seat",
}

def main():
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    print(f"model {polish.MODEL}, {runs} runs per message\n")
    every = []
    for name, msg in MESSAGES.items():
        times = []
        for _ in range(runs):
            t = time.perf_counter(); polish.llm(msg); times.append(time.perf_counter() - t)
        every += times
        print(f"{name:9} median {statistics.median(times):.2f}s  p90 {sorted(times)[int(len(times) * .9) - 1]:.2f}s")
        print(f"          -> {polish.llm(msg)!r}")
    print(f"\nall       median {statistics.median(every):.2f}s  min {min(every):.2f}s  max {max(every):.2f}s")

    # Local overhead per run: python start-up + imports, then the clipboard reads/writes around the call.
    t = time.perf_counter()
    subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, {os.path.dirname(polish.__file__)!r}); import polish"])
    start = time.perf_counter() - t
    saved = polish.read_clipboard()
    t = time.perf_counter()
    polish.clip("mods"); polish.clip("count"); polish.read_clipboard(); polish.write_clipboard(saved); polish.write_clipboard(saved)
    clip = time.perf_counter() - t
    print(f"overhead  start-up {start:.2f}s + clipboard {clip:.2f}s")

if __name__ == "__main__":
    main()
