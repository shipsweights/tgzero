# NOTE_TELEGRAM.md — jak Claude CLI współpracuje z tgzero

Ten plik jest instrukcją dla Claude Code. Skopiuj go do katalogu projektu,
w którym pracuje Claude, i wskaż go w `CLAUDE.md` (`@NOTE_TELEGRAM.md`) albo
każ Claude'owi go przeczytać na starcie sesji.

## Środowisko (zakładamy, że już jest)

- Zainstalowany `tgzero >= 0.3.1` (`pip install --upgrade tgzero`; starsze
  wersje psuły wiadomości ze znakiem `<`).
- Plik `telegram.env` (`TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`) w katalogu, z
  którego działa Claude — `tgzero` czyta go z bieżącego katalogu. Alternatywa:
  te same zmienne w środowisku.
- **Nigdy** nie wypisuj, nie cytuj i nie commituj `telegram.env` ani tokenu.
  Nie szukaj tokenu — jeśli `tgzero` zgłosi brak konfiguracji, powiedz o tym
  użytkownikowi i nie kombinuj.

## Tryb 1 — powiadomienia (jednokierunkowe)

Wysyłaj wiadomość **tylko w momencie zakończenia kroku** — nie na starcie, nie
w trakcie, nie przy pytaniach pomocniczych.

```bash
tgzero send -m "✅ Krok 2/5: migracja bazy — OK, 14 tabel"
tgzero send -s -m "Krok 3/5 gotowy"     # -s = bez dźwięku (kroki pośrednie)
```

Zasady:
- Jedna wiadomość na zakończony krok, 1–3 linie: co zrobione + wynik.
- Porażka lub potrzeba decyzji → jedna wiadomość wprost
  (`❌ ... — potrzebuję decyzji: ...`), normalna (bez `-s`).
- Na końcu całej pracy jedno podsumowanie (normalna, z dźwiękiem).
- Pośrednie kroki wysyłaj z `-s`; z dźwiękiem tylko porażka, decyzja i finał.
- Bez sekretów, tokenów i całych logów — wiadomość idzie na Telegram bez
  maskowania. Wklejaj krótkie fragmenty, nie dumpy.
- Wywołuj `tgzero` wprost, bez `shell=True`, pipe'ów i interpolacji
  niezaufanego tekstu w komendę. Treść z cudzysłowami podawaj jako
  jeden argument po `-m`.
- Znaki `<`, `>`, `&` i kody ANSI są escapowane/usuwane przez `tgzero send`
  (od 0.3.1) — nie escapuj ich ręcznie. Ręczne HTML (`<b>`) nie działa.
- Jeśli `tgzero send` zwróci błąd: nie ponawiaj w pętli, kontynuuj pracę i
  wspomnij o tym w terminalu.
- Limit: 4096 znaków. Trzymaj się krótkich komunikatów.

Na początku pracy wyślij jedną wiadomość testową:
`tgzero send -s -m "test: gotowy do pracy"`.

## Tryb 2 — odpowiedzi z Telegrama (dwukierunkowe)

Do tego **nie służy `send`**. Wymaga razem:

1. `tgzero bridge` uruchomiony w osobnym oknie tmux (jedyny proces, który
   robi `getUpdates`; `daemon` musi być wyłączony, a `tgzero ask` nie może
   działać równolegle).
2. Hooki w `~/.claude/settings.json` (lub pliku projektu):
   ```json
   {
     "hooks": {
       "Stop":             [ { "hooks": [ { "type": "command", "command": "tgzero hook" } ] } ],
       "UserPromptSubmit": [ { "hooks": [ { "type": "command", "command": "tgzero hook" } ] } ]
     }
   }
   ```
3. Sesja Claude Code uruchomiona **w tmux** (`echo $TMUX_PANE` nie może być
   puste) — odpowiedź jest wpisywana przez `tmux send-keys`.

Działanie: na koniec tury (`Stop`) hook zapisuje żądanie, bridge wysyła na
Telegram kontekst rozmowy; użytkownik odpowiada **reply** na tę wiadomość, a
tekst trafia do terminala jako zwykły prompt. Jeśli użytkownik odpowie na PC
(`UserPromptSubmit`), wiadomość zmienia się na „✅ Answered on PC".

Uwagi dla Claude'a:
- Odpowiedź z Telegrama przychodzi jako zwykła wiadomość użytkownika — traktuj
  ją tak samo jak wpisaną ręcznie.
- Hook nie wymaga od Ciebie żadnej akcji; nie wywołuj `tgzero hook` ręcznie.
- Przy kilku równoległych pytaniach bez „reply" bridge odmówi zgadywania
  (⚠️ „I can't tell which request this answer belongs to").
- W trybie 2 nie wysyłaj dodatkowo `tgzero send` na koniec każdej tury —
  hook robi to sam. `send` zostaw na istotne kroki pośrednie.

## Pytania blokujące (opcjonalnie)

`tgzero ask -p "Wdrożyć?" -b "Tak,Nie" -t 600` blokuje do odpowiedzi
(exit 0 = pierwszy przycisk, 1 = inny, 2 = timeout). Używaj **tylko gdy
`bridge` nie działa** — oba procesy konkurują o `getUpdates`.

## Czego nie robić

- Nie wysyłaj wiadomości „dla porządku" (start kroku, postęp co minutę,
  przeprosiny, powtórzenia).
- Nie uruchamiaj `bridge`, `daemon` ani `ask` bez wyraźnej prośby.
- Nie publikuj pakietu ani nie zmieniaj konfiguracji tgzero na własną rękę.
