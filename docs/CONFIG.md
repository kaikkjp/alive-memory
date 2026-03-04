# Configuration Reference

alive-memory uses a YAML config with dot-notation access. Override defaults by passing a dict or YAML path to `AliveMemory()`.

```python
# From dict
memory = AliveMemory(config={"consolidation": {"dream_count": 5}})

# From YAML file
memory = AliveMemory(config="my_config.yaml")

# Access values
cfg = AliveConfig()
cfg.get("memory.embedding_dimensions")  # → 384
cfg.get("nonexistent.key", 42)          # → 42 (default)
```

## All Parameters

### `memory`

| Key | Default | Description |
|-----|---------|-------------|
| `memory.embedding_dimensions` | `384` | Dimensionality of vector embeddings for cold archive |

### `intake`

| Key | Default | Description |
|-----|---------|-------------|
| `intake.base_salience` | `0.5` | Base salience score before event-type adjustments |
| `intake.conversation_boost` | `0.2` | Bonus salience for conversation events |
| `intake.novelty_weight` | `0.3` | Weight of content novelty in salience scoring |

### `drives`

| Key | Default | Description |
|-----|---------|-------------|
| `drives.equilibrium_pull` | `0.02` | Rate at which drives return to 0.5 baseline |
| `drives.diminishing_returns` | `0.8` | Multiplier for repeated stimuli of the same type |
| `drives.social_sensitivity` | `0.5` | How much social events affect the social drive (0-1) |

### `consolidation`

| Key | Default | Description |
|-----|---------|-------------|
| `consolidation.decay_rate` | `0.01` | Memory strength decay per hour (for meta-controller) |
| `consolidation.decay_floor` | `0.05` | Minimum strength a memory can decay to |
| `consolidation.dream_count` | `3` | Number of dreams generated per full consolidation |
| `consolidation.reflection_count` | `2` | Number of reflections per consolidation |
| `consolidation.nap_moment_count` | `5` | Max moments to process during nap mode |
| `consolidation.cold_embed_limit` | `50` | Max embeddings to create per sleep cycle |

### `recall`

| Key | Default | Description |
|-----|---------|-------------|
| `recall.default_limit` | `10` | Default max results per recall query |
| `recall.context_lines` | `3` | Lines of context around grep matches in hot memory |

### `identity`

| Key | Default | Description |
|-----|---------|-------------|
| `identity.snapshot_interval` | `10` | Consolidation cycles between self-model snapshots |
| `identity.drift_window` | `50` | Number of cycles to look back for drift detection |
| `identity.drift_threshold` | `0.15` | Trait change magnitude required to flag as drift |
