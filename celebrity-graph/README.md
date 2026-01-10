# Celebrity Connection Graph

This project builds a graph of real-world relationships between public figures
based on shared appearances in photographs.

A photo is treated as evidence of physical co-presence. If two people appear in
the same image, an edge is created between them. Repeated co-appearances increase
edge weight.

The system is intentionally backend-only and deterministic, designed to
demonstrate data modeling, graph algorithms, and system design.

## Data Contracts

### 1. Input Manifest

`celebs/manifest.json`

```json
{
  "some_image.jpg": ["Person A", "Person B", "Person C"]
}
```

### 2. Edge List

(celebs/edges.csv)

columns: person_a,person_b,image

each row = one evidence event

### 3. Graph Artifact

undirected, nodes=people

edge attrs: weight, images
