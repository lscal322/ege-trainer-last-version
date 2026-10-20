-- Source of truth for the Replit-managed PostgreSQL schema.
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    xp INTEGER NOT NULL DEFAULT 0,
    tests_completed INTEGER NOT NULL DEFAULT 0,
    avatar_emoji TEXT NOT NULL DEFAULT '',
    avatar_color TEXT NOT NULL DEFAULT '#2563eb',
    avatar_image BYTEA,
    avatar_image_mime TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    is_admin INTEGER NOT NULL DEFAULT 0,
    disabled INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE questions (
    id BIGSERIAL PRIMARY KEY,
    subject TEXT NOT NULL,
    part TEXT NOT NULL,
    task_number INTEGER NOT NULL DEFAULT 1,
    section TEXT NOT NULL DEFAULT '',
    difficulty TEXT NOT NULL DEFAULT 'base',
    text TEXT NOT NULL,
    options TEXT NOT NULL,
    correct_index INTEGER NOT NULL,
    answer_type TEXT NOT NULL DEFAULT 'choice',
    correct_answer TEXT NOT NULL DEFAULT '',
    accepted_answers TEXT NOT NULL DEFAULT '[]',
    explanation TEXT,
    wrong_explanations TEXT DEFAULT '{}',
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE test_results (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    subject TEXT NOT NULL,
    score INTEGER NOT NULL,
    questions_count INTEGER NOT NULL DEFAULT 0,
    mode TEXT NOT NULL DEFAULT 'quiz',
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE question_attempts (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    question_id BIGINT NOT NULL REFERENCES questions(id),
    answer_idx INTEGER NOT NULL,
    answer_text TEXT NOT NULL DEFAULT '',
    is_correct INTEGER NOT NULL DEFAULT 0,
    time_sec INTEGER NOT NULL DEFAULT 0,
    mode TEXT NOT NULL DEFAULT 'quiz',
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE exam_sessions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    subject TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'exam',
    time_limit_min INTEGER NOT NULL DEFAULT 235,
    started_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP WITHOUT TIME ZONE,
    score INTEGER,
    correct INTEGER,
    total INTEGER,
    answers_json TEXT DEFAULT '{}'
);

CREATE TABLE mistake_bank (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    question_id BIGINT NOT NULL REFERENCES questions(id),
    wrong_answer_idx INTEGER NOT NULL,
    wrong_answer_text TEXT NOT NULL DEFAULT '',
    review_count INTEGER NOT NULL DEFAULT 0,
    next_review TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, question_id)
);

CREATE TABLE essay_submissions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    subject TEXT NOT NULL,
    essay_type TEXT NOT NULL DEFAULT 'ege',
    essay_prompt_id BIGINT,
    essay_topic TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL,
    word_count INTEGER NOT NULL DEFAULT 0,
    checklist_json TEXT DEFAULT '{}',
    self_score INTEGER DEFAULT 0,
    teacher_score INTEGER,
    teacher_result TEXT,
    teacher_comment TEXT,
    teacher_criteria_json TEXT DEFAULT '{}',
    teacher_graded_at TIMESTAMP WITHOUT TIME ZONE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    resubmit_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE essay_prompts (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL UNIQUE,
    source_text TEXT NOT NULL,
    problem TEXT NOT NULL,
    analysis TEXT NOT NULL,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE theory_sections (
    id BIGSERIAL PRIMARY KEY,
    subject TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    order_index INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE task_analyses (
    id BIGSERIAL PRIMARY KEY,
    subject TEXT NOT NULL,
    task_number INTEGER NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL
);

CREATE TABLE guides (
    id BIGSERIAL PRIMARY KEY,
    subject TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    url TEXT
);

CREATE TABLE news_items (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    year INTEGER NOT NULL DEFAULT 2026,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    subject TEXT NOT NULL DEFAULT ''
);

CREATE TABLE news_suggestions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '',
    year INTEGER NOT NULL DEFAULT 2026,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending','published','rejected')),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TIMESTAMP WITHOUT TIME ZONE,
    reviewed_by BIGINT REFERENCES users(id)
);

CREATE INDEX idx_news_suggestions_user ON news_suggestions(user_id, id);
CREATE INDEX idx_news_suggestions_status ON news_suggestions(status, id);

CREATE TABLE support_tickets (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subject TEXT NOT NULL,
    question TEXT NOT NULL,
    admin_reply TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open'
        CHECK(status IN ('open','answered')),
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    replied_at TIMESTAMP WITHOUT TIME ZONE,
    replied_by BIGINT REFERENCES users(id)
);

CREATE INDEX idx_support_tickets_user ON support_tickets(user_id, id);
CREATE INDEX idx_support_tickets_status ON support_tickets(status, updated_at);

CREATE TABLE practice_sessions (
    id TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    subject TEXT NOT NULL,
    mode TEXT NOT NULL,
    question_ids_json TEXT NOT NULL,
    result_json TEXT,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE web_sessions (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    expires_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE auth_throttle (
    key TEXT PRIMARY KEY,
    attempts INTEGER NOT NULL DEFAULT 0,
    window_start DOUBLE PRECISION NOT NULL
);
