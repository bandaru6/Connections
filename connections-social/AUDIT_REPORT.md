# Audit Report: Connections Social

## A. Profile Images (Identity Source)
*   **Location:** The system looks for profile images in `data/profiles/` (defined in `backend/app/config.py`).
*   **Status:** ✅ Self-contained within the repository.
*   **Usage:** The `/admin/rebuild-profile-index` endpoint scans this directory. It expects a structure like `profiles/<Person Name>/*.jpg`. It takes the first valid face found in each folder to build the reference embedding for that person.

## B. Group Photos (Ingestion Source)
*   **Location:** Group photos are ingested from `uploads/` (defined in `backend/app/config.py`).
*   **Ingestion Logic:**
    *   The `/ingest/folder` endpoint iterates through all images in this directory.
    *   The `/ingest/upload` endpoint saves uploaded files to this directory before processing.
*   **Storage:** Uploaded files persist on disk in this folder. There is no separate "processed" folder; state is tracked in the PostgreSQL `processed_images` table.

## C. Unknown Person Logic
*   **Definition:** An "UNKNOWN" person is created whenever a detected face in a group photo does not match any known profile embedding with a cosine similarity score >= 0.45 (or fails the 0.05 margin check against the second best match).
*   **Mechanism:**
    1.  `ingest.py` detects faces.
    2.  If no match is found, it queries the DB for the last `UNKNOWN_{N}` ID.
    3.  It increments N and inserts a new row into the `persons` table (e.g., `UNKNOWN_0042`).
    4.  This "Unknown" person is now a permanent node in the graph and can have edges to other people.
*   **Impact:** This explains why `persons_total` grows beyond the number of profile folders. Every unmatched face in every group photo becomes a distinct identity in the database.

## D. Ego Network
*   **Definition:** The "Ego Network" is the subgraph consisting of a central person ("ego"), their direct connections ("alters"), and the connections between them (and potentially friends-of-friends).
*   **Computation:** The `/graph/ego` endpoint implements a Breadth-First Search (BFS) starting from the requested person's ID.
    *   **Depth:** Configurable (default 2). Depth 1 = direct neighbors. Depth 2 = neighbors + neighbors' neighbors.
    *   **Output:** Returns a list of `nodes` (people found) and `edges` (connections between any of those people) to allow for graph visualization on the frontend.

## E. Admin Actions & Demo Flow
*   **Rebuild Profile Index (`/admin/rebuild-profile-index`)**:
    *   **Destructive:** TRUNCATES `persons`, `person_profiles`, `uploads`, `faces`, `processed_images`.
    *   **Action:** Scans the (external) `PROFILES_DIR`, extracts embeddings, and populates `persons` and `person_profiles`.
    *   **Result:** A clean slate with *only* known identities. No graph edges exist yet.

*   **Reset Demo (`/admin/reset-demo`)**:
    *   **Semi-Destructive:** TRUNCATES `uploads`, `faces`, `edges`, `edge_evidence`, `processed_images`.
    *   **Preserves:** `persons` and `person_profiles`.
    *   **Use Case:** Clears the social graph and ingestion history so the same group photos can be re-ingested to "watch the graph grow" again, without needing to expensive re-scan the profile images.

*   **Ingest Folder (`/ingest/folder`)**:
    *   **Action:** Processes images in `uploads/` that are NOT in `processed_images`.
    *   **Result:** Detects faces, matches them (or creates Unknowns), and inserts `edges` (weighted connections) into the database.
