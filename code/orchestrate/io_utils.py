"""I/O helpers: CSV read/write, image path resolution, image encoding.

Images are downscaled before encoding to control token cost and stay within
rate limits, while preserving enough detail to assess surface damage.
"""
from __future__ import annotations

import base64
import csv
import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

from . import config
from .schema import OUTPUT_COLUMNS


@dataclass
class ImageRef:
    image_id: str          # filename without extension, e.g. "img_1"
    rel_path: str          # path as written in the CSV
    abs_path: Path         # resolved absolute path
    exists: bool


@dataclass
class Claim:
    user_id: str
    image_paths: str       # raw CSV value (semicolon separated)
    user_claim: str
    claim_object: str
    images: list[ImageRef]
    # passthrough expected outputs when present (sample set) for evaluation
    expected: dict | None = None


def read_claims(csv_path: Path, images_root: Path) -> list[Claim]:
    """Read a claims CSV. Works for both input-only and labeled (sample) files."""
    claims: list[Claim] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        label_cols = [c for c in OUTPUT_COLUMNS if c not in
                      ("user_id", "image_paths", "user_claim", "claim_object")]
        for row in reader:
            images = resolve_images(row["image_paths"], images_root)
            expected = None
            if all(c in row and row[c] != "" for c in label_cols[:1]):
                # looks labeled (has evidence_standard_met etc.)
                if "claim_status" in row and row.get("claim_status"):
                    expected = {c: row.get(c, "") for c in label_cols}
            claims.append(Claim(
                user_id=row["user_id"].strip(),
                image_paths=row["image_paths"].strip(),
                user_claim=row["user_claim"],
                claim_object=row["claim_object"].strip().lower(),
                images=images,
                expected=expected,
            ))
    return claims


def resolve_images(image_paths: str, images_root: Path) -> list[ImageRef]:
    refs: list[ImageRef] = []
    for raw in image_paths.split(";"):
        rel = raw.strip()
        if not rel:
            continue
        # CSV paths look like "images/test/case_001/img_1.jpg"; images_root is
        # the dataset/ dir, so resolve relative to it.
        abs_path = (images_root.parent / rel).resolve()
        if not abs_path.exists():
            # fallback: maybe path already absolute-ish from dataset root
            alt = (images_root / rel).resolve()
            abs_path = alt if alt.exists() else abs_path
        image_id = Path(rel).stem
        refs.append(ImageRef(image_id=image_id, rel_path=rel,
                             abs_path=abs_path, exists=abs_path.exists()))
    return refs


def read_user_history(csv_path: Path) -> dict[str, dict]:
    history: dict[str, dict] = {}
    if not csv_path.exists():
        return history
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            history[row["user_id"].strip()] = row
    return history


def read_evidence_requirements(csv_path: Path) -> list[dict]:
    reqs: list[dict] = []
    if not csv_path.exists():
        return reqs
    with open(csv_path, newline="", encoding="utf-8") as f:
        reqs = list(csv.DictReader(f))
    return reqs


def encode_image(ref: ImageRef) -> dict | None:
    """Load, EXIF-correct, downscale, and base64-encode an image for the API.

    Returns an Anthropic image content block, or None if unreadable.
    """
    if not ref.exists:
        return None
    try:
        img = Image.open(ref.abs_path)
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        max_edge = config.RUNTIME.max_image_edge
        if max(img.size) > max_edge:
            img.thumbnail((max_edge, max_edge), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=config.RUNTIME.jpeg_quality)
        data = base64.standard_b64encode(buf.getvalue()).decode("ascii")
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": data},
        }
    except Exception:
        return None


def write_output(rows: list[dict], out_path: Path) -> None:
    """Write output.csv with the exact required columns, in order, quoted."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS,
                                quoting=csv.QUOTE_ALL, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            out = {}
            for c in OUTPUT_COLUMNS:
                v = r.get(c, "")
                if isinstance(v, bool):
                    v = "true" if v else "false"
                out[c] = v
            writer.writerow(out)
