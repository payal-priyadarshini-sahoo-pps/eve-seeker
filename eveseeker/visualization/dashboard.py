"""Streamlit dashboard:  streamlit run eveseeker/visualization/dashboard.py

Drives the real simulator and agents. The agent view is built from the agent's belief only;
ground truth is confined to the clearly labelled evaluation tab.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from eveseeker.environment import MissionConfig  # noqa: E402
from eveseeker.experiments.runner import MissionSession, run_mission  # noqa: E402
from eveseeker.experiments.stats import wilson_ci  # noqa: E402
from eveseeker.strategies import LABELS, STRATEGIES  # noqa: E402
from eveseeker.visualization.render import draw_agent_view, draw_truth_view  # noqa: E402

st.set_page_config(page_title="EVE-Seeker", page_icon="🤖", layout="wide")
CONFIG_DIR = ROOT / "configs"
RESULTS = ROOT / "results"


def load_session() -> MissionSession:
    return MissionSession(st.session_state.cfg, st.session_state.strategy, st.session_state.seed)


def reset() -> None:
    st.session_state.sess = load_session()


# ---------------------------------------------------------------- sidebar
st.sidebar.title("🤖 EVE-Seeker")
st.sidebar.caption("Uncertainty-aware autonomous search agent")
presets = sorted(p.name for p in CONFIG_DIR.glob("*.json"))
preset = st.sidebar.selectbox("Mission preset", presets, index=presets.index("default_mission.json") if "default_mission.json" in presets else 0)
base = MissionConfig.from_json(CONFIG_DIR / preset)
strategy = st.sidebar.selectbox("Strategy", list(STRATEGIES), index=2, format_func=lambda s: LABELS[s])
st.session_state.setdefault("seed_in", int(base.seed))
seed = st.sidebar.number_input("Mission seed", 0, 10**6, step=1, key="seed_in")
with st.sidebar.expander("Override conditions"):
    rel = st.slider("Signal reliability", 0.34, 0.99, float(base.signal.reliability), 0.01)
    decoy_p = st.slider("Misleading (decoy) probability", 0.0, 1.0, float(base.decoys.probability), 0.05)
    cap = st.slider("Battery capacity", 10, 120, int(base.battery.capacity), 5)
    acts = st.slider("Action budget", 20, 300, int(base.budget.max_actions), 10)
over = {"signal.reliability": rel, "decoys.probability": decoy_p, "battery.capacity": float(cap),
        "budget.max_actions": acts}
if decoy_p > 0 and base.decoys.count == 0:
    over["decoys.count"] = 2
cfg = base.override(**over)

key = (preset, strategy, int(seed), tuple(sorted(over.items())))
if st.session_state.get("key") != key:
    st.session_state.update(key=key, cfg=cfg, strategy=strategy, seed=int(seed))
    reset()
sess: MissionSession = st.session_state.sess

c1, c2, c3 = st.sidebar.columns(3)
if c1.button("Step"):
    if not sess.done:
        sess.step()
if c2.button("+10"):
    for _ in range(10):
        if not sess.done:
            sess.step()
if c3.button("Run"):
    while not sess.done:
        sess.step()
d1, d2 = st.sidebar.columns(2)
if d1.button("Reset"):
    reset()
    st.rerun()
d2.button("New seed", on_click=lambda: st.session_state.update(seed_in=st.session_state.seed_in + 1))
if st.sidebar.button("Rerun (same seed)"):
    reset()
    while not st.session_state.sess.done:
        st.session_state.sess.step()
    st.rerun()

tab_mission, tab_compare, tab_truth = st.tabs(["Live mission", "Strategy comparison", "Evaluation-only ground truth"])

# ---------------------------------------------------------------- live mission
with tab_mission:
    obs = sess.obs
    status_map = {"running": ("🟢 RUNNING", st.info), "success": ("✅ SUCCESS — EVE found", st.success),
                  "stopped_uncertain": ("🟠 STOPPED — uncertain, estimate reported", st.warning)}
    label, box = status_map.get(obs.status, (f"🔴 FAILED — {obs.status}", st.error))
    box(f"**{label}**  ·  step {obs.step}")
    left, right = st.columns([3, 2])
    with left:
        fig = draw_agent_view(sess)
        st.pyplot(fig)
        plt.close(fig)
    with right:
        ent = sess.agent.entropy()
        est, conf = sess.agent.estimate() if obs.contact is None else (obs.contact, 1.0)
        m1, m2 = st.columns(2)
        m1.metric("Battery", f"{obs.battery:.1f} / {cfg.battery.capacity:.0f}")
        m2.metric("Entropy (bits)", "n/a" if ent is None else f"{ent:.2f}")
        m3, m4 = st.columns(2)
        m3.metric("Time left", obs.time_remaining)
        m4.metric("Actions left", obs.actions_remaining)
        st.progress(max(0.0, min(1.0, obs.battery / cfg.battery.capacity)), text="battery")
        if sess.agent.belief_map() is not None:
            st.write(f"**EVE estimate:** {est} (probability {conf:.2f}) — "
                     + ("**confirmed by sight**" if obs.contact else "*uncertain, not confirmed*"))
        if sess.trace:
            last = sess.trace[-1]
            st.markdown(f"**Last action:** `{last.action}`")
            st.info(last.reason or "—")
        st.write(f"Scans: {sess.env.stats.scans} · Recharges: {sess.env.stats.recharges} · "
                 f"Energy used: {sess.env.stats.energy_used:.1f} · Clues found: {len(sess.discovered)}")
    if sess.trace:
        hist = pd.DataFrame([{"step": r.step, "action": r.action, "pos": r.position, "battery": r.battery,
                              "entropy": r.entropy, "reading": r.reading, "clues": r.clues or "",
                              "why": r.reason} for r in sess.trace])
        if hist.entropy.notna().any():
            st.subheader("Uncertainty over time")
            st.line_chart(hist.set_index("step")["entropy"], height=180)
        st.subheader("Action & observation history")
        st.dataframe(hist.iloc[::-1], width="stretch", height=260, hide_index=True)

# ---------------------------------------------------------------- comparison
with tab_compare:
    st.subheader("Benchmark results (from `results/`, produced by the experiment runner)")
    summ = RESULTS / "summary.csv"
    if summ.exists():
        s = pd.read_csv(summ)
        meta_path = RESULTS / "run_metadata.json"
        st.caption(f"Pre-computed with fixed seeds; see results/run_metadata.json ({meta_path.exists()}).")
        factor = st.selectbox("Condition sweep", list(dict.fromkeys(s.factor)))
        g = s[s.factor == factor].copy()
        g["strategy"] = g.strategy.map(LABELS)
        piv = g.pivot_table(index="level", columns="strategy", values="success_rate", sort=False)
        st.bar_chart(piv)
        st.dataframe(g[["level", "strategy", "trials", "success_rate", "success_lo", "success_hi",
                        "mean_actions", "mean_energy", "mean_scans", "exhaustion_rate", "mean_final_error"]]
                     .round(3), hide_index=True, width="stretch")
        for img in ("plot_success_by_condition.png", "plot_efficiency_vs_reliability.png"):
            if (RESULTS / img).exists():
                st.image(str(RESULTS / img))
    else:
        st.warning("No benchmark found. Run: python -m eveseeker.experiments.run_experiments")
    st.subheader("Live head-to-head on the current conditions")
    n = st.slider("Missions per strategy (seeds 0..n-1)", 5, 40, 15)
    if st.button("Run live comparison"):
        rows = []
        bar = st.progress(0.0)
        todo = [(s_, sd) for s_ in STRATEGIES for sd in range(n)]
        res = {}
        for i, (s_, sd) in enumerate(todo):
            res.setdefault(s_, []).append(run_mission(cfg, s_, sd))
            bar.progress((i + 1) / len(todo))
        for s_, rs in res.items():
            k = sum(r.success for r in rs)
            lo, hi = wilson_ci(k, len(rs))
            rows.append({"strategy": LABELS[s_], "success": k / len(rs), "95% CI": f"[{lo:.2f}, {hi:.2f}]",
                         "mean actions": sum(r.actions for r in rs) / len(rs),
                         "mean energy": sum(r.energy_used for r in rs) / len(rs),
                         "exhausted": sum(r.resource_exhausted for r in rs) / len(rs)})
        st.dataframe(pd.DataFrame(rows).round(3), hide_index=True, width="stretch")
        st.caption(f"{n} missions per strategy is a small sample; wide intervals mean differences may be noise.")

# ---------------------------------------------------------------- ground truth
with tab_truth:
    st.error("EVALUATION-ONLY VIEW. This shows hidden ground truth (EVE, clues, decoys). "
             "The agent never receives this information.")
    if st.checkbox("Reveal ground truth"):
        fig = draw_truth_view(sess)
        st.pyplot(fig)
        plt.close(fig)
