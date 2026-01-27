# API Reference

Base URL: `http://localhost:8000`

Interactive docs: `http://localhost:8000/docs` (Swagger UI)

## Health

### GET /health
Check system health status.

**Response:**
```json
{
  "status": "healthy",
  "database": "ok"
}
```

---

## Admin Endpoints

### POST /admin/rebuild-profile-index
Rebuild the profile index by scanning `data/profiles/` directory.

**Warning:** This clears all existing persons, profiles, and graph data.

**Response:**
```json
{
  "status": "completed",
  "profiles_dir": "/app/data/profiles",
  "total_images_scanned": 94,
  "persons_created": 94,
  "profiles_inserted": 94,
  "images_rejected": 0,
  "rejected_details": []
}
```

### POST /admin/reset-demo
Reset graph data while preserving profiles.

Clears: `uploads`, `faces`, `edges`, `edge_evidence`, `processed_images`
Preserves: `persons`, `person_profiles`

**Response:**
```json
{
  "status": "completed",
  "cleared": ["uploads", "faces", "edges", "edge_evidence", "processed_images"],
  "preserved": ["persons", "person_profiles"]
}
```

### POST /admin/clear-processed
Clear only the processed_images tracking table.

**Response:**
```json
{
  "status": "completed",
  "cleared": ["processed_images"],
  "remaining_count": 0
}
```

### GET /admin/storage-info
Get storage directory information.

**Response:**
```json
{
  "profiles_dir": "/app/data/profiles",
  "profiles_count": 94,
  "uploads_dir": "/app/uploads",
  "uploads_count": 45,
  "group_photos_dir": "/app/data/group_photos",
  "group_photos_count": 0
}
```

---

## Ingest Endpoints

### POST /ingest/upload
Upload and process a single image.

**Request:** `multipart/form-data`
- `image`: Image file (jpg, png, webp)
- `force` (query param): Re-process even if already done

**Response:**
```json
{
  "faces_detected": 3,
  "known_matches": 2,
  "unknown_faces": 1,
  "edges_created": 3
}
```

### POST /ingest/folder
Process all images in the uploads directory.

**Query Parameters:**
- `force`: boolean - Re-process all images (default: false)

**Response:**
```json
{
  "total_images": 45,
  "processed": 45,
  "skipped": 0,
  "total_faces_detected": 120,
  "total_known_matches": 85,
  "total_unknown_faces": 35,
  "total_edges_created": 41,
  "results": [...]
}
```

---

## Graph Endpoints

### GET /graph/summary
Get a summary of the social graph.

**Query Parameters:**
- `include_unknown`: boolean - Include UNKNOWN persons (default: false)

**Response:**
```json
{
  "persons_total": 95,
  "known_persons_total": 95,
  "unknown_persons_total": 64,
  "edges_total": 41,
  "edges_known_only_total": 41,
  "top_edges": [
    {
      "person_a": "Hillary Clinton",
      "person_b": "Bill Clinton",
      "weight": 2,
      "evidence": ["photo1.jpg", "photo2.jpg"]
    }
  ],
  "recent_uploads": [...]
}
```

### GET /graph/neighbors
Get neighbors of a person.

**Query Parameters:**
- `person`: string (required) - Person name
- `limit`: int - Max neighbors (default: 25)
- `include_unknown`: boolean - Include UNKNOWN neighbors (default: false)

**Response:**
```json
{
  "person": "Barack Obama",
  "neighbors": [
    {
      "neighbor": "Joe Biden",
      "weight": 2,
      "evidence": ["Obama_Biden.jpg", "campaign.jpg"]
    }
  ]
}
```

### GET /graph/ego
Get ego network centered on a person.

**Query Parameters:**
- `person`: string (required) - Center person name
- `depth`: int - Hops from center, 1-3 (default: 2)
- `limit`: int - Max nodes (default: 50)
- `include_unknown`: boolean (default: false)

**Response:**
```json
{
  "center": "Barack Obama",
  "depth": 2,
  "nodes": [
    {"name": "Barack Obama", "is_unknown": false},
    {"name": "Joe Biden", "is_unknown": false}
  ],
  "edges": [
    {"source": "Barack Obama", "target": "Joe Biden", "weight": 2}
  ]
}
```

### GET /graph/path
Find shortest path between two people.

**Query Parameters:**
- `source`: string (required) - Source person
- `target`: string (required) - Target person
- `include_unknown`: boolean (default: false)

**Response:**
```json
{
  "source": "Taylor Swift",
  "target": "Barack Obama",
  "found": true,
  "path": ["Taylor Swift", "Beyonce", "Barack Obama"],
  "hops": 2,
  "edges": [...]
}
```

### GET /graph/persons/list
List persons in the graph.

**Query Parameters:**
- `q`: string - Search filter (case-insensitive)
- `include_unknown`: boolean (default: false)
- `limit`: int - Max results (default: 50)

**Response:**
```json
{
  "count": 95,
  "persons": ["Alexandria Ocasio-Cortez", "Allen Iverson", ...]
}
```

---

## Profile Endpoints

### GET /profiles/list
List all profiles with embedding counts.

**Query Parameters:**
- `include_unknown`: boolean (default: false)
- `limit`: int (default: 100)

**Response:**
```json
{
  "profiles": [
    {"id": "uuid", "name": "Barack Obama", "profile_count": 3}
  ],
  "total": 95
}
```

### POST /profiles/check-match
Check if a face matches any existing profile.

**Request:** `multipart/form-data`
- `image`: Image file with a face

**Response:**
```json
{
  "best_match": "Barack Obama",
  "similarity": 0.7823,
  "threshold": 0.50,
  "is_match": true
}
```

### POST /profiles/create
Create a new person profile.

**Request:** `multipart/form-data`
- `name`: string - Person name
- `images`: files - 1-5 face images
- `confirm`: boolean - Proceed even with potential match
- `mode`: string - "new" or "merge"

**Response:**
```json
{
  "status": "completed",
  "created": true,
  "person_name": "New Person",
  "person_id": "uuid",
  "embeddings_added": 3
}
```

### DELETE /profiles/{name}
Delete a person profile.

**Response:**
```json
{
  "status": "deleted",
  "person_name": "Person Name",
  "person_id": "uuid"
}
```

---

## Error Responses

All errors return JSON with detail:

```json
{
  "detail": "Error message here"
}
```

| Status Code | Meaning |
|-------------|---------|
| 400 | Bad request (invalid input) |
| 404 | Resource not found |
| 500 | Internal server error |
