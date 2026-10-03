"""
LE COURSIER
-----------
Va chercher les comptes de la commune sur data.ofgl.fr (Observatoire des
finances et de la gestion publique locales). La page (app.py) l'appelle
elle-même et garde les chiffres en mémoire 7 jours : les mises à jour
sont donc automatiques, sans rien à programmer sur GitHub.

Il récupère aussi les comptes de toutes les communes de la même strate
démographique, pour pouvoir comparer.

Tu n'as pas besoin de modifier ce fichier : la commune se choisit dans app.py.
"""

import datetime
import io
import unicodedata

import pandas as pd
import requests

CODE_INSEE = "63113"  # valeur par défaut ; la commune affichée se choisit dans app.py
ANNEE_DEBUT = 2018

API = "https://data.ofgl.fr/api/explore/v2.1/catalog/datasets/ofgl-base-communes"
ENTETES = {"User-Agent": "tableau-de-bord-budget-communal (projet personnel, données publiques)"}

# Strates démographiques utilisées par la DGCL et l'OFGL
STRATES = [
    (0, 500, "moins de 500 hab."),
    (500, 2000, "500 à 2 000 hab."),
    (2000, 3500, "2 000 à 3 500 hab."),
    (3500, 5000, "3 500 à 5 000 hab."),
    (5000, 10000, "5 000 à 10 000 hab."),
    (10000, 20000, "10 000 à 20 000 hab."),
    (20000, 50000, "20 000 à 50 000 hab."),
    (50000, 100000, "50 000 à 100 000 hab."),
    (100000, 10**8, "100 000 hab. et plus"),
]

# Les postes dont on a besoin, et les libellés OFGL qui peuvent les désigner
# (écrits sans accents ni majuscules : la comparaison se fait sur une version simplifiée)
POSTES = {
    "rrf": ["recettes de fonctionnement"],
    "drf": ["depenses de fonctionnement"],
    "eb": ["epargne brute"],
    "en": ["epargne nette"],
    "remb": ["remboursements d'emprunts", "remboursement d'emprunts", "remboursements des emprunts"],
    "dette": ["encours de dette"],
    "personnel": ["frais de personnel"],
    "impots": ["impots et taxes"],
    "interets": ["charges financieres", "interets de la dette"],
    "equip": ["depenses d'equipement", "depenses d'investissement hors remboursements",
              "depenses d'investissement"],
    "rinv": ["recettes d'investissement hors emprunts", "recettes d'investissement"],
    "emprunts": ["emprunts hors gad", "emprunts"],
    "dgf": ["dotation globale de fonctionnement"],
}
INDISPENSABLES = ["rrf", "drf", "dette"]


def simplifier(texte):
    texte = unicodedata.normalize("NFKD", str(texte)).encode("ascii", "ignore").decode()
    return texte.lower().replace("’", "'").strip()


def trouver_libelles(libelles_disponibles):
    """Associe chaque poste au libellé OFGL correspondant (égalité d'abord, puis début de libellé)."""
    simples = {simplifier(l): l for l in libelles_disponibles}
    trouves = {}
    for cle, candidats in POSTES.items():
        for c in candidats:
            if c in simples:
                trouves[cle] = simples[c]
                break
        else:
            for c in candidats:
                match = sorted(s for s in simples if s.startswith(c))
                if match:
                    trouves[cle] = simples[match[0]]
                    break
    return trouves


def filtre_annees():
    return f"exer >= date'{ANNEE_DEBUT}-01-01'"


def comptes_commune():
    """Tous les agrégats du budget principal de la commune, toutes années."""
    params = {
        "select": "exer, com_name, agregat, montant, ptot, euros_par_habitant",
        "where": f'insee="{CODE_INSEE}" and type_de_budget="Budget principal" and {filtre_annees()}',
        "delimiter": ";",
    }
    r = requests.get(f"{API}/exports/csv", params=params, headers=ENTETES, timeout=300)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.content.decode("utf-8-sig")), sep=";")
    if df.empty:
        raise RuntimeError(f"Aucune donnée OFGL pour la commune {CODE_INSEE}.")
    df["annee"] = df["exer"].astype(str).str[:4].astype(int)
    return df


def comptes_strate(annee, libelles, pop_min, pop_max):
    """Sommes, sur toutes les communes de la strate, des postes utiles pour une année."""
    liste = ", ".join(f'"{l}"' for l in libelles)
    params = {
        "select": "agregat, sum(montant) as montant, sum(ptot) as population, count(*) as n_communes",
        "where": (
            f'type_de_budget="Budget principal" and agregat in ({liste}) '
            f"and ptot >= {pop_min} and ptot < {pop_max} "
            f"and exer >= date'{annee}-01-01' and exer < date'{annee + 1}-01-01'"
        ),
        "group_by": "agregat",
        "limit": 100,
    }
    r = requests.get(f"{API}/records", params=params, headers=ENTETES, timeout=300)
    r.raise_for_status()
    return pd.DataFrame(r.json().get("results", []))


def ajouter_postes_calcules(df):
    """Calcule l'épargne brute/nette si l'OFGL ne les fournit pas directement."""
    resultat = []
    for (perimetre, annee), g in df.groupby(["perimetre", "annee"]):
        m = g.set_index("cle")["montant"]
        pop = g.set_index("cle")["population"].get("rrf")
        ajouts = {}
        if "eb" not in m and {"rrf", "drf"} <= set(m.index):
            ajouts["eb"] = m["rrf"] - m["drf"]
        eb = m.get("eb", ajouts.get("eb"))
        if "en" not in m and eb is not None and "remb" in m:
            ajouts["en"] = eb - m["remb"]
        for cle, montant in ajouts.items():
            resultat.append({
                "perimetre": perimetre, "annee": annee, "cle": cle,
                "libelle": "(calculé)", "montant": montant, "population": pop,
                "euros_hab": montant / pop if pop else None,
                "n_communes": g["n_communes"].iloc[0],
            })
    return pd.concat([df, pd.DataFrame(resultat)], ignore_index=True)


def telecharger(code_insee=CODE_INSEE):
    """Renvoie (finances, tous_agregats, infos) pour une commune."""
    global CODE_INSEE
    CODE_INSEE = code_insee
    print(f"Comptes de la commune {CODE_INSEE}…")
    brut = comptes_commune()
    nom = brut["com_name"].dropna().iloc[-1]
    libelles_ofgl = sorted(brut["agregat"].dropna().unique())
    print(f"{nom} : {len(brut)} lignes, {len(libelles_ofgl)} agrégats, années {brut['annee'].min()}–{brut['annee'].max()}")
    print("Agrégats disponibles :", " | ".join(libelles_ofgl))

    correspondance = trouver_libelles(libelles_ofgl)
    manquants = [c for c in INDISPENSABLES if c not in correspondance]
    if manquants:
        raise RuntimeError(f"Postes introuvables dans les libellés OFGL : {manquants}. "
                           f"Libellés disponibles : {' | '.join(libelles_ofgl)}")
    print("Correspondances :", correspondance)

    # Strate de la commune, d'après sa population la plus récente
    population = brut.sort_values("annee")["ptot"].dropna().iloc[-1]
    pop_min, pop_max, strate = next(s for s in STRATES if s[0] <= population < s[1])
    print(f"Strate : {strate}")

    # Commune : on garde les postes utiles
    inverse = {v: k for k, v in correspondance.items()}
    commune = brut[brut["agregat"].isin(inverse)].copy()
    commune = pd.DataFrame({
        "perimetre": nom,
        "annee": commune["annee"],
        "cle": commune["agregat"].map(inverse),
        "libelle": commune["agregat"],
        "montant": commune["montant"],
        "population": commune["ptot"],
        "euros_hab": commune["euros_par_habitant"],
        "n_communes": 1,
    })

    # Strate : une requête par année
    morceaux = []
    for annee in sorted(commune["annee"].unique()):
        s = comptes_strate(int(annee), list(inverse), pop_min, pop_max)
        if s.empty:
            continue
        morceaux.append(pd.DataFrame({
            "perimetre": f"Moyenne strate {strate}",
            "annee": annee,
            "cle": s["agregat"].map(inverse),
            "libelle": s["agregat"],
            "montant": s["montant"],
            "population": s["population"],
            "euros_hab": s["montant"] / s["population"],
            "n_communes": s["n_communes"],
        }))
        print(f"Strate {annee} : {int(s['n_communes'].max())} communes")

    df = pd.concat([commune] + morceaux, ignore_index=True)
    df = ajouter_postes_calcules(df).sort_values(["perimetre", "annee", "cle"])

    tous = brut[["annee", "agregat", "montant", "euros_par_habitant"]].sort_values(["annee", "agregat"])
    infos = {
        "commune": nom, "code_insee": CODE_INSEE, "strate": strate,
        "population": int(population), "mise_a_jour": datetime.date.today().isoformat(),
    }
    print(f"{len(df)} lignes prêtes")
    return df, tous, infos


if __name__ == "__main__":
    # Test rapide sur ton ordinateur : python fetch_data.py
    finances, tous, infos = telecharger()
    print(infos)
