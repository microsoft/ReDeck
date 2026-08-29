"""Generate publication-quality charts from structured viz_data."""

import logging
import textwrap
from pathlib import Path

logger = logging.getLogger(__name__)


class ChartGenerator:
    """Generate academic-style charts from viz_data dictionaries."""

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
            logger.warning("matplotlib not available, using Pillow chart fallback")
            return self._generate_chart_pillow(viz_data, output_path, theme_colors)

        chart_type = viz_data.get("chart_type", "column_clustered")
        categories = viz_data.get("categories", [])
        series_list = viz_data.get("series", [])
        title = viz_data.get("title", "")

        # Charts with their own data format bypass the categories/series check
        if chart_type in ("heatmap", "flowchart"):
            colors = theme_colors or self.DEFAULT_COLORS
            if chart_type == "heatmap":
                return self._draw_heatmap(viz_data, output_path, colors)
            else:
                return self._draw_flowchart(viz_data, output_path, colors)

        # Scatter can use either points[] or series[] format
        if chart_type == "scatter" and not series_list and viz_data.get("points"):
            pass  # allow through — _draw_scatter handles points format
        elif not categories or not series_list:
            logger.warning("viz_data missing categories or series")
            return None

        colors = theme_colors or self.DEFAULT_COLORS

        try:
            plt.style.use("seaborn-v0_8-whitegrid")
        except Exception:
            pass

        fig, ax = plt.subplots(figsize=(8, 4.5), dpi=200)

        try:
            if chart_type == "heatmap":
                # Already handled above — should not reach here
                plt.close(fig)
                return self._draw_heatmap(viz_data, output_path, colors)
            elif chart_type == "flowchart":
                plt.close(fig)
                return self._draw_flowchart(viz_data, output_path, colors)
            elif chart_type == "radar":
                plt.close(fig)
                return self._draw_radar(viz_data, output_path, colors)
            elif chart_type == "scatter":
                self._draw_scatter(ax, viz_data, colors)
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

    def _generate_chart_pillow(
        self,
        viz_data: dict,
        output_path: Path,
        theme_colors: list[str] | None = None,
    ) -> Path | None:
        """Small dependency-free fallback for basic bar/column/line charts."""
        try:
            from PIL import Image, ImageColor, ImageDraw, ImageFont
        except ImportError:
            logger.warning("Pillow not available, cannot generate fallback chart")
            return None

        categories = [str(c) for c in viz_data.get("categories", [])]
        series_list = viz_data.get("series", [])
        if not categories or not series_list:
            logger.warning("fallback chart missing categories or series")
            return None

        try:
            parsed_series = []
            for series in series_list:
                values = [float(v) for v in series.get("values", [])]
                if len(values) != len(categories):
                    return None
                parsed_series.append({"name": str(series.get("name", "")), "values": values})
        except (TypeError, ValueError):
            logger.warning("fallback chart has non-numeric values")
            return None

        colors = theme_colors or self.DEFAULT_COLORS

        def color_at(index: int) -> tuple[int, int, int]:
            try:
                return ImageColor.getcolor(colors[index % len(colors)], "RGB")
            except Exception:
                return ImageColor.getcolor(self.DEFAULT_COLORS[index % len(self.DEFAULT_COLORS)], "RGB")

        width, height = 1600, 900
        margin_l, margin_t, margin_r, margin_b = 210, 100, 90, 150
        plot_w = width - margin_l - margin_r
        plot_h = height - margin_t - margin_b
        img = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(img)
        font = ImageFont.load_default()
        title_font = ImageFont.load_default()

        title = str(viz_data.get("title", "")).strip()
        if title:
            draw.text((margin_l, 34), title[:120], fill="#222222", font=title_font)

        all_values = [v for series in parsed_series for v in series["values"]]
        min_val = min(0.0, min(all_values))
        max_val = max(0.0, max(all_values))
        if max_val == min_val:
            max_val = min_val + 1.0

        def x_for(value: float) -> int:
            return int(margin_l + (value - min_val) / (max_val - min_val) * plot_w)

        def y_for(value: float) -> int:
            return int(margin_t + plot_h - (value - min_val) / (max_val - min_val) * plot_h)

        axis = "#263238"
        grid = "#e3e8ee"
        text = "#263238"
        chart_type = str(viz_data.get("chart_type", "column_clustered")).lower()

        for i in range(6):
            frac = i / 5
            y = int(margin_t + plot_h * (1 - frac))
            value = min_val + frac * (max_val - min_val)
            draw.line([(margin_l, y), (margin_l + plot_w, y)], fill=grid, width=1)
            draw.text((20, y - 7), self._smart_format(value), fill=text, font=font)
        draw.line([(margin_l, margin_t), (margin_l, margin_t + plot_h)], fill=axis, width=2)
        draw.line([(margin_l, margin_t + plot_h), (margin_l + plot_w, margin_t + plot_h)], fill=axis, width=2)

        if chart_type in {"bar", "bar_clustered"}:
            group_h = plot_h / max(1, len(categories))
            bar_h = max(8, min(42, group_h * 0.68 / max(1, len(parsed_series))))
            zero_x = x_for(0)
            for cat_idx, category in enumerate(categories):
                group_y = margin_t + cat_idx * group_h
                draw.text((12, int(group_y + group_h / 2 - 7)), self._wrap_label(category, 24), fill=text, font=font)
                for series_idx, series in enumerate(parsed_series):
                    value = series["values"][cat_idx]
                    y = int(group_y + group_h * 0.16 + series_idx * (bar_h + 4))
                    x0, x1 = sorted((zero_x, x_for(value)))
                    draw.rectangle([x0, y, x1, int(y + bar_h)], fill=color_at(series_idx))
                    draw.text((x1 + 8, y - 1), self._smart_format(value), fill=text, font=font)
        elif chart_type == "line":
            step = plot_w / max(1, len(categories) - 1)
            for series_idx, series in enumerate(parsed_series):
                points = [
                    (int(margin_l + cat_idx * step), y_for(value))
                    for cat_idx, value in enumerate(series["values"])
                ]
                if len(points) >= 2:
                    draw.line(points, fill=color_at(series_idx), width=4)
                for x, y in points:
                    draw.ellipse([x - 5, y - 5, x + 5, y + 5], fill=color_at(series_idx), outline="white")
            for cat_idx, category in enumerate(categories):
                x = int(margin_l + cat_idx * step)
                draw.text((x - 28, margin_t + plot_h + 18), self._wrap_label(category, 12), fill=text, font=font)
        else:
            group_w = plot_w / max(1, len(categories))
            bar_w = max(10, min(54, group_w * 0.68 / max(1, len(parsed_series))))
            zero_y = y_for(0)
            for cat_idx, category in enumerate(categories):
                group_x = margin_l + cat_idx * group_w
                for series_idx, series in enumerate(parsed_series):
                    value = series["values"][cat_idx]
                    x = int(group_x + group_w * 0.16 + series_idx * (bar_w + 4))
                    y = y_for(value)
                    y0, y1 = sorted((zero_y, y))
                    draw.rectangle([x, y0, int(x + bar_w), y1], fill=color_at(series_idx))
                    draw.text((x, min(y0, y1) - 16), self._smart_format(value), fill=text, font=font)
                draw.text((int(group_x + 4), margin_t + plot_h + 18), self._wrap_label(category, 12), fill=text, font=font)

        legend_x = margin_l
        legend_y = height - 48
        for idx, series in enumerate(parsed_series[:6]):
            draw.rectangle([legend_x, legend_y, legend_x + 18, legend_y + 18], fill=color_at(idx))
            draw.text((legend_x + 26, legend_y + 2), series["name"][:28], fill=text, font=font)
            legend_x += 190

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(output_path)
        logger.info("Fallback chart saved: %s", output_path)
        return output_path

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
    # Heatmap
    # ------------------------------------------------------------------

    def _draw_heatmap(
        self, viz_data: dict, output_path: Path, colors: list[str],
    ) -> Path | None:
        """Render a heatmap (confusion matrix, attention matrix, correlation).

        viz_data keys:
          - matrix: list[list[float]]
          - row_labels: list[str]
          - col_labels: list[str]
          - colormap: str (default "Blues")
          - title: str (optional)
          - annotate: bool (default True) — show values in cells
          - fmt: str (default ".2f") — number format for annotations
        """
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import numpy as np
        except ImportError:
            return None

        matrix = viz_data.get("matrix", [])
        if not matrix:
            logger.warning("Heatmap has no matrix data")
            return None

        data = np.array(matrix, dtype=float)
        row_labels = viz_data.get("row_labels", [f"R{i}" for i in range(data.shape[0])])
        col_labels = viz_data.get("col_labels", [f"C{i}" for i in range(data.shape[1])])
        colormap = viz_data.get("colormap", "Blues")
        title = viz_data.get("title", "")
        annotate = viz_data.get("annotate", True)
        fmt = viz_data.get("fmt", ".2f")

        # Dynamic figure size based on matrix dimensions
        n_rows, n_cols = data.shape
        fig_w = max(6, min(12, 1.2 * n_cols + 2))
        fig_h = max(4, min(9, 0.8 * n_rows + 2))
        fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=200)

        im = ax.imshow(data, cmap=colormap, aspect="auto")
        fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02)

        # Tick labels
        ax.set_xticks(np.arange(n_cols))
        ax.set_yticks(np.arange(n_rows))
        wrapped_cols = [self._wrap_label(str(c), max_chars=14) for c in col_labels]
        wrapped_rows = [self._wrap_label(str(r), max_chars=18) for r in row_labels]
        ax.set_xticklabels(wrapped_cols, fontsize=9, rotation=45, ha="right")
        ax.set_yticklabels(wrapped_rows, fontsize=9)

        # Cell annotations
        if annotate and n_rows * n_cols <= 200:
            thresh = (data.max() + data.min()) / 2
            for i in range(n_rows):
                for j in range(n_cols):
                    val = data[i, j]
                    color = "white" if val > thresh else "black"
                    ax.text(j, i, format(val, fmt), ha="center", va="center",
                            fontsize=8, color=color)

        if title:
            ax.set_title(title, fontsize=14, fontweight="600", pad=12)

        fig.tight_layout()
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(output_path), bbox_inches="tight", facecolor="white")
        plt.close(fig)
        logger.info(f"Heatmap saved: {output_path}")
        return output_path

    # ------------------------------------------------------------------
    # Radar chart
    # ------------------------------------------------------------------

    def _draw_radar(
        self, viz_data: dict, output_path: Path, colors: list[str],
    ) -> Path | None:
        """Render a radar/spider chart for multi-dimensional comparison.

        viz_data keys:
          - categories: list[str] — dimension names
          - series: list[{name, values}] — one polygon per series
          - title: str (optional)
        """
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import numpy as np
        except ImportError:
            return None

        categories = viz_data.get("categories", [])
        series_list = viz_data.get("series", [])
        title = viz_data.get("title", "")

        if not categories or not series_list:
            logger.warning("Radar chart missing categories or series")
            return None

        n = len(categories)
        angles = np.linspace(0, 2 * np.pi, n, endpoint=False).tolist()
        angles += angles[:1]  # close the polygon

        fig, ax = plt.subplots(figsize=(6, 6), dpi=200, subplot_kw=dict(polar=True))

        for i, s in enumerate(series_list):
            values = s["values"]
            values_closed = values + values[:1]
            color = colors[i % len(colors)]
            ax.fill(angles, values_closed, alpha=0.15, color=color)
            ax.plot(angles, values_closed, "o-", linewidth=2, markersize=5,
                    color=color, label=s.get("name", ""))

        ax.set_xticks(angles[:-1])
        ax.set_xticklabels([self._wrap_label(c, 12) for c in categories], fontsize=10)
        ax.set_yticklabels([])  # hide radial tick labels for cleanliness

        if len(series_list) > 1:
            ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1), fontsize=9, framealpha=0.9)

        if title:
            ax.set_title(title, fontsize=14, fontweight="600", pad=20)

        fig.tight_layout()
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(str(output_path), bbox_inches="tight", facecolor="white")
        plt.close(fig)
        logger.info(f"Radar chart saved: {output_path}")
        return output_path

    # ------------------------------------------------------------------
    # Scatter chart
    # ------------------------------------------------------------------

    def _draw_scatter(self, ax, viz_data: dict, colors: list[str]):
        """Render a scatter plot (accuracy vs efficiency, etc.).

        viz_data keys:
          - points: list[{x, y, label, highlight?, size?}]
          - x_label, y_label: str
          - title: str (optional)
          - series: list[{name, values_x, values_y}] (alt format for grouped)
        """
        points = viz_data.get("points", [])
        series_list = viz_data.get("series", [])

        if series_list:
            # Grouped scatter: each series is a set of points
            for i, s in enumerate(series_list):
                color = colors[i % len(colors)]
                xs = s.get("values_x", [])
                ys = s.get("values_y", [])
                ax.scatter(xs, ys, s=60, color=color, label=s.get("name", ""),
                           edgecolors="white", linewidth=0.5, zorder=3)
            if len(series_list) > 1:
                ax.legend(fontsize=9, framealpha=0.9)
        elif points:
            xs = [p["x"] for p in points]
            ys = [p["y"] for p in points]
            highlights = [p.get("highlight", False) for p in points]
            sizes = [p.get("size", 60) for p in points]
            point_colors = [colors[1] if h else colors[0] for h in highlights]

            ax.scatter(xs, ys, s=sizes, c=point_colors,
                       edgecolors="white", linewidth=0.5, zorder=3)

            # Label points
            for p in points:
                label = p.get("label", "")
                if label:
                    ax.annotate(label, (p["x"], p["y"]),
                                textcoords="offset points", xytext=(6, 6),
                                fontsize=8, color="#333333")

        ax.grid(True, alpha=0.3)

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
