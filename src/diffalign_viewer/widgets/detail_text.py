"""Plain-text rendering of the position-detail panel.

Provides a copy-pastable, monospace text view of everything the
:class:`~.detail.DetailPanel` shows for a single template position — the
metadata, the template oligo, the variants table and the exclusivity
breakdown. The same reverse-complement / codon-spacing display options that
are active in the panel are applied so the text matches what is on screen.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..models import AnalysisParams, PositionDetail
from ..sequence import format_sequence_display


def _format_table(
    rows: Sequence[Sequence[str]], align_right: set[int]
) -> list[str]:
    """Render ``rows`` (first row is the header) as aligned, monospace columns.

    Columns whose index is in ``align_right`` are right-justified; the rest are
    left-justified. A dashed rule is inserted under the header row.
    """
    if not rows:
        return []
    n_cols = max(len(r) for r in rows)
    widths = [0] * n_cols
    for r in rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(cell))

    out: list[str] = []
    for idx, r in enumerate(rows):
        cells = []
        for i in range(n_cols):
            cell = r[i] if i < len(r) else ""
            cells.append(cell.rjust(widths[i]) if i in align_right else cell.ljust(widths[i]))
        out.append("  ".join(cells).rstrip())
        if idx == 0:
            out.append("  ".join("-" * widths[i] for i in range(n_cols)).rstrip())
    return out


def build_detail_text(
    detail: PositionDetail,
    length: int,
    params: AnalysisParams | None,
    template_sequence: str,
    reverse_complement: bool,
    codon_spacing: bool,
) -> str:
    """Build the full plain-text representation of one position's details."""
    lines: list[str] = []
    header = f"Position {detail.position + 1} ({length} bp)"
    lines.append(header)
    lines.append("=" * len(header))
    lines.append("")

    if detail.skipped:
        reason = detail.skip_reason or "skipped"
        lines.append(f"Skipped: {reason}")
        return "\n".join(lines) + "\n"

    threshold_pct = params.coverage_threshold if params is not None else 90.0
    lines.append(f"Total references: {detail.total_sequences}")
    lines.append(f"Matched: {detail.sequences_analyzed}")
    if detail.no_match_count > 0:
        nm_pct = (
            (detail.no_match_count / detail.total_sequences) * 100.0
            if detail.total_sequences
            else 0.0
        )
        lines.append(f"No match: {detail.no_match_count} ({nm_pct:.1f}%)")
    lines.append(
        f"Variants needed for {threshold_pct:g}% coverage: "
        f"{detail.variants_for_threshold}"
    )
    lines.append(f"Coverage at threshold: {detail.coverage_at_threshold:.1f}%")

    display_notes = []
    if reverse_complement:
        display_notes.append("reverse complement")
    if codon_spacing:
        display_notes.append("codon spacing")
    if display_notes:
        lines.append(f"Display: {', '.join(display_notes)}")

    if template_sequence and detail.position + length <= len(template_sequence):
        template_oligo = template_sequence[detail.position : detail.position + length]
        lines.append(
            "Template oligo: "
            + format_sequence_display(template_oligo, reverse_complement, codon_spacing)
        )

    lines.append("")
    lines.append("VARIANTS")
    var_rows: list[tuple[str, str, str, str, str]] = [
        ("#", "Sequence", "Count", "%", "Cumulative")
    ]
    cumulative = 0.0
    for i, v in enumerate(detail.variants):
        cumulative += v.percentage
        var_rows.append(
            (
                str(i + 1),
                format_sequence_display(v.sequence, reverse_complement, codon_spacing),
                str(v.count),
                f"{v.percentage:.1f}%",
                f"{cumulative:.1f}%",
            )
        )
    if detail.no_match_count > 0:
        nm_pct = (
            (detail.no_match_count / detail.total_sequences) * 100.0
            if detail.total_sequences
            else 0.0
        )
        var_rows.append(
            ("", "(no match)", str(detail.no_match_count), f"{nm_pct:.1f}%", "")
        )
    lines.extend(_format_table(var_rows, align_right={0, 2, 3, 4}))

    if detail.exclusivity is not None:
        excl = detail.exclusivity
        lines.append("")
        lines.append("EXCLUSIVITY")
        lines.append(f"Total: {excl.total_sequences}")
        if excl.min_mismatches is None:
            lines.append("All exclusivity sequences: no match (fully specific)")
        else:
            lines.append(f"No match: {excl.no_match_count}")
            lines.append(f"Min mismatches: {excl.min_mismatches}")
        lines.append("")
        excl_rows: list[tuple[str, str, str]] = [("Mismatches", "Count", "Example")]
        for bucket in excl.mismatch_histogram:
            mm = "no match" if bucket.is_no_match else str(bucket.mismatches)
            excl_rows.append((mm, str(bucket.count), bucket.example_name))
        lines.extend(_format_table(excl_rows, align_right={0, 1}))

    return "\n".join(lines).rstrip("\n") + "\n"


class PositionDetailTextDialog(QDialog):
    """A read-only, copy-pastable monospace view of one position's details."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Position details — text")
        self.resize(660, 580)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self._edit = QPlainTextEdit()
        self._edit.setReadOnly(True)
        self._edit.setPlainText(text)
        self._edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        mono = QFont("Cascadia Mono")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(10)
        self._edit.setFont(mono)
        layout.addWidget(self._edit, 1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        copy_button = QPushButton("Copy to clipboard")
        copy_button.clicked.connect(self._copy_to_clipboard)
        button_row.addWidget(copy_button)
        close_button = QPushButton("Close")
        close_button.setProperty("primary", "true")
        close_button.clicked.connect(self.accept)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

    def _copy_to_clipboard(self) -> None:
        QApplication.clipboard().setText(self._edit.toPlainText())
