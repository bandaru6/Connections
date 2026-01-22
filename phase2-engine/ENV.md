# Phase 2A Environment Setup

## Virtual Environment

**Use Python 3.11 venv for Phase 2A; Python 3.12 venv failed for insightface.**

### Activate
```bash
source .venv_phase2_py311/bin/activate
```

Or with full path:
```bash
source /Users/aashrithbandaru/Connections/phase2-engine/.venv_phase2_py311/bin/activate
```

### Deactivate
```bash
deactivate
```

## InsightFace Model Cache

Models are cached at:
```
~/.insightface/models/buffalo_l/
```

Contents:
- `1k3d68.onnx` - 3D landmark (68 points)
- `2d106det.onnx` - 2D landmark (106 points)
- `det_10g.onnx` - Face detection
- `genderage.onnx` - Gender/age estimation
- `w600k_r50.onnx` - Face recognition (512-dim embeddings)

## Smoke Tests

### Built-in test image (InsightFace sample)
```bash
python -c "
from insightface.app import FaceAnalysis
import insightface
app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
app.prepare(ctx_id=0, det_size=(640,640))
img = insightface.data.get_image('t1')
faces = app.get(img)
print(f'Faces: {len(faces)}, Embedding dim: {faces[0].embedding.shape[0]}')
"
```

### Real photos smoke test
```bash
python scripts/smoke_real_photos.py
```

## Profile Image Cleaner (Recommended)

Two-pass profile image downloader with robust rate limiting and caching:

```bash
# Fill all identities to 3 images each
python scripts/profiles_clean.py --target 3

# Process a single identity
python scripts/profiles_clean.py --target 3 --only "Barack Obama"

# Force re-download (overwrites existing)
python scripts/profiles_clean.py --target 3 --force

# Adjust rate limiting and limits
python scripts/profiles_clean.py --target 3 --sleep-base 2.0 --max-candidates 100
```

Features:
- **Two-pass approach**: Pass 1 ensures coverage (1 image each), Pass 2 fills to target
- **Exponential backoff** for HTTP 429 rate limits
- **Caches search results** in `artifacts/wiki_cache.json`
- **Validates with InsightFace**: accepts only single-face images
- **Saves report** to `artifacts/profiles_clean_report.json`

## Profile Image Downloader (Legacy)

Download headshot images from Wikimedia Commons for all identities:

```bash
# Download 3 images per identity (default)
python scripts/download_profiles_wikimedia.py --per-id 3

# Force re-download even if folder already has images
python scripts/download_profiles_wikimedia.py --per-id 3 --force

# Process a single identity (for testing)
python scripts/download_profiles_wikimedia.py --identity "Barack Obama" --per-id 3
```

The script:
- Searches Wikimedia Commons for portrait/headshot images
- Downloads candidates and validates with InsightFace
- Keeps only images with exactly 1 detected face
- Saves as `<Identity Name>1.jpg`, `<Identity Name>2.jpg`, etc.
- Skips identities that already have enough images (unless --force)

## Key Dependencies

| Package | Version |
|---------|---------|
| insightface | 0.7.3 |
| onnxruntime | 1.23.2 |
| opencv-python | 4.12.0 |
| numpy | 2.2.6 |
| networkx | 3.6.1 |
| pandas | 2.3.3 |

## Rebuild vs Incremental

### Incremental ingest
- Keeps `ingest_log.jsonl`.
- Ingests only images not in the log.
- The graph keeps growing with new nodes/edges.

### Full rebuild
- **Deletes ALL of:**
  - `phase2-engine/artifacts/celeb_graph_phase2.gpickle`
  - `phase2-engine/artifacts/ingest_log.jsonl`
  - `phase2-engine/artifacts/unknown_registry.pkl`
- Then runs ingest again to process *all* ingest images.
- This prevents the “new graph but old log” bug.

### Match Thresholds
- **Conservative thresholds:** `top1 >= 0.45` AND `margin >= 0.05`.
- **Reasoning:** We use conservative thresholds to avoid poisoning the graph with false positives. It is better to have more "Unknown" entries than to incorrectly link two different celebrities, which would corrupt the social graph structure.