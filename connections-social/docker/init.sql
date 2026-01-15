-- Connections Social DB Schema
-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Persons: known identities from profile index
CREATE TABLE persons (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Person profiles: face embeddings for each known person
CREATE TABLE person_profiles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    person_id UUID NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    source_image TEXT NOT NULL,
    embedding BYTEA NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_person_profiles_person_id ON person_profiles(person_id);

-- Uploads: user-uploaded images for processing
CREATE TABLE uploads (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    image_path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_uploads_status ON uploads(status);
CREATE INDEX idx_uploads_created_at ON uploads(created_at);

-- Faces: detected faces in uploaded images
CREATE TABLE faces (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    upload_id UUID NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
    bbox JSONB NOT NULL,
    embedding BYTEA NOT NULL,
    matched_person_id UUID REFERENCES persons(id) ON DELETE SET NULL,
    score FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_faces_upload_id ON faces(upload_id);
CREATE INDEX idx_faces_matched_person_id ON faces(matched_person_id);

-- Edges: connections between persons (ordered pair, person_a_id < person_b_id)
CREATE TABLE edges (
    person_a_id UUID NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    person_b_id UUID NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
    weight INT NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (person_a_id, person_b_id),
    CONSTRAINT edges_ordered_pair CHECK (person_a_id < person_b_id)
);

CREATE INDEX idx_edges_person_a ON edges(person_a_id);
CREATE INDEX idx_edges_person_b ON edges(person_b_id);

-- Edge evidence: photos that prove an edge exists
CREATE TABLE edge_evidence (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    person_a_id UUID NOT NULL,
    person_b_id UUID NOT NULL,
    upload_id UUID NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    FOREIGN KEY (person_a_id, person_b_id) REFERENCES edges(person_a_id, person_b_id) ON DELETE CASCADE
);

CREATE INDEX idx_edge_evidence_edge ON edge_evidence(person_a_id, person_b_id);
CREATE INDEX idx_edge_evidence_upload ON edge_evidence(upload_id);
