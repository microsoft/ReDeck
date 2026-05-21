"""Generate publication-quality charts from structured viz_data using matplotlib."""

import logging
import textwrap
from pathlib import Path

logger = logging.getLogger(__name__)


class ChartGenerator:
    """Generate presentation-style charts from viz_data dictionaries."""

    # Default theme colors matching slide design system
    DEFAULT_COLORS = [
        "#006699", "#e67e22", "#003366", "#0099cc",
        "#2c3e50", "#27ae60", "#8e44ad", "#c0392b",
    ]

    def generate_chart(
        self, viz_data: dict, output_path: Path,
        theme_colors: list[str] | None = None,
    ) -> Path | None:
        """Generate a chart PNG from structured viz_data.

        viz_data expected keys:
          - chart_type: str (column_clustered, bar_clustered, line, pie, doughnut)
          - title: str (optional)
          - categories: list[str]
          - series: list[dict] with keys: name, values
          - x_label, y_label: str (optional)

        Returns path to saved PNG or None on failure.
        """
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            logger.warning("matplotlib not available, skipping chart generation")
            return None

        chart_type = viz_data.get("chart_type", "column_clustered")
        categories = viz_data.get("categories", [])
        series_list = viz_data.get("series", [])
        title = viz_data.get("title", "")

        if not categories or not series_list:
            logger.warning("viz_data missing categories or series")
            return None

        colors = theme_colors or self.DEFAULT_COLORS

        try:
            plt.style.use("seaborn-v0_8-whitegrid")
        except Exception:
            pass

        fig, ax = plt.subplots(figsize=(8, 4.5), dpi=200)

        try:
            if chart_type == "flowchart":
                # Flowchart uses different data format — nodes/edges instead of categories/series
                plt.close(fig)
                return self._draw_flowchart(viz_data, output_path, colors)
            elif chart_type in ("column_clustered", "column"):
                self._draw_column(ax, categories, series_list, colors)
            elif chart_type in ("bar_clustered", "bar"):
                self._draw_bar(ax, categories, series_list, colors)
            elif chart_type == "line":
                self._draw_line(ax, categories, series_list, colors)
            elif chart_type in ("pie", "doughnut"):
                self._draw_pie(ax, categories, series_list, colors, chart_type == "doughnut")
            else:
                self._draw_column(ax, categories, series_list, colors)

            if title:
                ax.set_title(title, fontsize=14, fontweight="600", pad=12)

            x_label = viz_data.get("x_label", "")
            y_label = viz_data.get("y_label", "")
            if x_label:
                ax.set_xlabel(x_label, fontsize=11)
            if y_label:
                ax.set_ylabel(y_label, fontsize=11)

            fig.tight_layout()
            output_path = Path(output_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            fig.savefig(str(output_path), bbox_inches="tight", facecolor="white")
            plt.close(fig)
            logger.info(f"Chart saved: {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Chart generation failed: {e}")
            plt.close(fig)
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _wrap_label(text: str, max_chars: int = 22) -> str:
        """Wrap long labels onto multiple lines."""
        if len(text) <= max_chars:
            return text
        return "\n".join(textwrap.wrap(text, max_chars))

    @staticmethod
    def _smart_format(value: float) -> str:
        """Format a number smartly: use k/M suffix for large numbers, trim trailing zeros."""
        abs_v = abs(value)
        if abs_v >= 1_000_000:
            return f"{value / 1_000_000:.1f}M".rstrip("0").rstrip(".")
        if abs_v >= 10_000:
            return f"{value / 1_000:.1f}k".rstrip("0").rstrip(".")
        if abs_v >= 100:
            return f"{value:,.0f}"
        if abs_v >= 1:
            return f"{value:.2f}".rstrip("0").rstrip(".")
        return f"{value:.3f}".rstrip("0").rstrip(".")

    # ------------------------------------------------------------------
    # Column chart
    # ------------------------------------------------------------------

    def _draw_column(self, ax, categories, series_list, colors):
        import numpy as np
        x = np.arange(len(categories))
        n = len(series_list)
        width = 0.7 / max(n, 1)

        all_values = [v for s in series_list for v in s["values"]]
        max_val = max(all_values) if all_values else 1

        for i, s in enumerate(series_list):
            offset = (i - (n - 1) / 2) * width
            bars = ax.bar(
                x + offset, s["values"], width, label=s.get("name", ""),
                color=colors[i % len(colors)], edgecolor="white", linewidth=0.5,
            )
            # Data labels on top of bars
            for bar, val in zip(bars, s["values"]):
                label = self._smart_format(val)
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + max_val * 0.02,
                    label, ha="center", va="bottom", fontsize=8,
                    color="#333333",
                )

        # Y-axis headroom for labels
        ax.set_ylim(top=max_val * 1.15)

        # Wrap long category labels
        wrapped = [self._wrap_label(c) for c in categories]
        ax.set_xticks(x)
        ax.set_xticklabels(
            wrapped, fontsize=10,
            rotation=30 if len(categories) > 6 else 0,
            ha="right" if len(categories) > 6 else "center",
        )
        if n > 1:
            ax.legend(fontsize=9, framealpha=0.9)

    # ------------------------------------------------------------------
    # Bar chart (horizontal)
    # ------------------------------------------------------------------

    def _draw_bar(self, ax, categories, series_list, colors):
        import numpy as np
        y = np.arange(len(categories))
        n = len(series_list)
        # Adaptive height: thinner bars when many categories
        total_height = 0.7 if len(categories) <= 8 else 0.85
        height = total_height / max(n, 1)

        all_values = [v for s in series_list for v in s["values"]]
        max_val = max(all_values) if all_values else 1
        min_val = min(all_values) if all_values else 0

        for i, s in enumerate(series_list):
            offset = (i - (n - 1) / 2) * height
            bars = ax.barh(
                y + offset, s["values"], height, label=s.get("name", ""),
                color=colors[i % len(colors)], edgecolor="white", linewidth=0.5,
            )

            # Smart data label positioning
            for bar, val in zip(bars, s["values"]):
                label = self._smart_format(val)
                bar_width = bar.get_width()
                bar_frac = bar_width / max_val if max_val > 0 else 0

                if bar_frac > 0.85:
                    # Bar is very long: put label INSIDE, right-aligned, white text
                    ax.text(
                        bar_width - max_val * 0.02,
                        bar.get_y() + bar.get_height() / 2,
                        label, ha="right", va="center", fontsize=8,
                        color="white", fontweight="bold",
                    )
                else:
                    # Put label OUTSIDE, right of bar
                    ax.text(
                        bar_width + max_val * 0.02,
                        bar.get_y() + bar.get_height() / 2,
                        label, ha="left", va="center", fontsize=8,
                        color="#333333",
                    )

        # X-axis headroom for labels
        ax.set_xlim(right=max_val * 1.18)
        if min_val >= 0:
            ax.set_xlim(left=0)

        # Wrap long Y-axis labels
        wrapped = [self._wrap_label(c, max_chars=28) for c in categories]
        ax.set_yticks(y)
        ax.set_yticklabels(wrapped, fontsize=10)
        ax.invert_yaxis()
        if n > 1:
            ax.legend(fontsize=9, framealpha=0.9)

    # ------------------------------------------------------------------
    # Line chart
    # ------------------------------------------------------------------

    def _draw_line(self, ax, categories, series_list, colors):
        for i, s in enumerate(series_list):
            ax.plot(
                categories, s["values"], marker="o", markersize=5,
                color=colors[i % len(colors)], label=s.get("name", ""),
                linewidth=2,
            )

        # Rotate long x labels
        if len(categories) > 6 or any(len(str(c)) > 8 for c in categories):
            ax.tick_params(axis="x", rotation=30)
            for label in ax.get_xticklabels():
                label.set_ha("right")
        if len(series_list) > 1:
            ax.legend(fontsize=9, framealpha=0.9)

    # ------------------------------------------------------------------
    # Pie / Doughnut chart
    # ------------------------------------------------------------------

    def _draw_pie(self, ax, categories, series_list, colors, is_doughnut=False):
        values = series_list[0]["values"] if series_list else []
        wedge_colors = colors[:len(categories)]
        wedgeprops = (
            {"width": 0.4, "edgecolor": "white"}
            if is_doughnut
            else {"edgecolor": "white"}
        )
        ax.pie(
            values, labels=categories, colors=wedge_colors, autopct="%1.1f%%",
            startangle=90, wedgeprops=wedgeprops, textprops={"fontsize": 10},
        )
        ax.set_aspect("equal")

    # ------------------------------------------------------------------
    # Flowchart
    # ------------------------------------------------------------------

    def _draw_flowchart(
        self, viz_data: dict, output_path: Path, colors: list[str],
    ) -> Path | None:
        """Render a flowchart from nodes + edges to PNG.

        viz_data keys:
          - nodes: list[{id, label, type}]  type: rect|diamond|rounded|circle
          - edges: list[{from, to, label?}]
          - direction: "horizontal" | "vertical" (default horizontal)
          - title: str (optional)
        """
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import matplotlib.patches as mpatches
            from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
            import numpy as np
        except ImportError:
            return None

        nodes = viz_data.get("nodes", [])
        edges = viz_data.get("edges", [])
        direction = viz_data.get("direction", "horizontal")
        title = viz_data.get("title", "")

        if not nodes:
            logger.warning("Flowchart has no nodes")
            return None

        # Build node lookup
        node_map = {n["id"]: n for n in nodes}

        # Auto-layout: arrange nodes in a line or use topological order
        node_ids = [n["id"] for n in nodes]

        # Try topological sort for proper ordering
        ordered_ids = self._topo_sort(node_ids, edges)

        is_horizontal = direction == "horizontal"
        n = len(ordered_ids)

        # Calculate layout positions
        if is_horizontal:
            fig_w = max(2.5 * n, 6)
            fig_h = 3.0
            positions = {}
            for i, nid in enumerate(ordered_ids):
                positions[nid] = (1.2 + i * 2.2, 1.5)
        else:
            fig_w = 4.5
            fig_h = max(1.8 * n, 4)
            positions = {}
            for i, nid in enumerate(ordered_ids):
                positions[nid] = (2.25, fig_h - 0.8 - i * 1.6)

        fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=200)
        ax.set_xlim(0, fig_w)
        ax.set_ylim(0, fig_h)
        ax.axis("off")
        ax.set_aspect("equal")

        # Node dimensions
        node_w = 1.6
        node_h = 0.7

        # Draw edges first (under nodes)
        for edge in edges:
            fid, tid = str(edge.get("from", "")), str(edge.get("to", ""))
            if fid not in positions or tid not in positions:
                continue
            fx, fy = positions[fid]
            tx, ty = positions[tid]

            # Arrow start/end at node boundary
            if is_horizontal:
                sx, sy = fx + node_w / 2 + 0.05, fy
                ex, ey = tx - node_w / 2 - 0.05, ty
            else:
                sx, sy = fx, fy - node_h / 2 - 0.05
                ex, ey = tx, ty + node_h / 2 + 0.05

            arrow = FancyArrowPatch(
                (sx, sy), (ex, ey),
                arrowstyle="-|>",
                mutation_scale=15,
                color="#5871C4",
                linewidth=1.8,
                connectionstyle="arc3,rad=0",
            )
            ax.add_patch(arrow)

            # Edge label
            elabel = edge.get("label", "")
            if elabel:
                mx, my = (sx + ex) / 2, (sy + ey) / 2
                offset = 0.15 if is_horizontal else 0.0
                ax.text(
                    mx, my + offset, elabel, fontsize=8,
                    ha="center", va="bottom", color="#666666",
                    style="italic",
                )

        # Draw nodes
        primary_color = colors[0] if colors else "#006699"
        accent_color = colors[1] if len(colors) > 1 else "#e67e22"

        for i, nid in enumerate(ordered_ids):
            node = node_map[nid]
            x, y = positions[nid]
            ntype = node.get("type", "rect")
            label = node.get("label", nid)
            is_highlight = node.get("highlight", False)

            if ntype == "diamond":
                # Diamond shape
                hw, hh = node_w * 0.55, node_h * 0.7
                diamond = plt.Polygon(
                    [(x, y + hh), (x + hw, y), (x, y - hh), (x - hw, y)],
                    closed=True,
                    facecolor=accent_color if is_highlight else "#F0F4F8",
                    edgecolor=primary_color,
                    linewidth=1.5,
                )
                ax.add_patch(diamond)
                ax.text(
                    x, y, label, fontsize=9, ha="center", va="center",
                    fontweight="600", color="#1E2749",
                    wrap=True,
                )
            elif ntype == "circle":
                circle = plt.Circle(
                    (x, y), node_h * 0.5,
                    facecolor=accent_color if is_highlight else "#F0F4F8",
                    edgecolor=primary_color,
                    linewidth=1.5,
                )
                ax.add_patch(circle)
                ax.text(
                    x, y, label, fontsize=9, ha="center", va="center",
                    fontweight="600", color="#1E2749",
                )
            else:
                # rect or rounded
                box_style = "round,pad=0.15" if ntype == "rounded" else "square,pad=0.1"
                fc = accent_color if is_highlight else "#F0F4F8"
                box = FancyBboxPatch(
                    (x - node_w / 2, y - node_h / 2), node_w, node_h,
                    boxstyle=box_style,
                    facecolor=fc,
                    edgecolor=primary_color,
                    linewidth=1.5,
                )
                ax.add_patch(box)
                # Wrap long labels
                wrapped = self._wrap_label(label, max_chars=14)
                ax.text(
                    x, y, wrapped, fontsize=9, ha="center", va="center",
                    fontweight="600", color="#1E2749",
                )

        if title:
            ax.text(
                fig_w / 2, fig_h - 0.2, title, fontsize=13,
                ha="center", va="top", fontweight="bold", color="#1E2749",
            )

        fig.tight_layout(pad=0.3)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(output_path), bbox_inches="tight", facecolor="white")
        plt.close(fig)
        logger.info(f"Flowchart saved: {output_path}")
        return output_path

    @staticmethod
    def _topo_sort(node_ids: list[str], edges: list[dict]) -> list[str]:
        """Topological sort of nodes based on edges. Falls back to input order."""
        from collections import defaultdict, deque
        adj = defaultdict(list)
        in_deg = defaultdict(int)
        id_set = set(node_ids)
        for nid in node_ids:
            in_deg[nid] = 0
        for e in edges:
            f, t = str(e.get("from", "")), str(e.get("to", ""))
            if f in id_set and t in id_set:
                adj[f].append(t)
                in_deg[t] += 1
        queue = deque(nid for nid in node_ids if in_deg[nid] == 0)
        result = []
        while queue:
            n = queue.popleft()
            result.append(n)
            for nb in adj[n]:
                in_deg[nb] -= 1
                if in_deg[nb] == 0:
                    queue.append(nb)
        # Add any remaining (cycle or disconnected)
        for nid in node_ids:
            if nid not in result:
                result.append(nid)
        return result
