-- Athlete Lookalike Database Schema

-- Athletes table - stores all known athletes
CREATE TABLE IF NOT EXISTS athletes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    league VARCHAR(50) NOT NULL,  -- 'nba' or 'nfl'
    team VARCHAR(255),
    position VARCHAR(50),
    external_id VARCHAR(100),  -- ESPN/NBA/NFL API player ID
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name, league)
);

-- Athlete profiles - face embeddings for each athlete
CREATE TABLE IF NOT EXISTS athlete_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    athlete_id UUID NOT NULL REFERENCES athletes(id) ON DELETE CASCADE,
    image_path VARCHAR(500),
    embedding BYTEA NOT NULL,  -- 512-dim float32 vector (2048 bytes)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Comparison history - track user comparisons (optional)
CREATE TABLE IF NOT EXISTS comparison_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id VARCHAR(100),
    matched_athlete_id UUID REFERENCES athletes(id),
    similarity_score FLOAT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_athletes_league ON athletes(league);
CREATE INDEX IF NOT EXISTS idx_athletes_name ON athletes(name);
CREATE INDEX IF NOT EXISTS idx_athlete_profiles_athlete ON athlete_profiles(athlete_id);
CREATE INDEX IF NOT EXISTS idx_comparison_history_athlete ON comparison_history(matched_athlete_id);
CREATE INDEX IF NOT EXISTS idx_comparison_history_created ON comparison_history(created_at);
