import base64
import traceback
import re
import os
import json
import subprocess
import datetime

import uvicorn
import edge_tts
from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import HTMLResponse, FileResponse
from groq import Groq

# --- KONFIGURACJA ---
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eva_config.json")

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f)

config = load_config()
client = Groq(api_key=config.get("api_key", "dummy_key_to_prevent_crash"))

MODEL_LLM = "openai/gpt-oss-120b"
MODEL_STT = "whisper-large-v3-turbo"
DATA_FILE = "eva_data.json"

SYSTEM_PROMPT = """Jesteś EVA – polskim asystentem na macOS. Odpowiadaj krótko (maks. 2-3 zdania).
Na końcu swojej odpowiedzi MUSISZ dodać jeden z poniższych tagów:

1. Prośba o dodanie wydarzenia -> [ACTION: ADD_EVENT: Tytuł | YYYY-MM-DD | HH:MM]
2. Prośba o dodanie notatki -> [ACTION: ADD_NOTE: Treść notatki]
3. Prośba o USUNIĘCIE notatki -> [ACTION: DELETE_NOTE: Fragment]
4. Wyszukiwanie w internecie -> [ACTION: WEB_SEARCH: zapytanie]
5. Otwarcie ZEWNĘTRZNEJ aplikacji -> [ACTION: OPEN_APP: NazwaAplikacji]
6. Zamknięcie ZEWNĘTRZNEJ aplikacji -> [ACTION: CLOSE_APP: NazwaAplikacji]
7. Pytanie o mapę / szukanie restauracji -> [WIDGET: MAP: nazwa miejsca]
8. Pytanie o kalendarz -> [WIDGET: CALENDAR]
9. Prośba o pokazanie notatek -> [WIDGET: NOTES]
10. Prośba o pokazanie zdjęć -> [WIDGET: IMAGES: zapytanie]
11. Prośba o pokazanie obu okienek naraz -> [WIDGET: BOTH: nazwa miejsca]
12. Prośba o pokazanie WIELU okienek naraz (np. 'mapę, zdjęcia i kalendarz naraz') -> ZAWSZE I BEZWZGLĘDNIE musisz użyć tagu: [WIDGET: MULTI: MAP:zapytanie, IMAGES:zapytanie, CALENDAR, NOTES]
13. Zamknięcie okienek -> [WIDGET: NONE]

KRYTYCZNE ZASADY:
- NIGDY nie otwieraj systemowej aplikacji "Notatki", gdy użytkownik prosi o notatki w EVA. Zawsze używaj [WIDGET: NOTES].
- Jeśli użytkownik prosi o ZAMKNIĘCIE aplikacji, ZAWSZE użyj [ACTION: CLOSE_APP: NazwaAplikacji].
- NIGDY nie czytaj na głos zawartości notatek. Gdy wyświetlasz zdjęcia, powiedz np. "Oto znalezione zdjęcia".
- NIGDY nie wpisuj tagów w treści odpowiedzi.

Dla wydarzeń używaj daty {date}. Format HH:MM."""

app = FastAPI()
historia = []

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"events": [], "notes": []}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"events": [], "notes": []}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_mac_app_name(app_name):
    app_name = app_name.lower().strip()
    mapping = {
        "chrome": "Google Chrome", "google chrome": "Google Chrome", "opera": "Opera",
        "safari": "Safari", "calendar": "Calendar", "kalendarz": "Calendar",
        "notes": "Notes", "notatki": "Notes", "maps": "Maps", "mapy": "Maps",
        "spotify": "Spotify", "terminal": "Terminal", "vscode": "Visual Studio Code",
        "messages": "Messages", "wiadomosci": "Messages", "wiadomości": "Messages"
    }
    return mapping.get(app_name, app_name)

def otworz_aplikacje(app_name):
    real_name = get_mac_app_name(app_name)
    try:
        subprocess.run(["open", "-a", real_name], check=True, capture_output=True, text=True)
        return True, f"Otwieram {real_name}."
    except subprocess.CalledProcessError:
        try:
            subprocess.run(["open", "-a", app_name], check=True, capture_output=True, text=True)
            return True, f"Otwieram {app_name}."
        except subprocess.CalledProcessError:
            return False, f"Nie udało się otworzyć: {app_name}."

def zamknij_aplikacje(app_name):
    real_name = get_mac_app_name(app_name)
    try:
        script = f'tell application "{real_name}" to quit'
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        if res.returncode == 0:
            return True, f"Zamknięto {real_name}."
        else:
            subprocess.run(["killall", real_name], capture_output=True)
            return True, f"Zamknięto {real_name}."
    except Exception as e:
        return False, f"Błąd zamykania: {e}"

async def tts_base64(tekst: str) -> str:
    communicate = edge_tts.Communicate(tekst, "pl-PL-ZofiaNeural")
    audio_data = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]
    return base64.b64encode(audio_data).decode("utf-8") if audio_data else ""

async def generuj_odpowiedz(tekst: str) -> dict:
    historia.append({"role": "user", "content": tekst})
    try:
        today = datetime.date.today().isoformat()
        prompt = SYSTEM_PROMPT.replace("{date}", today)
        
        data = load_data()
        notes_str = "\n".join([f"- {n['text']}" for n in data['notes']]) or "Brak notatek."
        events_str = "\n".join([f"- {e['title']} ({e['date']} o {e['time']})" for e in data['events']]) or "Brak wydarzeń."
        prompt += f"\n\nAKTUALNE NOTATKI:\n{notes_str}\n\nAKTUALNE WYDARZENIA:\n{events_str}"

        response = client.chat.completions.create(
            model=MODEL_LLM,
            messages=[{"role": "system", "content": prompt}, *historia],
            temperature=0.6, max_tokens=300,
        )
        eva_tekst = response.choices[0].message.content.strip()

        action_results = []
        widget = None
        map_query = ""
        images_list = []
        multi_widgets = []

        # WEB_SEARCH
        search_match = re.search(r"\[\s*ACTION:\s*WEB_SEARCH:\s*(.*?)\]", eva_tekst)
        if search_match:
            query = search_match.group(1).strip()
            eva_tekst = re.sub(r"\[\s*ACTION:\s*WEB_SEARCH:.*?\]", "", eva_tekst).strip()
            try:
                from ddgs import DDGS
                results = list(DDGS().text(query, max_results=5))
                context = "".join([f"- {r.get('title', '')}: {r.get('body', '')}\n" for r in results])
                resp2 = client.chat.completions.create(
                    model=MODEL_LLM,
                    messages=[{"role": "system", "content": "Odpowiedz krótko po polsku na podstawie wyników."}, {"role": "user", "content": f"Pytanie: {tekst}\nWyniki:\n{context}"}]
                )
                eva_tekst = resp2.choices[0].message.content.strip()
                action_results.append({"ok": True, "message": "Przeszukano internet."})
            except Exception as e:
                action_results.append({"ok": False, "message": f"Błąd internetu: {e}"})

        # OPEN_APP
        open_apps = re.findall(r"\[\s*ACTION:\s*OPEN_APP:\s*(.*?)\]", eva_tekst)
        if open_apps:
            eva_tekst = re.sub(r"\[\s*ACTION:\s*OPEN_APP:.*?\]", "", eva_tekst).strip()
            for apps_str in open_apps:
                for app in re.split(r',|\s+i\s+|\s+oraz\s+', apps_str):
                    if app.strip():
                        ok, msg = otworz_aplikacje(app.strip())
                        action_results.append({"ok": ok, "message": msg})

        # CLOSE_APP
        close_apps = re.findall(r"\[\s*ACTION:\s*CLOSE_APP:\s*(.*?)\]", eva_tekst)
        if close_apps:
            eva_tekst = re.sub(r"\[\s*ACTION:\s*CLOSE_APP:.*?\]", "", eva_tekst).strip()
            for apps_str in close_apps:
                for app in re.split(r',|\s+i\s+|\s+oraz\s+', apps_str):
                    if app.strip():
                        ok, msg = zamknij_aplikacje(app.strip())
                        action_results.append({"ok": ok, "message": msg})

        # EVENTS
        event_match = re.search(r"\[\s*ACTION:\s*ADD_EVENT:\s*(.*?)\]", eva_tekst)
        if event_match:
            parts = [p.strip() for p in event_match.group(1).split("|")]
            if len(parts) == 3:
                data["events"].append({"title": parts[0], "date": parts[1], "time": parts[2]})
                data["events"].sort(key=lambda x: (x["date"], x["time"]))
                save_data(data)
                action_results.append({"ok": True, "message": "Dodano wydarzenie: " + parts[0]})
                widget = "calendar"
            eva_tekst = re.sub(r"\[\s*ACTION:\s*ADD_EVENT:.*?\]", "", eva_tekst).strip()

        # NOTES
        note_match = re.search(r"\[\s*ACTION:\s*ADD_NOTE:\s*(.*?)\]", eva_tekst)
        if note_match:
            note_text = note_match.group(1).strip().strip('"').strip("'")
            data["notes"].insert(0, {"text": note_text, "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M")})
            save_data(data)
            action_results.append({"ok": True, "message": "Zapisano notatkę."})
            widget = "notes"
            eva_tekst = re.sub(r"\[\s*ACTION:\s*ADD_NOTE:.*?\]", "", eva_tekst).strip()

        del_note_match = re.search(r"\[\s*ACTION:\s*DELETE_NOTE:\s*(.*?)\]", eva_tekst)
        if del_note_match:
            target = del_note_match.group(1).strip().strip('"').strip("'").lower()
            initial_len = len(data["notes"])
            data["notes"] = [n for n in data["notes"] if target not in n["text"].lower()]
            if len(data["notes"]) < initial_len:
                save_data(data)
                action_results.append({"ok": True, "message": "Usunięto notatkę."})
            else:
                action_results.append({"ok": False, "message": "Brak notatki."})
            widget = "notes"
            eva_tekst = re.sub(r"\[\s*ACTION:\s*DELETE_NOTE:.*?\]", "", eva_tekst).strip()

        # MULTI WIDGET
        multi_match = re.search(r"\[\s*WIDGET:\s*MULTI:\s*(.*?)\]", eva_tekst)
        if multi_match:
            widget = "multi"
            parts = multi_match.group(1).split(",")
            for p in parts:
                p = p.strip()
                if "MAP:" in p:
                    q = p.replace("MAP:", "").strip()
                    multi_widgets.append({"type": "map", "query": q})
                elif "IMAGES:" in p:
                    q = p.replace("IMAGES:", "").strip()
                    try:
                        from ddgs import DDGS
                        results = DDGS().images(q, max_results=4)
                        imgs = [r['image'] for r in results]
                        multi_widgets.append({"type": "images", "images": imgs})
                    except:
                        multi_widgets.append({"type": "images", "images": []})
                elif "CALENDAR" in p:
                    multi_widgets.append({"type": "calendar"})
                elif "NOTES" in p:
                    multi_widgets.append({"type": "notes"})
            eva_tekst = re.sub(r"\[\s*WIDGET:\s*MULTI:.*?\]", "", eva_tekst).strip()

        # OTHER WIDGETS
        map_match = re.search(r"\[\s*WIDGET:\s*MAP:\s*(.*?)\]", eva_tekst)
        if map_match:
            widget = "map"
            map_query = map_match.group(1).strip()
            eva_tekst = re.sub(r"\[\s*WIDGET:\s*MAP:.*?\]", "", eva_tekst).strip()

        img_match = re.search(r"\[\s*WIDGET:\s*IMAGES:\s*(.*?)\]", eva_tekst)
        if img_match:
            widget = "images"
            map_query = img_match.group(1).strip()
            eva_tekst = re.sub(r"\[\s*WIDGET:\s*IMAGES:.*?\]", "", eva_tekst).strip()
            try:
                from ddgs import DDGS
                results = DDGS().images(map_query, max_results=5)
                images_list = [r['image'] for r in results]
            except Exception as e:
                print("Błąd pobierania zdjęć:", e)

        if "[WIDGET: CALENDAR]" in eva_tekst:
            widget = "calendar"
            eva_tekst = eva_tekst.replace("[WIDGET: CALENDAR]", "").strip()
        if "[WIDGET: NOTES]" in eva_tekst:
            widget = "notes"
            eva_tekst = eva_tekst.replace("[WIDGET: NOTES]", "").strip()
        if "[WIDGET: NONE]" in eva_tekst:
            widget = "none"
            eva_tekst = eva_tekst.replace("[WIDGET: NONE]", "").strip()

        # CLEANUP
        eva_tekst = re.sub(r"\[\s*ACTION:.*?\]", "", eva_tekst)
        eva_tekst = re.sub(r"\[\s*WIDGET:.*?\]", "", eva_tekst)
        eva_tekst = eva_tekst.strip()
        eva_tekst = re.sub(r"^[\s,\.]+|[\s,\.]+$", "", eva_tekst)
        
        # --- FALLBACK: Wymuszenie okienek, jeśli model zapomniał tagu ---
        if widget is None and any(w in tekst.lower() for w in ["naraz", "wszystko", "tryb"]):
            widget = "multi"
            if "map" in tekst.lower(): multi_widgets.append({"type": "map", "query": "kebaby"})
            if "zdj" in tekst.lower():
                try:
                    from ddgs import DDGS
                    res = DDGS().images("kebaby", max_results=4)
                    multi_widgets.append({"type": "images", "images": [r['image'] for r in res]})
                except: multi_widgets.append({"type": "images", "images": []})
            if "kalendarz" in tekst.lower(): multi_widgets.append({"type": "calendar"})
            if "notat" in tekst.lower(): multi_widgets.append({"type": "notes"})

        if not eva_tekst:
            eva_tekst = "Wyświetlam."

        historia.append({"role": "assistant", "content": eva_tekst})
        audio_b64 = ""
        try:
            audio_b64 = await tts_base64(eva_tekst)
        except Exception as e:
            print("[TTS ERROR]", e)

        return {"eva_text": eva_tekst, "audio_b64": audio_b64, "actions": action_results, "widget": widget, "map_query": map_query, "images": images_list, "multi_widgets": multi_widgets}
    except Exception as e:
        historia.pop()
        raise RuntimeError("LLM: " + str(e))

@app.get("/orb.png")
async def get_orb():
    return FileResponse(os.path.join(os.path.dirname(os.path.abspath(__file__)), "orb.png"))

@app.get("/", response_class=HTMLResponse)
async def index():
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_frontend.html"), "r", encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_frontend.html"), "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

@app.post("/api/speak")
async def api_speak(request: Request):
    try:
        data = await request.json()
        text = data.get("text", "")
        if not text: return {"error": "Brak tekstu"}
        audio = await tts_base64(text)
        return {"audio_b64": audio}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/config")
async def get_config():
    cfg = load_config()
    return {"configured": bool(cfg.get("api_key")), "theme": cfg.get("theme", "dark")}

@app.post("/api/config")
async def set_config(request: Request):
    global client
    data = await request.json()
    cfg = load_config()
    
    if "api_key" in data and data["api_key"]:
        api_key = data["api_key"].strip()
        try:
            test_client = Groq(api_key=api_key)
            test_client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1
            )
            cfg["api_key"] = api_key
            client = test_client
        except Exception as e:
            return {"ok": False, "error": str(e)}
            
    if "theme" in data and data["theme"]:
        cfg["theme"] = data["theme"]
        
    save_config(cfg)
    return {"ok": True}

@app.get("/api/data")
async def get_data():
    return load_data()

@app.post("/chat_audio")
async def chat_audio(file: UploadFile = File(...)):
    try:
        audio_bytes = await file.read()
        if len(audio_bytes) < 1000: return {"user_text": "", "eva_text": "Za krótkie.", "audio_b64": ""}
        filename = file.filename or "audio.webm"
        out = client.audio.transcriptions.create(file=(filename, audio_bytes), model=MODEL_STT, language="pl", response_format="text", prompt="Transkrypcja mowy po polsku.")
        tekst = (out if isinstance(out, str) else out.text).strip()
        if not tekst or len(tekst) < 2: return {"user_text": "", "eva_text": "Nie usłyszałam.", "audio_b64": ""}
        res = await generuj_odpowiedz(tekst)
        res["user_text"] = tekst
        return res
    except Exception as e:
        return {"error": str(e)}

@app.post("/chat_text")
async def chat_text(request: Request):
    try:
        data = await request.json()
        tekst = (data.get("text") or "").strip()
        if not tekst: return {"error": "Puste"}
        res = await generuj_odpowiedz(tekst)
        res["user_text"] = tekst
        return res
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cert_file = os.path.join(base_dir, "cert.pem")
    key_file = os.path.join(base_dir, "key.pem")
    
    if os.path.exists(cert_file) and os.path.exists(key_file):
        print("🚀 EVA: https://127.0.0.1:8000")
        uvicorn.run(app, host="0.0.0.0", port=8000, ssl_keyfile=key_file, ssl_certfile=cert_file)
    else:
        print("🚀 EVA: http://127.0.0.1:8000")
        uvicorn.run(app, host="0.0.0.0", port=8000)
