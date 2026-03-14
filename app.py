import streamlit as st
import pandas as pd
import numpy as np
from datetime import date, datetime
import io
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

st.set_page_config(page_title="Relevé de Compte Copropriété", page_icon="🏢", layout="wide")

st.markdown("""
<style>
    .main-title { font-size: 2rem; font-weight: bold; color: #1a3a5c; margin-bottom: 0.2rem; }
    .subtitle { color: #555; margin-bottom: 1.5rem; }
    .card { background: #f8fafc; border-radius: 10px; padding: 1.2rem; border: 1px solid #e2e8f0; margin-bottom: 1rem; }
    .imputation-badge { display: inline-block; background: #dbeafe; color: #1e40af; border-radius: 5px; padding: 2px 8px; font-size: 0.8rem; font-weight: bold; }
    .solde-debiteur { color: #dc2626; font-weight: bold; }
    .solde-crediteur { color: #16a34a; font-weight: bold; }
    .law-box { background: #fefce8; border-left: 4px solid #ca8a04; padding: 1rem; border-radius: 5px; font-size: 0.88rem; color: #713f12; }
</style>
""", unsafe_allow_html=True)

# ── SESSION STATE ──────────────────────────────────────────────
if "debts" not in st.session_state:
    st.session_state.debts = []
if "payments" not in st.session_state:
    st.session_state.payments = []

# ── HELPERS ───────────────────────────────────────────────────
def impute_payment(payment_amount: float, debts: list[dict], payment_date: date) -> list[dict]:
    """
    Art. 1342-10 : imputation sur dettes échues, d'abord celles où le débiteur
    a le plus d'intérêt à payer (charges courantes < travaux < fonds travaux),
    puis par ancienneté croissante, puis proportionnellement.
    """
    PRIORITY = {"Charges courantes": 1, "Travaux": 2, "Fonds travaux ALUR": 3, "Autre": 4}

    echues = [d for d in debts if d["date_echeance"] <= payment_date and d["solde"] > 0]
    non_echues = [d for d in debts if d["date_echeance"] > payment_date and d["solde"] > 0]

    def sort_key(d):
        return (PRIORITY.get(d["categorie"], 99), d["date_echeance"])

    echues.sort(key=sort_key)
    non_echues.sort(key=sort_key)

    ordered = echues + non_echues
    remaining = payment_amount

    imputations = []
    for d in ordered:
        if remaining <= 0:
            break
        applied = min(remaining, d["solde"])
        if applied > 0:
            imputations.append({"dette_id": d["id"], "montant": round(applied, 2), "libelle": d["libelle"]})
            d["solde"] = round(d["solde"] - applied, 2)
            remaining = round(remaining - applied, 2)

    return imputations, round(remaining, 2)


def compute_ledger(debts, payments):
    """Build the full ledger sorted by date, computing running balance."""
    rows = []
    for d in debts:
        rows.append({
            "date": d["date_echeance"],
            "libelle": d["libelle"],
            "categorie": d["categorie"],
            "debit": d["montant"],
            "credit": 0.0,
            "type": "dette",
            "imputations": []
        })
    for p in payments:
        rows.append({
            "date": p["date"],
            "libelle": p["libelle"],
            "categorie": "",
            "debit": 0.0,
            "credit": p["montant"],
            "type": "paiement",
            "imputations": p.get("imputations", [])
        })
    rows.sort(key=lambda r: r["date"])
    balance = 0.0
    for r in rows:
        balance += r["debit"] - r["credit"]
        r["solde"] = round(balance, 2)
    return rows


def export_xlsx(proprietaire, rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "Relevé de compte"

    header_fill = PatternFill("solid", fgColor="1A3A5C")
    header_font = Font(bold=True, color="FFFFFF", name="Arial", size=10)
    normal_font = Font(name="Arial", size=10)
    thin = Side(border_style="thin", color="CCCCCC")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center")

    ws.merge_cells("A1:F1")
    ws["A1"] = f"RELEVÉ DE COMPTE — {proprietaire.upper()}"
    ws["A1"].font = Font(bold=True, name="Arial", size=13, color="1A3A5C")
    ws["A1"].alignment = center

    ws.merge_cells("A2:F2")
    ws["A2"] = f"Généré le {date.today().strftime('%d/%m/%Y')} — Art. 1342-10 Code civil"
    ws["A2"].font = Font(italic=True, name="Arial", size=9, color="888888")
    ws["A2"].alignment = center

    headers = ["Date", "Libellé", "Catégorie", "Débit (€)", "Crédit (€)", "Solde (€)"]
    for col, h in enumerate(headers, 1):
        c = ws.cell(row=4, column=col, value=h)
        c.fill = header_fill
        c.font = header_font
        c.alignment = center
        c.border = border

    for i, r in enumerate(rows, 5):
        ws.cell(row=i, column=1, value=r["date"].strftime("%d/%m/%Y") if hasattr(r["date"], "strftime") else str(r["date"])).font = normal_font
        ws.cell(row=i, column=2, value=r["libelle"]).font = normal_font
        ws.cell(row=i, column=3, value=r["categorie"]).font = normal_font
        ws.cell(row=i, column=4, value=r["debit"] if r["debit"] else "").number_format = "#,##0.00"
        ws.cell(row=i, column=5, value=r["credit"] if r["credit"] else "").number_format = "#,##0.00"
        solde_cell = ws.cell(row=i, column=6, value=r["solde"])
        solde_cell.number_format = "#,##0.00"
        solde_cell.font = Font(name="Arial", size=10,
                                color="C00000" if r["solde"] > 0 else "006400")
        for col in range(1, 7):
            ws.cell(row=i, column=col).border = border

    ws.column_dimensions["A"].width = 14
    ws.column_dimensions["B"].width = 50
    ws.column_dimensions["C"].width = 20
    ws.column_dimensions["D"].width = 14
    ws.column_dimensions["E"].width = 14
    ws.column_dimensions["F"].width = 14

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ── SIDEBAR ───────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Configuration")
    proprietaire = st.text_input("Nom du copropriétaire", value="GUINOT Jean-Charles")
    immeuble = st.text_input("Immeuble", value="69 Avenue du Président Wilson")
    lot = st.text_input("N° de lot", value="")

    st.divider()
    st.markdown('<div class="law-box"><b>📜 Art. 1342-10 Code civil</b><br><br>'
                'Le paiement s\'impute :<br>'
                '1. D\'abord sur les <b>dettes échues</b><br>'
                '2. Parmi celles-ci, sur les dettes où le débiteur avait le <b>plus d\'intérêt à payer</b><br>'
                '3. À égalité d\'intérêt : sur la <b>plus ancienne</b><br>'
                '4. Toutes choses égales : <b>proportionnellement</b></div>',
                unsafe_allow_html=True)

# ── MAIN ──────────────────────────────────────────────────────
st.markdown('<div class="main-title">🏢 Relevé de Compte Copropriété</div>', unsafe_allow_html=True)
st.markdown(f'<div class="subtitle">{proprietaire} — {immeuble}</div>', unsafe_allow_html=True)

tab1, tab2, tab3, tab4 = st.tabs(["📋 Appels de fonds", "💳 Règlements", "📊 Relevé & Solde", "📥 Import Excel"])

# ── TAB 1 : DETTES ──
with tab1:
    st.subheader("Ajouter un appel de fonds / charge")
    with st.container():
        col1, col2, col3 = st.columns(3)
        with col1:
            d_date = st.date_input("Date d'échéance", value=date.today(), key="d_date")
            d_libelle = st.text_input("Libellé", placeholder="Ex: 3ème appel de fonds 2025", key="d_lib")
        with col2:
            d_montant = st.number_input("Montant (€)", min_value=0.01, step=0.01, format="%.2f", key="d_mont")
            d_cat = st.selectbox("Catégorie", ["Charges courantes", "Travaux", "Fonds travaux ALUR", "Autre"], key="d_cat")
        with col3:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("➕ Ajouter l'appel", use_container_width=True, type="primary"):
                if d_libelle and d_montant > 0:
                    new_id = len(st.session_state.debts) + 1
                    st.session_state.debts.append({
                        "id": new_id,
                        "date_echeance": d_date,
                        "libelle": d_libelle,
                        "categorie": d_cat,
                        "montant": round(d_montant, 2),
                        "solde": round(d_montant, 2)
                    })
                    st.success(f"✅ Appel ajouté : {d_libelle} — {d_montant:.2f} €")
                else:
                    st.warning("Merci de renseigner le libellé et le montant.")

    if st.session_state.debts:
        st.divider()
        st.markdown("#### Liste des appels de fonds")
        df_debts = pd.DataFrame(st.session_state.debts)
        df_display = df_debts[["date_echeance", "libelle", "categorie", "montant", "solde"]].copy()
        df_display.columns = ["Échéance", "Libellé", "Catégorie", "Montant (€)", "Solde restant (€)"]
        df_display["Échéance"] = pd.to_datetime(df_display["Échéance"]).dt.strftime("%d/%m/%Y")
        st.dataframe(df_display, use_container_width=True, hide_index=True)

        col_tot, col_del = st.columns([3, 1])
        with col_tot:
            total_dette = sum(d["solde"] for d in st.session_state.debts)
            st.metric("Total restant dû", f"{total_dette:.2f} €")
        with col_del:
            if st.button("🗑️ Vider les appels", use_container_width=True):
                st.session_state.debts = []
                st.rerun()


# ── TAB 2 : PAIEMENTS ──
with tab2:
    st.subheader("Enregistrer un règlement")

    if not st.session_state.debts:
        st.info("Ajoutez d'abord des appels de fonds dans l'onglet précédent.")
    else:
        col1, col2 = st.columns(2)
        with col1:
            p_date = st.date_input("Date du règlement", value=date.today(), key="p_date")
            p_libelle = st.text_input("Libellé du règlement", placeholder="Ex: Virement GUINOT", key="p_lib")
        with col2:
            p_montant = st.number_input("Montant reçu (€)", min_value=0.01, step=0.01, format="%.2f", key="p_mont")
            p_mode = st.selectbox("Mode de règlement", ["Virement", "Chèque", "Prélèvement", "Espèces"])

        if st.button("💳 Imputer le règlement (Art. 1342-10)", type="primary", use_container_width=True):
            if p_libelle and p_montant > 0:
                debts_copy = [{**d} for d in st.session_state.debts]
                imputations, surplus = impute_payment(p_montant, debts_copy, p_date)

                if not imputations and surplus == p_montant:
                    st.warning("Aucune dette échue ou restante à apurer.")
                else:
                    # Apply to real debts
                    for imp in imputations:
                        for d in st.session_state.debts:
                            if d["id"] == imp["dette_id"]:
                                d["solde"] = round(d["solde"] - imp["montant"], 2)

                    st.session_state.payments.append({
                        "date": p_date,
                        "libelle": f"{p_libelle} ({p_mode})",
                        "montant": round(p_montant, 2),
                        "imputations": imputations,
                        "surplus": surplus
                    })

                    st.success(f"✅ Règlement de {p_montant:.2f} € imputé.")

                    with st.expander("📋 Détail de l'imputation (Art. 1342-10)", expanded=True):
                        for imp in imputations:
                            st.markdown(f'<span class="imputation-badge">→</span> **{imp["libelle"]}** : {imp["montant"]:.2f} €', unsafe_allow_html=True)
                        if surplus > 0:
                            st.warning(f"⚠️ Surplus non imputé (aucune dette) : **{surplus:.2f} €**")
            else:
                st.warning("Merci de renseigner le libellé et le montant.")

    if st.session_state.payments:
        st.divider()
        st.markdown("#### Historique des règlements")
        for p in reversed(st.session_state.payments):
            with st.expander(f"💳 {p['date'].strftime('%d/%m/%Y')} — {p['libelle']} — {p['montant']:.2f} €"):
                for imp in p["imputations"]:
                    st.write(f"→ {imp['libelle']} : {imp['montant']:.2f} €")
                if p["surplus"] > 0:
                    st.warning(f"Surplus : {p['surplus']:.2f} €")


# ── TAB 3 : RELEVÉ ──
with tab3:
    st.subheader("Relevé de compte complet")

    if not st.session_state.debts and not st.session_state.payments:
        st.info("Aucune donnée. Ajoutez des appels de fonds et des règlements.")
    else:
        rows = compute_ledger(
            [{**d, "date_echeance": d["date_echeance"] if isinstance(d["date_echeance"], date) else d["date_echeance"].date()} for d in st.session_state.debts],
            [{**p, "date": p["date"] if isinstance(p["date"], date) else p["date"].date()} for p in st.session_state.payments]
        )

        df_rel = pd.DataFrame(rows)
        df_rel["date_fmt"] = pd.to_datetime(df_rel["date"]).dt.strftime("%d/%m/%Y")
        df_rel["debit_fmt"] = df_rel["debit"].apply(lambda x: f"{x:.2f} €" if x > 0 else "")
        df_rel["credit_fmt"] = df_rel["credit"].apply(lambda x: f"{x:.2f} €" if x > 0 else "")
        df_rel["solde_fmt"] = df_rel["solde"].apply(lambda x: f"{x:.2f} €")

        st.dataframe(
            df_rel[["date_fmt", "libelle", "categorie", "debit_fmt", "credit_fmt", "solde_fmt"]].rename(
                columns={"date_fmt": "Date", "libelle": "Libellé", "categorie": "Catégorie",
                         "debit_fmt": "Débit", "credit_fmt": "Crédit", "solde_fmt": "Solde"}),
            use_container_width=True, hide_index=True)

        final_balance = rows[-1]["solde"] if rows else 0
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total appelé", f"{sum(r['debit'] for r in rows):.2f} €")
        with col2:
            st.metric("Total réglé", f"{sum(r['credit'] for r in rows):.2f} €")
        with col3:
            label = "Solde débiteur (dû)" if final_balance > 0 else "Solde créditeur (avoir)"
            st.metric(label, f"{abs(final_balance):.2f} €",
                      delta=f"{'▲ À recouvrer' if final_balance > 0 else '▼ À restituer'}")

        st.divider()
        xlsx_buf = export_xlsx(proprietaire, rows)
        st.download_button(
            "📥 Télécharger le relevé Excel",
            data=xlsx_buf,
            file_name=f"releve_compte_{proprietaire.replace(' ','_')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            type="primary"
        )


# ── TAB 4 : IMPORT ──
with tab4:
    st.subheader("Importer un relevé existant (format exemple)")
    st.markdown("Importez un fichier Excel avec les colonnes : **Date | Libellé | débit | crédit**")

    uploaded = st.file_uploader("Choisir un fichier Excel (.xlsx)", type=["xlsx"])
    if uploaded:
        try:
            df_imp = pd.read_excel(uploaded, header=0)
            df_imp.columns = [str(c).strip().lower() for c in df_imp.columns]

            # Normalize columns
            col_map = {}
            for c in df_imp.columns:
                if "date" in c: col_map[c] = "date"
                elif "lib" in c: col_map[c] = "libelle"
                elif "déb" in c or "deb" in c: col_map[c] = "debit"
                elif "cré" in c or "cre" in c: col_map[c] = "credit"
            df_imp = df_imp.rename(columns=col_map)

            df_imp["date"] = pd.to_datetime(df_imp["date"], errors="coerce")
            df_imp["debit"] = pd.to_numeric(df_imp.get("debit", 0), errors="coerce").fillna(0)
            df_imp["credit"] = pd.to_numeric(df_imp.get("credit", 0), errors="coerce").fillna(0)
            df_imp = df_imp.dropna(subset=["date"])

            st.success(f"✅ {len(df_imp)} lignes importées.")
            st.dataframe(df_imp[["date", "libelle", "debit", "credit"]].head(20), use_container_width=True, hide_index=True)

            if st.button("📥 Charger dans l'application", type="primary"):
                for _, row in df_imp.iterrows():
                    d = row["date"].date() if hasattr(row["date"], "date") else row["date"]
                    lib = str(row.get("libelle", ""))
                    deb = float(row["debit"])
                    cred = float(row["credit"])

                    if deb > 0:
                        new_id = len(st.session_state.debts) + 1
                        cat = "Fonds travaux ALUR" if "alur" in lib.lower() or "travaux" in lib.lower() else \
                              "Charges courantes" if "appel" in lib.lower() or "charge" in lib.lower() else "Autre"
                        st.session_state.debts.append({
                            "id": new_id, "date_echeance": d, "libelle": lib,
                            "categorie": cat, "montant": deb, "solde": deb
                        })
                    elif cred > 0:
                        st.session_state.payments.append({
                            "date": d, "libelle": lib, "montant": cred, "imputations": [], "surplus": 0
                        })
                st.success("✅ Données chargées. Consultez les autres onglets.")
                st.rerun()
        except Exception as e:
            st.error(f"Erreur lors de l'import : {e}")
