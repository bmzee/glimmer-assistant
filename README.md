# glimmer-assistant

A fully local, voice-activated PC assistant built on Meta's [Muse-Glimmer-30B](https://huggingface.co/meta-models/Muse-Glimmer-30B), served by [Ollama](https://ollama.com). No cloud LLM — all inference on-device.

**Status: Plans 1–3 complete** — a working text-mode core (hand-rolled tool-calling agent loop, risk-tiered permission gate, path allowlisting, JSONL audit log, file/app tools), hardened with an OS sandbox (`sandbox-exec`), a sandboxed `run_shell` tool behind a structured confirmation, a datamarking seam for untrusted content, and result-hash logging — and now **voice**: hold a push-to-talk hotkey, speak, and it transcribes (Parakeet-MLX), runs the agent, and speaks the answer back (Kokoro-ONNX). The voice stack is torch-free and local. Web and email/calendar land in later phases — see [docs/spec.md](docs/spec.md) for the full design and the `docs/smoke-test*.md` files for live results.

## Try voice mode

```bash
pip install -e '.[voice]'          # torch-free: parakeet-mlx + kokoro-onnx
python -m assistant --voice        # hold Ctrl, speak, release
```

Needs macOS Microphone + Accessibility permission for the terminal, and Ollama running with the model. First launch downloads the STT/TTS models (~1GB).

## Try it (text mode)

Requires Python ≥ 3.12 and a running Ollama with the model pulled:

```bash
ollama pull muse-glimmer:30b
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m assistant
```

Then talk to it:

```
> what's on my Desktop?
> open the Calculator app
```

Configuration (endpoint, model, allowed file roots) lives in `assistant/config.yaml`.

## Tests

```bash
.venv/bin/python -m pytest
```

## Roadmap

1. ~~Core agent loop (text mode)~~ ✅
2. ~~Security hardening — OS sandbox, datamarking seam, sandboxed `run_shell`~~ ✅
3. ~~Voice pipeline — push-to-talk, Parakeet-MLX STT, Kokoro-ONNX TTS~~ ✅
4. Integrations — web (Playwright), Apple Mail/Calendar, Microsoft 365, MCP servers
5. Evals — model A/B (Glimmer vs Qwen3.8), structured-output gates

Apache-2.0-friendly stack; built Mac-first with a platform-adapter layer for a Windows port.
