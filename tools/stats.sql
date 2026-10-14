-- Who has used the app (users appear when they accept the terms or first transcribe).
SELECT count(*) AS users_who_started FROM users;
SELECT count(DISTINCT user_id) AS users_with_a_transcription,
       count(*) AS transcriptions,
       count(*) FILTER (WHERE created_at > now() - interval '7 days') AS transcriptions_last_7_days,
       count(*) FILTER (WHERE status = 'failed') AS failed
  FROM jobs;
SELECT count(*) AS devices_with_notifications FROM push_tokens;
