import re


MOJIBAKE_MARKERS_RE = re.compile(r"[ØÙÃÂ]|[\u0080-\u009F]")
ARABIC_RE = re.compile(r"[\u0600-\u06FF]")
TEXT_CLEANUP_FIELDS = {
    "title", "summary", "description", "text", "content", "overview",
    "original_title", "original_snippet", "original_content",
    "source_title", "source_content",
    "platform", "level", "provider", "source", "certificate",
    "practical_benefit", "user_can_do", "cultural_relevance",
    "what_is_new", "new_capability", "why_it_is_valuable", "who_benefits",
    "selection_reason", "duplicate_check_reason", "reasoning",
    "internal_sector_label", "internal_sector_type_label",
}


# Text cleanup role: Score text quality when repairing broken Arabic encoding.
def mojibake_score(value):
    text = str(value or "")
    return len(ARABIC_RE.findall(text)) * 4 - len(MOJIBAKE_MARKERS_RE.findall(text)) * 3


# Text cleanup role: Repair common mojibake in stored or client-submitted text.
def repair_mojibake_text(value):
    if not isinstance(value, str) or not value:
        return value
    if not MOJIBAKE_MARKERS_RE.search(value):
        return value
    best = value
    best_score = mojibake_score(value)
    queue = [value]
    seen = {value}
    for _ in range(3):
        next_queue = []
        for candidate in queue:
            decoded_options = []
            try:
                raw = bytearray()
                for char in candidate:
                    code = ord(char)
                    if code <= 0xFF:
                        raw.append(code)
                    else:
                        raw.extend(char.encode("cp1252"))
                decoded_options.append(bytes(raw).decode("utf-8"))
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
            for encoding in ("latin1", "cp1252"):
                try:
                    decoded_options.append(candidate.encode(encoding).decode("utf-8"))
                except (UnicodeEncodeError, UnicodeDecodeError):
                    continue
            for repaired in decoded_options:
                if repaired in seen:
                    continue
                seen.add(repaired)
                score = mojibake_score(repaired)
                if score > best_score:
                    best = repaired
                    best_score = score
                if MOJIBAKE_MARKERS_RE.search(repaired):
                    next_queue.append(repaired)
        queue = next_queue
        if not queue:
            break
    return best


# Text cleanup role: Recursively repair configured text fields before API/storage use.
def cleanup_text_fields(value, *, all_strings=False):
    if isinstance(value, dict):
        return {
            key: cleanup_text_fields(item, all_strings=all_strings or key in TEXT_CLEANUP_FIELDS)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [cleanup_text_fields(item, all_strings=all_strings) for item in value]
    if isinstance(value, str) and all_strings:
        return repair_mojibake_text(value)
    return value
