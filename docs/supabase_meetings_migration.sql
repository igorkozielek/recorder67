-- ==============================================================================
-- MIGRACJA SUPABASE: Moduł Spotkań Biurowych (Ambient Meeting Intelligence)
-- ==============================================================================


-- 1. Tabela główna spotkań biurowych (izolowana, nie modyfikuje voice_notes)
CREATE TABLE IF NOT EXISTS public.meetings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    title TEXT NOT NULL,
    duration_seconds INTEGER NOT NULL DEFAULT 0,
    audio_url TEXT,
    transcript TEXT,
    status TEXT NOT NULL DEFAULT 'completed', -- 'processing', 'completed', 'failed'
    context_type TEXT NOT NULL DEFAULT 'general', -- 'general', 'client', 'crm_deal', 'task'
    context_id UUID,
    client_id UUID REFERENCES public.clients(id) ON DELETE SET NULL,
    created_by UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    device_name TEXT DEFAULT 'Biuro-Stanowisko-1',
    speaker_count INTEGER DEFAULT 1,
    ai_summary TEXT,
    ai_notes JSONB,
    ai_analyzed_at TIMESTAMPTZ,
    is_archived BOOLEAN NOT NULL DEFAULT false
);

-- 2. Tabela szczegółowych segmentów wypowiedzi per osoba (Word/Speaker level)
CREATE TABLE IF NOT EXISTS public.meeting_segments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meeting_id UUID NOT NULL REFERENCES public.meetings(id) ON DELETE CASCADE,
    speaker_name TEXT NOT NULL DEFAULT 'Mówca',
    start_time NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    end_time NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indeksy dla szybkiego wyszukiwania
CREATE INDEX IF NOT EXISTS idx_meetings_created_at ON public.meetings(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_meetings_client_id ON public.meetings(client_id);
CREATE INDEX IF NOT EXISTS idx_meeting_segments_meeting_id ON public.meeting_segments(meeting_id);

-- 3. Uprawnienia Row Level Security (RLS)
ALTER TABLE public.meetings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.meeting_segments ENABLE ROW LEVEL SECURITY;

-- Meetings: SELECT, INSERT, UPDATE dla zalogowanych i aplikacji biurowej
DROP POLICY IF EXISTS "Meetings are viewable" ON public.meetings;
CREATE POLICY "Meetings are viewable"
ON public.meetings FOR SELECT
TO authenticated, anon
USING (true);

DROP POLICY IF EXISTS "Meetings can be inserted" ON public.meetings;
CREATE POLICY "Meetings can be inserted"
ON public.meetings FOR INSERT
TO authenticated, anon
WITH CHECK (true);

DROP POLICY IF EXISTS "Meetings can be updated" ON public.meetings;
CREATE POLICY "Meetings can be updated"
ON public.meetings FOR UPDATE
TO authenticated, anon
USING (true)
WITH CHECK (true);

-- Meeting Segments: SELECT, INSERT, UPDATE, DELETE
DROP POLICY IF EXISTS "Meeting segments viewable" ON public.meeting_segments;
CREATE POLICY "Meeting segments viewable"
ON public.meeting_segments FOR SELECT
TO authenticated, anon
USING (true);

DROP POLICY IF EXISTS "Meeting segments insertable" ON public.meeting_segments;
CREATE POLICY "Meeting segments insertable"
ON public.meeting_segments FOR INSERT
TO authenticated, anon
WITH CHECK (true);

DROP POLICY IF EXISTS "Meeting segments deletable" ON public.meeting_segments;
CREATE POLICY "Meeting segments deletable"
ON public.meeting_segments FOR DELETE
TO authenticated, anon
USING (true);

-- 4. Uprawnienia Storage (bucket: voice-notes)
INSERT INTO storage.buckets (id, name, public)
VALUES ('voice-notes', 'voice-notes', true)
ON CONFLICT (id) DO NOTHING;

DROP POLICY IF EXISTS "Voice notes storage insertable" ON storage.objects;
CREATE POLICY "Voice notes storage insertable"
ON storage.objects FOR INSERT
TO authenticated, anon
WITH CHECK (bucket_id = 'voice-notes');

DROP POLICY IF EXISTS "Voice notes storage readable" ON storage.objects;
CREATE POLICY "Voice notes storage readable"
ON storage.objects FOR SELECT
TO authenticated, anon
USING (bucket_id = 'voice-notes');

