"""Auditable query-specific heuristics, never a substitute for manual screening."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

from .config import _read_yaml
from .exceptions import ConfigurationError
from .models import utc_now_iso
from .normalization import clean_markup


def normalized_text(text: str) -> str:
    return " ".join(re.findall(r"\w+", unicodedata.normalize("NFKC", clean_markup(text) or "").casefold()))


def load_rules(profile: str | Path) -> dict:
    path = Path(profile) / "relevance.yaml"
    if not path.exists():
        return {}
    rules = _read_yaml(path)
    if not isinstance(rules.get("sources"), list) or not isinstance(rules.get("queries"), dict):
        raise ConfigurationError("relevance.yaml requires sources and queries")
    for groups in rules["queries"].values():
        if not isinstance(groups, dict) or not groups:
            raise ConfigurationError("Each relevance query requires anchor groups")
        for terms in groups.values():
            if not isinstance(terms, list) or not terms or any(
                not isinstance(term, str) or not normalized_text(term) for term in terms
            ):
                raise ConfigurationError("Anchor groups require nonempty lists of terms")
    return rules


def evaluate(title: str, abstract: str | None, query_id: str, sources: list[str], rules: dict) -> dict:
    text = " " + normalized_text(title + " " + (abstract or "")) + " "
    groups = rules.get("queries", {}).get(query_id)
    if not groups:
        return {"decision": "review", "reason_codes": ["UNCONFIGURED_QUERY"], "matched": {}}
    if any(source not in rules["sources"] for source in sources):
        return {"decision": "include", "reason_codes": ["SOURCE_QUERY_ANCHORED"], "matched": {}}
    matched = {
        group: [term for term in terms if " " + normalized_text(term) + " " in text]
        for group, terms in groups.items()
    }
    reasons = [f"MISSING_{group.upper()}_ANCHOR" for group, terms in matched.items() if not terms]
    missing_abstract = not normalized_text(abstract or "")
    # A missing abstract is insufficient evidence for automatic exclusion.
    decision = "include" if not reasons else "review" if missing_abstract else "exclude"
    if missing_abstract:
        reasons.append("MISSING_ABSTRACT")
    return {"decision": decision, "reason_codes": reasons, "matched": matched}


def screen_run(store, *, run_id: str, study_id: str, profile_id: str, rules: dict) -> dict:
    if not rules:
        return {"enabled": False}
    version = hashlib.sha256(json.dumps({"engine": "lexical-anchors-v1", "rules": rules}, sort_keys=True).encode()).hexdigest()
    counts = {"include": 0, "exclude": 0, "review": 0}
    with store.connect() as con:
        run = con.execute("SELECT * FROM search_runs WHERE run_id = ?", (run_id,)).fetchone()
        if not run or (run["study_id"], run["profile_id"]) != (study_id, profile_id):
            raise ConfigurationError("run_id does not belong to the selected study/profile")
        rows = con.execute("""
            SELECT w.*, d.query_id, GROUP_CONCAT(DISTINCT d.source_name) AS sources
            FROM discoveries d JOIN works w ON w.work_id = d.work_id
            WHERE d.run_id = ? AND d.method = 'database'
            GROUP BY w.work_id, d.query_id
            ORDER BY w.work_id, d.query_id
        """, (run_id,)).fetchall()
        outcomes: dict[str, list[dict]] = {}
        for row in rows:
            result = evaluate(row["title"], row["abstract"], row["query_id"], row["sources"].split(","), rules)
            evidence = {"title": row["title"], "abstract": row["abstract"], "sources": row["sources"], **result}
            outcomes.setdefault(row["work_id"], []).append({"query_id": row["query_id"], **result})
            con.execute("""
                INSERT INTO automatic_relevance VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, work_id, query_id, rule_version) DO UPDATE SET
                decision=excluded.decision, details_json=excluded.details_json,
                assessed_at=excluded.assessed_at
            """, (run_id, row["work_id"], row["query_id"], version, study_id, profile_id,
                  result["decision"], json.dumps({"evidence": evidence, "rules": rules}), utc_now_iso()))
        for work_id, results in outcomes.items():
            decisions = {r["decision"] for r in results}
            decision = "include" if "include" in decisions else "review" if "review" in decisions else "exclude"
            counts[decision] += 1
            con.execute("""
                INSERT INTO screening_decisions(work_id, stage, decision, reason_code, note, reviewer_id, decided_at)
                VALUES (?, 'automatic_relevance', ?, ?, ?, ?, ?)
                ON CONFLICT(work_id, stage, reviewer_id) DO UPDATE SET
                decision=excluded.decision, reason_code=excluded.reason_code,
                note=excluded.note, decided_at=excluded.decided_at
            """, (work_id, decision, "ANCHORS_PASSED" if decision == "include" else "QUERY_ANCHORS_INCOMPLETE",
                  json.dumps(results), f"system:{study_id}:{profile_id}:{run_id}:{version}", utc_now_iso()))
    return {"enabled": True, "run_id": run_id, "rule_version": version,
            "works_assessed": len(outcomes), "query_assessments": len(rows), **counts}

