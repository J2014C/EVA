# EVA - Twój Cyfrowy Asystent AI 🤖

EVA to inteligentny asystent głosowy i tekstowy dzgięczący lokalnie na **macOS, Windows i Linux**. Projekt wykorzystuje modele językowe (LLM) oraz syntezę mowy (TTS) do interakcji z użytkownikiem, zarządzania notatkami, kalendarzem i wyszukiwania w internecie.

## 📸 Podgląd i zrjuty efranu

*(tbd)*

## ✨ Funkcje
- **Interfejs graficzny**: Nowoczesny wygląd z animowaną kulą reagującą na głos.
- **Tryb wielookienkowy**: Jednoczesne wyświetlanie mapy, zdjęci, kalendarza i notatek.
- **Ekran startowy**: Łatwa Konfiguracja klucza API i personalizacja motywu.
- **Asystent głosowy**: Rozpo'nawanie mowy (STT) i odpowiedzi głosowe (TTS).
- **Zarządzanie systemem**: Otwieranie i zamknięcie aplikacji za pomocą poleceń (działa na Mac, Windows i Linux).

## 🛠️ Wymagania
- Python 3.10+
- Klucz API Groq (darmowy plan wystarczy)

## 🚀 Instalacja i uruchamienie

1. Zinstaluj wymagane biblioteki:
   ```bash
   pip install fastapi uvicorn groq edge-tts python-multipart requests ddgs beautifulsoup4 cryptography
   ```

2. Uruchom serwer:
   ```bash
   python3 EVA.py   # macOS / Linux
   python EVA.py    # Windows
   ```

3. Otwórz w przeglądarce:
   ```
   https://127.0.0.1:8000
   ```

4. Przy pierwszym uruchomieniu aplikacja poprosi Cię o podanie klucza API Groq (możesz go wygenerować bezpłatnie na [console.groq.com](https://console.groq.com/keys)).

## 🔒 Bezpieczeństwo
Projekt nie zawiera na sztywno wpisanych kluczy API. Wszelkie dane konfiguracyjne oraz certyfikaty SSL są ignorowane przez system kontroli wersji (?.gitignore`).
