import re
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

    # Żeńskie
    "kasia": "Kasia", "kasiu": "Kasia", "kasię": "Kasia", "katarzyna": "Katarzyna", "kasi": "Kasia",
    "ania": "Ania", "aniu": "Ania", "anię": "Ania", "anna": "Anna",
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
    Zaawansowana, odporna analiza kontekstu rozmowy w języku polskim:
    1. Rozpoznaje samoprezentację w 1. osobie ('z tej strony Radek', 'tu Łukasz', 'mówi Szymon').
    2. Rozpoznaje bezpośrednie zwroty wołaczowe do rozmówcy ('Dobra Łukasz, ...', 'Szymon, powiedz mi...', 'Cześć Radek').
    3. Przypisuje imię rzeczywistemu partnerowi w dialogu (analizując kontekst wypowiedzi sąsiednich i ignorując wtrącenia typu 'hmm').
    4. Bezwzględnie wyklucza osobę wypowiadającą zwrot z bycia nazwaną tym imieniem.
    5. Zwraca statystyki, próbki i czytelne wskazówki kontekstowe dla użytkownika.
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
    for t in turns:
        spk = t.get("speaker")
        if not spk:
            continue
        text = t.get("text", "").strip()
        dur = max(0.0, t.get("end", 0.0) - t.get("start", 0.0))
        stats[spk]["count"] += 1
        stats[spk]["total_duration"] += dur

        if len(stats[spk]["sample"]) < 25 and len(text) >= 15:
            stats[spk]["sample"] = text
        elif not stats[spk]["sample"] and text:
            stats[spk]["sample"] = text

    scores = defaultdict(lambda: Counter())
    evidence = defaultdict(dict)

    for i, t in enumerate(turns):
        cur_spk = t.get("speaker")
        text = t.get("text", "").strip()
        text_lower = text.lower()

        if not cur_spk or not text:
            continue

        # --- A. SAMOPREZENTACJA W 1. OSOBIE I CYTOWANIE ZWROTÓW DO SIEBIE ---
        self_patterns = [
            r'\b(?:z\s+tej\s+strony|tu|jestem|mówi|ja\s+jestem|nazywam\s+się)\s+([a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+)\b',
            r'\b(?:do\s+mnie|pytali\s+mnie|mówią\s+mi|mówią\s+do\s+mnie|u\s+mnie)\s+([a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+)\b',
            r'\b(?:dzwonili|dzwonią|pytają|pytali|mówią)[\s\w\,]{1,30}?(?:mnie|do\s+mnie)[\s\w\,]{1,20}?([a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+)\b',
            r'\b(?:dostać\s+sygnał|dostanę\s+sygnał|sygnał)[\s\,\:]+([a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+)\b'
        ]
        for pat in self_patterns:
            for match in re.finditer(pat, text_lower):
                matched_name_word = match.group(1)
                found_names = find_names_in_text(matched_name_word)
                for fn in found_names:
                    scores[cur_spk][fn] += 8.0
                    snippet = text[max(0, match.start()-5):min(len(text), match.end()+20)].strip()
                    evidence[cur_spk][fn] = f"Mówi o sobie w 1. os.: „{snippet}”"

        # Np. "Dobra Łukasz, a o czym...", "Łukasz, słuchaj...", "Cześć Szymon...", "Słuchaj Radek..."
        vocative_patterns = [
            r'^(?:dobra|okej|ok|no|no\s+dobra|cześć|hej|witam|słuchaj|powiedz\s+mi|zobacz|spójrz)\s+([a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+)[\,\s\.\!\?]',
            r'^([a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+)\,',
            r'[\,\.\!\?]\s*([a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+)[\?\!\.]$'
        ]

        found_addressed_names = []
        matched_snippet = ""
        for v_pat in vocative_patterns:
            m = re.search(v_pat, text_lower)
            if m:
                names = find_names_in_text(m.group(1))
                if names:
                    found_addressed_names.extend(names)
                    matched_snippet = text[:min(len(text), 45)].strip()
                    break

        if found_addressed_names:
            for fn in found_addressed_names:
                # Mówca cur_spk ZAWSZE wyklucza siebie
                scores[cur_spk][fn] -= 6.0

                # Szukamy właściwego rozmówcy w sąsiednich turach dialogu
                target_spk = None

                # 1. Sprawdzamy kolejną turę (i+1), o ile nie jest tylko wtrąceniem typu "hmm"
                if i + 1 < len(turns):
                    candidate_spk = turns[i + 1].get("speaker")
                    candidate_txt = turns[i + 1].get("text", "").strip().lower()
                    if candidate_spk and candidate_spk != cur_spk:
                        if len(candidate_txt) > 4 and candidate_txt not in ("hmm", "mhm", "aha", "tak", "nie"):
                            target_spk = candidate_spk

                # 2. Jeśli kolejna tura to wtrącenie, sprawdzamy turę i+2
                if not target_spk and i + 2 < len(turns):
                    candidate_spk = turns[i + 2].get("speaker")
                    if candidate_spk and candidate_spk != cur_spk:
                        target_spk = candidate_spk

                # 3. Jeśli nie znaleziono po prawej, sprawdzamy poprzednią turę (i-1)
                if not target_spk and i - 1 >= 0:
                    candidate_spk = turns[i - 1].get("speaker")
                    if candidate_spk and candidate_spk != cur_spk:
                        target_spk = candidate_spk

                # 4. Jeśli nadal brak, wybieramy najbardziej aktywnego innego mówcę w nagraniu
                if not target_spk:
                    other_spks = [s for s in speakers if s != cur_spk and stats[s]["count"] >= 3]
                    if other_spks:
                        target_spk = max(other_spks, key=lambda s: stats[s]["count"])

                if target_spk:
                    scores[target_spk][fn] += 5.0
                    if fn not in evidence[target_spk]:
                        evidence[target_spk][fn] = f"Zwrot bezpośredni od {cur_spk}: „{matched_snippet}...”"

    # Przypisywanie najlepszych, unikalnych dopasowań
    candidates = []
    for spk, name_counts in scores.items():
        # Ignorujemy małe wtrącenia (<= 2 wypowiedzi) przy automatycznym przypisywaniu imion
        if stats[spk]["count"] <= 2:
            continue
        for name, score in name_counts.items():
            if score >= 3.0:
                candidates.append((score, spk, name))

    candidates.sort(key=lambda x: x[0], reverse=True)

    assigned_spk = set()
    assigned_names = set()

    for score, spk, name in candidates:
        if spk not in assigned_spk and name not in assigned_names:
            stats[spk]["suggested_name"] = name
            stats[spk]["clue"] = f"💡 {evidence[spk].get(name, 'Wykryto powiązanie z kontekstu dialogu')}"
            assigned_spk.add(spk)
            assigned_names.add(name)

    # Uzupełnienie wskazówek dla pozostałych mówców
    for spk in speakers:
        cnt = stats[spk]["count"]
        if not stats[spk]["suggested_name"]:
            if cnt <= 2:
                stats[spk]["clue"] = f"⚠️ Krótkie wtrącenie ({cnt} wypowiedzi) – zalecane scalenie z innym mówcą"
            else:
                stats[spk]["clue"] = "ℹ️ Brak bezpośrednich wzmianek imienia – wpisz osobę ręcznie"

    return stats


def suggest_speaker_names(turns: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    Zwraca prosty słownik mapowania {SPEAKER_XX: 'Imię'}.
    """
    analysis = analyze_speakers(turns)
    mapping = {}
    for spk, data in analysis.items():
        sug = data.get("suggested_name", "")
        mapping[spk] = sug if sug else spk
    return mapping


def get_speaker_samples(turns: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Zwraca próbki i statystyki mówców.
    """
    return analyze_speakers(turns)


def format_turns(turns: List[Dict[str, Any]], speaker_mapping: Optional[Dict[str, str]] = None) -> Tuple[str, str]:
    """
    Formatuje listę wypowiedzi do kodu HTML (dla okna aplikacji) oraz tekstu czystego (do zapisu .txt)
    z uwzględnieniem mapowania nazw mówców.
    """
    if not turns:
        return "Brak zarejestrowanej mowy.", "Brak zarejestrowanej mowy."

    mapping = speaker_mapping or {}
    final_html = ""
    final_plain = ""

    for t in turns:
        raw_spk = t.get("speaker", "SPEAKER")
        display_spk = mapping.get(raw_spk, raw_spk).strip() or raw_spk
        start = t.get("start", 0.0)
        end = t.get("end", 0.0)
        text = t.get("text", "").strip()

        if text:
            final_html += f"<b>[{start:.1f}s - {end:.1f}s] {display_spk}:</b> {text}<br><br>"
            final_plain += f"[{start:.1f}s - {end:.1f}s] {display_spk}: {text}\n\n"

    if not final_html:
        final_html = "Brak zarejestrowanej mowy."
        final_plain = "Brak zarejestrowanej mowy."

    return final_html, final_plain
