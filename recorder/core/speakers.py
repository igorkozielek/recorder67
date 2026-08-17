import re
from typing import List, Dict, Any, Tuple, Optional
from collections import defaultdict, Counter


# Słownik popularnych polskich imion (wraz z odmianami w wołaczu/celowniku/zdrobnieniach)
POLISH_NAMES_MAP = {
    # Męskie
    "łukasz": "Łukasz", "łukaszu": "Łukasz", "łukasza": "Łukasz", "łuki": "Łukasz",
    "radek": "Radek", "radku": "Radek", "radziu": "Radek", "radzia": "Radek", "radosław": "Radosław", "radka": "Radek",
    "szymon": "Szymon", "szymonie": "Szymon", "szymek": "Szymon", "szymku": "Szymon", "szymona": "Szymon",
    "adrian": "Adrian", "adrianie": "Adrian", "adriana": "Adrian", "adi": "Adrian",
    "tomek": "Tomek", "tomku": "Tomek", "tomasz": "Tomasz", "tomaszu": "Tomasz", "tomka": "Tomek",
    "paweł": "Paweł", "pawle": "Paweł", "pawła": "Paweł", "pawełka": "Paweł",
    "piotr": "Piotr", "piotrze": "Piotr", "piotrek": "Piotr", "piotrku": "Piotr", "piotra": "Piotr",
    "michał": "Michał", "michale": "Michał", "michała": "Michał", "misiek": "Michał",
    "kuba": "Kuba", "kubo": "Kuba", "jakub": "Jakub", "jakubie": "Jakub", "kuby": "Kuba",
    "bartek": "Bartek", "bartku": "Bartek", "bartosz": "Bartosz", "bartoszu": "Bartosz", "bartka": "Bartek",
    "krzysztof": "Krzysztof", "krzysztofie": "Krzysztof", "krzysiek": "Krzysiek", "krzysiu": "Krzysiek", "krzysztofa": "Krzysztof",
    "marcin": "Marcin", "marcinie": "Marcin", "marcina": "Marcin",
    "marek": "Marek", "marku": "Marek", "marka": "Marek",
    "jan": "Jan", "janie": "Jan", "janek": "Jan", "janku": "Jan", "jana": "Jan",
    "adam": "Adam", "adamie": "Adam", "adama": "Adam",
    "grzegorz": "Grzegorz", "grzegorzu": "Grzegorz", "grzesiek": "Grzegorz", "grzesiu": "Grzegorz",
    "maciej": "Maciej", "macieju": "Maciej", "maciek": "Maciek", "maćku": "Maciek",
    "mateusz": "Mateusz", "mateuszu": "Mateusz", "mati": "Mateusz", "mateusza": "Mateusz",
    "wojtek": "Wojtek", "wojtku": "Wojtek", "wojciech": "Wojciech", "wojciechu": "Wojciech",
    "przemek": "Przemek", "przemku": "Przemek", "przemysław": "Przemysław", "przemysława": "Przemysław",
    "igor": "Igor", "igorze": "Igor", "igora": "Igor",
    "kacper": "Kacper", "kacprze": "Kacper", "kacpra": "Kacper",
    "dawid": "Dawid", "dawidzie": "Dawid", "dawida": "Dawid",
    "kamil": "Kamil", "kamilu": "Kamil", "kamila": "Kamil",
    "patryk": "Patryk", "patryku": "Patryk", "patryka": "Patryk",
    "robert": "Robert", "robercie": "Robert", "roberta": "Robert",
    "mariusz": "Mariusz", "mariuszu": "Mariusz", "mariusza": "Mariusz",

    # Żeńskie
    "kasia": "Kasia", "kasiu": "Kasia", "katarzyna": "Katarzyna", "katarzyno": "Katarzyna", "kasi": "Kasia",
    "ania": "Ania", "aniu": "Ania", "anna": "Anna", "anno": "Anna", "ani": "Ania",
    "ola": "Ola", "olu": "Ola", "aleksandra": "Aleksandra", "aleksandro": "Aleksandra", "oli": "Ola",
    "magda": "Magda", "magdo": "Magda", "magdalena": "Magdalena", "magdaleno": "Magdalena", "magdy": "Magda",
    "paulina": "Paulina", "paulino": "Paulina", "pauliny": "Paulina",
    "karolina": "Karolina", "karolino": "Karolina", "karoliny": "Karolina",
    "natalia": "Natalia", "natalio": "Natalia", "natali": "Natalia",
    "monika": "Monika", "moniko": "Monika", "moniki": "Monika",
    "agnieszka": "Agnieszka", "agnieszko": "Agnieszka", "agnieszki": "Agnieszka",
    "marta": "Marta", "marto": "Marta", "marty": "Marta",
    "joanna": "Joanna", "joanno": "Joanna", "asia": "Asia", "asiu": "Asia",
    "dorota": "Dorota", "doroto": "Dorota", "doroty": "Dorota",
    "ewa": "Ewa", "ewo": "Ewa", "ewy": "Ewa",
    "justyna": "Justyna", "justyno": "Justyna", "justyny": "Justyna"
}


def suggest_speaker_names(turns: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    Analizuje dialog w poszukiwaniu zwrotów bezpośrednich, wołaczy oraz kontekstu,
    aby automatycznie zasugerować imię dla każdego wykrytego SPEAKER_XX.
    
    Zwraca słownik: {'SPEAKER_00': 'Radek', 'SPEAKER_01': 'Łukasz', ...}
    """
    if not turns:
        return {}

    # Zliczanie kandydatów na imię dla każdego mówcy
    # candidate_votes[speaker][name] = liczba punktów
    candidate_votes = defaultdict(Counter)

    # 1. Reguła A: Zwrot bezpośredni na początku zdania ("Łukasz, a o czym...", "Radziu weź...")
    # Jeśli mówca A zwraca się "Imię, ...", to najczęściej odpowiada mu mówca B (czyli mówca B = Imię)
    for i in range(len(turns)):
        curr_turn = turns[i]
        curr_speaker = curr_turn.get("speaker", "")
        text = curr_turn.get("text", "").strip()

        if not text:
            continue

        # Szukamy słów na początku lub w bezpośrednich zwrotach
        words = re.findall(r'[a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+', text)
        if not words:
            continue

        # Sprawdzenie pierwszego słowa lub pierwszych dwóch słów
        for idx in range(min(3, len(words))):
            w_lower = words[idx].lower()
            if w_lower in POLISH_NAMES_MAP:
                canonical_name = POLISH_NAMES_MAP[w_lower]
                
                # Jeśli po tym pytaniu/zwrocie odpowiada inny mówca, to ten inny mówca dostaje mocny punkt
                if i + 1 < len(turns):
                    next_speaker = turns[i + 1].get("speaker", "")
                    if next_speaker and next_speaker != curr_speaker:
                        candidate_votes[next_speaker][canonical_name] += 4

                # Mówca, do którego skierowano wypowiedź w tym samym bloku (np. "Ty Szymon wchodzisz")
                if idx > 0 and words[idx - 1].lower() in ("ty", "pan", "pani", "weź", "słuchaj"):
                    # Ktoś mówi "Ty Szymon..." -> szukamy kogo ma na myśli
                    if i + 1 < len(turns):
                        next_spk = turns[i + 1].get("speaker", "")
                        if next_spk != curr_speaker:
                            candidate_votes[next_spk][canonical_name] += 3

        # 2. Reguła B: Autoprezentacja lub mówienie o sobie ("do mnie będą dzwonili... radziu weź...")
        for w in words:
            w_lower = w.lower()
            if w_lower in POLISH_NAMES_MAP:
                canonical_name = POLISH_NAMES_MAP[w_lower]
                # Słabszy głos na mówcę występującego w wypowiedzi
                candidate_votes[curr_speaker][canonical_name] += 1

    # 3. Przypisanie najlepszego unikalnego imienia do każdego mówcy
    all_speakers = sorted(list(set(t.get("speaker", "") for t in turns if t.get("speaker"))))
    assigned_names = {}
    used_names = set()

    # Sortujemy mówców po najwyższej pewności (liczbie punktów)
    speaker_best_scores = []
    for spk in all_speakers:
        if candidate_votes[spk]:
            best_name, score = candidate_votes[spk].most_common(1)[0]
            speaker_best_scores.append((score, spk, best_name))
        else:
            speaker_best_scores.append((0, spk, spk))

    speaker_best_scores.sort(key=lambda x: x[0], reverse=True)

    for score, spk, best_name in speaker_best_scores:
        if score > 0 and best_name not in used_names:
            assigned_names[spk] = best_name
            used_names.add(best_name)
        else:
            # Szukamy alternatywnego imienia z kolejki dla tego mówcy
            assigned = False
            for name, sc in candidate_votes[spk].most_common():
                if name not in used_names:
                    assigned_names[spk] = name
                    used_names.add(name)
                    assigned = True
                    break
            if not assigned:
                assigned_names[spk] = spk  # Pozostaje SPEAKER_XX jeśli brak pewności

    return assigned_names


def format_turns(turns: List[Dict[str, Any]], speaker_mapping: Optional[Dict[str, str]] = None) -> Tuple[str, str]:
    """
    Formatuje listę ustrukturyzowanych wypowiedzi do kodu HTML (dla okna GUI) oraz zwykłego tekstu (do pliku .txt),
    stosując zdefiniowane lub automatycznie przypisane imiona mówców.
    """
    if not turns:
        return "Brak zarejestrowanej mowy.", "Brak zarejestrowanej mowy."

    mapping = speaker_mapping or {}

    final_html = ""
    final_plain = ""

    for t in turns:
        start_t = t.get("start", 0.0)
        end_t = t.get("end", 0.0)
        raw_speaker = t.get("speaker", "Mówca")
        speaker_name = mapping.get(raw_speaker, raw_speaker)
        text = t.get("text", "").strip()

        if not text:
            continue

        final_html += f"<b>[{start_t:.1f}s - {end_t:.1f}s] {speaker_name}:</b> {text}<br><br>"
        final_plain += f"[{start_t:.1f}s - {end_t:.1f}s] {speaker_name}: {text}\n\n"

    if not final_html:
        final_html = "Brak zarejestrowanej mowy."
        final_plain = "Brak zarejestrowanej mowy."

    return final_html, final_plain
