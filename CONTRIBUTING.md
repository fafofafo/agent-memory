# Contributing to Agent Memory

Thanks for your interest! Before contributing, please read the [README](README.md) and the core principles below.

## Core Principles (must hold for every contribution)

1. **No fabricated metrics** — every statistic must be a real count; never output "estimated recall" pinned to a fixed range.
2. **Secrets never in plaintext** — passwords/tokens/API keys must be auto-redacted; writing a raw secret to any file is a defect.
3. **Single source of configuration** — all rooms/mappings/retrieval params live in `config.yaml`; no hardcoded duplicates.
4. **Zero-dependency core** — BM25, storage, pruning, redaction must stay pure Python standard library; external services only as pluggable backends with circuit-breaker degradation.

## Getting Started

```bash
# run the test suite before/after changes
python3 test_hermes_lite.py    # 79 assertions must all pass
python3 test_stress.py         # 150-memory stress test
```

## How to Contribute

1. Fork the repo and create a feature branch (`git checkout -b feat/your-feature`).
2. Make changes; add or update tests in `test_hermes_lite.py` (every behavior change needs an assertion).
3. Run the full test suite; it must pass.
4. Update docs if behavior or CLI changed (`README.md`, skill specs in `skills/`).
5. Open a pull request describing the change, tests, and why.

## Reporting Issues

- **Bugs**: open an issue with reproduction steps, expected vs actual behavior, and environment (Python version, OS).
- **Security vulnerabilities**: do NOT open a public issue — follow [SECURITY.md](SECURITY.md).

## Code Style

- Python 3.10+; type hints on public functions.
- UTF-8 source; docstrings in the language of the surrounding code.
- Keep the single-file core (`hermes_lite.py`) cohesive; new features should fit its layered design.
