import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.verify_vtse_internal import TOPICS, verify_topic

rows = [verify_topic(t) for t in TOPICS]
out = Path(__file__).parent / "audit_vtse_verify.json"
# JSON only (no banner lines)
out.write_text(json.dumps({"topics": rows, "strategies": sorted({r["selected_strategy"] for r in rows})}, indent=2), encoding="utf-8")
for r in rows:
    print(
        r["topic"][:40],
        r["selected_strategy"],
        r["beat_count"],
        r["cir_representation_type"],
        r["timeline_layout_profile"],
        sep=" | ",
    )
