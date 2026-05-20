# Designový styl – kompletní průvodce

Tento dokument popisuje, jak přemýšlím při navrhování a stavění webových rozhraní. Je psán tak, aby byl reprodukovatelný — obsahuje konkrétní hodnoty, třídy, rozhodovací pravidla a příklady. Kdokoli, kdo se jím řídí, by měl dosáhnout vizuálně konzistentního výsledku.

Stack předpokladů: **React + TypeScript + Tailwind CSS**. Principy jsou ale přenositelné do jakéhokoli frameworku.

---

## 1. Základní filozofie

Každé designové rozhodnutí se dá vysvětlit jednou větou. Pokud nedokážu říct proč tam daný prvek je, není tam.

Tři otázky, které si kladu nad každým prvkem:

1. **Pomáhá to uživateli splnit jeho úkol?** Pokud ne, pryč.
2. **Kde je uživatelova pozornost?** Prvek, který ji odebírá od hlavního obsahu, musí mít dobrý důvod.
3. **Co se stane, když to odstraním?** Pokud nic — odstraním to.

Výsledkem je rozhraní, které nevypadá „nahé" nebo „prázdné" — vypadá **klidné**. Uživatel nemusí bojovat s UI, aby se dostal k datům.

### Sedm principů, podle kterých rozhoduji

**1. Klid > vzrušení.** UI je nástroj, ne zábava. Uživatel ho používá kvůli něčemu jinému, ne kvůli němu samotnému. Tlumený design pomáhá soustředění.

**2. Konzistence > kreativita.** Pokud jsem se rozhodl, že modály jsou `rounded-2xl`, jsou `rounded-2xl` všude. Kreativita patří do obsahu a do toho, jak vyřeším konkrétní problém — ne do toho, jestli má sedmý modál jiný rádius.

**3. Obsah > chrome.** Pozadí, bordery, ikony, oddělovače — to vše je „chrome" (rám). Skutečný obsah jsou data uživatele. Chrome nikdy nesmí vizuálně přebít obsah.

**4. Edge case > happy path.** UI navrhuju pro 10 000 položek a dlouhé řetězce, ne pro 3 položky a slovo „Test". Pokud design funguje jen na čistých datech, je rozbitý.

**5. Reverzibilita > prevence.** Místo „Opravdu chcete?" raději umožni undo. Confirmation dialogy únavou ztrácejí účinnost. Toast s „Smazáno. [Undo]" je často lepší než modál „Opravdu smazat?".

**6. Klávesnice > myš.** Každá akce, kterou jde udělat myší, musí jít i klávesnicí. Power useři, accessibility uživatelé a rychlost workflow — všichni z toho profitují.

**7. Skutečnost > skeumorfismus.** UI je software. Tlačítka nepotřebují vypadat jako fyzická tlačítka. Knihy v aplikaci nepotřebují „roh stránky pro otočení". Pracuju s pravdivými softwarovými metaforami.

---

## 2. Barvy

### Paleta

Vždy pracuji s omezenou paletou. Více barev = více rozhodnutí = více chaosu.

```
Primární akce / navigace:     #6366f1  (indigo-500)
Primární hover:               #4f46e5  (indigo-600)
Primární světlé pozadí:       #eef2ff  (indigo-50)

Úspěch / příjem / OK:         #10b981  (emerald-500)
Úspěch hover:                 #059669  (emerald-600)
Úspěch světlé pozadí:         #ecfdf5  (emerald-50)

Chyba / výdaj / destrukce:    #ef4444  (red-500)
Chyba hover:                  #dc2626  (red-600)
Chyba světlé pozadí:          #fef2f2  (red-50)

Varování:                     #f59e0b  (amber-500)
Varování světlé pozadí:       #fffbeb  (amber-50)

Info:                         #3b82f6  (blue-500)
Info světlé pozadí:           #eff6ff  (blue-50)

Text primární:                #111827  (gray-900)
Text sekundární:              #6b7280  (gray-500)
Text terciární / placeholder: #9ca3af  (gray-400)
Text na barevném bg:          #ffffff

Pozadí stránky (light):       #f9fafb  (gray-50)
Pozadí karet (light):         #ffffff
Border (light):               #e5e7eb  (gray-200)
Border silnější:              #d1d5db  (gray-300)

Pozadí stránky (dark):        #0f172a  (slate-900)
Pozadí karet (dark):          #1e293b  (slate-800)
Border (dark):                #334155  (slate-700)
Text primární (dark):         #f1f5f9  (slate-100)
Text sekundární (dark):       #94a3b8  (slate-400)
```

### Pravidla použití

- **Primární barva** pouze na: CTA tlačítka, aktivní navigační položka, focus ring, interaktivní ikony.
- **Barevné pozadí** (indigo-50, emerald-50 atd.) používám na karty se statistikami nebo badges — nikdy jako pozadí celé sekce.
- **Šedé škály** tvoří 80 % rozhraní. Barva je vzácná, proto funguje.
- Nikdy nepoužívám více než 3 sémantické barvy na jedné stránce (primární + úspěch/chyba + varování). Víc barev = vizuální hluk.
- Gradientům se vyhýbám v UI komponentách. Gradienty patří do ilustrací nebo hero obrázků, ne do tlačítek nebo karet.

### Kontrast (WCAG)

Každá kombinace text + pozadí, kterou používám, musí splňovat minimum WCAG AA:

```
Běžný text (< 18px nebo < 14px bold):  poměr 4.5:1
Velký text (≥ 18px nebo ≥ 14px bold):  poměr 3.0:1
UI prvky a grafika:                     poměr 3.0:1
```

Ověřené kombinace v mojí paletě (na bílém pozadí):

```
text-gray-900   na  bg-white   →  19.5:1   ✅ AAA
text-gray-700   na  bg-white   →  10.8:1   ✅ AAA
text-gray-500   na  bg-white   →   4.6:1   ✅ AA (jen pro běžný text těsně)
text-gray-400   na  bg-white   →   3.1:1   ❌ jen velký text nebo dekorace
text-indigo-600 na  bg-white   →   6.9:1   ✅ AAA
text-emerald-600 na bg-white   →   4.5:1   ✅ AA (těsně)
text-red-600    na  bg-white   →   5.9:1   ✅ AAA
```

`text-gray-400` používám jen pro placeholder, captions a dekorativní ikony — nikdy pro tělo textu. `text-gray-500` je hranice — pro nejdůležitější sekundární text raději `text-gray-600`.

### Sémantika barev

Barva nese informaci, ne dekoraci. Pravidlo: pokud bych prvek odstranil a barva by zmizela, ztratil bych informaci.

- **Zelená** = pozitivní, příjem, úspěch, růst, dokončeno.
- **Červená** = negativní, výdaj, chyba, pokles, destrukce.
- **Amber/oranžová** = varování, vyžaduje pozornost, ne fatální.
- **Modrá/indigo** = informace, neutrální akce, primární CTA.
- **Šedá** = neutrální, vypnuté, sekundární.

Nikdy nepoužívám zelenou pro „neutrální" akci nebo červenou pro „cancel". To je zmatení sémantiky.

---

## 3. Typografie

### Font

```
font-family: 'Inter', system-ui, -apple-system, sans-serif;
```

Inter z Google Fonts nebo systémový sans-serif. Nikdy dekorativní, nikdy serif v rozhraní.

Pro čísla v tabulkách a stat kartách: `font-variant-numeric: tabular-nums` — všechny číslice jsou stejně široké, číselné sloupce se zarovnají i bez `text-right`.

```css
.tabular-nums { font-variant-numeric: tabular-nums; }
```

V Tailwindu přes utility `tabular-nums`.

### Stupnice — přesné kombinace (Tailwind)

| Role | Tailwind třídy | Použití |
|------|---------------|---------|
| Page title | `text-2xl font-bold text-gray-900` | Nadpis stránky (H1) |
| Section title | `text-lg font-semibold text-gray-900` | Nadpis sekce nebo karty |
| Card value | `text-3xl font-bold text-gray-900 tabular-nums` | Velká číselná hodnota (stat karta) |
| Card label | `text-sm font-medium text-gray-500` | Popisek pod/nad hodnotou |
| Body | `text-sm text-gray-700` | Běžný text v tabulkách, popisech |
| Body large | `text-base text-gray-700` | Hlavní obsah článků, popisy v detailu |
| Secondary | `text-sm text-gray-500` | Datum, metadata, hint texty |
| Caption | `text-xs text-gray-400` | Nejmenší popisky, timestamps |
| Link | `text-sm font-medium text-indigo-600 hover:text-indigo-700` | Textové odkazy |
| Code inline | `text-sm font-mono bg-gray-100 px-1.5 py-0.5 rounded` | Inline kód, klávesy |

### Pravidla

- **Nikdy** nepoužívám `font-bold` a `text-gray-500` zároveň — tučnost říká důležitost, šedá říká nevýznamnost. V kombinaci si odporují.
- Hierarchii buduji maximálně ze **3 úrovní** na jedné stránce (nadpis → hodnota → metadata).
- Řádkování (`leading-`) nechávám na výchozím Tailwind nastavení (`leading-normal` = 1.5). Pro nadpisy `leading-tight` (1.25), pro dlouhé pasáže `leading-relaxed` (1.625).
- Maximální šířka čtecího sloupce: `max-w-prose` (65ch). Pro formuláře: `max-w-md` (28rem).
- Letter-spacing: výchozí. Pro `uppercase` text (např. table header) `tracking-wider` (0.05em) — uppercase bez letter-spacingu vypadá nahuštěně.
- **Nikdy** nepoužívám `text-justify` v UI. Vytváří „řeky" mezery, špatně se čte.

### Hierarchie nadpisů

V rámci jedné stránky:

```
H1  →  text-2xl font-bold       (jedna na stránku, page title)
H2  →  text-xl  font-semibold   (hlavní sekce stránky)
H3  →  text-lg  font-semibold   (sub-sekce, nadpisy karet)
H4  →  text-base font-semibold  (sekce uvnitř karty)
```

Skoky velikostí jsou znatelné, ale ne dramatické. Mezi H1 a H2 je rozdíl 4px, ne 16px — hierarchie je o váze a kontextu, ne jen o velikosti.

---

## 4. Microcopy a tón hlasu

Texty v UI jsou polovina designu. Špatný copy zničí jinak dokonalé rozhraní.

### Tón

- **Přátelský, ne korporátní.** „Něco se pokazilo, zkus to znovu" > „Došlo k neočekávané systémové chybě."
- **Věcný, ne marketingový.** „Uložit" > „Uložit změny a pokračovat".
- **Aktivní, ne pasivní.** „Smazali jsme transakci" > „Transakce byla smazána".
- **Konkrétní, ne obecný.** „Chybí kategorie" > „Nevalidní vstup".

Tykám/vykám konzistentně napříč celou aplikací. Nikdy nemíchat.

### Tlačítka

Sloveso, které popisuje, **co se stane po kliknutí**:

```
✅ Uložit         ❌ OK
✅ Smazat         ❌ Ano
✅ Přidat účet    ❌ Pokračovat
✅ Odhlásit       ❌ Potvrdit
```

V češtině používám infinitiv nebo rozkaz konzistentně. Já volím infinitiv („Uložit", „Smazat") — vypadá to neutrálněji a líp se to skloňuje v různých kontextech.

Pro destruktivní akce sloveso konkretizuji:

```
✅ Smazat transakci    ❌ Smazat
✅ Odhlásit se         ❌ Odhlásit
```

V confirmation dialogu vědět **co** mažu je důležitější než šetřit místem.

### Chybové zprávy

Pravidlo: **co se stalo + proč + co dělat**.

```
❌ "Chyba při ukládání."
✅ "Transakci se nepodařilo uložit — chybí kategorie. Vyber kategorii a zkus to znovu."

❌ "Invalid input."
✅ "E-mail musí obsahovat @."

❌ "Network error."
✅ "Nepodařilo se připojit k serveru. Zkontroluj internetové připojení."
```

Nikdy neobviňuj uživatele. „Zadal jsi špatný e-mail" → „E-mail musí obsahovat @". Sklouznutí do obviňování („Špatně jsi…", „Tvoje chyba…") působí nepřátelsky.

### Confirmation copy

Destruktivní akce vždy obsahuje slovo **„trvale"** nebo **„nevratně"**:

```
✅ "Smazat transakci? Tato akce je nevratná."
✅ "Smazat účet? Všechna data budou trvale odstraněna."
```

Pro nedestruktivní (archive, hide) tento jazyk nepoužívám.

### Prázdné stavy

Pravidlo: **co tu chybí + proč + jak to opravit**.

```
✅ "Žádné transakce
   Zatím jsi nezaznamenal žádnou transakci. Přidej první a začni sledovat své finance.
   [Přidat první transakci]"

❌ "No data"
```

### Pluralizace

Česká pluralizace má 3 formy (`one/few/many`). Nikdy nepiš `1 transakcí` ani `5 transakce`.

```tsx
function pluralize(count: number, forms: [string, string, string]): string {
  if (count === 1) return forms[0];                 // 1 transakce
  if (count >= 2 && count <= 4) return forms[1];    // 2 transakce
  return forms[2];                                  // 5 transakcí
}

// Použití:
pluralize(count, ['transakce', 'transakce', 'transakcí']);
```

Pro robustnější řešení `Intl.PluralRules`:

```tsx
const pr = new Intl.PluralRules('cs-CZ');
// pr.select(1) → "one"
// pr.select(2) → "few"
// pr.select(5) → "many"
```

Pro **0**: většinou používám tvar pro „many" („0 transakcí"), ne speciální „žádné" — výjimkou jsou prázdné stavy, kde slovo „žádné" čte lépe.

### Capitalizace

V češtině NEpoužívám Title Case v nadpisech. Anglická zvyklost „Add New Transaction" → česky „Přidat novou transakci" (jen první písmeno věty velké). Title case v češtině vypadá amatérsky.

Výjimky: vlastní jména, značky, akronymy.

### Čísla v textu

Pravidla z české typografie:

- Čísla 1–10 slovy v běžném textu („pět transakcí"), 11+ číslicí („25 transakcí").
- Ve statistikách, datech, tabulkách: vždy číslicí (i 1).
- Tisícové oddělovače: úzká nedělitelná mezera (`&#8239;`) nebo běžná pevná mezera. Tailwind / Intl to řeší automaticky.

### Datum a čas

V CZ formátu: `13. 5. 2026`, ne `13.5.2026` (chybí mezery) ani `13/5/2026` (US formát).

Čas: 24hodinový formát `14:30`, ne `2:30 PM`.

Relativní čas: jen pro události mladší než 24 hodin („před 5 minutami", „před 2 hodinami"). Starší události vždy absolutní datum.

### Kapitalizace v UI

```
Page title:       Sentence case  →  "Přehled transakcí"
Section title:    Sentence case  →  "Tento měsíc"
Button:           Sentence case  →  "Přidat transakci"
Label:            Sentence case  →  "Název transakce"
Table header:     UPPERCASE      →  "DATUM"
Badge:            UPPERCASE      →  "AKTIVNÍ"
Placeholder:      Sentence case  →  "Např. Nákup v Albertu"
```

---

## 5. Spacing — mezery a odsazení

Spacing je nejdůležitější designová proměnná. Špatné mezery rozbijí i jinak dobré UI.

### Systém

```
4px   (1)   — mezi ikonou a textem v buttonu, mezi badge prvky
8px   (2)   — mezi labelem a inputem, mezi malými prvky
12px  (3)   — vnitřní padding malých komponent (badge, small button)
16px  (4)   — standardní vnitřní padding (input, table cell)
24px  (6)   — padding karty, mezera mezi kartami v gridu
32px  (8)   — padding stránky na mobilu, velká mezera mezi sekcemi
48px  (12)  — mezera mezi hlavními sekcemi stránky
64px  (16)  — padding stránky na desktopu (max)
```

Nikdy `5px`, `7px`, `11px`. Držet se 4px gridu (Tailwind to vynucuje sám). Nestandardní hodnota vyžaduje vědomé rozhodnutí — pak používám arbitrary value `p-[18px]` s komentářem proč.

### Konkrétní pravidla

- **Karta:** `p-6` (24px všude). Na mobilech `p-4`, ale raději `p-6` i tam.
- **Grid gap:** `gap-6` mezi kartami, `gap-4` mezi menšími prvky.
- **Sekce na stránce:** `space-y-8` nebo `mb-8` mezi sekcemi.
- **Formulář:** `space-y-4` mezi poli, `space-y-6` mezi skupinami polí.
- **Tabulka:** `px-4 py-3` na buňce. Dostatek prostoru, aby řádky nebyly slepené.
- **Sidebar šířka:** `w-64` (256px) na desktopu — dost na text a ikony, ne tolik, aby kradl místo obsahu.
- **Hlavní obsah:** `max-w-7xl mx-auto px-4 sm:px-6 lg:px-8` — standardní container.

### Vnější vs vnitřní mezera

- Vnitřní padding = `p-*` — vždy uvnitř komponenty, definuje její „dech".
- Vnější mezera = `gap-*` na rodiči, ne `margin-*` na potomku. Margin způsobuje problémy (collapsing margins, nelze ho lehce reset).

```tsx
// ✅ Správně — gap na rodiči
<div className="flex flex-col gap-4">
  <Card />
  <Card />
</div>

// ❌ Špatně — margin na potomcích
<div>
  <Card className="mb-4" />
  <Card className="mb-4" />
</div>
```

---

## 6. Shadow a border-radius hierarchie

### Stíny — kdy použít jaký

```
shadow-none  — interaktivní prvky v kartách (buttony, inputy)
shadow-sm    — karty, tabulky, standardní plochy
shadow       — floating prvky, které jsou "nad" stránkou ale ne overlay
shadow-md    — dropdown menu, popovers
shadow-lg    — modální okna, toasty
shadow-xl    — nikdy v UI (příliš výrazné, dekorativní)
shadow-2xl   — nikdy
```

Stín vždy kombinuji s borderem. Výjimka: dropdown může mít jen stín bez borderu, ale jen pokud pozadí kontrastuje s obsahem pod ním.

V dark mode `shadow-*` jsou skoro neviditelné (stín je tmavý na tmavém pozadí). Místo toho zvyšuji kontrast borderu (`dark:border-slate-600` místo `dark:border-slate-700`) a často border úplně stačí.

### Border-radius — konzistentní hierarchie

```
rounded-full  — badges, avatary, progress bar fill, pill taby
rounded-2xl   — modální okna, velké karty (24px)
rounded-xl    — standardní karty, dropdown (12px)
rounded-lg    — vnořené prvky v kartách, ikony v kontejnerech (8px)
rounded-md    — tlačítka, inputy, selekty, taby (6px)
rounded       — drobné prvky, tooltip (4px)
rounded-sm    — výjimečně, pro velmi malé elementy (2px)
```

Tato hierarchie se nesmí porušit. Tlačítko nemá být `rounded-xl` (moc velké zaoblení), karta nemá být `rounded-md` (moc malé). Konzistence zaoblení = vizuální jednotnost.

**Pravidlo vnořeného radiusu:** vnořený prvek má vždy menší rádius než jeho rodič. Karta `rounded-xl` (12px) → ikona-kontejner uvnitř `rounded-lg` (8px) → vnořený badge `rounded-md` (6px).

---

## 7. Vizuální rytmus a oddělení sekcí

Obsah stránky dělím prostorem, ne čarami. Oddělovač (`<hr>`) je poslední možnost — nejdřív zkusím `space-y-8` nebo `mb-8`.

### Kdy použít oddělovač vs prostor

```
Prostor (space-y-8):   mezi sekcemi stejné úrovně na stránce
Oddělovač (border-t):  uvnitř karty, kde jsou jasně oddělené části (header / body / footer)
Oddělovač v tabulce:   divide-y divide-gray-100 — automatické jemné oddělovače řádků
Nikdy hr:              v běžném obsahu stránky — vždy nahradím margin/padding
```

### Vizuální rytmus

Skupiny příbuzného obsahu mají těsné mezery. Nesouvisející skupiny mají velké mezery. Oko čtenáře sleduje velikost mezery jako vodítko k příbuznosti.

```
Ikona + popisek vedle ní:        gap-2   (8px)   — jedno atomické celé
Label + input:                   space-y-1.5    — těsně svázané
Pole ve formuláři:               space-y-4      — oddělené ale patří k sobě
Sekce na stránce:                space-y-8      — jasná předěl
Hlavní vizuální bloky stránky:   space-y-10 nebo space-y-12
```

**Gestalt princip blízkosti:** prvky, které jsou blízko sebe, vnímáme jako skupinu. Špatně rozmístěné mezery rozbijí čitelnost rychleji než špatné barvy.

---

## 8. Karty

Karta je základní stavební blok. Používám ji pro každou logicky oddělenou skupinu informací.

### Anatomie karty

```tsx
<div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
  {/* obsah */}
</div>
```

**Tmavý režim:**

```tsx
<div className="bg-white dark:bg-slate-800 rounded-xl border border-gray-200 dark:border-slate-700 shadow-sm p-6">
```

### Pravidla karet

- `rounded-xl` (12px) — mé výchozí zaoblení. `rounded-lg` (8px) pro menší vnořené prvky. `rounded-md` pro inputy a tlačítka.
- `shadow-sm` — jemný stín. Nikdy `shadow-lg` nebo `shadow-xl` na běžné kartě — to patří na modální okna.
- `border border-gray-200` — vždy. Stín bez borderu vypadá nejistě. Border bez stínu je flat design, který funguje, ale já preferuji kombinaci.
- Karty nikdy nemají barevné pozadí (kromě stat karet se zvýrazněním). Barevné pozadí je pro badges a alerts.

### Stat karta (číslo s popiskem)

```tsx
<div className="bg-white dark:bg-slate-800 rounded-xl border border-gray-200 dark:border-slate-700 shadow-sm p-6">
  <div className="flex items-center justify-between mb-4">
    <span className="text-sm font-medium text-gray-500 dark:text-slate-400">Celkové příjmy</span>
    <div className="w-10 h-10 bg-emerald-50 dark:bg-emerald-900/20 rounded-lg flex items-center justify-center">
      <TrendingUpIcon className="w-5 h-5 text-emerald-500" />
    </div>
  </div>
  <div className="text-3xl font-bold text-gray-900 dark:text-slate-100 tabular-nums">45 000 Kč</div>
  <div className="flex items-center gap-1 text-sm mt-1">
    <ArrowUpIcon className="w-3.5 h-3.5 text-emerald-500" />
    <span className="text-emerald-600 dark:text-emerald-400 font-medium">+12,5 %</span>
    <span className="text-gray-500 dark:text-slate-400">oproti minulému měsíci</span>
  </div>
</div>
```

Klíč: ikona v barevném kulatém/čtvercovém kontejneru vpravo nahoře, velká hodnota, malý popisek pod ní s deltou (změna oproti předchozímu období).

### Karta jako odkaz / klikatelná karta

```tsx
<a
  href="..."
  className="block bg-white dark:bg-slate-800 rounded-xl border border-gray-200 dark:border-slate-700 shadow-sm p-6
             hover:border-gray-300 dark:hover:border-slate-600 hover:shadow-md transition-all duration-150
             focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2"
>
```

Pravidla:

- Klikatelná karta má hover stav (border tmavší + shadow silnější).
- Vždy `cursor-pointer` se neexplicituje — `<a>` ho má sám.
- Vždy focus ring pro klávesnici.
- Celá karta je klikatelná, ne jen text uvnitř.

---

## 9. Tlačítka

### Varianty

**Primary** — hlavní akce na stránce (max 1 na stránce):

```tsx
className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 
           text-white text-sm font-medium rounded-md transition-colors duration-150
           focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2
           disabled:opacity-50 disabled:cursor-not-allowed
           active:scale-[0.98]"
```

**Secondary** — sekundární akce, alternativa k primary:

```tsx
className="inline-flex items-center gap-2 px-4 py-2 bg-white hover:bg-gray-50
           text-gray-700 text-sm font-medium rounded-md border border-gray-300
           transition-colors duration-150 focus:outline-none focus:ring-2 
           focus:ring-indigo-500 focus:ring-offset-2"
```

**Ghost** — akce v tabulkách, inline akce:

```tsx
className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-gray-500 hover:text-gray-700 
           hover:bg-gray-100 text-sm rounded-md transition-colors duration-150"
```

**Destructive** — mazání, nevratné akce:

```tsx
className="inline-flex items-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-700
           text-white text-sm font-medium rounded-md transition-colors duration-150"
```

**Link** — akce, co vypadá jako odkaz:

```tsx
className="text-sm font-medium text-indigo-600 hover:text-indigo-700 dark:text-indigo-400 
           dark:hover:text-indigo-300 transition-colors duration-150"
```

### Velikosti

```
xs (text-xs, px-2 py-1)      — v hustých tabulkách, kontextové akce
sm (text-sm, px-2.5 py-1.5)  — kompaktní UI, sekundární akce
md (text-sm, px-4 py-2)      — default
lg (text-base, px-5 py-2.5)  — primární CTA na landing pages, hero
xl (text-base, px-6 py-3)    — výjimečné, marketing
```

### Pravidla tlačítek

- Vždy `transition-colors duration-150` — žádný jiný druh přechodu na tlačítcích.
- Vždy `focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2` — přístupnost.
- `active:scale-[0.98]` na primary — drobný „push" feedback při kliku.
- Ikona v tlačítku: `w-4 h-4`, mezera `gap-2`.
- Výška tlačítka: `py-2` pro standardní, `py-1.5` pro malé (v tabulkách), `py-2.5` pro velké CTA.
- Nikdy `w-full` na primárním tlačítku mimo formulář nebo mobil.
- Text tlačítka: aktivní sloveso (Přidat, Uložit, Smazat) — nikdy „OK" nebo „Potvrdit".
- **Hit target:** minimálně 36×36 px na desktopu, 44×44 px na mobilu — `py-2` + `px-4` to vždy splní.

### Loading state na tlačítku

```tsx
<button disabled={loading} className="...">
  {loading ? (
    <>
      <Spinner className="w-4 h-4 animate-spin" />
      Ukládám…
    </>
  ) : (
    <>
      <SaveIcon className="w-4 h-4" />
      Uložit
    </>
  )}
</button>
```

Pravidla:

- Spinner nahradí ikonu, ne text — uživatel chápe, co tlačítko dělá.
- Text se může změnit z infinitivu na průběhový tvar („Ukládám…").
- Tlačítko je `disabled` po dobu loading — zamezí double-submitu.
- Nikdy nemizí, jen je passive. Mizení rozbije layout.

### Icon-only tlačítka

```tsx
<button
  aria-label="Smazat transakci"
  className="inline-flex items-center justify-center w-9 h-9 text-gray-500 hover:text-gray-700 
             hover:bg-gray-100 rounded-md transition-colors duration-150
             focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2"
>
  <TrashIcon className="w-4 h-4" />
</button>
```

Pravidla:

- Vždy `aria-label` — screen reader jinak nepřečte funkci.
- Vždy `title` pro hover tooltip (volitelně, ale doporučeno).
- Minimální velikost `w-9 h-9` (36px) na desktopu, `w-11 h-11` (44px) na mobilu.
- Hit target je celé tlačítko, ne jen ikona uvnitř.

---

## 10. Formuláře a inputy

### Input

```tsx
<div className="space-y-1.5">
  <label htmlFor="title" className="block text-sm font-medium text-gray-700 dark:text-slate-300">
    Název transakce
  </label>
  <input
    id="title"
    className="block w-full px-3 py-2 text-sm text-gray-900 dark:text-slate-100
               bg-white dark:bg-slate-900 border border-gray-300 dark:border-slate-600
               rounded-md placeholder-gray-400 dark:placeholder-slate-500
               focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent
               transition-shadow duration-150"
  />
  {error && (
    <p className="text-xs text-red-500 flex items-center gap-1" role="alert">
      <AlertCircleIcon className="w-3.5 h-3.5" /> {error}
    </p>
  )}
  {hint && !error && (
    <p className="text-xs text-gray-500 dark:text-slate-400">{hint}</p>
  )}
</div>
```

### Select

Stejný styling jako input — konzistence. Nikdy nativní select bez vlastního stylování.

Pro pokročilejší selecty (vyhledávání v možnostech, multi-select, async načítání) používám Headless UI Listbox nebo Combobox — nativní `<select>` nestačí.

### Checkbox a radio

```tsx
// Checkbox
<label className="flex items-center gap-2 cursor-pointer">
  <input
    type="checkbox"
    className="w-4 h-4 rounded border-gray-300 text-indigo-600 
               focus:ring-2 focus:ring-indigo-500 focus:ring-offset-0"
  />
  <span className="text-sm text-gray-700 dark:text-slate-300">Zapamatovat přihlášení</span>
</label>

// Radio group
<fieldset className="space-y-2">
  <legend className="text-sm font-medium text-gray-700 mb-2">Typ transakce</legend>
  <label className="flex items-center gap-2 cursor-pointer">
    <input type="radio" name="type" value="income" className="..." />
    <span className="text-sm">Příjem</span>
  </label>
  <label className="flex items-center gap-2 cursor-pointer">
    <input type="radio" name="type" value="expense" className="..." />
    <span className="text-sm">Výdaj</span>
  </label>
</fieldset>
```

Klikatelná oblast = celý label + input, ne jen čtvereček/kolečko. Hit target velký.

### Toggle (switch)

Toggle používám pro **okamžitě aplikovatelné** binární volby (zapnout dark mode, zapnout notifikace). Pro formulářová pole s explicit Save tlačítkem používám checkbox.

```tsx
<button
  role="switch"
  aria-checked={enabled}
  onClick={() => setEnabled(!enabled)}
  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors duration-200
             focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 ${
    enabled ? 'bg-indigo-600' : 'bg-gray-300 dark:bg-slate-600'
  }`}
>
  <span
    className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform duration-200 ${
      enabled ? 'translate-x-6' : 'translate-x-1'
    }`}
  />
</button>
```

### Pravidla formulářů

- Label vždy **nad** inputem, nikdy vedle (u inline formulářů výjimečně vedle, ale musí být konzistentní).
- Vždy `htmlFor`/`id` propojení labelu a inputu — kliknutí na label fokusuje input + funguje pro screen readery.
- Mezera mezi labelem a inputem: `space-y-1.5` (6px).
- Mezera mezi poli: `space-y-4` (16px).
- Chybová zpráva: pod inputem, červená, malá, s ikonou, `role="alert"` — nikdy červený border bez zprávy.
- Hint text (pod inputem, šedý): jen pokud je třeba vysvětlit formát. Nikdy zároveň hint a chybu — chyba má prioritu.
- Placeholder text: popisuje formát nebo příklad, ne název pole (to je label). Příklad: label „Telefon", placeholder „+420 123 456 789".
- Povinná pole: neoznačuji hvězdičkou — validuji až při submitu (nebo při blur po prvním submitu) a chybu zobrazím u konkrétního pole.
- Šířka formuláře: `max-w-md` nebo `max-w-lg`. Nikdy full-width formulář na wide screenu.

### Validace — kdy

```
On submit (poprvé):     vždy. Před prvním submitem nehlásím chyby — uživatel ještě nedopsal.
On blur (po submitu):   ano. Po prvním submitu se kontrola spustí při opuštění pole.
On change:              jen pro async kontroly (např. dostupnost username) s debounce 500ms.
```

Pravidlo: **uživatel se nesmí dozvědět o chybě dřív, než ji udělal**. Hlásit „Heslo příliš krátké" po napsání 3 znaků z 8 = předčasné. Hlásit při blur nebo submit = na čas.

### Auto-focus

První input ve formuláři dostává `autoFocus` jen pokud je formulář **primárním obsahem stránky** (login, search modal). Nikdy autofocus na formulář v rámci stránky s jiným obsahem — krade fokus, ruší klávesnicovou navigaci.

### Inline edit pattern

Pro rychlé úpravy hodnot v tabulce nebo detailu:

```tsx
const [editing, setEditing] = useState(false);
const [value, setValue] = useState(initialValue);

return editing ? (
  <input
    autoFocus
    value={value}
    onChange={e => setValue(e.target.value)}
    onBlur={() => { save(value); setEditing(false); }}
    onKeyDown={e => {
      if (e.key === 'Enter') { save(value); setEditing(false); }
      if (e.key === 'Escape') { setValue(initialValue); setEditing(false); }
    }}
    className="..."
  />
) : (
  <button
    onClick={() => setEditing(true)}
    className="text-left hover:bg-gray-50 rounded px-2 py-1 -mx-2 -my-1"
  >
    {value || <span className="text-gray-400">Klikni pro úpravu</span>}
  </button>
);
```

Pravidla inline editu:

- Kliknutí na hodnotu → input s autofocus.
- `Enter` nebo blur → uložit.
- `Escape` → zrušit, vrátit původní hodnotu.
- Vizuální indikace, že je hodnota klikatelná (hover background).
- Auto-save indikátor („Uloženo • před 2s") nebo toast po úspěchu.

---

## 11. Navigace (Sidebar)

### Desktop sidebar

```
Šířka:         w-64 (256px), fixed, vlevo
Pozadí:        bg-white dark:bg-slate-900
Border:        border-r border-gray-200 dark:border-slate-700
Padding:       p-4
```

### Struktura sidebar položky

```tsx
// Neaktivní:
className="flex items-center gap-3 px-3 py-2.5 text-sm font-medium text-gray-600 
           dark:text-slate-400 rounded-lg hover:bg-gray-100 dark:hover:bg-slate-800 
           transition-colors duration-150"

// Aktivní:
className="flex items-center gap-3 px-3 py-2.5 text-sm font-medium text-indigo-600 
           dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-900/20 rounded-lg"
```

Aktivní položku poznám vždy: barva textu + barevné pozadí. Pouze tučný text nestačí — slabě viditelné na první pohled.

### Sekce sidebaru

Pokud je položek víc než 7, dělím je do sekcí s nadpisy:

```tsx
<nav className="space-y-6">
  <div>
    <h3 className="px-3 mb-2 text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-slate-500">
      Hlavní
    </h3>
    <ul className="space-y-1">...</ul>
  </div>
  <div>
    <h3 className="px-3 mb-2 text-xs font-semibold uppercase tracking-wider text-gray-400 dark:text-slate-500">
      Nastavení
    </h3>
    <ul className="space-y-1">...</ul>
  </div>
</nav>
```

### Mobilní navigace

Na mobilech: bottom navigation bar, ne hamburger menu. Hamburger menu vyžaduje kliknutí navíc. Bottom bar je vždy viditelný.

```
Pozadí:     bg-white dark:bg-slate-900
Border:     border-t border-gray-200 dark:border-slate-700
Výška:      h-16
Ikony:      w-5 h-5
Label:      text-xs pod ikonou
Aktivní:    text-indigo-600, ikona indigo
Neaktivní:  text-gray-500
```

Hamburger používám jen pro:

- Aplikace s 10+ navigačními položkami, kde bottom bar nestačí.
- Aplikace primárně pro power users na tabletu (např. admin).

Bottom bar má max **5 položek** — víc se nevejde čitelně.

### Breadcrumbs

Breadcrumbs používám jen v aplikacích s hluboce vnořenou strukturou (≥ 3 úrovně). V flat aplikacích (přehled → detail) jsou zbytečné.

```tsx
<nav aria-label="Breadcrumb" className="flex items-center gap-1 text-sm text-gray-500">
  <a href="/" className="hover:text-gray-700">Domů</a>
  <ChevronRightIcon className="w-3.5 h-3.5" />
  <a href="/transactions" className="hover:text-gray-700">Transakce</a>
  <ChevronRightIcon className="w-3.5 h-3.5" />
  <span className="text-gray-900 font-medium">Detail</span>
</nav>
```

Poslední úroveň je nadpis stránky, nikoli odkaz.

---

## 12. Tabulky

```tsx
<div className="bg-white dark:bg-slate-800 rounded-xl border border-gray-200 dark:border-slate-700 shadow-sm overflow-hidden">
  <table className="w-full text-sm">
    <thead>
      <tr className="border-b border-gray-200 dark:border-slate-700 bg-gray-50 dark:bg-slate-900/50">
        <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 dark:text-slate-400 uppercase tracking-wider">
          Název
        </th>
      </tr>
    </thead>
    <tbody className="divide-y divide-gray-100 dark:divide-slate-700">
      <tr className="hover:bg-gray-50 dark:hover:bg-slate-700/50 transition-colors duration-100">
        <td className="px-4 py-3 text-gray-900 dark:text-slate-100">
          ...
        </td>
      </tr>
    </tbody>
  </table>
</div>
```

### Pravidla tabulek

- Header: `text-xs uppercase tracking-wider text-gray-500` — odlišuje se od dat, neplete se s nimi.
- `divide-y divide-gray-100` na tbody — jemné oddělovače řádků, ne silné bordery.
- Hover na řádku: `hover:bg-gray-50` — jemné, ne výrazné.
- Numerické hodnoty: `text-right font-medium tabular-nums` — zarovnání čísel vpravo je standard.
- Kladné/záporné hodnoty: zelená/červená + prefix +/−.
- Na mobilech tabulku nahradím kartičkami (card list) — tabulky na malých obrazovkách nefungují.

### Sortovací header

```tsx
<th className="text-left px-4 py-3">
  <button
    onClick={() => toggleSort('date')}
    className="inline-flex items-center gap-1 text-xs font-semibold uppercase tracking-wider 
               text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200 
               transition-colors duration-150"
  >
    Datum
    {sortKey === 'date' && (
      sortDir === 'asc' 
        ? <ChevronUpIcon className="w-3 h-3" />
        : <ChevronDownIcon className="w-3 h-3" />
    )}
  </button>
</th>
```

Pravidla sortování:

- Klik na header sortuje. Druhý klik obrátí směr. Třetí klik zruší (volitelně).
- Aktivní sort: ikona šipky vedle textu, text mírně tmavší.
- Default sort: poslední změna nebo nejnovější — to, co uživatel pravděpodobně chce vidět nahoře.

### Selected row pattern

Pokud uživatel může vybírat řádky (checkbox):

```tsx
<tr className={`transition-colors duration-100 ${
  selected
    ? 'bg-indigo-50 dark:bg-indigo-900/20'
    : 'hover:bg-gray-50 dark:hover:bg-slate-700/50'
}`}>
  <td className="px-4 py-3 w-12">
    <input
      type="checkbox"
      checked={selected}
      onChange={...}
      className="..."
    />
  </td>
  ...
</tr>
```

- Selected pozadí silnější než hover, ale ne výrazné.
- Hlavička bar nad tabulkou s počtem vybraných + bulk akce, který se objeví jen když je něco vybráno.

### Pagination vs infinite scroll vs „Load more"

```
Pagination:       analytické pohledy, kde se uživatel vrací k záznamu (transakce, řády)
Infinite scroll:  feedy, kde záleží na novosti (social media, notifikace)
"Load more":      kompromis — záměrný čin uživatele, ale bez paging UI
```

V business aplikacích preferuji **pagination** — uživatel ví, kde je, může si poznamenat „strana 3" a vrátit se.

---

## 13. Badges a tagy

```tsx
// Neutrální:
className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium 
           bg-gray-100 text-gray-700 dark:bg-slate-700 dark:text-slate-300"

// Barevná (kategorie):
// Barva se určí z category.color — vždy s 15% opacity pozadím a plnou barvou textu:
style={{ backgroundColor: `${category.color}20`, color: category.color }}
className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium"

// Status úspěch:
className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium 
           bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400"

// Status chyba:
className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium 
           bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400"

// Status varování:
className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium 
           bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-400"
```

### Badge s ikonou / dot

Pro statusy s tečkou (online/offline, draft/published):

```tsx
<span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium 
                 bg-emerald-50 text-emerald-700">
  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
  Aktivní
</span>
```

Badges jsou vždy `rounded-full` (pilulka). Nikdy `rounded-md` na badge — to patří na buttony.

### Removable badges (filter chips)

```tsx
<span className="inline-flex items-center gap-1.5 pl-2.5 pr-1 py-0.5 rounded-full text-xs font-medium 
                 bg-indigo-50 text-indigo-700 dark:bg-indigo-900/20 dark:text-indigo-400">
  Kategorie: Jídlo
  <button
    onClick={onRemove}
    className="p-0.5 rounded-full hover:bg-indigo-100 dark:hover:bg-indigo-900/40"
    aria-label="Odstranit filtr"
  >
    <XIcon className="w-3 h-3" />
  </button>
</span>
```

---

## 14. Modální okna

```tsx
// Backdrop:
className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4"

// Kontejner:
className="bg-white dark:bg-slate-800 rounded-2xl shadow-xl w-full max-w-md 
           max-h-[90vh] overflow-y-auto"

// Header:
className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-slate-700"

// Body:
className="px-6 py-6"

// Footer:
className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-200 
           dark:border-slate-700 bg-gray-50 dark:bg-slate-900/50"
```

### Animace modálu

```css
/* Vstup */
@keyframes modal-in {
  from { opacity: 0; transform: scale(0.95) translateY(8px); }
  to   { opacity: 1; transform: scale(1) translateY(0); }
}
.modal-enter { animation: modal-in 150ms ease-out; }

/* Backdrop */
@keyframes backdrop-in {
  from { opacity: 0; }
  to   { opacity: 1; }
}
.backdrop-enter { animation: backdrop-in 150ms ease-out; }
```

### Focus management v modálu

Kritické pro klávesnici a accessibility:

- Při otevření modálu **focus skočí na první input** (nebo na primární tlačítko, pokud není input).
- **Tab trap:** Tab uvnitř modálu cykluje jen mezi prvky uvnitř, nedostane se ven (na pozadí stránky).
- Po zavření modálu **focus se vrátí na trigger** (tlačítko, které modál otevřelo).
- `Escape` zavírá modál.
- Klik na backdrop zavírá modál.

V Reactu používám `@headlessui/react` Dialog nebo `radix-ui` Dialog — řeší to za mě. Nikdy nepiš focus management ručně, je to plné edge cases.

### Pravidla modálů

- Max šířka `max-w-md` pro formuláře, `max-w-lg` pro složitější obsah, `max-w-2xl` pro přehledy.
- Nikdy `max-w-full` — modál musí mít vizuální odtah od pozadí.
- `backdrop-blur-sm` — jemné rozmazání pozadí, ne jen ztmavení.
- Zavírání: klik na backdrop + Escape klávesa + X tlačítko.
- Footer s tlačítky: Cancel vlevo (secondary), akce vpravo (primary). Nikdy obráceně.
- `aria-modal="true"` + `role="dialog"` + `aria-labelledby` ukazující na nadpis modálu.
- Když je modál otevřený, `body` má `overflow-hidden` — pozadí se nesmí scrollovat.

### Drawer (slide-in z boku) vs modal

```
Modal:    primární — formuláře, confirmace, krátké flow
Drawer:   sekundární — detail entity (mobile-friendly), filtry, settings
```

Drawer používám pro:

- Detail záznamu, když chci zůstat v kontextu seznamu (viz Linear, Notion).
- Komplexní filtry s mnoha možnostmi.
- Mobilní menu (sidebar drawer z levé strany).

---

## 15. Confirmation dialogy

Destruktivní akce (smazání, vymazání dat) potřebují potvrzení. Pattern je specifický — liší se od běžného modálu.

```tsx
// Menší než běžný modál: max-w-sm
<div className="bg-white dark:bg-slate-800 rounded-2xl shadow-xl w-full max-w-sm p-6">

  {/* Ikona varování — centrovaná, výrazná */}
  <div className="w-12 h-12 bg-red-100 dark:bg-red-900/30 rounded-full flex items-center 
                  justify-center mx-auto mb-4">
    <AlertTriangleIcon className="w-6 h-6 text-red-600 dark:text-red-400" />
  </div>

  {/* Text — centrovaný */}
  <h3 className="text-base font-semibold text-gray-900 dark:text-slate-100 text-center mb-2">
    Smazat transakci?
  </h3>
  <p className="text-sm text-gray-500 dark:text-slate-400 text-center mb-6">
    Tato akce je nevratná. Transakce bude trvale odstraněna.
  </p>

  {/* Tlačítka — vedle sebe, Cancel vlevo, destruktivní vpravo */}
  <div className="flex gap-3">
    <Button variant="secondary" className="flex-1" onClick={onClose}>Zrušit</Button>
    <Button variant="destructive" className="flex-1" onClick={onConfirm}>Smazat</Button>
  </div>

</div>
```

### Pravidla confirmation dialogů

- Vždy `max-w-sm` — menší než formulářový modál. Obsah je jednoduchý, nepotřebuje prostor.
- Text je centrovaný — vytváří vizuální klid a soustředění.
- Ikona varování v barevném kruhu nahoře — ne v textu, ne v nadpisu.
- Destruktivní tlačítko je vpravo, `flex-1` — obě tlačítka stejně velká.
- Nikdy destruktivní akci jako defaultní (Enter by neměl spustit smazání).
- Focus automaticky na **Cancel**, ne na Destructive — uživatel musí vědomě přesunout fokus.

### Kdy NEpoužívat confirmation

Confirmation dialog je únavný. Místo něj zvaž **undo pattern**:

```
Smazání jednoho řádku       →  smaž okamžitě + toast s "Vrátit zpět" (5s)
Smazání s následky          →  confirmation (zruším účet, vymažu všechna data)
Reverzibilní akce           →  bez confirmation
Nevratná akce s následky    →  confirmation + ideálně requirement napsat něco ("Smazat" do inputu)
```

### Typovaný confirmation (pro vážné akce)

Pro skutečně nebezpečné akce (smazání projektu, účtu) vyžadovat napsání slova nebo názvu:

```tsx
<p>Pro potvrzení napiš <code className="font-mono bg-gray-100 px-1 rounded">smazat účet</code></p>
<input type="text" value={confirmText} onChange={...} />
<Button 
  variant="destructive"
  disabled={confirmText !== 'smazat účet'}
  onClick={onConfirm}
>
  Smazat účet
</Button>
```

Brání náhodnému kliknutí nebo „enter spam" submitu.

---

## 16. Dropdown menu

```tsx
// Kontejner (relativně pozicovaný trigger):
className="relative"

// Menu:
className="absolute right-0 top-full mt-1 w-48 bg-white dark:bg-slate-800 
           border border-gray-200 dark:border-slate-700 rounded-xl shadow-lg 
           z-20 py-1 overflow-hidden
           animate-fade-in"

// Položka menu:
className="flex items-center gap-2.5 w-full px-3 py-2 text-sm text-gray-700 
           dark:text-slate-300 hover:bg-gray-50 dark:hover:bg-slate-700 
           transition-colors duration-100"

// Destruktivní položka:
className="flex items-center gap-2.5 w-full px-3 py-2 text-sm text-red-600 
           dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 
           transition-colors duration-100"

// Oddělovač:
className="my-1 border-t border-gray-100 dark:border-slate-700"

// Nadpis sekce (pokud potřebuji oddělit skupiny):
className="px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-gray-400"
```

### Klávesnicová navigace v dropdownu

- `Šipky nahoru/dolů` — pohyb mezi položkami.
- `Enter` — vybrat položku.
- `Escape` — zavřít.
- `Tab` — zavřít a přejít na další element na stránce.
- První písmeno názvu — skočit na položku začínající tím písmenem (jako v nativním selectu).

Implementuji přes `@headlessui/react` Menu nebo `radix-ui` DropdownMenu.

### Pravidla dropdownů

- Dropdown se vždy zavře kliknutím mimo (`onBlur` nebo click outside listener).
- Destruktivní akce vždy dole, oddělená oddělovačem.
- Max 7 položek — víc = nesprávný pattern, použij modal nebo stránku.
- `z-20` pro dropdown, nikdy víc — jinak přebíjí modály.
- Pozice: default nad/pod triggerem, podle prostoru. Při overflow obrazovky se přepne na opačnou stranu.

---

## 17. Taby (záložky)

Taby dělím na dva typy. Záleží na tom, co oddělují.

### Typ 1 — Navigační taby (přepínají pohled)

```tsx
<div className="flex border-b border-gray-200 dark:border-slate-700">
  {tabs.map(tab => (
    <button
      key={tab.id}
      onClick={() => setActive(tab.id)}
      className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors duration-150 ${
        active === tab.id
          ? 'border-indigo-600 text-indigo-600 dark:text-indigo-400 dark:border-indigo-400'
          : 'border-transparent text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-300'
      }`}
    >
      {tab.label}
    </button>
  ))}
</div>
```

### Typ 2 — Pill taby (přepínají filtr nebo zobrazení)

```tsx
<div className="flex gap-1 p-1 bg-gray-100 dark:bg-slate-800 rounded-lg w-fit">
  {options.map(opt => (
    <button
      key={opt.value}
      onClick={() => setSelected(opt.value)}
      className={`px-3 py-1.5 text-sm font-medium rounded-md transition-all duration-150 ${
        selected === opt.value
          ? 'bg-white dark:bg-slate-700 text-gray-900 dark:text-slate-100 shadow-sm'
          : 'text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-300'
      }`}
    >
      {opt.label}
    </button>
  ))}
</div>
```

Navigační taby = border bottom indikátor. Pill taby = pohyblivý bílý „šuplík" uvnitř šedého kontejneru. Nemíchat styly.

### Taby s počty

```tsx
<button className="...">
  Aktivní
  <span className="ml-2 px-1.5 py-0.5 text-xs font-medium bg-gray-100 text-gray-600 rounded-full">
    23
  </span>
</button>
```

Počet je vždy v decentním šedém badge, ne výrazně barevný.

### Pravidla tabů

- Aktivní tab musí být jednoznačně poznat — kombinace barvy textu + indikátoru.
- Klávesnice: šipky doleva/doprava mezi taby (pattern z ARIA Authoring Practices).
- Max 6 tabů na řadě — víc = ScrollableTabs nebo Select.
- Obsah tabu se nikdy nepřesouvá — všechny taby mají stejnou výšku, nebo se layout drží na min-height.

---

## 18. Tooltips

Tooltip používám pro **vysvětlení**, ne pro důležité informace. Klávesnice ho neuvidí — kritická info musí být i v UI.

### Nativní vs custom

```
title="..."             →  rychlá info, jen pro hover, nelze stylovat
Custom tooltip          →  delší obsah, formátování, klávesnicový access
```

Pro icon-only tlačítka stačí `title` + `aria-label`. Pro vysvětlení popisu hodnoty (ikona „i" vedle nadpisu) custom tooltip.

### Custom tooltip styling

```tsx
<div role="tooltip" className="absolute z-30 px-2.5 py-1.5 text-xs font-medium text-white 
                                bg-gray-900 dark:bg-slate-700 rounded-md shadow-lg 
                                pointer-events-none animate-fade-in
                                max-w-xs">
  {content}
  <div className="absolute -top-1 left-1/2 -translate-x-1/2 w-2 h-2 bg-gray-900 rotate-45" />
</div>
```

### Pravidla tooltipů

- Delay: 200–500ms před zobrazením. Okamžitý tooltip otravuje.
- Mizí: ihned při mouseleave.
- Pozice: default nad triggerem (`top`), fallback bottom při overflow.
- Max šířka: `max-w-xs` (20rem). Delší text patří do detailu, ne do tooltipu.
- Nikdy interaktivní obsah uvnitř tooltipu (tlačítka, odkazy). Pro to je popover.
- `pointer-events-none` — kurzor projde skrz, tooltip nepřebírá hover.

### Popover (interaktivní tooltip)

Když potřebuji v tooltipu odkaz nebo tlačítko, je to popover:

```tsx
<div role="dialog" className="absolute z-30 w-64 p-4 bg-white dark:bg-slate-800 
                              border border-gray-200 dark:border-slate-700 
                              rounded-xl shadow-lg animate-fade-in">
  <h4 className="text-sm font-semibold mb-1">Detail kategorie</h4>
  <p className="text-xs text-gray-500 mb-3">{description}</p>
  <a href={...} className="text-xs text-indigo-600 hover:text-indigo-700">
    Upravit kategorii →
  </a>
</div>
```

- Popover má `pointer-events-auto` (default), narozdíl od tooltipu.
- Otevírá se kliknutím nebo focusem, ne hoverem.
- Zavírá se kliknutím mimo nebo `Escape`.

---

## 19. Avatary a fallbacky

### Avatar s obrázkem

```tsx
<img
  src={user.avatarUrl}
  alt={user.name}
  className="w-10 h-10 rounded-full object-cover bg-gray-100"
  loading="lazy"
/>
```

### Avatar fallback (iniciály)

Pokud uživatel nemá avatar, generuji iniciály na barevném pozadí:

```tsx
function avatarColor(name: string): string {
  // Stabilní barva z hashu jména
  const hash = name.split('').reduce((a, c) => a + c.charCodeAt(0), 0);
  const colors = [
    'bg-indigo-500', 'bg-emerald-500', 'bg-amber-500', 
    'bg-pink-500', 'bg-cyan-500', 'bg-violet-500'
  ];
  return colors[hash % colors.length];
}

function initials(name: string): string {
  return name.split(' ').slice(0, 2).map(w => w[0]).join('').toUpperCase();
}

<div className={`w-10 h-10 rounded-full flex items-center justify-center 
                 text-white text-sm font-semibold ${avatarColor(user.name)}`}>
  {initials(user.name)}
</div>
```

Pravidla:

- Barva avataru je **stabilní** podle jména — Pavel má vždy stejnou barvu napříč aplikací.
- Max 2 iniciály — víc se nevejde čitelně.
- Pozadí je vždy z palety, nikdy čistá `#000` nebo `#fff`.

### Velikosti avataru

```
w-6 h-6   (24px)  — v komentech, inline mentions
w-8 h-8   (32px)  — v listech, table cell
w-10 h-10 (40px)  — v hlavičce karty, profil
w-12 h-12 (48px)  — v hlavičce stránky
w-16 h-16 (64px)  — v detail view profilu
w-24 h-24 (96px)  — v settings, edit profile
```

### Avatar group (stack)

```tsx
<div className="flex -space-x-2">
  {users.slice(0, 3).map(user => (
    <Avatar key={user.id} user={user} className="ring-2 ring-white dark:ring-slate-800" />
  ))}
  {users.length > 3 && (
    <div className="w-8 h-8 rounded-full bg-gray-100 dark:bg-slate-700 
                    text-xs font-semibold text-gray-600 dark:text-slate-300
                    flex items-center justify-center ring-2 ring-white dark:ring-slate-800">
      +{users.length - 3}
    </div>
  )}
</div>
```

- `-space-x-2` (záporný margin) způsobí překryv.
- `ring-2 ring-white` vytvoří „výřez" mezi avatary.

### Placeholder obrázky

Pro produktové / category obrázky:

- Při loadu: `bg-gray-100` s pulsing animací (`animate-pulse`).
- Při chybě: `bg-gray-100` s ikonou (`ImageOffIcon` ve středu, `text-gray-400`).
- Nikdy broken-image ikona prohlížeče — vždy explicit fallback.

```tsx
const [error, setError] = useState(false);
return error ? (
  <div className="w-full h-full bg-gray-100 dark:bg-slate-700 flex items-center justify-center">
    <ImageOffIcon className="w-6 h-6 text-gray-400" />
  </div>
) : (
  <img src={src} onError={() => setError(true)} className="..." />
);
```

---

## 20. Grafy (Recharts)

### Společné vlastnosti všech grafů

```tsx
<ResponsiveContainer width="100%" height={280}>
  // Barvy os a popisků:
  // tick: fill="#6b7280" (gray-500), fontSize=12
  // grid: stroke="#e5e7eb" (gray-200), strokeDasharray="3 3"
  // tooltip: custom styled (viz níže)
```

### Custom Tooltip

```tsx
const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700 
                    rounded-lg shadow-lg px-3 py-2 text-sm">
      <p className="font-medium text-gray-900 dark:text-slate-100 mb-1">{label}</p>
      {payload.map((entry) => (
        <p key={entry.name} style={{ color: entry.color }} className="text-sm">
          {entry.name}: {formatCurrency(entry.value)}
        </p>
      ))}
    </div>
  );
};
```

### Pravidla grafů

- Recharts `CartesianGrid` vždy s `strokeDasharray="3 3"` a `stroke="#e5e7eb"` — jemná mřížka.
- Osy: `tick={{ fill: '#6b7280', fontSize: 12 }}`, `axisLine={false}`, `tickLine={false}`.
- Legenda: pod grafem, ne nad ním. `verticalAlign="bottom"`, `height={36}`.
- Barvy sloupců/čar: emerald pro příjmy, red pro výdaje, indigo pro neutrální data.
- Nikdy 3D grafy. Nikdy příliš mnoho datových řad na jednom grafu (max 3).
- Graf musí mít `min-height` i bez dat — zobrazí prázdný stav, ne prázdný div.

### Typy grafů — co pro co

```
Line chart    →  průběh v čase, srovnání trendů (max 3 řady)
Bar chart     →  diskrétní hodnoty po kategoriích (měsíce, kategorie)
Stacked bar   →  složení celku v čase (struktura výdajů po měsících)
Area chart    →  průběh v čase, kde záleží na "objemu" (kumulativní)
Pie/Donut     →  rozložení celku, max 5 částí, jinak je nečitelný
Sparkline     →  inline trend, bez os, vedle hodnoty v tabulce
```

Pie chart používám neochotně — sloupcový graf je skoro vždy čitelnější. Donut chart s číslem ve středu funguje pro **jeden** úhel pohledu (např. „65 % rozpočtu vyčerpáno").

### Prázdný stav grafu

```tsx
<div className="flex flex-col items-center justify-center h-[280px] bg-gray-50 dark:bg-slate-900/50 rounded-lg">
  <BarChartIcon className="w-12 h-12 text-gray-300 dark:text-slate-600 mb-3" />
  <p className="text-sm text-gray-500 dark:text-slate-400">Zatím žádná data</p>
  <p className="text-xs text-gray-400 dark:text-slate-500 mt-1">Přidej první transakce</p>
</div>
```

---

## 21. Progress bary

```tsx
<div className="space-y-1.5">
  <div className="flex justify-between text-sm">
    <span className="font-medium text-gray-700 dark:text-slate-300">{category.name}</span>
    <span className="text-gray-500 dark:text-slate-400 tabular-nums">{spent} / {limit}</span>
  </div>
  <div className="h-2 bg-gray-100 dark:bg-slate-700 rounded-full overflow-hidden">
    <div
      className={`h-full rounded-full transition-all duration-500 ${
        pct >= 100 ? 'bg-red-500' :
        pct >= 80  ? 'bg-amber-500' :
                    'bg-emerald-500'
      }`}
      style={{ width: `${Math.min(pct, 100)}%` }}
    />
  </div>
</div>
```

Výška progress baru: `h-2` (8px) — tenký, elegantní. `h-3` pokud je potřeba více viditelnosti. Nikdy tlustší.

### Circular progress (kruhový)

Pro „% z celku" v stat kartě:

```tsx
<svg className="w-16 h-16 -rotate-90" viewBox="0 0 36 36">
  <circle cx="18" cy="18" r="16" fill="none" stroke="#e5e7eb" strokeWidth="3" />
  <circle
    cx="18" cy="18" r="16" fill="none"
    stroke="currentColor"
    strokeWidth="3"
    strokeDasharray={`${pct} 100`}
    strokeLinecap="round"
    className="text-indigo-500 transition-all duration-500"
  />
</svg>
<div className="absolute inset-0 flex items-center justify-center text-sm font-semibold">
  {pct}%
</div>
```

### Indeterminate progress (neznámá doba)

Pro „něco se děje, ale nevím přesně jak dlouho":

```tsx
<div className="h-1 bg-gray-100 overflow-hidden rounded-full">
  <div className="h-full bg-indigo-500 rounded-full animate-progress-indeterminate" />
</div>

// CSS:
@keyframes progress-indeterminate {
  0%   { transform: translateX(-100%); width: 30%; }
  50%  { transform: translateX(50%);   width: 60%; }
  100% { transform: translateX(200%);  width: 30%; }
}
```

Používá se v hlavičce stránky při route change, při uploadu apod.

---

## 22. Ikony

Knihovna: **Lucide React**. Konzistentní, tenké linie, dobře čitelné v malých velikostech.

### Velikosti

```
w-3.5 h-3.5  — v textu, vedle malého textu (chybová zpráva, caption)
w-4 h-4      — v tlačítkách, v tabulkách, v badge
w-5 h-5      — v navigaci, v kartách
w-6 h-6      — standalone ikony, velké akce
w-8 h-8      — ikony v stat kartách (v barevném kontejneru)
w-12 h-12    — empty state ikony
```

### Pravidla

- Ikony v tlačítkách: vždy `w-4 h-4`, vždy vlevo od textu.
- Ikony bez textu: musí mít `aria-label` nebo `title`.
- Barevné ikony jen tehdy, když barva nese informaci (zelená šipka nahoru = růst, červená dolů = pokles).
- Nikdy ikony jako čistě dekorativní prvky vedle každého textu — jen tam, kde pomáhají s rychlou orientací.
- `stroke-width` jednotná: Lucide má default 2, držet to. Měnit jen pro velmi malé (3.5px) nebo velmi velké (48px+) instance.

### Konzistence ikonografie

Pro každý koncept používám **jednu** ikonu napříč aplikací:

```
Smazat:           TrashIcon       (ne XIcon, ne MinusIcon)
Editovat:         PencilIcon      (ne EditIcon — neexistuje v Lucide)
Přidat:           PlusIcon
Zavřít:           XIcon
Více možností:    MoreHorizontalIcon (tři tečky)
Vyhledat:         SearchIcon
Filtrovat:        FilterIcon
Stáhnout:         DownloadIcon
Sdílet:           ShareIcon (ne Share2Icon — používat jen jednu z variant)
```

---

## 23. Stavy obecně — loading, error, optimistic UI

UI má vždy víc stavů než jen „happy path". Promyslet všechny.

### Loading states

```
Initial load (žádná data):   Skeleton, který napodobuje tvar obsahu
Refresh (existující data):   Existing data + jemný spinner v rohu nebo top bar
Partial loading:             Skeleton jen na novém obsahu, existující se nemění
Action loading (klik):       Spinner uvnitř tlačítka, tlačítko disabled
Background sync:             Tichý indikátor („Synchronizuji…") nebo žádný
```

Pravidlo: pokud načítání trvá **< 300ms**, nezobrazuj nic. Krátký skeleton/spinner blikne a vypadá to rozbitě. Pokud trvá **> 1 sekundu**, zobraz progress (skeleton/spinner). Mezi tím (300ms–1s) zobraz subtle indikátor.

### Error states

```
Field error:        červený text pod inputem
Form error:         alert nad formulářem ("Nepodařilo se uložit")
Section error:      v rámci karty, s tlačítkem "Zkusit znovu"
Page error:         celá stránka s ilustrací + co dělat
Network error:      toast s "Zkontroluj připojení" + retry tlačítko
```

```tsx
// Section error
<div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-900/30 
                rounded-xl p-6 flex items-start gap-3">
  <AlertCircleIcon className="w-5 h-5 text-red-600 dark:text-red-400 mt-0.5 flex-shrink-0" />
  <div className="flex-1">
    <h3 className="text-sm font-semibold text-red-900 dark:text-red-200 mb-1">
      Nepodařilo se načíst transakce
    </h3>
    <p className="text-sm text-red-700 dark:text-red-300 mb-3">
      Zkontroluj internetové připojení nebo to zkus znovu.
    </p>
    <button onClick={retry} className="text-sm font-medium text-red-700 hover:text-red-800 underline">
      Zkusit znovu
    </button>
  </div>
</div>
```

### Optimistic UI

Pro akce, které **téměř jistě uspějí**, neukazuj loading state — aplikuj změnu okamžitě.

```tsx
async function deleteTransaction(id: string) {
  // 1. Optimistic update — řádek zmizí ihned
  const previous = transactions;
  setTransactions(transactions.filter(t => t.id !== id));
  
  // 2. Toast s undo
  showToast('Transakce smazána', { 
    action: { label: 'Vrátit zpět', onClick: () => setTransactions(previous) },
    duration: 5000
  });
  
  try {
    // 3. Skutečné volání API na pozadí
    await api.delete(id);
  } catch (err) {
    // 4. Rollback při chybě
    setTransactions(previous);
    showToast('Smazání selhalo', { variant: 'error' });
  }
}
```

Pravidla optimistic UI:

- Použij pro **reverzibilní** akce s vysokou pravděpodobností úspěchu (delete, update).
- **Nepoužívej** pro nereverzibilní akce (platba, send email) — tam confirmation + skutečný loading.
- Vždy rollback při chybě.
- Vždy informuj uživatele o úspěchu (toast) — jinak neví, jestli to skutečně proběhlo.

### Undo pattern

Místo „Opravdu chcete?" raději umožni vrácení:

```tsx
// Toast po smazání:
"Transakce smazána. [Vrátit zpět]"   (5 sekund)
```

5 sekund je standard. Méně = uživatel nestihne. Více = ztrácí relevanci.

Po vypršení undo času je akce trvalá — server pak skutečně smaže (do té doby může být jen `deleted_at` flag v DB).

---

## 24. Skeleton loading stavy

Skeleton nahrazuje spinner všude tam, kde vím tvar obsahu předem. Spinner říká „čekej". Skeleton říká „tady bude tohle".

```tsx
// Základ skeleton bloku:
className="bg-gray-200 dark:bg-slate-700 rounded animate-pulse"

// Skeleton stat karta:
<div className="bg-white dark:bg-slate-800 rounded-xl border border-gray-200 dark:border-slate-700 shadow-sm p-6">
  <div className="flex items-center justify-between mb-4">
    <div className="h-4 w-24 bg-gray-200 dark:bg-slate-700 rounded animate-pulse" />
    <div className="w-10 h-10 bg-gray-200 dark:bg-slate-700 rounded-lg animate-pulse" />
  </div>
  <div className="h-8 w-32 bg-gray-200 dark:bg-slate-700 rounded animate-pulse mb-2" />
  <div className="h-3 w-20 bg-gray-200 dark:bg-slate-700 rounded animate-pulse" />
</div>

// Skeleton tabulkový řádek:
<tr>
  <td className="px-4 py-3"><div className="h-4 w-32 bg-gray-200 dark:bg-slate-700 rounded animate-pulse" /></td>
  <td className="px-4 py-3"><div className="h-4 w-16 bg-gray-200 dark:bg-slate-700 rounded animate-pulse" /></td>
  <td className="px-4 py-3"><div className="h-5 w-20 bg-gray-200 dark:bg-slate-700 rounded-full animate-pulse" /></td>
</tr>
```

### Pravidla skeletonů

- Skeleton bloky mají přibližně tvar skutečného obsahu — krátký text = úzký blok, nadpis = širší blok.
- Vždy `animate-pulse` (Tailwind built-in) — žádné vlastní animace.
- Nikdy spinner + skeleton zároveň.
- Pro jednoduché stavy (jedno číslo, jeden status) stačí spinner `w-5 h-5` na místě hodnoty.
- Po načtení dat se skeleton plynule nahradí obsahem — žádný flash. Pokud je to možné, fade out / fade in.

---

## 25. Prázdné stavy

Každá stránka nebo sekce musí mít prázdný stav. Nikdy prázdný div nebo prázdná tabulka bez zprávy.

```tsx
<div className="flex flex-col items-center justify-center py-16 text-center">
  <div className="w-16 h-16 bg-gray-100 dark:bg-slate-700 rounded-2xl flex items-center 
                  justify-center mb-4">
    <ReceiptIcon className="w-8 h-8 text-gray-400 dark:text-slate-500" />
  </div>
  <h3 className="text-base font-semibold text-gray-900 dark:text-slate-100 mb-1">
    Žádné transakce
  </h3>
  <p className="text-sm text-gray-500 dark:text-slate-400 mb-6 max-w-xs">
    Zatím jsi nezaznamenal žádnou transakci. Přidej první a začni sledovat své finance.
  </p>
  <Button variant="primary" onClick={onAdd}>
    <PlusIcon className="w-4 h-4" />
    Přidat první transakci
  </Button>
</div>
```

### Tři typy prázdných stavů

**1. First-use empty state** — uživatel ještě nemá data:

- Pozitivní tón, motivace začít.
- Akční tlačítko = primární CTA.
- Volitelně ilustrace nebo větší vizuál.

**2. Filtered empty state** — uživatel nastavil filtry a nic nematchuje:

- „Žádné transakce neodpovídají filtrům."
- Tlačítko „Resetovat filtry" — vede pryč z prázdna.
- Méně ilustrativní, víc utilitární.

**3. Error empty state** — data se nepodařilo načíst:

- Červená/varovná barva.
- „Něco se pokazilo" + tlačítko „Zkusit znovu".
- Ne zaměňovat s 1) — nejsou to „žádná data", je to chyba.

### Pravidla prázdných stavů

- Ikona v šedém čtvercovém kontejneru (`rounded-2xl`), ne samotná.
- Krátký nadpis: co není přítomno.
- Popis: proč to může být prázdné a co má uživatel udělat.
- Akční tlačítko: vždy, pokud je relevantní.
- Max šířka textu: `max-w-xs` — úzký blok textu vypadá záměrně, ne jako broken layout.

---

## 26. Notifikační hierarchie

Toast je jen jedna ze čtyř úrovní notifikací. Každá má jiný kontext a chování.

### Hierarchie (zezdola nahoru intenzitou)

**1. Badge dot** — tichá indikace

- Červená tečka na ikoně (zvonek, avatar).
- Žádný text, žádné rušení.
- Použití: nepřečtená zpráva, neviděná notifikace v centru.

```tsx
<button className="relative">
  <BellIcon className="w-5 h-5" />
  {hasUnread && (
    <span className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-red-500 rounded-full ring-2 ring-white" />
  )}
</button>
```

**2. Inline alert** — kontextová informace

- V rámci obsahu, kde je relevantní.
- Trvalá (uživatel ji odbaví zavřením nebo akcí).
- Použití: „Tento účet ještě nebyl ověřen — [Ověřit teď]" nad formulářem; „Tvůj plán vyprší za 7 dní" na hlavní stránce.

```tsx
<div className="bg-amber-50 dark:bg-amber-900/20 border-l-4 border-amber-500 px-4 py-3 rounded-r-md flex items-start gap-3">
  <AlertTriangleIcon className="w-5 h-5 text-amber-600 dark:text-amber-400 mt-0.5 flex-shrink-0" />
  <div className="flex-1 text-sm">
    <p className="font-medium text-amber-900 dark:text-amber-200">Účet není ověřen</p>
    <p className="text-amber-700 dark:text-amber-300 mt-0.5">
      Ověření je nutné pro plnou funkčnost. <a href="#" className="underline font-medium">Ověřit teď</a>
    </p>
  </div>
  <button className="text-amber-600 hover:text-amber-700" aria-label="Zavřít">
    <XIcon className="w-4 h-4" />
  </button>
</div>
```

Varianty: info (blue), success (emerald), warning (amber), error (red).

**3. Toast (snackbar)** — krátká zpětná vazba

- Vpravo dole (desktop) nebo nahoře (mobil).
- Automatické mizení (4–6s).
- Použití: potvrzení akce („Transakce uložena"), tichá chyba.

(Viz kap. 27 — Toast notifikace.)

**4. Banner** — systémová / globální informace

- Přes celou šíři, nahoře nad celým obsahem.
- Persistentní, zavírací.
- Použití: „Plánovaná údržba zítra od 02:00", „Nová verze aplikace — [Obnovit]".

```tsx
<div className="bg-indigo-600 text-white px-4 py-2 flex items-center justify-center gap-3 text-sm">
  <InfoIcon className="w-4 h-4" />
  <span>Plánovaná údržba zítra od 02:00 do 04:00.</span>
  <button className="ml-4 text-white/80 hover:text-white" aria-label="Zavřít">
    <XIcon className="w-4 h-4" />
  </button>
</div>
```

### Pravidla notifikací

- **Nikdy** modal pro notifikaci, která nepotřebuje rozhodnutí.
- **Nikdy** toast pro kritickou chybu, na kterou musí uživatel zareagovat — to je inline alert nebo modal.
- **Nikdy** banner pro feature announcement, který lze přečíst později — to je inline na dashboardu.
- Hierarchii respektuj: pokud uživatel zavře banner, neukaž stejnou věc znovu jako toast.

---

## 27. Toast notifikace

Toast je odpověď na akci, která proběhla na pozadí nebo mimo aktuální fokus. Modál by uživatele zastavil — toast ho jen informuje.

### Pozice a styling

```tsx
// Pozice: fixed, vpravo dole (nebo nahoře na mobilu)
className="fixed bottom-4 right-4 z-[60] flex flex-col gap-2 max-w-sm w-full pointer-events-none"

// Jedna toast zpráva:
className="flex items-start gap-3 bg-white dark:bg-slate-800 border border-gray-200 
           dark:border-slate-700 rounded-xl shadow-lg px-4 py-3 pointer-events-auto
           animate-slide-in-right"
```

### Varianty

```tsx
// Úspěch:
<div className="w-5 h-5 bg-emerald-100 dark:bg-emerald-900/30 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5">
  <CheckIcon className="w-3 h-3 text-emerald-600 dark:text-emerald-400" />
</div>
<div>
  <p className="text-sm font-medium text-gray-900 dark:text-slate-100">Transakce uložena</p>
  <p className="text-xs text-gray-500 dark:text-slate-400 mt-0.5">Částka 1 200 Kč přidána.</p>
</div>

// Chyba: ikona červená, text stejný
// Varování: ikona amber
// Info: ikona indigo
```

### Toast s akcí (undo)

```tsx
<div className="flex items-center gap-3 ...">
  <CheckIcon className="w-5 h-5 text-emerald-500" />
  <div className="flex-1">
    <p className="text-sm font-medium">Transakce smazána</p>
  </div>
  <button
    onClick={onUndo}
    className="text-sm font-medium text-indigo-600 hover:text-indigo-700"
  >
    Vrátit zpět
  </button>
</div>
```

### Pravidla toastů

- Automaticky mizí po **4 sekundách**. Chybové toasty po **6 sekundách** — uživatel potřebuje čas přečíst.
- Toasty s akcí (undo) **5 sekund**.
- Toasty s akcí se nezavřou při hoveru — uživatel chce kliknout.
- Vždy s tlačítkem × pro ruční zavření.
- Max 3 toasty najednou — starší se odstraní.
- Nikdy v toastu neptat — to je práce modálu.
- Animace vstupu: slide in zprava. Odchod: fade out + slide out.
- `role="status"` nebo `role="alert"` (pro chyby) — screen reader oznámí.

```css
@keyframes slide-in-right {
  from { opacity: 0; transform: translateX(100%); }
  to   { opacity: 1; transform: translateX(0); }
}
```

---

## 28. Progressive disclosure

Neukazuj všechno najednou. Co je sekundární, odhal na vyžádání.

### Tři vrstvy informace

```
Primární:    vždy viditelné, neskryté
Sekundární:  za jedním klikem (expand, hover, drawer)
Terciární:   za dvěma kliky (detail page, modal)
```

### Patterny

**Expand / collapse (accordion):**

```tsx
<button
  onClick={() => setOpen(!open)}
  aria-expanded={open}
  className="flex items-center justify-between w-full py-3 text-left"
>
  <span className="text-sm font-medium">Pokročilá nastavení</span>
  <ChevronDownIcon className={`w-4 h-4 transition-transform duration-150 ${open ? 'rotate-180' : ''}`} />
</button>
{open && (
  <div className="pb-3 space-y-3">
    {/* obsah */}
  </div>
)}
```

**„Show more" pattern:**

```tsx
{description.length > 200 ? (
  <>
    <p>{expanded ? description : description.slice(0, 200) + '…'}</p>
    <button onClick={() => setExpanded(!expanded)} className="text-sm text-indigo-600 mt-1">
      {expanded ? 'Skrýt' : 'Zobrazit více'}
    </button>
  </>
) : (
  <p>{description}</p>
)}
```

**Hover-to-reveal akce:**

```tsx
// V tabulce: row actions se zobrazí jen při hoveru řádku
<tr className="group">
  <td>...</td>
  <td className="text-right">
    <div className="opacity-0 group-hover:opacity-100 transition-opacity">
      <button>Upravit</button>
      <button>Smazat</button>
    </div>
  </td>
</tr>
```

Pozor: hover-to-reveal nefunguje na mobilu (žádný hover). Tam vždy zobrazit nebo dát do dropdownu.

### Co skrývat, co ne

```
Skrýt:        pokročilá nastavení, edge case akce, historický kontext
Neskryt:      primární akce, povinná pole, aktuální status
Zvážit:       sekundární metadata (timestamps), bulk akce
```

Pravidlo: kdyby uživatel pět minut nepoužíval aplikaci a vrátil se, co potřebuje vidět hned? To je primární. Zbytek skrývej.

---

## 29. Anatomie stránky

Každá stránka má konzistentní vertikální strukturu. Uživatel ví, kde co hledat, protože struktura se neopakuje náhodně.

```tsx
<div className="p-6 lg:p-8 space-y-8">

  {/* 1. Page header — vždy nahoře */}
  <div className="flex items-center justify-between">
    <div>
      <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">Transakce</h1>
      <p className="text-sm text-gray-500 dark:text-slate-400 mt-1">
        Celkem 47 záznamů
      </p>
    </div>
    <Button variant="primary">
      <PlusIcon className="w-4 h-4" />
      Přidat transakci
    </Button>
  </div>

  {/* 2. Filter / search bar — pokud je potřeba */}
  <FilterBar ... />

  {/* 3. Hlavní obsah */}
  <div className="space-y-4">
    {/* karty nebo tabulka */}
  </div>

</div>
```

### Page header pravidla

- Nadpis vlevo, primární CTA vpravo — vždy tento pořadí.
- Podnadpis (počet záznamů, aktuální měsíc apod.): `text-sm text-gray-500 mt-1`.
- Na mobilech: nadpis a CTA pod sebou (`flex-col sm:flex-row`).
- Nikdy více než jedno primární CTA v page headeru.

### Page header s tabs

Pokud má stránka taby, jsou pod hlavičkou:

```tsx
<div className="border-b border-gray-200 dark:border-slate-700">
  <div className="px-6 lg:px-8 pt-6 lg:pt-8">
    {/* Page header */}
    <Tabs />
  </div>
</div>
<div className="px-6 lg:px-8 py-8">
  {/* Obsah aktivního tabu */}
</div>
```

### Sticky header

V dlouhých stránkách (long forms, dlouhé tabulky) page header sticky:

```tsx
<header className="sticky top-0 z-10 bg-white dark:bg-slate-900 border-b border-gray-200 
                   dark:border-slate-700 px-6 py-4">
  ...
</header>
```

Pravidlo: sticky jen pokud má smysl (primární CTA vždy dostupné). Jinak je to vizuální dluh.

---

## 30. Filter bar

Filter bar sedí mezi page headerem a obsahem. Obsahuje vyhledávání a filtry.

```tsx
<div className="flex flex-col sm:flex-row gap-3">

  {/* Vyhledávání — vždy první, nejširší */}
  <div className="relative flex-1">
    <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
    <input
      className="w-full pl-9 pr-3 py-2 text-sm bg-white dark:bg-slate-800 border 
                 border-gray-300 dark:border-slate-600 rounded-md ..."
      placeholder="Hledat..."
    />
  </div>

  {/* Selekty — vždy za vyhledáváním, fixní šířka */}
  <select className="w-full sm:w-40 px-3 py-2 text-sm bg-white dark:bg-slate-800 
                     border border-gray-300 dark:border-slate-600 rounded-md ...">
    <option value="">Všechny typy</option>
  </select>

  <select className="w-full sm:w-40 ...">
    <option value="">Všechny kategorie</option>
  </select>

</div>
```

### Aktivní filtry chips

Pod filter barem zobrazím aktivní filtry jako removable chips:

```tsx
{activeFilters.length > 0 && (
  <div className="flex flex-wrap gap-2 mt-3">
    {activeFilters.map(f => (
      <RemovableBadge key={f.id} onRemove={() => removeFilter(f.id)}>
        {f.label}: {f.value}
      </RemovableBadge>
    ))}
    <button onClick={clearAll} className="text-sm text-indigo-600 hover:text-indigo-700">
      Vymazat vše
    </button>
  </div>
)}
```

### Pravidla filter baru

- Vyhledávací input má ikonu lupy vlevo uvnitř (`pl-9`).
- Selekty mají fixní šířku na desktopu (`w-36` nebo `w-40`), full-width na mobilu.
- Pokud jsou aktivní filtry, zobrazím pod filter barem „aktivní filtry" jako odstraňovatelné badges.
- Reset všech filtrů: `text-sm text-indigo-600 hover:text-indigo-700` odkaz, ne tlačítko.
- Filtry se aplikují **okamžitě** při změně, ne přes „Použít" tlačítko (kromě komplexních filter drawer).
- Filtry se ukládají do URL (`?category=food&type=expense`) — uživatel může sdílet odkaz nebo se vrátit.

### Filter drawer (pokročilé filtry)

Pro 5+ filtrů místo overcrowded baru používám drawer:

```tsx
<Button variant="secondary" onClick={() => setOpen(true)}>
  <FilterIcon className="w-4 h-4" />
  Filtry
  {activeCount > 0 && (
    <span className="ml-1 px-1.5 py-0.5 text-xs bg-indigo-100 text-indigo-700 rounded-full">
      {activeCount}
    </span>
  )}
</Button>
```

Po kliknutí slide-in drawer z pravé strany s detailními filtry, „Použít" tlačítkem dole.

---

## 31. Search a command palette

Pro středně velké až velké aplikace přidávám command palette (`Cmd+K` / `Ctrl+K`) — fuzzy search napříč celou aplikací + akce.

### UI struktura

```tsx
{open && (
  <div className="fixed inset-0 z-50 flex items-start justify-center pt-[20vh] px-4 bg-black/40 backdrop-blur-sm">
    <div className="w-full max-w-xl bg-white dark:bg-slate-800 rounded-xl shadow-2xl overflow-hidden">
      
      {/* Input */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-200 dark:border-slate-700">
        <SearchIcon className="w-5 h-5 text-gray-400" />
        <input
          autoFocus
          value={query}
          onChange={...}
          placeholder="Hledej akci, stránku nebo záznam…"
          className="flex-1 bg-transparent outline-none text-sm placeholder-gray-400"
        />
        <kbd className="px-1.5 py-0.5 text-xs font-medium bg-gray-100 dark:bg-slate-700 rounded">ESC</kbd>
      </div>
      
      {/* Výsledky */}
      <ul className="max-h-96 overflow-y-auto py-2">
        {results.map((item, idx) => (
          <li
            key={item.id}
            className={`flex items-center gap-3 px-4 py-2 cursor-pointer ${
              idx === activeIdx ? 'bg-indigo-50 dark:bg-indigo-900/20' : ''
            }`}
            onMouseEnter={() => setActiveIdx(idx)}
            onClick={() => onSelect(item)}
          >
            <item.icon className="w-4 h-4 text-gray-400" />
            <span className="flex-1 text-sm">{item.label}</span>
            {item.shortcut && (
              <kbd className="px-1.5 py-0.5 text-xs bg-gray-100 rounded">{item.shortcut}</kbd>
            )}
          </li>
        ))}
      </ul>
      
      {/* Footer */}
      <div className="flex items-center justify-between px-4 py-2 border-t border-gray-200 dark:border-slate-700 text-xs text-gray-500">
        <div className="flex items-center gap-3">
          <span><kbd>↑</kbd> <kbd>↓</kbd> pohyb</span>
          <span><kbd>↵</kbd> vybrat</span>
          <span><kbd>ESC</kbd> zavřít</span>
        </div>
      </div>
      
    </div>
  </div>
)}
```

### Pravidla command palette

- Otevírání: `Cmd+K` (macOS) / `Ctrl+K` (Win/Linux). Detekce platformy automatická.
- Klávesnice je primární: šipky pohyb, Enter vybrat, Escape zavřít, Tab přepíná sekce.
- Fuzzy search (knihovny: `fuse.js`, `cmdk`).
- Sekce výsledků: nejdřív akce („Přidat transakci"), pak navigace („Přejít na nastavení"), pak data („Transakce: Albert").
- Recent items na prázdný input.
- Empty state: „Žádné výsledky pro 'xyz'".

### Globální vyhledávání v hlavičce

Pokud nemám command palette, mám v hlavičce globální search:

```tsx
<div className="relative w-96 max-w-full">
  <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
  <input
    placeholder="Vyhledat… (Cmd+K)"
    className="w-full pl-9 pr-3 py-2 text-sm bg-gray-100 dark:bg-slate-800 
               border border-transparent rounded-md focus:bg-white dark:focus:bg-slate-900
               focus:border-gray-300 dark:focus:border-slate-600
               focus:outline-none focus:ring-2 focus:ring-indigo-500"
  />
</div>
```

---

## 32. Z-index systém

Chaos v z-indexech vznikne, pokud každý komponent přidá `z-50` bez systému.

```
z-0    — normální tok dokumentu
z-10   — sticky elementy (sticky header, sticky table header)
z-20   — dropdown menu, tooltip, popover
z-30   — floating akční tlačítko (FAB), mobilní bottom bar
z-40   — sidebar overlay na mobilech
z-50   — modální okno (backdrop + kontejner)
z-[60] — toast notifikace (musí být nad modálem)
z-[70] — command palette (musí být nad vším)
z-[100]— debug overlay, error boundary fallback (jen pro dev)
```

Pravidlo: pokud přidávám `z-index`, napíšu proč do komentáře nebo se ujistím, že hodnota sedí do systému výše.

V `tailwind.config.js` můžu nadefinovat sémantická jména:

```js
theme: {
  extend: {
    zIndex: {
      'sticky': '10',
      'dropdown': '20',
      'fab': '30',
      'overlay': '40',
      'modal': '50',
      'toast': '60',
      'palette': '70',
    }
  }
}

// Použití:
className="z-modal"
```

---

## 33. Text overflow a zkracování

### Jednořádkové zkrácení

```tsx
className="truncate"                    // overflow: hidden + text-overflow: ellipsis
className="truncate max-w-[200px]"      // s explicitní šířkou
```

### Víceřádkové zkrácení (line-clamp)

```tsx
className="line-clamp-2"   // 2 řádky, pak …
className="line-clamp-3"   // 3 řádky
```

### Kde zkracovat

- **Nadpisy transakcí v tabulce**: `truncate max-w-[180px]` — raději zkrácení než přetečení.
- **Poznámky / descriptions**: `line-clamp-2` — ukazuji začátek, detail na hover nebo v detailu.
- **URL nebo technické řetězce**: `break-all` — lepší zalomení uprostřed slova než přetečení.
- **Čísla a datum**: nikdy nezkracuji — vždy zobrazím celé, nebo použiju kratší formát.
- **Emaily**: `truncate` se zobrazením celého v `title` atributu.

### Tooltip při zkrácení

Pokud text zkracuji, přidám `title={fullText}` na element — nativní tooltip funguje bez knihovny.

```tsx
<span className="truncate max-w-[180px]" title={transaction.title}>
  {transaction.title}
</span>
```

### Smart zkracování (middle ellipsis)

Pro filename/path lepší zachovat začátek i konec:

```tsx
function middleEllipsis(text: string, max: number): string {
  if (text.length <= max) return text;
  const half = Math.floor((max - 1) / 2);
  return text.slice(0, half) + '…' + text.slice(-half);
}

// "very_long_filename_with_details_v2.pdf" → "very_lon…ils_v2.pdf"
```

---

## 34. Zobrazení čísel a dat

### Čísla a měna

- Vždy tisícové oddělovače: `1 200`, ne `1200`. `45 000 Kč`, ne `45000 Kč`.
- Desetinná místa: pro CZK 0 nebo 2 desetinná místa, vždy konzistentně v rámci jednoho pohledu.
- Kladné hodnoty v tabulce: `+1 200 Kč` zelená. Záporné: `-800 Kč` červená.
- Velká čísla ve stat kartách: `45 000 Kč` nebo `45,0 tis. Kč` pro > 100 000.
- `tabular-nums` na všech sloupcích s čísly — jinak se cifry pohybují.

```tsx
function formatCurrency(amount: number, currency: Currency): string {
  const locales = { CZK: 'cs-CZ', EUR: 'de-DE', USD: 'en-US' };
  return new Intl.NumberFormat(locales[currency], {
    style: 'currency',
    currency,
    maximumFractionDigits: currency === 'CZK' ? 0 : 2,
  }).format(amount);
}
```

### Procenta

```
Hodnota:           65 %  (s mezerou, ne 65%)
Změna pozitivní:   +12,5 %  zelená
Změna negativní:   -8,3 %   červená
Nulová změna:      0 %  šedá, bez znaménka
```

### Data

```
Absolutní datum:  "13. 5. 2026"     — v tabulkách, v detailu záznamu
Krátké datum:     "13. 5."          — pokud je rok zřejmý z kontextu
Relativní čas:    "před 2 hodinami" — pouze pro události < 24 hodin
Měsíc + rok:      "Květen 2026"     — v grafech, v nadpisech sekcí
Den v týdnu:      "Pondělí 13. 5."  — pro plánovací kontexty
```

Pravidlo: relativní datum (`před X dny`) používám jen pokud je čerstvost informace relevantní. V přehledu transakcí chci vědět přesné datum, ne „před 5 dny" — to je méně užitečné.

```tsx
function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('cs-CZ', {
    day: 'numeric', month: 'numeric', year: 'numeric'
  }); // → "13. 5. 2026"
}

function formatRelative(date: Date): string {
  const rtf = new Intl.RelativeTimeFormat('cs-CZ', { numeric: 'auto' });
  const diff = (date.getTime() - Date.now()) / 1000;
  if (Math.abs(diff) < 60)    return rtf.format(Math.round(diff), 'second');
  if (Math.abs(diff) < 3600)  return rtf.format(Math.round(diff/60), 'minute');
  if (Math.abs(diff) < 86400) return rtf.format(Math.round(diff/3600), 'hour');
  return formatDate(date.toISOString());
}
```

### Časová pásma

Vždy ukládat UTC, zobrazovat v lokálním čase uživatele. Pro globální aplikace v hover/tooltip ukázat časové pásmo:

```tsx
<span title={`${absoluteUtc} UTC`}>{formatLocal(date)}</span>
```

### Jednotky a zkrácení

```
Bajty:       1.2 KB / 5.6 MB / 1.4 GB
Doba:        2h 35min / 45min / 12s
Vzdálenost:  1.2 km / 350 m
Počet:       1.2k / 45.6k / 1.2M  (pro velké hodnoty v UI, ne v reportech)
```

Vždy s mezerou před jednotkou (`5 MB`, ne `5MB`) — česká typografická pravidla.

---

## 35. Edge cases a data variabilita

UI, které funguje na demo datech, často spadne na produkčních. Tohle promyslet **před** spuštěním.

### Test plán pro každou komponentu

Pro každý seznam, tabulku, kartu si projedu:

```
0 položek       →  je tu prázdný stav?
1 položka       →  vypadá to dobře nebo to vypadá jako chyba?
3 položky       →  normální stav
20 položek      →  je tu pagination / scroll?
1 000 položek   →  výkon? virtualizace?
10 000 položek  →  performance?

Krátký název    →  "Test"
Dlouhý název    →  "Velmi dlouhý název transakce na 200 znaků..."
Žádný název     →  je tu fallback?

Číslo:
  0             →  nezobrazím "—"?
  -150          →  červená?
  9999999999    →  přeteče?
  NaN           →  ošetřím? Spadne to?

Datum:
  Včera         →  formát?
  Před rokem    →  jiný formát?
  Budoucnost    →  povoleno?

Avatar:
  S obrázkem    →  loading state?
  Bez obrázku   →  iniciály?
  Broken URL    →  fallback?
```

### Konkrétní zacházení s edge cases

**Velmi dlouhé řetězce:**

```tsx
// Truncate s tooltipem:
<span className="truncate max-w-[180px] block" title={title}>{title}</span>

// Nebo natvrdo limit při ukládání: max 100 znaků na název.
```

**Nulové hodnoty:**

```tsx
// Místo "0 Kč" v cap kartě, kde je hodnota podstatná:
{value === 0 ? <span className="text-gray-400">—</span> : formatCurrency(value)}

// V tabulce: 0 zobraz normálně (skupinová součet by chyběl).
```

**Negativní hodnoty:**

```tsx
// Vždy s prefixem a barvou:
<span className={value >= 0 ? 'text-emerald-600' : 'text-red-600'}>
  {value >= 0 ? '+' : ''}{formatCurrency(value)}
</span>
```

**Velmi velká čísla:**

```tsx
function abbreviate(n: number): string {
  if (Math.abs(n) >= 1e9) return (n / 1e9).toFixed(1) + ' mld.';
  if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(1) + ' mil.';
  if (Math.abs(n) >= 1e3) return (n / 1e3).toFixed(1) + ' tis.';
  return n.toString();
}

// Ve stat kartě nad limit:
{value > 100_000 ? abbreviate(value) + ' Kč' : formatCurrency(value)}
```

**Chybějící data:**

```tsx
// Vždy explicit fallback, nikdy "undefined" v UI:
{user.email || <span className="text-gray-400 italic">není zadáno</span>}
```

### Race conditions

Když uživatel klikne na dvě tlačítka rychle po sobě, nebo se vrátí odpověď v jiném pořadí:

```tsx
// Sledování poslední request:
const requestId = useRef(0);

async function search(query: string) {
  const currentId = ++requestId.current;
  const results = await api.search(query);
  if (currentId === requestId.current) {
    // Jen pokud je tahle response stále aktuální
    setResults(results);
  }
}
```

Alternativně: `AbortController` na fetch.

---

## 36. Dark mode

### Principy

Dark mode není inverzní světlý mode. Je to jiná paleta, ne přehozené barvy.

```
Světlý mode:        Tmavý mode:
bg-gray-50     →    bg-slate-900    (stránka)
bg-white       →    bg-slate-800    (karty)
bg-gray-100    →    bg-slate-700    (hover, oddělovače)
border-gray-200 →   border-slate-700
text-gray-900  →    text-slate-100
text-gray-500  →    text-slate-400
text-gray-400  →    text-slate-500
```

Proč `slate` místo `gray` v dark mode: slate má mírně modrý nádech, který vypadá přirozeněji v tmavém prostředí než čistá šedá.

### Implementace

Dark mode přepínám přidáním třídy `dark` na `<html>` element:

```tsx
useEffect(() => {
  if (theme === 'dark') {
    document.documentElement.classList.add('dark');
  } else {
    document.documentElement.classList.remove('dark');
  }
}, [theme]);
```

`tailwind.config.js` musí mít `darkMode: 'class'`.

### Detekce systému

Default na systémové nastavení, ale s uložením preference uživatele:

```tsx
const stored = localStorage.getItem('theme');
const systemDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
const initial = stored || (systemDark ? 'dark' : 'light');
```

Sledovat změny systému:

```tsx
useEffect(() => {
  const media = window.matchMedia('(prefers-color-scheme: dark)');
  const handler = () => { if (!localStorage.getItem('theme')) setTheme(media.matches ? 'dark' : 'light'); };
  media.addEventListener('change', handler);
  return () => media.removeEventListener('change', handler);
}, []);
```

### Pravidla pro dark mode

- **Žádná čistá černá** (`#000`). Slate-900 (`#0f172a`) je dost tmavá a méně kontrastuje s textem (lepší pro oči).
- **Žádná čistá bílá** v textu na tmavém. Slate-100 (`#f1f5f9`) je dost světlá.
- **Stíny** jsou málo viditelné — nahrazují je bordery (`dark:border-slate-700`).
- **Barvy s opacity:** `dark:bg-indigo-900/20` místo plné `bg-indigo-100` — tlumené, kompatibilní.
- **Ikony a obrázky:** kontrolovat čitelnost. Logo bývá potřeba mít dvě verze (světlé na tmavém pozadí).
- **Testovat každou komponentu** v obou módech — focus rings, hovery, disabled states.

### Tříbarevný systém (light / dark / system)

```tsx
type Theme = 'light' | 'dark' | 'system';
```

Nezapomenout na možnost „system" — uživatel chce nechat OS rozhodnout.

---

## 37. Responzivita

### Breakpointy (Tailwind defaults, neměním)

```
sm:  640px   — velký mobil / malý tablet
md:  768px   — tablet
lg:  1024px  — desktop
xl:  1280px  — wide desktop
2xl: 1536px  — large desktop
```

### Grid systém

```tsx
// Stat karty (3-4 na řadě):
className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6"

// 2 sloupce obsah:
className="grid grid-cols-1 lg:grid-cols-2 gap-6"

// Layout se sidebarem:
className="flex min-h-screen"
// Sidebar: "hidden lg:flex lg:w-64 lg:flex-col"
// Main: "flex-1 lg:ml-64"
```

### Mobile-first

Píšu CSS pro mobil jako default, pak rozšiřuji pro větší obrazovky. `sm:`, `md:`, `lg:` jsou „a větší", nikdy „a menší".

```tsx
// ✅ Mobile-first:
className="p-4 sm:p-6 lg:p-8"

// ❌ Desktop-first:
className="p-8 lg:p-6 sm:p-4"
```

### Mobilní pravidla

- Bottom nav místo sidebar na `< lg`.
- Tabulky se mění na karty na `< md`.
- Grafy: `height={200}` na mobilu, `height={280}` na desktopu (přes responsive wrapper nebo media query).
- Modály: `max-w-full` na mobilech — `className="... max-w-md mx-4 sm:mx-auto"`.
- Tlačítka v header: pouze ikona na mobilu, ikona + text na desktopu.
- Hit targets: minimum 44×44 px na mobilu (Apple HIG).
- Font size minimum: 16px na inputech (jinak iOS auto-zoomuje).

### Testovací breakpointy

V dev tools projedu při každé úpravě:

```
375px   iPhone SE   — nejmenší relevantní obrazovka
414px   iPhone Plus — typický mobil
768px   iPad        — tablet portrait
1024px  iPad Pro    — tablet landscape, malý laptop
1440px  MacBook     — typický desktop
1920px  Full HD     — wide desktop
```

### Touch vs mouse

```
@media (hover: hover)   — myš/trackpad
@media (hover: none)    — touch device
```

Hover stavy nezobrazovat na touch — uživatel je nemůže spustit (kromě edge case přidržení prstu, který nikdy nepoužívá).

```css
@media (hover: hover) {
  .button:hover { background: ...; }
}
```

---

## 38. Animace a motion principles

### Co animuji

```css
/* Barvy a pozadí — vždy: */
transition-colors duration-150

/* Průhlednost: */
transition-opacity duration-150

/* Transformace (modál, dropdown): */
transition-all duration-150 ease-out

/* Progress bar plnění: */
transition-all duration-500 ease-out

/* Stránkový přechod: */
transition-opacity duration-200
```

### Co NEanimuji

- Layout změny (width, height, margin, padding) — způsobují reflow, jsou pomalé.
- Hover změny, které trvají déle než 200ms — uživatel čeká.
- Scroll-triggered animace — zbytečná komplexita.

### Easing — kdy co

Easing curve říká, jak se animace zrychluje a zpomaluje. Volba ovlivňuje pocit.

```
ease-out (cubic-bezier(0, 0, 0.2, 1))
  → Rychlý start, pomalý konec. "Doráží" k cíli.
  → Použití: vstupy (modal in, toast in, hover on)

ease-in (cubic-bezier(0.4, 0, 1, 1))
  → Pomalý start, rychlý konec. "Uhání pryč".
  → Použití: odchody (modal out, toast out)

ease-in-out (cubic-bezier(0.4, 0, 0.2, 1))
  → Symetrické. Plynulé na obou koncích.
  → Použití: kontinuální pohyby (toggle, sliding, drag)

linear
  → Konstantní rychlost.
  → Použití: indeterminate progress, rotující spinner, fyzikálně dlouhé pohyby
```

Pravidlo: **většinu UI animací = `ease-out`**. Vypadá responzivně, předvídatelně.

### Duration — kdy co

```
50-100ms    →  mikro-interakce (color change na hover, focus ring)
150ms       →  default pro UI změny (modal, dropdown, toast)
200-300ms   →  velké tranzice (page transition, large content swap)
500ms+      →  attention-getting animace (progress bar fill, success checkmark)
```

Pravidlo: pokud animace trvá > 300ms a není to záměr (např. progress bar), je moc pomalá. Uživatel ji vnímá jako lag.

### Stagger — staggered animace

Když se objevuje seznam, každá položka má drobné delay:

```tsx
{items.map((item, idx) => (
  <div
    key={item.id}
    style={{ animationDelay: `${idx * 30}ms` }}
    className="animate-fade-in"
  >
    ...
  </div>
))}
```

30ms na položku je sweet spot. Méně = nevidět. Více = pomalé. Max 10 položek se animuje s delay, zbytek hned (jinak by čekal 1+ s).

### Anticipation a follow-through

Drobné zvýraznění interakce. Tlačítko stiskneš → mírně se zmenší (`active:scale-[0.98]`), pak vrátí. Vypadá to fyzicky reálně.

```tsx
className="... active:scale-[0.98] transition-transform"
```

### Page transitions

```tsx
// App.tsx nebo PageWrapper.tsx
<div
  key={location.pathname}
  className="animate-fade-in"
>
  {children}
</div>

// tailwind.config.js:
animation: {
  'fade-in': 'fadeIn 200ms ease-out',
},
keyframes: {
  fadeIn: {
    '0%': { opacity: '0', transform: 'translateY(4px)' },
    '100%': { opacity: '1', transform: 'translateY(0)' },
  },
},
```

### `prefers-reduced-motion`

Někteří uživatelé mají v OS vypnuté animace (motion sickness, attention disorders). Respektovat.

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

Tailwind plugin `motion-safe:` a `motion-reduce:` umožňují per-element kontrolu:

```tsx
className="motion-safe:animate-pulse"
```

---

## 39. Přístupnost (a11y)

A11y není „extra". Je to definice toho, jestli UI funguje pro skutečné lidi. Slepí, neslyšící, motoricky postižení, lidé s pomalou klávesnicí, lidé na vlaku s malou obrazovkou — všichni si zaslouží použitelné UI.

### Kontrast (WCAG)

```
WCAG AA:    4.5:1 pro běžný text, 3.0:1 pro velký text a UI prvky
WCAG AAA:   7.0:1 pro běžný text, 4.5:1 pro velký text
```

Cíl: vždy AA, AAA tam, kde to lze. Kontrast testovat každou kombinací text + pozadí.

Nástroje:

- Browser DevTools (Chrome / Firefox) → Accessibility tab
- `axe DevTools` extension
- WebAIM Contrast Checker

### Sémantický HTML

Pravý HTML element pro pravou funkci. Nikdy `<div onClick>` místo `<button>`.

```tsx
// ✅
<button onClick={...}>Smazat</button>

// ❌
<div onClick={...} className="cursor-pointer">Smazat</div>
```

Sémantický element zdarma dává:

- Keyboard support (Enter, Space).
- Screen reader oznámení („button, Smazat").
- Focus styles.
- Correct ARIA role.

### Tabulky používat tabulky, formuláře `<form>`, navigace `<nav>`, nadpisy `<h1>`-`<h6>`, seznamy `<ul>`/`<ol>`.

### ARIA — kdy

Pravidlo: **No ARIA is better than wrong ARIA.** Použij ARIA jen tam, kde sémantický HTML nestačí.

```tsx
// ✅ Custom toggle bez nativního ekvivalentu:
<button role="switch" aria-checked={enabled}>...</button>

// ❌ Zbytečný ARIA na nativním elementu:
<button role="button">...</button>  // <button> už má role="button"
```

Časté použití ARIA:

- `aria-label` — textový popis pro icon-only tlačítka.
- `aria-labelledby` — odkaz na ID elementu, který popisuje tento (např. modal title).
- `aria-describedby` — odkaz na delší popis (helper text k inputu).
- `aria-expanded` — accordion, dropdown.
- `aria-hidden="true"` — dekorativní ikony, které screen reader nemá číst.
- `aria-live` — region, kterou screen reader hlásí při změně (toast).
- `role="alert"` — důležitá zpráva (error).
- `role="status"` — méně důležitá zpráva (toast success).

### Screen reader only text

Pro vizuální kontext, kterého screen reader nevidí (např. ikona vedle textu):

```tsx
<button>
  <TrashIcon className="w-4 h-4" aria-hidden="true" />
  <span className="sr-only">Smazat transakci</span>
  Smazat
</button>
```

Tailwind `sr-only` třída skryje vizuálně, ale screen reader to přečte.

### Hit targets

Minimum 44×44 px na touch zařízeních (Apple HIG, WCAG 2.5.5). Na desktopu 24×24 px stačí, ale 36+ je lepší.

Pro malé ikony zajisti **klikatelnou plochu** větší než vizuální ikona:

```tsx
<button className="p-2">  {/* 4 + 16 (ikona) + 4 = 24, ale s paddingem je hit area 32+ */}
  <XIcon className="w-4 h-4" />
</button>
```

### Klávesnice — každá akce dosažitelná

Pravidlo: cokoli, co jde myší, musí jít klávesnicí.

- `Tab` — pohyb mezi interaktivními prvky.
- `Enter` / `Space` — aktivace tlačítka.
- `Escape` — zavření modal / dropdown / picker.
- Šipky — pohyb v listech (tab, radio, menu).
- `Home` / `End` — první / poslední položka v seznamu.

Testovat: odpoj myš, projed všechny user flow jen klávesnicí.

### Focus visible

`focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2` na všem interaktivním. Ne `focus:outline-none` bez náhrady.

Pro „myší" uživatele se ring zbytečně objevuje. Řešení: `focus-visible` místo `focus`:

```css
button:focus-visible {
  outline: 2px solid #6366f1;
  outline-offset: 2px;
}
button:focus:not(:focus-visible) {
  outline: none;
}
```

Tailwind ekvivalent: `focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2`.

### Form labels

Každý input má label propojený přes `htmlFor`/`id`. Placeholder není label.

```tsx
// ✅
<label htmlFor="email">E-mail</label>
<input id="email" type="email" />

// ❌ Placeholder místo labelu:
<input placeholder="E-mail" />
```

### Error messages

Chybové zprávy spojené s polem přes `aria-describedby`:

```tsx
<input id="email" aria-invalid={!!error} aria-describedby={error ? "email-error" : undefined} />
{error && <p id="email-error" role="alert">{error}</p>}
```

### Images and icons

```tsx
// Informativní obrázek:
<img src="..." alt="Graf příjmů za posledních 6 měsíců" />

// Dekorativní:
<img src="..." alt="" />

// Ikona s vlastním textem vedle:
<TrashIcon aria-hidden="true" />
<span>Smazat</span>

// Icon-only tlačítko:
<button aria-label="Smazat">
  <TrashIcon aria-hidden="true" />
</button>
```

### Color is not the only signal

Nikdy jen barvou. Zelený / červený text rozliš i ikonou nebo prefix textem („+" / „−"), aby barvoslepý člověk poznal.

```tsx
// ❌ Jen barva:
<span className="text-emerald-600">{value}</span>

// ✅ Barva + prefix + ikona:
<span className="text-emerald-600 inline-flex items-center gap-1">
  <ArrowUpIcon className="w-3 h-3" /> +{value}
</span>
```

### `prefers-reduced-motion`

Viz kap. 38. Animace musí jít vypnout.

### Testovací nástroje

```
axe DevTools         — automatická a11y kontrola
WAVE                 — vizuální markup chyb
Lighthouse           — Chrome built-in audit
NVDA / JAWS / VoiceOver — skutečné screen readery
```

---

## 40. Focus management

Klávesnicová navigace vyžaduje pečlivou správu, kde je „kurzor".

### Tab order

Tab prochází prvky v pořadí DOM. Neměnit přes `tabindex` (kromě výjimek).

```tsx
tabindex="0"   →  prvek je v tab orderu (default pro nativní interactive)
tabindex="-1"  →  prvek lze focusovat programaticky, ale není v tab orderu
tabindex="1+"  →  NIKDY POUŽÍVAT. Rozbije přirozené pořadí.
```

`tabindex="-1"` používám pro:

- Modal kontejner (focus se programaticky přesune dovnitř).
- Skip links (focusovaný, ne v tabu).
- Sekce, na které focus jen skočí ze skip linku.

### Focus trap (uvnitř modalu)

Když je modal otevřený, Tab nesmí utéct pryč:

```tsx
import { FocusTrap } from '@headlessui/react';

<FocusTrap>
  <Modal>...</Modal>
</FocusTrap>
```

Nebo `radix-ui` Dialog, který trap má vestavěný.

### Focus restoration

Po zavření modalu / dropdownu se focus vrátí na trigger:

```tsx
const triggerRef = useRef<HTMLButtonElement>(null);

const handleClose = () => {
  setOpen(false);
  triggerRef.current?.focus();
};
```

`radix-ui` to dělá automaticky přes `restoreFocus`.

### Initial focus v modalu

Po otevření modalu focus skočí na první input nebo na primární tlačítko:

```tsx
<Modal initialFocus="firstInput">  // konvence
  <input autoFocus />  // nebo
  ...
</Modal>
```

Pro confirmation modaly focus na **Cancel** (ne Destructive) — aby Enter omylem nesmazal.

### Skip links

Pro klávesnicové uživatele přeskočit navigaci:

```tsx
<a 
  href="#main"
  className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 
             focus:bg-white focus:px-4 focus:py-2 focus:rounded focus:shadow-lg
             focus:z-50"
>
  Přeskočit na obsah
</a>
<nav>...</nav>
<main id="main">...</main>
```

Skryté default, viditelné při focusu (přes Tab z URL baru).

### Auto-focus

Auto-focus jen kde to dává smysl:

```
✅ Modal s formulářem  →  první input
✅ Search modal        →  search input
✅ Standalone přihlášení → email input
❌ Formulář v rámci stránky → krade focus z rest of page
❌ Dashboard s několika widgety
```

---

## 41. Keyboard shortcuts

Power useři milují klávesovky. Konvence:

```
Cmd/Ctrl + K       →  Open command palette / global search
Cmd/Ctrl + /       →  Show keyboard shortcuts help
?                  →  Show shortcuts (without modifier, on most apps)
Esc                →  Close modal / dropdown / cancel current
Cmd/Ctrl + Enter   →  Submit form
Cmd/Ctrl + S       →  Save (na auto-save aplikacích zbytečné, jinak ano)
Cmd/Ctrl + Z       →  Undo
Cmd/Ctrl + Shift + Z  → Redo
N                  →  New (in context: new transaction, new note)
E                  →  Edit selected
Del / Backspace    →  Delete selected
J / K              →  Down / Up in list (Gmail, Linear convention)
G then [letter]    →  Go to section (G+I = inbox, G+S = settings)
```

### Implementace

Použiju knihovnu `react-hotkeys-hook`, `tinykeys` nebo Mousetrap. Vlastní implementace `window.addEventListener('keydown')` je full of edge cases.

```tsx
import { useHotkeys } from 'react-hotkeys-hook';

useHotkeys('mod+k', () => setSearchOpen(true));
useHotkeys('mod+s', (e) => { e.preventDefault(); save(); });
useHotkeys('?', () => setShortcutsHelp(true));
```

`mod` = `Cmd` na macOS, `Ctrl` jinde — automaticky.

### Pravidla shortcuts

- **Konvence respektovat:** `Cmd+S` = save, `Cmd+K` = search. Nedělat vlastní mapping.
- **Nepřepisovat browser shortcuts:** `Cmd+T` (nová záložka), `Cmd+W` (zavřít) — leave alone.
- **Zobrazit shortcuts** v UI: vedle položek menu `<kbd>⌘K</kbd>`, v ? overlay seznam všech.
- **Kontextuální shortcuts** (E, D pro selected row) — disabled pokud není selekce.
- **NE shortcuts v inputu:** uživatel píše, neaktivovat shortcuts z liter (jen s modifierem).

### `<kbd>` styling

```tsx
<kbd className="px-1.5 py-0.5 text-xs font-mono font-medium 
                bg-gray-100 dark:bg-slate-700 
                text-gray-700 dark:text-slate-300
                border border-gray-300 dark:border-slate-600
                rounded shadow-sm">
  ⌘K
</kbd>
```

Symbol Cmd je `⌘` (U+2318), Option `⌥`, Shift `⇧`, Ctrl `⌃`.

---

## 42. Internacionalizace (i18n)

Pokud aplikace cílí jen na ČR a nikdy nepoužije jiný jazyk, můžeš přeskočit. Ale i jednojazyčná aplikace má pravidla:

### Text expansion

Cizí jazyky bývají delší než angličtina:

```
Anglicky:    "Save"           (4 znaky)
Česky:       "Uložit"         (6 znaků)
Německy:     "Speichern"      (9 znaků)  ←
Francouzsky: "Enregistrer"    (11 znaků) ←
```

Tlačítka, labely, sidebar položky musí mít **flex layout**, nikdy fixed width. Tested with longest expected text.

Pravidlo: design tlačítka by měl unést **30 % delší** text bez rozbití.

### Pluralizace

Viz kap. 4. Pro multi-jazyk používat `Intl.PluralRules` nebo i18n knihovny (i18next, FormatJS):

```tsx
const t = useTranslation();
t('transactions_count', { count: 5 })
// → "5 transakcí" v CZ
// → "5 transactions" v EN  
// → "5 Transaktionen" v DE
```

### Datum, čas, čísla

`Intl.NumberFormat`, `Intl.DateTimeFormat` automaticky lokalizují podle locale:

```tsx
const date = new Date();
date.toLocaleDateString('cs-CZ');  // "13. 5. 2026"
date.toLocaleDateString('en-US');  // "5/13/2026"
date.toLocaleDateString('de-DE');  // "13.5.2026"

const num = 1234.56;
num.toLocaleString('cs-CZ');  // "1 234,56"
num.toLocaleString('en-US');  // "1,234.56"
num.toLocaleString('de-DE');  // "1.234,56"
```

### RTL (right-to-left)

Pro arabštinu, hebrejštinu — celé UI flipuje. Tailwind plugin `tailwindcss-rtl` přidá utility `ltr:` a `rtl:`:

```tsx
className="ml-4 rtl:ml-0 rtl:mr-4"

// nebo logické properties:
className="ms-4"  // margin-inline-start = ml v LTR, mr v RTL
```

V češtině neaktuální, ale dobré navrhovat layout symetricky, kde to lze (icon vždy „před" text, ne „vlevo od").

### Lokalizační soubory

```
locales/
  cs.json
  en.json
  de.json
```

```json
{
  "transactions": {
    "title": "Transakce",
    "add": "Přidat transakci",
    "empty": "Žádné transakce",
    "count": "{count, plural, one {# transakce} few {# transakce} other {# transakcí}}"
  }
}
```

ICU MessageFormat (jako výše) zvládá pluralizaci a interpolace robustně.

---

## 43. Performance-aware design

Design rozhodnutí má performance dopady. Co vypadá hezky, ale je pomalé:

### Virtualizace u dlouhých seznamů

Pokud zobrazuju > 100 položek v listu, použij virtualizaci (`react-window`, `TanStack Virtual`):

```tsx
import { useVirtualizer } from '@tanstack/react-virtual';

const virtualizer = useVirtualizer({
  count: items.length,
  getScrollElement: () => parentRef.current,
  estimateSize: () => 64,  // výška jednoho řádku
});
```

Bez virtualizace 10 000 řádků = pomalé scrollování + dlouhý initial render. S virtualizací = render jen ~20 viditelných řádků.

### Lazy loading obrázků

```tsx
<img src={...} loading="lazy" alt="..." />
```

Native lazy loading. Pro pokročilejší (blur placeholder, intersection observer) `next/image` nebo `react-lazyload`.

### Code splitting

Velké pages a komponenty (admin, settings, charts) načítat až při použití:

```tsx
const Settings = lazy(() => import('./Settings'));

<Suspense fallback={<Spinner />}>
  <Settings />
</Suspense>
```

### Memoizace

```tsx
const expensiveValue = useMemo(() => computeStats(transactions), [transactions]);
const handler = useCallback(() => doSomething(id), [id]);
```

Ne všude — `useMemo` má vlastní overhead. Použij když je computation skutečně drahá a stejné inputy bývají časté.

### Skeleton vs spinner — perf úhel

Skeleton vyžaduje render celé komponenty, jen s placeholder daty. Spinner je jeden DOM node. Pro **velmi rychlé** odpovědi spinner bije skeleton.

```
< 300ms odpověd   →  Nezobrazuj nic. Skeleton blikne a vypadá to rozbitě.
300ms - 1s         →  Subtle spinner v rohu nebo top bar.
> 1s               →  Skeleton.
> 5s               →  Skeleton + indikátor progressu (% nebo „Stahuji…").
```

### Debounce / throttle

Pro search, filter, scroll handlery:

```tsx
const debouncedSearch = useDebouncedCallback((q) => api.search(q), 300);

<input onChange={(e) => debouncedSearch(e.target.value)} />
```

`debounce` = počká, až user přestane psát. `throttle` = max X volání za sekundu (pro scroll).

### CSS performance

```
✅ Animovat:    opacity, transform (GPU-accelerated)
❌ Animovat:    width, height, margin, padding, top, left (CPU reflow)
```

`will-change: transform` přidává GPU hint, ale jen tam, kde animace probíhá. Nadužívání zhorší výkon.

---

## 44. Komponentní filozofie

Jak strukturuju komponenty. Méně o vzhledu, víc o údržbě.

### Composition over configuration

```tsx
// ✅ Composable:
<Card>
  <Card.Header>
    <Card.Title>Příjmy</Card.Title>
    <Card.Action>
      <Button>Export</Button>
    </Card.Action>
  </Card.Header>
  <Card.Body>
    ...
  </Card.Body>
</Card>

// ❌ Configuration-heavy:
<Card 
  title="Příjmy" 
  action={<Button>Export</Button>}
  bodyContent={...}
/>
```

Composition je flexibilnější. Když chci v hlavičce dvě tlačítka nebo nadpis ze tří částí, composition to umí beze změny API.

### Varianty přes `cva`

`class-variance-authority` knihovna pro varianty komponent:

```tsx
import { cva } from 'class-variance-authority';

const button = cva(
  'inline-flex items-center justify-center font-medium rounded-md transition-colors',
  {
    variants: {
      variant: {
        primary: 'bg-indigo-600 text-white hover:bg-indigo-700',
        secondary: 'bg-white text-gray-700 border border-gray-300 hover:bg-gray-50',
        ghost: 'text-gray-500 hover:bg-gray-100',
        destructive: 'bg-red-600 text-white hover:bg-red-700',
      },
      size: {
        sm: 'px-2.5 py-1.5 text-xs',
        md: 'px-4 py-2 text-sm',
        lg: 'px-5 py-2.5 text-base',
      },
    },
    defaultVariants: {
      variant: 'primary',
      size: 'md',
    },
  }
);

<button className={button({ variant: 'secondary', size: 'lg' })}>...</button>
```

Místo if/else v className. TypeScript typuje varianty.

### Polymorphic `as` prop

Komponenta může být různý HTML element:

```tsx
<Button as="a" href="/">Domů</Button>
<Button as="button" onClick={...}>Klikni</Button>
<Button as={Link} to="/">Domů</Button>
```

Implementace přes generika v TS:

```tsx
type ButtonProps<E extends ElementType> = {
  as?: E;
  children: ReactNode;
} & ComponentPropsWithoutRef<E>;

function Button<E extends ElementType = 'button'>({ as, ...props }: ButtonProps<E>) {
  const Component = as || 'button';
  return <Component {...props} />;
}
```

### Forwarding refs

Komponenta, která wrappuje nativní element, forwarduje ref:

```tsx
const Button = forwardRef<HTMLButtonElement, ButtonProps>((props, ref) => (
  <button ref={ref} {...props} />
));
```

Bez refu nelze focusovat, scrollovat to, používat focus management knihovny.

### Controlled vs uncontrolled

Formulářové komponenty (Input, Select, Checkbox) musí podporovat oba módy:

```tsx
// Uncontrolled (s default):
<Input defaultValue="hello" />

// Controlled:
<Input value={val} onChange={(e) => setVal(e.target.value)} />
```

Konvence shadcn/ui a Radix.

### Klíčová pravidla komponentního API

- **Props pojmenovávat sémanticky**, ne podle vzhledu. `variant="primary"`, ne `color="blue"`. Modré může zítra být fialové, ale „primary" zůstane primary.
- **Klíčové komponenty s `data-*` atributy** pro testování:
  ```tsx
  <button data-testid="submit-button">...</button>
  ```
- **className přijmi vždy**, slouč ho s defaultními (`clsx` nebo `cn` helper):
  ```tsx
  function Button({ className, ...props }: ButtonProps) {
    return <button className={cn(button(props), className)} {...props} />;
  }
  ```
- **Render props nebo children-as-function** pro flexibilní rendering uvnitř:
  ```tsx
  <Dropdown>{({ open }) => (open ? '↑' : '↓')}</Dropdown>
  ```
- **Nepředávat zbytečné props dolů** — destructuruj a předej jen relevantní.

### Adresářová struktura

```
src/
  components/
    ui/                    ← primitivní komponenty (Button, Input, Card)
      Button.tsx
      Button.stories.tsx
      Button.test.tsx
    composed/              ← komponenty stavěné z ui (StatCard, FilterBar)
      StatCard.tsx
    pages/                 ← page-specifické komponenty
      Transactions/
        TransactionList.tsx
        TransactionRow.tsx
  hooks/
  utils/
  styles/
```

Pravidlo: komponenty v `ui/` neimportují z `pages/`. Závislosti tečou jen jedním směrem.

---

## 45. Co nikdy nedělám

| ❌ Nedělám | ✅ Místo toho |
|-----------|-------------|
| Gradienty na tlačítkách nebo kartách | Solid barva + hover darkening |
| Box shadow `shadow-xl` na kartách | `shadow-sm` s borderem |
| Více než 3 různé barvy na stránce | Omezená sémantická paleta |
| Tučný text (`font-bold`) na šedé barvě | Buď tučné+tmavé, nebo tenké+šedé |
| Full-width tlačítka na desktopu (mimo formulář) | Tlačítko velikosti obsahu |
| Nativní `alert()` nebo `confirm()` | Vlastní modál |
| Inline CSS pro styling (kromě dynamických barev) | Tailwind třídy |
| `!important` | Přepracování struktury |
| Hover efekty měnící layout (margin, padding) | Pouze barvy, opacity, transform |
| Ikona vedle každého textu pro „ozdobu" | Ikony jen kde nesou informaci |
| Více než 2 primární CTA na stránce | Jasná hierarchie akcí |
| Scrollbar v modal overlaps obsah | `overflow-y-auto` na modal containeru |
| `<div onClick>` místo `<button>` | Sémantický HTML |
| Placeholder jako label | `<label>` element |
| Hover-only akce na mobilu | Vždy viditelné nebo dropdown |
| Animace > 300ms na běžné UI | Max 200ms |
| Layout změny v animaci (width, height) | Animovat transform a opacity |
| Modal pro každé potvrzení | Undo pattern |
| Hvězdičky u povinných polí | Validace při submitu |
| Title Case v českých nadpisech | Sentence case |
| Toast pro kritickou chybu | Inline alert nebo modal |
| Spinner místo skeletonu když znám tvar | Skeleton |
| Náhodný `z-50` | Z-index systém |
| Více než 3 fonty | Jeden font + monospace |
| Justified text (`text-justify`) | Left-aligned |
| Underline pod hover linkem | Změna barvy nebo background |
| Auto-focus na formulář v dashboardu | Auto-focus jen u modal/page-as-form |
| Pure black `#000` a pure white `#fff` v dark mode | Slate-900 a slate-100 |
| Custom focus styling bez `:focus-visible` | `focus-visible:` |
| Klikatelná oblast < 36×36 px (desktop) | Min 36×36, ideálně 44×44 |
| Sortování bez vizuálního indikátoru | Šipka u aktivního sloupce |
| Tooltip na kritické informaci | Vždy ve viditelném UI, tooltip jen vysvětluje |

---

## 46. Checklist před dokončením

Před tím, než označím UI za hotové, projdu tento seznam:

**Funkčnost:**

- [ ] Funguje dark mode na každé komponentě?
- [ ] Má každý prázdný stav zprávu a akci?
- [ ] Je na mobilu (375px) vše čitelné a klikatelné?
- [ ] Mají všechny interaktivní prvky focus stav (pro klávesnici)?
- [ ] Fungují všechny akce klávesnicí?
- [ ] Zavře se modal Escape klávesou + klikem na backdrop + X tlačítkem?
- [ ] Vrátí se focus na trigger po zavření modalu?
- [ ] Funguje undo / rollback při optimistic UI?

**Vizuální:**

- [ ] Jsou mezery konzistentní — používám systém, ne náhodné hodnoty?
- [ ] Je na stránce jasné, co je primární akce?
- [ ] Jsou barvy použity sémanticky, ne dekorativně?
- [ ] Splňují všechny text/pozadí kombinace WCAG AA?
- [ ] Mají všechny ikony konzistentní velikost a styl?
- [ ] Jsou všechny hit targets minimálně 36×36 px (desktop) / 44×44 px (mobil)?

**Obsah:**

- [ ] Mají formuláře validaci s konkrétními chybovými zprávami?
- [ ] Je microcopy přátelská, věcná, aktivní?
- [ ] Pluralizace funguje pro 0 / 1 / 2-4 / 5+ položek?
- [ ] Jsou všechny destruktivní akce s explicitním varováním?
- [ ] Existují loading, empty, error stavy pro každý seznam/sekci?

**Edge cases:**

- [ ] Funguje to s 0 / 1 / 100 / 10000 položkami?
- [ ] Jsou dlouhé řetězce truncated nebo line-clamped?
- [ ] Co se stane se zápornými / nulovými / NaN hodnotami?
- [ ] Co se stane při výpadku sítě / pomalém spojení?

**Přístupnost:**

- [ ] Mají všechny inputy `<label>`?
- [ ] Mají všechny icon-only tlačítka `aria-label`?
- [ ] Jsou dekorativní ikony `aria-hidden="true"`?
- [ ] Hlásí screen reader změny (toasty, errors) přes `aria-live` / `role="alert"`?
- [ ] Funguje aplikace s vypnutou myší (pouze klávesnice)?
- [ ] Respektuje `prefers-reduced-motion`?

**Performance:**

- [ ] Mají dlouhé listy virtualizaci?
- [ ] Jsou obrázky `loading="lazy"`?
- [ ] Jsou velké stránky code-splitted?
- [ ] Fungují přechody plynule, ne trhanně?

**Technické:**

- [ ] Projde `npm run build` bez TS chyb?
- [ ] Projde `npm run lint` bez varování?
- [ ] Projde axe DevTools bez violations?
- [ ] Projde Lighthouse audit s ≥ 90 v Accessibility?
- [ ] Funguje to v Safari, Chrome, Firefox?

---

## 47. Závěrečná filozofie

Dobré UI je takové, kterého si uživatel nevšimne. Špatné UI křičí. Skvělé UI je nositelné dál — neviděno, ale cítěno jako klid.

Tento dokument není dogma. Je to **výchozí stav** mého rozhodování. Pokud konkrétní projekt vyžaduje jinou cestu (značka, audience, edge case), pravidla se ohýbají — vždy ale s vědomím, **co** ohýbám a **proč**.

Tři zlatá pravidla, podle kterých testuji každé rozhodnutí:

1. **Pomáhá to uživateli?** Pokud ne, jsem v cestě.
2. **Pochopí to bez vysvětlení?** Pokud ne, je to moc komplexní.
3. **Funguje to i v 3:00 ráno na vlaku s pomalým 3G a slepým uživatelem s vypnutými animacemi?** Pokud ano, je to hotové.

Konzistentně držet pravidla je důležitější, než hledat dokonalost u jednotlivého prvku. Konzistence buduje důvěru. Dokonalost jednotlivosti rozbíjí celek.

48. Color-coded seznamy a stabilní kategorizace
Tahle kapitola je o tom, jak udělat seznam, který se okem čte rychleji než tabulka — a o rozdílu mezi UI, které funguje, a UI, které působí promyšleně.
Filozofie: barva jako informační kanál
Lidské periferní vidění rozpoznává barvu rychleji než tvar a tvar rychleji než text. V seznamu 50 transakcí uživatel chce na první letmé skenování říct „kolik je tu jídla a kolik dopravy" — a to dokáže jen barva.
Proto v seznamech s kategoriemi je barva primární informační kanál, ne dekorace. Pravidlo: pokud bych barvu odstranil a uživatel by potřeboval místo toho číst text, ztratil bych informaci.
Stabilní mapování kategorie → barva
Každá kategorie má jednu barvu napříč celou aplikací. „Jídlo" je vždy oranžové. „Doprava" je vždy žlutá. „Zdraví" je vždy růžové. Není to náhoda na řádku — je to identita kategorie.
Pravidlo: barva kategorie žije ve třech místech současně:

Levý border karty záznamu (3–4 px stripe)
Badge s názvem kategorie
Ikona kategorie, pokud existuje (v dashboardu, grafu, kategoria pickeru)

Trojí opakování buduje rozpoznání. Uživatel po dvou dnech ví, že „oranžový proužek vlevo" = jídlo, aniž by četl text.
Mapování: explicit > hash
1. Explicit mapping (preferované)
Každá kategorie v databázi má sloupec color. Uživatel ho může změnit v nastavení kategorií. Stabilita zaručena.
tstype Category = {
  id: string;
  name: string;
  color: string;       // '#f97316' (Tailwind orange-500)
  colorLight: string;  // '#ffedd5' (orange-100) pro badge bg
  icon?: LucideIcon;
};
2. Deterministický hash (fallback)
Pokud nemám explicit color, generuji ho z hashu jména. Jiné jméno = jiná barva, stejné jméno = vždy stejná barva.
tsconst CATEGORY_PALETTE = [
  { bg: 'bg-orange-100',  text: 'text-orange-700',  bar: 'bg-orange-500'  },
  { bg: 'bg-blue-100',    text: 'text-blue-700',    bar: 'bg-blue-500'    },
  { bg: 'bg-purple-100',  text: 'text-purple-700',  bar: 'bg-purple-500'  },
  { bg: 'bg-pink-100',    text: 'text-pink-700',    bar: 'bg-pink-500'    },
  { bg: 'bg-amber-100',   text: 'text-amber-700',   bar: 'bg-amber-500'   },
  { bg: 'bg-cyan-100',    text: 'text-cyan-700',    bar: 'bg-cyan-500'    },
  { bg: 'bg-violet-100',  text: 'text-violet-700',  bar: 'bg-violet-500'  },
  { bg: 'bg-rose-100',    text: 'text-rose-700',    bar: 'bg-rose-500'    },
  { bg: 'bg-teal-100',    text: 'text-teal-700',    bar: 'bg-teal-500'    },
];

function categoryColor(name: string) {
  const hash = name.split('').reduce((a, c) => a + c.charCodeAt(0), 0);
  return CATEGORY_PALETTE[hash % CATEGORY_PALETTE.length];
}
Pravidlo: paleta má min. 8–9 barev, abych se vyhnul kolizím u běžné domény (jídlo, doprava, bydlení, zdraví, zábava, mzda, freelance, úspory, ostatní).
Vyhrazené barvy nepoužívat v kategoriální paletě
V paletě pro kategorie nepoužívám:

Indigo — primární barva aplikace, kolidovala by s CTA tlačítky.
Red — vyhrazená pro chybu / výdaj / destrukci.
Emerald — vyhrazená pro úspěch / příjem.
Šedou — vyhrazená pro „nezařazené" a placeholder stavy.

Zbývá orange, amber, yellow, lime, teal, cyan, blue, violet, purple, fuchsia, pink, rose — bohatě dost.
Anatomie record card (seznam jako karty)
Když je seznam bohatý — má kategorii, datum, název, hodnotu, akce — netřeba dělat tabulku. Každá položka je vlastní karta v stacku.
tsx<div className="space-y-3">
  {transactions.map(tx => {
    const cat = categoryColor(tx.category);
    return (
      <div
        key={tx.id}
        className="relative flex items-center gap-4 bg-white dark:bg-slate-800 
                   rounded-xl border border-gray-200 dark:border-slate-700 shadow-sm
                   pl-5 pr-4 py-4
                   hover:shadow-md hover:border-gray-300 dark:hover:border-slate-600
                   transition-all duration-150"
      >
        {/* Levý barevný proužek = category indicator */}
        <span 
          className={`absolute left-0 top-3 bottom-3 w-1 rounded-r-full ${cat.bar}`}
          aria-hidden="true"
        />
        
        {/* Title + meta */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h3 className="text-sm font-medium text-gray-900 dark:text-slate-100 truncate">
              {tx.title}
            </h3>
            {tx.note && (
              <MessageSquareIcon 
                className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" 
                aria-label="Má poznámku"
              />
            )}
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500 dark:text-slate-400 tabular-nums">
              {formatDate(tx.date)}
            </span>
            <span className={`inline-flex items-center px-2 py-0.5 rounded-full 
                              text-xs font-medium ${cat.bg} ${cat.text}`}>
              {tx.category}
            </span>
          </div>
        </div>
        
        {/* Amount + actions */}
        <div className="flex items-center gap-3">
          <span className={`text-sm font-semibold tabular-nums whitespace-nowrap ${
            tx.amount > 0 
              ? 'text-emerald-600 dark:text-emerald-400' 
              : 'text-red-600 dark:text-red-400'
          }`}>
            {tx.amount > 0 ? '+' : ''}{formatCurrency(tx.amount)}
          </span>
          <div className="flex gap-0.5">
            <button 
              aria-label="Upravit"
              className="p-1.5 rounded text-gray-400 hover:text-gray-700 hover:bg-gray-100
                         dark:text-slate-500 dark:hover:text-slate-300 dark:hover:bg-slate-700
                         transition-colors duration-100"
            >
              <PencilIcon className="w-3.5 h-3.5" />
            </button>
            <button 
              aria-label="Smazat"
              className="p-1.5 rounded text-gray-400 hover:text-red-600 hover:bg-red-50
                         dark:text-slate-500 dark:hover:text-red-400 dark:hover:bg-red-900/20
                         transition-colors duration-100"
            >
              <TrashIcon className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>
    );
  })}
</div>
Klíčové detaily, na kterých záleží:

pl-5 (větší než p-4) — místo pro barevný proužek vlevo, bez kolize s obsahem.
Proužek absolute left-0 top-3 bottom-3 w-1 rounded-r-full — tenký, jen v ose karty, nedotýká se rohů.
space-y-3 mezi kartami — vzdušnost, ne nahuštění jako tabulka.
Hover: jemný lift přes hover:shadow-md + tmavší border.
Actions vpravo — drobné šedé ikony, ne barevná tlačítka.
tabular-nums na čísle a datu — sloupce čísel se zarovnají i bez text-right.

Card-list vs tabulka — kdy co
Tabulka:           hodně sloupců, srovnávací pohled, sortování, dense data
                   (faktury, logy, výkazy, admin tabulky)

Card-list:         každý záznam je bohatý (kategorie, status, hodnota, akce),
                   chci rychlou kategorizaci a mobilní použití
                   (transakce, úkoly, kontakty, kandidáti, notifikace)

Hybrid:            na desktopu tabulka, na mobilu cards
                   (univerzální, ale víc kódu)
V byznys aplikacích volím card-list jako default, tabulku jen kde úkol vyžaduje porovnání mnoha sloupců.
Pravidlo neredundance — color carries type
Pokud informaci nese barva, netiskni ji znovu textem.
❌ Špatně:
   "Lékárna  [Výdaj]  [Zdraví]    -520 Kč"
   (Červená hodnota říká „výdaj". Badge „Výdaj" je redundantní.)

✅ Správně:
   "Lékárna  [Zdraví]              -520 Kč"
   (Červená hodnota říká typ. Růžový badge říká kategorii. Bez duplikace.)
Stejný princip jinde:

Status pill „Aktivní" + zelená tečka → buď pill, nebo tečka. Ne obojí.
„Required" hvězdička + zvýrazněný label → jedna nebo druhá indikace.
„Selected" pozadí + checkmark ikona → jedna nebo druhá.

Pravidlo: každá informace má jednu vizuální reprezentaci. Zdvojení je šum.
Tichost UI — méně textu, víc důvěry
UI, které je samovysvětlující, nepotřebuje nálepky vysvětlující funkce. Tohle je největší rozdíl mezi „Claude-grade" designem a „enterprise wizardem".
1. Žádné nadpisy nad samovysvětlujícími sekcemi
❌ "Filtry
    Zúž seznam podle názvu, typu, kategorie a měsíce."
    [search] [select] [select] [date]

✅ [search]  [select]  [select]  [date]
Search input s ikonou lupy říká „hledat". Selecty říkají „filtruj". Nadpis „Filtry" je redundantní vyhrazení místa.
2. Žádné subtitly pod názvem aplikace
❌ "FinTrack
    Osobní finance"

✅ "FinTrack"
Pokud je uživatel v aplikaci, ví o co jde. Subtitle krade prostor sidebaru.
3. Žádné popisy stránek pod nadpisem
❌ "Transakce
    Spravuj příjmy i výdaje, filtruj podle měsíce, typu a kategorie."

✅ "Transakce
    Nalezeno 9 transakcí"
Stránka „Transakce" zjevně slouží k práci s transakcemi. Sekundární info je užitečné metadata, ne vysvětlení.
4. Žádné instrukce nad formuláři
❌ "Vyplň všechna povinná pole označená hvězdičkou. Po odeslání…"

✅ [formulář s jasnými labely]
5. Žádné popisy tlačítek
❌ "Vytvořit novou transakci do systému"

✅ "Přidat transakci"  nebo  "+ Přidat"
Princip: UI, které musí vysvětlovat samo sebe, je špatně navržené. Vysvětlování nahradíš lepším designem, ne větším množstvím textu.
Akce na řádku — tlumené, ne křiklavé
Edit / Delete ikony na transakční kartě jsou šedé, malé, decentní. Když jsou výrazné, soupeří s daty o pozornost.
tsx<button
  aria-label="Smazat"
  className="p-1.5 rounded text-gray-400 hover:text-red-600 hover:bg-red-50
             transition-colors duration-100"
>
  <TrashIcon className="w-3.5 h-3.5" />
</button>
Pravidla row actions:

Default text-gray-400 — téměř splývají.
Hover „probudí" barvu — modrá edit, červená delete.
Velikost ikony w-3.5 h-3.5 — menší než ikony v page headeru.
Padding p-1.5 — hit target stále ≥ 28 px.
Nikdy color-filled tlačítka v řádku.
Volitelně: actions visible jen group-hover (viz kap. 28).

Filter bar — bez nadpisu, na jedné lince
tsx<div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 mb-6">
  <div className="relative flex-1 sm:max-w-md">
    <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
    <input
      type="search"
      placeholder="Hledat transakce..."
      className="w-full pl-9 pr-3 py-2 text-sm bg-white border border-gray-200 rounded-lg
                 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
    />
  </div>
  
  <Select value={type} className="w-full sm:w-32">
    <option>Vše</option>
    <option>Výdaj</option>
    <option>Příjem</option>
  </Select>
  
  <Select value={category} className="w-full sm:w-44">
    <option>Všechny kategorie</option>
  </Select>
  
  <input type="month" value={month} className="w-full sm:w-40 ..." />
</div>

Bez nadpisu „Filtry".
Bez popisu „Zúž seznam podle…".
Search nejširší, filtry fixní šířky.
Filtry aplikují okamžitě při změně.
Reset filtrů: malý odkaz pod barem, jen pokud jsou aktivní.

Page header — kompaktní
tsx<div className="flex items-end justify-between mb-6">
  <div>
    <h1 className="text-2xl font-bold text-gray-900 dark:text-slate-100">
      Transakce
    </h1>
    <p className="text-sm text-gray-500 dark:text-slate-400 mt-0.5">
      Nalezeno {count} {pluralize(count, ['transakce', 'transakce', 'transakcí'])}
    </p>
  </div>
  <Button variant="primary">
    <PlusIcon className="w-4 h-4" />
    Přidat transakci
  </Button>
</div>
Co tam není: descriptivní subtitle, breadcrumbs (pokud nejsou nezbytné), banner s tipy, sekundární akce.
Sidebar — logo + navigace, nic víc
tsx<aside className="w-64 bg-white dark:bg-slate-900 border-r border-gray-200 dark:border-slate-700 p-4">
  <div className="flex items-center gap-2 mb-8 px-3">
    <div className="w-8 h-8 bg-indigo-600 rounded-lg flex items-center justify-center 
                    text-white font-bold text-sm">F</div>
    <span className="font-semibold text-gray-900 dark:text-slate-100">FinTrack</span>
  </div>
  <nav>...</nav>
</aside>
Co tam není: subtitle „Osobní finance", popisek aplikace, „v1.0" badge nahoře.
Sekundární info — drobná, šedá, vedle hlavního
Drobné informace (datum, poznámka, počet) jsou:

Menší než hlavní obsah (text-xs vs text-sm).
Šedé (text-gray-500).
Vedle primárního textu, ne pod ním (pokud se vejdou).

tsx<div className="flex items-center gap-2">
  <span className="text-xs text-gray-500 tabular-nums">10. 5. 2026</span>
  <Badge category={tx.category} />
</div>
Vedle = méně vertikálního prostoru = víc obsahu na obrazovce.
Vizuální hierarchie v řádku — tři úrovně
V každé record card mám maximálně tři vizuální úrovně:
Úroveň 1 — Primární:   název záznamu     text-sm font-medium text-gray-900
Úroveň 2 — Hodnota:    částka, status    text-sm font-semibold + sémantická barva
Úroveň 3 — Meta:       datum, kategorie   text-xs text-gray-500 + barevný badge
Víc úrovní = vizuální chaos, oko neví kam dřív.
Anti-patterns — co dělá UI „less Claude"
Konkrétní seznam, co odlišuje Claude design od ostatních AI:
❌ Anti-pattern✅ Lepší řešeníŠedé univerzální badges pro všechny kategorieStabilní barva per kategorie + barevný left borderVýdaj + Kategorie badge vedle sebeJen kategorie — typ řekne barva hodnotyNadpis „Filtry" + popis nad filter baremFilter bar bez nadpisu„Osobní finance" pod logem v sidebaruJen logo + názevPopis stránky pod H1H1 + počet/datum jako sekundární infoHorizontální čáry mezi řádkyCards s mezerami (space-y-3)Velké výrazné akce v řádkuDrobné šedé ikony, hover „probouzí" barvuStejně velký text všudeHierarchie title > value > meta (3 úrovně max)Verbose tlačítkaStručné („Přidat transakci")„Loading…" text na buttonuSpinner + průběhový tvar slovesaModální popup pro každou drobnostInline edit, optimistic update, undoŠedý border všude stejnýBarevný left border jako category indicatorVelký padding karty (p-8)pl-5 pr-4 py-4 — hutnějšíCentrované řádkyLeft-aligned, hierarchie zleva doprava
Test: rychlý sken jednou rukou
Test, jestli je seznam dobře navržený. Otevři stránku a:

Bez čtení textu — co vidíš? Po 1 sekundě by mělo být zřejmé: tohle je seznam transakcí, jsou tu výdaje (červené) a příjmy (zelené), kategorie poznám podle barvy.
Po 3 sekundách víš, kolik je dnes výdajů a v jaké kategorii převažují, aniž bys četl jediné slovo navíc.
„Žmoulací" test: přimhouři oči, aby se text rozmazal. Pořád vidíš strukturu? Pořád poznáš kategorie podle barev? Pokud ano, vyhrál jsi.
Bez šedé: pokud bys mohl rozeznat kategorie a typy jen z textu (bez barev), máš v UI moc šedi a málo barvy.

Pokud UI projde tímto testem, je „Claude-grade".
Shrnutí — sedm pravidel, které dělají rozdíl

Každá kategorie má stabilní barvu napříč celou aplikací.
Barva žije ve třech místech: levý border karty + badge + ikona.
Card-list místo tabulky pro bohaté záznamy.
Color carries type — sémantická barva hodnoty říká typ, badge říká kategorii. Nikdy obojí jako text.
Tichost UI — žádné nadpisy nad self-evident sekcemi, žádné subtitly, žádné popisy stránek.
Akce v řádku jsou tlumené — šedé ikony, hover se barvou „probouzí".
Tři vizuální úrovně v každém řádku — title, value, meta. Ne víc.

---

## 49. Claude-grade aplikační kompozice: seznamová stránka

Tato sekce definuje přesné rozložení pro moderní SaaS / fintech aplikaci se sidebar navigací a hlavním seznamem záznamů.

Použij tento pattern vždy, když aplikace obsahuje stránku typu:

- Transakce
- Objednávky
- Úkoly
- Kontakty
- Faktury
- Rozpočet
- Kategorie
- Notifikace
- Jakýkoli seznam položek s názvem, datem, kategorií, hodnotou a akcemi

Cíl: výsledek musí působit jako hotový, prémiový SaaS dashboard — čistý, klidný, přesný, lehce „Linear / Stripe / Notion / fintech app“. Ne jako defaultní Tailwind demo.

---

### 1. Hlavní vizuální princip této obrazovky

Obrazovka musí působit jako **produktový dashboard**, ne jako stránka s náhodně poskládanými komponentami.

Správný pocit:

```txt
✅ čisté šedé pozadí
✅ bílý sidebar
✅ bílý toolbar jako jedna karta
✅ bílé record cards
✅ jemné bordery
✅ velmi jemné stíny
✅ jedna dominantní akce
✅ kompaktní, ale čitelný seznam
✅ barevné kategorie
✅ data jsou důležitější než dekorace
```

Špatný pocit:

```txt
❌ filtry rozházené volně po stránce
❌ příliš široký obsah
❌ moc vysoké karty
❌ tenké, nenápadné nebo náhodně barevné category čárky
❌ šedé badges bez charakteru
❌ moc popisných textů
❌ velké mezery bez důvodu
❌ akční ikony křičí víc než samotná data
```

---

### 2. Page shell

Základní layout používá fixní sidebar vlevo a centrovaný hlavní obsah.

```tsx
<div className="min-h-screen bg-gray-50 text-gray-900">
  <aside className="fixed inset-y-0 left-0 w-56 bg-white border-r border-gray-200">
    {/* Sidebar */}
  </aside>

  <main className="ml-56 min-h-screen">
    <div className="mx-auto max-w-[960px] px-8 py-8">
      {/* Page content */}
    </div>
  </main>
</div>
```

Pravidla:

- Sidebar je fixní vlevo.
- Sidebar má šířku `w-56` až `w-64`.
- Hlavní obsah **nesmí být roztažený přes celou obrazovku**.
- Pro jednoduché seznamové stránky používej `max-w-[920px]`, `max-w-[960px]` nebo `max-w-[1040px]`.
- Nepoužívej `max-w-7xl`, pokud stránka obsahuje jen seznam položek.
- Pozadí stránky je `bg-gray-50`.
- Obsahové bloky jsou bílé: `bg-white`.
- Stránka má působit vzdušně, ale ne prázdně.
- Vizuální těžiště musí být uprostřed hlavního obsahu, ne roztažené do krajů.

---

### 3. Sidebar polish

Sidebar musí být jednoduchý, čistý a stabilní. Nemá soutěžit s hlavním obsahem.

```tsx
<aside className="fixed inset-y-0 left-0 w-56 bg-white border-r border-gray-200">
  <div className="flex h-full flex-col">
    <div className="flex h-20 items-center gap-3 px-6 border-b border-gray-100">
      <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-600 text-sm font-semibold text-white shadow-sm">
        F
      </div>

      <span className="text-base font-semibold text-gray-900">
        FinTrack
      </span>
    </div>

    <nav className="flex-1 space-y-1 px-4 py-6">
      {/* nav items */}
    </nav>

    <div className="border-t border-gray-100 px-6 py-4 text-center text-xs text-gray-400">
      FinTrack v1.0
    </div>
  </div>
</aside>
```

Pravidla:

- Logo blok má výšku cca `h-20`.
- Logo ikona je `h-10 w-10 rounded-xl`.
- Název aplikace je `text-base font-semibold`.
- Nepřidávej subtitle typu „Osobní finance“, pokud není opravdu nutný.
- Sidebar položky mají `rounded-lg`.
- Aktivní položka má světlé indigo pozadí.
- Spodní verze aplikace je malá, šedá, ukotvená dole.
- Sidebar nesmí mít výrazný stín. Stačí pravý border.

Sidebar položka:

```tsx
<a
  className="flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-gray-600 transition-colors hover:bg-gray-100 hover:text-gray-900"
>
  <Icon className="h-4.5 w-4.5 text-gray-500" />
  Dashboard
</a>
```

Aktivní sidebar položka:

```tsx
<a
  className="flex items-center gap-3 rounded-lg bg-indigo-50 px-3 py-2.5 text-sm font-medium text-indigo-600"
>
  <Icon className="h-4.5 w-4.5 text-indigo-600" />
  Transakce
</a>
```

---

### 4. Header stránky

Header stránky je jednoduchý: nadpis vlevo, hlavní CTA vpravo.

```tsx
<div className="mb-6 flex items-center justify-between">
  <div>
    <h1 className="text-2xl font-bold tracking-tight text-gray-900">
      Transakce
    </h1>
  </div>

  <button className="inline-flex h-9 items-center gap-2 rounded-md bg-indigo-600 px-4 text-sm font-medium text-white shadow-sm transition-colors hover:bg-indigo-700 active:scale-[0.98]">
    <PlusIcon className="h-4 w-4" />
    Přidat transakci
  </button>
</div>
```

Pravidla:

- H1 je `text-2xl font-bold tracking-tight`.
- CTA tlačítko má výšku `h-9`.
- CTA není obří.
- CTA má jemný `shadow-sm`.
- Na stránce je pouze jedno hlavní CTA.
- Nepřidávej pod H1 vysvětlující text typu „Spravuj své finance“.
- Pokud je potřeba počet výsledků, patří až pod toolbar, ne pod H1.

---

### 5. Filter toolbar jako jedna karta

Filtry nikdy nepokládej volně na stránku. Musí být sjednocené v jedné bílé toolbar kartě.

```tsx
<div className="mb-4 rounded-xl border border-gray-200 bg-white p-3 shadow-sm">
  <div className="flex items-center gap-3">
    <div className="relative flex-1">
      <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />

      <input
        placeholder="Hledat transakce..."
        className="h-9 w-full rounded-md border border-gray-300 bg-white pl-9 pr-3 text-sm text-gray-900 placeholder:text-gray-400 transition-shadow focus:border-transparent focus:outline-none focus:ring-2 focus:ring-indigo-500"
      />
    </div>

    <select className="h-9 w-[110px] rounded-md border border-gray-300 bg-white px-3 text-sm text-gray-700 focus:border-transparent focus:outline-none focus:ring-2 focus:ring-indigo-500">
      <option>Vše</option>
    </select>

    <select className="h-9 w-[180px] rounded-md border border-gray-300 bg-white px-3 text-sm text-gray-700 focus:border-transparent focus:outline-none focus:ring-2 focus:ring-indigo-500">
      <option>Všechny kategorie</option>
    </select>

    <button className="inline-flex h-9 w-[140px] items-center justify-between rounded-md border border-gray-300 bg-white px-3 text-sm text-gray-700 transition-colors hover:bg-gray-50">
      květen 2026
      <CalendarIcon className="h-4 w-4 text-gray-500" />
    </button>
  </div>
</div>
```

Pravidla:

- Toolbar je jedna karta: `rounded-xl border border-gray-200 bg-white p-3 shadow-sm`.
- Search input je nejširší a používá `flex-1`.
- Selecty mají pevnou šířku.
- Všechny ovládací prvky mají stejnou výšku: `h-9`.
- Mezera mezi prvky je `gap-3`.
- Input má ikonku vlevo.
- Nepřidávej nad toolbar nadpis „Filtry“.
- Nepřidávej popis „Zúž seznam podle…“.
- Toolbar má působit jako jeden produktový ovládací panel.

Špatně:

```txt
❌ Hledání vlevo, selecty volně rozházené, každý bez společného wrapperu.
```

Správně:

```txt
✅ Jeden bílý toolbar, uvnitř search + select + select + date picker.
```

---

### 6. Počet výsledků

Počet výsledků je malé metadata mezi toolbarem a seznamem.

```tsx
<p className="mb-3 text-sm text-gray-500">
  Nalezeno 9 transakcí
</p>
```

Pravidla:

- Použij `text-sm text-gray-500`.
- Není to nadpis.
- Patří blízko seznamu.
- Popisuje aktuální výsledek filtrace.
- Nepiš „Zobrazuji seznam všech nalezených transakcí“.
- Krátké metadata působí víc prémiově než vysvětlovací věty.

---

### 7. Record card list

Seznam záznamů se u bohatých položek nezobrazuje jako tabulka, ale jako card-list.

Použij card-list, pokud položka obsahuje:

- název,
- datum,
- kategorii,
- hodnotu,
- stav,
- krátkou poznámku,
- akce.

```tsx
<div className="space-y-2.5">
  {/* Record cards */}
</div>
```

Pravidla:

- Použij `space-y-2.5` nebo `space-y-3`.
- Nepoužívej `space-y-5` ani větší mezery.
- Seznam má být kompaktní.
- Každá položka má být samostatná bílá karta.
- Karta nemá působit jako velký panel, ale jako elegantní řádek.

---

### 8. Record card anatomie

Výchozí record card:

```tsx
<div className="relative flex min-h-[66px] items-center rounded-xl border border-gray-200 bg-white py-3 pl-10 pr-4 shadow-sm transition-all duration-150 hover:border-gray-300 hover:shadow">
  <div className="absolute left-4 top-3.5 bottom-3.5 w-1.5 rounded-full bg-orange-500" />

  <div className="min-w-0 flex-1">
    <div className="flex items-center gap-2">
      <h3 className="truncate text-sm font-semibold text-gray-900">
        Restaurace Mama Roma
      </h3>

      <MessageSquareIcon className="h-3.5 w-3.5 shrink-0 text-gray-400" />
    </div>

    <div className="mt-1 flex items-center gap-2">
      <span className="text-xs text-gray-500 tabular-nums">
        10. 5. 2026
      </span>

      <span className="inline-flex items-center rounded-full bg-orange-100 px-2 py-0.5 text-xs font-medium text-orange-700">
        Jídlo & restaurace
      </span>
    </div>
  </div>

  <div className="ml-4 flex items-center gap-3">
    <div className="min-w-[112px] text-right text-sm font-semibold tabular-nums text-red-600">
      -480 Kč
    </div>

    <div className="flex items-center gap-1">
      <button
        aria-label="Upravit transakci"
        className="inline-flex h-8 w-8 items-center justify-center rounded-md text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
      >
        <PencilIcon className="h-4 w-4" />
      </button>

      <button
        aria-label="Smazat transakci"
        className="inline-flex h-8 w-8 items-center justify-center rounded-md text-gray-400 transition-colors hover:bg-red-50 hover:text-red-600"
      >
        <TrashIcon className="h-4 w-4" />
      </button>
    </div>
  </div>
</div>
```

Pravidla:

- Karta má `rounded-xl`.
- Karta má `border border-gray-200`.
- Karta má `shadow-sm`.
- Hover zvedne pouze jemně: `hover:border-gray-300 hover:shadow`.
- Výška je kompaktní: `min-h-[66px]`.
- Padding je `py-3 pl-10 pr-4`.
- Název je `text-sm font-semibold text-gray-900`.
- Metadata jsou `text-xs text-gray-500`.
- Částka je vpravo a má `min-w-[112px]`.
- Akční ikony jsou šedé a sekundární.
- Ikony se barevně „probudí“ až na hover.
- Nepoužívej `p-6` na record card. To je moc velké.
- Nepoužívej center layout. Položka se čte zleva doprava.

---

### 9. Barevné category čárky

Barevná čárka vlevo je důležitý vizuální signál. Musí být dostatečně viditelná, ale ne agresivní.

Správná čárka:

```tsx
<div className="absolute left-4 top-3.5 bottom-3.5 w-1.5 rounded-full bg-orange-500" />
```

Pravidla:

- Čárka má šířku `w-1.5`, tedy cca 6 px.
- Nepoužívej `w-1`, pokud vizuálně zaniká.
- Nepoužívej `w-2`, pokud začíná působit moc těžce.
- Čárka není nalepená na vnějším okraji karty.
- Čárka je odsazená přes `left-4`.
- Vertikálně nedosahuje úplně od kraje ke kraji.
- Použij `top-3.5 bottom-3.5`.
- Čárka má vždy `rounded-full`.
- Barva čárky odpovídá kategorii.
- Stejná kategorie má vždy stejnou barvu.
- Čárka nesmí být šedá.
- Čárka nesmí používat primární indigo pro všechny položky.

Špatně:

```tsx
<div className="absolute left-0 top-0 bottom-0 w-1 bg-orange-500" />
```

Proč špatně:

```txt
❌ nalepené na okraj
❌ působí jako error state nebo border systému
❌ méně prémiové
❌ horší vizuální odsazení
```

Správně:

```tsx
<div className="absolute left-4 top-3.5 bottom-3.5 w-1.5 rounded-full bg-orange-500" />
```

Proč správně:

```txt
✅ vypadá jako záměrný designový detail
✅ pomáhá rychlému skenování
✅ barva má jasnou funkci
✅ karta má vnitřní dech
```

---

### 10. Hezčí barvy kategorií

Kategorie nesmí používat náhodné základní barvy. Barvy musí být stabilní, příjemné a dobře čitelné.

Použij tuto paletu jako výchozí:

```tsx
const categoryColors = {
  "Jídlo & restaurace": {
    bar: "bg-orange-500",
    badgeBg: "bg-orange-100",
    badgeText: "text-orange-700",
    hex: "#f97316",
  },
  "Zábava": {
    bar: "bg-cyan-500",
    badgeBg: "bg-cyan-100",
    badgeText: "text-cyan-700",
    hex: "#06b6d4",
  },
  "Doprava": {
    bar: "bg-amber-500",
    badgeBg: "bg-amber-100",
    badgeText: "text-amber-700",
    hex: "#f59e0b",
  },
  "Zdraví": {
    bar: "bg-pink-500",
    badgeBg: "bg-pink-100",
    badgeText: "text-pink-700",
    hex: "#ec4899",
  },
  "Bydlení": {
    bar: "bg-violet-500",
    badgeBg: "bg-violet-100",
    badgeText: "text-violet-700",
    hex: "#8b5cf6",
  },
  "Mzda": {
    bar: "bg-emerald-500",
    badgeBg: "bg-emerald-100",
    badgeText: "text-emerald-700",
    hex: "#10b981",
  },
  "Freelance": {
    bar: "bg-indigo-500",
    badgeBg: "bg-indigo-100",
    badgeText: "text-indigo-700",
    hex: "#6366f1",
  },
  "Nákupy": {
    bar: "bg-sky-500",
    badgeBg: "bg-sky-100",
    badgeText: "text-sky-700",
    hex: "#0ea5e9",
  },
  "Vzdělání": {
    bar: "bg-purple-500",
    badgeBg: "bg-purple-100",
    badgeText: "text-purple-700",
    hex: "#a855f7",
  },
  "Ostatní": {
    bar: "bg-slate-500",
    badgeBg: "bg-slate-100",
    badgeText: "text-slate-700",
    hex: "#64748b",
  },
};
```

Pravidla:

- Nepoužívej pro všechny kategorie stejnou barvu.
- Nepoužívej příliš tmavé badge pozadí.
- Badge pozadí je vždy světlé: `*-100`.
- Badge text je vždy sytější: `*-700`.
- Levá čárka je vždy sytá: `*-500`.
- Příjmy/výdaje neřeší barva kategorie, ale barva částky.
- Kategorie „Mzda“ může být zelená, protože typicky odpovídá příjmu.
- Kategorie „Zdraví“ může být růžová/pink.
- Kategorie „Jídlo“ funguje nejlépe jako oranžová.
- Kategorie „Zábava“ funguje dobře jako cyan.
- Kategorie „Bydlení“ funguje dobře jako violet.

---

### 11. Badge polish

Badge musí být malé, barevné a čitelné. Nemá vypadat jako tlačítko.

```tsx
<span className="inline-flex items-center rounded-full bg-orange-100 px-2 py-0.5 text-xs font-medium text-orange-700">
  Jídlo & restaurace
</span>
```

Pravidla:

- Badge má vždy `rounded-full`.
- Badge používá `text-xs`.
- Badge používá `font-medium`.
- Badge padding: `px-2 py-0.5`.
- Badge pozadí je světlé.
- Badge text je sytější.
- Badge nepoužívá border.
- Badge nemá shadow.
- Badge není uppercase, pokud jde o kategorii.
- Badge nemá ikonu, pokud není potřeba.
- Badge má být jemný vizuální signál, ne hlavní obsah.

Volitelně badge s tečkou:

```tsx
<span className="inline-flex items-center gap-1.5 rounded-full bg-orange-100 px-2 py-0.5 text-xs font-medium text-orange-700">
  <span className="h-1.5 w-1.5 rounded-full bg-orange-500" />
  Jídlo & restaurace
</span>
```

Použij tečku pouze v případě, že badge bez tečky působí moc plochě. Pokud už existuje levá category čárka, badge tečka většinou není potřeba.

---

### 12. Barevná logika položek

Barva v record card má tři role:

```txt
1. Levá čárka = kategorie
2. Badge = kategorie
3. Částka = typ transakce
```

Pravidla:

- Výdaj je červený pouze v částce.
- Příjem je zelený pouze v částce.
- Kategorie má vlastní stabilní barvu.
- Nedávej badge „Výdaj“, pokud už je částka červená.
- Nedávej badge „Příjem“, pokud už je částka zelená.
- Nedělej všechny badges šedé.
- Nedělej všechny levé čárky indigo.
- Nepoužívej barvu jen dekorativně.
- Barva musí nést informaci.

Správně:

```txt
Restaurace Mama Roma
10. 5. 2026  [Jídlo & restaurace]          -480 Kč
```

Špatně:

```txt
Restaurace Mama Roma
10. 5. 2026  [Výdaj] [Jídlo & restaurace]  -480 Kč
```

Proč špatně:

```txt
❌ typ „Výdaj“ už říká červená částka
❌ badge navíc přidává šum
❌ horší skenování
```

---

### 13. Typografie v record card

Každý řádek má maximálně tři vizuální úrovně.

```txt
Úroveň 1: Název položky
Úroveň 2: Částka / hodnota
Úroveň 3: Metadata / datum / kategorie
```

Přesné třídy:

```txt
Název:       text-sm font-semibold text-gray-900
Částka:      text-sm font-semibold tabular-nums
Datum:       text-xs text-gray-500 tabular-nums
Badge:       text-xs font-medium
Ikony:       h-4 w-4 text-gray-400
Poznámka:    text-xs text-gray-500
```

Pravidla:

- Název nesmí být `text-base`, pokud jde o hustý seznam.
- Datum nesmí být stejně výrazné jako název.
- Částka má být výrazná, ale ne obří.
- Částka má být zarovnaná doprava.
- Používej `tabular-nums` pro částky i datum.
- Pokud je poznámka krátká, může být vedle badge.
- Pokud je poznámka dlouhá, zobraz jen ikonu poznámky a detail otevři po kliknutí.

---

### 14. Zarovnání částek

Částky musí tvořit vizuální sloupec vpravo.

```tsx
<div className="min-w-[112px] text-right text-sm font-semibold tabular-nums text-red-600">
  -480 Kč
</div>
```

Pravidla:

- Vždy `text-right`.
- Vždy `tabular-nums`.
- Vždy pevná minimální šířka: `min-w-[96px]` až `min-w-[128px]`.
- Pro běžné finance použij `min-w-[112px]`.
- Výdaje: `text-red-600`.
- Příjmy: `text-emerald-600`.
- Nula/neutrální: `text-gray-700`.
- Kladné hodnoty mají prefix `+`.
- Záporné hodnoty mají prefix `-`.
- Měna je na stejném řádku.
- Nepiš částky vlevo do textového bloku. Zhoršuje to skenování.

---

### 15. Row actions

Akce na řádku jsou sekundární. Uživatel je potřebuje, ale nemají soupeřit s daty.

```tsx
<div className="flex items-center gap-1">
  <button
    aria-label="Upravit"
    className="inline-flex h-8 w-8 items-center justify-center rounded-md text-gray-400 transition-colors hover:bg-gray-100 hover:text-gray-600"
  >
    <PencilIcon className="h-4 w-4" />
  </button>

  <button
    aria-label="Smazat"
    className="inline-flex h-8 w-8 items-center justify-center rounded-md text-gray-400 transition-colors hover:bg-red-50 hover:text-red-600"
  >
    <TrashIcon className="h-4 w-4" />
  </button>
</div>
```

Pravidla:

- Ikony jsou defaultně `text-gray-400`.
- Edit hover: `hover:bg-gray-100 hover:text-gray-600`.
- Delete hover: `hover:bg-red-50 hover:text-red-600`.
- Velikost tlačítka je `h-8 w-8`.
- Ikona je `h-4 w-4`.
- Nepoužívej barevné ikony defaultně.
- Nepoužívej textová tlačítka „Upravit“ a „Smazat“ přímo v řádku.
- Textové akce patří do detailu nebo dropdownu.
- Každé icon-only tlačítko musí mít `aria-label`.

---

### 16. Hover a active polish

Interakce musí být jemná, ne teatrální.

Record card hover:

```tsx
className="transition-all duration-150 hover:border-gray-300 hover:shadow"
```

Button hover:

```tsx
className="transition-colors duration-150"
```

CTA active:

```tsx
className="active:scale-[0.98]"
```

Pravidla:

- Nepoužívej silné shadow na hover.
- Nepoužívej scale efekt na celé karty v seznamu.
- Nepoužívej animace delší než `150ms`.
- Hover má pouze potvrdit interaktivitu.
- Hover nesmí změnit layout.
- Hover nesmí posunout text.
- Hover nesmí měnit velikost prvku.

---

### 17. Hustota seznamu

Claude-like seznam je kompaktní, ale ne namačkaný.

Doporučené hodnoty:

```txt
Výška record card:        min-h-[66px] až min-h-[72px]
Padding svisle:           py-3
Padding vlevo:            pl-10
Padding vpravo:           pr-4
Mezera mezi kartami:      space-y-2.5 nebo space-y-3
Radius karty:             rounded-xl
Levá čárka:               w-1.5, left-4, top-3.5, bottom-3.5
Akční ikony:              h-8 w-8
```

Špatně:

```txt
❌ min-h-[92px]
❌ p-6
❌ space-y-5
❌ text-base všude
❌ velké badge
```

Správně:

```txt
✅ min-h-[66px]
✅ py-3 pl-10 pr-4
✅ space-y-2.5
✅ text-sm title
✅ text-xs metadata
```

---

### 18. Tichost UI

UI má být sebevědomé. Nemusí všechno vysvětlovat.

Odstraň tyto zbytečnosti:

```txt
❌ Nadpis „Filtry“
❌ Text „Zúž seznam podle názvu, typu, kategorie a měsíce“
❌ Popis pod H1 „Spravuj své příjmy a výdaje“
❌ Subtitle pod logem „Osobní finance“
❌ Badge „Výdaj“, když je částka červená
❌ Badge „Příjem“, když je částka zelená
❌ Popisek „Akce“ před ikonami edit/delete
❌ Popis „Klikni na tužku pro úpravu“
```

Nahraď je lepším designem:

```txt
✅ Search input s ikonou lupy
✅ Selecty s jasnou hodnotou
✅ Barva částky říká příjem/výdaj
✅ Kategorie má badge a levou čárku
✅ Ikony edit/delete jsou standardně srozumitelné
✅ Tooltip/aria-label řeší přístupnost
```

---

### 19. Empty state

Prázdný stav musí být klidný, centrovaný a akční.

```tsx
<div className="rounded-xl border border-dashed border-gray-300 bg-white px-6 py-12 text-center">
  <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-indigo-50">
    <ReceiptIcon className="h-6 w-6 text-indigo-600" />
  </div>

  <h3 className="text-sm font-semibold text-gray-900">
    Zatím žádné transakce
  </h3>

  <p className="mx-auto mt-1 max-w-sm text-sm text-gray-500">
    Přidej první transakci a začni sledovat své finance.
  </p>

  <button className="mt-5 inline-flex h-9 items-center gap-2 rounded-md bg-indigo-600 px-4 text-sm font-medium text-white shadow-sm hover:bg-indigo-700">
    <PlusIcon className="h-4 w-4" />
    Přidat transakci
  </button>
</div>
```

Pravidla:

- Empty state má dashed border.
- Ikona je v jemném barevném kruhu.
- Nadpis je krátký.
- Popis je maximálně jedna věta.
- CTA je stejné jako hlavní akce stránky.
- Nepiš „No data“.
- Nepoužívej velkou ilustraci, pokud aplikace není marketingová.

---

### 20. Loading state

Loading stav má zachovat layout.

```tsx
<div className="space-y-2.5">
  {Array.from({ length: 8 }).map((_, index) => (
    <div
      key={index}
      className="relative flex min-h-[66px] items-center rounded-xl border border-gray-200 bg-white py-3 pl-10 pr-4 shadow-sm"
    >
      <div className="absolute left-4 top-3.5 bottom-3.5 w-1.5 rounded-full bg-gray-200" />

      <div className="min-w-0 flex-1 animate-pulse">
        <div className="h-4 w-40 rounded bg-gray-200" />
        <div className="mt-2 flex items-center gap-2">
          <div className="h-3 w-20 rounded bg-gray-100" />
          <div className="h-5 w-24 rounded-full bg-gray-100" />
        </div>
      </div>

      <div className="ml-4 h-4 w-24 animate-pulse rounded bg-gray-200" />
    </div>
  ))}
</div>
```

Pravidla:

- Skeleton má stejnou výšku jako finální record card.
- Skeleton má stejný layout jako finální data.
- Nepoužívej fullscreen spinner pro seznam.
- Spinner je vhodný pro tlačítko, ne pro celou stránku se seznamem.
- Loading nesmí způsobit layout shift.

---

### 21. Detailní rozdíl: běžné GPT UI vs Claude-grade UI

```txt
Běžné GPT UI:
- komponenty jsou technicky správně
- stránka ale působí rozpadle
- inputy jsou volně položené
- karty jsou moc vysoké
- barvy kategorií jsou slabé
- akce jsou příliš viditelné
- chybí jednotná kompozice

Claude-grade UI:
- stránka má jasný layout shell
- toolbar je jedna karta
- seznam má přesnou hustotu
- každá karta má silnou, hezkou category čárku
- badges mají příjemnou stabilní barvu
- částky tvoří sloupec
- akce jsou potlačené
- UI nepotřebuje vysvětlovací texty
```

---

### 22. Mini checklist před dokončením obrazovky

Před dokončením každé seznamové stránky zkontroluj:

```txt
[ ] Hlavní obsah má max šířku cca 920–1040 px.
[ ] Filtry jsou v jedné bílé toolbar kartě.
[ ] Všechny prvky toolbaru mají stejnou výšku h-9.
[ ] Search input je nejširší prvek v toolbaru.
[ ] Počet výsledků je malé metadata mezi toolbar a seznamem.
[ ] Seznam používá card-list, ne tabulku, pokud položky obsahují bohatší metadata.
[ ] Record cards jsou kompaktní, cca 66–72 px vysoké.
[ ] Levá category čárka je tlustší: w-1.5.
[ ] Category čárka je odsazená: left-4, top-3.5, bottom-3.5.
[ ] Category čárka má rounded-full.
[ ] Badge má barvu podle kategorie.
[ ] Badge nepoužívá šedou, pokud kategorie má vlastní barvu.
[ ] Výdaj/příjem je vyjádřen barvou částky, ne extra badgem.
[ ] Částky jsou zarovnané doprava a mají tabular-nums.
[ ] Akční ikony jsou defaultně šedé.
[ ] Delete ikona zčervená až na hover.
[ ] UI neobsahuje zbytečné vysvětlující texty.
[ ] Stránka působí jako hotový SaaS produkt, ne jako defaultní Tailwind layout.
```

Pokud alespoň 3 body neplatí, obrazovku přepracuj.

---

### 23. Finální instrukce pro AI generování

Když generuješ UI podle tohoto design systému, neber tuto sekci jako inspiraci. Ber ji jako přesný layoutový předpis.

Priorita:

```txt
1. Nejdřív správná kompozice stránky.
2. Potom správný toolbar.
3. Potom správná hustota seznamu.
4. Potom category čárky a badges.
5. Potom hover/focus polish.
6. Až nakonec drobné dekorace.
```

Nikdy nezačínej dekoracemi. Prémiový vzhled vzniká z proporcí, mezer, hierarchie a konzistence — ne z gradientů, velkých stínů nebo efektů.

Výsledek má působit takto:

```txt
„Tohle je jednoduchá, hotová, sebevědomá SaaS aplikace.“
```

Ne takto:

```txt
„Tohle je rychle vygenerovaný dashboard s pár Tailwind komponentami.“
```

---

## 50. Claude-grade analytické, rozpočtové a KPI karty

Tato sekce definuje přesné rozložení pro stránky, které zobrazují analytické karty, rozpočty, limity, KPI, usage tracking, projektové statistiky, výkon kategorií, produktové metriky nebo jiné hodnoty s průběhem.

Použij tento pattern vždy, když stránka obsahuje více menších karet typu:

- rozpočtové kategorie,
- limity a čerpání,
- KPI metriky,
- usage / token tracking,
- storage usage,
- projektové kapacity,
- stav objednávek,
- finanční přehledy,
- statistiky podle kategorií,
- výkon kampaní,
- cíle a progress.

Cíl: výsledek musí působit jako hotová moderní SaaS aplikace. Karty mají být kompaktní, přehledné, přesně zarovnané a vizuálně klidné. Ne jako velké roztažené boxy s náhodnými progress bary.

---

### 50.1 Hlavní princip

Analytické karty nejsou landing-page cards. Jsou to pracovní produktové komponenty.

Správný pocit:

```txt
✅ kompaktní karty
✅ menší výška
✅ přesný grid
✅ klidné progress bary
✅ jasná hierarchie textu
✅ akce vpravo nahoře
✅ žádné zbytečné warning boxy
✅ čísla jsou formátovaná
✅ barvy jsou stabilní a sémantické
✅ stránka má hodně vzduchu, ale karty nejsou nafouknuté
```

Špatný pocit:

```txt
❌ obří karty s velkým prázdným místem
❌ dvousloupcový grid, když by fungoval třísloupcový
❌ velké warning boxy uvnitř každé karty
❌ neformátované hodnoty typu 12000
❌ progress bar přes celou obří kartu
❌ příliš výrazná červená pro běžný warning
❌ levá barevná čára u všech analytických karet
❌ moc velký padding
❌ metadata jsou stejně výrazná jako hlavní hodnota
```

---

### 50.2 Page layout pro analytickou stránku

Analytická stránka má používat stejný shell jako ostatní SaaS stránky: sidebar vlevo, hlavní obsah centrovaný.

```tsx
<div className="min-h-screen bg-gray-50 text-gray-900">
  <aside className="fixed inset-y-0 left-0 w-56 bg-white border-r border-gray-200">
    {/* Sidebar */}
  </aside>

  <main className="ml-56 min-h-screen">
    <div className="mx-auto max-w-[1120px] px-8 py-8">
      {/* Page content */}
    </div>
  </main>
</div>
```

Pravidla:

- Pro analytické karty používej větší container než pro jednoduchý seznam.
- Doporučená šířka: `max-w-[1040px]` až `max-w-[1120px]`.
- Nepoužívej zbytečně úzký container, pokud je na stránce grid karet.
- Nepoužívej full-width layout přes celou obrazovku.
- Stránka má mít vizuální těžiště uprostřed.
- Pozadí stránky je vždy jemné `bg-gray-50`.
- Karty jsou bílé: `bg-white`.

---

### 50.3 Header analytické stránky

Header má být jednoduchý a nízký. Vlevo název stránky, vpravo časové ovládání nebo hlavní akce.

```tsx
<div className="mb-6 flex items-center justify-between">
  <div>
    <h1 className="text-2xl font-bold tracking-tight text-gray-900">
      Rozpočet
    </h1>
  </div>

  <div className="flex items-center gap-3">
    <button className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-gray-200 bg-white text-gray-500 shadow-sm transition-colors hover:bg-gray-50 hover:text-gray-700">
      <ChevronLeftIcon className="h-4 w-4" />
    </button>

    <div className="min-w-[120px] text-center text-sm font-medium text-gray-700 tabular-nums">
      květen 2026
    </div>

    <button className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-gray-200 bg-white text-gray-500 shadow-sm transition-colors hover:bg-gray-50 hover:text-gray-700">
      <ChevronRightIcon className="h-4 w-4" />
    </button>
  </div>
</div>
```

Pravidla:

- H1 je vlevo.
- Časové ovládání je vpravo.
- Pokud stačí jednoduchý přepínač období, nepoužívej velkou kartu s inputem.
- Nepřidávej pod H1 zbytečný subtitle typu „8 výdajových kategorií“, pokud stránka už sama obsahuje karty.
- Pokud je počet důležitý, zobraz ho jemně jako metadata, ne jako druhý nadpis.
- Ovládání období má být kompaktní: šipka vlevo, aktuální období, šipka vpravo.
- Tlačítka období mají `h-9 w-9`.
- Aktuální období má `text-sm font-medium`.

---

### 50.4 Kdy použít date picker a kdy month switcher

Použij month switcher, pokud uživatel typicky prochází období po měsících, týdnech nebo kvartálech.

```txt
✅ rozpočet podle měsíců
✅ měsíční reporting
✅ usage za měsíc
✅ přehled kampaní podle období
✅ KPI dashboard s časovým obdobím
```

Použij date picker / select kartu pouze tehdy, když uživatel potřebuje přesný výběr rozsahu.

```txt
✅ vlastní datum od–do
✅ filtrování transakcí
✅ audit log
✅ export dat
✅ analytika s libovolným rozsahem
```

Špatně:

```txt
❌ Obří karta „Období“ jen kvůli výběru jednoho měsíce.
```

Správně:

```txt
✅ Kompaktní month switcher vpravo nahoře.
```

---

### 50.5 Grid analytických karet

Analytické karty nejčastěji používej ve 3 sloupcích na desktopu.

```tsx
<div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
  {/* KPI cards */}
</div>
```

Pravidla:

- Desktop: preferuj `xl:grid-cols-3`.
- Tablet: `md:grid-cols-2`.
- Mobil: `grid-cols-1`.
- Mezera mezi kartami je `gap-4`.
- Nepoužívej `gap-6`, pokud karty nejsou velké detailní panely.
- Třísloupcový grid často působí prémiověji než dvousloupcový, protože karty jsou kompaktnější.
- Dvousloupcový grid používej jen pro velmi obsahově bohaté karty.
- Karty v jednom gridu musí mít podobnou výšku.

---

### 50.6 Základní analytická karta

Výchozí karta má být kompaktní, nízká a čitelná.

```tsx
<div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm transition-all duration-150 hover:border-gray-300 hover:shadow">
  <div className="mb-3 flex items-start justify-between gap-3">
    <div className="flex min-w-0 items-center gap-2">
      <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-orange-500" />

      <h3 className="truncate text-sm font-semibold text-gray-900">
        Jídlo & restaurace
      </h3>
    </div>

    <button className="shrink-0 text-xs font-medium text-indigo-600 transition-colors hover:text-indigo-700">
      Upravit
    </button>
  </div>

  <div className="mb-2 text-sm text-gray-600 tabular-nums">
    1 730 Kč / 5 000 Kč utraceno
  </div>

  <div className="h-2 overflow-hidden rounded-full bg-gray-100">
    <div className="h-full rounded-full bg-emerald-500" style={{ width: '35%' }} />
  </div>
</div>
```

Pravidla:

- Karta má `rounded-xl`.
- Border je `border-gray-200`.
- Stín je pouze `shadow-sm`.
- Padding je `p-4`, ne `p-6`.
- Výška má přirozeně vycházet přibližně na 96–118 px.
- Header karty má název vlevo a akci vpravo.
- Kategorie se označuje barevnou tečkou, ne vždy levou čárou.
- Progress bar je nízký: `h-2`.
- Progress track je `bg-gray-100`.
- Progress fill má `rounded-full`.

---

### 50.7 Tečka vs levá čára

U analytických / KPI karet preferuj barevnou tečku místo levé čáry.

Tečka je lepší, pokud:

```txt
✅ karta je malá
✅ karta je součást gridu
✅ barva označuje kategorii
✅ nechceš, aby karta působila jako alert
✅ každá karta má podobnou strukturu
```

Levá čára je lepší, pokud:

```txt
✅ jde o seznam řádků
✅ uživatel rychle skenuje dlouhý list
✅ karta má horizontální řádkový charakter
✅ kategorie musí být vidět při rychlém scrollování
```

Pro analytické karty:

```tsx
<span className="h-2.5 w-2.5 shrink-0 rounded-full bg-orange-500" />
```

Pro seznamové řádky:

```tsx
<div className="absolute left-4 top-3.5 bottom-3.5 w-1.5 rounded-full bg-orange-500" />
```

Pravidla:

- Nepoužívej levou čáru automaticky všude.
- U malých grid karet působí tečka čistěji a moderněji.
- Tečka má být `h-2.5 w-2.5`.
- Tečka má být před názvem kategorie.
- Tečka a progress bar používají stejnou category barvu nebo sémantickou progress barvu.

---

### 50.8 Akce v kartě

Akce v analytické kartě má být textová, malá a vpravo nahoře.

```tsx
<button className="text-xs font-medium text-indigo-600 transition-colors hover:text-indigo-700">
  Upravit
</button>
```

Varianty:

```txt
Upravit
Nastavit limit
Zobrazit detail
Spravovat
```

Pravidla:

- Akce je `text-xs font-medium`.
- Akce je vpravo nahoře.
- Akce není button s pozadím.
- Akce není ikonové tlačítko, pokud text lépe vysvětluje kontext.
- Pokud karta nemá nastavený limit, akce může být „Nastavit limit“.
- Pokud karta má limit, akce může být „Upravit“.
- Nepoužívej velké CTA uvnitř každé karty.
- Hlavní CTA stránky smí být jen jedno.

---

### 50.9 Textová hierarchie v kartě

Analytická karta má mít jasnou tříúrovňovou hierarchii.

```txt
Úroveň 1: název metriky / kategorie
Úroveň 2: aktuální hodnota a limit
Úroveň 3: progress / stav
```

Doporučené třídy:

```txt
Název:        text-sm font-semibold text-gray-900
Akce:         text-xs font-medium text-indigo-600
Hodnota:      text-sm text-gray-600 tabular-nums
Sekundární:   text-xs text-gray-500
Progress:     h-2 rounded-full
```

Pravidla:

- Název není `text-lg`.
- Hodnota není obří, pokud karta není hlavní KPI karta.
- Metadata nejsou bold.
- Akce není větší než název.
- V kartě nepoužívej více než 2 velikosti textu.
- Nepoužívej čísla bez jednotek.
- Nepoužívej neformátované hodnoty.

Špatně:

```txt
12000
4500
2500
```

Správně:

```txt
12 000 Kč
4 500 Kč
2 500 Kč
```

Ještě lepší v progress kontextu:

```txt
1 730 Kč / 5 000 Kč utraceno
550 Kč / 2 000 Kč utraceno
0 Kč utraceno (bez limitu)
```

---

### 50.10 Formátování čísel

Všechna čísla musí být čitelná a lokálně formátovaná.

Pravidla:

- Používej mezery v tisících: `12 000 Kč`.
- Nepiš `12000`.
- Nepiš `12,000 Kč` v českém UI.
- Měna je vždy za číslem.
- Používej `tabular-nums`.
- Pro procenta používej mezeru před `%`: `80 %`.
- Pro desetinná čísla v češtině používej čárku: `12,5 %`.

Doporučený formatter:

```tsx
const formatCurrency = (value: number) =>
  new Intl.NumberFormat("cs-CZ", {
    style: "currency",
    currency: "CZK",
    maximumFractionDigits: 0,
  }).format(value);
```

Pro zkrácený zápis bez `,00`:

```tsx
const formatCzk = (value: number) =>
  `${new Intl.NumberFormat("cs-CZ", {
    maximumFractionDigits: 0,
  }).format(value)} Kč`;
```

---

### 50.11 Progress bar pravidla

Progress bar má být jemný, nízký a přesný.

```tsx
<div className="h-2 overflow-hidden rounded-full bg-gray-100">
  <div
    className="h-full rounded-full bg-emerald-500 transition-all duration-300"
    style={{ width: `${Math.min(progress, 100)}%` }}
  />
</div>
```

Pravidla:

- Výška progress baru: `h-2`.
- Nepoužívej `h-3` nebo větší, pokud nejde o hlavní hero metriku.
- Track je `bg-gray-100`.
- Fill je `rounded-full`.
- Fill má `transition-all duration-300`.
- Progress nesmí přesáhnout 100 % vizuálně.
- Pokud je hodnota přes limit, bar zůstává max 100 %, ale stav se vyjádří barvou/textem.
- Nepoužívej ostré rohy.
- Nepoužívej progress bar bez textové hodnoty.
- Nepoužívej příliš tmavý track.

---

### 50.12 Barvy progressu podle stavu

Progress bar nemá vždy kopírovat kategorii. U limitů často dává větší smysl sémantická barva podle stavu.

Doporučená logika:

```txt
0–69 %      → emerald / pozitivní stav
70–89 %     → amber / pozor
90–100 %    → orange / velmi blízko limitu
100 %+      → red / překročeno
```

Třídy:

```tsx
function getProgressColor(percent: number) {
  if (percent >= 100) return "bg-red-500";
  if (percent >= 90) return "bg-orange-500";
  if (percent >= 70) return "bg-amber-500";
  return "bg-emerald-500";
}
```

Pravidla:

- Kategorie je tečka.
- Stav čerpání je progress bar.
- Nepleť category barvu a stavovou barvu, pokud by to mátlo.
- Pokud aplikace sleduje jen kategorii, progress může mít category barvu.
- Pokud aplikace sleduje limit/riziko, progress má sémantickou barvu.
- Červená se používá až pro skutečně špatný stav, ne pro běžné čerpání.

---

### 50.13 Warning stav bez velkého boxu

Nevkládej do každé karty velký žlutý warning box. V malých analytických kartách působí těžce a rozbíjí grid.

Špatně:

```tsx
<div className="mt-4 rounded-lg bg-amber-50 p-3 text-sm font-medium text-amber-700">
  Pozor, překročeno 80 % limitu.
</div>
```

Správně:

```tsx
<p className="mt-2 text-xs font-medium text-amber-600">
  Blíží se limitu
</p>
```

Nebo:

```tsx
<p className="mt-2 text-xs font-medium text-red-600">
  Limit překročen o 650 Kč
</p>
```

Pravidla:

- Pro lehké upozornění použij malý text pod progress barem.
- Pro vážný stav použij červený text, ne obří box.
- Warning box používej jen u detailních karet nebo globálních alertů.
- Neopakuj stejný warning box ve více kartách.
- Stav musí být krátký: max 3–5 slov.
- Pokud je potřeba detail, otevře se po kliknutí na kartu nebo v detailu.

Doporučené texty:

```txt
70–89 %:   Blíží se limitu
90–99 %:   Téměř vyčerpáno
100 %+ :   Limit překročen
Bez limitu: Bez nastaveného limitu
```

---

### 50.14 Karty bez limitu

Karta bez limitu nemá mít prázdný progress bar, pokud by to vypadalo jako chyba.

Varianta A — bez progress baru:

```tsx
<div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
  <div className="mb-3 flex items-start justify-between gap-3">
    <div className="flex min-w-0 items-center gap-2">
      <span className="h-2.5 w-2.5 rounded-full bg-lime-500" />
      <h3 className="truncate text-sm font-semibold text-gray-900">
        Oblečení
      </h3>
    </div>

    <button className="text-xs font-medium text-indigo-600 hover:text-indigo-700">
      Nastavit limit
    </button>
  </div>

  <div className="text-sm text-gray-600 tabular-nums">
    0 Kč utraceno (bez limitu)
  </div>
</div>
```

Varianta B — jemný disabled progress:

```tsx
<div className="mt-2 h-2 overflow-hidden rounded-full bg-gray-100">
  <div className="h-full w-0 rounded-full bg-gray-200" />
</div>
```

Pravidla:

- Pokud limit neexistuje, neukazuj falešný limit.
- Text má být „0 Kč utraceno (bez limitu)“.
- Akce vpravo má být „Nastavit limit“.
- Nepiš `0 Kč z 0 Kč`.
- Nepiš `NaN %`.
- Nepoužívej červenou/amber pro chybějící limit.
- Chybějící limit je neutrální stav.

---

### 50.15 Kategorie a barvy v analytických kartách

Používej stabilní, příjemnou paletu kategorií.

```tsx
const categoryColors = {
  "Jídlo & restaurace": {
    dot: "bg-orange-500",
    softBg: "bg-orange-50",
    text: "text-orange-700",
    hex: "#f97316",
  },
  "Doprava": {
    dot: "bg-amber-500",
    softBg: "bg-amber-50",
    text: "text-amber-700",
    hex: "#f59e0b",
  },
  "Bydlení": {
    dot: "bg-violet-500",
    softBg: "bg-violet-50",
    text: "text-violet-700",
    hex: "#8b5cf6",
  },
  "Zdraví": {
    dot: "bg-pink-500",
    softBg: "bg-pink-50",
    text: "text-pink-700",
    hex: "#ec4899",
  },
  "Zábava": {
    dot: "bg-cyan-500",
    softBg: "bg-cyan-50",
    text: "text-cyan-700",
    hex: "#06b6d4",
  },
  "Oblečení": {
    dot: "bg-lime-500",
    softBg: "bg-lime-50",
    text: "text-lime-700",
    hex: "#84cc16",
  },
  "Vzdělání": {
    dot: "bg-blue-500",
    softBg: "bg-blue-50",
    text: "text-blue-700",
    hex: "#3b82f6",
  },
  "Ostatní": {
    dot: "bg-slate-500",
    softBg: "bg-slate-50",
    text: "text-slate-700",
    hex: "#64748b",
  },
};
```

Pravidla:

- Kategorie má stabilní barvu napříč aplikací.
- Kategorie používá tečku v headeru karty.
- Progress bar může být category barva jen pokud nejde o rizikový limit.
- Pokud jde o riziko/limit, progress bar má stavovou barvu.
- Nepoužívej náhodné barvy podle pořadí renderu.
- Barva se musí vázat na kategorii nebo stav, ne na náhodu.

---

### 50.16 Rozměry analytických karet

Doporučené hodnoty:

```txt
Karta:
- padding: p-4
- radius: rounded-xl
- border: border-gray-200
- shadow: shadow-sm
- min-height: cca 96–118 px

Grid:
- gap: gap-4
- desktop: 3 sloupce
- tablet: 2 sloupce
- mobil: 1 sloupec

Header karty:
- margin-bottom: mb-3
- dot: h-2.5 w-2.5
- title: text-sm font-semibold
- action: text-xs font-medium

Progress:
- height: h-2
- track: bg-gray-100
- fill: rounded-full
```

Špatně:

```txt
❌ p-6 pro malé KPI karty
❌ min-h-[160px]
❌ gap-6 u hustého dashboardu
❌ progress h-3 nebo h-4
❌ velký warning box v každé kartě
```

Správně:

```txt
✅ p-4
✅ kompaktní výška
✅ gap-4
✅ progress h-2
✅ krátký stavový text
```

---

### 50.17 Kdy použít velkou kartu

Velkou kartu používej pouze tehdy, když obsahuje více vrstev informací:

```txt
✅ graf
✅ tabulku
✅ detailní rozpad hodnot
✅ více akcí
✅ trend v čase
✅ porovnání období
```

Velká karta:

```tsx
<div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
  {/* chart, table, details */}
</div>
```

Pravidla:

- Velká karta může mít `p-6`.
- Malá KPI karta má `p-4`.
- Nemíchej v jednom gridu malé a velké karty bez promyšleného layoutu.
- Pokud je obsah jen název, hodnota a progress, karta má být malá.

---

### 50.18 Obecný KPI card pattern

Pro obecné KPI bez progress baru:

```tsx
<div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
  <div className="mb-2 flex items-center justify-between gap-3">
    <span className="text-sm font-medium text-gray-500">
      Celkové příjmy
    </span>

    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-50">
      <TrendingUpIcon className="h-4 w-4 text-emerald-600" />
    </div>
  </div>

  <div className="text-2xl font-bold tracking-tight text-gray-900 tabular-nums">
    45 000 Kč
  </div>

  <div className="mt-1 text-xs text-gray-500">
    +12,5 % oproti minulému měsíci
  </div>
</div>
```

Pravidla:

- KPI value může být větší: `text-2xl font-bold`.
- KPI label je `text-sm font-medium text-gray-500`.
- Ikona je v jemném barevném kontejneru.
- Nepoužívej `text-3xl`, pokud je na stránce hodně KPI karet.
- V hustém dashboardu preferuj `text-2xl`.

---

### 50.19 Detailní srovnání: méně prémiové vs Claude-grade

Méně prémiové analytické UI:

```txt
- dvousloupcový grid je moc široký
- každá karta je moc vysoká
- padding je příliš velký
- limit je zobrazen jako holé číslo
- progress bary jsou moc dominantní
- upozornění jsou velké boxy
- období je zbytečně velká samostatná karta
- karty vypadají jako generické panely
```

Claude-grade analytické UI:

```txt
- třísloupcový grid
- karty jsou nižší a přesnější
- padding je kompaktní
- čísla jsou součástí věty
- progress bary jsou jemné
- upozornění jsou krátký stavový text
- období je kompaktní switcher vpravo nahoře
- akce je malý textový link v kartě
- karty působí jako produktová komponenta, ne jako demo blok
```

---

### 50.20 Checklist pro analytické / rozpočtové stránky

Před dokončením stránky zkontroluj:

```txt
[ ] Hlavní obsah má vhodnou max šířku cca 1040–1120 px.
[ ] Header má H1 vlevo a ovládání období/akci vpravo.
[ ] Období není zbytečně velká samostatná karta, pokud stačí month switcher.
[ ] Grid používá na desktopu 3 sloupce, pokud to obsah dovoluje.
[ ] Mezera mezi kartami je gap-4.
[ ] Malé analytické karty používají p-4, ne p-6.
[ ] Karty jsou kompaktní, ne nafouknuté.
[ ] Kategorie je označena barevnou tečkou.
[ ] Tečka má h-2.5 w-2.5.
[ ] Akce v kartě je malý textový link vpravo nahoře.
[ ] Čísla jsou formátovaná: 12 000 Kč, ne 12000.
[ ] Hodnota a limit jsou v jedné čitelné větě.
[ ] Progress bar má h-2.
[ ] Progress track je bg-gray-100.
[ ] Progress fill je rounded-full.
[ ] Červená se používá jen pro skutečně špatný stav.
[ ] Warning není obří box uvnitř každé malé karty.
[ ] Karty bez limitu zobrazují neutrální text a akci „Nastavit limit“.
[ ] Stránka působí jako hotový SaaS produkt, ne jako sada defaultních Tailwind karet.
```

Pokud alespoň 3 body neplatí, obrazovku přepracuj.

---

### 50.21 Finální instrukce pro AI generování

Když generuješ analytickou, rozpočtovou nebo KPI stránku, postupuj podle této priority:

```txt
1. Nejdřív vyber správný container a grid.
2. Potom vytvoř čistý header s kompaktním ovládáním období.
3. Potom navrhni malé, přesné karty.
4. Potom nastav textovou hierarchii.
5. Potom formátuj čísla.
6. Potom doplň progress bary.
7. Potom nastav category barvy a stavové barvy.
8. Až nakonec řeš hover, stíny a drobné efekty.
```

Nikdy nezačínej dekoracemi. Prémiový vzhled vzniká hlavně z přesných rozměrů, správného gridu, kompaktních karet, dobrého formátování hodnot a klidné hierarchie.

Výsledek má působit takto:

```txt
„Tohle je čistý produktový dashboard, který bych čekal v moderní SaaS aplikaci.“
```

Ne takto:

```txt
„Tohle jsou velké vygenerované karty s progress bary.“
```

---

## 51. Claude-grade dashboard sekce: grafy, KPI karty a poslední záznamy

Tato sekce definuje přesné chování pro dashboardy, které kombinují:

- horní KPI/statistické karty,
- grafy,
- přehled kategorií,
- poslední záznamy,
- rychlé tabulky,
- finance / usage / projekty / objednávky / analytiku.

Cíl: dashboard musí působit jako hotový moderní SaaS produkt. Musí mít klidnou Claude-like kompozici, ale zároveň může používat výraznější category signály jako barevné čárky na začátku řádků, pokud pomáhají rychlému skenování.

---

### 51.1 Hlavní princip dashboardu

Dashboard není jen sada karet pod sebou. Je to úvodní přehled, který musí uživateli během pár sekund říct:

```txt
1. Jaký je aktuální stav?
2. Co se změnilo?
3. Kde je problém nebo příležitost?
4. Kam kliknout dál?
```

Správný pocit:

```txt
✅ nahoře jasné KPI karty
✅ pod nimi grafy v čistých kartách
✅ dole poslední záznamy nebo důležitý seznam
✅ kategorie jsou barevně jasné, ale ne hlučné
✅ grafy jsou přehledné a nepůsobí defaultně
✅ poslední záznamy jsou kompaktní
✅ čárky vlevo pomáhají skenování řádků
✅ badges kategorií jsou hezké jako v prémiové SaaS aplikaci
```

Špatný pocit:

```txt
❌ grafy jsou první věc na stránce bez KPI kontextu
❌ donut chart je moc velký a legenda je chaotická
❌ line chart má špatně čitelnou osu
❌ seznam je vložený do obří karty s moc velkým prázdným místem
❌ kategorie jsou barevně náhodné
❌ badges vypadají jako laciné štítky
❌ čárky vlevo jsou moc tenké, nalepené nebo nesouvisí s kategorií
```

---

### 51.2 Doporučená struktura dashboardu

Výchozí dashboard layout:

```tsx
<div className="mx-auto max-w-[1120px] px-8 py-8">
  {/* 1. Header */}
  <div className="mb-6">
    <h1 className="text-2xl font-bold tracking-tight text-gray-900">
      Dashboard
    </h1>
  </div>

  {/* 2. KPI row */}
  <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-3">
    {/* KPI cards */}
  </div>

  {/* 3. Charts */}
  <div className="mb-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
    {/* Chart cards */}
  </div>

  {/* 4. Recent records */}
  <div>
    {/* Recent list / table card */}
  </div>
</div>
```

Pravidla:

- Dashboard má používat `max-w-[1040px]` až `max-w-[1120px]`.
- Nepoužívej full-width layout.
- Sekce odděluj pomocí `mb-6`.
- Grid mezera je `gap-4`, ne `gap-8`.
- Dashboard musí mít vizuální rytmus: KPI → grafy → poslední záznamy.
- Pokud dashboard nemá KPI karty, působí méně hotově.

---

### 51.3 Horní KPI karty

KPI karty nahoře dávají dashboardu okamžitý kontext. Mají být větší než běžné malé karty, ale pořád klidné.

```tsx
<div className="rounded-xl border border-indigo-100 bg-indigo-50/70 p-5 shadow-sm">
  <div className="mb-4 flex items-start justify-between">
    <div className="text-sm font-medium text-gray-600">
      Saldo
    </div>

    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-white/70 text-indigo-600 shadow-sm">
      <WalletIcon className="h-4 w-4" />
    </div>
  </div>

  <div className="text-2xl font-bold tracking-tight text-indigo-600 tabular-nums">
    38 901 Kč
  </div>

  <div className="mt-1 text-xs text-gray-500">
    Aktuální měsíc
  </div>
</div>
```

Pravidla:

- KPI karta má `p-5`.
- KPI hodnota je `text-2xl font-bold tracking-tight`.
- Label je `text-sm font-medium text-gray-600`.
- Kontext je `text-xs text-gray-500`.
- Ikona je v malém světlém kontejneru.
- KPI karty mohou mít jemné barevné pozadí: `indigo-50`, `emerald-50`, `red-50`.
- Nepoužívej syté barevné pozadí.
- Nepoužívej velké gradienty.
- Nepoužívej `text-4xl`, pokud nejsi na landing page.

Doporučené barvy:

```txt
Primární / saldo / hlavní stav:     bg-indigo-50/70, text-indigo-600
Pozitivní / příjmy / růst:          bg-emerald-50/70, text-emerald-600
Negativní / výdaje / pokles:        bg-red-50/70, text-red-600
Varování / riziko:                  bg-amber-50/70, text-amber-700
Neutrální / počet / objem:          bg-slate-50, text-slate-700
```

---

### 51.4 Chart cards

Grafy musí být v čistých bílých kartách s jasným nadpisem a jemným kontextem.

```tsx
<div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
  <div className="mb-4 flex items-baseline gap-2">
    <h2 className="text-base font-semibold text-gray-900">
      Výdaje podle kategorií
    </h2>

    <span className="text-xs text-gray-400">
      aktuální měsíc
    </span>
  </div>

  {/* Chart */}
</div>
```

Pravidla:

- Chart karta používá `p-5`.
- Nadpis je `text-base font-semibold`.
- Kontext v závorce nebo vedle nadpisu je `text-xs text-gray-400`.
- Nepiš dlouhý popis pod nadpis, pokud graf mluví sám.
- Graf musí být centrovaný a nesmí vyplňovat kartu až po okraje.
- Karta má mít `rounded-xl border border-gray-200 bg-white shadow-sm`.
- Hover efekt u statických grafových karet většinou nepoužívej.

Špatně:

```txt
Vývoj za 6 měsíců
Příjmy a výdaje v čase.
```

Lépe:

```txt
Příjmy vs. výdaje (posledních 6 měsíců)
```

---

### 51.5 Donut chart pravidla

Donut chart má být výrazný, ale ne obří. Legenda má být čitelná a klidná.

```tsx
<div className="flex flex-col items-center">
  <div className="h-[220px] w-full">
    {/* ResponsiveContainer + PieChart */}
  </div>

  <div className="mt-2 flex flex-wrap justify-center gap-x-3 gap-y-2 text-xs">
    {categories.map((category) => (
      <div key={category.name} className="flex items-center gap-1.5">
        <span className={`h-2 w-2 rounded-full ${category.dot}`} />
        <span className={category.textClass}>
          {category.name}
        </span>
      </div>
    ))}
  </div>
</div>
```

Pravidla:

- Donut chart výška: `h-[200px]` až `h-[240px]`.
- Nepoužívej obří donut, který sežere většinu karty.
- Donut musí mít dostatečně velký otvor uprostřed.
- Legenda je dole, centrovaná.
- Legenda používá malé barevné tečky, ne velké obdélníky.
- Text legendy je `text-xs`.
- Barvy legendy musí odpovídat kategoriím.
- Nepoužívej příliš mnoho kategorií v legendě. Pokud je kategorií víc než 6, slouč malé do „Ostatní“.
- Kategorie v grafu i badges musí používat stejnou paletu.

---

### 51.6 Bar chart / line chart pravidla

Pro srovnání dvou veličin, jako příjmy vs. výdaje, často preferuj sloupcový graf před line chartem.

Sloupcový graf je lepší, když:

```txt
✅ porovnáváš dvě hodnoty za jednotlivé měsíce
✅ hodnoty nejsou spojitý trend
✅ uživatel chce rychle vidět rozdíl mezi kategoriemi
✅ finance / usage / prodeje / výdaje
```

Line chart je lepší, když:

```txt
✅ ukazuješ skutečný trend v čase
✅ hodnoty mají spojitý vývoj
✅ sleduješ růst, průběh, kumulaci nebo výkon
```

Pravidla pro graf:

```txt
Osy:       text-xs, gray-500
Grid:      jemný dashed grid, gray-100/200
Legenda:   dole, centrovaná
Barvy:     emerald pro pozitivní hodnotu, red pro negativní
Tooltip:   vlastní bílý tooltip s borderem a shadow-sm
```

Nikdy:

```txt
❌ nepoužívej defaultní ostré Recharts barvy
❌ nepoužívej příliš silnou grid mřížku
❌ nepoužívej černé osy
❌ nepoužívej přeplněnou legendu
❌ nepoužívej line chart tam, kde bar chart čte lépe
```

---

### 51.7 Poslední záznamy — hybrid GPT + Claude

Pro sekce typu „Poslední transakce“, „Nedávné objednávky“, „Poslední aktivity“, „Nejnovější projekty“ používej hybrid:

```txt
Claude-like:
✅ čistá karta sekce
✅ dobré zarovnání
✅ přehledné kategorie
✅ jasná akce vpravo nahoře

GPT-like ponechat:
✅ barevná category čárka vlevo u každého řádku
```

Tento hybrid je výchozí pro přehled posledních záznamů.

---

### 51.8 Karta posledních záznamů

Sekce posledních záznamů je jedna větší karta.

```tsx
<div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
  <div className="mb-4 flex items-center justify-between">
    <div>
      <h2 className="text-base font-semibold text-gray-900">
        Poslední transakce
      </h2>
    </div>

    <a
      href="/transactions"
      className="text-sm font-medium text-indigo-600 transition-colors hover:text-indigo-700"
    >
      Zobrazit vše →
    </a>
  </div>

  <div className="space-y-2.5">
    {/* recent rows */}
  </div>
</div>
```

Pravidla:

- Karta používá `p-5`.
- Nadpis je `text-base font-semibold`.
- Akce vpravo je textový link, ne tlačítko.
- Nepiš dlouhý popis pod nadpis, pokud není nutný.
- Seznam uvnitř používá `space-y-2.5`.
- Pokud je záznamů jen 5, card-list je hezčí než tvrdá tabulka.
- Pokud je záznamů 10+, použij tabulku.

---

### 51.9 Recent row s barevnou čárkou vlevo

Barevná čárka vlevo zůstává zachovaná, protože zlepšuje rychlé skenování kategorií.

```tsx
<div className="relative flex min-h-[56px] items-center rounded-lg border border-gray-200 bg-white py-2.5 pl-9 pr-3 transition-colors hover:bg-gray-50">
  <div className="absolute left-3.5 top-3 bottom-3 w-1.5 rounded-full bg-orange-500" />

  <div className="min-w-0 flex-1">
    <div className="flex items-center gap-2">
      <h3 className="truncate text-sm font-semibold text-gray-900">
        Restaurace Mama Roma
      </h3>
    </div>

    <div className="mt-1 flex items-center gap-2">
      <span className="text-xs text-gray-500 tabular-nums">
        10. 5. 2026
      </span>

      <span className="inline-flex items-center rounded-full bg-orange-100 px-2 py-0.5 text-xs font-medium text-orange-700">
        Jídlo & restaurace
      </span>
    </div>
  </div>

  <div className="ml-4 min-w-[96px] text-right text-sm font-semibold tabular-nums text-red-600">
    -480 Kč
  </div>
</div>
```

Pravidla:

- Recent row je menší než plná transaction karta.
- Výška: `min-h-[56px]` až `min-h-[62px]`.
- Radius: `rounded-lg`.
- Padding: `py-2.5 pl-9 pr-3`.
- Barevná čárka má `w-1.5`.
- Čárka je odsazená: `left-3.5 top-3 bottom-3`.
- Čárka má `rounded-full`.
- Čárka používá barvu kategorie.
- Částka je vpravo.
- Kategorie je badge pod názvem nebo vedle data.
- Akce edit/delete v dashboard recent row většinou nezobrazuj. Patří do detailu nebo plného seznamu.

---

### 51.10 Kategorie jako Claude-like badges

Kategorie musí být malé, barevné, čitelné a konzistentní.

```tsx
<span className="inline-flex items-center rounded-full bg-orange-100 px-2 py-0.5 text-xs font-medium text-orange-700">
  Jídlo & restaurace
</span>
```

Pravidla:

- Badge má `rounded-full`.
- Badge má `text-xs font-medium`.
- Badge má `px-2 py-0.5`.
- Badge nemá shadow.
- Badge nemá border.
- Badge není uppercase.
- Badge barva odpovídá category čárce.
- Badge text je sytější než pozadí.
- Badge pozadí je světlé.
- Kategorie se nesmí zobrazovat jako obyčejný šedý text, pokud je v aplikaci důležitá.

Správná kombinace:

```txt
Čárka:       bg-orange-500
Badge bg:    bg-orange-100
Badge text:  text-orange-700
```

Špatně:

```txt
❌ Čárka orange, badge modrý
❌ Čárka indigo u všech řádků
❌ Badge šedý u všech kategorií
❌ Badge moc velký
❌ Badge s borderem a shadow
```

---

### 51.11 Paleta kategorií pro dashboardy a recent rows

Používej stejnou paletu pro:

```txt
1. donut chart segment
2. legend dot
3. recent row čárku
4. category badge
5. category text
```

Doporučená paleta:

```tsx
const categoryColors = {
  "Bydlení": {
    chart: "#7c3aed",
    dot: "bg-violet-500",
    badgeBg: "bg-violet-100",
    badgeText: "text-violet-700",
    labelText: "text-violet-600",
  },
  "Jídlo & restaurace": {
    chart: "#f97316",
    dot: "bg-orange-500",
    badgeBg: "bg-orange-100",
    badgeText: "text-orange-700",
    labelText: "text-orange-600",
  },
  "Doprava": {
    chart: "#f59e0b",
    dot: "bg-amber-500",
    badgeBg: "bg-amber-100",
    badgeText: "text-amber-700",
    labelText: "text-amber-600",
  },
  "Zábava": {
    chart: "#06b6d4",
    dot: "bg-cyan-500",
    badgeBg: "bg-cyan-100",
    badgeText: "text-cyan-700",
    labelText: "text-cyan-600",
  },
  "Zdraví": {
    chart: "#ec4899",
    dot: "bg-pink-500",
    badgeBg: "bg-pink-100",
    badgeText: "text-pink-700",
    labelText: "text-pink-600",
  },
  "Freelance": {
    chart: "#6366f1",
    dot: "bg-indigo-500",
    badgeBg: "bg-indigo-100",
    badgeText: "text-indigo-700",
    labelText: "text-indigo-600",
  },
  "Mzda": {
    chart: "#10b981",
    dot: "bg-emerald-500",
    badgeBg: "bg-emerald-100",
    badgeText: "text-emerald-700",
    labelText: "text-emerald-600",
  },
  "Ostatní": {
    chart: "#64748b",
    dot: "bg-slate-500",
    badgeBg: "bg-slate-100",
    badgeText: "text-slate-700",
    labelText: "text-slate-600",
  },
};
```

Pravidla:

- Kategorie má stabilní barvu v celé aplikaci.
- Donut, legenda, čárka a badge používají stejnou barevnou identitu.
- Barva nesmí být generovaná náhodně podle pořadí položek.
- Pokud kategorie není známá, použij `Ostatní`.
- Nepoužívej víc než 6 výrazných kategorií v jednom grafu.
- Menší kategorie slučuj do „Ostatní“.

---

### 51.12 Recent rows vs tabulka

Použij recent card-list s čárkami, pokud:

```txt
✅ jde o posledních 3–7 záznamů
✅ dashboard má působit moderněji
✅ každá položka má kategorii
✅ chceš vizuálně zachovat category signál
```

Použij tabulku, pokud:

```txt
✅ záznamů je 10+
✅ uživatel bude porovnávat sloupce
✅ je potřeba sorting
✅ je potřeba více metadat
✅ jde o primární stránku seznamu
```

Hybrid pravidlo:

```txt
Dashboard preview = card-list s category čárkami.
Plný seznam = card-list nebo tabulka podle množství dat.
Analytická tabulka = table layout.
```

---

### 51.13 Pokud musí být recent sekce tabulka

I v tabulce lze zachovat barevný category signál jemně.

```tsx
<td className="px-4 py-3">
  <div className="flex items-center gap-3">
    <span className="h-8 w-1.5 rounded-full bg-orange-500" />

    <div>
      <div className="text-sm font-medium text-gray-900">
        Restaurace Mama Roma
      </div>
      <div className="text-xs text-gray-500 tabular-nums">
        10. 5. 2026
      </div>
    </div>
  </div>
</td>
```

Pravidla:

- Barevná čárka je součástí první buňky.
- Nepoužívej čárku jako border celé tabulky.
- Badge kategorie je v samostatném sloupci nebo pod názvem.
- Tabulka má stále zůstat čistá a zarovnaná.

---

### 51.14 Částky a hodnoty v recent rows

Hodnota vpravo musí být snadno skenovatelná.

```tsx
<div className="ml-4 min-w-[96px] text-right text-sm font-semibold tabular-nums text-red-600">
  -480 Kč
</div>
```

Pravidla:

- Vždy `text-right`.
- Vždy `tabular-nums`.
- Použij `min-w-[96px]` až `min-w-[120px]`.
- Pozitivní hodnoty: `text-emerald-600`.
- Negativní hodnoty: `text-red-600`.
- Neutrální hodnoty: `text-gray-700`.
- Hodnota musí mít jednotku.
- Nepoužívej neformátovaná čísla.
- Kladné hodnoty mají `+`.
- Záporné hodnoty mají `-`.

---

### 51.15 Popisky u grafů a kategorií

Popisky musí být krátké a přesné.

Dobré:

```txt
Výdaje podle kategorií
Příjmy vs. výdaje
Poslední transakce
Zobrazit vše →
```

Horší:

```txt
Výdaje podle kategorií
Aktuální měsíc podle zvolených kategorií.

Vývoj za 6 měsíců
Příjmy a výdaje v čase.
```

Pravidla:

- Kontext dej do malého textu vedle nadpisu, ne do celé věty pod ním.
- Nepiš vysvětlení, pokud je graf jasný.
- Link „Zobrazit vše →“ je lepší než velké tlačítko.
- Dashboard má být rychlý ke skenování.

---

### 51.16 Přesné rozměry dashboard sekcí

Doporučené hodnoty:

```txt
Container:
- max-width: 1040–1120 px
- padding: px-8 py-8

Sekce:
- margin-bottom: mb-6
- grid gap: gap-4

KPI karty:
- p-5
- rounded-xl
- value: text-2xl font-bold
- label: text-sm
- context: text-xs

Chart karty:
- p-5
- rounded-xl
- chart height: 220–260 px
- title: text-base font-semibold

Recent karta:
- p-5
- list gap: space-y-2.5

Recent row:
- min-height: 56–62 px
- padding: py-2.5 pl-9 pr-3
- left stripe: w-1.5, left-3.5, top-3, bottom-3
- title: text-sm font-semibold
- meta: text-xs text-gray-500
- badge: text-xs font-medium px-2 py-0.5
```

---

### 51.17 Co u dashboardu nikdy nedělat

```txt
❌ Nepoužívej grafy bez horní KPI vrstvy, pokud dashboard má shrnovat stav.
❌ Nepoužívej donut chart větší než je potřeba.
❌ Nepoužívej legendu s velkými barevnými bloky.
❌ Nepoužívej defaultní chart styling.
❌ Nepoužívej dlouhé popisy pod každým grafem.
❌ Nepoužívej recent tabulku, pokud jde jen o 5 položek a moderní preview.
❌ Nepoužívej category badge bez barvy.
❌ Nepoužívej category čárku bez odpovídající badge barvy.
❌ Nepoužívej akční ikony edit/delete v dashboard preview řádcích.
❌ Nepoužívej velké mezery mezi recent rows.
❌ Nepoužívej `p-6` všude.
```

---

### 51.18 Claude + GPT hybrid pravidlo

Pro dashboardy kombinuj silné stránky obou přístupů:

```txt
Z Claude stylu vzít:
✅ celkovou kompozici
✅ KPI karty nahoře
✅ čisté grafové karty
✅ přehledné kategorie
✅ tabular/formátované hodnoty
✅ klidnou typografii
✅ správné spacingy

Z GPT stylu ponechat:
✅ barevné čárky vlevo u recent/list row položek
✅ card-list preview pro poslední záznamy
✅ rychlé category skenování přes levou lištu
```

Výsledek má působit takto:

```txt
„Claude-like dashboard s lepšími category signály v řádcích.“
```

Ne takto:

```txt
„Claude tabulka bez vizuálních category signálů.“
```

A ne takto:

```txt
„GPT card-list, který je barevný, ale méně přehledný.“
```

---

### 51.19 Checklist pro dashboard obrazovku

Před dokončením dashboardu zkontroluj:

```txt
[ ] Dashboard má nahoře H1 a jasný obsahový container.
[ ] Nad grafy existuje KPI/statistická vrstva, pokud stránka shrnuje stav.
[ ] KPI karty jsou barevně jemné, ne syté.
[ ] Grafové karty mají jednotný padding a radius.
[ ] Donut chart není přerostlý.
[ ] Legenda používá malé barevné tečky.
[ ] Barvy kategorií jsou stabilní napříč grafem, legendou, badge a čárkou.
[ ] Recent sekce má textový link „Zobrazit vše →“ vpravo.
[ ] Recent položky mají barevnou čárku vlevo.
[ ] Čárka je tlustší: w-1.5.
[ ] Čárka je odsazená a rounded-full.
[ ] Kategorie jsou zobrazené jako malé barevné pills.
[ ] Badge barva odpovídá čárce.
[ ] Hodnoty vpravo jsou zarovnané a mají tabular-nums.
[ ] V dashboard preview nejsou zbytečné edit/delete ikony.
[ ] Texty jsou krátké a nevysvětlují očividné věci.
[ ] Výsledek působí jako hotová SaaS aplikace, ne jako demo dashboard.
```

Pokud alespoň 3 body neplatí, obrazovku přepracuj.

---

### 51.20 Finální instrukce pro AI generování

Když generuješ dashboard, postupuj v tomto pořadí:

```txt
1. Nejdřív nastav container a sekční rytmus.
2. Přidej horní KPI karty.
3. Přidej grafové karty.
4. Přidej recent sekci.
5. U recent řádků zachovej barevné category čárky vlevo.
6. Kategorie zobraz jako malé barevné Claude-like badges.
7. Sjednoť category barvy napříč celou stránkou.
8. Zkrať texty.
9. Zjemni grafy.
10. Zkontroluj spacing a výšky.
```

Priorita není „víc efektů“. Priorita je:

```txt
kompozice → hierarchie → zarovnání → kategorie → grafy → mikrodetaily
```

Výsledek má být moderní dashboard, který je přehledný jako Claude, ale s lepší vizuální orientací v řádcích díky barevným category čárkám.

---

## 52. Dashboard recent table-preview se samostatným sloupcem kategorie

Tento pattern používej pro dashboard bloky typu „Poslední transakce“, „Poslední objednávky“, „Nedávné aktivity“ nebo jakýkoli krátký preview seznam o 3–7 položkách, kde uživatel potřebuje rychle skenovat datum, název, kategorii a hodnotu.

Cíl: preview má působit jako čistá produktová tabulka, ale zachovat barevný category signál přes levou čárku a badge kategorie. Je přehlednější než card-list, pokud se u každé položky opakují stejné čtyři informace.

### Struktura

```tsx
<div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
  <div className="mb-4 flex items-center justify-between">
    <h2 className="text-base font-semibold text-gray-900">Poslední transakce</h2>
    <a className="text-sm font-medium text-indigo-600 hover:text-indigo-700">
      Zobrazit vše →
    </a>
  </div>

  <div className="hidden grid-cols-[150px_minmax(0,1fr)_360px_120px] gap-4 border-b border-gray-100 pb-3 text-sm font-semibold text-gray-500 md:grid">
    <span>Datum</span>
    <span>Název</span>
    <span className="text-center">Kategorie</span>
    <span className="text-right">Částka</span>
  </div>

  <div className="divide-y divide-gray-100">
    <div className="relative grid gap-2 py-3 pl-5 md:min-h-[58px] md:grid-cols-[150px_minmax(0,1fr)_360px_120px] md:items-center md:gap-4 md:py-4">
      <span className="absolute bottom-3 left-0 top-3 w-1.5 rounded-full bg-orange-500" />
      <span className="text-sm text-gray-500 tabular-nums">10. 5. 2026</span>
      <h3 className="truncate text-sm font-semibold text-gray-900">Restaurace Mama Roma</h3>
      <div className="flex justify-center">
        <span className="inline-flex w-fit rounded-full bg-orange-500 px-3 py-1 text-xs font-medium text-white">
          Jídlo & restaurace
        </span>
      </div>
      <span className="text-right text-sm font-semibold tabular-nums text-red-600">-480 Kč</span>
    </div>
  </div>
</div>
```

### Pravidla

- Použij tento layout pro krátké dashboard preview seznamy, ne pro primární stránku dlouhého seznamu.
- Hlavička má čtyři sloupce: `Datum`, `Název`, `Kategorie`, `Částka`.
- Kategorie musí být samostatný prostřední sloupec, ne přilepená k datu.
- Sloupec kategorie musí začínat vlevo na stabilní ose; nepoužívej centrování badge.
- Pokud je mezi názvem a kategorií moc prostoru, vlož pružný spacer mezi kategorii a částku, ne před kategorii.
- Badge kategorie je sytý barevný pill s bílým textem; barva odpovídá levé čárce.
- Levá čárka zůstává na začátku řádku jako rychlý category signál.
- Čárka má `w-1.5`, `top-3`, `bottom-3`, `rounded-full`.
- Datum je šedé, `tabular-nums`, méně výrazné než název.
- Název je `text-sm font-semibold text-gray-900` a musí být `truncate`.
- Částka je vpravo, `text-right`, `tabular-nums`, zelená/červená podle typu.
- Řádky odděluj `divide-y divide-gray-100`, ne samostatnými kartami s velkými mezerami.
- V preview tabulce nezobrazuj edit/delete akce; detailní akce patří do plného seznamu.
- Link vpravo nahoře má být textový: `Zobrazit vše →`, ne tlačítko.

### Kdy nepoužít

- Nepoužívej pro 10+ položek, kde uživatel potřebuje sorting nebo dense porovnávání; tam použij plnou tabulku.
- Nepoužívej pro primární seznam transakcí, pokud je cílem rychlá práce se záznamy a akce edit/delete.
- Nepřesouvej badge zpět k datu, pokud existuje samostatný sloupec kategorie; opakovalo by to méně přehledný layout.

---

## 53. Claude-grade tabulkové preview: přesné sloupce, kategorie a zarovnání

Tato sekce definuje vzhled pro menší tabulkové přehledy uvnitř dashboardů, detailů nebo analytických obrazovek.

Použij tento pattern pro sekce typu:

- poslední transakce,
- nedávné objednávky,
- poslední aktivity,
- poslední faktury,
- nejnovější leady,
- poslední úkoly,
- rychlý přehled záznamů,
- preview tabulka na dashboardu.

Cíl: tabulkové preview musí působit přesně, klidně a prémiově. Každý sloupec musí mít jasnou osu. Kategorie musí začínat vždy na stejné horizontální pozici. Částky nebo hodnoty musí být zarovnané doprava. Pokud řádky používají barevný category signál, musí být decentní a nesmí rozbíjet tabulkovou geometrii.

### Hlavní princip

Tabulkové preview nesmí být několik flex řádků, které se náhodně tváří jako tabulka.

Správně:

```txt
✅ hlavička a řádky používají stejnou grid šablonu
✅ datum má vlastní pevný sloupec
✅ název má pružný sloupec
✅ kategorie má pevný sloupec
✅ všechny category badge začínají na stejné ose
✅ částka/hodnota je zarovnaná doprava
✅ barevná čárka vlevo je dekorativní a nerozbíjí grid
✅ řádky jsou kompaktní
✅ fonty jsou menší a klidné
```

Špatně:

```txt
❌ každý řádek používá vlastní flex rozložení
❌ badge kategorií jsou opticky uprostřed různě širokého prostoru
❌ kategorie nezačínají na stejné svislé ose
❌ sloupce jsou moc daleko od sebe
❌ řádky jsou příliš vysoké
❌ badge jsou moc velké
❌ částky jsou moc dominantní
❌ barevná čárka posouvá obsah každého řádku jinak
```

### Základní struktura

Celá sekce je jedna karta:

```tsx
<div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
  <div className="mb-4 flex items-center justify-between">
    <h2 className="text-base font-semibold text-gray-900">Poslední transakce</h2>
    <a href="/transactions" className="text-sm font-medium text-indigo-600 transition-colors hover:text-indigo-700">
      Zobrazit vše →
    </a>
  </div>

  {/* Table preview */}
</div>
```

Pravidla:

- Karta používá `rounded-xl border border-gray-200 bg-white p-5 shadow-sm`.
- Nadpis je `text-base font-semibold text-gray-900`.
- Akce vpravo je textový link.
- Nepoužívej velké CTA tlačítko.
- Nepřidávej popis pod nadpis, pokud není nutný.
- Tabulkové preview má být rychlé ke skenování.

### Společná grid šablona

Nejdůležitější pravidlo: hlavička i všechny řádky musí používat stejnou grid šablonu.

```tsx
const tableGridClass =
  "grid grid-cols-[140px_minmax(220px,1fr)_220px_minmax(72px,0.45fr)_120px]";
```

Použití:

```tsx
<div className={`${tableGridClass} border-b border-gray-100 pb-2 text-sm font-medium text-gray-500`}>
  <div>Datum</div>
  <div>Název</div>
  <div>Kategorie</div>
  <div />
  <div className="text-right">Částka</div>
</div>

<div className="divide-y divide-gray-100">
  {items.map((item) => (
    <div key={item.id} className={`relative ${tableGridClass} min-h-[50px] items-center py-2 text-sm`}>
      <div className="pl-7 text-gray-500 tabular-nums">10. 5. 2026</div>
      <div className="min-w-0 pr-4 font-medium text-gray-900">
        <span className="block truncate">Restaurace Mama Roma</span>
      </div>
      <div className="justify-self-start">
        <span className="inline-flex max-w-full items-center rounded-full bg-orange-500 px-2.5 py-0.5 text-xs font-medium text-white">
          <span className="truncate">Jídlo & restaurace</span>
        </span>
      </div>
      <div aria-hidden="true" />
      <div className="justify-self-end text-right text-sm font-semibold tabular-nums text-red-600">
        -480 Kč
      </div>
    </div>
  ))}
</div>
```

Pravidla:

- Nikdy neměň grid šablonu mezi hlavičkou a řádkem.
- Pokud má header 5 grid stop včetně spaceru, každý řádek má stejnou šablonu i prázdný spacer.
- Spacer patří mezi `Kategorie` a `Částka`, aby kategorie nebyla opticky příliš vpravo.
- Řádky musí obsahovat prázdnou spacer buňku před částkou; jinak částka skončí ve spacer sloupci a nebude zarovnaná pod headerem `Částka`.
- Nepoužívej `justify-between` pro tabulkové řádky.
- Nepoužívej `flex` jako hlavní layout pro tabulkové preview.
- Flex může být pouze uvnitř jednotlivých buněk.

### Doporučené šířky sloupců

Pro finanční nebo transakční preview:

```tsx
grid-cols-[140px_minmax(220px,1fr)_220px_minmax(72px,0.45fr)_120px]
```

Význam:

```txt
Datum:      140px
Název:      minmax(220px, 1fr)
Kategorie: 220px
Spacer:     minmax(72px, 0.45fr)
Částka:     120px
```

Pro obecné business preview:

```tsx
grid-cols-[160px_minmax(240px,1fr)_200px_120px]
```

Pro užší kartu:

```tsx
grid-cols-[120px_minmax(180px,1fr)_180px_100px]
```

Pravidla:

- Datum má být pevné, aby řádky držely osu.
- Název je pružný, protože má nejvíc variabilní délku.
- Kategorie má pevnou šířku, aby badge začínaly na stejné ose.
- Částka/hodnota má pevnou šířku a je zarovnaná doprava.
- Pokud jsou názvy dlouhé, použij `truncate`.
- Pokud jsou kategorie dlouhé, badge může mít `max-w-full truncate`.

### Zarovnání kategorie

Sloupec Kategorie musí být zarovnaný vlevo, ne centrovaný.

```tsx
<div className="justify-self-start">
  <span className="inline-flex items-center rounded-full bg-orange-500 px-2.5 py-0.5 text-xs font-medium text-white">
    Jídlo & restaurace
  </span>
</div>
```

Pravidla:

- Použij `justify-self-start`.
- Badge nesmí mít `mx-auto`.
- Buňka kategorie nesmí mít `text-center`.
- Sloupec kategorie nesmí používat `justify-center`.
- Začátky všech badge musí být na stejné svislé ose.
- Badge může mít různou šířku podle textu, ale její levý okraj musí být vždy stejně zarovnaný.
- Když kategorie působí moc vpravo, neposouvej ji centrováním; uprav grid tak, že přidáš spacer mezi kategorii a částku.

Špatně:

```tsx
<div className="flex justify-center">
  <span>Jídlo & restaurace</span>
</div>
```

Správně:

```tsx
<div className="justify-self-start">
  <span>Jídlo & restaurace</span>
</div>
```

### Category badge

Badge má být menší než ve velkých kartách.

```tsx
<span className="inline-flex max-w-full items-center rounded-full bg-orange-500 px-2.5 py-0.5 text-xs font-medium text-white">
  <span className="truncate">Jídlo & restaurace</span>
</span>
```

Pravidla:

- Badge má `text-xs`.
- Badge má `font-medium`.
- Badge má `px-2.5 py-0.5`.
- Badge má `rounded-full`.
- Badge nemá shadow.
- Badge nemá border.
- Badge není uppercase.
- Badge nepoužívá velký padding.
- Badge používá sytou plnou barvu kategorie.
- Text uvnitř badge je bílý: `text-white`.
- Badge musí být barevný, ne univerzálně šedý.
- Badge nesmí být tak velký, aby působil jako hlavní CTA.

### Barevná čárka vlevo

Barevnou čárku lze ponechat, ale musí být dekorativní a nesmí měnit tabulkový layout.

```tsx
<div className="absolute left-0 top-2.5 bottom-2.5 w-1.5 rounded-full bg-orange-500" />
```

Pravidla:

- Čárka má `w-1.5`.
- Čárka je `rounded-full`.
- Čárka je absolutně pozicovaná uvnitř řádku.
- Čárka nepřidává další sloupec.
- Čárka neposouvá grid šablonu.
- První buňka má kvůli čárce `pl-7`.
- Čárka používá stejnou category barvu jako badge.
- Čárka není nalepená na text.
- Čárka má být kratší než výška řádku: `top-2.5 bottom-2.5`.

### Row density

Tabulkové preview má být kompaktní.

```txt
Řádek:
- min-height: 46–52 px
- padding-y: py-2
- font-size: text-sm
- divider: divide-y divide-gray-100

Header:
- padding-bottom: pb-2
- font-size: text-sm
- color: text-gray-500
- weight: font-medium

Badge:
- text-xs
- px-2.5
- py-0.5
- plná category barva
- text-white

Čárka:
- w-1.5
- top-2.5
- bottom-2.5
```

Nepoužívej:

```txt
❌ min-h-[72px]
❌ py-4
❌ text-base
❌ text-lg
❌ velké pill badges
❌ gapy místo sloupců
```

### Částky a hodnoty

Částka nebo hodnota je poslední sloupec. Vždy je zarovnaná doprava.

```tsx
<div className="justify-self-end text-right text-sm font-semibold tabular-nums text-red-600">
  -480 Kč
</div>
```

Pravidla:

- Použij `justify-self-end`.
- Použij `text-right`.
- Použij `tabular-nums`.
- Použij `font-semibold`.
- Pozitivní hodnota: `text-emerald-600`.
- Negativní hodnota: `text-red-600`.
- Neutrální hodnota: `text-gray-700`.
- Hodnota musí mít jednotku.
- Kladné hodnoty mají `+`.
- Záporné hodnoty mají `-`.
- Nepoužívej neformátovaná čísla.

### Responsive chování

Na desktopu používej grid tabulku. Na mobilu přepni na card-list.

```tsx
{/* Desktop */}
<div className="hidden md:block">
  {/* grid table preview */}
</div>

{/* Mobile */}
<div className="space-y-2 md:hidden">
  {/* compact card rows */}
</div>
```

### Checklist

Před dokončením zkontroluj:

```txt
[ ] Header a rows používají stejnou grid šablonu.
[ ] Nepoužívá se justify-between jako hlavní layout řádku.
[ ] Sloupec Kategorie má pevnou šířku.
[ ] Badge v kategorii mají stejný levý začátek.
[ ] Kategorie nejsou centrované.
[ ] Pokud je potřeba vizuální vyvážení, spacer je mezi kategorií a částkou, ne mezi názvem a kategorií.
[ ] Každý řádek obsahuje prázdnou spacer buňku před částkou, pokud ji obsahuje grid šablona.
[ ] Částky jsou zarovnané doprava.
[ ] Hodnoty používají tabular-nums.
[ ] Barevná čárka vlevo je absolutní a nerozbíjí grid.
[ ] Barevná čárka má stejnou barvu jako badge.
[ ] Badge mají sytou plnou barvu a bílý text.
[ ] Řádky jsou vysoké cca 46–52 px.
[ ] Badge jsou malé a jemné.
[ ] Header je jemný, ne moc výrazný.
[ ] Desktop používá grid tabulku.
[ ] Mobil používá card-list.
[ ] Celá sekce působí jako přesná SaaS komponenta, ne jako zvětšený seznam.
```

Pokud alespoň 3 body neplatí, tabulkové preview přepracuj.

---

## 54. Product-grade dashboard correction rules

Tato sekce je tvrdý override pro analytické dashboardy, finance aplikace, budget stránky, KPI přehledy, grafové sekce, transakční seznamy a category-heavy UI.

Pokud je tato sekce v konfliktu se starší částí dokumentu, platí tato sekce.

Cíl: výsledek nesmí působit jako defaultní Tailwind/Recharts demo, ale jako hotový, promyšlený a vizuálně dotažený SaaS produkt.

---

### 52.1 Základní anti-patterny

Nikdy nevytvářej dashboard, který působí jako:

```txt
❌ tři bílé KPI karty + defaultní grafy + jednoduchá tabulka
❌ prázdný minimalistický layout bez vizuální hierarchie
❌ velké bílé plochy bez rytmu a informační hodnoty
❌ defaultní Recharts graf vložený do card komponenty
❌ pastelové category badges s barevným textem
❌ formulářové inputy uvnitř analytických/budget karet
❌ budget stránka jako settings form
❌ graf bez legendy, insightu nebo jasného důvodu
```

Minimalismus neznamená „málo designu“. Minimalismus znamená přesný rytmus, silnou hierarchii, dobré zarovnání a odstranění zbytečností.

---

### 52.2 Dashboard musí mít produktovou strukturu

Každý dashboard musí mít jasné vrstvy:

```txt
1. Header
   - H1 vlevo
   - krátký popis pod H1 nebo vedle H1
   - primární akce / období vpravo

2. KPI vrstva
   - 3 až 4 kompaktní stat cards
   - každá karta má hodnotu, label, kontext/trend a jemný vizuální signál

3. Analytická vrstva
   - grafy s kontextem
   - žádný graf nesmí být jen dekorace

4. Recent / detail vrstva
   - poslední záznamy, tabulka nebo card-list podle typu stránky
```

Dashboard nesmí začínat grafem, pokud jde o stránku, která shrnuje stav. Nejdřív musí uživatel vidět odpověď, až potom detail.

---

### 52.3 KPI karty nesmí být prázdné boxy

KPI karta nesmí obsahovat pouze:

```txt
label
velké číslo
ikonku
```

Každá KPI karta musí mít alespoň jednu kontextovou informaci:

```txt
✅ změna oproti minulému období
✅ krátký trend
✅ poměr k limitu/cíli
✅ počet souvisejících záznamů
✅ stavový text
✅ mini sparkline / accent line / subtle footer
```

Preferovaná struktura KPI karty:

```txt
Top row:
- label vlevo
- ikona nebo krátký status vpravo

Main:
- hlavní hodnota, text-2xl nebo text-3xl, tabular-nums

Context:
- krátká věta nebo trend
- např. "+12 % oproti minulému měsíci"
- např. "5 transakcí tento týden"
- např. "Zbývá 7 150 Kč"
```

KPI karta musí být vizuálně kompaktní, ne nafouknutá.

Doporučené třídy:

```txt
Card:       rounded-xl border border-gray-200 bg-white p-5 shadow-sm
Label:      text-sm font-medium text-gray-500
Value:      text-2xl font-bold text-gray-900 tabular-nums
Context:    text-xs text-gray-500
Icon box:   h-9 w-9 rounded-lg bg-indigo-50
```

---

### 52.4 Grafy musí mít insight, ne jen shape

Každý graf musí odpovědět na konkrétní otázku.

Před vložením grafu si určete:

```txt
Otázka: Co má uživatel z grafu pochopit?
Odpověď: Jaký insight má být vidět do 3 sekund?
Akce: Co může uživatel udělat dál?
```

Graf bez jasného insightu je špatný graf.

---

### 52.5 Donut chart pravidla

Donut chart nikdy nesmí být osamocené kolečko bez kontextu.

Donut chart musí mít:

```txt
✅ kompaktní velikost
✅ legendu s názvem kategorie
✅ hodnotu nebo procento
✅ stabilní category barvy
✅ top kategorii nebo shrnutí
```

Preferovaný layout donut karty:

```txt
Header:
- title
- krátký helper / období

Body:
- donut vlevo nebo uprostřed
- legenda vpravo nebo pod grafem

Insight:
- "Největší výdaj: Bydlení — 18 500 Kč"
```

Nikdy:

```txt
❌ donut bez legendy
❌ donut větší než obsah kolem něj
❌ náhodné barvy podle pořadí dat
❌ legenda s velkými barevnými bloky
❌ donut jen proto, že „dashboard potřebuje graf“
```

Doporučená velikost:

```txt
Donut outer radius: 72–86 px
Donut inner radius: 46–58 px
Chart card height: 240–280 px
```

---

### 52.6 Bar chart / line chart pravidla

Sloupcové a line grafy nesmí vypadat jako defaultní Recharts.

Povinné vlastnosti:

```txt
✅ rounded bars
✅ jemná grid mřížka
✅ osy bez černých linek
✅ malé gray tick labely
✅ custom tooltip
✅ legenda dole nebo v headeru
✅ dostatečný vnitřní padding
✅ barvy podle sémantiky
```

Doporučený styling:

```txt
Grid:        stroke="#e5e7eb", strokeDasharray="3 3", opacity 0.7
Axis line:   false
Tick line:   false
Ticks:       fill="#6b7280", fontSize 12
Bars:        radius={[6, 6, 0, 0]}
Tooltip:     bg-white, border-gray-200, rounded-lg, shadow-sm
Positive:    #10b981
Negative:    #ef4444
Primary:     #6366f1
```

Nikdy:

```txt
❌ defaultní ostré Recharts barvy
❌ černé osy
❌ silná grid mřížka
❌ graf přes celou kartu bez paddingu
❌ legenda nalepená na graf
❌ graf bez tooltipu
```

---

### 52.7 Category badges — tvrdý override

Pro category badges v aplikacích typu finance, transakce, budget, dashboard, CRM, projekty a analytika platí:

```txt
Category badges musí být plně vyplněné barvou a mít bílý text.
```

Nepoužívej pastelové badges s barevným textem pro hlavní category pills.

Zakázané:

```txt
❌ bg-orange-100 text-orange-700
❌ bg-indigo-100 text-indigo-700
❌ backgroundColor: category.color + opacity, color: category.color
❌ světlý badge s tmavším textem jako hlavní category badge
```

Povolené:

```txt
✅ bg-orange-500 text-white
✅ bg-indigo-500 text-white
✅ bg-emerald-500 text-white
✅ bg-violet-500 text-white
✅ bg-rose-500 text-white
✅ bg-slate-500 text-white
```

Badge anatomie:

```tsx
<span className="inline-flex items-center rounded-full px-2.5 py-1 text-xs font-semibold text-white shadow-sm">
  Kategorie
</span>
```

Badge pravidla:

```txt
- vždy rounded-full
- text-xs
- font-semibold nebo font-medium
- px-2.5 až px-3
- py-0.5 až py-1
- text-white
- stabilní barva podle kategorie
- stejná barva v tabulce, dashboardu, grafu, legendě i budget kartě
```

Výjimka:

```txt
Světlé pastelové badges lze použít jen pro sekundární/neutrální statusy,
ne pro hlavní kategorii transakce nebo budgetu.
```

---

### 52.8 Stabilní category color map

Kategorie nesmí dostávat barvu podle indexu v poli. Barvy musí být stabilní.

Použij mapu:

```tsx
const categoryColors = {
  "Bydlení": {
    bg: "bg-violet-500",
    text: "text-white",
    chart: "#8b5cf6",
    dot: "bg-violet-500",
  },
  "Jídlo & restaurace": {
    bg: "bg-orange-500",
    text: "text-white",
    chart: "#f97316",
    dot: "bg-orange-500",
  },
  "Doprava": {
    bg: "bg-blue-500",
    text: "text-white",
    chart: "#3b82f6",
    dot: "bg-blue-500",
  },
  "Zábava": {
    bg: "bg-pink-500",
    text: "text-white",
    chart: "#ec4899",
    dot: "bg-pink-500",
  },
  "Zdraví": {
    bg: "bg-emerald-500",
    text: "text-white",
    chart: "#10b981",
    dot: "bg-emerald-500",
  },
  "Vzdělání": {
    bg: "bg-cyan-500",
    text: "text-white",
    chart: "#06b6d4",
    dot: "bg-cyan-500",
  },
  "Mzda": {
    bg: "bg-green-500",
    text: "text-white",
    chart: "#22c55e",
    dot: "bg-green-500",
  },
  "Freelance": {
    bg: "bg-indigo-500",
    text: "text-white",
    chart: "#6366f1",
    dot: "bg-indigo-500",
  },
  "Ostatní": {
    bg: "bg-slate-500",
    text: "text-white",
    chart: "#64748b",
    dot: "bg-slate-500",
  },
};
```

Pokud kategorie není známá, použij `Ostatní`.

---

### 52.9 Budget page není settings form

Rozpočtová stránka nesmí působit jako formulář pro nastavení limitů.

Primární účel budget stránky:

```txt
1. ukázat kolik bylo utraceno
2. ukázat limit
3. ukázat kolik zbývá
4. ukázat riziko překročení
5. nabídnout nenápadnou možnost limit upravit
```

Limit je sekundární informace. Editace limitu je sekundární akce.

---

### 52.10 Zakázaný budget pattern

Nikdy nevkládej always-visible input do každé budget karty.

Zakázané:

```txt
Utraceno        Limit
1 850 Kč        [ 9000      ]

[ progress bar ]
```

Proč je to špatně:

```txt
❌ karta působí jako formulář
❌ input vizuálně přebíjí data
❌ uživatel má pocit, že musí něco vyplňovat
❌ dashboard ztrácí analytický charakter
❌ raw číslo bez měny působí nedodělaně
```

---

### 52.11 Správný budget card pattern

Budget karta je display-first komponenta.

Preferovaná struktura:

```txt
Top row:
- plný category badge vlevo
- procento čerpání vpravo

Main:
- hlavní hodnota: utraceno

Context:
- "z limitu X Kč"
- "Zbývá X Kč"

Progress:
- h-2 progress bar
- track bg-gray-100
- fill podle stavu

Footer:
- status vlevo
- "Upravit" jako malý textový link vpravo
```

Příklad:

```txt
[Jídlo & restaurace]                      21 %

1 850 Kč
z limitu 9 000 Kč

████░░░░░░░░░░░░░░░░

Zbývá 7 150 Kč                    Upravit
```

Riziková karta:

```txt
[Bydlení]                                93 %

18 500 Kč
z limitu 20 000 Kč

██████████████████░░

Blížíš se limitu · zbývá 1 500 Kč   Upravit
```

Karta bez limitu:

```txt
[Vzdělání]                               —

0 Kč
limit zatím není nastaven

░░░░░░░░░░░░░░░░░░░░

Nastavit limit
```

---

### 52.12 Jak se upravuje budget limit

Editace limitu nesmí být zobrazena jako výchozí stav v každé kartě.

Povolené způsoby editace:

```txt
✅ klik na "Upravit"
✅ ikonka tužky vpravo dole nebo v top row
✅ inline edit až po kliknutí
✅ modal
✅ side panel / drawer
```

Inline edit pattern:

```txt
Default:
Limit: 9 000 Kč      Upravit

Po kliknutí:
[ 9000 ] Kč          Uložit / Zrušit
```

Pravidla:

```txt
- input se objeví až po akci uživatele
- input musí mít měnu nebo suffix Kč
- Enter uloží
- Escape zruší
- blur může uložit jen pokud je to v aplikaci konzistentní
- po uložení se karta vrátí do display režimu
```

---

### 52.13 Budget progress status

Progress bar barvi podle stavu:

```txt
0–69 %       safe        indigo nebo emerald
70–89 %      warning     amber
90–100 %     danger      red
100 % +      over        red + jasný status
```

Status text:

```txt
Safe:
- "V pořádku"
- "Zbývá 7 150 Kč"

Warning:
- "Blížíš se limitu"
- "Zbývá 1 500 Kč"

Over:
- "Limit překročen o 850 Kč"
```

Červenou používej pouze, když je stav skutečně rizikový. Ne každá výdajová kategorie má být červená.

---

### 52.14 Transakce a tabulky

Na plné stránce transakcí může být tabulka. Na dashboard preview preferuj recent card-list.

Tabulka transakcí musí mít:

```txt
✅ jasné zarovnání sloupců
✅ název vlevo
✅ kategorie jako solid badge s bílým textem
✅ datum tlumenější barvou
✅ částku vpravo, tabular-nums
✅ akce vpravo s dostatečným hit targetem
```

Částky:

```txt
Příjem: +52 000 Kč, emerald
Výdaj: −1 420 Kč, red
```

Akční ikonky:

```txt
- icon button minimálně 36×36 px
- hover background
- aria-label
- delete červený až na hover nebo jako destruktivní akce
```

Nikdy:

```txt
❌ malá ikonka bez button hit area
❌ category badge pastelový s barevným textem
❌ částky zarovnané vlevo
❌ tabulka bez hover stavu
❌ příliš vysoké řádky bez důvodu
```

---

### 52.15 Finální visual quality gate

Před dokončením každé dashboard / finance / budget / analytics stránky musí agent projít tento checklist:

```txt
[ ] Dashboard má jasnou informační hierarchii: header → KPI → grafy → detail.
[ ] KPI karty nejsou jen label + číslo + ikona.
[ ] Každá KPI karta má kontext, trend nebo stav.
[ ] Grafy nevypadají jako default Recharts.
[ ] Každý graf má legendu, tooltip a jasný insight.
[ ] Donut chart má legendu nebo top-category summary.
[ ] Badges kategorií jsou solid filled a mají bílý text.
[ ] Category barvy jsou stabilní napříč celou aplikací.
[ ] Budget karty neobsahují always-visible inputy.
[ ] Limit je zobrazen jako text, např. "1 850 Kč z 9 000 Kč".
[ ] Editace limitu je sekundární akce přes Upravit / modal / inline edit po kliknutí.
[ ] Progress bary mají status podle procenta čerpání.
[ ] Tabulky mají správné zarovnání, hover a tabular-nums.
[ ] Prázdná místa působí jako rytmus, ne jako nedodělaný layout.
[ ] Stránka by obstála jako screenshot v portfoliu moderní SaaS aplikace.
```

Pokud alespoň 3 body neplatí, stránku nepovažuj za hotovou a přepracuj ji.

---

### 52.16 Instrukce pro AI agenty

Když AI agent implementuje dashboard, budget stránku, transakce nebo analytické UI:

```txt
1. Nejdřív navrhni informační hierarchii.
2. Potom zkontroluj existující design pravidla.
3. Potom navrhni komponenty.
4. Potom implementuj layout.
5. Potom implementuj datové stavy.
6. Potom proveď visual quality gate z této sekce.
7. Pokud najdeš konflikt ve starších pravidlech, použij pravidlo z této sekce.
```

Agent nesmí označit úkol za hotový, dokud explicitně neověří:

```txt
- badges jsou solid filled + white text
- grafy nejsou defaultní
- budget limity nejsou always-visible inputy
- dashboard není prázdný/minimalistický bez informační hodnoty
```

---
