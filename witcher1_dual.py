import argparse
import json
import os
import shutil
import struct
import sys
from pathlib import Path

TYPE_DLG = 0x07ED
TYPE_QST = 0x0824
TEXT_LABEL = 25
QST_LABEL_HINTS = {
    "QuestLocName", "QuestLocMainPhas", "QuestLocDescrip", "QuestLocShortDes",
    "QuestFailedLocDe", "QuestFailedLocSh", "LocName", "LocPhaseName",
    "LocDescription", "LocShortDescript", "FailedLocDesc", "FailedLocShortDe",
}
MAGIC = b"DLG"
HEADER_SIZE = 56
FIELD_SIZE = 12

LANG_NAMES = {
    3: "English",
    5: "Polski",
    10: "Deutsch",
    11: "Français",
    12: "Español",
    13: "Italiano",
    14: "Русский",
    15: "Čeština",
    16: "Magyar",
    20: "한국어",
    21: "中文（繁體）",
    22: "中文（简体）",
}

# Witcher 1 GFF CExoLocString language slots use the game's language table
# multiplied by two.  This is visible in real DLG/QST resources: 3→6,
# 5→10, 10→20, ... 21→42.  IDs 1/2/3 in the GFF documentation correspond
# to the three English variants; the in-game FinalEnglish_short slot is 6.
TLK_TO_GFF = {k: k * 2 for k in LANG_NAMES if k != 0}
GFF_TO_TLK = {v: k for k, v in TLK_TO_GFF.items()}


def u32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def p32(b, o, v):
    struct.pack_into("<I", b, o, v)



def parse_tlk(path_or_bytes):
    b = path_or_bytes if isinstance(path_or_bytes, (bytes, bytearray)) else Path(path_or_bytes).read_bytes()
    if len(b) < 20 or not b.startswith(b"TLK V3.0"):
        raise ValueError("not a TLK V3.0 file")
    lang_id = u32(b, 8)
    count = u32(b, 12)
    base = u32(b, 16)
    if count > 100000 or base > len(b):
        raise ValueError("invalid TLK header")
    table_end = 20 + count * 40
    if table_end > len(b) or base < table_end:
        raise ValueError("invalid TLK string table")
    entries = []
    for i in range(count):
        eo = 20 + i * 40
        off = u32(b, eo + 28)
        ln = u32(b, eo + 32)
        if base + off + ln > len(b):
            raise ValueError(f"TLK string {i} out of bounds")
        raw = bytes(b[base + off:base + off + ln])
        entries.append({"id": i, "entry_offset": eo, "offset": off, "length": ln, "raw": raw})
    return bytes(b), lang_id, entries


def scan_languages(game):
    data_dir = Path(game) / "Data"
    found = []
    for p in sorted(data_dir.rglob("dialog_*.tlk"), key=lambda x: str(x).lower()):
        try:
            raw, lang_id, entries = parse_tlk(p)
            found.append({
                "path": str(p),
                "filename": p.name,
                "language_id": lang_id,
                "language": LANG_NAMES.get(lang_id, f"Language {lang_id}"),
                "strings": len(entries),
            })
        except Exception as e:
            found.append({"path": str(p), "filename": p.name, "error": str(e)})
    # Keep one standard resource per language ID, preferring the exact
    # dialog_<id>.tlk filename.  The GUI still logs all physical files.
    usable = [x for x in found if "language_id" in x]
    by_id = {}
    for x in usable:
        lid = x["language_id"]
        exact = x["filename"].lower() == f"dialog_{lid}.tlk"
        if lid not in by_id or exact:
            by_id[lid] = x
    return {"languages": sorted(usable, key=lambda x: (x.get("language_id", 9999), x.get("filename", ""))),
            "available": sorted(by_id.values(), key=lambda x: x["language_id"])}


def parse_dlg(data, kind="dlg"):
    magic = MAGIC if kind == "dlg" else b"QST"
    if len(data) < HEADER_SIZE or not data.startswith(magic):
        raise ValueError("not a %s resource" % kind.upper())
    vals = struct.unpack_from("<12I", data, 8)
    names = [
        "StructOffset", "StructCount", "FieldOffset", "FieldCount",
        "LabelOffset", "LabelCount", "FieldDataOffset", "FieldDataCount",
        "FieldIndicesOffset", "FieldIndicesCount", "ListIndicesOffset", "ListIndicesCount",
    ]
    h = dict(zip(names, vals))
    sections = [
        ("Struct", h["StructOffset"], h["StructCount"] * 12),
        ("Field", h["FieldOffset"], h["FieldCount"] * FIELD_SIZE),
        ("Label", h["LabelOffset"], h["LabelCount"] * 16),
        ("FieldData", h["FieldDataOffset"], h["FieldDataCount"]),
        ("FieldIndices", h["FieldIndicesOffset"], h["FieldIndicesCount"]),
        ("ListIndices", h["ListIndicesOffset"], h["ListIndicesCount"]),
    ]
    for name, off, size in sections:
        if off < 0 or size < 0 or off + size > len(data):
            raise ValueError(f"{name} out of bounds ({off}+{size}>{len(data)})")
    fields = []
    for i in range(h["FieldCount"]):
        o = h["FieldOffset"] + i * FIELD_SIZE
        typ, label, doff = struct.unpack_from("<III", data, o)
        fields.append((i, typ, label, doff, o))
    return h, fields


def label_name(data, h, label_index):
    if label_index < 0 or label_index >= h["LabelCount"]:
        return "<invalid>"
    start = h["LabelOffset"] + label_index * 16
    raw = data[start:start + 16]
    return raw.split(b"\x00", 1)[0].decode("ascii", "replace")


def loc_entries(data, start):
    if start < 0 or start + 12 > len(data):
        raise ValueError("CExoLocString header out of bounds")
    total, string_ref, count = struct.unpack_from("<III", data, start)
    if total < 12 or start + total > len(data):
        raise ValueError(f"CExoLocString total out of bounds at {start}: {total}")
    pos = start + 12
    out = []
    for _ in range(count):
        if pos + 8 > start + total:
            raise ValueError("CExoLocString entry header out of bounds")
        sid, n = struct.unpack_from("<II", data, pos)
        ts = pos + 8
        te = ts + n
        if te > start + total:
            raise ValueError("CExoLocString text out of bounds")
        try:
            text = bytes(data[ts:te]).decode("utf-8")
        except UnicodeDecodeError as e:
            raise ValueError(f"UTF-8 decode failed: {e}") from e
        out.append({"id": sid, "len": n, "ts": ts, "te": te, "text": text})
        pos = te
    if pos != start + total:
        raise ValueError(f"CExoLocString trailing bytes: {start + total - pos}")
    return total, out, start + total


def validate_dlg(data, kind="dlg"):
    h, fields = parse_dlg(data, kind)
    checked = 0
    for _, typ, _, doff, _ in fields:
        if typ == 12 and doff != 0xFFFFFFFF:
            start = h["FieldDataOffset"] + doff
            loc_entries(data, start)
            checked += 1
    return checked


def get_lang_slots(primary_id, secondary_id):
    if primary_id not in TLK_TO_GFF or secondary_id not in TLK_TO_GFF:
        raise ValueError("Unsupported Witcher 1 language ID")
    return TLK_TO_GFF[primary_id], TLK_TO_GFF[secondary_id]


def find_candidates(orig, kind="dlg", primary_id=5, secondary_id=3):
    primary_slot, secondary_slot = get_lang_slots(primary_id, secondary_id)
    data = bytearray(orig)
    h, fields = parse_dlg(data, kind)
    candidates = []
    for field_index, typ, label, doff, _ in fields:
        if typ != 12 or doff == 0xFFFFFFFF:
            continue
        if kind == "dlg" and label != TEXT_LABEL:
            continue
        start = h["FieldDataOffset"] + doff
        try:
            total, entries, _ = loc_entries(data, start)
        except Exception:
            continue
        by = {x["id"]: x for x in entries}
        if primary_slot not in by or secondary_slot not in by:
            continue
        primary = by[primary_slot]["text"]
        secondary = by[secondary_slot]["text"]
        if not secondary.strip() or secondary in primary:
            continue
        if "||" in primary and "||" in secondary:
            add_text = "\n" + secondary.split("||", 1)[1]
            mode = "structured_description"
        else:
            add_text = "\n" + secondary
            mode = "plain"
        candidates.append({
            "field": field_index,
            "primary_id": primary_id,
            "secondary_id": secondary_id,
            "primary_slot": primary_slot,
            "secondary_slot": secondary_slot,
            "primary": primary,
            "secondary": secondary,
            "append_text": add_text,
            "mode": mode,
            "delta": len(add_text.encode("utf-8")),
        })
    return candidates


def _insert_loc_text(data, kind, field_index, loc_start, entry, add_bytes):
    """Insert bytes at the end of one CExoLocString entry and repair BIF/GFF offsets."""
    h, fields = parse_dlg(data, kind)
    row = next((x for x in fields if x[0] == field_index), None)
    if row is None:
        raise ValueError(f"field {field_index} disappeared during insertion")
    insert_at = entry["te"]
    old_len = entry["len"]
    delta = len(add_bytes)
    p32(data, entry["ts"] - 4, old_len + delta)
    data[insert_at:insert_at] = add_bytes
    p32(data, loc_start, u32(data, loc_start) + delta)

    # FieldData-relative offsets after the insertion move forward.
    h2, fields2 = parse_dlg(data, kind)
    for _, typ2, _, doff2, field_offset2 in fields2:
        if typ2 in (10, 11, 12, 13) and doff2 != 0xFFFFFFFF:
            if h2["FieldDataOffset"] + doff2 > insert_at:
                p32(data, field_offset2 + 8, doff2 + delta)
    p32(data, 8 + 7 * 4, h2["FieldDataCount"] + delta)
    p32(data, 8 + 8 * 4, h2["FieldIndicesOffset"] + delta)
    p32(data, 8 + 10 * 4, h2["ListIndicesOffset"] + delta)
    return delta


def _strip_old_dual_suffix(text, by_id, primary_slot):
    """Remove suffixes previously appended by an older dual-subtitle build.

    This is intentionally conservative: a suffix is removed only when the
    complete text after the last newline exactly matches another localized
    slot in the same CExoLocString. This lets users change Secondary language
    without carrying an old English/Russian/etc. line into the new pair.
    """
    current = text
    changed = False
    while "\n" in current:
        tail = current.rsplit("\n", 1)[1].strip()
        if not tail:
            break
        matched = False
        for sid, entry in by_id.items():
            if sid == primary_slot:
                continue
            other = entry.get("text", "").strip()
            if other and tail == other:
                current = current.rsplit("\n", 1)[0]
                changed = True
                matched = True
                break
        if not matched:
            break
    return current, changed


def _remove_loc_text(data, kind, field_index, loc_start, entry, new_text):
    """Replace a CExoLocString entry with a shorter UTF-8 text and repair offsets."""
    old_len = entry["len"]
    new_bytes = new_text.encode("utf-8")
    delta = len(new_bytes) - old_len
    if delta >= 0:
        return 0
    ts = entry["ts"]
    te = entry["te"]
    data[ts:te] = new_bytes
    p32(data, ts - 4, len(new_bytes))
    # The CExoLocString total shrinks by the same amount.
    p32(data, loc_start, u32(data, loc_start) + delta)
    # Shift the sections after FieldData before reparsing the structure.
    p32(data, 8 + 7 * 4, u32(data, 8 + 7 * 4) + delta)
    p32(data, 8 + 8 * 4, u32(data, 8 + 8 * 4) + delta)
    p32(data, 8 + 10 * 4, u32(data, 8 + 10 * 4) + delta)
    # Repair FieldData-relative offsets for fields located after the deletion.
    h2, fields2 = parse_dlg(data, kind)
    for _, typ2, _, doff2, field_offset2 in fields2:
        if typ2 in (10, 11, 12, 13) and doff2 != 0xFFFFFFFF:
            absolute = h2["FieldDataOffset"] + doff2
            if absolute > ts:
                p32(data, field_offset2 + 8, doff2 + delta)
    return delta


def modify_gff(orig, kind="dlg", primary_id=5, secondary_id=3, max_strings=None, only_fields=None):
    """Append selected secondary language to selected primary language.

    Before adding the selected Secondary, stale suffixes produced by previous
    dual-subtitle builds are removed when they exactly match another language
    slot in the same CExoLocString. This keeps the result strictly Primary +
    current Secondary instead of accumulating Primary + old Secondary + new Secondary.

    DLG: edit the selected primary language slot.
    QST: edit the selected primary slot and, when slot 0 is present and its
    text exactly matches the primary slot, edit slot 0 too. This preserves the
    observed Witcher 1 journal fallback behavior without overwriting a distinct default.
    """
    primary_slot, secondary_slot = get_lang_slots(primary_id, secondary_id)
    data = bytearray(orig)
    candidates = find_candidates(orig, kind, primary_id, secondary_id)
    if only_fields is not None:
        candidates = [c for c in candidates if c["field"] in only_fields]
    if max_strings is not None:
        candidates = candidates[:max_strings]
    if not candidates:
        return bytes(data), 0, []

    candidates = sorted(candidates, key=lambda x: x["field"], reverse=True)
    changed = []

    for c in candidates:
        h, fields = parse_dlg(data, kind)
        row = next((x for x in fields if x[0] == c["field"]), None)
        if row is None:
            raise ValueError(f"field {c['field']} disappeared after an earlier edit")
        field_index, typ, label, doff, field_offset = row
        if typ != 12 or doff == 0xFFFFFFFF or (kind == "dlg" and label != TEXT_LABEL):
            raise ValueError(f"field {c['field']} is no longer a target CExoLocString")
        start = h["FieldDataOffset"] + doff
        total, entries, _ = loc_entries(data, start)
        by = {x["id"]: x for x in entries}
        if primary_slot not in by or secondary_slot not in by:
            continue
        sec = by[secondary_slot]["text"]
        pri = by[primary_slot]
        if not sec.strip():
            continue

        # If the primary already contains an older appended language, remove
        # only the exact matching suffixes before constructing the new pair.
        cleaned_primary, had_old_suffix = _strip_old_dual_suffix(pri["text"], by, primary_slot)
        if had_old_suffix and cleaned_primary != pri["text"]:
            # Re-resolve the field after deletion because offsets may have moved.
            _remove_loc_text(data, kind, field_index, start, pri, cleaned_primary)
            h, fields = parse_dlg(data, kind)
            row = next((x for x in fields if x[0] == field_index), None)
            if row is None:
                raise ValueError(f"field {field_index} disappeared after cleanup")
            start = h["FieldDataOffset"] + row[3]
            total, entries, _ = loc_entries(data, start)
            by = {x["id"]: x for x in entries}
            sec = by[secondary_slot]["text"]
            pri = by[primary_slot]

        if sec in pri["text"]:
            continue
        primary_before = pri["text"]
        if "||" in primary_before and "||" in sec:
            append_text = "\n" + sec.split("||", 1)[1]
            mode = "structured_description"
        else:
            append_text = "\n" + sec
            mode = "plain"
        add = append_text.encode("utf-8")
        total_delta = _insert_loc_text(data, kind, field_index, start, pri, add)

        zero_patched = False
        if kind == "qst":
            # Reparse because the first insertion may have shifted FieldData.
            hq, fq = parse_dlg(data, kind)
            rowq = next((x for x in fq if x[0] == field_index), None)
            if rowq is not None:
                startq = hq["FieldDataOffset"] + rowq[3]
                totalq, entriesq, _ = loc_entries(data, startq)
                byq = {x["id"]: x for x in entriesq}
                if 0 in byq and byq[0]["text"] == primary_before:
                    total_delta += _insert_loc_text(data, kind, field_index, startq, byq[0], add)
                    zero_patched = True

        changed.append({
            "field": field_index,
            "primary_id": primary_id,
            "secondary_id": secondary_id,
            "primary": primary_before,
            "secondary": sec,
            "append": append_text,
            "mode": mode,
            "delta": total_delta,
            "qst_default_slot_0": zero_patched,
        })

    validate_dlg(data, kind)
    return bytes(data), len(changed), changed


def parse_bif(path):
    b = Path(path).read_bytes()
    if len(b) < 20 or not b.startswith(b"BIFFV1.1"):
        raise ValueError("not BIFFV1.1")
    n = u32(b, 8)
    table_end = 20 + n * 20
    if table_end > len(b):
        raise ValueError("BIF resource table exceeds file")
    entries = []
    for i in range(n):
        o = 20 + i * 20
        rid, flags, off, size, typ = struct.unpack_from("<IIIII", b, o)
        if off < table_end or off + size > len(b):
            raise ValueError(f"BIF resource {i} out of bounds: off={off}, size={size}")
        entries.append({"index": i, "rid": rid, "flags": flags, "off": off, "size": size, "type": typ})
    if entries:
        first = entries[0]["off"]
        prev = first
        for e in entries:
            if e["off"] != prev:
                raise ValueError(f"BIF resource gap/overlap before {e['index']}")
            prev = e["off"] + e["size"]
        if prev != len(b):
            raise ValueError("BIF resources do not end at EOF")
    return b, entries


def is_qst_resource(raw, entry_type):
    if not raw.startswith(b"QST"):
        return False
    if entry_type == TYPE_QST:
        return True
    try:
        h, _ = parse_dlg(raw, "qst")
        labels = {label_name(raw, h, i) for i in range(h["LabelCount"])}
        return bool(labels & QST_LABEL_HINTS)
    except Exception:
        return False


def scan_bif(path, kind="dlg", primary_id=5, secondary_id=3):
    b, entries = parse_bif(path)
    target_resources = 0
    ready_resources = 0
    candidate_strings = 0
    warnings = []
    max_strings = (0, None)
    for e in entries:
        raw = b[e["off"]:e["off"] + e["size"]]
        if kind == "dlg":
            if e["type"] != TYPE_DLG:
                continue
        else:
            if not is_qst_resource(raw, e["type"]):
                continue
        target_resources += 1
        expected_magic = MAGIC if kind == "dlg" else b"QST"
        if not raw.startswith(expected_magic):
            warnings.append({"index": e["index"], "rid": e["rid"], "error": "%s type without expected magic" % kind.upper()})
            continue
        try:
            validate_dlg(raw, kind)
            c = find_candidates(raw, kind, primary_id, secondary_id)
            if c:
                ready_resources += 1
                candidate_strings += len(c)
                if len(c) > max_strings[0]:
                    max_strings = (len(c), e["index"])
        except Exception as ex:
            warnings.append({"index": e["index"], "rid": e["rid"], "error": str(ex)})
    return {
        "resources": len(entries),
        "target_resources": target_resources,
        "ready_resources": ready_resources,
        "candidate_strings": candidate_strings,
        "max_strings_in_resource": max_strings[0],
        "max_strings_resource_index": max_strings[1],
        "warnings": warnings,
        "primary_id": primary_id,
        "secondary_id": secondary_id,
        "primary_slot": TLK_TO_GFF.get(primary_id),
        "secondary_slot": TLK_TO_GFF.get(secondary_id),
    }


def build_bif(src, dst, kind="dlg", primary_id=5, secondary_id=3, resource_limit=None, string_limit=None, resource_index=None, fields=None, progress=None):
    src_b, entries = parse_bif(src)
    blobs = []
    modified = []
    failed = []
    total_strings = 0
    ready_resources = 0
    for e in entries:
        raw = src_b[e["off"]:e["off"] + e["size"]]
        blob = raw
        target_type = TYPE_DLG if kind == "dlg" else TYPE_QST
        expected_magic = MAGIC if kind == "dlg" else b"QST"
        target_match = (e["type"] == target_type and raw.startswith(expected_magic)) if kind == "dlg" else is_qst_resource(raw, e["type"])
        if target_match:
            selected_by_index = resource_index is None or e["index"] == resource_index
            selected_by_batch = resource_limit is None or ready_resources < resource_limit
            if selected_by_index and selected_by_batch:
                try:
                    candidates = find_candidates(raw, kind, primary_id, secondary_id)
                    if fields is not None:
                        candidates = [c for c in candidates if c["field"] in fields]
                    if candidates:
                        if string_limit is not None:
                            remaining = max(0, string_limit - total_strings)
                            candidates = candidates[:remaining]
                        if candidates:
                            blob, changed_count, changes = modify_gff(
                                raw, kind, primary_id, secondary_id, len(candidates),
                                {c["field"] for c in candidates} if fields is not None else None
                            )
                            validate_dlg(blob, kind)
                            if changed_count != len(candidates):
                                raise ValueError(f"expected {len(candidates)} edits but applied {changed_count}")
                            modified.append({
                                "resource_index": e["index"],
                                "resource_id": e["rid"],
                                "strings": changed_count,
                                "delta": len(blob) - len(raw),
                                "fields": [x["field"] for x in changes],
                                "changes": changes,
                            })
                            total_strings += changed_count
                            ready_resources += 1
                except Exception as ex:
                    failed.append({"resource_index": e["index"], "resource_id": e["rid"], "error": str(ex)})
        blobs.append(blob)
        if progress:
            progress(e["index"], len(entries))
    if failed:
        raise RuntimeError("%s validation failed: %s" % (kind.upper(), json.dumps(failed[:20], ensure_ascii=True)))
    first = entries[0]["off"] if entries else len(src_b)
    out = bytearray(src_b[:first])
    new_entries = []
    pos = first
    for e, blob in zip(entries, blobs):
        ne = dict(e); ne["off"] = pos; ne["size"] = len(blob)
        new_entries.append(ne); out.extend(blob); pos += len(blob)
    for e in new_entries:
        o = 20 + e["index"] * 20
        struct.pack_into("<IIIII", out, o, e["rid"], e["flags"], e["off"], e["size"], e["type"])
    Path(dst).write_bytes(out)
    parse_bif(dst)
    return {"modified_resources": len(modified), "modified_strings": total_strings, "delta": len(out) - len(src_b), "modified": modified, "primary_id": primary_id, "secondary_id": secondary_id}


def game_bif(game): return Path(game) / "Data" / "dialogues00.bif"
def game_qst_bif(game): return Path(game) / "Data" / "quests00.bif"
def data_dir(game): return Path(game) / "Data"
def backup_qst_path(game): return data_dir(game) / "_DualSubtitles_Backups" / "quests00.original.bif"
def backup_path(game): return data_dir(game) / "_DualSubtitles_Backups" / "dialogues00.original.bif"
def tlk_backup_path(game, lang_id): return data_dir(game) / "_DualSubtitles_Backups" / f"dialog_{lang_id}.original.tlk"
def tlk_path(game, lang_id): return data_dir(game) / f"dialog_{lang_id}.tlk"


def ensure_qst_backup(game):
    src = game_qst_bif(game)
    if not src.is_file(): raise FileNotFoundError(f"quests00.bif not found: {src}")
    bdir = backup_qst_path(game).parent; bdir.mkdir(parents=True, exist_ok=True)
    bak = backup_qst_path(game)
    if not bak.is_file(): shutil.copy2(src, bak)
    return bak


def ensure_backup(game):
    src = game_bif(game)
    if not src.is_file(): raise FileNotFoundError(f"dialogues00.bif not found: {src}")
    bdir = backup_path(game).parent; bdir.mkdir(parents=True, exist_ok=True)
    bak = backup_path(game)
    if not bak.exists(): shutil.copy2(src, bak)
    return bak


def ensure_tlk_backup(game, lang_id):
    src = tlk_path(game, lang_id)
    if not src.is_file(): raise FileNotFoundError(f"dialog_{lang_id}.tlk not found: {src}")
    bdir = tlk_backup_path(game, lang_id).parent; bdir.mkdir(parents=True, exist_ok=True)
    bak = tlk_backup_path(game, lang_id)
    if not bak.exists(): shutil.copy2(src, bak)
    return bak


def restore(game):
    restored = []
    for src, dest in [(backup_path(game), game_bif(game)), (backup_qst_path(game), game_qst_bif(game))]:
        if src.is_file(): shutil.copy2(src, dest); restored.append(str(dest))
    bdir = data_dir(game) / "_DualSubtitles_Backups"
    for bak in sorted(bdir.glob("dialog_*.original.tlk")):
        try:
            lid = int(bak.name.split("_")[1].split(".")[0])
        except Exception:
            continue
        dest = tlk_path(game, lid)
        if dest.is_file(): shutil.copy2(bak, dest); restored.append(str(dest))
    if not restored: raise FileNotFoundError("No original backups found")
    return restored


def source_qst_for_build(game):
    bak = backup_qst_path(game); return bak if bak.exists() else game_qst_bif(game)
def source_for_build(game):
    bak = backup_path(game); return bak if bak.exists() else game_bif(game)
def source_tlk_for_build(game, lang_id):
    bak = tlk_backup_path(game, lang_id); return bak if bak.exists() else tlk_path(game, lang_id)


def build_all(game, outdir, primary_id=5, secondary_id=3):
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    dsrc = source_for_build(game); qsrc = source_qst_for_build(game)
    dout = outdir / "dialogues00.dual.bif"; qout = outdir / "quests00.dual.bif"
    dr = build_bif(dsrc, dout, kind="dlg", primary_id=primary_id, secondary_id=secondary_id)
    qr = build_bif(qsrc, qout, kind="qst", primary_id=primary_id, secondary_id=secondary_id)
    return {"dialogues": dr, "quests": qr, "dialogues_out": str(dout), "quests_out": str(qout), "primary_id": primary_id, "secondary_id": secondary_id}


def build_tlk_english_ui(game, primary_id, out):
    src = source_tlk_for_build(game, primary_id)
    en = tlk_path(game, 3)
    if not en.is_file(): raise FileNotFoundError(f"dialog_3.tlk not found: {en}")
    raw, lid, entries = parse_tlk(src)
    eraw, elid, eentries = parse_tlk(en)
    if len(entries) != len(eentries): raise ValueError("Primary and English TLK string counts differ")
    if primary_id == 3:
        Path(out).write_bytes(raw); return {"language_id": primary_id, "changed": 0, "output": str(out)}
    # IDs are the same across all official Witcher 1 language packs; replace
    # only the known English UI/journal set, leaving the rest in primary language.
    menu_ids = sorted(set(
        list(range(80,180)) + list(range(1604,1651)) + list(range(1666,1673)) +
        list(range(1693,1719)) + [1749] + list(range(1820,1825)) + list(range(2008,2064)) +
        list(range(2380,2406)) + list(range(2437,2449)) + list(range(2647,2675)) +
        [1641,1690] + list(range(1743,1789)) + list(range(2295,2300)) + list(range(2512,2546))
    ))
    outb = bytearray(raw); base = u32(outb,16); ebase = u32(eraw,16); changed=[]
    for idx in menu_ids:
        if idx >= len(entries): continue
        pe = entries[idx]; ee = eentries[idx]
        praw = pe["raw"]; er = ee["raw"]
        if not praw or not er or praw == er: continue
        rel = len(outb) - base; outb.extend(er)
        struct.pack_into("<I", outb, pe["entry_offset"] + 28, rel)
        struct.pack_into("<I", outb, pe["entry_offset"] + 32, len(er))
        changed.append(idx)
    Path(out).write_bytes(outb)
    parse_tlk(out)
    return {"language_id": primary_id, "changed": len(changed), "ids": changed, "output": str(out)}


def install_candidates(game, manifest, tlk_candidate=None, primary_id=None):
    m = json.loads(Path(manifest).read_text(encoding="utf-8"))
    dbak = ensure_backup(game); qbak = ensure_qst_backup(game)
    shutil.copy2(m["dialogues_out"], game_bif(game)); shutil.copy2(m["quests_out"], game_qst_bif(game))
    result = {"installed": [str(game_bif(game)), str(game_qst_bif(game))], "backups": [str(dbak), str(qbak)]}
    if tlk_candidate and primary_id is not None:
        bak = ensure_tlk_backup(game, primary_id)
        shutil.copy2(tlk_candidate, tlk_path(game, primary_id))
        result["tlk"] = str(tlk_path(game, primary_id)); result["tlk_backup"] = str(bak)
    return result


def parse_save(path_or_bytes):
    b = path_or_bytes if isinstance(path_or_bytes, (bytes, bytearray)) else Path(path_or_bytes).read_bytes()
    if len(b) < 16 or b[:4] != b"RGMH": raise ValueError("not a TheWitcherSave file (missing RGMH)")
    table_off = u32(b, len(b)-8); count = u32(b, len(b)-4)
    if table_off < 0x2028 or table_off >= len(b)-8 or count > 10000: raise ValueError(f"invalid save resource table: offset={table_off}, count={count}")
    pos=table_off; entries=[]
    for i in range(count):
        if pos+4>len(b): raise ValueError("save resource table truncated")
        n=u32(b,pos); pos+=4
        if n>4096 or pos+n+8>len(b): raise ValueError(f"invalid save resource name length at {i}: {n}")
        name_b=bytes(b[pos:pos+n]); pos+=n; size=u32(b,pos); off=u32(b,pos+4); pos+=8
        if off+size>table_off or off<0x2028: raise ValueError(f"save resource {i} out of bounds: {off}+{size}>{table_off}")
        entries.append({"index":i,"name":name_b,"size":size,"off":off})
    if pos != len(b)-8: raise ValueError(f"resource table length mismatch: parsed to {pos}, expected {len(b)-8}")
    ordered=sorted(entries,key=lambda e:e["off"])
    if ordered:
        prev=ordered[0]["off"]
        for e in ordered:
            if e["off"]!=prev: raise ValueError(f"save resource gap/overlap before resource {e['index']}")
            prev=e["off"]+e["size"]
        if prev!=table_off: raise ValueError("save resource data does not end at resource table")
    return bytes(b),entries,table_off,count


def patch_save(src_path,dst_path=None,primary_id=5,secondary_id=3):
    b,entries,table_off,count=parse_save(src_path); ordered=sorted(entries,key=lambda e:e["off"])
    blobs={}; modified=[]; total_strings=0; total_delta=0
    for e in ordered:
        raw=b[e["off"]:e["off"]+e["size"]]; name=e["name"].decode("utf-8","replace"); blob=raw
        if name.lower().endswith('.qst') and raw.startswith(b"QST"):
            try:
                candidates=find_candidates(raw,"qst",primary_id,secondary_id)
                if candidates:
                    blob,changed_count,changes=modify_gff(raw,"qst",primary_id,secondary_id)
                    validate_dlg(blob,"qst")
                    modified.append({"resource_index":e["index"],"name":name,"strings":changed_count,"delta":len(blob)-len(raw),"fields":[x["field"] for x in changes]})
                    total_strings+=changed_count; total_delta+=len(blob)-len(raw)
            except Exception as ex:
                raise RuntimeError(f"QST save resource {e['index']} {name}: {ex}") from ex
        blobs[e["index"]]=blob
    first_off=ordered[0]["off"] if ordered else 0x2028; out=bytearray(b[:first_off]); new_entries=[]; pos=first_off
    for e in ordered:
        blob=blobs[e["index"]]; ne=dict(e); ne["off"]=pos; ne["size"]=len(blob); new_entries.append(ne); out.extend(blob); pos+=len(blob)
    new_table_off=pos; by_index={e["index"]:e for e in new_entries}
    for e in entries:
        ne=by_index[e["index"]]; out.extend(struct.pack("<I",len(ne["name"]))); out.extend(ne["name"]); out.extend(struct.pack("<II",ne["size"],ne["off"]))
    out.extend(struct.pack("<II",new_table_off,count))
    dst=Path(dst_path) if dst_path else Path(src_path)
    if dst.resolve()==Path(src_path).resolve():
        tmp=dst.with_suffix(dst.suffix+'.dual_tmp'); tmp.write_bytes(out); tmp.replace(dst)
    else: dst.write_bytes(out)
    parse_save(dst)
    return {"save":str(dst),"modified_resources":len(modified),"modified_strings":total_strings,"delta":len(out)-len(b),"modified":modified,"primary_id":primary_id,"secondary_id":secondary_id}


def patch_save_folder(folder,primary_id=5,secondary_id=3):
    folder=Path(folder)
    if not folder.is_dir(): raise FileNotFoundError(str(folder))
    saves=sorted([p for p in folder.iterdir() if p.is_file() and p.name.lower().endswith('.thewitchersave')],key=lambda p:p.name.lower())
    if not saves: raise FileNotFoundError(f"No .TheWitcherSave files found in {folder}")
    results=[]; total_r=total_s=total_d=0
    for save in saves:
        backup=save.with_suffix(save.suffix+'.dual_backup')
        if not backup.exists(): shutil.copy2(save,backup)
        tmp=save.with_suffix(save.suffix+'.dual_tmp')
        try:
            result=patch_save(save,tmp,primary_id,secondary_id); tmp.replace(save); result['save']=str(save); result['backup']=str(backup); results.append(result)
            total_r+=result.get('modified_resources',0); total_s+=result.get('modified_strings',0); total_d+=result.get('delta',0)
        except Exception:
            if tmp.exists():
                try: tmp.unlink()
                except Exception: pass
            raise
    return {'folder':str(folder),'saves_found':len(saves),'saves_patched':len(results),'modified_resources':total_r,'modified_strings':total_s,'delta':total_d,'results':results,'primary_id':primary_id,'secondary_id':secondary_id}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("action",choices=["scan","scan-languages","build","build-all","build-tlk-ui","install","restore","patch-save"])
    ap.add_argument("--game"); ap.add_argument("--bif"); ap.add_argument("--out"); ap.add_argument("--outdir"); ap.add_argument("--kind",choices=["dlg","qst"],default="dlg")
    ap.add_argument("--resources",type=int); ap.add_argument("--strings",type=int); ap.add_argument("--resource-index",type=int); ap.add_argument("--fields"); ap.add_argument("--folder")
    ap.add_argument("--primary-id",type=int,default=5); ap.add_argument("--secondary-id",type=int,default=3)
    args=ap.parse_args(); game=Path(args.game) if args.game else None
    if args.action=="scan-languages":
        if game is None: raise ValueError("--game is required")
        print(json.dumps(scan_languages(game),ensure_ascii=True)); return
    if args.action=="patch-save":
        if args.folder:
            print(json.dumps(patch_save_folder(args.folder,args.primary_id,args.secondary_id),ensure_ascii=True)); return
        if not args.bif: raise ValueError("--bif is required for patch-save")
        save=Path(args.bif)
        if not save.is_file(): raise FileNotFoundError(str(save))
        if args.out: result=patch_save(save,args.out,args.primary_id,args.secondary_id)
        else:
            backup=save.with_suffix(save.suffix+'.dual_backup')
            if not backup.exists(): shutil.copy2(save,backup)
            result=patch_save(save,None,args.primary_id,args.secondary_id); result["backup"]=str(backup)
        print(json.dumps(result,ensure_ascii=True)); return
    if args.action=="restore":
        if game is None: raise ValueError("--game is required for restore")
        print(json.dumps({"restored":restore(game)},ensure_ascii=True)); return
    if args.action=="build-all":
        if game is None: raise ValueError("--game is required for build-all")
        if not game_bif(game).is_file(): raise FileNotFoundError(str(game_bif(game)))
        if not game_qst_bif(game).is_file(): raise FileNotFoundError(str(game_qst_bif(game)))
        if not args.outdir: raise ValueError("--outdir is required for build-all")
        print(json.dumps(build_all(game,args.outdir,args.primary_id,args.secondary_id),ensure_ascii=True)); return
    if args.action=="build-tlk-ui":
        if game is None or not args.out: raise ValueError("--game and --out are required")
        print(json.dumps(build_tlk_english_ui(game,args.primary_id,args.out),ensure_ascii=True)); return
    default_bif=game_bif(game) if (game and args.kind=="dlg") else (game_qst_bif(game) if game else None)
    bif=Path(args.bif) if args.bif else default_bif
    if bif is None or not bif.is_file(): raise FileNotFoundError(f"{args.kind} BIF not found: {bif}")
    if args.action=="scan":
        src=(source_for_build(game) if args.kind=="dlg" else source_qst_for_build(game)) if game else bif
        print(json.dumps(scan_bif(src,args.kind,args.primary_id,args.secondary_id),ensure_ascii=True)); return
    if not args.out: raise ValueError("--out is required for build/install")
    fields=None
    if args.fields: fields={int(x.strip()) for x in args.fields.split(",") if x.strip()}
    src=(source_for_build(game) if args.kind=="dlg" else source_qst_for_build(game)) if game else bif
    result=build_bif(src,args.out,kind=args.kind,primary_id=args.primary_id,secondary_id=args.secondary_id,resource_limit=args.resources,string_limit=args.strings,resource_index=args.resource_index,fields=fields)
    if args.action=="install":
        if game is None: raise ValueError("--game is required for install")
        bak=ensure_backup(game) if args.kind=="dlg" else ensure_qst_backup(game); shutil.copy2(args.out,game_bif(game) if args.kind=="dlg" else game_qst_bif(game)); result["backup"]=str(bak); result["installed"]=str(game_bif(game) if args.kind=="dlg" else game_qst_bif(game))
    print(json.dumps(result,ensure_ascii=True))


if __name__=="__main__":
    try: main()
    except Exception as e:
        print(json.dumps({"error":str(e)},ensure_ascii=True)); sys.exit(1)
