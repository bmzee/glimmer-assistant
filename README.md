# glimmer-assistant

A fully local, voice-activated PC assistant built on Meta's [Muse-Glimmer-30B](https://huggingface.co/meta-models/Muse-Glimmer-30B), served by [Ollama](https://ollama.com). No cloud LLM — all inference on-device.

**Status: Plan 1 complete** — a working text-mode core: a hand-rolled tool-calling agent loop with a risk-tiered permission gate, path allowlisting, a JSONL audit log, and platform-adapted tools (files, apps) for macOS. Voice, sandboxing, web, and email/calendar land in later phases — see [docs/spec.md](docs/spec.md) for the full design and [docs/smoke-test.md](docs/smoke-test.md) for first live results.

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
2. Security hardening — OS sandbox, untrusted-content quarantine, `run_shell`
3. Voice pipeline — push-to-talk, Parakeet-TDT STT, Kokoro TTS
4. Integrations — web (Playwright), Apple Mail/Calendar, Microsoft 365, MCP servers
5. Evals — model A/B (Glimmer vs Qwen3.8), structured-output gates

Apache-2.0-friendly stack; built Mac-first with a platform-adapter layer for a Windows port.
