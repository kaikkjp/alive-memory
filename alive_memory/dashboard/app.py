"""Streamlit debug dashboard for alive-memory.

Connects to the alive-memory REST API server to visualize cognitive state,
memories, identity, and drives in real time.

Usage:
    streamlit run alive_memory/dashboard/app.py -- --api-url http://localhost:8100

Requires: pip install alive-memory[dashboard]
"""

from __future__ import annotations

import argparse
import sys

import requests  # type: ignore[import-untyped]
import streamlit as st

DEFAULT_API_URL = "http://localhost:8100"


def get_api_url() -> str:
    """Get the API URL from CLI args or session state."""
    if "api_url" in st.session_state:
        return str(st.session_state.api_url)

    # Parse from Streamlit's -- args
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    # Streamlit passes args after --
    try:
        idx = sys.argv.index("--")
        args = parser.parse_args(sys.argv[idx + 1:])
    except (ValueError, SystemExit):
        args = parser.parse_args([])

    st.session_state.api_url = args.api_url
    return str(args.api_url)


def api_get(path: str, api_url: str, api_key: str | None = None) -> dict | list | None:
    """GET request to the API."""
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        resp = requests.get(f"{api_url}{path}", headers=headers, timeout=10)
        resp.raise_for_status()
        result: dict | list = resp.json()
        return result
    except requests.RequestException as e:
        st.error(f"API error: {e}")
        return None


def api_post(
    path: str, api_url: str, body: dict, api_key: str | None = None
) -> dict | None:
    """POST request to the API."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        resp = requests.post(f"{api_url}{path}", json=body, headers=headers, timeout=30)
        resp.raise_for_status()
        result: dict = resp.json()
        return result
    except requests.RequestException as e:
        st.error(f"API error: {e}")
        return None


def render_mood_drives(state: dict) -> None:
    """Render mood and drives gauges."""
    mood = state.get("mood", {})
    drives = state.get("drives", {})

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Mood")
        valence = mood.get("valence", 0)
        arousal = mood.get("arousal", 0.5)
        word = mood.get("word", "neutral")
        st.metric("Feeling", word)
        st.progress(max(0.0, min(1.0, (valence + 1) / 2)), text=f"Valence: {valence:.2f}")
        st.progress(max(0.0, min(1.0, arousal)), text=f"Arousal: {arousal:.2f}")
        st.metric("Energy", f"{state.get('energy', 0):.2f}")

    with col2:
        st.subheader("Drives")
        for drive_name in ["curiosity", "social", "expression", "rest"]:
            val = drives.get(drive_name, 0.5)
            st.progress(max(0.0, min(1.0, val)), text=f"{drive_name}: {val:.2f}")


def render_identity(identity: dict) -> None:
    """Render identity traits."""
    traits = identity.get("traits", {})
    if traits:
        for name, val in sorted(traits.items()):
            st.progress(max(0.0, min(1.0, val)), text=f"{name}: {val:.2f}")
    else:
        st.info("No traits recorded yet.")

    summary = identity.get("behavioral_summary", "")
    if summary:
        st.markdown(f"**Behavioral summary:** {summary}")

    drift = identity.get("drift_history", [])
    if drift:
        st.subheader("Drift History")
        for entry in drift[-5:]:
            st.json(entry)


def render_recall(results: dict) -> None:
    """Render recall results."""
    total = results.get("total_hits", 0)
    st.caption(f"{total} hits")

    for category in ["journal_entries", "visitor_notes", "self_knowledge",
                     "reflections", "thread_context"]:
        entries = results.get(category, [])
        if entries:
            label = category.replace("_", " ").title()
            with st.expander(f"{label} ({len(entries)})", expanded=len(entries) <= 3):
                for entry in entries:
                    st.markdown(entry)
                    st.divider()


def main() -> None:
    """Main dashboard entry point."""
    st.set_page_config(page_title="alive-memory dashboard", layout="wide")
    st.title("alive-memory dashboard")

    # Sidebar config
    with st.sidebar:
        api_url = st.text_input("API URL", value=get_api_url())
        st.session_state.api_url = api_url
        api_key = st.text_input("API Key (optional)", type="password")
        auto_refresh = st.checkbox("Auto-refresh", value=False)

        if auto_refresh:
            st.caption("Refreshing every 5 seconds")

    # Health check
    health = api_get("/health", api_url, api_key)
    if health is None:
        st.error(f"Cannot connect to {api_url}. Is the server running?")
        st.stop()

    assert isinstance(health, dict)
    st.caption(f"Connected to alive-memory v{health.get('version', '?')}")

    # Tabs
    tab_state, tab_recall, tab_identity, tab_intake, tab_consolidate = st.tabs(
        ["State", "Recall", "Identity", "Intake", "Consolidate"]
    )

    with tab_state:
        state = api_get("/state", api_url, api_key)
        if state:
            assert isinstance(state, dict)
            render_mood_drives(state)
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Cycle count", state.get("cycle_count", 0))
            with col2:
                st.metric("Total memories", state.get("memories_total", 0))
            last_sleep = state.get("last_sleep")
            if last_sleep:
                st.caption(f"Last sleep: {last_sleep}")

    with tab_recall:
        query = st.text_input("Search query", placeholder="Enter keywords...")
        if query:
            results = api_post("/recall", api_url, {"query": query}, api_key)
            if results:
                render_recall(results)

    with tab_identity:
        identity = api_get("/identity", api_url, api_key)
        if identity:
            assert isinstance(identity, dict)
            render_identity(identity)

    with tab_intake:
        st.subheader("Ingest an event")
        event_type = st.selectbox("Event type", ["conversation", "observation", "action", "system"])
        content = st.text_area("Content", placeholder="What happened?")
        if st.button("Ingest") and content:
            result = api_post(
                "/intake", api_url,
                {"event_type": event_type, "content": content},
                api_key,
            )
            if result:
                st.success(f"Moment recorded (salience: {result.get('salience', '?')})")
            else:
                st.info("Event was below salience threshold (not recorded)")

    with tab_consolidate:
        st.subheader("Trigger consolidation")
        depth = st.selectbox("Depth", ["full", "nap"])
        if st.button("Consolidate"):
            with st.spinner("Running consolidation..."):
                report = api_post(
                    "/consolidate", api_url,
                    {"depth": depth},
                    api_key,
                )
            if report:
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Moments processed", report.get("moments_processed", 0))
                with col2:
                    st.metric("Journal entries", report.get("journal_entries_written", 0))
                with col3:
                    st.metric("Cold embeddings", report.get("cold_embeddings_added", 0))

                dreams = report.get("dreams", [])
                if dreams:
                    st.subheader("Dreams")
                    for dream in dreams:
                        st.markdown(dream)

    if auto_refresh:
        import time
        time.sleep(5)
        st.rerun()


if __name__ == "__main__":
    main()
