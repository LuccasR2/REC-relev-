import streamlit as st
import pandas as pd
import io
from datetime import date
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

st.set_page_config(page_title="Relevé Copropriété", page_icon="🏢", layout="wide")

st.markdown("""
<style>
    .block-container { padding-top: 1.5rem; }
    h1 { color: #1a3a5c; }
    .info-box {
        background: #eff6ff; border-left: 4px solid #3b82f6;
        padding: 0.8rem 1rem; border-radius: 6px;
        font-size: 0.85rem; color: #1e3a5f; margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────
# CONSTANTES
# ─────────────────────────────────────────────────────────────

# Mots-clés identifiant un encaissement réel du copropriétaire
MOTS_REGLEMENT = ["règlement", "virement", "rglt", "chèque", "cheque"]

# Mots-clés identifiant une écriture comptable d'apurement (contrepartie
# de la répartition de l'exercice clos) — elles affectent le solde du
# compte mais NE constituent PAS un règlement imputable sur les dettes.
MOTS_COMPTABLE = [
    "régularisation", "regularisation",
    "remboursement",
    "annul.", "annulation",
    "r.a.n.", "ran opérations", "ran tvx",
    "répartition des dépenses",
]


def nature(libelle: str) -> str:
    """Retourne 'reglement', 'comptable' ou 'appel'."""
    lib = libelle.lower()
    if any(k in lib for k in MOTS_REGLEMENT):
        return "reglement"
    if any(k in lib for k in MOTS_COMPTABLE):
        return "comptable"
    return "appel"


# ─────────────────────────────────────────────────────────────
# LOGIQUE PRINCIPALE
# ─────────────────────────────────────────────────────────────

def traiter_releve(df_raw: pd.DataFrame):
    """
    Pour chaque règlement (crédit réel), éteint les dettes (débits d'appel)
    en commençant toujours par la plus ancienne, jusqu'à épuisement du montant.
    Les écritures comptables (régularisations, remboursements de provisions…)
    ne participent pas à l'imputation.
    """
    df = df_raw.copy()
    df["date"]   = pd.to_datetime(df["date"])
    df["debit"]  = pd.to_numeric(df["debit"],  errors="coerce").fillna(0).round(2)
    df["credit"] = pd.to_numeric(df["credit"], errors="coerce").fillna(0).round(2)
    df["nature"] = df["libelle"].apply(nature)
    df = df.sort_values("date", kind="stable").reset_index(drop=True)

    # Pool de dettes : uniquement les débits d'appel, triés par date croissante
    dettes = []
    for i, row in df.iterrows():
        if row["debit"] > 0 and row["nature"] == "appel":
            dettes.append({
                "idx":     i,
                "date":    row["date"].date(),
                "libelle": row["libelle"],
                "montant": row["debit"],
                "solde":   row["debit"],
            })
    # Tri par ancienneté (puis ordre d'apparition en cas d'égalité)
    dettes.sort(key=lambda d: (d["date"], d["idx"]))

    # Colonnes résultat
    df["impute_sur"] = ""
    df["surplus"]    = 0.0

    for i, row in df.iterrows():
        if row["credit"] <= 0:
            continue

        if row["nature"] == "comptable":
            df.at[i, "impute_sur"] = "Écriture comptable (apurement exercice)"
            continue

        # Règlement réel → on éteint les dettes les plus anciennes
        restant = round(row["credit"], 2)
        detail  = []

        for d in dettes:
            if restant < 0.01:
                break
            if d["solde"] < 0.01:
                continue
            applique = round(min(restant, d["solde"]), 2)
            detail.append(f"{d['libelle'][:45]} ({applique:.2f}€)")
            d["solde"] = round(d["solde"] - applique, 2)
            restant    = round(restant - applique, 2)

        df.at[i, "impute_sur"] = "; ".join(detail) if detail else "—"
        df.at[i, "surplus"]    = restant

    df["solde_courant"] = (df["debit"] - df["credit"]).cumsum().round(2)
    return df, dettes


# ─────────────────────────────────────────────────────────────
# EXPORT EXCEL
# ─────────────────────────────────────────────────────────────

def export_xlsx(df: pd.DataFrame, dettes: list, proprietaire: str) -> io.BytesIO:
    wb  = Workbook()
    ws  = wb.active
    ws.title = "Relevé imputé"

    thin = Side(border_style="thin", color="D1D5DB")
    brd  = Border(left=thin, right=thin, top=thin, bottom=thin)
    fill_hdr  = PatternFill("solid", fgColor="1E3A5F")
    fill_pair = PatternFill("solid", fgColor="F3F4F6")
    font_hdr  = Font(bold=True, color="FFFFFF", name="Calibri", size=10)
    font_norm = Font(name="Calibri", size=10)
    center    = Alignment(horizontal="center", vertical="center", wrap_text=True)
    gauche    = Alignment(horizontal="left",   vertical="center", wrap_text=True)

    # Titre
    ws.merge_cells("A1:G1")
    ws["A1"] = f"RELEVÉ DE COMPTE — {proprietaire.upper()}"
    ws["A1"].font = Font(bold=True, name="Calibri", size=13, color="1E3A5F")
    ws["A1"].alignment = center

    ws.merge_cells("A2:G2")
    ws["A2"] = f"Règlement par extinction de la dette la plus ancienne — généré le {date.today().strftime('%d/%m/%Y')}"
    ws["A2"].font = Font(italic=True, name="Calibri", size=9, color="6B7280")
    ws["A2"].alignment = center

    headers = ["Date", "Libellé", "Débit (€)", "Crédit (€)", "Imputé sur", "Surplus (€)", "Solde (€)"]
    for col, h in enumerate(headers, 1):
        c = ws.cell(row=4, column=col, value=h)
        c.fill = fill_hdr; c.font = font_hdr
        c.alignment = center; c.border = brd

    for i, (_, row) in enumerate(df.iterrows(), 5):
        ws.cell(row=i, column=1, value=row["date"].strftime("%d/%m/%Y")).alignment = center
        ws.cell(row=i, column=2, value=row["libelle"]).alignment = gauche
        d = ws.cell(row=i, column=3, value=row["debit"] if row["debit"] > 0 else None)
        d.number_format = '#,##0.00'
        c = ws.cell(row=i, column=4, value=row["credit"] if row["credit"] > 0 else None)
        c.number_format = '#,##0.00'
        ws.cell(row=i, column=5, value=row["impute_sur"]).alignment = gauche
        s = ws.cell(row=i, column=6, value=row["surplus"] if row["surplus"] > 0 else None)
        s.number_format = '#,##0.00'
        sc = ws.cell(row=i, column=7, value=row["solde_courant"])
        sc.number_format = '#,##0.00'
        sc.font = Font(name="Calibri", size=10, bold=True,
                       color="C00000" if row["solde_courant"] > 0 else "006400")
        for col in range(1, 8):
            ws.cell(row=i, column=col).font   = font_norm if col != 7 else sc.font
            ws.cell(row=i, column=col).border = brd
            if i % 2 == 0:
                ws.cell(row=i, column=col).fill = fill_pair

    for col, w in enumerate([14, 50, 13, 13, 60, 13, 13], 1):
        ws.column_dimensions[get_column_letter(col)].width = w

    # Onglet dettes restantes
    ws2 = wb.create_sheet("Dettes non soldées")
    ws2["A1"] = "DETTES NON SOLDÉES"
    ws2["A1"].font = Font(bold=True, name="Calibri", size=12, color="C00000")
    for col, h in enumerate(["Date", "Libellé", "Montant initial (€)", "Solde restant (€)"], 1):
        c = ws2.cell(row=2, column=col, value=h)
        c.fill = PatternFill("solid", fgColor="C00000")
        c.font = Font(bold=True, color="FFFFFF", name="Calibri")
        c.border = brd
    for i, d in enumerate([x for x in dettes if x["solde"] > 0.01], 3):
        dt = d["date"].strftime("%d/%m/%Y") if hasattr(d["date"], "strftime") else str(d["date"])
        ws2.cell(row=i, column=1, value=dt)
        ws2.cell(row=i, column=2, value=d["libelle"])
        ws2.cell(row=i, column=3, value=d["montant"]).number_format = '#,##0.00'
        ws2.cell(row=i, column=4, value=d["solde"]).number_format   = '#,##0.00'
    for col, w in enumerate([14, 55, 20, 18], 1):
        ws2.column_dimensions[get_column_letter(col)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ─────────────────────────────────────────────────────────────
# INTERFACE
# ─────────────────────────────────────────────────────────────

st.title("🏢 Relevé de Compte Copropriété")
st.markdown(
    '<div class="info-box">Chaque règlement (virement, chèque…) éteint les dettes '
    'en commençant par la <b>plus ancienne</b>. Les régularisations et remboursements '
    'de provisions sont des écritures comptables d\'apurement : elles ne participent '
    'pas à l\'imputation.</div>',
    unsafe_allow_html=True
)

col_up, col_name = st.columns([3, 2])
with col_up:
    uploaded = st.file_uploader(
        "📂 Importer le relevé brut (.xlsx) — colonnes : Date | Libellé | débit | crédit",
        type=["xlsx"]
    )
with col_name:
    proprietaire = st.text_input("Nom du copropriétaire", value="GUINOT Jean-Charles")

if not uploaded:
    st.info("👆 Importez votre fichier Excel pour démarrer l'analyse.")
    with st.expander("ℹ️ Format attendu"):
        st.markdown("""
| Date | Libellé | débit | crédit |
|------|---------|-------|--------|
| 01/01/2024 | 1er appel de fonds 2024 | 477.23 | 0 |
| 16/01/2024 | Virement GUINOT | 0 | 477.23 |

- **Débit** = appels de fonds, travaux, charges…
- **Crédit** = règlements reçus (virement, chèque) ou écritures comptables
        """)
    st.stop()

# Lecture et normalisation
try:
    df_raw = pd.read_excel(uploaded, header=0)
    df_raw.columns = [str(c).strip() for c in df_raw.columns]
    rename = {}
    for c in df_raw.columns:
        cl = c.lower()
        if "date" in cl:                               rename[c] = "date"
        elif "lib" in cl:                              rename[c] = "libelle"
        elif "éb" in cl or "deb" in cl or cl == "db": rename[c] = "debit"
        elif "éd" in cl or "cr" in cl or cl == "cd":  rename[c] = "credit"
    df_raw = df_raw.rename(columns=rename)[["date","libelle","debit","credit"]]
    df_raw = df_raw.dropna(subset=["date"])
except Exception as e:
    st.error(f"Impossible de lire le fichier : {e}")
    st.stop()

df_result, dettes = traiter_releve(df_raw)

# Métriques
total_appele = df_result["debit"].sum()
total_regle  = df_result["credit"].sum()
solde_final  = df_result["solde_courant"].iloc[-1]
dettes_ouv   = [d for d in dettes if d["solde"] > 0.01]
reste_du     = sum(d["solde"] for d in dettes_ouv)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total appelé",        f"{total_appele:,.2f} €")
c2.metric("Total réglé",         f"{total_regle:,.2f} €")
c3.metric("Solde du compte",     f"{solde_final:,.2f} €",
          delta="⚠️ Débiteur" if solde_final > 0 else "✅ Soldé",
          delta_color="inverse")
c4.metric("Dettes non soldées",  f"{len(dettes_ouv)} poste(s) — {reste_du:,.2f} €")

st.divider()

tab1, tab2 = st.tabs(["📋 Relevé complet", "🔴 Dettes non soldées"])

with tab1:
    df_display = df_result[["date","libelle","debit","credit","impute_sur","surplus","solde_courant"]].copy()
    df_display["date"] = df_display["date"].dt.strftime("%d/%m/%Y")
    df_display.columns = ["Date","Libellé","Débit (€)","Crédit (€)","Imputé sur","Surplus (€)","Solde (€)"]
    df_display["Débit (€)"]   = df_display["Débit (€)"].replace(0, None)
    df_display["Crédit (€)"]  = df_display["Crédit (€)"].replace(0, None)
    df_display["Surplus (€)"] = df_display["Surplus (€)"].replace(0, None)

    def color_solde(val):
        if isinstance(val, (int, float)):
            if val > 0: return "color:#dc2626;font-weight:bold"
            if val < 0: return "color:#16a34a;font-weight:bold"
        return ""

    st.dataframe(
        df_display.style
            .applymap(color_solde, subset=["Solde (€)"])
            .format({
                "Débit (€)":   lambda x: f"{x:,.2f} €" if pd.notna(x) else "",
                "Crédit (€)":  lambda x: f"{x:,.2f} €" if pd.notna(x) else "",
                "Surplus (€)": lambda x: f"{x:,.2f} €" if pd.notna(x) else "",
                "Solde (€)":   lambda x: f"{x:,.2f} €" if pd.notna(x) else "",
            }),
        use_container_width=True,
        hide_index=True,
        height=600
    )

with tab2:
    if dettes_ouv:
        st.error(f"⚠️ {len(dettes_ouv)} dette(s) non soldée(s) — total restant dû : **{reste_du:,.2f} €**")
        df_rem = pd.DataFrame(dettes_ouv)[["date","libelle","montant","solde"]]
        df_rem.columns = ["Date","Libellé","Montant initial (€)","Solde restant (€)"]
        df_rem["Date"] = pd.to_datetime(df_rem["Date"]).dt.strftime("%d/%m/%Y")
        st.dataframe(
            df_rem.style.format({
                "Montant initial (€)": "{:,.2f} €",
                "Solde restant (€)":   "{:,.2f} €"
            }),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.success("✅ Toutes les dettes sont soldées !")

st.divider()
xlsx_buf = export_xlsx(df_result, dettes, proprietaire)
st.download_button(
    "📥 Télécharger le relevé imputé (.xlsx)",
    data=xlsx_buf,
    file_name=f"releve_{proprietaire.replace(' ','_')}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary",
    use_container_width=True
)
