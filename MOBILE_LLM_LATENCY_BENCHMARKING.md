# Mobile LLM Latency Benchmarking Guide

A comprehensive guide for testing local LLM latency on mobile devices, inspired by Google AI Edge Gallery methodology.

---

## 1. Core Latency Metrics

These are the primary metrics measured by Google AI Edge Gallery and standard LLM benchmarks:

### 1.1 Time to First Token (TTFT)
- **Definition:** Time elapsed from sending a request to receiving the first generated token
- **Why it matters:** This is the most impactful metric for perceived speed. Users feel this as "response start time"
- **Target thresholds:**
  - < 100ms — Feels instantaneous (autocomplete use cases)
  - < 500ms — Ideal for chat/conversational UI
  - < 1s — Acceptable for chat, flow stays uninterrupted
  - > 10s — Users abandon the interaction

### 1.2 Prefill Speed / Prefill Throughput
- **Definition:** Rate at which input tokens are processed before generation begins (input tokens/sec)
- **Why it matters:** Determines how quickly the model can "read" and understand your prompt
- **Context:** Prefill is compute-bound — scales with input sequence length

### 1.3 Decode Speed / Output Throughput
- **Definition:** Rate at which output tokens are generated after the first token (output tokens/sec)
- **Why it matters:** Determines how fast the response streams to the user
- **Context:** Decode is memory-bandwidth-bound — each token requires reading all model weights

### 1.4 Inter-Token Latency (ITL)
- **Definition:** Time gap between consecutive generated tokens
- **Target:** < 50ms for smooth "typing" experience (> 20 tokens/sec)

### 1.5 End-to-End (E2E) Latency
- **Definition:** Total wall-clock time from request to final token
- **Formula:** `E2E = TTFT + (output_tokens × TPOT)`
- **When it matters most:** Non-streaming use cases (function calls, RAG pipelines)

### 1.6 Time Per Output Token (TPOT)
- **Definition:** Average time per output token = total decode time / output tokens
- **Relation:** Similar to ITL but averaged over the full response

---

## 2. Hardware & Device Profiling Metrics

These metrics help understand what the device hardware is doing during inference:

| Metric | Description |
|---|---|
| **CPU Usage %** | Utilization of big vs. efficiency cores (big.LITTLE architecture) |
| **GPU Usage %** | Mobile GPU utilization (typically only 5-20% is used) |
| **NPU Usage** | Neural Processing Unit utilization (if available; NPUs show 50x+ prefill speedup) |
| **Memory (RAM) Usage** | Peak and sustained memory consumption |
| **Thermal Throttling** | CPU/GPU clock reduction due to heat |
| **Power Consumption** | Battery drain rate during inference |

---

## 3. Test Workload Design

### 3.1 Input Prompt Categories

| Category | Input Tokens | Example |
|---|---|---|
| Short query | 10-50 tokens | "What is 2+2?" |
| Medium prompt | 100-500 tokens | Summarize a paragraph, simple QA |
| Long prompt | 1,000-4,000 tokens | Document analysis, RAG context |
| Very long prompt | 4,000-8,000 tokens | Long context tasks (if supported) |

### 3.2 Output Length Categories

| Category | Output Tokens | Use Case |
|---|---|---|
| Short answer | 10-50 tokens | Single sentence, classification |
| Medium answer | 100-300 tokens | Paragraph, brief explanation |
| Long answer | 500-1,000 tokens | Detailed response, code generation |
| Very long answer | 1,000+ tokens | Essay, full code file |

### 3.3 Task Types to Benchmark

- **Text Generation** — Free-form creative/descriptive output
- **Question Answering** — Factual short-answer responses
- **Summarization** — Long input → compressed output
- **Code Generation** — Structured, token-dense output
- **Translation** — Language-to-language conversion
- **Multi-turn Chat** — Simulated conversation (tests KV cache behavior)

---

## 4. Test Execution Methodology

### 4.1 Pre-Test Setup

1. **Device state:**
   - Fully charge battery (or plug in charger — but note this affects thermal behavior)
   - Close all background apps
   - Enable airplane mode (eliminates network interference)
   - Record device info: OS version, RAM, CPU model, GPU model, NPU availability

2. **Model state:**
   - Record model name, parameter count, quantization level (FP16/INT8/INT4)
   - Record inference runtime (llama.cpp, ExecuTorch, MLC-LLM, MediaPipe, etc.)
   - Record context window size configured

3. **Environmental:**
   - Record ambient temperature (affects thermal throttling)
   - Note if device was cold-started or already warm

### 4.2 Three-Run Testing Protocol

Each test configuration is executed in **3 separate runs** to capture different performance states:

| Run | Name | Purpose | What to Record |
|---|---|---|---|
| **Run 1** | Cold Start | Model freshly loaded; no KV cache, no OS page cache | TTFT (worst case), initial decode speed, load time |
| **Run 2** | Warm / Cached | Model loaded; OS page cache populated, KV cache warm | TTFT (best case), steady decode speed |
| **Run 3** | Thermal / Sustained | After sustained load; captures thermal throttling effects | TTFT under load, decode degradation, CPU/GPU throttling |

**Execution flow:**

```
[Restart App / Clear Cache]
        │
        ▼
   ┌─────────┐
   │  RUN 1  │  Cold Start — record TTFT, decode, memory
   └────┬────┘
        │  Wait 60s (thermal recovery)
        ▼
   ┌─────────┐
   │  RUN 2  │  Warm / Cached — record TTFT, decode
   └────┬────┘
        │  Immediately chain 10 rapid requests
        ▼
   ┌─────────┐
   │  RUN 3  │  Thermal — record TTFT, decode, CPU throttle %
   └─────────┘
```

### 4.3 Test Execution Rules

- Run **minimum 3 runs** per prompt/configuration (cold → warm → thermal)
- Wait **60 seconds between Run 1 and Run 2** to allow thermal recovery
- **Chain 10 rapid requests** before Run 3 to induce thermal load
- Record **minimum, maximum, average, median, P95** for all metrics
- Run tests in **randomized prompt order** within each run to avoid ordering bias

### 4.4 Cold vs Warm vs Thermal

| Scenario | Description | Expected Behavior |
|---|---|---|
| **Cold Start** | Model freshly loaded into memory; no cache | Highest TTFT, slowest decode |
| **Warm / Cached** | Model loaded; OS page cache + KV cache populated | Lowest TTFT, fastest decode |
| **Thermal** | Sustained load causing CPU/GPU throttling | TTFT may increase 30-50%, decode slows |

---

## 5. Benchmarking Tools & Approaches

### 5.1 On-Device Timing (Custom)

```python
import time

def benchmark_inference(model, prompt, num_runs=3):
    """3-run protocol: Cold → Warm → Thermal"""
    results = []

    for run_num in range(num_runs):
        run_label = ["cold", "warm", "thermal"][run_num]
        run_results = []

        for _ in range(5):  # 5 iterations within each run
            start = time.perf_counter()
            tokens = []
            first_token_time = None

            for token in model.generate(prompt):
                if first_token_time is None:
                    first_token_time = time.perf_counter() - start
                tokens.append(token)

            end = time.perf_counter()
            run_results.append({
                "run": run_label,
                "ttft": first_token_time,
                "total_time": end - start,
                "output_tokens": len(tokens),
                "decode_speed": len(tokens) / (end - start - first_token_time),
            })

        results.append({
            "run": run_label,
            "iterations": run_results,
            "avg_ttft": sum(r["ttft"] for r in run_results) / len(run_results),
            "avg_decode": sum(r["decode_speed"] for r in run_results) / len(run_results),
        })

        # Induce thermal load before Run 3
        if run_num == 1:
            print("Inducing thermal load (10 rapid requests)...")
            for _ in range(10):
                list(model.generate("Hello"))
            time.sleep(5)  # Short pause before measuring thermal state

    return results
```

### 5.2 Recommended Tools

| Tool | Platform | Notes |
|---|---|---|
| **[llama-benchy](https://github.com/eugr/llama-benchy)** | Any (CLI) | **Recommended** — works with any OpenAI-compatible endpoint (llama.cpp, vLLM, SGLang, Ollama). Measures pp/tg at different context depths. Default 3 runs with mean ± std. |
| **llama-bench** | llama.cpp only | Built into llama.cpp; measures pp/tg directly via C++ engine |
| **ExecuTorch benchmark** | Android/iOS | Meta's mobile runtime; has `BenchmarkRunner` |
| **MLC-LLM** | Android/iOS | Supports mobile GPU/NPU acceleration |
| **MediaPipe LLM** | Android | Google's on-device inference; integrates with Edge Gallery |
| **Android Profiler / Instruments** | Android/iOS | System-level CPU/GPU/memory/thermal monitoring |

### 5.3 llama-benchy Quick Reference

```bash
# Install
uvx llama-benchy --base-url <ENDPOINT_URL> --model <MODEL_NAME>

# Basic benchmark (3 runs, reports mean ± std)
llama-benchy \
  --base-url http://localhost:8080/v1 \
  --model my-model \
  --pp 2048 \
  --tg 128

# Multiple context depths (tests how performance degrades with context)
llama-benchy \
  --base-url http://localhost:8080/v1 \
  --model my-model \
  --pp 2048 \
  --tg 128 \
  --depth 0 4096 8192 16384

# Multiple prompt/generation lengths
llama-benchy \
  --base-url http://localhost:8080/v1 \
  --model my-model \
  --pp 128 512 2048 \
  --tg 32 128 512

# With prefix caching measurement
llama-benchy \
  --base-url http://localhost:8080/v1 \
  --model my-model \
  --pp 2048 \
  --tg 128 \
  --depth 0 4096 8192 \
  --enable-prefix-caching

# Save results as JSON for analysis
llama-benchy \
  --base-url http://localhost:8080/v1 \
  --model my-model \
  --pp 2048 \
  --tg 128 \
  --format json \
  --save-result results.json
```

**Key metrics output by llama-benchy:**

| Column | Description |
|---|---|
| `t/s` | Tokens per second (pp = prefill speed, tg = decode speed) |
| `peak t/s` | Highest throughput observed in any 1-second window |
| `ttfr (ms)` | Time to first response chunk from server |
| `est_ppt (ms)` | Estimated prompt processing time (TTFR minus network latency) |
| `e2e_ttft (ms)` | End-to-end time to first content token (what user perceives) |

### 5.3 System-Level Profiling

| Platform | Tool | What it measures |
|---|---|---|
| Android | `adb shell dumpsys cpuinfo` | CPU usage per process |
| Android | Android Studio Profiler | CPU, memory, GPU, thermal, battery |
| Android | `cat /sys/class/thermal/thermal_zone*/temp` | Thermal sensor readings |
| Android | `dumpsys batterystats` | Power consumption |
| iOS | Instruments (Time Profiler, Energy Log) | CPU, memory, energy, thermal |
| iOS | `os_signpost` | Custom interval timing |

---

## 6. Test Matrix Template

llama-benchy output (default 3 runs):

| model | test | t/s | peak t/s | ttfr (ms) | est_ppt (ms) | e2e_ttft (ms) |
|---|---|---|---|---|---|---|
| my-model | pp2048 | 8236 ± 134 | 298 ± 4 | 248 ± 4 | 242 ± 4 | 342 ± 3 |
| my-model | tg128 | 73.9 ± 1.2 | 76.6 ± 1.2 | | | |
| my-model | pp2048 @ d4096 | 7467 ± 131 | 324 ± 5 | 274 ± 5 | 268 ± 5 | 367 ± 5 |
| my-model | tg128 @ d4096 | 72.2 ± 0.1 | 74.9 ± 0.1 | | | |
| my-model | pp2048 @ d8192 | 6846 ± 135 | 349 ± 6 | 299 ± 6 | 293 ± 6 | 394 ± 5 |
| my-model | tg128 @ d8192 | 72.6 ± 0.7 | 75.2 ± 0.7 | | | |

---

## 7. Statistical Analysis & Reporting

### 7.1 Required Statistics

For each metric, report:
- **Mean** — Average across all runs
- **Median (P50)** — Middle value (resistant to outliers)
- **P95** — 95th percentile (captures tail latency)
- **P99** — 99th percentile (worst-case user experience)
- **Std Dev** — Variability indicator
- **Min / Max** — Range

### 7.2 Reporting Format

```
Model: Llama-3.2-1B (INT4)
Device: Samsung Galaxy S24 (Snapdragon 8 Gen 3)
Inference Runtime: llama.cpp 0.3.x

Prompt: 50 tokens (QA), Expected output: ~100 tokens
  TTFT:   Mean=320ms  P50=310ms  P95=380ms  P99=410ms
  Decode: Mean=45 tok/s  P50=46 tok/s  P95=38 tok/s
  E2E:    Mean=2.5s  P50=2.4s  P95=2.9s

Prompt: 500 tokens (Summarize), Expected output: ~300 tokens
  TTFT:   Mean=850ms  P50=820ms  P95=950ms  P99=1050ms
  Decode: Mean=42 tok/s  P50=43 tok/s  P95=35 tok/s
  E2E:    Mean=8.0s  P50=7.8s  P95=9.2s
```

---

## 8. Factors That Affect Results

| Factor | Impact |
|---|---|
| **Quantization level** | INT4 is ~2-4x faster than FP16 but may reduce quality |
| **Context length** | TTFT scales linearly with input length |
| **KV cache state** | First request is slower; subsequent requests reuse cache |
| **Thermal state** | Sustained load causes CPU throttling (up to 30-50% slowdown) |
| **Battery level** | Some devices throttle at low battery |
| **Background processes** | Other apps consume CPU/RAM/bandwidth |
| **Number of CPU threads** | Optimal = number of big cores; adding efficiency cores can hurt |
| **Runtime/Backend** | llama.cpp vs ExecuTorch vs MLC-LLM have different optimizations |
| **NPU vs GPU vs CPU** | NPU excels at prefill; GPU good for decode; CPU most compatible |

---

## 9. Reference Benchmarks (Edge Gallery Style)

Google AI Edge Gallery reports these metrics after each response:

```
┌─────────────────────────────────┐
│  Performance Insights           │
├─────────────────────────────────┤
│  Prefill Speed:  XX.X tok/s     │
│  Decode Speed:   XX.X tok/s     │
│  Total Latency:  X.XX s         │
│  Output Tokens:  XXX            │
└─────────────────────────────────┘
```

Your benchmark should aim to replicate this with more statistical rigor.

---

## 10. Quick-Start Checklist

- [ ] Choose 2-3 models of different sizes (e.g., 350M, 1B, 3B)
- [ ] Pick an inference runtime (llama.cpp, ExecuTorch, or MLC-LLM)
- [ ] Ensure endpoint exposes OpenAI-compatible `/v1/chat/completions`
- [ ] Install llama-benchy: `uvx llama-benchy --help`
- [ ] Run baseline: `llama-benchy --base-url <URL> --model <MODEL> --pp 2048 --tg 128`
- [ ] Test across context depths: `--depth 0 4096 8192 16384`
- [ ] Test across prompt lengths: `--pp 128 512 2048 4096`
- [ ] Save results: `--format json --save-result results.json`
- [ ] Profile CPU/GPU/memory usage during inference (Android Profiler / Instruments)
- [ ] Document everything in a results table

---

## References

- [Google AI Edge Gallery](https://github.com/google-ai-edge/gallery) — Performance Insights feature (TTFT, decode speed, latency)
- [IETF LLM Benchmarking Methodology Draft](https://datatracker.ietf.org/doc/draft-gaikwad-llm-benchmarking-methodology/) — Standardized LLM serving benchmarks
- [MobileLLM-Flash (Meta, ACL 2026)](https://arxiv.org/abs/2603.15954) — On-device LLM design under mobile latency constraints
- [LLM Performance Benchmarking on Mobile Platforms](https://arxiv.org/html/2410.03613v1) — Comprehensive mobile LLM measurement study
- [Jakob Nielsen's Response Time Thresholds](https://www.nngroup.com/articles/response-times-3-important-limits/) — 0.1s / 1.0s / 10s UX framework
