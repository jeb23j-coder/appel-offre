"""Boîte de réception des critères sauvegardés depuis le site, sans quitter l'application.

Le site chiffre la sauvegarde (critères + code de sauvegarde) et l'envoie sur un canal ntfy privé.
Ce script lit les nouveaux messages du canal, les déchiffre avec la clé privée (secret CLE_PRIVEE),
vérifie le code (secret CODE_SAUVEGARDE), puis applique les critères avec criteres.py.

Format d'un message (JSON) : {"cle": RSA-OAEP(clé AES) en base64, "iv": base64, "donnees": AES-GCM(gzip(JSON)) en base64}
Contenu déchiffré : {"code": "...", "corps": "texte des critères (même format que les demandes GitHub)"}
"""
import base64
import gzip
import hmac
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
ETAT = RACINE / "data" / "boite.json"   # dernier message traité
TMP = os.environ.get("AO_TMP", "/tmp")


def dechiffrer(msg, cle_privee):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    cle = serialization.load_pem_private_key(cle_privee.encode(), password=None)
    aes = cle.decrypt(base64.b64decode(msg["cle"]), padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    brut = AESGCM(aes).decrypt(base64.b64decode(msg["iv"]), base64.b64decode(msg["donnees"]), None)
    return json.loads(gzip.decompress(brut).decode("utf-8"))


def messages(sujet, depuis):
    url = f"https://ntfy.sh/{sujet}/json?poll=1&since={depuis or 'all'}"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "radar-chantier"}), timeout=30) as r:
        for ligne in r.read().decode("utf-8").splitlines():
            if ligne.strip():
                m = json.loads(ligne)
                if m.get("event") == "message":
                    yield m


def main():
    sujet, cle_privee, code = os.environ.get("NTFY_CRITERES"), os.environ.get("CLE_PRIVEE"), os.environ.get("CODE_SAUVEGARDE")
    if not (sujet and cle_privee and code):
        sys.exit("Réglages manquants (NTFY_CRITERES, CLE_PRIVEE ou CODE_SAUVEGARDE)")
    etat = json.loads(ETAT.read_text(encoding="utf-8")) if ETAT.exists() else {}
    appliques = 0
    for m in messages(sujet, etat.get("dernier")):
        etat["dernier"] = m["id"]
        try:
            contenu = dechiffrer(json.loads(m["message"]), cle_privee)
        except Exception as e:
            print(f"Message {m['id']} illisible, ignoré : {type(e).__name__}")
            continue
        if not hmac.compare_digest(str(contenu.get("code", "")).strip().upper(), code.strip().upper()):
            print(f"Message {m['id']} : code de sauvegarde incorrect, ignoré")
            continue
        Path(TMP, "demande.md").write_text(contenu.get("corps", ""), encoding="utf-8")
        r = subprocess.run([sys.executable, str(RACINE / "scanner" / "criteres.py")], cwd=RACINE)
        print(f"Message {m['id']} : critères {'appliqués' if r.returncode == 0 else 'refusés'}")
        appliques += r.returncode == 0
    ETAT.write_text(json.dumps(etat), encoding="utf-8")
    Path(TMP, "criteres_appliques.txt").write_text(str(appliques), encoding="utf-8")
    print(f"Sauvegardes appliquées : {appliques}")


if __name__ == "__main__":
    main()
