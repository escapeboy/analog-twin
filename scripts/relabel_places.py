"""Rewrite place_label of Earth points in an existing index (points.parquet) from the current admin-0 source
(engine.dem.FILES["ne_countries"]) without rebuilding features.

    python scripts/relabel_places.py data/index/full data/index/small
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_index import earth_country_labels  # noqa: E402
from engine import dem  # noqa: E402


def relabel(index_dir: Path) -> dict:
    import pyarrow as pa
    import pyarrow.parquet as pq
    p = index_dir / "points.parquet"
    t = pq.read_table(p)
    body = np.asarray(t.column("body").to_pylist(), dtype=object)
    labels = np.asarray(t.column("place_label").to_pylist(), dtype=object)
    e = np.flatnonzero(body == "earth")
    new = earth_country_labels(t.column("lat").to_numpy()[e], t.column("lon").to_numpy()[e])
    changed = int(sum(a != b for a, b in zip(labels[e], new)))
    labels[e] = new
    t = t.set_column(t.schema.get_field_index("place_label"), "place_label", pa.array(labels.tolist()))
    tmp = p.with_suffix(".tmp.parquet")
    pq.write_table(t, tmp)
    os.replace(tmp, p)
    mp = index_dir / "manifest.json"
    m = json.loads(mp.read_text())
    m["place_labels"] = {"source": str(dem.FILES["ne_countries"]), "point_of_view": "DEU (Natural Earth POV file)"}
    mp.write_text(json.dumps(m, indent=2))
    return {"index": str(index_dir), "earth_points": len(e), "labels_changed": changed}


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    for d in sys.argv[1:]:
        print(relabel(Path(d)))
