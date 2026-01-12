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

## Key Dependencies

| Package | Version |
|---------|---------|
| insightface | 0.7.3 |
| onnxruntime | 1.23.2 |
| opencv-python | 4.12.0 |
| numpy | 2.2.6 |
| networkx | 3.6.1 |
| pandas | 2.3.3 |
