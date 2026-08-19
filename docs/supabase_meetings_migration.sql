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
    client_id UUID,
    created_by UUID,
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

-- Upewnienie się, że ON DELETE CASCADE jest aktywne na kluczu obcym
ALTER TABLE public.meeting_segments
DROP CONSTRAINT IF EXISTS meeting_segments_meeting_id_fkey;

ALTER TABLE public.meeting_segments
ADD CONSTRAINT meeting_segments_meeting_id_fkey
  FOREIGN KEY (meeting_id)
  REFERENCES public.meetings(id)
  ON DELETE CASCADE;

-- Indeksy dla szybkiego wyszukiwania
CREATE INDEX IF NOT EXISTS idx_meetings_created_at ON public.meetings(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_meetings_client_id ON public.meetings(client_id);
CREATE INDEX IF NOT EXISTS idx_meeting_segments_meeting_id ON public.meeting_segments(meeting_id);

-- 3. Uprawnienia Postgres (GRANT) dla roli anon, authenticated i service_role
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
GRANT ALL ON TABLE public.meetings TO anon, authenticated, service_role;
GRANT ALL ON TABLE public.meeting_segments TO anon, authenticated, service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated, service_role;

-- 4. Uprawnienia Row Level Security (RLS)
ALTER TABLE public.meetings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.meeting_segments ENABLE ROW LEVEL SECURITY;

-- Meetings: Pełny dostęp dla aplikacji
DROP POLICY IF EXISTS "Meetings are viewable" ON public.meetings;
CREATE POLICY "Meetings are viewable" ON public.meetings FOR SELECT TO authenticated, anon USING (true);

DROP POLICY IF EXISTS "Meetings can be inserted" ON public.meetings;
CREATE POLICY "Meetings can be inserted" ON public.meetings FOR INSERT TO authenticated, anon WITH CHECK (true);

DROP POLICY IF EXISTS "Meetings can be updated" ON public.meetings;
CREATE POLICY "Meetings can be updated" ON public.meetings FOR UPDATE TO authenticated, anon USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Meetings can be deleted" ON public.meetings;
CREATE POLICY "Meetings can be deleted" ON public.meetings FOR DELETE TO authenticated, anon USING (true);

-- Meeting Segments: Pełny dostęp dla aplikacji
DROP POLICY IF EXISTS "Meeting segments viewable" ON public.meeting_segments;
CREATE POLICY "Meeting segments viewable" ON public.meeting_segments FOR SELECT TO authenticated, anon USING (true);

DROP POLICY IF EXISTS "Meeting segments insertable" ON public.meeting_segments;
CREATE POLICY "Meeting segments insertable" ON public.meeting_segments FOR INSERT TO authenticated, anon WITH CHECK (true);

DROP POLICY IF EXISTS "Meeting segments updatable" ON public.meeting_segments;
CREATE POLICY "Meeting segments updatable" ON public.meeting_segments FOR UPDATE TO authenticated, anon USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Meeting segments deletable" ON public.meeting_segments;
CREATE POLICY "Meeting segments deletable" ON public.meeting_segments FOR DELETE TO authenticated, anon USING (true);

-- 5. Utworzenie dedykowanego bucketu Storage dla spotkań ('meeting-recordings') oraz 'voice-notes'
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES 
  ('meeting-recordings', 'meeting-recordings', true, 104857600, ARRAY['audio/wav', 'audio/mpeg', 'audio/mp3', 'audio/ogg', 'audio/m4a']),
  ('voice-notes', 'voice-notes', true, 104857600, ARRAY['audio/wav', 'audio/mpeg', 'audio/mp3', 'audio/ogg', 'audio/m4a'])
ON CONFLICT (id) DO UPDATE SET 
  public = true,
  file_size_limit = 104857600;

-- Polityki RLS dla Storage
DROP POLICY IF EXISTS "Meeting recordings storage insertable" ON storage.objects;
CREATE POLICY "Meeting recordings storage insertable" ON storage.objects FOR INSERT TO authenticated, anon WITH CHECK (bucket_id IN ('meeting-recordings', 'voice-notes'));

DROP POLICY IF EXISTS "Meeting recordings storage readable" ON storage.objects;
CREATE POLICY "Meeting recordings storage readable" ON storage.objects FOR SELECT TO authenticated, anon USING (bucket_id IN ('meeting-recordings', 'voice-notes'));

DROP POLICY IF EXISTS "Meeting recordings storage updatable" ON storage.objects;
CREATE POLICY "Meeting recordings storage updatable" ON storage.objects FOR UPDATE TO authenticated, anon USING (bucket_id IN ('meeting-recordings', 'voice-notes'));

DROP POLICY IF EXISTS "Meeting recordings storage deletable" ON storage.objects;
CREATE POLICY "Meeting recordings storage deletable" ON storage.objects FOR DELETE TO authenticated, anon USING (bucket_id IN ('meeting-recordings', 'voice-notes'));

