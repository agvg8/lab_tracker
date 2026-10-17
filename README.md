# LabTracker

Prosty system do śledzenia laborek dla 3 osób i admina: logowanie → przedmioty → laborki → taski z pliku .txt.

## Role
- **Admin** widzi wszystko. Tworzy, edytuje i usuwa przedmioty (projekty), laborki i taski, wrzuca pliki .txt
  i ustala, które osoby należą do danego projektu („Osoby w projekcie” na stronie przedmiotu).
- **Osoby (3)** widzą tylko projekty, do których admin je przypisał — pozostałe są dla nich niewidoczne.
  W swoich projektach odhaczają taski, oddają laborki i cofają oddanie. Ikonka ✎ nad „Postępem całości” włącza
  tryb edycji: przy każdym tasku pojawia się lista „kto robi” (dowolna osoba z projektu) i „Przypisz wszystkie”. Swoje taski mają oznaczone kreską z lewej.
- Paski postępu pokazują tylko osoby z danego projektu. Usunięcie osoby z projektu sprawia, że jej taski liczą się jako nieprzypisane.

## Funkcje
- 4 konta zaszyte w `app.py` (słownik `USERS` na górze pliku).
- Dashboard z przedmiotami.
- Laborki w przedmiocie: dodanie z pliku `.txt` (jedna linia = jeden task) lub wklejonego tekstu.
  Znaczniki list (`-`, `*`, `1.`, `[ ]`) są usuwane, kodowanie UTF-8 i Windows-1250 obsługiwane.
- Taski: odhaczanie i przypisywanie osób (członkowie projektu); w trybie edycji admin dodatkowo zmienia treść i usuwa taski.
- Odhaczone taski spadają do sekcji „Zrobione” na dole listy; odznaczone wracają na swoje miejsce.
- Odhaczanie działa zwykłym przyciskiem (także bez JavaScriptu), a strona po przeładowaniu wraca do tego samego miejsca.
- Progress bar całości + osobny pasek dla każdej osoby z projektu (jej przypisane taski). Admin nie ma paska.
- Przycisk **Oddaj** pojawia się, gdy wszystko jest odhaczone. Oddana laborka spada na dół listy, wyszarzona.
- Cofnięcie oddania: przycisk „Cofnij oddanie” albo odznaczenie taska — oba z potwierdzeniem.

## Konta
Edytuj w `app.py`:
```python
USERS = {
    "admin": {"password": "zmien-admin", "name": "Admin", "role": "admin"},
    "aga": {"password": "zmien-mnie-1", "name": "Aga", "role": "member"},
    "osoba2": {"password": "zmien-mnie-2", "name": "Osoba 2", "role": "member"},
    "osoba3": {"password": "zmien-mnie-3", "name": "Osoba 3", "role": "member"},
}
```
Klucz (`aga`) to login, `role` to `admin` albo `member`. Kolory pasków są przygotowane dla 3 osób (dla 4. dopisz `--u4` w CSS). Przy zmianie loginu po starcie istniejące przypisania do starego loginu przestaną się liczyć.

## Uruchomienie lokalnie
```bash
pip install -r requirements.txt
python app.py          # http://localhost:5000, baza SQLite w instance/labtracker.db
```

## Deploy na Railway
1. Wrzuć folder do repo na GitHubie.
2. Railway → **New Project → Deploy from GitHub repo** → wybierz repo.
3. W projekcie: **+ New → Database → PostgreSQL**.
4. W serwisie aplikacji → **Variables**:
   - `DATABASE_URL` = `${{Postgres.DATABASE_URL}}` (referencja do bazy)
   - `SECRET_KEY` = dowolny długi losowy ciąg
5. **Settings → Networking → Generate Domain**.

Railway sam wykryje Pythona i uruchomi aplikację z `Procfile` (gunicorn). Tabele tworzą się automatycznie przy starcie.

Bez Postgresa aplikacja użyje SQLite, ale na Railwayu dane znikną przy każdym redeployu — dlatego baza jest potrzebna.
