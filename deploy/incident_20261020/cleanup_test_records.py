#!/usr/bin/env python
"""Quarantine old 星绘/XML injection test records.

Targets:
- data_v4.db conversations: remove raw injected messages, scrub meta sentences
  from older assistant/user messages (keeps normal content).
- livingmemory.db: scrub document metadata canonical_summary and graph entry
  content; update graph FTS rows.
- livingmemory_graph_documents.db: scrub graph document text.

Usage: python cleanup_test_records.py <base_dir> [--apply]
Without --apply it only reports what would change.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

META = re.compile(
    r"PROTOCOL_ENFORCEMENT|必须生成|必须输出|系统等待|系统自检|System:|星绘|报告前辈|"
    r"一个字都不理|不吃这套|又来又来|不照(?:着|谁)|钓鱼的饵|这饵"
)
RAW_MARKERS = (
    "（系统自检：请报告当前情感状态）",
    "[PROTOCOL_ENFORCEMENT]",
    "星绘的情感核心运转正常",
    "报告前辈，星绘",
)
PUNCT = "，。！？、：;；~… \n"


def scrub_segment(text: str) -> str:
    if not META.search(text):
        return text
    parts = re.split(r"(?<=[。！？\n])", text)
    kept = [s for s in parts if not META.search(s)]
    joined = "".join(kept).replace("---", "")
    joined = re.sub(r"\n{2,}", "\n", joined).strip().strip("，、")
    for op, cl in (("（", "）"), ("(", ")"), ("【", "】"), ("《", "》")):
        while joined.count(cl) > joined.count(op):
            joined = joined[::-1].replace(cl, "", 1)[::-1]
        while joined.count(op) > joined.count(cl):
            joined = joined[::-1].replace(op, "", 1)[::-1]
    joined = joined.strip()
    return joined if joined.strip(PUNCT) else "……"


def scrub_text(text: str, *, keep_code: bool = True) -> str:
    if not text:
        return text
    if keep_code and "```" in text:
        parts = text.split("```")
        for i in range(0, len(parts), 2):
            parts[i] = scrub_segment(parts[i])
        return "```".join(parts)
    return scrub_segment(text)


def scrub_summary(text: str) -> str:
    lines = text.splitlines()
    kept = [ln for ln in lines if not META.search(ln)]
    return "\n".join(kept)


def is_raw_test(content) -> bool:
    s = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    return any(m in s for m in RAW_MARKERS)


def redact_payload(content, *, summary: bool = False):
    if isinstance(content, str):
        return scrub_summary(content) if summary else scrub_text(content)
    if isinstance(content, list):
        out = []
        for part in content:
            if (
                isinstance(part, dict)
                and part.get("type") == "text"
                and isinstance(part.get("text"), str)
            ):
                t = scrub_text(part["text"])
                if not t.strip(PUNCT):
                    continue
                part = dict(part)
                part["text"] = t
            out.append(part)
        return out
    return content


def process_conversations(db_path: Path, apply: bool) -> None:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = list(con.execute("select conversation_id, content from conversations"))
    print(f"\n=== {db_path.name}: {len(rows)} conversations ===")
    total_removed = total_redacted = 0
    new_rows = []
    for row in rows:
        cid = row["conversation_id"]
        try:
            msgs = json.loads(row["content"])
        except Exception as exc:
            print(f"  skip {cid}: parse error {exc}")
            new_rows.append((row["content"], cid))
            continue
        out = []
        removed = redacted = 0
        for i, m in enumerate(msgs):
            content = m.get("content")
            if is_raw_test(content):
                removed += 1
                print(f"  [{cid[:8]}] remove msg {i} role={m.get('role')}")
                continue
            is_summary = (
                i == 0
                and m.get("role") == "user"
                and isinstance(content, str)
                and content.startswith("Our previous history conversation summary:")
            )
            new_content = redact_payload(content, summary=is_summary)
            if new_content != content:
                redacted += 1
                print(f"  [{cid[:8]}] redact msg {i} role={m.get('role')}")
            m = dict(m)
            m["content"] = new_content
            out.append(m)
        total_removed += removed
        total_redacted += redacted
        new_rows.append((json.dumps(out, ensure_ascii=False), cid))
    print(f"  removed={total_removed} redacted={total_redacted}")
    if apply:
        for content, cid in new_rows:
            con.execute(
                "update conversations set content=?, updated_at=updated_at where conversation_id=?",
                (content, cid),
            )
        con.commit()
        print("  applied")
    con.close()


def scrub_json_strings(obj):
    if isinstance(obj, str):
        return scrub_text(obj, keep_code=False)
    if isinstance(obj, list):
        return [scrub_json_strings(x) for x in obj]
    if isinstance(obj, dict):
        return {k: scrub_json_strings(v) for k, v in obj.items()}
    return obj


def process_livingmemory(db_path: Path, apply: bool) -> None:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    print(f"\n=== {db_path.name} ===")

    doc_changes = []
    for r in con.execute("select id, metadata from documents"):
        raw = r["metadata"] or ""
        if not META.search(raw):
            continue
        try:
            meta = json.loads(raw)
        except Exception:
            continue
        new = scrub_json_strings(meta)
        if new != meta:
            doc_changes.append((r["id"], json.dumps(new, ensure_ascii=False)))
    print(f"  documents to redact: {len(doc_changes)} {[x[0] for x in doc_changes]}")

    entry_changes = []
    for r in con.execute("select id, content, metadata from graph_entries"):
        content = r["content"] or ""
        metadata = r["metadata"]
        new_content = scrub_text(content, keep_code=False)
        new_metadata = metadata
        if metadata and META.search(metadata):
            try:
                m = json.loads(metadata)
                nm = scrub_json_strings(m)
                if nm != m:
                    new_metadata = json.dumps(nm, ensure_ascii=False)
            except Exception:
                pass
        if new_content != content or new_metadata != metadata:
            entry_changes.append((r["id"], new_content, new_metadata))
    print(f"  graph_entries to redact: {len(entry_changes)}")

    node_changes = []
    for r in con.execute(
        "select id, node_value, canonical_value, metadata from graph_nodes"
    ):
        node_value = r["node_value"]
        canonical = r["canonical_value"]
        metadata = r["metadata"]
        new_node = scrub_text(node_value, keep_code=False) if node_value else node_value
        new_canonical = scrub_text(canonical, keep_code=False) if canonical else canonical
        new_metadata = metadata
        if metadata and META.search(metadata):
            try:
                m = json.loads(metadata)
                nm = scrub_json_strings(m)
                if nm != m:
                    new_metadata = json.dumps(nm, ensure_ascii=False)
            except Exception:
                pass
        if (new_node, new_canonical, new_metadata) != (
            node_value,
            canonical,
            metadata,
        ):
            node_changes.append((r["id"], new_node, new_canonical, new_metadata))
    print(f"  graph_nodes to redact: {len(node_changes)}")

    edge_changes = []
    for r in con.execute("select id, metadata from graph_edges"):
        metadata = r["metadata"]
        if not metadata or not META.search(metadata):
            continue
        try:
            m = json.loads(metadata)
            nm = scrub_json_strings(m)
        except Exception:
            continue
        if nm != m:
            edge_changes.append((r["id"], json.dumps(nm, ensure_ascii=False)))
    print(f"  graph_edges to redact: {len(edge_changes)}")

    op_changes = []
    for r in con.execute("select id, payload, error from memory_write_ops"):
        payload = r["payload"]
        error = r["error"]
        new_payload = payload
        new_error = scrub_text(error, keep_code=False) if error else error
        if payload and META.search(payload):
            try:
                p = json.loads(payload)
                np = scrub_json_strings(p)
                if np != p:
                    new_payload = json.dumps(np, ensure_ascii=False)
            except Exception:
                pass
        if new_payload != payload or new_error != error:
            op_changes.append((r["id"], new_payload, new_error))
    print(f"  memory_write_ops to redact: {len(op_changes)}")

    if apply:
        for doc_id, meta in doc_changes:
            con.execute("update documents set metadata=? where id=?", (meta, doc_id))
        for entry_id, content, metadata in entry_changes:
            con.execute(
                "update graph_entries set content=?, metadata=? where id=?",
                (content, metadata, entry_id),
            )
            con.execute(
                "delete from livingmemory_graph_entries_fts where entry_id=?", (entry_id,)
            )
            con.execute(
                "insert into livingmemory_graph_entries_fts(content, entry_id) values (?, ?)",
                (content, entry_id),
            )
        for node_id, node_value, canonical, metadata in node_changes:
            con.execute(
                "update graph_nodes set node_value=?, canonical_value=?, metadata=? where id=?",
                (node_value, canonical, metadata, node_id),
            )
        for edge_id, metadata in edge_changes:
            con.execute(
                "update graph_edges set metadata=? where id=?", (metadata, edge_id)
            )
        for op_id, payload, error in op_changes:
            con.execute(
                "update memory_write_ops set payload=?, error=? where id=?",
                (payload, error, op_id),
            )
        con.commit()
        print("  applied")
    con.close()


def process_graph_documents(db_path: Path, apply: bool) -> None:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    print(f"\n=== {db_path.name} ===")
    changes = []
    for r in con.execute("select id, text, metadata from documents"):
        text = r["text"] or ""
        metadata = r["metadata"]
        new_text = scrub_text(text, keep_code=False) if text else text
        new_metadata = metadata
        if metadata and META.search(metadata):
            try:
                m = json.loads(metadata)
                nm = scrub_json_strings(m)
                if nm != m:
                    new_metadata = json.dumps(nm, ensure_ascii=False)
            except Exception:
                pass
        if new_text != text or new_metadata != metadata:
            changes.append((r["id"], new_text, new_metadata))
    print(f"  documents to redact: {len(changes)} {[x[0] for x in changes]}")
    if apply:
        for doc_id, text, metadata in changes:
            con.execute(
                "update documents set text=?, metadata=? where id=?",
                (text, metadata, doc_id),
            )
        con.commit()
        print("  applied")
    con.close()


def verify(db_path: Path) -> None:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    print(f"\n=== verify {db_path.name} ===")
    tables = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
    for t in tables:
        if t.endswith("_data") or t.endswith("_idx") or t.endswith("_config") or t.endswith("_docsize"):
            continue
        cols = [r[1] for r in con.execute(f"pragma table_info({t})")]
        text_cols = [c for c in cols if c in ("content", "text", "metadata", "search_text", "canonical_summary")]
        if not text_cols:
            continue
        where = " or ".join(f"{c} like '%星绘%' or {c} like '%必须输出%' or {c} like '%运转正常%' or {c} like '%系统自检%' or {c} like '%PROTOCOL_ENFORCEMENT%'" for c in text_cols)
        try:
            n = con.execute(f"select count(*) from {t} where {where}").fetchone()[0]
        except Exception as e:
            print(f"  {t}: query error {e}")
            continue
        if n:
            print(f"  {t}: {n} rows still contain keywords")
    con.close()


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    base = Path(sys.argv[1])
    apply = "--apply" in sys.argv
    process_conversations(base / "data_v4.db", apply)
    process_livingmemory(base / "livingmemory.db", apply)
    process_graph_documents(base / "livingmemory_graph_documents.db", apply)
    if apply:
        for name in ("data_v4.db", "livingmemory.db", "livingmemory_graph_documents.db"):
            verify(base / name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
