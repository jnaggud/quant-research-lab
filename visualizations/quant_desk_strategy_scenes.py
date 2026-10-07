"""ManimGL scenes generated from immutable July 14 strategy reports."""
from __future__ import annotations

import json
from pathlib import Path

from manimlib import *


ROOT = Path(__file__).resolve().parents[1]
AUDIT = json.loads((ROOT / "reports/quant_desk_methods_audit_20260714.json").read_text())
INK = "#E8ECEF"
MUTED = "#8B99A6"
GREEN = "#24B47E"
RED = "#E65353"
AMBER = "#E0A12B"
BLUE = "#3E8EDE"


def label(text, size=28, color=INK):
    return Text(text, font="Arial", font_size=size, color=color)


class EvidenceStack(Scene):
    def construct(self):
        evidence = AUDIT["evidence"]
        exact = evidence["exact_tradingview"]
        long = evidence["five_year_transport"]
        title = label("C11: evidence changes with the horizon", 42).to_edge(UP)
        subtitle = label("Recent performance is real; distribution certainty is not.", 24, MUTED)
        subtitle.next_to(title, DOWN, buff=0.18)
        self.play(Write(title), FadeIn(subtitle))

        panels = VGroup()
        rows = [
            ("Exact TradingView", "247 days", f"${exact['total_pnl']:,.0f}",
             f"drawdown {abs(exact['max_drawdown']):.1%}", GREEN),
            ("Five-year transport", "2021-2026", f"${long['net']:,.0f}",
             f"drawdown {abs(long['max_drawdown']):.1%}", AMBER),
        ]
        for heading, span, pnl, dd, color in rows:
            box = Rectangle(width=5.3, height=3.0, stroke_color=color, stroke_width=2)
            content = VGroup(label(heading, 29), label(span, 22, MUTED),
                             label(pnl, 38, color), label(dd, 23, RED))
            content.arrange(DOWN, buff=0.22).move_to(box)
            panels.add(VGroup(box, content))
        panels.arrange(RIGHT, buff=0.55).shift(DOWN * 0.45)
        self.play(LaggedStart(*[FadeIn(x, shift=UP * 0.2) for x in panels], lag_ratio=0.25))
        footer = label("Decision: preserve C11; size from stressed risk, not the short-window equity curve.", 24)
        footer.to_edge(DOWN, buff=0.5)
        self.play(Write(footer))
        self.wait(2)


class TailRiskStress(Scene):
    def construct(self):
        sim = AUDIT["evidence"]["three_year_simulation"]
        base, stress = sim["baseline"], sim["execution_stress"]
        title = label("One million regime-preserving paths", 42).to_edge(UP)
        self.play(Write(title))
        chart = VGroup()
        metrics = [("P(drawdown >= 30%)", "probability_drawdown_30pct"),
                   ("P(capital loss >= 50%)", "probability_ruin_50pct")]
        for row, (name, key) in enumerate(metrics):
            y = 1.4 - row * 2.25
            name_mob = label(name, 25).move_to(LEFT * 4.6 + UP * y).set_x(-4.6)
            name_mob.align_to(LEFT * 6.4, LEFT)
            chart.add(name_mob)
            for j, (caption, source, color) in enumerate([
                    ("baseline", base, BLUE), ("execution + jumps", stress, RED)]):
                value = source[key]
                width = 5.5 * value
                bar = Rectangle(width=max(width, 0.04), height=0.48,
                                fill_color=color, fill_opacity=0.85, stroke_width=0)
                bar.move_to(LEFT * 2.5 + RIGHT * width / 2 + UP * (y - 0.55 - j * 0.62))
                cap = label(f"{caption}: {value:.1%}", 21, color).next_to(bar, RIGHT, buff=0.16)
                chart.add(bar, cap)
        self.play(LaggedStart(*[FadeIn(m, shift=RIGHT * 0.15) for m in chart], lag_ratio=0.06))
        note = label("Execution assumptions dominate the risk result.", 29, AMBER).to_edge(DOWN, buff=0.48)
        self.play(Write(note))
        self.wait(2)


class MethodTriage(Scene):
    def construct(self):
        title = label("What transfers from the quant-desk post?", 42).to_edge(UP)
        self.play(Write(title))
        columns = [
            ("USE NOW", GREEN, ["Calibration", "Empirical fills", "EVT / jump stress", "Block bootstrap"]),
            ("PORTFOLIO / MONITOR", AMBER, ["Latent-state filter", "t / vine copula", "Importance sampling"]),
            ("DEFER / REJECT", RED, ["Quant GAN", "Neural SDE", "Toy ABM as fill model"]),
        ]
        groups = VGroup()
        for heading, color, methods in columns:
            box = Rectangle(width=4.05, height=4.65, stroke_color=color, stroke_width=2)
            h = label(heading, 24, color).move_to(box.get_top() + DOWN * 0.45)
            items = VGroup(*[label(method, 22) for method in methods]).arrange(DOWN, buff=0.45)
            items.next_to(h, DOWN, buff=0.55)
            groups.add(VGroup(box, h, items))
        groups.arrange(RIGHT, buff=0.28).shift(DOWN * 0.35)
        self.play(LaggedStart(*[FadeIn(g, shift=UP * 0.2) for g in groups], lag_ratio=0.2))
        self.wait(2)
