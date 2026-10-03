"""
LA VITRINE
----------
Tableau de bord de l'analyse financière de la commune, avec comparaison
à la strate démographique et simulateur de prospective sur 5 ans.

Les chiffres sont téléchargés par le coursier (fetch_data.py) à la première
visite, puis gardés en mémoire 7 jours. Passé ce délai, ils sont
re-téléchargés automatiquement : rien d'autre à programmer.

Pour analyser une autre commune : change CODE_INSEE ci-dessous.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import fetch_data

CODE_INSEE = "63113"  # CLERMONT-FERRAND (le code INSEE figure sur la page Wikipédia de la commune)
SEUIL_VIGILANCE, SEUIL_ALERTE = 8, 12  # capacité de désendettement, en années
BLEU, GRIS, ORANGE, ROUGE, VERT = "#1f4e79", "#9aa5b1", "#e69f00", "#c0392b", "#2e8b57"

st.set_page_config(page_title="Finances communales", page_icon="🏛️", layout="wide")


@st.cache_data(ttl=7 * 24 * 3600, show_spinner="Téléchargement des comptes sur data.ofgl.fr… (environ 30 secondes, seulement à la première visite)")
def charger(code_insee):
    return fetch_data.telecharger(code_insee)


try:
    df, tous, infos = charger(CODE_INSEE)
except Exception as erreur:
    st.error("Impossible de récupérer les données de l'OFGL pour le moment.")
    st.write("Copie le message ci-dessous et envoie-le à Claude pour qu'il corrige :")
    st.code(f"{type(erreur).__name__}: {erreur}")
    st.stop()
COMMUNE = infos["commune"]
STRATE = next(p for p in df["perimetre"].unique() if p != COMMUNE) if df["perimetre"].nunique() > 1 else None

# Tableaux larges : une ligne par année, une colonne par poste
montants = df.pivot_table(index=["perimetre", "annee"], columns="cle", values="montant").reset_index()
par_hab = df.pivot_table(index=["perimetre", "annee"], columns="cle", values="euros_hab").reset_index()


def col(t, cle):
    return t[cle] if cle in t else pd.Series(float("nan"), index=t.index)


# Ratios d'analyse financière
montants["taux_eb"] = col(montants, "eb") / col(montants, "rrf") * 100
montants["cap_desend"] = col(montants, "dette") / col(montants, "eb")
montants["poids_personnel"] = col(montants, "personnel") / col(montants, "drf") * 100
montants["taux_equip"] = col(montants, "equip") / col(montants, "rrf") * 100

c = montants[montants["perimetre"] == COMMUNE].sort_values("annee").reset_index(drop=True)
s = montants[montants["perimetre"] == STRATE].sort_values("annee").reset_index(drop=True)
c = c.dropna(subset=["rrf", "drf", "dette"])
annees = c["annee"].tolist()
derniere = c.iloc[-1]
precedente = c.iloc[-2] if len(c) > 1 else None


def meur(x):
    return f"{x / 1e6:,.1f} M€".replace(",", " ")


def zone(cd):
    if pd.isna(cd) or cd < 0:
        return "Épargne brute négative", ROUGE
    if cd < SEUIL_VIGILANCE:
        return "Situation saine", VERT
    if cd < SEUIL_ALERTE:
        return "Vigilance", ORANGE
    return "Zone d'alerte", ROUGE


# ---------------------------------------------------------------- En-tête
st.title(f"🏛️ Santé financière de {COMMUNE}")
st.caption(
    f"Budget principal · Source : OFGL (data.ofgl.fr), d'après les comptes de gestion DGFiP · "
    f"{infos['population']:,} habitants · Strate : {infos['strate']} · "
    f"Données mises à jour le {infos['mise_a_jour']}".replace(",", " ")
)

onglets = st.tabs(["📊 Vue d'ensemble", "⚖️ Comparaison avec la strate", "🔮 Simulateur de prospective", "📋 Données", "📖 Méthode"])

# ---------------------------------------------------------------- 1. Vue d'ensemble
with onglets[0]:
    an = int(derniere["annee"])
    st.subheader(f"Les chiffres clés {an}")

    def delta(cle, fmt):
        if precedente is None or pd.isna(precedente.get(cle)):
            return None
        return fmt(derniere[cle] - precedente[cle])

    k = st.columns(4)
    k[0].metric("Épargne brute", meur(derniere["eb"]), delta("eb", meur),
                help="Recettes de fonctionnement − dépenses de fonctionnement. C'est l'autofinancement dégagé par la gestion courante.")
    k[1].metric("Taux d'épargne brute", f"{derniere['taux_eb']:.1f} %",
                delta("taux_eb", lambda d: f"{d:+.1f} pt"),
                help="Épargne brute / recettes de fonctionnement. En dessous de 7–8 %, la marge de manœuvre devient faible.")
    libelle, couleur = zone(derniere["cap_desend"])
    k[2].metric("Capacité de désendettement", f"{derniere['cap_desend']:.1f} ans",
                delta("cap_desend", lambda d: f"{d:+.1f} an"), delta_color="inverse",
                help="Encours de dette / épargne brute : nombre d'années pour rembourser toute la dette en y consacrant toute l'épargne. Seuil d'alerte : 12 ans.")
    k[3].metric("Encours de dette", meur(derniere["dette"]), delta("dette", meur), delta_color="inverse")
    st.markdown(f"**Diagnostic {an} :** <span style='color:{couleur};font-weight:700'>{libelle}</span> "
                f"(capacité de désendettement de {derniere['cap_desend']:.1f} ans ; vigilance au-delà de "
                f"{SEUIL_VIGILANCE} ans, alerte au-delà de {SEUIL_ALERTE} ans).", unsafe_allow_html=True)

    g1, g2 = st.columns(2)
    with g1:
        st.markdown("**Recettes, dépenses et épargne de fonctionnement**")
        fig = go.Figure()
        fig.add_bar(x=c["annee"], y=c["rrf"] / 1e6, name="Recettes de fonctionnement", marker_color=BLEU)
        fig.add_bar(x=c["annee"], y=c["drf"] / 1e6, name="Dépenses de fonctionnement", marker_color=GRIS)
        fig.add_scatter(x=c["annee"], y=c["eb"] / 1e6, name="Épargne brute", mode="lines+markers",
                        line=dict(color=ORANGE, width=3))
        fig.update_layout(barmode="group", yaxis_title="M€", legend=dict(orientation="h", y=-0.2),
                          margin=dict(t=10), height=380)
        st.plotly_chart(fig, width="stretch")
    with g2:
        st.markdown("**Dette et capacité de désendettement**")
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_bar(x=c["annee"], y=c["dette"] / 1e6, name="Encours de dette (M€)", marker_color=BLEU, opacity=0.8)
        fig.add_scatter(x=c["annee"], y=c["cap_desend"], name="Capacité de désendettement (ans)",
                        mode="lines+markers", line=dict(color=ROUGE, width=3), secondary_y=True)
        fig.add_hline(y=SEUIL_ALERTE, line_dash="dash", line_color=ROUGE, secondary_y=True,
                      annotation_text="Seuil d'alerte 12 ans", annotation_position="top left")
        fig.update_yaxes(title_text="M€", secondary_y=False)
        fig.update_yaxes(title_text="années", secondary_y=True, rangemode="tozero")
        fig.update_layout(legend=dict(orientation="h", y=-0.2), margin=dict(t=10), height=380)
        st.plotly_chart(fig, width="stretch")

    if "equip" in c:
        st.markdown("**Investissement et son financement**")
        fig = go.Figure()
        fig.add_bar(x=c["annee"], y=c["equip"] / 1e6, name="Dépenses d'équipement", marker_color=BLEU)
        if "en" in c:
            fig.add_scatter(x=c["annee"], y=c["en"] / 1e6, name="Épargne nette (autofinancement)",
                            mode="lines+markers", line=dict(color=VERT, width=3))
        if "emprunts" in c:
            fig.add_scatter(x=c["annee"], y=c["emprunts"] / 1e6, name="Emprunts nouveaux",
                            mode="lines+markers", line=dict(color=ROUGE, width=3, dash="dot"))
        fig.update_layout(yaxis_title="M€", legend=dict(orientation="h", y=-0.2), margin=dict(t=10), height=360)
        st.plotly_chart(fig, width="stretch")

# ---------------------------------------------------------------- 2. Comparaison
with onglets[1]:
    if STRATE is None or s.empty:
        st.info("Les données de la strate ne sont pas disponibles.")
    else:
        communes_strate = int(df[df["perimetre"] == STRATE]["n_communes"].max())
        st.subheader(f"{COMMUNE} face aux communes de {infos['strate']}")
        st.caption(f"Moyenne pondérée des {communes_strate} communes de la strate (somme des montants / somme des populations).")
        an_comp = st.selectbox("Année", sorted(set(c["annee"]) & set(s["annee"]), reverse=True))

        postes = {
            "drf": "Dépenses de fonctionnement", "personnel": "Frais de personnel",
            "rrf": "Recettes de fonctionnement", "impots": "Impôts et taxes", "dgf": "DGF",
            "eb": "Épargne brute", "equip": "Dépenses d'équipement", "dette": "Encours de dette",
        }
        ph = par_hab[par_hab["annee"] == an_comp].set_index("perimetre")
        lignes = [(lib, ph.loc[COMMUNE, k], ph.loc[STRATE, k]) for k, lib in postes.items()
                  if k in ph and COMMUNE in ph.index and STRATE in ph.index]
        comp = pd.DataFrame(lignes, columns=["Poste", COMMUNE, "Strate"]).dropna()
        comp["Écart"] = (comp[COMMUNE] / comp["Strate"] - 1) * 100

        fig = go.Figure()
        fig.add_bar(y=comp["Poste"], x=comp[COMMUNE], name=COMMUNE, orientation="h", marker_color=BLEU,
                    text=comp[COMMUNE].round(0), textposition="outside")
        fig.add_bar(y=comp["Poste"], x=comp["Strate"], name="Moyenne de la strate", orientation="h",
                    marker_color=GRIS, text=comp["Strate"].round(0), textposition="outside")
        fig.update_layout(barmode="group", xaxis_title="€ par habitant", height=520,
                          yaxis=dict(autorange="reversed"), legend=dict(orientation="h", y=-0.12), margin=dict(t=10))
        st.plotly_chart(fig, width="stretch")

        st.markdown("**Ratios d'analyse financière**")
        rc = c[c["annee"] == an_comp].iloc[0]
        rs = s[s["annee"] == an_comp].iloc[0]
        ratios = pd.DataFrame({
            "Ratio": ["Taux d'épargne brute (%)", "Capacité de désendettement (années)",
                      "Poids des frais de personnel dans les dépenses de fonctionnement (%)",
                      "Effort d'équipement (% des recettes de fonctionnement)"],
            COMMUNE: [rc["taux_eb"], rc["cap_desend"], rc["poids_personnel"], rc["taux_equip"]],
            "Strate": [rs["taux_eb"], rs["cap_desend"], rs["poids_personnel"], rs["taux_equip"]],
        }).round(1)
        st.dataframe(ratios, hide_index=True, width="stretch")

        st.markdown("**Écarts à la strate (en € par habitant)**")
        st.dataframe(
            comp.round({COMMUNE: 0, "Strate": 0, "Écart": 1}).rename(columns={"Écart": "Écart (%)"}),
            hide_index=True, width="stretch",
        )

# ---------------------------------------------------------------- 3. Simulateur
with onglets[2]:
    base_an = int(derniere["annee"])
    st.subheader(f"Prospective financière {base_an + 1}–{base_an + 5}")
    st.caption(f"Point de départ : compte administratif {base_an}. Fais varier les hypothèses : "
               "les projections se recalculent instantanément.")

    # Valeurs de départ
    rrf0, drf0, dette0 = derniere["rrf"], derniere["drf"], derniere["dette"]
    impots0 = derniere["impots"] if pd.notna(derniere.get("impots")) else 0.0
    pers0 = derniere["personnel"] if pd.notna(derniere.get("personnel")) else 0.55 * drf0
    int0 = derniere["interets"] if pd.notna(derniere.get("interets")) else 0.02 * dette0
    remb0 = derniere["remb"] if pd.notna(derniere.get("remb")) else dette0 / 12
    equip_moy = c["equip"].tail(3).mean() if "equip" in c else 0.2 * rrf0
    equip_moy = equip_moy if pd.notna(equip_moy) and equip_moy > 0 else 0.2 * rrf0
    dette_prec = precedente["dette"] if precedente is not None else dette0
    taux_ex = min(max(int0 / dette_prec, 0.005), 0.06) if dette_prec else 0.02
    subv_hist = (c["rinv"] / c["equip"]).tail(3).mean() * 100 if "rinv" in c else 30
    subv_def = int(min(max(round(subv_hist / 5) * 5, 0), 70)) if pd.notna(subv_hist) else 30

    h1, h2, h3 = st.columns(3)
    with h1:
        st.markdown("**Recettes de fonctionnement**")
        g_imp = st.slider("Impôts et taxes (% par an)", -2.0, 8.0, 2.0, 0.5,
                          help="Revalorisation des bases + éventuelle hausse des taux de taxe foncière.")
        g_autres_r = st.slider("Autres recettes : dotations, produits des services (% par an)", -3.0, 5.0, 1.0, 0.5)
    with h2:
        st.markdown("**Dépenses de fonctionnement**")
        g_pers = st.slider("Frais de personnel (% par an)", 0.0, 8.0, 3.0, 0.5,
                           help="Glissement vieillesse-technicité, revalorisations du point d'indice, créations de postes.")
        g_autres_d = st.slider("Autres charges de gestion (% par an)", -2.0, 6.0, 2.0, 0.5,
                               help="Énergie, achats, subventions aux associations, contingents…")
    with h3:
        st.markdown("**Investissement et emprunt**")
        equip = st.slider("Dépenses d'équipement (M€ par an)", 0.0, float(round(equip_moy / 1e6 * 2.5)),
                          float(round(equip_moy / 1e6)), 1.0,
                          help=f"Par défaut : moyenne des 3 derniers exercices ({meur(equip_moy)}).") * 1e6
        subv = st.slider("Part financée par subventions et FCTVA (%)", 0, 70, subv_def, 5) / 100
        taux_new = st.slider("Taux des nouveaux emprunts (%)", 1.0, 6.0, 3.5, 0.25) / 100
        duree = st.slider("Durée des nouveaux emprunts (ans)", 10, 30, 20, 1)

    # Projection
    imp, autres_r = impots0, rrf0 - impots0
    pers, autres_d = pers0, drf0 - pers0 - int0
    stock_ex, prets = dette0, []  # dette existante ; nouveaux prêts [montant initial, restant]
    proj = []
    for i in range(1, 6):
        imp *= 1 + g_imp / 100
        autres_r *= 1 + g_autres_r / 100
        pers *= 1 + g_pers / 100
        autres_d *= 1 + g_autres_d / 100
        stock_new = sum(p[1] for p in prets)
        interets = taux_ex * stock_ex + taux_new * stock_new
        rrf = imp + autres_r
        drf = pers + autres_d + interets
        eb = rrf - drf
        remb_ex = min(remb0, stock_ex)
        remb_new = sum(min(p[0] / duree, p[1]) for p in prets)
        en = eb - remb_ex - remb_new
        besoin = equip * (1 - subv) - en
        emprunt = max(0.0, besoin)
        stock_ex -= remb_ex
        for p in prets:
            p[1] -= min(p[0] / duree, p[1])
        if emprunt > 0:
            prets.append([emprunt, emprunt])
        dette = stock_ex + sum(p[1] for p in prets)
        proj.append({
            "Année": base_an + i, "Recettes de fonctionnement": rrf, "Dépenses de fonctionnement": drf,
            "dont intérêts": interets, "Épargne brute": eb, "Remboursement du capital": remb_ex + remb_new,
            "Épargne nette": en, "Dépenses d'équipement": equip, "Emprunt nouveau": emprunt,
            "Encours de dette au 31/12": dette,
            "Taux d'épargne brute (%)": eb / rrf * 100,
            "Capacité de désendettement (ans)": dette / eb if eb > 0 else float("nan"),
        })
    p = pd.DataFrame(proj)
    fin = p.iloc[-1]

    libelle, couleur = zone(fin["Capacité de désendettement (ans)"])
    r = st.columns(4)
    r[0].metric(f"Épargne brute {int(fin['Année'])}", meur(fin["Épargne brute"]),
                meur(fin["Épargne brute"] - derniere["eb"]))
    teb_fin = fin["Taux d'épargne brute (%)"]
    r[1].metric(f"Taux d'épargne brute {int(fin['Année'])}", f"{teb_fin:.1f} %",
                f"{teb_fin - derniere['taux_eb']:+.1f} pt")
    cd_txt = "∞" if pd.isna(fin["Capacité de désendettement (ans)"]) else f"{fin['Capacité de désendettement (ans)']:.1f} ans"
    r[2].metric(f"Capacité de désendettement {int(fin['Année'])}", cd_txt)
    r[3].metric(f"Emprunts cumulés {base_an + 1}–{base_an + 5}", meur(p["Emprunt nouveau"].sum()))
    st.markdown(f"**Verdict :** avec ces hypothèses, la commune est en "
                f"<span style='color:{couleur};font-weight:700'>{libelle.lower()}</span> en {int(fin['Année'])}.",
                unsafe_allow_html=True)

    hist = c[["annee", "dette", "cap_desend"]].rename(columns={"annee": "Année"})
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_bar(x=hist["Année"], y=hist["dette"] / 1e6, name="Encours constaté (M€)", marker_color=GRIS)
    fig.add_bar(x=p["Année"], y=p["Encours de dette au 31/12"] / 1e6, name="Encours projeté (M€)", marker_color=BLEU)
    fig.add_scatter(x=list(hist["Année"]) + list(p["Année"]),
                    y=list(hist["cap_desend"]) + list(p["Capacité de désendettement (ans)"]),
                    name="Capacité de désendettement (ans)", mode="lines+markers",
                    line=dict(color=ROUGE, width=3), secondary_y=True)
    fig.add_vline(x=base_an + 0.5, line_dash="dot", line_color=GRIS)
    fig.add_hline(y=SEUIL_ALERTE, line_dash="dash", line_color=ROUGE, secondary_y=True,
                  annotation_text="Seuil d'alerte 12 ans", annotation_position="top left")
    fig.add_hline(y=SEUIL_VIGILANCE, line_dash="dot", line_color=ORANGE, secondary_y=True,
                  annotation_text="Vigilance 8 ans", annotation_position="bottom left")
    fig.update_yaxes(title_text="M€", secondary_y=False)
    fig.update_yaxes(title_text="années", secondary_y=True, rangemode="tozero")
    fig.update_layout(legend=dict(orientation="h", y=-0.2), margin=dict(t=10), height=420)
    st.plotly_chart(fig, width="stretch")

    st.markdown("**Tableau de prospective (M€)**")
    tableau = p.set_index("Année").T
    for ligne in tableau.index:
        if "(%)" in ligne or "(ans)" in ligne:
            tableau.loc[ligne] = tableau.loc[ligne].round(1)
        else:
            tableau.loc[ligne] = (tableau.loc[ligne] / 1e6).round(1)
    st.dataframe(tableau, width="stretch")
    st.caption("Hypothèses simplificatrices : la dette existante est amortie au rythme du dernier exercice ; "
               "les nouveaux emprunts sont amortis de façon constante ; le besoin de financement est "
               "intégralement couvert par l'emprunt (pas de mobilisation du fonds de roulement).")

# ---------------------------------------------------------------- 4. Données
with onglets[3]:
    st.subheader("Tous les agrégats OFGL du budget principal")
    unite = st.radio("Unité", ["Millions d'euros", "Euros par habitant"], horizontal=True)
    if unite == "Millions d'euros":
        t = tous.pivot_table(index="agregat", columns="annee", values="montant") / 1e6
    else:
        t = tous.pivot_table(index="agregat", columns="annee", values="euros_par_habitant")
    st.dataframe(t.round(1), width="stretch", height=600)
    st.download_button("Télécharger en CSV", tous.to_csv(index=False).encode("utf-8"),
                       file_name=f"ofgl_{infos['code_insee']}.csv", mime="text/csv")

# ---------------------------------------------------------------- 5. Méthode
with onglets[4]:
    st.subheader("Définitions et méthode")
    st.markdown(f"""
- **Épargne brute** = recettes réelles de fonctionnement − dépenses réelles de fonctionnement (intérêts compris).
  C'est l'autofinancement dégagé par la gestion courante.
- **Épargne nette** = épargne brute − remboursement du capital de la dette. C'est ce qui reste pour financer l'investissement.
- **Taux d'épargne brute** = épargne brute / recettes de fonctionnement.
- **Capacité de désendettement** = encours de dette / épargne brute. Repères usuels : moins de {SEUIL_VIGILANCE} ans,
  situation saine ; {SEUIL_VIGILANCE} à {SEUIL_ALERTE} ans, vigilance ; au-delà de {SEUIL_ALERTE} ans, zone d'alerte
  (plafond de référence de la loi de programmation des finances publiques 2018-2022 pour les communes).
- **Strate** : communes de même taille ({infos['strate']}). La moyenne est pondérée par la population.
- **Périmètre** : budget principal uniquement (hors budgets annexes), comptes de gestion DGFiP agrégés par l'OFGL.
- **Mise à jour** : le coursier interroge data.ofgl.fr chaque mois ; les comptes définitifs d'une année
  paraissent en général à l'été de l'année suivante.
""")
