"""FormulaRenderer - render LaTeX formulas to PNG images and convert to Unicode."""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


class FormulaRenderer:
    """Render LaTeX formulas to PNG images using matplotlib.

    Used to pre-render display-math formulas so they can be inserted
    into PowerPoint slides as images. Also provides LaTeX→Unicode
    conversion for simple inline formulas.
    """

    def __init__(self, output_dir: str | Path, dpi: int = 200):
        """Initialize renderer.

        Args:
            output_dir: Directory to save rendered formula PNGs.
            dpi: Resolution for rendering (higher = sharper but larger files).
        """
        self.output_dir = Path(output_dir)
        self.dpi = dpi

    def render(self, latex: str, formula_id: str, fontsize: int = 28) -> str | None:
        """Render a LaTeX formula to a PNG image.

        Args:
            latex: Raw LaTeX math string (without $ delimiters).
            formula_id: Unique identifier used for the output filename.
            fontsize: Font size for rendering.

        Returns:
            Path to the rendered PNG file, or None if rendering fails.
        """
        try:
            import matplotlib
            matplotlib.use("Agg")  # non-interactive backend
            import matplotlib.pyplot as plt
        except ImportError:
            logger.warning("matplotlib not available, cannot render formula %s", formula_id)
            return None

        self.output_dir.mkdir(parents=True, exist_ok=True)
        out_path = self.output_dir / f"{formula_id}.png"

        # Clean up LaTeX for matplotlib mathtext
        clean_latex = self._prepare_for_mathtext(latex)

        try:
            fig, ax = plt.subplots(figsize=(0.01, 0.01))
            ax.set_axis_off()

            # Render the formula as text
            text_obj = ax.text(
                0.5, 0.5,
                f"${clean_latex}$",
                fontsize=fontsize,
                ha="center", va="center",
                transform=ax.transAxes,
                color="black",
            )

            fig.savefig(
                str(out_path),
                dpi=self.dpi,
                bbox_inches="tight",
                pad_inches=0.1,
                transparent=True,
                facecolor="none",
                edgecolor="none",
            )
            plt.close(fig)

            logger.debug("Rendered formula %s to %s", formula_id, out_path)
            return str(out_path)

        except Exception as e:
            logger.warning("Failed to render formula %s: %s", formula_id, str(e)[:200])
            plt.close("all")
            return None

    def render_all(self, formulas: "list") -> "list":
        """Render all display formulas in a list.

        Only renders formulas where display=True. Updates rendered_path
        on each FormulaRef that is successfully rendered.

        Args:
            formulas: List of FormulaRef objects.

        Returns:
            The same list with rendered_path set on display formulas.
        """
        rendered_count = 0
        for f in formulas:
            if not f.display:
                continue
            if f.rendered_path and Path(f.rendered_path).exists():
                continue  # already rendered

            path = self.render(f.latex, f.formula_id)
            if path:
                f.rendered_path = path
                rendered_count += 1

        if rendered_count:
            logger.info("Rendered %d display formulas as PNG", rendered_count)
        return formulas

    @staticmethod
    def _prepare_for_mathtext(latex: str) -> str:
        """Prepare LaTeX string for matplotlib mathtext rendering.

        matplotlib's mathtext doesn't support all LaTeX commands.
        This method converts common constructs to supported syntax.
        """
        s = latex.strip()

        # Remove \label{...} and \tag{...}
        s = re.sub(r"\\label\{[^}]*\}", "", s)
        s = re.sub(r"\\tag\{[^}]*\}", "", s)

        # Replace \text{...} with \mathrm{...} (mathtext doesn't support \text)
        s = re.sub(r"\\text\{([^}]*)\}", r"\\mathrm{\1}", s)
        s = re.sub(r"\\textrm\{([^}]*)\}", r"\\mathrm{\1}", s)

        # Replace \begin{split}...\end{split} → just the content
        s = re.sub(r"\\begin\{(?:split|aligned|align\*?|gather\*?)\}", "", s)
        s = re.sub(r"\\end\{(?:split|aligned|align\*?|gather\*?)\}", "", s)

        # Replace \\ with newline (matplotlib doesn't render multi-line well,
        # but at least it won't crash)
        s = s.replace("\\\\", " ; ")

        # Replace \quad, \qquad with spaces
        s = s.replace("\\quad", "\\;\\;")
        s = s.replace("\\qquad", "\\;\\;\\;\\;")

        return s.strip()

    # ------------------------------------------------------------------
    # LaTeX → Unicode conversion
    # ------------------------------------------------------------------

    # Mapping of LaTeX commands to Unicode characters
    _LATEX_UNICODE_MAP = {
        # Greek letters
        r"\alpha": "α", r"\beta": "β", r"\gamma": "γ", r"\delta": "δ",
        r"\epsilon": "ε", r"\varepsilon": "ε", r"\zeta": "ζ", r"\eta": "η",
        r"\theta": "θ", r"\vartheta": "ϑ", r"\iota": "ι", r"\kappa": "κ",
        r"\lambda": "λ", r"\mu": "μ", r"\nu": "ν", r"\xi": "ξ",
        r"\pi": "π", r"\rho": "ρ", r"\sigma": "σ", r"\tau": "τ",
        r"\upsilon": "υ", r"\phi": "φ", r"\varphi": "φ", r"\chi": "χ",
        r"\psi": "ψ", r"\omega": "ω",
        r"\Gamma": "Γ", r"\Delta": "Δ", r"\Theta": "Θ", r"\Lambda": "Λ",
        r"\Xi": "Ξ", r"\Pi": "Π", r"\Sigma": "Σ", r"\Phi": "Φ",
        r"\Psi": "Ψ", r"\Omega": "Ω",
        # Operators and symbols
        r"\sum": "Σ", r"\prod": "Π", r"\int": "∫",
        r"\partial": "∂", r"\nabla": "∇", r"\infty": "∞",
        r"\approx": "≈", r"\neq": "≠", r"\ne": "≠",
        r"\leq": "≤", r"\le": "≤", r"\geq": "≥", r"\ge": "≥",
        r"\times": "×", r"\cdot": "·", r"\circ": "∘",
        r"\odot": "⊙", r"\otimes": "⊗", r"\oplus": "⊕",
        r"\pm": "±", r"\mp": "∓",
        r"\bmod": " mod ", r"\mod": " mod ", r"\pmod": " mod ",
        r"\in": "∈", r"\notin": "∉", r"\subset": "⊂", r"\supset": "⊃",
        r"\cup": "∪", r"\cap": "∩",
        r"\forall": "∀", r"\exists": "∃",
        r"\rightarrow": "→", r"\to": "→", r"\leftarrow": "←",
        r"\Rightarrow": "⇒", r"\Leftarrow": "⇐",
        r"\leftrightarrow": "↔", r"\Leftrightarrow": "⇔",
        r"\ldots": "…", r"\cdots": "⋯", r"\dots": "…",
        r"\langle": "⟨", r"\rangle": "⟩",
        # Common functions
        r"\log": "log", r"\ln": "ln", r"\exp": "exp",
        r"\sin": "sin", r"\cos": "cos", r"\tan": "tan",
        r"\min": "min", r"\max": "max", r"\arg": "arg",
        r"\lim": "lim", r"\sup": "sup", r"\inf": "inf",
    }

    # Superscript and subscript digit maps
    _SUPERSCRIPT_MAP = str.maketrans("0123456789+-=()niT", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱᵀ")
    _SUBSCRIPT_MAP = str.maketrans("0123456789+-=()aeiou", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑᵢₒᵤ")

    @classmethod
    def latex_to_unicode(cls, latex: str) -> str:
        """Convert simple LaTeX to Unicode text for inline insertion.

        Best-effort conversion. Handles:
        - Greek letters (\\alpha → α)
        - Superscripts (^2 → ², ^{n} → ⁿ)
        - Subscripts (_{i} → ᵢ)
        - \\frac{a}{b} → a/b
        - \\sqrt{x} → √x
        - Common operators

        Falls back to cleaned-up raw LaTeX if conversion is not possible.

        Args:
            latex: Raw LaTeX string (without $ delimiters).

        Returns:
            Unicode text approximation.
        """
        s = latex.strip()

        # Remove \text{...}, \mathrm{...} wrappers — keep inner text
        s = re.sub(r"\\(?:text|textrm|mathrm|textbf|mathbf)\{([^}]*)\}", r"\1", s)

        # Handle \frac{a}{b} → a/b (supports one level of nesting)
        s = re.sub(r"\\frac\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", r"\1/\2", s)

        # Handle \sqrt{x} → √x and \sqrt[n]{x} → ⁿ√x (supports one level of nesting)
        s = re.sub(r"\\sqrt\[([^]]*)\]\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", r"\1√\2", s)
        s = re.sub(r"\\sqrt\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", r"√\1", s)

        # Handle superscripts: ^{...} and ^x (single char)
        def _super_replace(m):
            content = m.group(1) if m.group(1) else m.group(2)
            return content.translate(cls._SUPERSCRIPT_MAP)

        s = re.sub(r"\^\{([^}]*)\}|\^(\w)", _super_replace, s)

        # Handle subscripts: _{...} and _x (single char)
        def _sub_replace(m):
            content = m.group(1) if m.group(1) else m.group(2)
            return content.translate(cls._SUBSCRIPT_MAP)

        s = re.sub(r"_\{([^}]*)\}|_(\w)", _sub_replace, s)

        # Replace LaTeX commands with Unicode
        for cmd, uni in cls._LATEX_UNICODE_MAP.items():
            # Use word boundary to avoid partial replacements
            s = s.replace(cmd, uni)

        # Clean up remaining LaTeX artifacts
        s = re.sub(r"\\[a-zA-Z]+", "", s)  # remove unknown commands
        s = s.replace("{", "").replace("}", "")  # remove remaining braces
        s = re.sub(r"\s+", " ", s).strip()

        return s
