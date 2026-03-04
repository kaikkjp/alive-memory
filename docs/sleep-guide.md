# Sleep Cycle Integration Guide

## Quick Start

The simplest `sleep_cycle()` call needs only the core components:

```python
from alive_memory import AliveMemory

async with AliveMemory(storage="agent.db", memory_dir="/data/memory") as memory:
    # Record some events during the day...
    await memory.intake("conversation", "Hello world", metadata={"salience": 0.9})

    # Run the full sleep cycle
    report = await memory.sleep()
    print(f"Consolidated {report.moments_consolidated} moments")
    print(f"Generated {report.dreams_generated} dreams")
```

Or using the standalone function:

```python
from alive_memory import sleep_cycle, SleepConfig

report = await sleep_cycle(storage, writer, reader, llm, embedder, config)
```

## Full Integration

Supply optional providers to enable all sleep phases:

```python
from alive_memory import sleep_cycle, SleepConfig

report = await sleep_cycle(
    storage, writer, reader, llm, embedder, config,
    whispers=[{"param_path": "drives.curiosity", "old_value": 0.3, "new_value": 0.7}],
    metrics_provider=my_metrics,
    drive_provider=my_drives,
    wake_hooks=my_hooks,
    metric_targets=my_targets,
    protected_traits={"warmth": (0.3, 0.9)},
)
```

## Provider Implementation

### MetricsProvider

Any object with an async `collect_metrics()` method:

```python
class MyMetricsProvider:
    async def collect_metrics(self) -> dict[str, float]:
        return {
            "response_quality": 0.75,
            "engagement_rate": 0.60,
        }
```

### DriveProvider

Used by meta-review for trait stability analysis:

```python
class MyDriveProvider:
    async def get_drives(self) -> dict[str, float]:
        return {"curiosity": 0.6, "social": 0.4}
```

### WakeHooks

Application-specific callbacks during wake transition:

```python
class MyWakeHooks:
    async def on_wake(self, storage, config):
        # Reset thread pools, flush caches, etc.
        pass
```

## Configuration

### SleepConfig

Control which phases run:

```python
from alive_memory import SleepConfig

config = SleepConfig(
    enable_whispers=True,          # Process config-change whispers
    enable_meta_review=True,       # Trait stability checks
    enable_meta_controller=True,   # Parameter homeostasis
    enable_identity_evolution=True, # Drift detection and resolution
    enable_wake=True,              # Wake transition hooks
    fault_tolerant=True,           # Continue on phase failure
    consolidation_depth="full",    # "full" or "nap"
)
```

### AliveConfig sleep section

Default values in `alive_config.yaml`:

```yaml
sleep:
  fault_tolerant: true
  enable_whispers: true
  enable_meta_review: true
  enable_meta_controller: true
  enable_identity_evolution: true
  enable_wake: true
```

## Nap vs Full Sleep

Use `nap()` for lightweight mid-cycle consolidation that only processes
the top moments by salience. No meta-cognition, identity, or wake phases run.

```python
from alive_memory import nap

report = await nap(storage, writer, reader, llm)
assert report.depth == "nap"
```

Use `sleep_cycle()` for the full orchestrated sleep with all phases.

## Error Handling

With `fault_tolerant=True` (default), each phase catches its own exceptions.
Failed phases are logged and recorded in `SleepCycleReport.errors`:

```python
report = await sleep_cycle(storage, writer, reader, llm)
if report.errors:
    for err in report.errors:
        print(f"Non-fatal: {err}")
print(f"Completed phases: {report.phases_completed}")
```

With `fault_tolerant=False`, the first phase failure raises immediately:

```python
config = SleepConfig(fault_tolerant=False)
try:
    report = await sleep_cycle(storage, writer, reader, llm, sleep_config=config)
except Exception as e:
    print(f"Sleep cycle failed: {e}")
```

## AliveMemory.sleep()

The `AliveMemory` class provides a convenience method that wires up
all internal components automatically:

```python
async with AliveMemory(storage="agent.db", memory_dir="/data/memory") as memory:
    report = await memory.sleep(
        metrics_provider=my_metrics,
        protected_traits={"warmth": (0.3, 0.9)},
    )
```
