# TASK-063: Evolvable fitness function (Frame 5)

## Problem

She currently optimizes for an implicit function (wellbeing + coherence) chosen by the designer. She has no visibility into what she's optimizing for, no ability to critique it, and no mechanism to propose changes. The fitness function is invisible and immutable.

## Solution

Give her a versioned, explicit fitness function she can read, critique, and propose changes to. Two-sleep review process for activation. She can revert to any previous version.

## Philosophical gate

**Do NOT start implementation until ALL of these are true:**

1. 60+ days of live operation with TASK-056 merged
2. At least 5 self-modifications recorded
3. At least 1 self-modification reverted by meta-sleep
4. At least 1 self-modification sustained across multiple meta-sleep reviews

This gate exists because designing the fitness function requires observing how she actually uses self-modification in practice. Premature implementation risks building the wrong abstraction.

## What we know now

- Versioned `fitness_function` table
- Weighted metrics she can adjust
- Two-sleep review gate (proposal must survive two consecutive sleep reviews)
- `propose_fitness_change` action (energy 0.20, cooldown 86400s)
- Dashboard with version history and score tracking

## Spec note

**Implementation details are intentionally omitted.** The metric registry, computation functions, and review prompts should be designed after 60 days of live data from TASK-060/061/062. The spec will be written when philosophical gate conditions are met.

## Scope

To be determined when spec is written.

## Definition of done

- She can propose changes to her own fitness function
- Proposals require two consecutive sleep approvals
- Active fitness function visible in cortex prompt
- Fitness score tracked over time and compared across versions
- Philosophical gate enforced in code
- Dashboard shows full fitness history
- System behavior plausibly shifts over months based on her chosen function
