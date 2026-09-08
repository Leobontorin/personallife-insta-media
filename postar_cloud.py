# -*- coding: utf-8 -*-
"""
PERSONAL LIFE - Robo de postagem na NUVEM (GitHub Actions, cron 12h BRT).
Roda no runner do GitHub: PC do Leonardo pode estar desligado.

Fluxo:
 1. Fila = pasta fila/ deste repo (sincronizada pelo PC quando liga)
 2. Pega a imagem mais antiga (ordem de commit ~ nome), 1 post/dia (registro.json)
 3. Ajusta proporcao, salva em artes/pl_AAAAMMDD.jpg, commita, espera o Pages servir
 4. Publica via Graph API (secrets IG_TOKEN / IG_USER_ID)
 5. Remove da fila, atualiza registro.json e legendas.json (proxima), commita
Token: renovado pelo PC local (postar.py), que atualiza o secret IG_TOKEN via gh.
"""
import json, os, subprocess, sys, time
from datetime import date, datetime, timezone, timedelta
import requests
from PIL import Image

BRT = timezone(timedelta(hours=-3))
REPO_DIR = os.path.dirname(os.path.abspath(__file__))
FILA = os.path.join(REPO_DIR, "fila")
ARTES = os.path.join(REPO_DIR, "artes")
LEG = os.path.join(REPO_DIR, "legendas.json")
REG = os.path.join(REPO_DIR, "registro.json")
SITE_URL = "https://leobontorin.github.io/personallife-insta-media"
API = "https://graph.instagram.com/v23.0"
IMAGENS = (".png", ".jpg", ".jpeg", ".webp")

def log(m):
    print(f"[{datetime.now(BRT):%Y-%m-%d %H:%M:%S}] {m}", flush=True)

def fail(m):
    log("ERRO: " + m)
    sys.exit(1)

def git(*args):
    r = subprocess.run(["git", *args], cwd=REPO_DIR, capture_output=True, text=True)
    if r.returncode != 0:
        fail(f"git {args[0]}: {(r.stderr or r.stdout)[-300:]}")
    return r.stdout

def main():
    token = os.environ["IG_TOKEN"]
    ig_user = os.environ["IG_USER_ID"]
    hoje = datetime.now(BRT).date().isoformat()

    reg = json.load(open(REG, encoding="utf-8"))
    if any(p["data"] == hoje for p in reg["posts"]):
        log("Ja postou hoje. Nada a fazer.")
        return

    os.makedirs(FILA, exist_ok=True)
    fila = sorted(f for f in os.listdir(FILA) if f.lower().endswith(IMAGENS))
    if not fila:
        log("AVISO: fila/ VAZIA — ligar o PC pra sincronizar artes da pasta 'Postar insta'.")
        return
    if len(fila) <= 2:
        log(f"AVISO: so {len(fila)} arte(s) na fila.")
    arte = fila[0]

    banco = json.load(open(LEG, encoding="utf-8"))
    idx = banco["proxima"] % len(banco["legendas"])
    item = banco["legendas"][idx]
    caption = item["texto"].strip() + "\n.\n" + " ".join(item["hashtags"])

    img = Image.open(os.path.join(FILA, arte)).convert("RGB")
    w, h = img.size
    ratio = w / h
    if ratio < 0.8:
        nh = int(w / 0.8); top = (h - nh) // 2
        img = img.crop((0, top, w, top + nh))
    elif ratio > 1.91:
        nw = int(h * 1.91); left = (w - nw) // 2
        img = img.crop((left, 0, left + nw, h))
    if max(img.size) > 1440:
        img.thumbnail((1440, 1440), Image.LANCZOS)
    nome = f"pl_{datetime.now(BRT):%Y%m%d}.jpg"
    os.makedirs(ARTES, exist_ok=True)
    img.save(os.path.join(ARTES, nome), "JPEG", quality=92)

    git("add", "-A")
    git("-c", "user.name=PersonalLife Bot", "-c", "user.email=bontorin17@gmail.com",
        "commit", "-qm", f"media {hoje}")
    git("push", "-q")

    url = f"{SITE_URL}/artes/{nome}"
    for _ in range(60):
        try:
            if requests.head(url, timeout=20, allow_redirects=True).status_code == 200:
                break
        except requests.RequestException:
            pass
        time.sleep(5)
    else:
        fail(f"Pages nao serviu {url} em 5 min")
    log(f"Arte no ar: {url}")

    r = requests.post(f"{API}/{ig_user}/media",
                      data={"image_url": url, "caption": caption, "access_token": token},
                      timeout=90)
    j = r.json()
    if "id" not in j:
        fail(f"container falhou: {json.dumps(j)[:300]}")
    creation = j["id"]
    for _ in range(12):
        s = requests.get(f"{API}/{creation}", params={"fields": "status_code",
                         "access_token": token}, timeout=30).json()
        if s.get("status_code") == "FINISHED":
            break
        if s.get("status_code") == "ERROR":
            fail(f"container erro: {json.dumps(s)[:300]}")
        time.sleep(5)
    r = requests.post(f"{API}/{ig_user}/media_publish",
                      data={"creation_id": creation, "access_token": token}, timeout=90)
    j = r.json()
    if "id" not in j:
        fail(f"media_publish falhou: {json.dumps(j)[:300]}")
    media_id = j["id"]

    banco["proxima"] = (idx + 1) % len(banco["legendas"])
    json.dump(banco, open(LEG, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    reg["posts"].append({"data": hoje, "arquivo": arte, "media_id": media_id,
                         "legenda": idx, "origem": "cloud",
                         "postado_em": datetime.now(BRT).isoformat(timespec="seconds")})
    json.dump(reg, open(REG, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.remove(os.path.join(FILA, arte))
    git("add", "-A")
    git("-c", "user.name=PersonalLife Bot", "-c", "user.email=bontorin17@gmail.com",
        "commit", "-qm", f"postado {hoje} media {media_id}")
    git("push", "-q")
    log(f"POSTADO {arte} -> media {media_id} (legenda {idx}). Restam {len(fila)-1} na fila.")

if __name__ == "__main__":
    main()
