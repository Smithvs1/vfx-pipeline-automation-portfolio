-- SignedIt Social Content Automation
-- Run these in order in the Supabase SQL Editor

-- 1. Prompt templates
CREATE TABLE IF NOT EXISTS si_prompts (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  post_type    text NOT NULL CHECK (post_type IN ('REEL', 'STATIC', 'CAROUSEL')),
  focus_type   text NOT NULL CHECK (focus_type IN ('N', 'C', 'A')),
  name         text NOT NULL,
  prompt_text  text NOT NULL,
  active       boolean NOT NULL DEFAULT true,
  created_at   timestamptz NOT NULL DEFAULT now()
);

-- 2. 90-topic bank (30 per post type × 3 types)
CREATE TABLE IF NOT EXISTS si_topics (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  post_type   text NOT NULL CHECK (post_type IN ('REEL', 'STATIC', 'CAROUSEL')),
  focus_type  text NOT NULL CHECK (focus_type IN ('N', 'C', 'A')),
  day_slot    int  NOT NULL CHECK (day_slot BETWEEN 1 AND 30),
  topic       text NOT NULL,
  notes       text,
  UNIQUE (post_type, day_slot)
);

-- 3. Weekly tone schedule (21 rows: 7 days × 3 post types)
CREATE TABLE IF NOT EXISTS si_day_schedule (
  day_of_week  int  NOT NULL CHECK (day_of_week BETWEEN 0 AND 6), -- 0=Mon, 6=Sun
  post_type    text NOT NULL CHECK (post_type IN ('REEL', 'STATIC', 'CAROUSEL')),
  focus_type   text NOT NULL CHECK (focus_type IN ('N', 'C', 'A')),
  PRIMARY KEY (day_of_week, post_type)
);

-- 4. Generated + published posts
CREATE TABLE IF NOT EXISTS si_generated_posts (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scheduled_date      date NOT NULL,
  post_type           text NOT NULL,
  focus_type          text NOT NULL,
  topic_id            uuid REFERENCES si_topics(id),
  prompt_id           uuid REFERENCES si_prompts(id),
  topic_text          text NOT NULL,
  generated_json      jsonb,
  image_urls          jsonb,         -- array of public image URLs from Pexels/Unsplash
  media_source        text,          -- 'pexels' or 'unsplash'
  safety_status       text NOT NULL DEFAULT 'PENDING' CHECK (safety_status IN ('PENDING','SAFE','UNSAFE')),
  safety_result       jsonb,
  linkedin_post_id    text,
  instagram_post_id   text,
  publish_status      text NOT NULL DEFAULT 'DRAFT' CHECK (publish_status IN ('DRAFT','PUBLISHED','FAILED')),
  error_log           text,
  created_at          timestamptz NOT NULL DEFAULT now()
);

-- 5. Cycle tracker — stores the date day_slot 1 began
CREATE TABLE IF NOT EXISTS si_cycle_tracker (
  id           int PRIMARY KEY DEFAULT 1,
  cycle_start  date NOT NULL,
  updated_at   timestamptz NOT NULL DEFAULT now()
);

-- Seed cycle start to today when first running
INSERT INTO si_cycle_tracker (id, cycle_start)
VALUES (1, CURRENT_DATE)
ON CONFLICT (id) DO NOTHING;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_si_generated_posts_date ON si_generated_posts (scheduled_date);
CREATE INDEX IF NOT EXISTS idx_si_topics_slot ON si_topics (post_type, day_slot);
CREATE INDEX IF NOT EXISTS idx_si_prompts_type ON si_prompts (post_type, focus_type, active);
-- Token store for auto-refreshing Instagram (and storing LinkedIn) tokens.
-- Tokens are read by the daily content script at startup.
-- Instagram tokens are automatically refreshed when < 14 days remain.

CREATE TABLE IF NOT EXISTS si_token_store (
  key           text PRIMARY KEY,
  value         text NOT NULL,
  refreshed_at  timestamptz NOT NULL DEFAULT now(),
  expires_at    timestamptz NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now()
);

-- Enable RLS but allow service_role full access (script uses service key)
ALTER TABLE si_token_store ENABLE ROW LEVEL SECURITY;

CREATE POLICY "service_role_all" ON si_token_store
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);
