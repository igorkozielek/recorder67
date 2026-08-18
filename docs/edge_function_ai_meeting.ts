/**
 * Supabase Edge Function: ai-meeting-insights
 * 
 * Przyjmuje meetingId, pobiera transkrypcję i segmenty wypowiedzi ze spotkania,
 * wysyła do Google Gemini 2.5 Flash i generuje:
 * 1. Zwięzłe podsumowanie biznesowe (Executive Summary)
 * 2. Kluczowe ustalenia i decyzje
 * 3. Zadania (Action Items) z przypisaniem do osób i priorytetem
 * 4. Wąskie gardła / ryzyka
 */

import { createClient } from "https://esm.sh/@supabase/supabase-js@2.49.4";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type, x-supabase-client-platform, x-supabase-client-platform-version, x-supabase-client-runtime, x-supabase-client-runtime-version",
};

const MODEL = "gemini-2.5-flash";

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response(null, { headers: corsHeaders });

  try {
    const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
    const supabaseKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
    const geminiKey = Deno.env.get("GEMINI_API_KEY");
    if (!geminiKey) throw new Error("Brak klucza GEMINI_API_KEY w zmiennych środowiskowych");

    const supabase = createClient(supabaseUrl, supabaseKey);

    const { meetingId } = await req.json();
    if (!meetingId) {
      return new Response(JSON.stringify({ error: "Brak meetingId" }), {
        status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" },
      });
    }

    // 1. Pobierz dane spotkania
    const { data: meeting, error: meetingErr } = await supabase
      .from("meetings")
      .select("id, title, transcript, duration_seconds")
      .eq("id", meetingId)
      .single();

    if (meetingErr || !meeting) {
      return new Response(JSON.stringify({ error: "Spotkanie nie zostało znalezione" }), {
        status: 404, headers: { ...corsHeaders, "Content-Type": "application/json" },
      });
    }

    // 2. Pobierz segmenty z mówcami
    const { data: segments } = await supabase
      .from("meeting_segments")
      .select("speaker_name, start_time, end_time, text")
      .eq("meeting_id", meetingId)
      .order("start_time", { ascending: true });

    let dialogContent = meeting.transcript || "";
    if (segments && segments.length > 0) {
      dialogContent = segments
        .map((s: any) => `[${s.speaker_name}]: ${s.text}`)
        .join("\n");
    }

    const prompt = `Jesteś starszym analitykiem biznesowym i asystentem zarządu.
Przeanalizuj poniższy zapis rozmowy ze spotkania w biurze.

Zwróć odpowiedź w ścisłym formacie JSON zawierającym:
- "summary": zwięzłe podsumowanie wykonawcze (2-4 akapity po polsku),
- "key_decisions": lista podjętych ustaleń i decyzji (tablica stringów),
- "action_items": lista konkretnych zadań do wykonania (tablica obiektów { "title": string, "assignee_hint": string, "priority": "high"|"medium"|"low" }),
- "bottlenecks": lista zidentyfikowanych ryzyk, problemów lub wąskich gardeł (tablica stringów).

Rozmowa:
${dialogContent}`;

    const geminiRes = await fetch(
      `https://generativelanguage.googleapis.com/v1beta/models/${MODEL}:generateContent?key=${geminiKey}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          contents: [{ parts: [{ text: prompt }] }],
          generationConfig: {
            temperature: 0.2,
            responseMimeType: "application/json"
          },
        }),
      }
    );

    if (!geminiRes.ok) {
      const errText = await geminiRes.text();
      throw new Error(`Błąd Gemini API: ${errText}`);
    }

    const geminiData = await geminiRes.json();
    const rawJson = geminiData?.candidates?.[0]?.content?.parts?.[0]?.text?.trim() || "{}";
    const parsedAnalysis = JSON.parse(rawJson);

    // 3. Aktualizacja rekordu w bazie
    await supabase
      .from("meetings")
      .update({
        ai_summary: parsedAnalysis.summary || "",
        ai_notes: parsedAnalysis,
        ai_analyzed_at: new Date().toISOString()
      })
      .eq("id", meetingId);

    return new Response(JSON.stringify({ success: true, analysis: parsedAnalysis }), {
      headers: { ...corsHeaders, "Content-Type": "application/json" },
    });

  } catch (err: any) {
    return new Response(JSON.stringify({ error: err.message }), {
      status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
  }
});
