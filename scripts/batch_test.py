import requests
import json

BACKEND = "http://localhost:8000"

WEB_RB_QUESTIONS = [
    # ÚČTY
    "Kolik stojí CHYTRÝ účet?",
    "Kolik stojí AKTIVNÍ účet měsíčně?",
    "Jak si otevřu EXKLUZIVNÍ účet online?",
    "Za jakých podmínek je EXKLUZIVNÍ účet zdarma?",
    "Jaký je rozdíl mezi CHYTRÝM a AKTIVNÍM účtem?",
    "Mám CHYTRÝ účet, chci přejít na AKTIVNÍ — jak na to?",
    "Jak funguje studentský účet a je opravdu zdarma?",
    "Jak otevřu dětský účet pro svého syna?",
    # SPOŘENÍ A INVESTICE
    "Jaké spořicí produkty nabízíte?",
    "Kolik procent úroků dostanu na Bonusovém spořicím účtu?",
    "Co musím splnit, abych dostal 4,2 % na spořicím účtu?",
    "Jaký je rozdíl mezi spořicím účtem a termínovaným vkladem?",
    "Kolik mi vynesou peníze na termínovaném vkladu?",
    "Jaká je minimální částka pro termínovaný vklad?",
    "Jak funguje stavební spoření a kolik dostanu od státu?",
    "Co je DIP a jak ho mohu využít pro daňový odpočet?",
    "Chci investovat do podílových fondů — kde začít?",
    "Jaký je rozdíl mezi konzervativním a dynamickým fondem?",
    # HYPOTÉKY A PŮJČKY
    "Chci hypotéku na byt — jak rychle ji schválíte?",
    "Jak dlouho je garantovaná úroková sazba hypotéky?",
    "Kolik si mohu půjčit na hypotéku?",
    "Jaké jsou podmínky pro předčasné splacení hypotéky?",
    "Co je Odpovědná hypotéka a jaké výhody nabízí?",
    "Chci refinancovat hypotéku od jiné banky — je to možné?",
    "Jak funguje RekoPůjčka a jaká je maximální výše?",
    # KARTY A DIGITÁLNÍ SLUŽBY
    "Jaký je rozdíl mezi kreditní kartou EASY a STYLE?",
    "Jaké výhody dává kreditní karta RB Premium?",
    "Co jsou letištní salonky Priority Pass a jak k nim získám přístup?",
    "Jak funguje Bankovní identita RB a k čemu ji použiji?",
    "Jak aktivuji Apple Pay nebo Google Pay ke své kartě?",
]

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
    # Nové testy pro 6 oprav
    "Mám CHYTRÝ účet, chci přejít na AKTIVNÍ — jak na to?": "internetového bankovnictví",
    "Co musím splnit, abych dostal 4,2 % na spořicím účtu?": "4,2",
    "Jaký je rozdíl mezi kreditní kartou EASY a STYLE?": "STYLE",
    "Jaké výhody dává kreditní karta RB Premium?": "Priority Pass",
    "Co jsou letištní salonky Priority Pass a jak k nim získám přístup?": "1 300",
    "Jak aktivuji Apple Pay nebo Google Pay ke své kartě?": "Apple Pay",
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

all_questions = questions + WEB_RB_QUESTIONS

results = []
for q in all_questions:
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
print(f"\nVýsledek: {passed} ✓  {failed} ✗  {len(all_questions)-passed-failed} bez kontroly")
