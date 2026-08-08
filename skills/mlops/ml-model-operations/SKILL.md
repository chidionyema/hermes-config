---
name: ml-model-operations
description: "Work with machine-learning models end to end: discover and fetch artifacts, run local inference, serve APIs, benchmark, segment, generate media, and track experiments."
version: 1.0.0
author: Hermes Agent
platforms: [linux, macos]
metadata:
  hermes:
    tags: [mlops, models, huggingface, llama, vllm, benchmarks, wandb, segmentation, audiogen]
---

# ML Model Operations

Use this class skill for model lifecycle work, from artifact discovery through reproducible evaluation and serving.

## Lifecycle
1. Define task, hardware, license, latency/quality target, and artifact format.
2. Discover and pin model/dataset revisions; verify checksums and disk budget.
3. Choose local runtime (llama.cpp or equivalent), hosted generation workflow, or vLLM serving.
4. Run a small smoke test before a full batch.
5. Measure quality, throughput, memory, and failure modes; record configuration.
6. Clean up caches and expose only intended endpoints.

## Subsections
- **Hub and artifacts**: use Hugging Face search/download/upload with explicit revisions and access checks.
- **Local GGUF inference**: validate quantization, context size, prompt template, and GPU offload.
- **Serving**: bind vLLM deliberately, protect the OpenAI-compatible endpoint, and verify health plus one completion.
- **Evaluation**: pin harness version and task prompts; report command, model revision, and aggregate metrics.
- **Vision**: for SAM-style segmentation, record points/boxes, image preprocessing, and mask output format.
- **Generative audio**: keep lyrics/prompts, seeds, checkpoints, and output sample rate with the artifact.
- **Experiment tracking**: log code revision, environment, hyperparameters, metrics, and artifact lineage to W&B or an equivalent.

Never claim a benchmark or generation succeeded without inspecting the actual output and logs.
