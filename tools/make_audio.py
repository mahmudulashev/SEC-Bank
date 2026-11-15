#!/usr/bin/env python3
"""
Dars ovozlarini yaratadi va lessons.js ni yozadi.

  python3 tools/make_audio.py                      # Mac ovozi: Serena (Premium)
  python3 tools/make_audio.py --voice "Ava (Premium)"
  python3 tools/make_audio.py --engine elevenlabs --list-voices
  python3 tools/make_audio.py --engine elevenlabs --voice-id <id>

ElevenLabs kaliti birinchi marta yashirin oynachada so'raladi va macOS Keychain'ga saqlanadi
(almashtirish: --reset-key). ELEVENLABS_API_KEY o'zgaruvchisi ham ishlaydi.

Manba: lessons/*.json  →  audio/<kod>-<nn>.(m4a|mp3)  +  lessons.js
Matn, ovoz yoki dvigatel o'zgarmagan sahnalar qayta yaratilmaydi (audio/manifest.json).
"""
import argparse, glob, hashlib, json, os, re, subprocess, sys, tempfile, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIO = os.path.join(ROOT, "audio")
MANIFEST = os.path.join(AUDIO, "manifest.json")


def spoken(text):
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text)


def duration(path):
    out = subprocess.run(["afinfo", path], capture_output=True, text=True).stdout
    m = re.search(r"estimated duration:\s*([\d.]+)", out)
    return round(float(m.group(1)), 2) if m else 0.0


def gen_say(text, voice, rate, out):
    with tempfile.TemporaryDirectory() as td:
        aiff = os.path.join(td, "a.aiff")
        cmd = ["say", "-v", voice, "-o", aiff]
        if rate:
            cmd += ["-r", str(rate)]
        subprocess.run(cmd + [text], check=True)
        subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", "-c", "1", "-b", "64000", aiff, out], check=True)


def el_request(path, key, body=None):
    req = urllib.request.Request("https://api.elevenlabs.io" + path, headers={"xi-api-key": key, "Content-Type": "application/json"},
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        hint = {401: "Kalit rad etildi yoki unga kerakli ruxsat berilmagan (API Keys sahifasida kalit ruxsatlarini tekshiring)."}.get(e.code, "")
        sys.exit(f"ElevenLabs xatosi {e.code} ({path.split('?')[0]}): {detail}\n{hint}")


KC_SERVICE, KC_ACCOUNT = "sec-bank-elevenlabs", "api-key"


def elevenlabs_key(reset=False):
    """Kalit tartibi: ELEVENLABS_API_KEY → macOS Keychain → yashirin oynacha (keyin Keychain'ga saqlanadi)."""
    env = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if env.startswith("sk_") and not reset:
        return env
    if not reset:
        r = subprocess.run(["security", "find-generic-password", "-s", KC_SERVICE, "-a", KC_ACCOUNT, "-w"],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip().startswith("sk_"):
            return r.stdout.strip()
    script = ('text returned of (display dialog "ElevenLabs API kalitini joylashtiring (sk_ bilan boshlanadi):" '
              'default answer "" with hidden answer with title "SEC Bank" buttons {"Bekor", "Saqlash"} default button "Saqlash")')
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    key = re.sub(r"\s", "", r.stdout)
    if r.returncode != 0 or not key:
        sys.exit("Kalit kiritilmadi.")
    if not key.startswith("sk_"):
        sys.exit("Bu kalit emas: haqiqiy kalit sk_ bilan boshlanadi. Saytdagi ID raqamini emas, yangi yaratilgan kalitni nusxalang.")
    subprocess.run(["security", "add-generic-password", "-U", "-s", KC_SERVICE, "-a", KC_ACCOUNT, "-w", key],
                   check=True, capture_output=True)
    print("✓ Kalit Keychain'ga saqlandi (keyingi safar so'ralmaydi).")
    return key


def gen_eleven(text, key, voice_id, model, out):
    data = el_request(f"/v1/text-to-speech/{voice_id}?output_format=mp3_44100_64", key,
                      {"text": text, "model_id": model, "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}})
    with open(out, "wb") as f:
        f.write(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["say", "elevenlabs"], default="say")
    ap.add_argument("--voice", default="Serena (Premium)", help="Mac ovozi (say -v '?')")
    ap.add_argument("--rate", type=int, default=0, help="say tezligi, so'z/daqiqa (0 = standart)")
    ap.add_argument("--voice-id", default="21m00Tcm4TlvDq8ikWAM", help="ElevenLabs voice_id")
    ap.add_argument("--model", default="eleven_multilingual_v2", help="ElevenLabs model_id")
    ap.add_argument("--list-voices", action="store_true", help="ElevenLabs ovozlari ro'yxati")
    ap.add_argument("--only", help="faqat shu darslar, masalan: 1a,2b")
    ap.add_argument("--reset-key", action="store_true", help="Keychain'dagi ElevenLabs kalitini almashtirish")
    a = ap.parse_args()

    key = ""
    if a.engine == "elevenlabs" or a.list_voices:
        key = elevenlabs_key(a.reset_key)
    if a.list_voices:
        for v in json.loads(el_request("/v1/voices", key))["voices"]:
            print(f'{v["voice_id"]}  {v["name"]}  {v.get("labels", {})}')
        return

    lessons = {}
    for p in sorted(glob.glob(os.path.join(ROOT, "lessons", "*.json"))):
        with open(p, encoding="utf-8") as f:
            lessons.update(json.load(f))

    os.makedirs(AUDIO, exist_ok=True)
    man = {}
    if os.path.exists(MANIFEST):
        with open(MANIFEST) as f:
            man = json.load(f)

    sig = f"say|{a.voice}|{a.rate}" if a.engine == "say" else f"el|{a.voice_id}|{a.model}"
    ext = "m4a" if a.engine == "say" else "mp3"
    only = set(a.only.split(",")) if a.only else None
    total = sum(len(v) for v in lessons.values())
    done = 0
    for code, scenes in lessons.items():
        for i, sc in enumerate(scenes):
            done += 1
            name = f"{code}-{i:02d}"
            text = spoken(sc["say"])
            h = hashlib.sha1(f"{sig}|{text}".encode()).hexdigest()[:12]
            old = man.get(name)
            if old and old["h"] == h and os.path.exists(os.path.join(AUDIO, old["f"])):
                continue
            if only and code not in only:
                continue
            fn = f"{name}.{ext}"
            out = os.path.join(AUDIO, fn)
            print(f"[{done}/{total}] {name}: {text[:60]}…", flush=True)
            if a.engine == "say":
                gen_say(text, a.voice, a.rate, out)
            else:
                gen_eleven(text, key, a.voice_id, a.model, out)
            man[name] = {"f": fn, "h": h, "d": duration(out)}
            with open(MANIFEST, "w") as f:
                json.dump(man, f, indent=0)

    audio = {code: [man.get(f"{code}-{i:02d}", {}) and {"f": man[f"{code}-{i:02d}"]["f"], "d": man[f"{code}-{i:02d}"]["d"]}
                    for i in range(len(scenes))] for code, scenes in lessons.items()}
    with open(os.path.join(ROOT, "lessons.js"), "w", encoding="utf-8") as f:
        f.write("/* tools/make_audio.py yaratgan, qo'lda tahrirlamang */\n")
        f.write("window.LESSONS_EN=" + json.dumps(lessons, ensure_ascii=False) + ";\n")
        f.write("window.AUDIO=" + json.dumps(audio, ensure_ascii=False) + ";\n")
    secs = sum(x["d"] for v in audio.values() for x in v if x)
    print(f"✓ {total} sahna, jami {secs/60:.1f} daqiqa ovoz. lessons.js yozildi.")


if __name__ == "__main__":
    main()
