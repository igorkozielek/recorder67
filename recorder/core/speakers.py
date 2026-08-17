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
    Kompleksowa, odporna analiza intencji i kontekstu wypowiedzi:
    1. Rozpoznaje kiedy ktoś mówi O SOBIE w 1. osobie (np. 'pytali mnie radziu', 'sygnał radek weź').
    2. Rozpoznaje zwroty bezpośrednie i pytania do rozmówcy na początku zdań (np. 'Łukasz, a czym się zajmiemy?').
    3. Rozpoznaje polecenia skierowane do kogoś (np. 'wyloguj się Szymon').
    4. Rozpoznaje mówienie o kimś w 3. osobie (np. 'wysłałem to Radziowi').
    5. Zwraca statystyki, próbki wypowiedzi oraz czytelne wskazówki kontekstowe (clues) dla człowieka.
    """
    if not turns:
        return {}

    speakers = sorted(list(set(t.get("speaker", "") for t in turns if t.get("speaker"))))
    if not speakers:
        return {}

    # Inicjalizacja struktur
    stats = {}
    for spk in speakers:
        stats[spk] = {
            "count": 0,
            "total_duration": 0.0,
            "sample": "",
            "suggested_name": "",
            "clue": ""
        }

    # Zbieranie próbek i statystyk
    for t in turns:
        spk = t.get("speaker")
        if not spk:
            continue
        text = t.get("text", "").strip()
        dur = max(0.0, t.get("end", 0.0) - t.get("start", 0.0))
        stats[spk]["count"] += 1
        stats[spk]["total_duration"] += dur

        # Wybór reprezentatywnej próbki
        if len(stats[spk]["sample"]) < 20 and len(text) >= 15:
            stats[spk]["sample"] = text
        elif not stats[spk]["sample"] and text:
            stats[spk]["sample"] = text

    # Obliczanie punktów i dowodów
    scores = defaultdict(lambda: Counter())
    evidence = defaultdict(dict)  # evidence[spk][name] = "opis kontekstu"

    for i, t in enumerate(turns):
        cur_spk = t.get("speaker")
        text = t.get("text", "")
        text_lower = text.lower()

        # --- A. SAMOPREZENTACJA / MÓWIENIE O SOBIE W 1. OSOBIE ---
        # Wzorce generyczne: "do mnie ... [Imię]", "pytali mnie ... [Imię]", "jestem [Imię]", "ja [Imię]"
        self_patterns = [
            r'\b(?:do\s+mnie|pytali\s+mnie|pytają\s+mnie|mówią\s+mi|mówi\s+mi|u\s+mnie|ja|jestem|dla\s+mnie)\b[^\.\,\?\!]{0,25}\b([a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+)\b',
            r'\b(?:sygnał|mówi)\b[^\.\,\?\!]{0,20}\b([a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+)\s+weź\b'
        ]
        for pat in self_patterns:
            for match in re.finditer(pat, text_lower):
                matched_name_word = match.group(1)
                found_names = find_names_in_text(matched_name_word)
                for fn in found_names:
                    # Bardzo silny punkt dla MÓWCY AKTUALNEGO
                    scores[cur_spk][fn] += 6.0
                    snippet = text[max(0, match.start()-10):min(len(text), match.end()+25)].strip()
                    evidence[cur_spk][fn] = f"Mówi o sobie w 1. os.: „...{snippet}...”"

        # --- B. ZWROT BEZPOŚREDNI / PYTANIE NA POCZĄTKU WYPOWIEDZI ---
        # Np. "Piotr, a o czym dzisiaj porozmawiamy?" lub "Tomasz, spójrz na to..."
        words_first = text.strip().split()[:3]
        first_str = " ".join(words_first)
        first_names = find_names_in_text(first_str)

        if first_names and i + 1 < len(turns):
            next_turn = turns[i + 1]
            next_spk = next_turn.get("speaker")
            if next_spk and next_spk != cur_spk:
                for fn in first_names:
                    # Rozmówca odpowiadający na wywołanie dostaje mocny punkt
                    scores[next_spk][fn] += 4.5
                    evidence[next_spk][fn] = f"Wywołany przez {cur_spk}: „{first_str}...”"
                    # Mówiący wyklucza siebie
                    scores[cur_spk][fn] -= 3.0

        # --- C. POLECENIA I ZWROTY DO ROZMÓWCY ---
        # Np. "Sprawdź to Piotr" lub "Ty Tomasz..."
        cmd_matches = re.findall(r'\b(?:ty|tobie|ciebie|się)\s+([a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+)\b', text_lower)
        for cm in cmd_matches:
            target_names = find_names_in_text(cm)
            for tn in target_names:
                # Wszyscy inni oprócz mówcy
                for other_spk in speakers:
                    if other_spk != cur_spk:
                        scores[other_spk][tn] += 2.5
                        if tn not in evidence[other_spk]:
                            evidence[other_spk][tn] = f"Zwrot od {cur_spk}: „...{cm}... {tn}”"

        # --- D. ODNIESIENIE W 3. OSOBIE ---
        # Np. "Wysłałem to Janowi", "U Piotra na biurku"
        ref_matches = re.findall(r'\b(?:wysłałem|wysłałam|poszło\s+do|u|od|tam\s+jest\s+u)\s+([a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+)\b', text_lower)
        for rm in ref_matches:
            target_names = find_names_in_text(rm)
            for tn in target_names:
                scores[cur_spk][tn] -= 2.0  # Mówca mówi o kimś innym
                if i + 1 < len(turns) and turns[i + 1].get("speaker") != cur_spk:
                    scores[turns[i + 1].get("speaker")][tn] += 2.0

    # Przypisywanie najlepszych, unikalnych dopasowań
    candidates = []
    for spk, name_counts in scores.items():
        for name, score in name_counts.items():
            if score >= 2.0:
                candidates.append((score, spk, name))

    candidates.sort(key=lambda x: x[0], reverse=True)

    assigned_spk = set()
    assigned_names = set()

    for score, spk, name in candidates:
        if spk not in assigned_spk and name not in assigned_names:
            stats[spk]["suggested_name"] = name
            stats[spk]["clue"] = f"💡 {evidence[spk].get(name, 'Wykryto powiązanie z kontekstu')}"
            assigned_spk.add(spk)
            assigned_names.add(name)

    # Uzupełnienie wskazówek dla pozostałych mówców
    for spk in speakers:
        cnt = stats[spk]["count"]
        if not stats[spk]["suggested_name"]:
            if cnt <= 2:
                stats[spk]["clue"] = f"⚠️ Krótkie wtrącenie ({cnt} wypowiedzi) – wybierz osobę lub scali z innym mówcą"
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
