# Claude Code ↔ Telegram bridge — integration notes

Nowe komponenty: `tgzero bridge` (jedyny długo działający poller) i
`tgzero hook` (lekki, nieblokujący producent wywoływany przez Claude Code).
Łączy je `state.py` — kolejka żądań w plikach JSON w katalogu runtime.

## 1. Uruchom terminal w tmux

Bridge wstrzykuje odpowiedź z Telegrama do konkretnego panelu przez
`tmux send-keys`, więc sesja Claude Code musi działać wewnątrz tmux (zwykły
`tmux new -s work`, potem `claude` w środku). Bez tmux hook nadal wyśle
powiadomienie z kontekstem, ale odpowiedź z telefonu trzeba będzie wpisać
ręcznie — bridge jasno to zaznaczy w wiadomości zamiast milczeć.

## 2. Podepnij hooki w Claude Code

W `~/.claude/settings.json` (lub analogicznym pliku projektu):

```json
{
  "hooks": {
    "Stop": [
      { "hooks": [ { "type": "command", "command": "tgzero hook" } ] }
    ],
    "UserPromptSubmit": [
      { "hooks": [ { "type": "command", "command": "tgzero hook" } ] }
    ]
  }
}
```

`tgzero hook` sam rozpoznaje zdarzenie z pola `hook_event_name` w JSON-ie na
stdin, więc ta sama komenda obsługuje oba hooki.

## 3. Odpal bridge (jeden na maszynę)

```bash
tgzero bridge
```

Pod systemd, analogicznie do `daemon` z README:

```ini
[Unit]
Description=tgzero Claude Code bridge
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/myapp
EnvironmentFile=/opt/myapp/telegram.env
ExecStart=tgzero bridge
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

**Ważne:** nie odpalaj równocześnie `tgzero ask` / `tgzero daemon` na tym
samym tokenie/czacie co `bridge` — dwa procesy robiące `getUpdates`
jednocześnie dostaną od Telegrama błąd 409.

## 4. Jak to działa

1. Claude Code kończy turę → hook `Stop` → `tgzero hook` czyta transkrypt,
   wyciąga ostatnią odpowiedź + krótki kontekst, zapisuje żądanie
   (`status: pending`) i kończy natychmiast — Claude Code nie czeka.
2. `bridge` (osobny proces, polling co ~15s) widzi nowe żądanie, wysyła je
   na Telegram, zapisuje `message_id` i zmienia status na `sent`.
3. **Odpowiedź z telefonu:** reply na tę konkretną wiadomość (albo zwykły
   tekst, jeśli akurat tylko jedno pytanie czeka) → bridge wstrzykuje tekst
   do właściwego panelu tmux przez `send-keys`, edytuje wiadomość na
   Telegramie (✅ + treść odpowiedzi), kasuje żądanie.
4. **Odpowiedź na PC:** wpisujesz coś wprost w Claude Code → hook
   `UserPromptSubmit` oznacza żądanie jako `answered_pc` → bridge przy
   najbliższym cyklu edytuje wiadomość na Telegramie („✅ Odpowiedziano na
   PC”) i usuwa przyciski, więc spóźniona odpowiedź z telefonu nic już nie
   zrobi.
5. Żądania bez odpowiedzi wygasają po `--ttl` sekund (domyślnie 6h).

## Czego tu jeszcze nie ma (świadomie odłożone)

- Przyciski/wybór opcji (np. `AskUserQuestion`, zgody na użycie narzędzia) —
  silnik w `cmd_bridge.py` już obsługuje callbacki generycznie
  (`callback_prefix` = id żądania), ale żaden hook jeszcze nie generuje
  żądań z przyciskami. To osobny krok.
- Wiele równoległych sesji odpowiada dziś na zasadzie "reply do konkretnej
  wiadomości, albo jedno oczekujące pytanie" — przy kilku pytaniach naraz
  bez użycia reply bridge grzecznie odmówi zgadywania.
- Redaktor maskujący sekrety w kontekście wysyłanym na Telegram.
