// TS mirror of src/activist/api/schemas.py. Small and stable; kept by hand.

export interface Flag {
  severity: 'error' | 'warn';
  policy: string;
  rule: string;
  detail: string;
}

export interface Content {
  id: string;
  kind: string;
  status: string;
  text: string;
  original_text: string | null;
  created: string;
  identity: string;
  scheduled_for: string | null;
  not_before: string;
  source_url: string;
  source_title: string;
  opinion_keys: string[];
  opinion_change: OpinionChange | null;
  flags: Flag[];
  engine: string;
  in_reply_to_status_id: string;
  reply_to_author: string;
  reply_to_text: string;
  visibility: string;
  mastodon_status_id: string;
  published_url: string;
  published_at: string;
  rejected_reason: string;
  updated_at: string;
  char_count: number;
  over_limit: boolean;
  is_reply: boolean;
  error_count: number;
  warn_count: number;
}

export interface OpinionChange {
  key: string;
  old_stance: string;
  new_stance: string;
  trigger_item: string;
  reason: string;
}

export interface Event {
  ts: string;
  content_id: string;
  actor: string;
  action: string;
  detail: string;
}

export interface ContentDetail {
  content: Content;
  events: Event[];
}

export interface Persona {
  persona_id: string;
  name: string;
  handle: string;
  bio: string;
  disclosure: string;
  active: boolean;
}

export interface Account {
  mastodon_id: string;
  base_url: string;
  instances: string[];
  handle: string | null;
  verified: boolean;
}

export interface EngineProfile {
  engine: string;
  model: string | null;
  moderation_engine: string;
  poster_live: boolean;
  default_visibility: string;
}

export interface Profile {
  persona: Persona;
  account: Account;
  engine: EngineProfile;
  counts: Record<string, number>;
  last_fetch: Event | null;
  live_edit_available: boolean;
}

export const STATUSES = [
  'pending_review',
  'approved',
  'published',
  'rejected',
  'failed',
  'publishing',
] as const;
