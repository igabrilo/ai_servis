# AI servis za narudžbe

## Pokretanje

Potreban je Python 3.14 i [Gemini API ključ](https://aistudio.google.com/apikey). U korijenu projekta pokrenite:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade 'pip>=26.2'
python -m pip install -r requirements.txt
```

U korijenu projekta napravite lokalnu datoteku `.env`:

```dotenv
GEMINI_API_KEY=vas_api_kljuc
GEMINI_MODEL=gemini-3.1-flash-lite
```

Ključ se čita iz varijabli okruženja ili `.env`, koja je isključena iz Gita. Varijable okruženja imaju prednost.

```bash
python -m uvicorn app.main:app --reload --host 127.0.0.1
```

Servis je dostupan na `http://127.0.0.1:8000`, a [interaktivna dokumentacija](http://127.0.0.1:8000/docs) omogućuje isprobavanje poziva. Ako ključ nedostaje ili jelovnik nije valjan, servis se ne pokreće i ispisuje razlog.

## Primjer poziva

`POST /order` prima JSON s poljem `text`, koje mora sadržavati neprazan tekst do 2.000 znakova:

```bash
curl http://127.0.0.1:8000/order \
  -H 'Content-Type: application/json' \
  -d '{"text": "dva hamburgera, dvije margarite i jednu colu"}'
```

Primjer odgovora:

```json
{
  "items": [
    {"id": "margarita", "quantity": 2},
    {"id": "coca_cola", "quantity": 1}
  ],
  "unavailable": [{"text": "hamburger", "quantity": 2}],
  "suggestions": [],
  "clarification": null
}
```

`items` sadrži naručene stavke prema ID-evima jelovnika, a `unavailable` čuva proizvode kojih nema, bez zamjene sličnim artiklom. Dodao sam `suggestions` za prijedloge hrane bez mesa i `clarification` za pitanje kad narudžba nije jasna; prijedlozi sami nisu narudžba. Ako je potrebno pojašnjenje, rezultat je nepotpun i u novom zahtjevu treba poslati cijelu pojašnjenu rečenicu. Kasniji ispravci, poput „tri margarite, ipak dvije”, određuju konačnu količinu.

## Pogreške

Neispravan ulaz vraća `422`. Ako model vrati nevaljan JSON, nepoznat ID, neispravnu količinu ili prazan, blokiran ili prekinut odgovor, servis vraća `502`; nedostupnost API-ja, problem povezivanja ili iscrpljena kvota vraćaju `503`, a istek vremena `504`. SDK čeka do 15 sekundi po pokušaju, uz najviše jedan ponovni pokušaj za privremene pogreške; cijeli AI poziv ograničen je na 30 sekundi. Poruke pogrešaka ne otkrivaju API ključ ni interne detalje, a pogreška se ne prikazuje kao uspješna prazna narudžba.

## Poboljšanja i provjera kvalitete

Proširio bih skup primjera stvarnim anonimiziranim narudžbama, a prije javne objave dodao autentifikaciju i ograničenje broja zahtjeva. Validaciju i obradu kvarova moguće je provjeriti bez API ključa naredbama `python -m pip install -r requirements-dev.txt` i `python -m pytest`. Razumijevanje hrvatskog provjerava se zasebno naredbom `python -m evaluation.evaluate --assignment-only` za pet primjera iz zadatka ili `python -m evaluation.evaluate` za svih 20, uz ručni pregled značenja rezultata i dostupnu Gemini kvotu.
