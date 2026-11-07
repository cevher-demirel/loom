CREATE TABLE auth_identities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            provider TEXT NOT NULL,
            subject TEXT NOT NULL,
            email TEXT,
            created_at TEXT NOT NULL,
            UNIQUE (provider, subject)
        );
CREATE TABLE connection_feedback (
            user_id INTEGER NOT NULL,
            connection_key TEXT NOT NULL,
            status TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, connection_key)
        );
CREATE TABLE dream_submissions (
            user_id INTEGER NOT NULL,
            request_id TEXT NOT NULL,
            payload_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            owner TEXT,
            dream_id INTEGER,
            result_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, request_id)
        );
CREATE TABLE dreams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            timestamp TEXT NOT NULL,
            raw_text TEXT NOT NULL,
            symbols TEXT,
            emotions TEXT,
            people TEXT,
            settings TEXT,
            themes TEXT,
            interpretation TEXT,
            embedding TEXT,
            conversation TEXT
        , location TEXT, symbol_icons TEXT, emotions_reported TEXT, emotions_plutchik TEXT, request_id TEXT);
CREATE TABLE element_interpretations (
            user_id INTEGER NOT NULL,
            symbol_key TEXT NOT NULL,
            symbol_label TEXT NOT NULL,
            teaser TEXT NOT NULL DEFAULT '',
            general_text TEXT NOT NULL DEFAULT '',
            journal_text TEXT NOT NULL DEFAULT '',
            direction TEXT NOT NULL DEFAULT '',
            occurrence_count INTEGER NOT NULL DEFAULT 0,
            latest_occurrence_date TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL, occurrence_fingerprint TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (user_id, symbol_key)
        );
CREATE TABLE entity_confirmations (
            user_id INTEGER NOT NULL,
            dream_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            concept_key TEXT NOT NULL,
            label TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (user_id, dream_id, category, concept_key)
        );
CREATE TABLE oauth_flows (
            state TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            nonce TEXT NOT NULL,
            code_verifier TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
CREATE TABLE oauth_tickets (
            ticket TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            user_id INTEGER,
            provider TEXT,
            subject TEXT,
            email TEXT,
            attempts INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
CREATE TABLE personal_meanings (
            user_id INTEGER NOT NULL,
            subject_type TEXT NOT NULL,
            subject_key TEXT NOT NULL,
            subject_label TEXT NOT NULL,
            meaning TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, subject_type, subject_key)
        );
CREATE TABLE profile (
                user_id INTEGER PRIMARY KEY,
                name TEXT,
                birth_year INTEGER,
                birthplace TEXT,
                current_location TEXT,
                bio TEXT,
                picture_path TEXT,
                birth_date TEXT,
                gender TEXT,
                relationship_status TEXT,
                picture_data TEXT
            );
CREATE TABLE symbol_chats (
            user_id INTEGER NOT NULL,
            symbol_key TEXT NOT NULL,
            symbol_label TEXT NOT NULL,
            conversation TEXT NOT NULL DEFAULT '[]',
            PRIMARY KEY (user_id, symbol_key)
        );
CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            token TEXT UNIQUE,
            token_created_at TEXT,
            created_at TEXT NOT NULL
        , is_guest INTEGER NOT NULL DEFAULT 0, reset_token TEXT, reset_token_created_at TEXT, email_verified INTEGER NOT NULL DEFAULT 0, verify_token TEXT, verify_token_created_at TEXT);
CREATE UNIQUE INDEX idx_dreams_user_request ON dreams(user_id, request_id);
