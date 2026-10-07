"""Dash application for real-time ES market-state inference."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import threading
import time

from dash import Dash, Input, Output, State, callback, dcc, html
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np

from dashboard.realtime_inference import infer_market_state, prepare_bars


ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.getenv("TRADINGVIEW_CDP_PORT", "9223"))
POLL_SECONDS = int(os.getenv("DASHBOARD_POLL_SECONDS", "15"))
_CACHE = {"at": 0.0, "payload": None}
_LOCK = threading.Lock()


def _read_live() -> dict:
    with _LOCK:
        if _CACHE["payload"] and time.time() - _CACHE["at"] < max(3, POLL_SECONDS - 1):
            return _CACHE["payload"]
        command = ["node", str(ROOT / "scripts/export_tv_main_bars.mjs")]
        env = {**os.environ, "TRADINGVIEW_CDP_PORT": str(PORT)}
        try:
            completed = subprocess.run(command, cwd=ROOT, env=env, capture_output=True,
                                       text=True, timeout=45, check=True)
            raw = json.loads(completed.stdout)
            if not raw.get("success"):
                raise RuntimeError(raw.get("error", "TradingView export failed"))
            frame = prepare_bars(raw["bars"], exclude_live_bar=True)
            snapshot, history = infer_market_state(frame)
            payload = {"ok": True, "live": True, "source": "TradingView Desktop CDP",
                       "symbol": raw.get("symbol", "ES1!"),
                       "interval": raw.get("interval", "15"), "snapshot": snapshot.to_dict(),
                       "history": history.reset_index().to_json(orient="records", date_format="iso"),
                       "received_at": datetime.now(timezone.utc).isoformat(), "error": None}
        except Exception as exc:
            detail = exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) and exc.stderr else str(exc)
            fallback = Path(os.getenv("QUANT_TV_BARS_FILE", str(ROOT / "data/tradingview/bars.json")))
            try:
                raw = json.loads(fallback.read_text())
                frame = prepare_bars(raw["bars"], exclude_live_bar=True)
                snapshot, history = infer_market_state(frame)
                payload = {"ok": True, "live": False, "source": "Local bar snapshot",
                           "symbol": raw.get("symbol", "ES1!"), "interval": raw.get("interval", "15"),
                           "snapshot": snapshot.to_dict(),
                           "history": history.reset_index().to_json(orient="records", date_format="iso"),
                           "received_at": datetime.now(timezone.utc).isoformat(), "error": detail}
            except Exception as fallback_exc:
                payload = {"ok": False, "live": False,
                           "error": f"{detail}; fallback failed: {fallback_exc}",
                           "received_at": datetime.now(timezone.utc).isoformat()}
        _CACHE.update(at=time.time(), payload=payload)
        return payload


def _gauge(value: float, title: str, color: str) -> go.Figure:
    figure = go.Figure(go.Indicator(mode="number+gauge", value=value * 100,
        number={"suffix": "%", "font": {"size": 46, "color": color}},
        title={"text": f"<span style='font-size:12px;color:#82909c'>{title.upper()}</span>"},
        gauge={"shape": "bullet", "axis": {"range": [0, 100], "visible": False},
               "bar": {"color": color, "thickness": .35}, "bgcolor": "#20262c", "borderwidth": 0},
        domain={"x": [0.08, .92], "y": [.08, .9]}))
    figure.update_layout(height=150, margin=dict(l=10, r=10, t=30, b=8),
                         paper_bgcolor="#101419", font_color="#e9eef2")
    return figure


def _simulation_figure(records: list[dict], snapshot: dict) -> go.Figure:
    import pandas as pd
    frame = pd.DataFrame(records)
    returns = frame["return"].dropna().tail(192).to_numpy(float)
    sigma = max(float(np.nanstd(returns)), 1e-5)
    direction = 1 if snapshot["direction"] == "BULLISH" else -1
    drift = direction * sigma * .08 * snapshot["trend_probability"]
    stress = 1 + 1.7 * snapshot["stress_probability"]
    rng = np.random.default_rng(20260714)
    steps, paths = 48, 140
    shocks = rng.standard_t(df=5, size=(paths, steps)) * sigma * stress + drift
    simulated = snapshot["price"] * np.exp(np.cumsum(shocks, axis=1))
    x = np.arange(steps + 1)
    simulated = np.column_stack([np.full(paths, snapshot["price"]), simulated])
    fig = go.Figure()
    for path in simulated[:70]:
        fig.add_trace(go.Scatter(x=x, y=path, mode="lines", hoverinfo="skip", showlegend=False,
                                 line={"color": "rgba(71,167,255,.10)", "width": 1}))
    q05, q25, q50, q75, q95 = np.quantile(simulated, [.05, .25, .5, .75, .95], axis=0)
    fig.add_trace(go.Scatter(x=x, y=q95, line={"width": 0}, hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=x, y=q05, fill="tonexty", fillcolor="rgba(42,107,142,.14)",
                             line={"width": 0}, name="90% field"))
    fig.add_trace(go.Scatter(x=x, y=q75, line={"width": 0}, hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=x, y=q25, fill="tonexty", fillcolor="rgba(36,180,126,.15)",
                             line={"width": 0}, name="50% field"))
    fig.add_trace(go.Scatter(x=x, y=q50, name="median path",
                             line={"color": "#f2f5f7", "width": 3}))
    fig.add_hline(y=snapshot["price"], line_dash="dot", line_color="#6f7c86", opacity=.7)
    fig.update_layout(height=470, margin=dict(l=20, r=25, t=15, b=30),
                      paper_bgcolor="#0c1014", plot_bgcolor="#0c1014", font_color="#aab6c0",
                      xaxis={"title": "15-MINUTE STEPS", "showgrid": False, "zeroline": False},
                      yaxis={"side": "right", "gridcolor": "#1b2229", "tickformat": ",.0f"},
                      legend={"orientation": "h", "y": 1.02, "x": .02}, hovermode="x unified")
    return fig


def _history_figure(records: list[dict]) -> go.Figure:
    import pandas as pd
    frame = pd.DataFrame(records)
    frame["time"] = pd.to_datetime(frame["time"], utc=True)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=.08,
                        row_heights=[.62, .38])
    fig.add_trace(go.Candlestick(x=frame.time, open=frame.open, high=frame.high,
                                 low=frame.low, close=frame.close, name="ES"), row=1, col=1)
    for field, name, color in [("trend_probability", "Trend", "#35a7ff"),
                               ("chop_probability", "Chop", "#e0a12b"),
                               ("stress_probability", "Stress", "#ef5b5b")]:
        fig.add_trace(go.Scatter(x=frame.time, y=100 * frame[field], name=name,
                                 line={"color": color, "width": 1.8}), row=2, col=1)
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Probability", range=[0, 100], ticksuffix="%", row=2, col=1)
    fig.update_layout(height=520, margin=dict(l=55, r=25, t=20, b=35),
                      paper_bgcolor="#111418", plot_bgcolor="#111418", font_color="#cbd4dc",
                      xaxis_rangeslider_visible=False, legend_orientation="h",
                      legend_y=1.02, legend_x=.55)
    fig.update_xaxes(gridcolor="#252b31")
    fig.update_yaxes(gridcolor="#252b31")
    return fig


app = Dash(__name__, title="ES Inference Monitor", assets_folder=str(ROOT / "dashboard/assets"))
app.layout = html.Main([
    dcc.Interval(id="poll", interval=POLL_SECONDS * 1000, n_intervals=0),
    dcc.Store(id="live-store"),
    html.Header([html.Div([html.Div("QUANT DESK / LIVE INFERENCE", className="kicker"),
                          html.H1("The market is not one distribution.")]),
                 html.Div(id="connection", className="status")]),
    html.Section(id="summary", className="summary-grid"),
    html.Section([html.Div([html.Div("MONTE CARLO FIELD · 12H", className="kicker"),
                            html.H2("WHERE PRICE COULD GO NEXT"),
                            dcc.Graph(id="simulation-chart", config={"displaylogo": False})], className="simulation-stage"),
                  html.Aside([html.Div([html.Div("LATENT STATE", className="kicker"),
                                       html.Div(id="state-word", className="state-word"),
                                       html.Div(id="state-formula", className="formula")]),
                              dcc.Graph(id="trend-gauge", config={"displayModeBar": False}),
                              dcc.Graph(id="chop-gauge", config={"displayModeBar": False}),
                              dcc.Graph(id="stress-gauge", config={"displayModeBar": False}),
                              dcc.Graph(id="risk-gauge", config={"displayModeBar": False})])], className="hero-grid"),
    html.Section([html.Div([html.Div([html.Div("FILTERED OBSERVATION", className="kicker"), html.H2("STATE TRANSITION TAPE")]),
                            html.Div(id="freshness")], className="section-head"),
                  dcc.Graph(id="history-chart", config={"displaylogo": False})], className="panel"),
    html.Section([html.Div([html.Div("MODEL", className="kicker"), html.H2("CAUSAL LOGIT STATE"),
                            html.Div("p(zₜ | y₁:ₜ)", className="big-formula")]),
                  html.Div([html.Div("RISK", className="kicker"), html.H2("EXPOSURE FUNCTION"),
                            html.Div("wₜ = 1 − 0.65·stress − 0.15·chop", className="big-formula")]),
                  html.Div([html.Div("TELEMETRY", className="kicker"), html.Div(id="operations")])], className="method-grid"),
])


@callback(Output("live-store", "data"), Input("poll", "n_intervals"))
def refresh(_):
    return _read_live()


@callback(Output("connection", "children"), Output("connection", "className"),
          Output("summary", "children"), Output("trend-gauge", "figure"),
          Output("chop-gauge", "figure"), Output("stress-gauge", "figure"),
          Output("risk-gauge", "figure"), Output("history-chart", "figure"),
          Output("simulation-chart", "figure"), Output("state-word", "children"),
          Output("state-word", "className"), Output("state-formula", "children"),
          Output("freshness", "children"), Output("operations", "children"),
          Input("live-store", "data"))
def render(payload):
    empty = go.Figure().update_layout(paper_bgcolor="#111418", plot_bgcolor="#111418")
    if not payload or not payload.get("ok"):
        error = (payload or {}).get("error", "Waiting for TradingView")
        return ("OFFLINE", "status offline", [html.Div(error, className="error")],
                empty, empty, empty, empty, empty, empty, "WAITING", "state-word",
                "p(zₜ | y₁:ₜ)", "No fresh data", error)
    s = payload["snapshot"]
    cards = [
        html.Div([html.Span("INSTRUMENT"), html.Strong(f"{payload['symbol']} / {payload['interval']}m")]),
        html.Div([html.Span("LAST CLOSED"), html.Strong(f"{s['price']:,.2f}"), html.I("CME E-MINI")]),
        html.Div([html.Span("DIRECTIONAL POSTERIOR"), html.Strong(f"{s['direction_probability']:.0%}"), html.I(s["direction"])]),
        html.Div([html.Span("VOLATILITY RANK"), html.Strong(f"{s['volatility_percentile']:.0%}"), html.I("ROLLING 96H")]),
    ]
    history = json.loads(payload["history"])
    operations = html.Ul([html.Li(f"Closed bars used: {s['bars_used']:,}"),
                          html.Li(f"Volatility percentile: {s['volatility_percentile']:.1%}"),
                          html.Li(f"State confidence: {s['confidence']:.1%}"),
                          html.Li(f"Source: {payload['source']}"),
                          html.Li("Live reconnect is automatic" if not payload.get("live") else f"CDP port: {PORT}")])
    stamp = f"Closed bar: {s['timestamp']} · received: {payload['received_at']}"
    status_text = "LIVE" if payload.get("live") else "DEGRADED · SNAPSHOT"
    status_class = "status live" if payload.get("live") else "status degraded"
    return (status_text, status_class, cards,
            _gauge(s["trend_probability"], "Trend", "#35a7ff"),
            _gauge(s["chop_probability"], "Chop", "#e0a12b"),
            _gauge(s["stress_probability"], "Stress", "#ef5b5b"),
            _gauge(s["risk_multiplier"], "Advisory exposure", "#24b47e"),
            _history_figure(history), _simulation_figure(history, s), s["state"],
            f"state-word {s['state'].lower()}",
            f"arg max p(zₜ) = {s['confidence']:.1%}", stamp, operations)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("DASHBOARD_PORT", "8060")), debug=False)
