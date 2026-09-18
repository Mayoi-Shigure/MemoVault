# Manual ownership migration

`001_add_user_ownership.sql` is a one-time manual worksheet, not an executable migration. Every SQL line is commented with `-- | `. Running the whole file makes no database changes. Never uncomment it wholesale or pass it to an automatic migration runner.

Fresh installations use `../schema.sql`. This upgrade requires existing `users`, `types`, and `notes` tables, with no `user_id` in the latter two. A database with only an early `notes` table, no suitable user, mixed ownership, or a partially completed migration needs a separate reviewed plan.

## Before starting

1. Stop all application processes, registration endpoints and background writers until final verification finishes.
2. Back up structure and data and verify restoration in an isolated environment. Keep backups in ignored `backups/` or a secure location outside the repository. Never put passwords on command lines or commit backups, query results, or account lists.
3. Rehearse on an isolated MySQL 8 / InnoDB copy. Check version, strict SQL mode, column types, collations, indexes and foreign keys. Compare all definitions with `schema.sql`; fields outside this migration must already have compatible important constraints. Stop on discrepancies.
4. Save baseline row counts and original ID/type relationships locally. There are no assumed counts or record IDs. Resolve orphan references and NULL/invalid user timestamps before proceeding, using a separately reviewed data correction plan.

## Required operator choices

Copy only the statements for the current phase, remove their `-- | ` prefixes, and replace its placeholders. Placeholders cannot execute unchanged.

| Placeholder | Required choice |
|---|---|
| `<LEGACY_OWNER_ID>` | Positive integer ID of an existing user explicitly confirmed to own ALL legacy records and types. Never assume the first user or a fixed ID. |
| `<OLD_TYPE_NAME_UNIQUE_INDEX>` | Actual global `UNIQUE(name)` index name from `SHOW CREATE TABLE types`. |
| `<OLD_NOTES_TYPE_FK>` | Actual old single-column `type_id -> types.id` foreign key name from `SHOW CREATE TABLE notes`. |

Phase 1 first clears `@legacy_owner_id`, then requires an explicit assignment and local identity/ownership confirmation. Exactly one intended account must match. If no appropriate account exists, stop: this worksheet does not create users or passwords. Keep the same database connection throughout; reconnecting loses the variable and requires fresh confirmation.

Backfill also requires the owner to exist: an unset or invalid owner updates no rows. This is only a defensive check. SQL cannot decide whether an existing account truly owns the data. Owner confirmation is mandatory even for empty tables.

## Order and checkpoints

| Phase | Action and condition to continue |
|---|---|
| 0-1 | Verify old structure, save baseline, explicitly confirm owner. Stop on any failed prerequisite. |
| 2 | Add nullable ownership columns, verifying each ALTER. |
| 3-4 | Backfill both tables in one transaction. Before COMMIT, run all phase 4 SELECTs: owner count 1, all invalid counts 0, original row counts and IDs/relationships preserved. Commit separately only after confirmation; otherwise ROLLBACK and stop. Repeat SELECTs after commit. |
| 5 | Make owner columns NOT NULL and align the user creation timestamp. |
| 6-7 | Add user foreign keys and replace global name uniqueness with `UNIQUE(user_id, name)`. |
| 8 | Add composite candidate key, child index and `(user_id, type_id)` foreign key. Verify old and new FKs both exist. |
| 9 | Remove the old single-column FK only after the new FK is verified. |
| 10 | Repeat relationship checks and compare baseline data and canonical constraints before restarting the app. |

## Canonical schema and timestamps

Both fresh and upgraded databases use `users.created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP`, preserving the original user-table timestamp semantics. The worksheet explicitly sets that definition, and the fresh schema uses it too. The existing DATETIME definitions for note timestamps remain unchanged.

For a legacy DATETIME column, do not convert blindly. First inspect NULL/invalid values, the TIMESTAMP representable range, historical timezone meaning and connection timezone on an isolated copy, then compare values before and after conversion. Do not use non-strict mode to silently truncate or replace dates. Stop and design a separate conversion if semantics are uncertain. An already-correct TIMESTAMP definition needs no semantic conversion.

The final important constraints must match `schema.sql`: unique username/email, non-null owner IDs, user foreign keys, per-user type-name uniqueness, composite type candidate key, and composite ownership FK with RESTRICT update/delete actions. Old index names or an extra redundant index may differ without changing constraints; do not drop indexes solely for cosmetic consistency.

## Recovery and verification limits

MySQL DDL implicitly commits. ROLLBACK can undo only the uncommitted backfill transaction, not ALTER TABLE. Never use `--force`, disable foreign key checks, rerun the whole worksheet, or continue after errors. Keep errors and structure output locally; inspect completed steps before deciding to resume or restore a verified backup.

The offline suite is `python -m unittest discover -v`. Mock/SQLite tests cannot validate MySQL ALTER, locking, implicit commits, timestamp conversion or complete collation behavior. Publishing this worksheet does not mean it has been executed or validated against a live MySQL database.
