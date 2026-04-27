"""Sequence formatting and IUPAC-aware search."""

from __future__ import annotations

from dataclasses import dataclass

COMPLEMENT = {
    "A": "T", "T": "A", "U": "A", "C": "G", "G": "C",
    "R": "Y", "Y": "R", "S": "S", "W": "W",
    "K": "M", "M": "K", "B": "V", "V": "B",
    "D": "H", "H": "D", "N": "N",
}

IUPAC_BASES = {
    "A": "A", "C": "C", "G": "G", "T": "T",
    "R": "AG", "Y": "CT", "S": "GC", "W": "AT", "K": "GT", "M": "AC",
    "B": "CGT", "D": "AGT", "H": "ACT", "V": "ACG",
    "N": "ACGT",
}

AMBIGUITY_CODES = set("RYSWKMBDHVN")


def reverse_complement(seq: str) -> str:
    return "".join(COMPLEMENT.get(c, c) for c in reversed(seq))


def format_with_codon_spacing(seq: str) -> str:
    return " ".join(seq[i : i + 3] for i in range(0, len(seq), 3))


def format_sequence_display(
    seq: str, reverse_complement_view: bool, codon_spacing: bool
) -> str:
    s = reverse_complement(seq) if reverse_complement_view else seq
    if codon_spacing:
        s = format_with_codon_spacing(s)
    return s


@dataclass(slots=True, frozen=True)
class SearchMatch:
    start: int  # 0-indexed inclusive
    end: int  # 0-indexed exclusive
    direction: str  # "sense" | "antisense"


def _matches_at(template: str, query: str, start: int) -> bool:
    for j, qc in enumerate(query):
        bases = IUPAC_BASES.get(qc)
        if bases is None or template[start + j] not in bases:
            return False
    return True


def _find_matches(
    template: str, query: str, direction: str, out: list[SearchMatch]
) -> None:
    t_len = len(template)
    q_len = len(query)
    for i in range(t_len - q_len + 1):
        if _matches_at(template, query, i):
            out.append(SearchMatch(start=i, end=i + q_len, direction=direction))


def search_template(template: str, raw_query: str) -> list[SearchMatch]:
    query = "".join(raw_query.upper().split())
    if not query or len(query) > len(template):
        return []
    if not all(c in IUPAC_BASES for c in query):
        return []

    matches: list[SearchMatch] = []
    _find_matches(template, query, "sense", matches)

    rc = reverse_complement(query)
    if rc != query:
        _find_matches(template, rc, "antisense", matches)

    matches.sort(key=lambda m: (m.start, m.direction))
    return matches
