# Appli REC — Relevé de Compte Copropriété

Application Streamlit de génération et de gestion des relevés de compte copropriétaires, avec imputation automatique des règlements sur la dette la plus ancienne.

---

## Description

Cette application permet à un gestionnaire de copropriété de :

- Importer un relevé de compte exporté depuis un logiciel comptable (format `.xlsx`)
- Visualiser l'ensemble des opérations (appels de fonds, règlements, régularisations)
- Sélectionner ou exclure des lignes à retenir dans le relevé final
- Recalculer automatiquement l'imputation des règlements et les soldes
- Ajouter manuellement des lignes supplémentaires (appels ou règlements)
- Exporter le relevé recalculé et les dettes non soldées au format Excel

> **Règle d'imputation** : chaque règlement est imputé en priorité sur la dette la plus ancienne (méthode FIFO chronologique).

---

## Prérequis

- Python 3.8 ou supérieur
- pip

---

## Installation

```bash
# Cloner ou télécharger le projet
cd appli-REC-releve-de-compte

# Installer les dépendances
pip install streamlit pandas openpyxl numpy
```

---

## Lancement

```bash
streamlit run app.py
```

L'application s'ouvre automatiquement dans votre navigateur à l'adresse `http://localhost:8501`.

---

## Format du fichier Excel attendu

Le fichier `.xlsx` importé doit contenir **deux feuilles** :

### Feuille 1 — `Relevé imputé`

| Colonne | Description |
|---|---|
| `Date` | Date de l'opération (format JJ/MM/AAAA) |
| `Libellé` | Intitulé de l'opération |
| `Débit (€)` | Montant appelé (appel de fonds, travaux…) |
| `Crédit (€)` | Montant réglé par le copropriétaire |
| `Imputé sur` | Détail de l'imputation du règlement |
| `Surplus (€)` | Éventuel trop-perçu |
| `Solde (€)` | Solde cumulé après l'opération |

### Feuille 2 — `Dettes non soldées`

| Colonne | Description |
|---|---|
| `Date` | Date de l'appel initial |
| `Libellé` | Intitulé de la dette |
| `Montant initial (€)` | Montant de l'appel d'origine |
| `Solde restant (€)` | Part non encore réglée |

---

## 🗂️ Fonctionnalités détaillées

### Onglet 1 — 📋 Relevé de compte

- **Import** du fichier Excel via le panneau latéral
- **Affichage ligne par ligne** avec code couleur :
  - 🔴 Débits (appels de fonds)
  - 🟢 Crédits (règlements)
- **Case à cocher** sur chaque ligne pour l'inclure ou l'exclure du calcul
- **Recalcul en temps réel** de l'imputation et des soldes à chaque modification
- **Filtres** par libellé (recherche textuelle) et par type d'opération
- **Boutons rapides** : Tout sélectionner / Tout désélectionner / Réinitialiser
- **Solde final** affiché avec indication visuelle (dette ou crédit)
- **Export Excel** du relevé recalculé, avec mise en forme professionnelle

### Onglet 2 — 📊 Dettes non soldées

- Recalcul automatique des dettes restantes après application des règlements actifs
- Tableau des postes non entièrement apurés avec solde restant
- Total des dettes en cours
- Export Excel des dettes non soldées

### Onglet 3 — ➕ Ajouter des lignes

- Formulaire de saisie manuelle d'une ligne (date, libellé, montant, type)
- Insertion automatique dans l'ordre chronologique
- Les lignes ajoutées sont immédiatement intégrées au recalcul
- Aperçu du relevé complet mis à jour

---

## 📤 Exports générés

| Fichier | Contenu |
|---|---|
| `releve_NOM_AAAAMMJJ.xlsx` | Relevé complet recalculé avec imputation et soldes |
| `dettes_NOM_AAAAMMJJ.xlsx` | Liste des dettes non soldées à la date d'export |

Les fichiers Excel exportés incluent :
- En-tête avec nom du copropriétaire et date de génération
- Mise en forme colorée (crédits en vert, débits en blanc)
- Colonnes dimensionnées automatiquement
- Solde final mis en évidence

---

## Structure du projet

```
appli-REC-releve-de-compte/
│
├── app.py          # Application principale Streamlit
├── README.md       # Documentation
└── exemple/
    └── releve_GUINOT_Jean-Charles.xlsx   # Fichier exemple
```

---

## Logique d'imputation

L'algorithme d'imputation fonctionne selon les étapes suivantes :

1. **Identification des dettes** : toutes les lignes de débit actives sont collectées et triées par date croissante.
2. **Application des règlements** : chaque crédit actif (dans l'ordre chronologique) est imputé successivement sur les dettes les plus anciennes jusqu'à épuisement du montant réglé.
3. **Calcul des soldes** : le solde cumulé est recalculé ligne par ligne en tenant compte uniquement des lignes actives.
4. **Dettes résiduelles** : les postes dont le solde restant est supérieur à 0,01 € sont listés dans l'onglet "Dettes non soldées".

> Cette méthode est conforme à la pratique comptable standard en copropriété (extinction de la dette la plus ancienne en premier).

---

## Auteur

Développé pour la gestion comptable de copropriété.  
Généré le 14/03/2026.

---

## Licence

Usage interne Amandine LAZZARINI AJASSOCIES— tous droits réservés.
