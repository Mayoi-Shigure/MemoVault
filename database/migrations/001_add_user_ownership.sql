-- MANUAL WORKSHEET ONLY: no executable statements in this file.
-- Read README.md. Copy ONE phase, remove '-- | ' prefixes, replace placeholders.
-- Never SOURCE/uncomment the entire file. Stop on every failed checkpoint.
-- MySQL 8 / InnoDB; one-time upgrade from users + unowned types/notes.
-- Stop all writers; verify a restorable backup. DDL implicitly commits.
-- Never use --force, disable foreign_key_checks, or blindly rerun DDL.

-- 0. Preflight: confirm the old definitions against schema.sql and save baseline.
-- | USE memovault;
-- | SELECT DATABASE(), VERSION();
-- | SHOW CREATE TABLE users;
-- | SHOW CREATE TABLE types;
-- | SHOW CREATE TABLE notes;
-- | SELECT COUNT(*) AS notes_before FROM notes;
-- | SELECT COUNT(*) AS types_before FROM types;
-- | SELECT id, type_id FROM notes ORDER BY id;
-- | SELECT id, name, is_default FROM types ORDER BY id;
-- | SELECT COUNT(*) AS orphan_type_refs FROM notes n LEFT JOIN types t
-- |     ON t.id=n.type_id WHERE n.type_id IS NOT NULL AND t.id IS NULL;
-- | SELECT COUNT(*) AS null_user_created_at FROM users WHERE created_at IS NULL;
-- Require zero orphan references and NULL user timestamps. Save results locally.
-- types/notes must not have user_id yet. Confirm UNIQUE(name) and the old notes
-- type_id FK; record their actual names. Stop on other schema incompatibilities.

-- 1. OWNER CONFIRMATION: same database connection for all remaining phases.
-- Replace <LEGACY_OWNER_ID> with the confirmed EXISTING positive integer user ID.
-- That user must own ALL old records/types. No default owner is supplied.
-- | SET @legacy_owner_id = NULL;
-- | SET @legacy_owner_id = <LEGACY_OWNER_ID>;
-- | SELECT id, username FROM users WHERE id=@legacy_owner_id;
-- | SELECT COUNT(*) AS confirmed_owner_count FROM users
-- |     WHERE id=@legacy_owner_id AND @legacy_owner_id>0;
-- STOP unless exactly the intended user is returned and count is 1.
-- Missing users or mixed ownership require a separately reviewed plan.

-- 2. Add nullable ownership; stop after any failed ALTER.
-- | ALTER TABLE types ADD COLUMN user_id INT NULL;
-- | ALTER TABLE notes ADD COLUMN user_id INT NULL;

-- 3. Backfill transaction. An unset/invalid owner updates no rows.
-- | START TRANSACTION;
-- | UPDATE types SET user_id=@legacy_owner_id WHERE user_id IS NULL
-- |     AND EXISTS (SELECT 1 FROM users WHERE id=@legacy_owner_id AND id>0);
-- | UPDATE notes SET user_id=@legacy_owner_id WHERE user_id IS NULL
-- |     AND EXISTS (SELECT 1 FROM users WHERE id=@legacy_owner_id AND id>0);
-- | SELECT COUNT(*) AS total, COUNT(*)-COUNT(user_id) AS null_owners FROM types;
-- | SELECT COUNT(*) AS total, COUNT(*)-COUNT(user_id) AS null_owners FROM notes;
-- Execute phase 4 INSIDE this transaction before deciding whether to COMMIT.
-- Counts and original IDs/relationships must match the saved baseline.

-- 4. Validation: owner count must be 1; all other counts must be 0.
-- These checks also apply when there are no records/types.
-- | SELECT COUNT(*) AS confirmed_owner_count FROM users
-- |     WHERE id=@legacy_owner_id AND @legacy_owner_id>0;
-- | SELECT COUNT(*) AS null_type_owners FROM types WHERE user_id IS NULL;
-- | SELECT COUNT(*) AS null_note_owners FROM notes WHERE user_id IS NULL;
-- | SELECT COUNT(*) AS orphan_type_owners FROM types t LEFT JOIN users u ON u.id=t.user_id WHERE u.id IS NULL;
-- | SELECT COUNT(*) AS orphan_note_owners FROM notes n LEFT JOIN users u ON u.id=n.user_id WHERE u.id IS NULL;
-- | SELECT COUNT(*) AS orphan_type_refs FROM notes n LEFT JOIN types t ON t.id=n.type_id WHERE n.type_id IS NOT NULL AND t.id IS NULL;
-- | SELECT COUNT(*) AS cross_user_refs FROM notes n JOIN types t ON t.id=n.type_id WHERE n.user_id<>t.user_id;
-- | SELECT COUNT(*) AS unexpected_owners FROM (
-- |     SELECT user_id FROM notes WHERE NOT (user_id <=> @legacy_owner_id)
-- |     UNION ALL SELECT user_id FROM types WHERE NOT (user_id <=> @legacy_owner_id)
-- | ) AS unexpected;
-- On ANY failed check: execute ROLLBACK and STOP. Do not run later DDL.
-- Only after all checks pass, execute the following separately, then repeat checks:
-- | COMMIT;

-- 5. Tighten ownership and align canonical users.created_at.
-- Legacy DATETIME needs timezone/range/conversion review on an isolated copy.
-- Never silently coerce NULL/invalid timestamps. See README.md before ALTER.
-- | ALTER TABLE types MODIFY COLUMN user_id INT NOT NULL;
-- | ALTER TABLE notes MODIFY COLUMN user_id INT NOT NULL;
-- | ALTER TABLE users MODIFY COLUMN created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;

-- 6. User foreign keys, RESTRICT in both directions.
-- | ALTER TABLE types ADD CONSTRAINT fk_types_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT ON UPDATE RESTRICT;
-- | ALTER TABLE notes ADD CONSTRAINT fk_notes_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT ON UPDATE RESTRICT;

-- 7. Replace global type-name uniqueness; substitute its VERIFIED index name.
-- | ALTER TABLE types ADD UNIQUE KEY uq_types_user_name (user_id, name),
-- |     DROP INDEX `<OLD_TYPE_NAME_UNIQUE_INDEX>`;

-- 8. Supporting keys and composite ownership FK. Keep the old FK until verified.
-- | ALTER TABLE types ADD UNIQUE KEY uq_types_user_id (user_id, id);
-- | ALTER TABLE notes ADD INDEX ix_notes_user_type (user_id, type_id);
-- | ALTER TABLE notes ADD CONSTRAINT fk_notes_user_type
-- |     FOREIGN KEY (user_id, type_id) REFERENCES types(user_id, id)
-- |     ON DELETE RESTRICT ON UPDATE RESTRICT;
-- | SHOW CREATE TABLE notes;
-- | SHOW CREATE TABLE types;
-- STOP unless both FKs exist with the expected columns/actions.

-- 9. Remove ONLY the verified old single-column FK, using its actual name.
-- | ALTER TABLE notes DROP FOREIGN KEY `<OLD_NOTES_TYPE_FK>`;
-- A redundant old type_id index may remain; it does not change constraints.

-- 10. Repeat phase 4 SELECTs, compare baseline counts and original IDs/type_ids,
-- and compare important constraints with schema.sql before restarting the app.
-- | SELECT COUNT(*) AS notes_after FROM notes;
-- | SELECT COUNT(*) AS types_after FROM types;
-- | SELECT id, user_id, type_id FROM notes ORDER BY id;
-- | SELECT id, user_id, name, is_default FROM types ORDER BY id;
-- | SHOW CREATE TABLE users;
-- | SHOW CREATE TABLE types;
-- | SHOW CREATE TABLE notes;
-- Never publish backups or query results. Registration creates default types.
