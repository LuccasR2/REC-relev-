import streamlit as st
import pandas as pd
import io
from datetime import date
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

st.set_page_config(page_title="Relevé Copropriété – Art. 1342-10", page_icon="🏢", layout="wide")

st.markdown("""
<style>
    .block-container { padding-top: 1.5rem; }
    h1 { color: #1a3a5c; }
    .law-box {
        background: #fefce8; border-left: 4px solid #ca8a04;
        padding: 0.8rem 1rem; border-radius: 6px;
        font-size: 0.85rem; color: #713f12; margin-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def detect_category(libelle: str) -> str:
    lib = libelle.lower()
    if any(k in lib for k in ["alur", "fonds travaux", "cotisation"]):
        return "Fonds travaux ALUR"
    if any(k in lib for k in ["travaux", "réfect", "sécurité", "urgents", "diagnos",
                                "enedis", "veolia", "france travaux", "plancher",
                                "colonne", "honoraire", "publication"]):
        return "Travaux"
    if any(k in lib for k in ["appel", "charges", "provisions", "ran", "r.a.n", "budget"]):
        return "Charges courantes"
    return "Autre"

PRIORITY = {"Charges courantes": 1, "Travaux": 2, "Fonds travaux ALUR": 3, "Autre": 4}


def impute_art1342(debts_pool, payment_amount, payment_date):
    """Art. 1342-10 : dettes échues d'abord, par priorité, ancienneté, puis proportionnel."""
    open_debts = [d for d in debts_pool if d["solde"] > 0.001]
    echues     = [d for d in open_debts if d["date"] <= payment_date]
    non_echues = [d for d in open_debts if d["date"] >  payment_date]

    def sort_key(d):
        # Ancienneté prime toujours : la dette la plus ancienne s'éteint en premier.
        # En cas d'égalité de date, on respecte l'ordre d'apparition dans le relevé.
        return (d["date"], d["idx"])

    echues.sort(key=sort_key)
    non_echues.sort(key=sort_key)
    ordered = echues + non_echues

    remaining = round(payment_amount, 2)
    imputations = []

    for d in ordered:
        if remaining < 0.01:
            break
        applied = round(min(remaining, d["solde"]), 2)
        imputations.append({
            "dette_idx": d["idx"],
            "dette_lib": d["libelle"],
            "dette_date": d["date"],
            "montant": applied
        })
        d["solde"] = round(d["solde"] - applied, 2)
        remaining = round(remaining - applied, 2)

    return imputations, remaining


def is_reglement_reel(libelle: str) -> bool:
    """
    Retourne True uniquement pour les encaissements réels du copropriétaire
    (virement, chèque, prélèvement…).
    Les régularisations, remboursements de provisions et annulations sont des
    écritures comptables d'apurement (contrepartie de la répartition de l'exercice
    clos) : elles ne constituent PAS des règlements imputables selon l'Art. 1342-10.
    """
    lib = libelle.lower()
    return any(k in lib for k in [
        "règlement", "virement", "rglt", "chèque", "cheque",
    ])


def is_ecriture_comptable(libelle: str) -> bool:
    """
    Écritures d'apurement comptable : régularisations, remboursements de provisions,
    annulations, R.A.N. Elles affectent le solde du compte mais ne s'imputent pas
    sur les dettes au sens de l'Art. 1342-10.
    """
    lib = libelle.lower()
    return any(k in lib for k in [
        "régularisation", "regularisation",
        "remboursement", "annul.", "annulation",
        "r.a.n.", "ran opérations", "ran tvx",
        "répartition des dépenses",
    ])


def build_full_ledger(df_raw: pd.DataFrame):
    df = df_raw.copy()
    df["date"]   = pd.to_datetime(df["date"])
    df["debit"]  = pd.to_numeric(df["debit"],  errors="coerce").fillna(0).round(2)
    df["credit"] = pd.to_numeric(df["credit"], errors="coerce").fillna(0).round(2)
    df["categorie"] = df["libelle"].apply(detect_category)
    df = df.sort_values(["date", "debit"], ascending=[True, False]).reset_index(drop=True)

    # Constitue le pool de dettes (appels, travaux, charges — hors écritures comptables)
    debts_pool = []
    for i, row in df.iterrows():
        if row["debit"] > 0 and not is_ecriture_comptable(row["libelle"]):
            debts_pool.append({
                "idx": i,
                "date": row["date"].date(),
                "libelle": row["libelle"],
                "categorie": row["categorie"],
                "montant": row["debit"],
                "solde": row["debit"]
            })

    df["impute_sur"] = ""
    df["surplus"]    = 0.0
    df["type_ligne"] = ""

    # Rejoue dans l'ordre chronologique
    for i, row in df.iterrows():
        if row["credit"] > 0:
            if is_ecriture_comptable(row["libelle"]):
                # Écriture comptable : impact solde uniquement, pas d'imputation Art. 1342-10
                df.at[i, "impute_sur"] = "Écriture comptable (apurement exercice)"
                df.at[i, "type_ligne"] = "comptable"
            else:
                # Règlement réel → imputation Art. 1342-10
                imps, surplus = impute_art1342(debts_pool, row["credit"], row["date"].date())
                detail = "; ".join(
                    f"{imp['dette_lib'][:40]} ({imp['montant']:.2f}\u20ac)" for imp in imps
                ) if imps else "—"
                df.at[i, "impute_sur"] = detail
                df.at[i, "surplus"]    = surplus
                df.at[i, "type_ligne"] = "règlement"

    df["solde_courant"] = (df["debit"] - df["credit"]).cumsum().round(2)
    return df, debts_pool


def color_solde(val):
    if isinstance(val, (int, float)):
        if val > 0:   return "color: #dc2626; font-weight: bold"
        if val < 0:   return "color: #16a34a; font-weight: bold"
    return ""


def export_xlsx(df: pd.DataFrame, proprietaire: str, debts_pool: list) -> io.BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = "Relevé imputé"

    thin = Side(border_style="thin", color="D1D5DB")
    brd  = Border(left=thin, right=thin, top=thin, bottom=thin)
    hdr_fill = PatternFill("solid", fgColor="1E3A5F")
    hdr_font = Font(bold=True, color="FFFFFF", name="Calibri", size=10)
    norm     = Font(name="Calibri", size=10)
    center   = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left_al  = Alignment(horizontal="left",   vertical="center", wrap_text=True)

    ws.merge_cells("A1:H1")
    ws["A1"] = f"RELEVÉ DE COMPTE — {proprietaire.upper()}"
    ws["A1"].font      = Font(bold=True, name="Calibri", size=13, color="1E3A5F")
    ws["A1"].alignment = center

    ws.merge_cells("A2:H2")
    ws["A2"] = (f"Imputation Art. 1342-10 Code civil — généré le "
                f"{date.today().strftime('%d/%m/%Y')}")
    ws["A2"].font      = Font(italic=True, name="Calibri", size=9, color="6B7280")
    ws["A2"].alignment = center

    headers = ["Date","Libellé","Catégorie","Débit (€)","Crédit (€)",
               "Imputé sur","Surplus (€)","Solde (€)"]
    for col, h in enumerate(headers, 1):
        c = ws.cell(row=4, column=col, value=h)
        c.fill = hdr_fill; c.font = hdr_font
        c.alignment = center; c.border = brd

    for i, (_, row) in enumerate(df.iterrows(), 5):
        ws.cell(row=i, column=1, value=row["date"].strftime("%d/%m/%Y")).alignment = center
        ws.cell(row=i, column=2, value=row["libelle"]).alignment = left_al
        ws.cell(row=i, column=3, value=row["categorie"]).alignment = center
        for col in range(1, 9):
            ws.cell(row=i, column=col).font   = norm
            ws.cell(row=i, column=col).border = brd
            if i % 2 == 0:
                ws.cell(row=i, column=col).fill = PatternFill("solid", fgColor="F3F4F6")

        d_cell = ws.cell(row=i, column=4,
                         value=row["debit"] if row["debit"] > 0 else None)
        d_cell.number_format = '#,##0.00'
        c_cell = ws.cell(row=i, column=5,
                         value=row["credit"] if row["credit"] > 0 else None)
        c_cell.number_format = '#,##0.00'
        ws.cell(row=i, column=6, value=row["impute_sur"]).alignment = left_al
        s_cell = ws.cell(row=i, column=7,
                         value=row["surplus"] if row["surplus"] > 0 else None)
        s_cell.number_format = '#,##0.00'
        sc = ws.cell(row=i, column=8, value=row["solde_courant"])
        sc.number_format = '#,##0.00'
        sc.font = Font(name="Calibri", size=10, bold=True,
                       color="C00000" if row["solde_courant"] > 0 else "006400")

    widths = [14, 48, 22, 13, 13, 55, 13, 13]
    for col, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(col)].width = w

    # Onglet dettes restantes
    ws2 = wb.create_sheet("Dettes restantes")
    ws2["A1"] = "DETTES NON SOLDÉES"
    ws2["A1"].font = Font(bold=True, name="Calibri", size=12, color="C00000")
    h2 = ["Date échéance","Libellé","Catégorie","Montant initial (€)","Solde restant (€)"]
    for col, h in enumerate(h2, 1):
        c = ws2.cell(row=2, column=col, value=h)
        c.fill = PatternFill("solid", fgColor="C00000")
        c.font = Font(bold=True, color="FFFFFF", name="Calibri")
        c.border = brd
    for i, d in enumerate([x for x in debts_pool if x["solde"] > 0.01], 3):
        dt = d["date"].strftime("%d/%m/%Y") if hasattr(d["date"], "strftime") else str(d["date"])
        ws2.cell(row=i, column=1, value=dt)
        ws2.cell(row=i, column=2, value=d["libelle"])
        ws2.cell(row=i, column=3, value=d["categorie"])
        ws2.cell(row=i, column=4, value=d["montant"]).number_format = '#,##0.00'
        ws2.cell(row=i, column=5, value=d["solde"]).number_format   = '#,##0.00'
    for col, w in enumerate([14, 50, 22, 20, 18], 1):
        ws2.column_dimensions[get_column_letter(col)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ─────────────────────────────────────────────
# UI
# ─────────────────────────────────────────────

st.title("🏢 Relevé de Compte Copropriété")
st.markdown(
    '<div class="law-box"><b>📜 Art. 1342-10 Code civil</b> — Les règlements s\'imputent '
    'd\'abord sur les <b>dettes échues</b>, puis sur celles où le débiteur a le <b>plus '
    'd\'intérêt à payer</b> (charges courantes &gt; travaux &gt; fonds ALUR), '
    'puis sur les <b>plus anciennes</b>, puis <b>proportionnellement</b>.</div>',
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

if uploaded:
    try:
        df_raw = pd.read_excel(uploaded, header=0)
        df_raw.columns = [str(c).strip() for c in df_raw.columns]

        # Normalise colonnes
        rename = {}
        for c in df_raw.columns:
            cl = c.lower()
            if "date" in cl:                        rename[c] = "date"
            elif "lib" in cl:                       rename[c] = "libelle"
            elif "éb" in cl or "eb" in cl:          rename[c] = "debit"
            elif "éd" in cl or "red" in cl or "cr" in cl: rename[c] = "credit"
        df_raw = df_raw.rename(columns=rename)
        df_raw = df_raw[["date","libelle","debit","credit"]].dropna(subset=["date"])

        df_result, debts_pool = build_full_ledger(df_raw)

        # Métriques
        total_appele = df_result["debit"].sum()
        total_regle  = df_result["credit"].sum()
        solde_final  = df_result["solde_courant"].iloc[-1]
        reste_du     = sum(d["solde"] for d in debts_pool if d["solde"] > 0.01)
        nb_ouv       = sum(1 for d in debts_pool if d["solde"] > 0.01)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total appelé",       f"{total_appele:,.2f} €")
        c2.metric("Total réglé",        f"{total_regle:,.2f} €")
        c3.metric("Solde final",        f"{solde_final:,.2f} €",
                  delta="⚠️ Débiteur" if solde_final > 0 else "✅ Soldé",
                  delta_color="inverse")
        c4.metric("Dettes non soldées", f"{nb_ouv} poste(s) — {reste_du:,.2f} €")

        st.divider()

        tab1, tab2 = st.tabs(["📋 Relevé complet imputé", "🔴 Dettes non soldées"])

        with tab1:
            df_display = df_result[["date","libelle","categorie","debit",
                                    "credit","impute_sur","surplus","solde_courant"]].copy()
            df_display["date"] = df_display["date"].dt.strftime("%d/%m/%Y")
            df_display.columns = ["Date","Libellé","Catégorie","Débit (€)","Crédit (€)",
                                   "Imputé sur (Art. 1342-10)","Surplus (€)","Solde (€)"]
            df_display["Débit (€)"]   = df_display["Débit (€)"].replace(0, None)
            df_display["Crédit (€)"]  = df_display["Crédit (€)"].replace(0, None)
            df_display["Surplus (€)"] = df_display["Surplus (€)"].replace(0, None)

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
            remaining = [d for d in debts_pool if d["solde"] > 0.01]
            if remaining:
                st.error(f"⚠️ {len(remaining)} dette(s) non soldée(s) — total : **{reste_du:,.2f} €**")
                df_rem = pd.DataFrame(remaining)[["date","libelle","categorie","montant","solde"]]
                df_rem.columns = ["Date échéance","Libellé","Catégorie",
                                   "Montant initial (€)","Solde restant (€)"]
                df_rem["Date échéance"] = pd.to_datetime(df_rem["Date échéance"]).dt.strftime("%d/%m/%Y")
                st.dataframe(
                    df_rem.style.format({
                        "Montant initial (€)": "{:,.2f} €",
                        "Solde restant (€)":   "{:,.2f} €"
                    }),
                    use_container_width=True, hide_index=True
                )
            else:
                st.success("✅ Toutes les dettes sont soldées !")

        st.divider()
        xlsx_buf = export_xlsx(df_result, proprietaire, debts_pool)
        st.download_button(
            "📥 Télécharger le relevé imputé (.xlsx)",
            data=xlsx_buf,
            file_name=f"releve_impute_{proprietaire.replace(' ','_')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True
        )

    except Exception as e:
        st.error(f"Erreur lors du traitement : {e}")
        st.exception(e)

else:
    st.info("👆 Importez votre fichier Excel pour démarrer l'analyse.")
    with st.expander("ℹ️ Format attendu du fichier Excel"):
        st.markdown("""
Le fichier doit contenir **4 colonnes** :

| Date | Libellé | débit | crédit |
|------|---------|-------|--------|
| 01/01/2024 | 1er appel de fonds 2024 | 477.23 | 0 |
| 16/01/2024 | Virement GUINOT | 0 | 477.23 |

- **Débit** = sommes appelées (charges, travaux, fonds ALUR…)
- **Crédit** = règlements reçus (virement, chèque, régularisation…)
        """)
