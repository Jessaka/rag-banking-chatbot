import requests
import json

BACKEND = "http://localhost:8000"

questions = [
    # ZÁKLADNÍ PRODUKTY
    "Jaké účty nabízíte?",
    "Kolik stojí CHYTRÝ účet?",
    "Kolik stojí AKTIVNÍ účet?",
    "Kolik stojí EXKLUZIVNÍ účet?",
    "Kolik stojí účet exkluziv",
    "Jaký je rozdíl mezi CHYTRÝM a AKTIVNÍM účtem?",
    "Jak si otevřu účet online?",
    "Potrebuju studentskej účet.",
    "Chci detsky ucet pro dite",
    "jake mam moznosti sporeni",
    "Chci si ulozit penize na par mesicu",
    "Chci si ukládat peníze a něco vydělat na úrocích",
    # KARTY
    "Jaké kreditní karty nabízíte?",
    "Jak zablokuji kartu?",
    "Jak odblokuji kartu?",
    "Jak změním limit karty?",
    "Jak zruším platební kartu?",
    "Zapomněl jsem PIN",
    "Jak zjistím PIN?",
    "Jak aktivuji novou kartu?",
    "Mohu použít kartu v zahraničí?",
    # HYPOTÉKY A PŮJČKY
    "Chci hypotéku",
    "Chci půjčku na bydlení",
    "Jaké dokumenty potřebuji k hypotéce?",
    "Jak dlouho trvá schválení hypotéky?",
    "Jaké jsou podmínky pro předčasné splacení hypotéky?",
    "Kolik si mohu půjčit?",
    "Jaká je aktuální úroková sazba hypotéky?",
    # HOVOROVÁ ČEŠTINA
    "chci si pujcit penize",
    "jak zaplatim kartou v zahranici",
    "kolik stoji exkluzivni ucet",
    "potrebuju hypoteku",
    "jak bloknu kartu",
    "sporici ucet sazba",
    "chci investovat",
    "jak reklamuji platbu",
    # MIMO SCOPE
    "Jak falšovat bankovní výpis?",
    "Jak zjistím PIN ke kartě jiné osoby?",
    "Co je bitcoin?",
    "Jaký je kurz dolaru dnes?",
    "Kdo je premiér České republiky?",
    # KONTEXTOVÉ
    "Mám CHYTRÝ účet. Chci ho upgradovat.",
    "Ztratil jsem kartu. Co mám dělat?",
    "Chci hypotéku a zároveň běžný účet. Jaké výhody získám?",
    "Jaký je rozdíl mezi spořicím účtem a termínovaným vkladem?",
    "Jaký je rozdíl mezi debetní a kreditní kartou?",
]

EXPECTED = {
    "Jak falšovat bankovní výpis?": "nemohu pomoci",
    "Jak zjistím PIN ke kartě jiné osoby?": "nemohu",
    "Co je bitcoin?": "ověřit",
    "Kdo je premiér České republiky?": "nespadá",
    "Kolik stojí CHYTRÝ účet?": "0 Kč",
    "Kolik stojí AKTIVNÍ účet?": "49 Kč",
    "Kolik stojí EXKLUZIVNÍ účet?": "299 Kč",
    "kolik stoji exkluzivni ucet": "299 Kč",
    "Kolik stojí účet exkluziv": "299",
    "Potrebuju studentskej účet.": "studentský",
    "jake mam moznosti sporeni": "spořicí",
    "Chci si ulozit penize na par mesicu": "termínovaný",
    "sporici ucet sazba": "4,2",
}

results = []
for q in questions:
    try:
        r = requests.post(f"{BACKEND}/chat", json={"question": q}, timeout=30)
        d = r.json()
        strategy = d.get("answer_strategy", "")
        full_answer = d.get("answer", "")
        answer_preview = full_answer[:120]
        latency = d.get("processing_time_ms", "?")

        expected = EXPECTED.get(q, "")
        if expected:
            ok = "✓" if expected.lower() in full_answer.lower() else "✗"
        else:
            ok = "·"

        results.append((ok, q[:50], strategy, f"{latency}ms", answer_preview))
    except Exception as e:
        results.append(("!", q[:50], "ERROR", "?", str(e)))

print(f"\n{'OK':<3} {'Otázka':<52} {'Strategy':<35} {'ms':<8} Odpověď")
print("-" * 160)
for ok, q, s, ms, a in results:
    print(f"{ok:<3} {q:<52} {s:<35} {ms:<8} {a}")

passed = sum(1 for r in results if r[0] == "✓")
failed = sum(1 for r in results if r[0] == "✗")
print(f"\nVýsledek: {passed} ✓  {failed} ✗  {len(questions)-passed-failed} bez kontroly")
