import re
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional
from collections import Counter, defaultdict


# Baza popularnych polskich imion oraz ich form odmiennych / zdrobnień
POLISH_NAMES_MAP = {
    # Męskie
    "łukasz": "Łukasz", "łukaszu": "Łukasz", "łukasza": "Łukasz", "łukaszem": "Łukasz", "łukaszkowi": "Łukasz",
    "radek": "Radek", "radziu": "Radek", "radka": "Radek", "radkiem": "Radek", "radkowi": "Radek", "radosław": "Radosław",
    "szymon": "Szymon", "szymonie": "Szymon", "szymona": "Szymon", "szymonem": "Szymon", "szymonowi": "Szymon", "szymek": "Szymon",
    "adrian": "Adrian", "adrianie": "Adrian", "adriana": "Adrian", "adrianem": "Adrian", "adrianowi": "Adrian", "adi": "Adrian",
    "tomek": "Tomek", "tomku": "Tomek", "tomka": "Tomek", "tomasz": "Tomasz", "tomaszu": "Tomasz",
    "paweł": "Paweł", "pawle": "Paweł", "pawła": "Paweł", "pawełku": "Paweł", "pawłowi": "Paweł",
    "piotr": "Piotr", "piotrze": "Piotr", "piotrek": "Piotr", "piotrku": "Piotr", "piotra": "Piotr", "piotrowi": "Piotr",
    "michał": "Michał", "michale": "Michał", "michała": "Michał", "misiek": "Michał", "michałowi": "Michał",
    "krzysztof": "Krzysztof", "krzysztofie": "Krzysztof", "krzysiek": "Krzysztof", "krzysiu": "Krzysztof", "krzysztofa": "Krzysztof",
    "marcin": "Marcin", "marcinie": "Marcin", "marcina": "Marcin", "marcinowi": "Marcin",
    "marek": "Marek", "marku": "Marek", "marka": "Marek", "markowi": "Marek",
    "kuba": "Kuba", "kubo": "Kuba", "kubie": "Kuba", "jakub": "Jakub", "jakubie": "Jakub",
    "adam": "Adam", "adamie": "Adam", "adama": "Adam", "adamowi": "Adam",
    "bartek": "Bartek", "bartku": "Bartek", "bartosz": "Bartosz", "bartoszu": "Bartosz",
    "mateusz": "Mateusz", "mateuszu": "Mateusz", "mati": "Mateusz",
    "przemek": "Przemek", "przemku": "Przemek", "przemysław": "Przemysław",
    "dawid": "Dawid", "dawidzie": "Dawid", "dawida": "Dawid",
    "kamil": "Kamil", "kamilu": "Kamil", "kamila": "Kamil",
    "grzegorz": "Grzegorz", "grzegorzu": "Grzegorz", "grzesiek": "Grzegorz", "grzesiu": "Grzegorz",
    "wojtek": "Wojtek", "wojtku": "Wojtek", "wojciech": "Wojciech",
    "robert": "Robert", "robercie": "Robert", "roberta": "Robert",
    "igor": "Igor", "igorze": "Igor", "igora": "Igor",
    "maciek": "Maciek", "maćku": "Maciek", "maciej": "Maciej", "macieju": "Maciej",
    "artur": "Artur", "arturze": "Artur", "artura": "Artur",
    "sebastian": "Sebastian", "sebastianie": "Sebastian", "seba": "Sebastian",
    "damian": "Damian", "damianie": "Damian", "damiana": "Damian",
    "patryk": "Patryk", "patryku": "Patryk", "patryka": "Patryk",
    "dominik": "Dominik", "dominiku": "Dominik",
    "kacper": "Kacper", "kacprze": "Kacper", "kacpra": "Kacper",
    "rafał": "Rafał", "rafała": "Rafał", "rafale": "Rafał", "rafałem": "Rafał",

    # Żeńskie
    "kasia": "Kasia", "kasiu": "Kasia", "kasię": "Kasia", "katarzyna": "Katarzyna", "kasi": "Kasia",
    "ania": "Ania", "aniu": "Ania", "anię": "Ania", "anna": "Anna",
    "jola": "Jola", "jolu": "Jola", "jolę": "Jola", "jolka": "Jola", "jolku": "Jola", "jolkę": "Jola", "jolanta": "Jolanta",
    "iza": "Iza", "izo": "Iza", "izę": "Iza", "izabela": "Izabela",
    "daria": "Daria", "dario": "Daria", "darię": "Daria",
    "gabriela": "Gabriela", "gabrysiu": "Gabriela", "gabrysia": "Gabriela", "gabrysię": "Gabriela",
    "ola": "Ola", "olu": "Ola", "olę": "Ola", "aleksandra": "Aleksandra",
    "magda": "Magda", "magdo": "Magda", "magdę": "Magda", "magdalena": "Magdalena",
    "monika": "Monika", "moniko": "Monika", "monikę": "Monika",
    "natalia": "Natalia", "natalio": "Natalia", "natalię": "Natalia", "natalka": "Natalia",
    "karolina": "Karolina", "karolino": "Karolina", "karolinę": "Karolina",
    "paulina": "Paulina", "paulino": "Paulina", "paulinę": "Paulina",
    "justyna": "Justyna", "justyno": "Justyna", "justynę": "Justyna",
    "agnieszka": "Agnieszka", "agnieszko": "Agnieszka", "agnieszkę": "Agnieszka", "aga": "Agnieszka",
    "julia": "Julia", "julio": "Julia", "julię": "Julia", "julka": "Julia",
    "weronika": "Weronika", "weroniko": "Weronika",
    "marta": "Marta", "marto": "Marta", "martę": "Marta",
    "klaudia": "Klaudia", "klaudio": "Klaudia",
    "patrycja": "Patrycja", "patrycjo": "Patrycja",
    "sylwia": "Sylwia", "sylwio": "Sylwia",
    "dorota": "Dorota", "doroto": "Dorota",
    "ewa": "Ewa", "ewo": "Ewa", "ewę": "Ewa",
    "joanna": "Joanna", "joanno": "Joanna", "asia": "Asia", "asiu": "Asia",
    "alicja": "Alicja", "alicjo": "Alicja", "ala": "Alicja", "alu": "Alicja",
    "zuzanna": "Zuzanna", "zuzia": "Zuzia", "zuziu": "Zuzia",
    "maja": "Maja", "maju": "Maja",
}


MALE_NAMES = {
    "Łukasz", "Radek", "Radosław", "Szymon", "Adrian", "Tomek", "Tomasz",
    "Paweł", "Piotr", "Michał", "Krzysztof", "Marcin", "Marek", "Kuba", "Jakub",
    "Adam", "Bartek", "Bartosz", "Mateusz", "Przemek", "Przemysław", "Dawid",
    "Kamil", "Grzegorz", "Wojtek", "Wojciech", "Robert", "Igor", "Maciek", "Maciej",
    "Artur", "Sebastian", "Damian", "Patryk", "Dominik", "Kacper", "Rafał"
}

FEMALE_NAMES = {
    "Kasia", "Katarzyna", "Ania", "Anna", "Jola", "Jolanta", "Iza", "Izabela", "Daria", "Gabriela",
    "Ola", "Aleksandra", "Magda", "Magdalena",
    "Monika", "Natalia", "Karolina", "Paulina", "Justyna", "Agnieszka", "Julia",
    "Weronika", "Marta", "Klaudia", "Patrycja", "Sylwia", "Dorota", "Ewa",
    "Joanna", "Asia", "Alicja", "Zuzanna", "Maja"
}


def find_names_in_text(text: str) -> List[str]:
    """
    Wyszukuje rozpoznane polskie imiona w podanym fragmencie tekstu.
    Zwraca znormalizowaną formę mianownikową (np. 'Łukasz', 'Radek').
    """
    words = re.findall(r'\b[a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+\b', text.lower())
    found = []
    for w in words:
        if w in POLISH_NAMES_MAP:
            found.append(POLISH_NAMES_MAP[w])
    return found


def analyze_speakers(turns: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Zaawansowana analiza kontekstu dialogu w języku polskim:
    1. Rozpoznaje płeć gramatyczną (męskie formy czasowników -łem wykluczają imiona żeńskie).
    2. Rozpoznaje samoreferencje i cytowanie zwrotów do siebie ('Radek weź...', 'do mnie będą dzwonili... Radziu').
    3. Rozpoznaje bezpośrednie zwroty ('Dobra Łukasz', 'Poczekaj Łukasz', 'Ty Szymon', 'wyloguj się Szymon').
    4. Eliminuje fałszywe dopasowania (osoba mówiąca zwrot nie może być tą osobą).
    5. Wykonuje globalne dopasowanie 1-do-1 z maksymalizacją zgodności.
    """
    if not turns:
        return {}

    speakers = sorted(list(set(t.get("speaker", "") for t in turns if t.get("speaker"))))
    if not speakers:
        return {}

    stats = {}
    for spk in speakers:
        stats[spk] = {
            "count": 0,
            "total_duration": 0.0,
            "sample": "",
            "suggested_name": "",
            "clue": ""
        }

    # Zliczanie wypowiedzi i dobór próbek
    speaker_texts = defaultdict(list)
    speaker_gender = defaultdict(lambda: {"masc": 0, "fem": 0})

    for t in turns:
        spk = t.get("speaker")
        if not spk:
            continue
        text = t.get("text", "").strip()
        dur = max(0.0, t.get("end", 0.0) - t.get("start", 0.0))
        stats[spk]["count"] += 1
        stats[spk]["total_duration"] += dur
        speaker_texts[spk].append(text)

        # Analiza form czasownikowych
        txt_low = text.lower()
        masc_hits = len(re.findall(r'\b(?:\w+łem|byłem|chciałem|myślałem|próbowałem|zalogowałem|zrobiłem|powiedziałem|wysłałem|słyszałem|widziałem|mówiłem)\b', txt_low))
        fem_hits = len(re.findall(r'\b(?:\w+łam|byłam|chciałam|myślałam|próbowałam|zalogowałam|zrobiłam|powiedziałam|wysłałam|słyszałam|widziałam|mówiłam)\b', txt_low))
        speaker_gender[spk]["masc"] += masc_hits
        speaker_gender[spk]["fem"] += fem_hits

        if len(stats[spk]["sample"]) < 25 and len(text) >= 15:
            stats[spk]["sample"] = text
        elif not stats[spk]["sample"] and text:
            stats[spk]["sample"] = text

    scores = defaultdict(lambda: Counter())
    evidence = defaultdict(dict)
    exclusions = defaultdict(set)  # spk -> set of forbidden names
    conversation_names = set()

    for i, t in enumerate(turns):
        cur_spk = t.get("speaker")
        text = t.get("text", "").strip()
        text_lower = text.lower()

        if not cur_spk or not text:
            continue

        # Rejestruj wszystkie imiona pojawiające się w tekście
        all_found = find_names_in_text(text_lower)
        for fn in all_found:
            conversation_names.add(fn)

        # --- A. Samoreferencje i cytaty o sobie ---
        self_quote_pats = [
            r'\b(?:biorę\s+to|mówię\s+to)\s+ja[\,\s]+([a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+)\b',
            r'\b(?:z\s+tej\s+strony|tu|jestem|mówi|ja\s+jestem|nazywam\s+się)\s+([a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+)\b',
            r'\b(?:do\s+mnie|pytali\s+mnie|pytają\s+mnie|mówią\s+do\s+mnie|dzwonili\s+do\s+mnie)[\s\w\,]{1,40}?\b([a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+)\b',
            r'\b(?:dostać\s+sygnał|dostanę\s+sygnał)[\s\,\.\:]+([a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+)\b',
            r'\b([a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+)[\,\s]+weź\s+(?:to|tu|ten|skrót|krzesło)\b'
        ]
        for pat in self_quote_pats:
            for match in re.finditer(pat, text_lower):
                matched_word = match.group(1)
                found = find_names_in_text(matched_word)
                for fn in found:
                    scores[cur_spk][fn] += 20.0
                    evidence[cur_spk][fn] = f"Mówi o sobie / cytuje zwrot do siebie: „{match.group(0)}”"

        # --- B. Bezpośrednie zwroty do rozmówcy (Vocatives & Direct Address) ---
        addressed_patterns = [
            r'\b(?:poczekaj|czekaj|dobra|dobre|słuchaj|powiedz|zobacz|spójrz|jasne|okej|ok)[\,\s]+([a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+)\b',
            r'\b(?:ja\s+rozumiem|rozumiem|wiesz\s+co|zresztą|faktycznie|pamiętasz|widzisz|powiedz\s+mi\s+jeszcze)[\,\s]+([a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+)\b',
            r'\b(?:powiem\s+ci|mówię\s+ci|ja\s+ci)[\,\s]+([a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+)\b',
            r'\bty[\,\s]+([a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+)\b',
            r'\b(?:wyloguj\s+się|wejdź|zrób|kliknij|zostawmy|otwórz|zapisz|przepisz)[\,\s]+([a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+)\b',
            r'^([a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+)[\,\:]\s+',
            r'[\,\.\!\?]\s*([a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+)[\?\!\.]$'
        ]
        for v_pat in addressed_patterns:
            for m in re.finditer(v_pat, text_lower):
                names = find_names_in_text(m.group(1))
                for fn in names:
                    # Mówca cur_spk wyklucza siebie
                    exclusions[cur_spk].add(fn)
                    scores[cur_spk][fn] -= 50.0

                    # Szukamy następnego innego mówcy w dialogu
                    target_spk = None
                    for next_idx in range(i + 1, len(turns)):
                        cand_spk = turns[next_idx].get("speaker")
                        if cand_spk and cand_spk != cur_spk:
                            if fn not in exclusions[cand_spk]:
                                target_spk = cand_spk
                                break

                    if not target_spk and i > 0:
                        # Sprawdzamy turę poprzednią
                        if turns[i - 1].get("speaker") != cur_spk:
                            target_spk = turns[i - 1].get("speaker")

                    if target_spk and target_spk != cur_spk:
                        scores[target_spk][fn] += 8.0
                        if fn not in evidence[target_spk]:
                            evidence[target_spk][fn] = f"Bezpośredni zwrot od {cur_spk}: „{text[:40]}...”"


    # --- C. Płeć gramatyczna jako filtr bezwzględny ---
    for spk in speakers:
        g = speaker_gender[spk]
        if g["masc"] >= 2 and g["masc"] > g["fem"]:
            for fn in FEMALE_NAMES:
                scores[spk][fn] -= 100.0
                exclusions[spk].add(fn)
        elif g["fem"] >= 2 and g["fem"] > g["masc"]:
            for fn in MALE_NAMES:
                scores[spk][fn] -= 100.0
                exclusions[spk].add(fn)

    # --- D. Globalne dopasowanie 1-do-1 z maksymalizacją zgodności ---
    candidates = []
    for spk in speakers:
        if stats[spk]["count"] <= 1:
            continue
        for name, sc in scores[spk].items():
            if sc > 2.0 and name not in exclusions[spk]:
                candidates.append((sc, spk, name))

    candidates.sort(key=lambda x: x[0], reverse=True)

    assigned_spk = set()
    assigned_names = set()

    for sc, spk, name in candidates:
        if spk not in assigned_spk and name not in assigned_names:
            stats[spk]["suggested_name"] = name
            stats[spk]["clue"] = f"💡 {evidence[spk].get(name, 'Rozpoznano z kontekstu dialogu')}"
            assigned_spk.add(spk)
            assigned_names.add(name)

    # --- E. Dopasowanie drogą eliminacji (dla pozostałych aktywnych mówców) ---
    unassigned_speakers = [s for s in speakers if s not in assigned_spk and stats[s]["count"] >= 2]
    unassigned_names = [n for n in conversation_names if n not in assigned_names]


    for spk in unassigned_speakers:
        for name in unassigned_names:
            if name not in exclusions[spk] and scores[spk][name] > -50.0:
                stats[spk]["suggested_name"] = name
                stats[spk]["clue"] = f"💡 Rozpoznano drogą eliminacji z kontekstu spotkania (wzmianka o: {name})"
                assigned_spk.add(spk)
                assigned_names.add(name)
                break

    # Uzupełnienie wskazówek dla pozostałych
    for spk in speakers:
        cnt = stats[spk]["count"]
        if not stats[spk]["suggested_name"]:
            if cnt <= 2:
                stats[spk]["clue"] = f"⚠️ Krótkie wtrącenie ({cnt} wypowiedzi) – zalecane scalenie"
            else:
                stats[spk]["clue"] = "ℹ️ Brak jednoznacznych wzmianek – wpisz imię ręcznie"

    return stats




def format_speaker_stats(count: int, total_duration_sec: float) -> str:
    """Zwraca czytelny ciąg statystyk mówcy, np. '42 wypowiedzi · 14m 20s'."""
    mins = int(total_duration_sec // 60)
    secs = int(total_duration_sec % 60)
    time_str = f"{mins}m {secs:02d}s" if mins > 0 else f"{secs}s"
    w_str = f"{count} wypowiedź" if count == 1 else f"{count} wypowiedzi"
    return f"{w_str} · ⏱️ {time_str}"


def suggest_speaker_names(turns: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    Zwraca słownik unikalnego mapowania {SPEAKER_XX: 'Imię'}.
    Gwarantuje, że to samo imię nigdy nie zostanie przypisane dwóm różnym mówcom.
    """
    analysis = analyze_speakers(turns)
    mapping = {}
    used_names = set()

    for spk, data in analysis.items():
        sug = data.get("suggested_name", "")
        if sug and sug not in used_names:
            mapping[spk] = sug
            used_names.add(sug)
        else:
            mapping[spk] = spk
    return mapping


def get_speaker_samples(turns: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Zwraca próbki i statystyki mówców.
    """
    return analyze_speakers(turns)


def format_turns(turns: List[Dict[str, Any]], speaker_mapping: Optional[Dict[str, str]] = None,
                 session_start_time: Optional[datetime] = None,
                 reverse_order: Optional[bool] = None) -> Tuple[str, str]:
    """
    Formatuje listę wypowiedzi do kodu HTML (dla okna aplikacji) oraz tekstu czystego (do zapisu .txt)
    z uwzględnieniem mapowania nazw mówców i preferowanego formatu timestampu.
    """
    if not turns:
        return "Brak zarejestrowanej mowy.", "Brak zarejestrowanej mowy."

    from recorder.core.session import format_turn_timestamp
    if reverse_order is None:
        try:
            from recorder.config import get_preview_order
            reverse_order = (get_preview_order() == "newest_first")
        except Exception:
            reverse_order = True

    mapping = speaker_mapping or {}
    chrono_turns = sorted(turns, key=lambda t: float(t.get("start", 0.0)))

    final_plain = ""
    for t in chrono_turns:
        raw_spk = t.get("speaker", "SPEAKER")
        display_spk = mapping.get(raw_spk, raw_spk).strip() or raw_spk
        start = t.get("start", 0.0)
        end = t.get("end", 0.0)
        text = t.get("text", "").strip()

        if text:
            time_label = format_turn_timestamp(start, end, session_start_time)
            final_plain += f"[{time_label}] {display_spk}: {text}\n\n"

    final_html = ""
    display_turns = list(reversed(chrono_turns)) if reverse_order else chrono_turns
    for t in display_turns:
        raw_spk = t.get("speaker", "SPEAKER")
        display_spk = mapping.get(raw_spk, raw_spk).strip() or raw_spk
        start = t.get("start", 0.0)
        end = t.get("end", 0.0)
        text = t.get("text", "").strip()

        if text:
            time_label = format_turn_timestamp(start, end, session_start_time)
            final_html += f"<b>[{time_label}] {display_spk}:</b> {text}<br><br>"

    if not final_html:
        final_html = "Brak zarejestrowanej mowy."
    if not final_plain:
        final_plain = "Brak zarejestrowanej mowy."

    return final_html, final_plain


def parse_txt_to_turns(txt_content: str, session_start_time: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """
    Parsuje treść pliku tekstowego transkrypcji na listę ustrukturyzowanych segmentów/turns.
    Obsługuje formaty:
    - [19.5s - 20.6s] SPEAKER_02: Treść wypowiedzi
    - [00:19 - 00:20] Jan: Treść wypowiedzi
    - [15:43:54 - 15:44:01] Jan: Treść wypowiedzi
    - [00:19 - 00:20 | 15:43:54 - 15:44:01] Jan: Treść wypowiedzi
    - SPEAKER_02: Treść wypowiedzi
    """
    turns = []
    if not txt_content:
        return turns

    pattern_hybrid = re.compile(r'^\s*\[(\d+):(\d+)\s*-\s*(\d+):(\d+)\s*\|\s*(\d{1,2}):(\d{2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2}):(\d{2})\]\s*([^:]+):\s*(.*)$')
    pattern_clock = re.compile(r'^\s*\[(\d{1,2}):(\d{2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2}):(\d{2})\]\s*([^:]+):\s*(.*)$')
    pattern_sec = re.compile(r'^\s*\[([\d\.]+)\s*s?\s*-\s*([\d\.]+)\s*s?\]\s*([^:]+):\s*(.*)$')
    pattern_min = re.compile(r'^\s*\[(\d+):(\d+)\s*-\s*(\d+):(\d+)\]\s*([^:]+):\s*(.*)$')
    pattern_simple = re.compile(r'^\s*([^:\[\n]+):\s*(.*)$')

    blocks = txt_content.strip().split('\n\n')
    current_time = 0.0
    first_clock_sec = None

    for block in blocks:
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if not lines:
            continue
        header_line = lines[0]
        remaining_text = " ".join(lines[1:]) if len(lines) > 1 else ""

        # 1. Format hybrydowy [00:19 - 00:20 | 15:43:54 - 15:44:01] Mówca: ...
        m_hyb = pattern_hybrid.match(header_line)
        if m_hyb:
            start = int(m_hyb.group(1)) * 60 + int(m_hyb.group(2))
            end = int(m_hyb.group(3)) * 60 + int(m_hyb.group(4))
            speaker = m_hyb.group(9).strip()
            text = (m_hyb.group(10) + " " + remaining_text).strip()
            turns.append({"speaker": speaker, "start": float(start), "end": float(end), "text": text})
            current_time = float(end)
            continue

        # 2. Format samej godziny realnej [15:43:54 - 15:44:01] Mówca: ...
        m_clock = pattern_clock.match(header_line)
        if m_clock:
            h1, min1, s1 = int(m_clock.group(1)), int(m_clock.group(2)), int(m_clock.group(3))
            h2, min2, s2 = int(m_clock.group(4)), int(m_clock.group(5)), int(m_clock.group(6))
            c_start = h1 * 3600 + min1 * 60 + s1
            c_end = h2 * 3600 + min2 * 60 + s2

            if session_start_time is not None:
                base_sec = session_start_time.hour * 3600 + session_start_time.minute * 60 + session_start_time.second
                start = max(0.0, float(c_start - base_sec))
                end = max(start + 0.1, float(c_end - base_sec))
            else:
                if first_clock_sec is None:
                    first_clock_sec = c_start
                start = max(0.0, float(c_start - first_clock_sec))
                end = max(start + 0.1, float(c_end - first_clock_sec))

            speaker = m_clock.group(7).strip()
            text = (m_clock.group(8) + " " + remaining_text).strip()
            turns.append({"speaker": speaker, "start": start, "end": end, "text": text})
            current_time = end
            continue

        # 3. Format sekundowy [1.8s - 10.2s] Mówca: ...
        m_sec = pattern_sec.match(header_line)
        if m_sec:
            start = float(m_sec.group(1))
            end = float(m_sec.group(2))
            speaker = m_sec.group(3).strip()
            text = (m_sec.group(4) + " " + remaining_text).strip()
            turns.append({"speaker": speaker, "start": start, "end": end, "text": text})
            current_time = end
            continue

        # 4. Format minutowy [00:19 - 00:20] Mówca: ...
        m_min = pattern_min.match(header_line)
        if m_min:
            start = int(m_min.group(1)) * 60 + int(m_min.group(2))
            end = int(m_min.group(3)) * 60 + int(m_min.group(4))
            speaker = m_min.group(5).strip()
            text = (m_min.group(6) + " " + remaining_text).strip()
            turns.append({"speaker": speaker, "start": float(start), "end": float(end), "text": text})
            current_time = float(end)
            continue

        # 5. Prosty format Mówca: Treść
        m_sim = pattern_simple.match(header_line)
        if m_sim and len(m_sim.group(1)) < 40 and not m_sim.group(1).startswith("["):
            speaker = m_sim.group(1).strip()
            text = (m_sim.group(2) + " " + remaining_text).strip()
            turns.append({"speaker": speaker, "start": current_time, "end": current_time + 5.0, "text": text})
            current_time += 5.0
            continue

        # 6. Zwykły blok tekstu bez nagłówka
        full_text = " ".join(lines)
        turns.append({"speaker": "Mówca", "start": current_time, "end": current_time + 5.0, "text": full_text})
        current_time += 5.0

    return turns

