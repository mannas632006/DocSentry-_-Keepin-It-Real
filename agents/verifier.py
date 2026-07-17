"""After a fix is drafted, confirm the doc no longer lies."""
from docsentry.agents.divergence import check_divergence


def verify_fix(change: dict, fixed_doc_content: str, verdict: dict) -> bool:
    """Re-run divergence on the patched section. True = fix is clean."""
    patched_section = {
        "id": verdict["doc_id"],
        "content": fixed_doc_content,
        "meta": {"file": verdict["doc_file"],
                 "heading": verdict["doc_heading"],
                 "start_line": verdict["doc_start_line"],
                 "end_line": verdict["doc_end_line"]},
    }
    recheck = check_divergence(change, patched_section)
    return not recheck["diverged"]
