# tgzero — CLAUDE.md

Zero-dependency, stdlib-only Telegram bridge for two-way CLI automation, plus
a bridge/hook pair that connects Claude Code sessions to Telegram.

## Git — tryb pracy

- Pracujemy w trybie **zmian na git** (diff/commit po każdym sensownym
  kroku), nie edycji plików "w powietrzu". Każda zmiana w kodzie powinna
  skończyć się commitem z krótkim, konkretnym opisem (po polsku lub
  angielsku — bez znaczenia, byle rzeczowo).
- **Katalog startowy (ten, w którym teraz pracujesz) jest ŹRÓDŁEM PRAWDY —
  jest świeższy niż to, co leży w `origin` na GitHubie.** Zanim zrobisz
  cokolwiek z historią (`git log`, `git diff origin/main`, branch, PR),
  **najpierw zaktualizuj zdalne repo** tymi plikami, a dopiero potem
  pracuj na gicie normalnie. Nie zakładaj, że `git clone`/`git pull` da Ci
  aktualny stan — nie da, dopóki nie wypchniesz tego, co jest lokalnie.
- Typowa sekwencja na start pracy w nowym katalogu:
  ```bash
  git init                      # jeśli katalog nie jest jeszcze repo
  git add -A
  git commit -m "sync: stan roboczy z katalogu startowego"
  git remote add origin https://$(cat terminal_access.token)@github.com/shipsweights/tgzero.git
  git push -u origin main --force-with-lease   # --force tylko przy pierwszej synchronizacji startowej!
  ```
  Jeśli repo już istnieje i jest podpięty `origin`, zamiast `remote add`
  zrób `git remote set-url origin ...` (patrz niżej) i zweryfikuj przed
  `push`, czy faktycznie chcesz nadpisać zdalną historię, czy raczej
  zmergować.
- **Dostęp do repo przez token z pliku**, nigdy nie wklejaj tokenu wprost
  do komendy ani nie commituj go:
  ```bash
  git clone https://$(cat terminal_access.token)@github.com/shipsweights/tgzero.git
  # albo dla już sklonowanego repo:
  git remote set-url origin https://$(cat terminal_access.token)@github.com/shipsweights/tgzero.git
  ```
  `terminal_access.token` ma zawierać wyłącznie sam token (bez `\n` na
  końcu potrafi namieszać — sprawdź `cat -A terminal_access.token`, jeśli
  coś nie działa). Plik **nigdy nie trafia do commita** — upewnij się, że
  jest w `.gitignore` zanim zrobisz pierwszy `git add -A`.
- Po normalnej synchronizacji (czyli gdy katalog startowy *nie* jest już
  przed repo) obowiązuje zwykły flow: branch → zmiana → commit → push →
  (jeśli używamy PR) PR, bez `--force`.

## Pip — osobny kanał od gita, nie myl ze sobą

Repo jest też pakietem instalowanym przez `pip install tgzero` (patrz
README). To **drugi, niezależny kanał dystrybucji** — `git push` na GitHuba
NIE aktualizuje tego, co ktoś dostanie przez `pip install tgzero` z PyPI.
Traktuj to jako dwie osobne operacje z osobnym celem, nie jako jedną rzecz.

- **Podczas developmentu zawsze pracuj na editable install**, żeby komenda
  `tgzero` od razu widziała zmiany w plikach `.py` bez reinstalacji:
  ```bash
  pip install -e .
  ```
  Jeśli w katalogu nie ma jeszcze `pyproject.toml`/`setup.py`, zgłoś to —
  nie zakładaj cicho, że jest, i nie twórz go samodzielnie bez potwierdzenia
  (to decyzja o strukturze pakietu, nie oczywista poprawka).
- **Przed jakimkolwiek testowaniem CLI sprawdź, która kopia faktycznie się
  odpala** — łatwo przetestować "zmianę", która w rzeczywistości biegnie na
  starej, globalnie zainstalowanej wersji z PyPI:
  ```bash
  which tgzero
  pip show tgzero                                   # Location: powinno wskazywać na ten katalog repo
  python3 -c "import tgzero, pathlib; print(pathlib.Path(tgzero.__file__).resolve())"
  ```
  Jeśli `Location`/ścieżka nie wskazuje na bieżący katalog roboczy —
  `pip uninstall tgzero` i zrób `pip install -e .` od nowa, zanim uznasz
  jakikolwiek test za wiarygodny.
- **Nowe moduły trzeba dopisać do manifestu pakietu.** `state.py`,
  `cmd_hook.py`, `cmd_bridge.py` są nowe względem pierwotnego repo — jeśli
  `pyproject.toml`/`setup.py`/`MANIFEST.in` wylicza pliki pakietu
  jawnie (a nie np. `find_packages()` na katalogu), upewnij się, że są na
  liście. Inaczej `pip install -e .` może działać (bo widzi katalog wprost),
  a dopiero prawdziwy `pip install tgzero` z zbudowanej paczki — nie,
  i wykryje się to dopiero na czyimś środowisku, nie tutaj.
- **Wydanie nowej wersji na PyPI jest zawsze ostatnim krokiem całej pracy,
  nie czymś robionym "przy okazji" commita.** Kolejność jest sztywna:
  1. zmiana w kodzie,
  2. testy z sekcji "jak terminal" / bridge+hook poniżej — na żywo, z
     realną wiadomością na Telegramie, nie tylko `py_compile`,
  3. commit + push na git,
  4. dopiero gdy wszystko powyższe przeszło i **wyraźnie o to poproszę** —
     podbicie `__version__` w `__init__.py` (zgodnie z tym, co czyta
     `cli.py` przez `from . import __version__` i co pokazuje
     `tgzero version`), potem build i upload:
     ```bash
     python3 -m build
     twine upload dist/*
     ```
  Nigdy nie przeskakuj do punktu 4 tylko dlatego, że kod się kompiluje —
  "kompiluje się" i "przetestowane na żywo" to nie to samo, a publikacja na
  PyPI trafia od razu do każdego, kto zrobi `pip install`/`pip install
  --upgrade`, więc cofnięcie jest dużo droższe niż cofnięcie commita.
- Jeśli kiedykolwiek coś "nie działa mimo poprawnego kodu" — pierwsze
  podejrzenie to właśnie rozjazd między edytowanym katalogiem a tym, co
  faktycznie uruchamia `tgzero` w `$PATH`. Sprawdź to przed szukaniem buga
  gdzie indziej.

## Zasady projektu (nieprzekraczalne)

- **Zero zależności zewnętrznych.** Tylko standardowa biblioteka Pythona.
  Zanim dodasz `import`, sprawdź czy to stdlib.
- **Nigdy `shell=True`.** Wszystkie `subprocess.run` używają
  `shlex.split(...)` + `shell=False`. Dotyczy to też wszystkiego nowego.
- **Sanityzacja przed HTML.** Każdy tekst, który trafia do wiadomości
  Telegrama w `parse_mode=HTML`, musi przejść przez `api.sanitize()`. Jeśli
  może zawierać kody ANSI (output poleceń, logi) — najpierw
  `api.strip_ansi()`, potem `sanitize()`. Do budowania bloków
  poleceń/outputu używaj `api.format_command_block()`, nie składaj tego
  ręcznie — to jedyne miejsce, które ma decydować, jak wygląda "terminal"
  na Telegramie.
- **Booleany w payloadzie przez `api._normalize()`.** Nie wysyłaj surowych
  `True`/`False` do `_post`/`_multipart_post` z pominięciem tej funkcji.
- **`send_message`/`edit_message_text`/itd. zwracają `dict | None`**, nie
  `bool`. Sprawdzaj przez `api.ok(result)`, odczytuj id przez
  `api.message_id(result)`.
- **`get_updates` zwraca `None` przy błędzie sieci, `[]` przy braku nowych
  wiadomości.** To rozróżnienie jest celowe — zawsze je honoruj.

## Mapa plików

| Plik              | Rola |
|-------------------|------|
| `api.py`           | Cała komunikacja z Telegram Bot API. Jedyne miejsce z `urllib`. |
| `cli.py`           | `argparse`, dispatch do `cmd_*.py`. |
| `config.py`        | `telegram.env` / zmienne środowiskowe, sprawdzanie uprawnień pliku. |
| `lock.py`          | Nazwane lockfile'y (`acquire(name=...)`/`release(name=...)`). |
| `cmd_send.py`      | `tgzero send` — jednorazowy alert. |
| `cmd_ask.py`       | `tgzero ask` — pytanie z przyciskami, blokujące. |
| `cmd_daemon.py`    | `tgzero daemon` — wykonuje komendy z allow-listy przychodzące z Telegrama. |
| `cmd_run.py`       | `tgzero run` — uruchamia komendę lokalnie, wysyła output. |
| `cmd_tail.py`      | `tgzero tail` — strumieniuje plik logu na Telegram. |
| `cmd_ping.py`      | `tgzero ping` — test connectivity. |
| `state.py`         | Plikowa kolejka żądań (JSON) między hookiem a bridge'em. |
| `cmd_hook.py`      | `tgzero hook` — producent, wywoływany przez Claude Code (`Stop`/`UserPromptSubmit`). Nigdy nie dotyka sieci, zawsze exit 0. |
| `cmd_bridge.py`    | `tgzero bridge` — jedyny długo działający poller `getUpdates`, routuje odpowiedzi do tmux. |

## Setup do pracy z terminala

```bash
cd /path/to/tgzero
cat telegram.env   # sprawdź, że TELEGRAM_TOKEN / TELEGRAM_CHAT_ID są ustawione
tgzero ping        # musi przyjść testowa wiadomość na Telegram
```

Jeśli pracujesz nad bridge/hookiem: sesja musi działać w tmux, bo
wstrzykiwanie odpowiedzi z Telegrama korzysta z `tmux send-keys -t $TMUX_PANE`.

```bash
tmux new -s tgzero-dev    # albo tmux attach, jeśli już istnieje
echo $TMUX_PANE            # powinno coś wypisać — jeśli puste, nie jesteś w tmux
```

## Jak testować sam silnik (bez tmux/bridge)

Najszybsza pętla zwrotna: `tgzero ping`, `tgzero send`, potem `tgzero run`.
Każda zmiana w `api.py`, `cmd_run.py`, `cmd_daemon.py`, `cmd_tail.py` powinna
kończyć się realną wysyłką na Telegram, nie tylko `py_compile`.

```bash
python3 -m py_compile *.py           # najpierw składnia
tgzero ping                          # połączenie
tgzero send -m "test: $(date)"       # podstawowa wysyłka
```

## Testowanie wyglądu "jak terminal" (ważne — to był ostatni duży temat)

`api.format_command_block()` ma trzy zadania naraz: ściąć kody ANSI,
zescapować HTML, zmieścić się w limicie Telegrama. Testuj to realnymi,
"brudnymi" outputami, nie czystym tekstem — czysty tekst nigdy nie wykryje
regresji.

Dobre polecenia testowe (celowo kolorowe / tabelaryczne / ze znakami
specjalnymi, które muszą przejść przez `sanitize()` bez łamania HTML):

```bash
# Kolor ANSI — musi zniknąć, nie zostać jako śmieci w <pre>
tgzero run "ls --color=always -la /etc"

# Tabela z wyrównanymi kolumnami — sprawdź, czy się nie rozjeżdża po zawinięciu
tgzero run "df -h"

# Znaki specjalne HTML w outpucie — < > & " muszą wyjść jako &lt; &gt; &amp; &quot;,
# nie połamać <pre> ani nie zniknąć
tgzero run 'echo "<script>alert(1)</script> & \"cytat\" <tag>"'

# Długi output — podgląd (15 pierwszych + 10 ostatnich linii) + załącznik output.txt
# (bez shell=True pipe'y nie działają — | trafiłby jako argument)
tgzero run "ls -la /etc"

# Kod wyjścia != 0 — sprawdź ❌ i poprawny <code>exit code</code>
# (exit to builtin powłoki — bez shella "exit 42" daje "Command not found")
tgzero run "ls /nie-ma"

# Timeout — sprawdź ⏱ i że wiadomość faktycznie przychodzi
tgzero run --timeout 2 "sleep 5"

# tail: kolorowe, strumieniowe logi z filtrem słów kluczowych
( for i in $(seq 1 20); do
    printf "\033[91m[ERROR]\033[0m linia %d <ważne> & \"dane\"\n" "$i"
    sleep 0.3
  done ) > /tmp/fake.log &
tgzero tail /tmp/fake.log --filter "error" --label "fake-service"
# ... poczekaj na kilka batchy, potem Ctrl+C na tailu
```

Dla `daemon`: odpal `tgzero daemon --allow-list "ls --color=always -la,df -h"`
i wyślij te komendy z Telegrama ręcznie — to jedyny sposób, żeby sprawdzić
cały łańcuch (allow-list → `shlex.split` → `strip_ansi` → `sanitize` →
Telegram) tak, jak go zobaczy użytkownik.

**Czego pilnować wzrokiem na Telegramie:**
- brak widocznych `\x1b[` / `[91m` itp. w treści,
- `<`, `>`, `&`, `"` pokazują się jako normalne znaki, nie psują formatowania wiadomości,
- blok z outputem jest czcionką monospace (`<pre>`),
- długi output przychodzi jako podgląd z `... preview — full output attached` + plik `output.txt`, a nie wywala wysyłki,
- `$ komenda` w nagłówku jest czytelna nawet gdy komenda zawiera cudzysłowy.

## Testowanie bridge + hook (bez prawdziwego Claude Code)

Hook czyta JSON ze stdin — można go wywołać ręcznie, symulując to, co
wysłałby Claude Code, i obserwować plik żądania oraz (z działającym
`bridge` w drugim oknie tmux) realną wiadomość na Telegramie.

```bash
# Okno 1: bridge
tgzero bridge

# Okno 2 (ta sama maszyna, inny panel — $TMUX_PANE musi być inny niż bridge'a):
cat > /tmp/fake_transcript.jsonl <<'EOF'
{"message": {"role": "user", "content": "sprawdz status serwisu X"}}
{"message": {"role": "assistant", "content": [{"type": "text", "text": "Serwis X dziala, ale ma 85% zuzycia CPU. Chcesz, zebym go zrestartowal?"}]}}
EOF

echo '{"hook_event_name":"Stop","session_id":"test-1","cwd":"'"$PWD"'","transcript_path":"/tmp/fake_transcript.jsonl"}' \
  | tgzero hook
```

Powinna przyjść wiadomość na Telegram z kontekstem rozmowy. Odpowiedz na nią
(reply!) — sprawdź, czy tekst pojawia się wpisany w panelu z Okna 2.

Test ścieżki "odpowiedziano na PC" (bez czekania na Telegram):

```bash
echo '{"hook_event_name":"UserPromptSubmit","session_id":"test-1","prompt":"tak, zrestartuj"}' \
  | tgzero hook
# W ciągu ~15s (cykl bridge'a) wiadomość na Telegramie powinna zmienić się
# na "✅ Odpowiedziano na PC" z usuniętymi przyciskami.
```

Podgląd stanu kolejki żądań bez grzebania w kodzie:

```bash
python3 -c "from tgzero import state; import pprint; pprint.pprint(state.list_all())"
```

## Zanim zacommitujesz zmianę w czymkolwiek, co wysyła na Telegram

1. `python3 -m py_compile *.py`
2. Przynajmniej jeden z testów z sekcji "jak terminal" powyżej — **patrz na
   realną wiadomość w Telegramie**, nie ufaj samemu brakowi wyjątku w
   terminalu.
3. Jeśli zmiana dotyka `api.py` — sprawdź oba tryby `_post` i
   `_multipart_post` (booleany, błędy HTTP z body JSON).

## Znane, świadomie odłożone braki (nie zgłaszaj jako bugi, dopytaj najpierw)

- Brak przycisków/wyboru opcji dla żądań z hooka (np. `AskUserQuestion`,
  zgody na narzędzia) — silnik w `cmd_bridge.py` je obsłuży
  (`callback_prefix` = id żądania), ale żaden hook jeszcze ich nie generuje.
- Wiele równoległych pytań bez użycia Telegramowego "reply" → bridge
  odmawia zgadywania, do którego żądania należy odpowiedź.
- Brak redaktora maskującego sekrety/tokeny w kontekście wysyłanym na
  Telegram (output komend, fragmenty transkryptu).
