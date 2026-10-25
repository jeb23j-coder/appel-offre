"""Courriels des profils : chiffrés dans le navigateur avec la clé publique du site (RSA-OAEP, SHA-256),
déchiffrés seulement par le robot des notifications avec la clé privée (secret GitHub CLE_PRIVEE).
Les fichiers publics ne contiennent jamais un courriel en clair."""
import base64
import os


def dechiffrer(texte_chiffre):
    cle_pem = os.environ.get("CLE_PRIVEE")
    if not texte_chiffre or not cle_pem:
        return None
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    cle = serialization.load_pem_private_key(cle_pem.encode(), password=None)
    clair = cle.decrypt(base64.b64decode(texte_chiffre),
                        padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    return clair.decode("utf-8").strip()


def masquer(courriel):
    """« jeb.23.j@gmail.com » -> « j•••@gmail.com »"""
    if not courriel or "@" not in courriel:
        return ""
    nom, dom = courriel.split("@", 1)
    return f"{nom[:1]}•••@{dom}"
