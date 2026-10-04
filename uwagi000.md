Patrząc na realny zrzut z Telegrama (to świetny test), widzę konkretne, punktowe problemy — część to faktyczne niespójności w kodzie, nie tylko "gust":

## Co dokładnie szarpie obraz (z dowodem w zrzucie)

**1. Nie wszystkie ścieżki błędów przechodzą przez `format_command_block()` — to realny bug mój, nie Twój.**
W poprzedniej turze poprawiłem gałąź `TimeoutExpired` w `cmd_run.py`, ale zapomniałem o `FileNotFoundError` i ogólnym `Exception`. Stąd widoczne na zrzucie „⚠️ Command not found: exit 42" — jednolinijkowiec bez nagłówka `$ komenda`, bez boxa, zupełnie inny kształt niż reszta. Oko musi za każdym razem na nowo rozpoznawać typ wiadomości zamiast skanować po stałym wzorcu.

**2. Wiadomości bez outputu tracą "box" — wizualnie wypadają z rytmu.**
Porównaj wiadomość `df -h` (ma szary box z paskiem „copy" nad treścią — to natywny code-block Telegrama) z wiadomością `sleep 5` / timeout (zwykły tekst, bez boxa, bo `(no output)` renderuje się jako `<i>`, nie `<pre>`). W strumieniu wiadomości to wygląda jak dwa różne komunikatory. Naprawa: zawsze owijać treść w `<pre>`, nawet pustą — `<pre>(brak outputu)</pre>` zamiast kursywy poza blokiem.

**3. Linia meta jest przeładowana i częściowo redundantna.**
„Exit: 0 · Started: 18:15:49 · Took: 0.0s" — `Started` w formacie 24h dubluje to, co Telegram i tak pokazuje w rogu wiadomości (6:15 PM, 12h). Dwa różne zegary dla tej samej informacji to czysty szum. Usunięcie `Started` skraca każdą wiadomość o jedną trzecią linii meta bez utraty informacji.

**4. Ściana tekstu przy długim outpucie (ten ogromny `ls -la /etc`) to główny winowajca „zamazania".**
`"... output truncated"` działa zgodnie z kodem, ale 4000 znaków nieczytelnej, poprzycinanej tabeli to i tak ściana. Mam już gotowe `send_document()` w `api.py` — nigdy go nie podłączyłem. Najlepsza dźwignia: powyżej pewnego progu (np. 40 linii) wysyłać krótki podgląd (pierwsze/ostatnie kilka linii) inline + pełny output jako załącznik `.txt`. To jedna zmiana, a realnie rozwiązuje problem gęstości.

**5. Telegram sam dorzuca etykietę języka do `<pre>` (widać „html" przy bloku z `<script>`) — niespójnie, bo auto-detekcja.**
Sprawdziłem w dokumentacji Bot API: `<pre><code class="language-xxx">` pozwala jawnie wymusić język zamiast zdawać się na zgadywanie klienta. Wymuszenie neutralnego `language-text` na każdym bloku powinno ujednolicić wygląd — ale to zachowanie klienta (Telegram Desktop vs mobile mogą się różnić), więc traktowałbym to jako eksperyment do sprawdzenia na żywo, nie pewnik.

**6. Słownictwo ikon jest już w sumie sensowne (✅ ❌ ⏱ ⚠️), ale warto to spisać jako regułę** — i pilnować, żeby komunikaty systemowe daemona (start/stop, rate-limit, rejected) **celowo nie udawały** kształtu `$ komenda`, bo inaczej oko szuka nieistniejącej komendy.

## Priorytet

Punkty **1–4** dają największy efekt najmniejszym kosztem (1–2 to literalnie naprawa tego, co zepsułem; 3 i 4 to realna redukcja gęstości). Punkt 5 jest ciekawy, ale niepewny efektowo. Punkt 6 to w zasadzie już mamy, tylko spisanie zasady.