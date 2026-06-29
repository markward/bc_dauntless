# tools/probes/

Probe files for instrumentation approach 2 (the BC `-TestMode` Python REPL).

**Full workflow:** see [`docs/instrumented_experiments/console-probe-workflow.md`](../../docs/instrumented_experiments/console-probe-workflow.md).

## Quick reference

| | |
|---|---|
| Author a probe | copy `_template.py` to `q0N_<short_name>.py` |
| Push to the game | `uv run python tools/probes/push.py q0N` |
| Run on the BC machine | launch `stbc.exe -TestMode`; `execfile('q0N_*.py')` |
| Collect results | `uv run python tools/probes/collect.py q0N` |
| Result file (committed) | `tools/probes/results/q0N_<short_name>.txt` |

`push.py --all` and `collect.py --all` operate on every probe in this directory.

## Layout

```
_template.py             canonical probe skeleton
push.py                  copy probe(s) to game/
collect.py               extract [BCProbe_q0N] section from game/BCProbe_q0N.cfg
q0N_<name>.py            individual probes
results/q0N_<name>.txt   captured findings -- one per probe
```
