# Database schema (as implemented)

Created by Alembic revisions `209354ec1d11` (team's first schema) and `0003` (integration). Enum columns are plain
`VARCHAR` holding the enum value (portable, no native MySQL ENUM).

| Table | Purpose / notable columns |
|---|---|
| departments | name (unique); 10 seeded |
| users | firebase_uid (nullable), full_name, email (unique), staff_id (unique), role (admin / floor_incharge / maintenance / faculty / staff), department_id, is_active, password_hash (scrypt), failed_login_count, locked_until, last_login_at, fcm_token, notification_prefs |
| complaints | complaint_number (CN-00001), reported_by, reporter_department_id, responsible_department_id, block/floor/room_number, title, description, category, priority, status (registered→assigned→in_progress→resolved→closed), assigned_to/at, resolved_at, closed_at, safety_risk, needs_manual_review, sla_hours, sla_due_at, sla_warned, escalation_level |
| assignments | complaint_id, assigned_to, assigned_by (NULL = AI), assignment_type (manual / auto / claimed), notes |
| complaint_history | status timeline + remarks (old_status, new_status, changed_by, remarks) |
| complaint_events | detailed audit trail (registered, assigned, released, status_changed, remark, ai_review, sla_warning, escalated…) |
| complaint_images | image_path, thumbnail_path, original_name, content_type, size, width, height, sha256 |
| routing_rules | category (unique) → department_id (NULL = reporter's own department), is_active |
| ai_predictions | every AI/manual prediction: source, confidence, rationale, review fields |
| priority_matrix, priority_keyword_rules | rule-engine configuration |
| notifications | type, channel, status (pending/sent/failed/gave_up), retry_count, dedupe_key, is_read |
| refresh_tokens | hashed refresh-token ids with revocation / rotation chain |

Regenerate/verify: `alembic upgrade head && alembic check` (no pending model changes).
Offline SQL for review: `alembic upgrade head --sql` (generated for the SQLite dialect here; review MySQL output on your own server).
