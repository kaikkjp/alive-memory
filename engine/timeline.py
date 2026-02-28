"""Timeline Logger — compact simulation output. No LLM.

Prints one line per cycle during simulation:
    [Day 3  14:32] consume — reading about brutalist architecture
    [Day 3  14:35] idle — fidget: She takes a sip of tea.
    [Day 3  17:00] SLEEP — 4 moments consolidated
"""

import pathlib
from datetime import datetime, timedelta, timezone

from clock import JST


class TimelineLogger:
    """Compact timeline logger for simulation output."""

    def __init__(self, log_path: str, start_time: datetime):
        self.log_path = pathlib.Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._start = start_time
        self._f = open(self.log_path, 'w')
        self._cycle_count = 0
        self._header()

    def _header(self):
        line = f"=== Simulation started at {self._start.strftime('%Y-%m-%d %H:%M JST')} ==="
        self._write(line)

    def _write(self, line: str, quiet: bool = False):
        self._f.write(line + '\n')
        self._f.flush()
        if not quiet:
            print(line)

    def _day_label(self, now: datetime) -> str:
        """Compute day number relative to simulation start."""
        delta = now - self._start
        day = delta.days + 1
        return f"Day {day:<2}"

    def _time_label(self, now: datetime) -> str:
        """Format as HH:MM in JST."""
        jst = now.astimezone(JST) if now.tzinfo else now
        return jst.strftime('%H:%M')

    def log_cycle(self, sim_time: datetime, result, quiet: bool = False):
        """Log a single cycle result."""
        self._cycle_count += 1
        day = self._day_label(sim_time)
        time = self._time_label(sim_time)
        channel = result.focus_channel
        detail = result.detail[:60] if result.detail else ''

        line = f"[{day} {time}] {channel:<8} — {detail}"
        if result.dialogue:
            line += f'  \033[90m"{result.dialogue[:40]}..."\033[0m'
        self._write(line, quiet=quiet)

    def log_sleep(self, sim_time: datetime, moment_count: int, quiet: bool = False):
        """Log sleep cycle."""
        day = self._day_label(sim_time)
        time = self._time_label(sim_time)
        line = f"[{day} {time}] SLEEP    — {moment_count} moments consolidated"
        self._write(line, quiet=quiet)

    def log_wake(self, sim_time: datetime, quiet: bool = False):
        """Log waking up."""
        day = self._day_label(sim_time)
        time = self._time_label(sim_time)
        line = f"[{day} {time}] WAKE     — new day begins"
        self._write(line, quiet=quiet)

    def log_visitor_arrive(self, sim_time: datetime, display_name: str, quiet: bool = False):
        """Log visitor arrival."""
        day = self._day_label(sim_time)
        time = self._time_label(sim_time)
        line = f"[{day} {time}] VISITOR  — {display_name} enters the shop"
        self._write(line, quiet=quiet)

    def log_visitor_message(self, sim_time: datetime, display_name: str, text: str, quiet: bool = False):
        """Log visitor speech."""
        day = self._day_label(sim_time)
        time = self._time_label(sim_time)
        truncated = text[:60] if len(text) > 60 else text
        line = f'[{day} {time}] VISITOR  — {display_name} says: "{truncated}"'
        self._write(line, quiet=quiet)

    def log_visitor_depart(self, sim_time: datetime, display_name: str, quiet: bool = False):
        """Log visitor departure."""
        day = self._day_label(sim_time)
        time = self._time_label(sim_time)
        line = f"[{day} {time}] VISITOR  — {display_name} leaves the shop"
        self._write(line, quiet=quiet)

    def log_summary(self, stats: dict):
        """Print final simulation statistics."""
        lines = [
            '',
            '=== Simulation Complete ===',
            f"  Total cycles: {stats.get('total_cycles', self._cycle_count)}",
            f"  Days simulated: {stats.get('days', '?')}",
            f"  Journal entries: {stats.get('journal_count', '?')}",
            f"  Cycle log entries: {stats.get('cycle_log_count', '?')}",
            f"  DB path: {stats.get('db_path', '?')}",
            f"  Log path: {self.log_path}",
            '',
        ]
        for line in lines:
            self._write(line)

    def close(self):
        self._f.close()
