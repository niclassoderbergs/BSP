import streamlit as st
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

st.set_page_config(page_title="Scenariosimulator för BRP&BSP", layout="wide")


# Tillåt radbryt i rubriker för både DataFrame och DataEditor
st.markdown("""
<style>
/* DataEditor: bryt rubriktext på \n */
[data-testid="stDataEditorColumnHeader"] div {
  white-space: pre-line !important;
}

/* DataFrame: bryt rubriktext på \n */
[data-testid="stDataFrame"] th div {
  white-space: pre-line !important;
}

/* (frivilligt) centrera headern lite snyggare */
[data-testid="stDataEditorColumnHeader"], [data-testid="stDataFrame"] th {
  text-align: center !important;
}
</style>
""", unsafe_allow_html=True)


# ---------- Hjälpfunktioner ----------
def normal_pdf(x, mu, sigma):
    if sigma <= 0:
        return np.zeros_like(x)
    z = (x - mu) / sigma
    return (1 / (np.sqrt(2*np.pi) * sigma)) * np.exp(-0.5 * z * z)

def fmt_or_na(x, decimals=3):
    if x is None:
        return "–"
    return f"{x:.{decimals}f}"

# ---------- Sidopanel: Parametrar (i angiven ordning) ----------
st.sidebar.title("Parametrar")

# 1) DA Handelsvolym (standard 100 MWh)
V_DA  = st.sidebar.number_input(
    "DA Handelsvolym (MWh)", min_value=0.0, value=100.0, step=1.0, format="%.0f"
)

# Handelstyp styr tecknet i tabellen (köp = negativ rad, sälj = positiv rad)
handel_typ = st.sidebar.radio(
    "Handelstyp",
    ["Köp (visa negativ i tabell)", "Sälj (visa positiv i tabell)"],
    index=0,
)

# --- Uppmätt förbrukning (default 92% av DA-handeln, avrundat till heltal) ---
default_e_cons = int(round(0.92 * V_DA))  # 92% och närmaste heltal
E_cons = st.sidebar.number_input(
    "Uppmätt förbrukning E_cons (MWh)",
    min_value=0.0,
    value=float(default_e_cons),
    step=1.0,
    format="%.0f",
    help="Default sätts till 92% av DA-handeln, avrundat till heltal."
)

# 2) Budstorlek
E_bud = st.sidebar.number_input("Budstorlek E_bud (MWh)", min_value=0.0, value=10.0, step=0.5, format="%.3f")
# 3) Uppmätt aktivering (för jämförelser/Scenario 3–5)
E_akt = st.sidebar.number_input("Uppmätt aktivering E_akt (MWh)", min_value=0.0, value=8.0, step=0.5, format="%.3f")

# 4) Pris DA (standard 2 €/MWh)
P_DA  = st.sidebar.number_input(
    "Pris DA P_DA (EUR/MWh)", min_value=-200.0, value=2.0, step=0.5, format="%.2f"
)
# 5) Pris Obalanskostnad (standard 5 €/MWh)
P_IMB = st.sidebar.number_input(
    "Pris Obalanskostnad P_IMB (EUR/MWh)", min_value=-200.0, value=5.0, step=0.5, format="%.2f"
)

# Tecken för handel i tabellen
handel_sign = -1 if "Köp" in handel_typ else 1

# 6) BSP ersättningspris = obalanspris (checkbox, default)
use_imb_for_comp = st.sidebar.checkbox("BSP ersättningspris = obalanspris", value=True)
P_comp_custom    = st.sidebar.number_input(
    "BSP annat ersättningspris P_COMP (EUR/MWh)",
    min_value=-200.0, value=7.0, step=1.0, format="%.2f",
    disabled=use_imb_for_comp
)
P_COMP = P_IMB if use_imb_for_comp else P_comp_custom

# 7) BSP avdrag över/underleverans = obalanspris (checkbox, default)
use_imb_for_pen  = st.sidebar.checkbox("BSP avdrag över/underleverans = obalanspris", value=True)
P_pen_custom     = st.sidebar.number_input(
    "BSP avdragspris P_PEN (EUR/MWh)",
    min_value=-200.0, value=9.0, step=1.0, format="%.2f",
    disabled=use_imb_for_pen
)
P_PEN = P_IMB if use_imb_for_pen else P_pen_custom

# --- RE-komp (parametrar, används ej i scen 1 just nu; scen 4–5 styrs av scenariot) ---
re_comp_is_da = st.sidebar.checkbox("Kompensationspris till RE = DA (P_DA)", value=True)
re_comp_custom = st.sidebar.number_input(
    "Annat kompensationspris till RE (EUR/MWh)",
    min_value=-200.0, value=4.0, step=1.0, format="%.2f",
    disabled=re_comp_is_da
)
P_RECOMP = P_DA if re_comp_is_da else re_comp_custom

# Endast för diagrammets pdf-visning (kosmetik)
mu    = st.sidebar.number_input("Visnings-μ (MWh)", min_value=0.0, value=max(E_bud, E_akt), step=0.5, format="%.3f")
sigma = st.sidebar.number_input("Visnings-σ (MWh)", min_value=0.1, value=4.0, step=0.1, format="%.2f")

# ---------- Rubrik ----------
st.title("Scenariosimulator för BRP&BSP")
st.caption(
    "Scenarier: (1) Bud + underleverans, (2) Bud + överleverans (spegling), (3) Uppmätt aktivering (BRP=BSP), "
    "(4) Uppmätt aktivering, ingen kompensation (BRP≠BSP), "
    "(5) Uppmätt aktivering, med kompensation (BRP≠BSP). "
    "Volymer visas per rad. ‘Balanshandel’ följer: köp = negativt, sälj = positivt."
)

# ---------- Grundtermer ----------
dP = P_IMB - P_DA

# init
st.session_state.setdefault("re_forward_balance_costs", True)



# --- Initiera huvudstate en gång högst upp i appen (innan widgets används) ---
if "brp_forward_balance_costs" not in st.session_state:
    st.session_state["brp_forward_balance_costs"] = True

# Hjälpare för att spegla dubblett-widgeten till huvudnyckeln
def _sync_brb_copy_to_main(copy_key: str):
    st.session_state["brp_forward_balance_costs"] = st.session_state[copy_key]




# ---------- Scenariogenomgång (kompakt med expanders) ----------
st.markdown("### Om scenarierna")

with st.expander("Gemensamma antaganden (A/B)", expanded=False):
    st.markdown("""
- **A = uppreglering** (förbrukningen sänks mot DA-plan), **B = nedreglering** (förbrukningen höjs mot DA-plan).
- **Balanshandelstecken:** köp visas som **negativ** volym, sälj som **positiv**.
- **Obalanskostnad:** beräknas med obalanspriset `P_IMB` på balanshandeln.
- **Checkboxar som kan påverka flöden och rader i tabeller:**
  
  - *BRP vidarefakturerar balanskostnader till elhandlare* – om ikryssad går BRP:s balanskostnad vidare till RE.
  - *BSP köper in energi vid nedreglering* – om ikryssad bokas en DA-handel till `P_DA` för samtliga **B-scenarier** (nedreglering); extra rader visas i BSP-tabellen.
  - *Tillämpa avdrag för BSP vid över/underleverans* – aktiverar avdrag baserat på differensen mellan aktiverad och budad volym (`E_akt` – `E_bud`) i BSP-tabellen.  
    Under- eller överleverans ger ett avdrag enligt `P_PEN` om aktiverad.
  - *Motsatt kompensation i 5b (RE → BSP)* – om ikryssad betalar RE kompensation till BSP i scenario 5b (default: ingen kompensation i 5b).
  - *Elhandlaren vidarefakturerar balanskostnader till slutkunden* – om ikryssad skickas BRP:s balansfaktura vidare på kundfakturan.
  
  
  
  
  
  
  
    """)


with st.expander("Scenario 1 – BRP = BSP, bud och **underleverans** (1a = upp, 1b = ned)", expanded=False):
    st.markdown("""
- BRP/BSP lämnar bud `E_bud` på reglering.
- Utfallet ger **underleverans** mot budet: faktisk aktivering < budad aktivering.
- Obalansjusteringen i BRP-tabellen baseras på **`E_bud`**.
- I BSP-tabellen kan avdrag för under/överleverans aktiveras via checkboxen *Tillämpa avdrag...*.
- Om *BSP köper in energi vid nedreglering* är ikryssad visas DA-rader i **1b** (ned).
    """)

with st.expander("Scenario 2 – BRP = BSP, bud och **överleverans** (2a = upp, 2b = ned)", expanded=False):
    st.markdown("""
- Spegling av Scenario 1 men med **överleverans**: faktisk aktivering > budad aktivering.
- Obalansjusteringen baseras på **`E_bud`**.
- Avdrag i BSP-tabellen hanteras som i Scenario 1.
- Om *BSP köper in energi vid nedreglering* är ikryssad visas DA-rader i **2b** (ned).
    """)

with st.expander("Scenario 3 – BRP = BSP, **uppmätt aktivering** (3a = upp, 3b = ned)", expanded=False):
    st.markdown("""
- BRP och BSP är samma aktör.
- Obalansjusteringen baseras på **uppmätt aktivering `E_akt`** (inte `E_bud`).
- Ingen separat kompensation mellan aktörer.
- Om *BSP köper in energi vid nedreglering* är ikryssad visas DA-rader i **3b** (ned).
    """)

with st.expander("Scenario 4 – BRP ≠ BSP, uppmätt aktivering **utan kompensation** (4a = upp, 4b = ned)", expanded=False):
    st.markdown("""
- BRP och BSP är **olika** aktörer.
- Obalansjusteringen baseras på **`E_akt`**.
- **Ingen kompensation** mellan BSP och RE.
- Om *BSP köper in energi vid ndereglering* är ikryssad visas DA-rader i **4b** (ned).
    """)

with st.expander("Scenario 5 – BRP ≠ BSP, uppmätt aktivering **med kompensation** (5a = upp, 5b = ned)", expanded=False):
    st.markdown("""
- Baseras på **`E_akt`**.
- **5a (ned):** BSP → RE (RE får kompensation) med pris **`P_RECOMP`**. *Denna kompensation är alltid aktiv i 5a.*
- **5b (ned):** Default **ingen kompensation**. Om *Motsatt kompensation i 5b (RE → BSP)* är ikryssad betalar RE kompensation till BSP.
- Om *BSP köper in energi vid nedreglering* är ikryssad visas DA-rader i **5b** (ned).
    """)

with st.expander("Slutkundens elpris & tabeller", expanded=False):
    st.markdown("""
- **Slutkundens elpris** i RE-tabellen:
  \n  `Pris = –(Inköp från BRP + ev. balans som skickas vidare + ev. kompensation) / fakturerad volym`
- Tabellen **”Slutkundens elpris per scenario”** visar även avvikelse mot vald målkolumn (default 5a) samt **Ökad totalkostnad slutkund** (= prisavvikelse × fakturerad volym).
    """)

with st.expander("Kompensation till slutkund (Tabell 6)", expanded=False):
    st.markdown("""
- **Kompensation = max(0, Ökad totalkostnad slutkund)** per scenario för att neutralisera merkostnaden mot målscenariot.
- **Aktörers resultat efter kompensation** räknas från **BRP+BSP+Elhandlare resultat** (om ”NA” används **BSP resultat** som bas) minus kompensationen.
- Om *Motsatt kompensation i 5b* är aktiverad påverkar detta resultaten i 5b innan neutraliseringskompensation beräknas.
    """)


# ---------- Scenario-val: Visa scenarier i tabellerna ----------
with st.expander("Visa scenarier i tabellerna", expanded=False):
    st.markdown(
        """
Markera vilka scenarier som ska visas i tabellerna nedan.
Om du avmarkerar ett scenarie döljs det i samtliga tabeller (BRP, BSP, RE, resultat, slutkund, kompensation).
        """
    )

    BRP_SCENARIO_COLUMNS = {
        "1a": "1a BRP=BSP, Upp – Bud/underlev.",
        "1b": "1b BRP=BSP, Ned – Bud/underlev.",
        "2a": "2a BRP=BSP, Upp – Bud/överlev.",
        "2b": "2b BRP=BSP, Ned – Bud/överlev.",
        "3a": "3a BRP=BSP, Upp – Uppmätt akt.",
        "3b": "3b BRP=BSP, Ned – Uppmätt akt.",
        "4a": "4a BRP≠BSP, Upp – Uppmätt (ingen komp)",
        "4b": "4b BRP≠BSP, Ned – Uppmätt (ingen komp)",
        "5a": "5a BRP≠BSP, Upp – Uppmätt (med komp)",
        "5b": "5b BRP≠BSP, Ned – Uppmätt (med komp)",
    }

    # En checkbox per scenario – alla ikryssade som default
    cols = st.columns(5)  # bara layout/kosmetik
    for i, (short_key, label) in enumerate(BRP_SCENARIO_COLUMNS.items()):
        with cols[i % 5]:
            st.checkbox(
                label,
                value=True,
                key=f"show_brp_{short_key}",
                help=f"Visa/dölj scenario {short_key} i alla tabeller.",
            )


# ---------- Checkbox före BRP-tabellen ----------
# Checkbox ovanför BRP-tabellen
brp_forward_balance_costs = st.checkbox(
    "BRP vidarefakturerar balanskostnader till elhandlare",
    key="brp_forward_balance_costs",   # <-- huvudnyckeln
    help="Om urkryssad står BRP själv för balanskostnaden och fakturerar inte elhandlaren."
)







def _wrap_header(h: str) -> str:
    # Bryt på " - " och efter kommatecken för att bli smalare
    return h.replace(" - ", "\n").replace(", ", ",\n")



# ---------- TABELL 1: BRP (1a,1b,2a,2b,3a,3b,4a,4b,5a,5b) ----------
st.markdown("## BRP")

def _fmt_cell(v, enhet):
    """Formatering av visningsvärden i tabellen."""
    try:
        if enhet == "MWh":
            return f"{float(v):,.0f}"
        if enhet == "€/MWh":
            return f"{float(v):,.2f}"
        if enhet == "EUR":
            return f"{float(v):,.0f}"
    except Exception:
        return v
    return v


# ---- BRP: beräkningar och scenarier 1a–5b ----
def _brp_metrics(uppmatt_mwh: float, obalans_vol_mwh: float, based_on: str, is_up: bool):
    """
    uppmatt_mwh: uppmätt förbrukning i scenariot
    obalans_vol_mwh: volym som ska obalansjusteras (E_bud eller E_akt)
    based_on: "Bud" eller "Uppmätt aktivering" (för utskrift)
    is_up: True = nedreglering (vänd tecken), False = uppreglering
    """
    # DA-handel
    handel_mwh = handel_sign * V_DA          # köp = -, sälj = +
    kostnad_handel_eur = handel_mwh * P_DA

    # Vänd tecken på obalansjustering vid nedreglering
    obalansjust_mwh = -obalans_vol_mwh if is_up else obalans_vol_mwh

    # Balansavräkning
    summa_avr_balans_mwh = handel_mwh + obalansjust_mwh
    obalans_mwh = uppmatt_mwh + summa_avr_balans_mwh
    balanshandel_mwh = -obalans_mwh
    balanskostnad_eur = balanshandel_mwh * P_IMB

    # Vidarefakturering?
    obalans_fakt_eur = 0.0 if not brp_forward_balance_costs else -balanskostnad_eur

    # Fakturering till RE
    inkopt_el_fakt_eur = abs(handel_mwh) * P_DA
    brp_fakt_re_eur = inkopt_el_fakt_eur + obalans_fakt_eur

    # BRP:s eget netto
    brp_netto_eur = (
        kostnad_handel_eur
        + balanskostnad_eur
        + inkopt_el_fakt_eur
        + obalans_fakt_eur
    )

    return {
        "Obalansjusteras baserat på": f"{based_on} ({'ned' if is_up else 'upp'})",
        "Handel": handel_mwh,
        "DA Pris": P_DA,
        "Kostnad handel": kostnad_handel_eur,
        "Obalansjustering": obalansjust_mwh,
        "Summa avräknas i balans": summa_avr_balans_mwh,
        "Uppmätt": uppmatt_mwh,
        "Balanshandel (köp − / sälj +)": balanshandel_mwh,
        "Obalanspris": P_IMB,
        "Balanskostnad BRP": balanskostnad_eur,
        "Inköpt el som faktureras": inkopt_el_fakt_eur,
        "Obalanskostnad som faktureras": obalans_fakt_eur,
        "BRP fakturerar elhandlare": brp_fakt_re_eur,
        "BRP nettokostnad": brp_netto_eur,
    }


# ---- Parametrar för A (ned) och B (upp) enligt dina värden ----
E_bud_down = E_bud          # ned-scenarier
E_bud_up   = 10.0           # upp-scenarier
E_akt_down = E_akt
E_akt_up   = 8.0

E_cons_down = E_cons
E_cons_up   = 108.0

# Uppmätt förbrukning per scenario (som du ville ha dem)
E_cons_1a = E_cons_down
E_cons_1b = E_cons_up
E_cons_2a = E_cons_down - 4
E_cons_2b = E_cons_up + 4
E_cons_3a = E_cons_down
E_cons_3b = E_cons_up
E_cons_4a = E_cons_down
E_cons_4b = E_cons_up
E_cons_5a = E_cons_down
E_cons_5b = E_cons_up

# Beräkna 10 BRP-scenarier
m1a = _brp_metrics(E_cons_1a, E_bud_down, "Bud",                is_up=False)  # 1a Upp
m1b = _brp_metrics(E_cons_1b, E_bud_up,   "Bud",                is_up=True)   # 1b Ned

m2a = _brp_metrics(E_cons_2a, E_bud_down, "Bud",                is_up=False)  # 2a Upp
m2b = _brp_metrics(E_cons_2b, E_bud_up,   "Bud",                is_up=True)   # 2b Ned

m3a = _brp_metrics(E_cons_3a, E_akt_down, "Uppmätt aktivering", is_up=False)  # 3a Upp
m3b = _brp_metrics(E_cons_3b, E_akt_up,   "Uppmätt aktivering", is_up=True)   # 3b Ned

m4a = _brp_metrics(E_cons_4a, E_akt_down, "Uppmätt aktivering", is_up=False)  # 4a Upp
m4b = _brp_metrics(E_cons_4b, E_akt_up,   "Uppmätt aktivering", is_up=True)   # 4b Ned

m5a = _brp_metrics(E_cons_5a, E_akt_down, "Uppmätt aktivering", is_up=False)  # 5a Upp
m5b = _brp_metrics(E_cons_5b, E_akt_up,   "Uppmätt aktivering", is_up=True)   # 5b Ned

# (Alias om resten av appen fortfarande använder m1..m5)
m1, m2, m3, m4, m5 = m1a, m2a, m3a, m4a, m5a


# ----- Bygg BRP-DataFrame -----
rows_brp = [
    (
        "Obalansjusteras baserat på",
        m1a["Obalansjusteras baserat på"], m1b["Obalansjusteras baserat på"],
        m2a["Obalansjusteras baserat på"], m2b["Obalansjusteras baserat på"],
        m3a["Obalansjusteras baserat på"], m3b["Obalansjusteras baserat på"],
        m4a["Obalansjusteras baserat på"], m4b["Obalansjusteras baserat på"],
        m5a["Obalansjusteras baserat på"], m5b["Obalansjusteras baserat på"], "",
    ),
    (
        "Handel",
        m1a["Handel"], m1b["Handel"], m2a["Handel"], m2b["Handel"],
        m3a["Handel"], m3b["Handel"], m4a["Handel"], m4b["Handel"],
        m5a["Handel"], m5b["Handel"], "MWh",
    ),
    (
        "DA Pris",
        m1a["DA Pris"], m1b["DA Pris"], m2a["DA Pris"], m2b["DA Pris"],
        m3a["DA Pris"], m3b["DA Pris"], m4a["DA Pris"], m4b["DA Pris"],
        m5a["DA Pris"], m5b["DA Pris"], "€/MWh",
    ),
    (
        "Kostnad handel",
        m1a["Kostnad handel"], m1b["Kostnad handel"], m2a["Kostnad handel"], m2b["Kostnad handel"],
        m3a["Kostnad handel"], m3b["Kostnad handel"], m4a["Kostnad handel"], m4b["Kostnad handel"],
        m5a["Kostnad handel"], m5b["Kostnad handel"], "EUR",
    ),
    (
        "Obalansjustering",
        m1a["Obalansjustering"], m1b["Obalansjustering"], m2a["Obalansjustering"], m2b["Obalansjustering"],
        m3a["Obalansjustering"], m3b["Obalansjustering"], m4a["Obalansjustering"], m4b["Obalansjustering"],
        m5a["Obalansjustering"], m5b["Obalansjustering"], "MWh",
    ),
    (
        "Summa avräknas i balans",
        m1a["Summa avräknas i balans"], m1b["Summa avräknas i balans"],
        m2a["Summa avräknas i balans"], m2b["Summa avräknas i balans"],
        m3a["Summa avräknas i balans"], m3b["Summa avräknas i balans"],
        m4a["Summa avräknas i balans"], m4b["Summa avräknas i balans"],
        m5a["Summa avräknas i balans"], m5b["Summa avräknas i balans"], "MWh",
    ),
    (
        "Uppmätt",
        m1a["Uppmätt"], m1b["Uppmätt"], m2a["Uppmätt"], m2b["Uppmätt"],
        m3a["Uppmätt"], m3b["Uppmätt"], m4a["Uppmätt"], m4b["Uppmätt"],
        m5a["Uppmätt"], m5b["Uppmätt"], "MWh",
    ),
    (
        "Balanshandel (köp − / sälj +)",
        m1a["Balanshandel (köp − / sälj +)"], m1b["Balanshandel (köp − / sälj +)"],
        m2a["Balanshandel (köp − / sälj +)"], m2b["Balanshandel (köp − / sälj +)"],
        m3a["Balanshandel (köp − / sälj +)"], m3b["Balanshandel (köp − / sälj +)"],
        m4a["Balanshandel (köp − / sälj +)"], m4b["Balanshandel (köp − / sälj +)"],
        m5a["Balanshandel (köp − / sälj +)"], m5b["Balanshandel (köp − / sälj +)"], "MWh",
    ),
    (
        "Obalanspris",
        m1a["Obalanspris"], m1b["Obalanspris"], m2a["Obalanspris"], m2b["Obalanspris"],
        m3a["Obalanspris"], m3b["Obalanspris"], m4a["Obalanspris"], m4b["Obalanspris"],
        m5a["Obalanspris"], m5b["Obalanspris"], "€/MWh",
    ),
    (
        "Balanskostnad BRP",
        m1a["Balanskostnad BRP"], m1b["Balanskostnad BRP"], m2a["Balanskostnad BRP"], m2b["Balanskostnad BRP"],
        m3a["Balanskostnad BRP"], m3b["Balanskostnad BRP"], m4a["Balanskostnad BRP"], m4b["Balanskostnad BRP"],
        m5a["Balanskostnad BRP"], m5b["Balanskostnad BRP"], "EUR",
    ),
    (
        "Inköpt el som faktureras",
        m1a["Inköpt el som faktureras"], m1b["Inköpt el som faktureras"],
        m2a["Inköpt el som faktureras"], m2b["Inköpt el som faktureras"],
        m3a["Inköpt el som faktureras"], m3b["Inköpt el som faktureras"],
        m4a["Inköpt el som faktureras"], m4b["Inköpt el som faktureras"],
        m5a["Inköpt el som faktureras"], m5b["Inköpt el som faktureras"], "EUR",
    ),
    (
        "Obalanskostnad som faktureras",
        m1a["Obalanskostnad som faktureras"], m1b["Obalanskostnad som faktureras"],
        m2a["Obalanskostnad som faktureras"], m2b["Obalanskostnad som faktureras"],
        m3a["Obalanskostnad som faktureras"], m3b["Obalanskostnad som faktureras"],
        m4a["Obalanskostnad som faktureras"], m4b["Obalanskostnad som faktureras"],
        m5a["Obalanskostnad som faktureras"], m5b["Obalanskostnad som faktureras"], "EUR",
    ),
    (
        "BRP fakturerar elhandlare",
        m1a["BRP fakturerar elhandlare"], m1b["BRP fakturerar elhandlare"],
        m2a["BRP fakturerar elhandlare"], m2b["BRP fakturerar elhandlare"],
        m3a["BRP fakturerar elhandlare"], m3b["BRP fakturerar elhandlare"],
        m4a["BRP fakturerar elhandlare"], m4b["BRP fakturerar elhandlare"],
        m5a["BRP fakturerar elhandlare"], m5b["BRP fakturerar elhandlare"], "EUR",
    ),
    (
        "BRP nettokostnad",
        m1a["BRP nettokostnad"], m1b["BRP nettokostnad"],
        m2a["BRP nettokostnad"], m2b["BRP nettokostnad"],
        m3a["BRP nettokostnad"], m3b["BRP nettokostnad"],
        m4a["BRP nettokostnad"], m4b["BRP nettokostnad"],
        m5a["BRP nettokostnad"], m5b["BRP nettokostnad"], "EUR",
    ),
]

df_brp = pd.DataFrame(
    rows_brp,
    columns=[
        "Fält",
        "1a BRP=BSP, Upp – Bud/underlev.",
        "1b BRP=BSP, Ned – Bud/underlev.",
        "2a BRP=BSP, Upp – Bud/överlev.",
        "2b BRP=BSP, Ned – Bud/överlev.",
        "3a BRP=BSP, Upp – Uppmätt akt.",
        "3b BRP=BSP, Ned – Uppmätt akt.",
        "4a BRP≠BSP, Upp – Uppmätt (ingen komp)",
        "4b BRP≠BSP, Ned – Uppmätt (ingen komp)",
        "5a BRP≠BSP, Upp – Uppmätt (med komp)",
        "5b BRP≠BSP, Ned – Uppmätt (med komp)",
        "Enhet",
    ],
)

# Formatera värdena (siffror → strängar med rätt antal decimaler)
for col in df_brp.columns[1:-1]:
    df_brp[col] = [_fmt_cell(v, e) for v, e in zip(df_brp[col], df_brp["Enhet"])]

# ----- Rad-tooltips: text till varje "Fält" -----
# ----- Rad-tooltips: text till varje "Fält" -----
brp_row_tips = {
    "Obalansjusteras baserat på":
        "Visar om obalansjusteringen görs mot bud (E_bud) eller uppmätt aktivering (E_akt), samt riktning: upp eller ned.",
    "Handel":
        "DA-handeln mot marknaden: handel_sign × V_DA (köp = negativ, sälj = positiv). Enhet: MWh.",
    "DA Pris":
        "Day-Ahead-priset P_DA som används för DA-handeln. Enhet: €/MWh.",
    "Kostnad handel":
        "Kostnad/intäkt för DA-handeln: Handel × P_DA. Enhet: EUR.",
    "Obalansjustering":
        "Volym som justeras i balansavräkningen (E_bud eller E_akt; tecken vänds i ned-scenarier). Enhet: MWh.",
    "Summa avräknas i balans":
        "Handel + Obalansjustering. Summan som går in i balansavräkningen. Enhet: MWh.",
    "Uppmätt":
        "Uppmätt förbrukning i scenariot (E_cons_x). Enhet: MWh.",
    "Balanshandel (köp − / sälj +)":
        "Motpost som balanserar mätning och avräknad handel: −(Uppmätt + Summa avräknas i balans). Enhet: MWh.",
    "Obalanspris":
        "Obalanspris P_IMB som används för balanshandeln. Enhet: €/MWh.",
    "Balanskostnad BRP":
        "Kostnad/intäkt för balanshandeln: Balanshandel × P_IMB. Enhet: EUR.",
    "Inköpt el som faktureras":
        "Belopp för DA-inköp som BRP fakturerar elhandlaren: |Handel| × P_DA. Enhet: EUR.",
    "Obalanskostnad som faktureras":
        "Den del av BRP:s balanskostnad som faktureras vidare till elhandlaren (styrt av checkboxen). Enhet: EUR.",
    "BRP fakturerar elhandlare":
        "Summa faktura till elhandlaren: Inköpt el som faktureras + Obalanskostnad som faktureras. Enhet: EUR.",
    "BRP nettokostnad":
        "BRP:s resultat: Kostnad handel + Balanskostnad BRP + Inköpt el som faktureras + Obalanskostnad som faktureras. Enhet: EUR.",
}

# Bygg tooltip-matris i samma form som df_brp (alla kolumner, innan filtrering)
tooltips = pd.DataFrame("", index=df_brp.index, columns=df_brp.columns)
for i, field in enumerate(df_brp["Fält"]):
    tooltips.iloc[i, 0] = brp_row_tips.get(field, "")

# --------- NYTT: filtrera kolumner utifrån scenario-checkboxar ---------
visible_scenario_cols = [
    full_label
    for short_key, full_label in BRP_SCENARIO_COLUMNS.items()
    if st.session_state.get(f"show_brp_{short_key}", True)
]

# Se till att alltid ha Fält + Enhet kvar
ordered_cols = ["Fält", *visible_scenario_cols, "Enhet"]

df_brp_visible = df_brp[ordered_cols]
tooltips_visible = tooltips[ordered_cols]

# Skapa Styler med tooltips för den filtrerade tabellen
styled_brp = df_brp_visible.style.set_tooltips(tooltips_visible)

# ----- Visa BRP-tabellen med hover-tooltips på första kolumnen -----
st.table(styled_brp)





# BSP köper in energi vid nedreglering (default: False)
bsp_buy_up = st.checkbox(
    "BSP köper in energi vid nedreglering",
    value=False,
    help="När ikryssad bokas en DA-handel till P_DA för uppregleringsscenarier (B)."
)



# ---------- Checkbox för avdrag på över/underleverans ----------
apply_penalty = st.checkbox(
    "Tillämpa avdrag för BSP vid över/underleverans",
    value=False,
    help="Om urkryssad sätts över/underleveranspris till 0 €/MWh.",
)


# >>> Lägg in DEN HÄR BLOCKET HÄR <<<
st.checkbox(
    "Motsatt kompensation i 5b (RE → BSP)",
    value=False,
    key="rev_comp_5b",   # unik nyckel
    help="Default: ingen kompensation i 5b. Om ikryssad betalar RE kompensation till BSP."
)
rev_comp_5b = st.session_state.get("rev_comp_5b", False)
# >>> slut på nytt block <<<




# ---------- TABELL 2: BSP (1a–5b) ----------
st.markdown("## BSP")

def _bsp_metrics(
    pay_basis: str,
    with_comp: bool,
    E_bud_x: float,
    E_akt_x: float,
    is_up: bool,                 # True = B-scenario (ned), False = A-scenario (upp)
    comp_sign: int = -1
):
    # 1) Ersättning (bud eller akt)
    raw_vol_pay = E_bud_x if pay_basis == "bud" else E_akt_x      # "äkta" volym för beräkning
    disp_vol_pay = -raw_vol_pay if is_up else raw_vol_pay         # visningsvolym: minus i B
    price_pay = P_COMP
    res_pay   = abs(raw_vol_pay) * price_pay                      # resultat baserat på absolut volym

    # 2) Under/överleverans (endast när baserat på bud)
    if pay_basis == "bud":
        vol_dev   = abs(E_akt_x - E_bud_x)
        price_dev = P_PEN if apply_penalty else 0.0
        res_dev   = -(vol_dev * price_dev)
    else:
        vol_dev = price_dev = res_dev = 0.0

    # 3) Kompensation BSP↔RE
    if with_comp:
        vol_comp   = E_akt_x
        price_comp = P_RECOMP
        res_comp   = comp_sign * vol_comp * price_comp
    else:
        vol_comp = price_comp = res_comp = 0.0

    # 4) DA-handel vid nedreglering (endast om checkbox ikryssad och scenario är B)
    if is_up and bsp_buy_up:
        da_vol   = E_akt_x
        da_price = P_DA
        da_cost  = -(da_vol * da_price)   # kostnad för BSP => negativ
    else:
        da_vol = da_price = da_cost = 0.0

    # 5) Nettoresultat
    res_netto = res_pay + res_dev + res_comp + da_cost

    return {
        "Budvolym/Aktiverad volym": disp_vol_pay,   # visar minus i B
        "Ersättningspris": price_pay,
        "Ersättningsresultat": res_pay,            # absolutvolym
        "Under/överleveransvolym": vol_dev,
        "Under/överleveranspris": price_dev,
        "Under/överleveransresultat": res_dev,
        "Kompensationsvolym": vol_comp,
        "Kompensationspris": price_comp,
        "Kompensationsresultat": res_comp,

        "DA handel vid nedreglering": da_vol,
        "DA pris": da_price,
        "Kostnad DA handel": da_cost,

        "BSP nettoresultat": res_netto,
    }


# A (ned) & B (upp)
E_bud_down, E_bud_up   = E_bud, 10.0
E_akt_down, E_akt_up   = E_akt, 8.0

# 10 scenarier (1a–5b)
bsp_1a = _bsp_metrics("bud", False, E_bud_down, E_akt_down, is_up=False)
bsp_1b = _bsp_metrics("bud", False, E_bud_up,   E_akt_up,   is_up=True)

bsp_2a = _bsp_metrics("bud", False, E_bud_down, E_akt_down, is_up=False)
bsp_2b = _bsp_metrics("bud", False, E_bud_up,   E_akt_up,   is_up=True)

bsp_3a = _bsp_metrics("akt", False, E_bud_down, E_akt_down, is_up=False)
bsp_3b = _bsp_metrics("akt", False, E_bud_up,   E_akt_up,   is_up=True)

bsp_4a = _bsp_metrics("akt", False, E_bud_down, E_akt_down, is_up=False)
bsp_4b = _bsp_metrics("akt", False, E_bud_up,   E_akt_up,   is_up=True)

# 5a: BSP betalar komp (negativt) – ned (a)
bsp_5a = _bsp_metrics("akt", True,  E_bud_down, E_akt_down, comp_sign=-1, is_up=False)

# 5b: motsatt komp ev. aktiv – upp (b)
bsp_5b = _bsp_metrics("akt", rev_comp_5b, E_bud_up, E_akt_up, comp_sign=+1, is_up=True)


rows_bsp = [
    ("Budvolym/Aktiverad volym",
        bsp_1a["Budvolym/Aktiverad volym"], bsp_1b["Budvolym/Aktiverad volym"],
        bsp_2a["Budvolym/Aktiverad volym"], bsp_2b["Budvolym/Aktiverad volym"],
        bsp_3a["Budvolym/Aktiverad volym"], bsp_3b["Budvolym/Aktiverad volym"],
        bsp_4a["Budvolym/Aktiverad volym"], bsp_4b["Budvolym/Aktiverad volym"],
        bsp_5a["Budvolym/Aktiverad volym"], bsp_5b["Budvolym/Aktiverad volym"], "MWh"
    ),
    ("Ersättningspris",
        bsp_1a["Ersättningspris"], bsp_1b["Ersättningspris"],
        bsp_2a["Ersättningspris"], bsp_2b["Ersättningspris"],
        bsp_3a["Ersättningspris"], bsp_3b["Ersättningspris"],
        bsp_4a["Ersättningspris"], bsp_4b["Ersättningspris"],
        bsp_5a["Ersättningspris"], bsp_5b["Ersättningspris"], "€/MWh"
    ),
    ("Ersättningsresultat",
        bsp_1a["Ersättningsresultat"], bsp_1b["Ersättningsresultat"],
        bsp_2a["Ersättningsresultat"], bsp_2b["Ersättningsresultat"],
        bsp_3a["Ersättningsresultat"], bsp_3b["Ersättningsresultat"],
        bsp_4a["Ersättningsresultat"], bsp_4b["Ersättningsresultat"],
        bsp_5a["Ersättningsresultat"], bsp_5b["Ersättningsresultat"], "EUR"
    ),
    ("Under/överleveransvolym",
        bsp_1a["Under/överleveransvolym"], bsp_1b["Under/överleveransvolym"],
        bsp_2a["Under/överleveransvolym"], bsp_2b["Under/överleveransvolym"],
        bsp_3a["Under/överleveransvolym"], bsp_3b["Under/överleveransvolym"],
        bsp_4a["Under/överleveransvolym"], bsp_4b["Under/överleveransvolym"],
        bsp_5a["Under/överleveransvolym"], bsp_5b["Under/överleveransvolym"], "MWh"
    ),
    ("Under/överleveranspris",
        bsp_1a["Under/överleveranspris"], bsp_1b["Under/överleveranspris"],
        bsp_2a["Under/överleveranspris"], bsp_2b["Under/överleveranspris"],
        bsp_3a["Under/överleveranspris"], bsp_3b["Under/överleveranspris"],
        bsp_4a["Under/överleveranspris"], bsp_4b["Under/överleveranspris"],
        bsp_5a["Under/överleveranspris"], bsp_5b["Under/överleveranspris"], "€/MWh"
    ),
    ("Under/överleveransresultat",
        bsp_1a["Under/överleveransresultat"], bsp_1b["Under/överleveransresultat"],
        bsp_2a["Under/överleveransresultat"], bsp_2b["Under/överleveransresultat"],
        bsp_3a["Under/överleveransresultat"], bsp_3b["Under/överleveransresultat"],
        bsp_4a["Under/överleveransresultat"], bsp_4b["Under/överleveransresultat"],
        bsp_5a["Under/överleveransresultat"], bsp_5b["Under/överleveransresultat"], "EUR"
    ),
    ("Kompensationsvolym",
        bsp_1a["Kompensationsvolym"], bsp_1b["Kompensationsvolym"],
        bsp_2a["Kompensationsvolym"], bsp_2b["Kompensationsvolym"],
        bsp_3a["Kompensationsvolym"], bsp_3b["Kompensationsvolym"],
        bsp_4a["Kompensationsvolym"], bsp_4b["Kompensationsvolym"],
        bsp_5a["Kompensationsvolym"], bsp_5b["Kompensationsvolym"], "MWh"
    ),
    ("Kompensationspris",
        bsp_1a["Kompensationspris"], bsp_1b["Kompensationspris"],
        bsp_2a["Kompensationspris"], bsp_2b["Kompensationspris"],
        bsp_3a["Kompensationspris"], bsp_3b["Kompensationspris"],
        bsp_4a["Kompensationspris"], bsp_4b["Kompensationspris"],
        bsp_5a["Kompensationspris"], bsp_5b["Kompensationspris"], "€/MWh"
    ),
    ("Kompensationsresultat",
        bsp_1a["Kompensationsresultat"], bsp_1b["Kompensationsresultat"],
        bsp_2a["Kompensationsresultat"], bsp_2b["Kompensationsresultat"],
        bsp_3a["Kompensationsresultat"], bsp_3b["Kompensationsresultat"],
        bsp_4a["Kompensationsresultat"], bsp_4b["Kompensationsresultat"],
        bsp_5a["Kompensationsresultat"], bsp_5b["Kompensationsresultat"], "EUR"
    ),
    ("DA handel vid nedreglering",
        bsp_1a["DA handel vid nedreglering"], bsp_1b["DA handel vid nedreglering"],
        bsp_2a["DA handel vid nedreglering"], bsp_2b["DA handel vid nedreglering"],
        bsp_3a["DA handel vid nedreglering"], bsp_3b["DA handel vid nedreglering"],
        bsp_4a["DA handel vid nedreglering"], bsp_4b["DA handel vid nedreglering"],
        bsp_5a["DA handel vid nedreglering"], bsp_5b["DA handel vid nedreglering"], "MWh"
    ),
    ("DA pris",
        bsp_1a["DA pris"], bsp_1b["DA pris"],
        bsp_2a["DA pris"], bsp_2b["DA pris"],
        bsp_3a["DA pris"], bsp_3b["DA pris"],
        bsp_4a["DA pris"], bsp_4b["DA pris"],
        bsp_5a["DA pris"], bsp_5b["DA pris"], "€/MWh"
    ),
    ("Kostnad DA handel",
        bsp_1a["Kostnad DA handel"], bsp_1b["Kostnad DA handel"],
        bsp_2a["Kostnad DA handel"], bsp_2b["Kostnad DA handel"],
        bsp_3a["Kostnad DA handel"], bsp_3b["Kostnad DA handel"],
        bsp_4a["Kostnad DA handel"], bsp_4b["Kostnad DA handel"],
        bsp_5a["Kostnad DA handel"], bsp_5b["Kostnad DA handel"], "EUR"
    ),
    ("BSP nettoresultat",
        bsp_1a["BSP nettoresultat"], bsp_1b["BSP nettoresultat"],
        bsp_2a["BSP nettoresultat"], bsp_2b["BSP nettoresultat"],
        bsp_3a["BSP nettoresultat"], bsp_3b["BSP nettoresultat"],
        bsp_4a["BSP nettoresultat"], bsp_4b["BSP nettoresultat"],
        bsp_5a["BSP nettoresultat"], bsp_5b["BSP nettoresultat"], "EUR"
    ),
]


columns_bsp = [
    "Fält",
    "1a BRP=BSP, Upp – Bud/underlev.",
    "1b BRP=BSP, Ned – Bud/underlev.",
    "2a BRP=BSP, Upp – Bud/överlev.",
    "2b BRP=BSP, Ned – Bud/överlev.",
    "3a BRP=BSP, Upp – Uppmätt akt.",
    "3b BRP=BSP, Ned – Uppmätt akt.",
    "4a BRP≠BSP, Upp – Uppmätt (ingen komp)",
    "4b BRP≠BSP, Ned – Uppmätt (ingen komp)",
    "5a BRP≠BSP, Upp – Uppmätt (med komp)",
    "5b BRP≠BSP, Ned – Uppmätt (med komp)",
    "Enhet",
]


def _fmt_bsp(v, unit):
    try:
        if unit == "MWh":
            return f"{float(v):,.0f}"
        if unit == "€/MWh":
            return f"{float(v):,.2f}"
        if unit == "EUR":
            return f"{float(v):,.0f}"
    except Exception:
        return v
    return v


df_bsp = pd.DataFrame(rows_bsp, columns=columns_bsp)

# Formatera värden
for col in df_bsp.columns[1:-1]:
    df_bsp[col] = [_fmt_bsp(v, u) for v, u in zip(df_bsp[col], df_bsp["Enhet"])]

# ---------- (NYTT) Tooltips för BSP-rader ----------
bsp_row_tips = {
    "Budvolym/Aktiverad volym":
        "Volym som ersättning baseras på: E_bud (bud) eller E_akt (uppmätt). Negativ i B-scenarier (nedreglering).",
    "Ersättningspris":
        "Pris per MWh som BSP får för aktiveringen: P_COMP (alt. obalanspris om checkbox).",
    "Ersättningsresultat":
        "Intäkt baserad på ersättningsvolym: |Budvolym/Aktiverad volym| × Ersättningspris.",
    "Under/överleveransvolym":
        "Skillnad mellan uppmätt aktivering och budad volym: |E_akt − E_bud| (endast när ersättning baseras på bud).",
    "Under/överleveranspris":
        "Avdragspris P_PEN för över-/underleverans (0 om checkbox för avdrag ej ikryssad).",
    "Under/överleveransresultat":
        "Avdrag för över-/underleverans: − Under/överleveransvolym × Under/överleveranspris.",
    "Kompensationsvolym":
        "Volym som används för kompensation mellan BSP och RE (oftast E_akt i scen 5).",
    "Kompensationspris":
        "Pris för kompensation mellan BSP och RE: P_RECOMP.",
    "Kompensationsresultat":
        "Resultat av kompensationen: Kompensationsvolym × Kompensationspris × comp_sign (tecken beror på riktning).",
    "DA handel vid nedreglering":
        "Extra DA-handel BSP gör i ned-scenarier när checkboxen 'BSP köper in energi vid nedreglering' är ikryssad.",
    "DA pris":
        "DA-pris P_DA som används för köp/sälj i raden 'DA handel vid nedreglering'.",
    "Kostnad DA handel":
        "Kostnad/intäkt för DA-handel vid nedreglering: − DA handel × DA pris (negativt = kostnad).",
    "BSP nettoresultat":
        "Samlat resultat för BSP: Ersättningsresultat + Under/överleveransresultat + Kompensationsresultat + Kostnad DA handel.",
}

# Bygg tooltip-matris: samma form som df_bsp, men fyll bara första kolumnen
tooltips_bsp = pd.DataFrame("", index=df_bsp.index, columns=df_bsp.columns)
for i, field in enumerate(df_bsp["Fält"]):
    tooltips_bsp.iloc[i, 0] = bsp_row_tips.get(field, "")

# --------- NYTT: filtrera kolumner utifrån scenario-checkboxar ---------
# Vi återanvänder samma BRP_SCENARIO_COLUMNS som för BRP-tabellen
visible_scenario_cols = [
    full_label
    for short_key, full_label in BRP_SCENARIO_COLUMNS.items()
    if st.session_state.get(f"show_brp_{short_key}", True)
]

# Se till att alltid ha Fält + Enhet kvar
ordered_cols_bsp = ["Fält", *visible_scenario_cols, "Enhet"]

df_bsp_visible = df_bsp[ordered_cols_bsp]
tooltips_bsp_visible = tooltips_bsp[ordered_cols_bsp]

# Skapa Styler med tooltips
styled_bsp = df_bsp_visible.style.set_tooltips(tooltips_bsp_visible)

# Visa tabellen med hover-tooltips på kolumnen "Fält"
st.table(styled_bsp)








# ---------- Checkbox: Elhandlaren vidarefakturerar balanskostnader ----------
# Initiera session state vid behov
if "re_forward_balance_costs" not in st.session_state:
    st.session_state["re_forward_balance_costs"] = True

# Visa checkbox ovanför RE-tabellen
re_forward_balance_costs = st.checkbox(
    "Elhandlaren vidarefakturerar balanskostnader till slutkunden",
    key="re_forward_balance_costs",
    help="Om urkryssad står elhandlaren själv för balanskostnaden och fakturerar inte slutkunden."
)


# Hämtar värdet direkt från session_state så det fungerar även vid dubblett-checkboxes
re_forward_balance_costs = st.session_state["re_forward_balance_costs"]


# ---------- Checkbox: Elhandlaren använder DA pris som slutkundspris ----------
use_da_price = st.checkbox(
    "Använd DA pris som slutkundens elpris",
    value=False,
    key="use_da_price",
    help="När ikryssad sätts slutkundens elpris = P_DA istället för att räknas från kostnad/volym."
)




# ---------- TABELL 3: Elhandlare / RE (Scenario 1–5) ----------
# ---------- TABELL 3: Elhandlare / RE (Scenario 1–5) ----------
# ---------- TABELL 3: Elhandlare / RE (Scenario 1a–5b) ----------
st.markdown("## RE")

def _re_metrics_v4(
    m_brp: dict,
    e_cons: float,
    obalansjust_mwh: float,
    with_comp: bool,
    re_sign: int = +1,  # +1 = RE får från BSP, -1 = RE betalar BSP
):
    re_forward_balance_costs = st.session_state.get("re_forward_balance_costs", True)
    use_da_as_customer_price = st.session_state.get("use_da_as_customer_price", False)

    # BRP → RE
    re_inkop_eur = -abs(m_brp["Handel"]) * P_DA
    re_balansfakt_eur = -m_brp["Obalanskostnad som faktureras"] if brp_forward_balance_costs else 0.0

    # Kompensation (RE ↔ BSP)
    re_comp_vol_mwh = obalansjust_mwh if with_comp else 0.0
    re_comp_eur = re_sign * re_comp_vol_mwh * P_RECOMP   # + intäkt för RE / − kostnad för RE

    # Vad skickas vidare till kund?
    balans_till_kund_eur = re_balansfakt_eur if re_forward_balance_costs else 0.0

    # Total kostnad som ska faktureras (belopp, ej pris)
    re_kostnad_att_fakturera_eur = -(re_inkop_eur + balans_till_kund_eur + re_comp_eur)

    # Volym till kund
    re_cust_vol_mwh = e_cons

    # Kostnadsbaserat snittpris (används om man inte låser till DA-pris)
    if re_cust_vol_mwh:
        pris_kund_kostnadsbas = re_kostnad_att_fakturera_eur / re_cust_vol_mwh
    else:
        pris_kund_kostnadsbas = 0.0

    # (NYTT) Slutkundens elpris: använd DA-pris om checkboxen är ikryssad
    if st.session_state.get("use_da_price", False):
        slutkund_elpris_per_mwh = P_DA
    else:
        slutkund_elpris_per_mwh = (
            re_kostnad_att_fakturera_eur / re_cust_vol_mwh
        ) if re_cust_vol_mwh else 0.0

    # Kundens kostnad enligt valt pris
    re_cust_cost_eur = re_cust_vol_mwh * slutkund_elpris_per_mwh

    # RE:s resultat
    re_net_eur = re_inkop_eur + re_balansfakt_eur + re_comp_eur + re_cust_cost_eur

    # (NYTT) Snittpris för inköp el som kan faktureras
    vol_att_fakturera = re_cust_vol_mwh
    snittpris_inkop = (
        re_kostnad_att_fakturera_eur / vol_att_fakturera
    ) if vol_att_fakturera else 0.0

    return {
        "Inköpt el fakturerad av BRP": re_inkop_eur,
        "Balanskostnad fakturerad av BRP": re_balansfakt_eur,
        "Kompensationsvolym för flexibilitet": re_comp_vol_mwh,
        "Kompensationsbelopp": re_comp_eur,  # + intäkt för RE / − kostnad för RE

        # (NYTT namn) – var tidigare "Kostnad att fakturera kunden"
        "Kostnad att fakturera slutkunden": re_kostnad_att_fakturera_eur,

        # (NY etikett för visningen i tabellen)
        "Volym att fakturera kunden": vol_att_fakturera,

        # (NY rad)
        "Snittpris för inköp el som kan faktureras": snittpris_inkop,

        "Slutkundens elpris": slutkund_elpris_per_mwh,
        "Kostnad som faktureras slutkund": re_cust_cost_eur,

        # Bakåtkompatibilitet
        "Volym som faktureras slutkund": re_cust_vol_mwh,

        "Resultat": re_net_eur,
    }


# --- Definiera scenarier 1a–5b ---
re_1a = _re_metrics_v4(m1a, E_cons_1a, E_bud_down, with_comp=False)
re_1b = _re_metrics_v4(m1b, E_cons_1b, E_bud_up,   with_comp=False)
re_2a = _re_metrics_v4(m2a, E_cons_2a, E_bud_down, with_comp=False)
re_2b = _re_metrics_v4(m2b, E_cons_2b, E_bud_up,   with_comp=False)
re_3a = _re_metrics_v4(m3a, E_cons_3a, E_akt_down, with_comp=False)
re_3b = _re_metrics_v4(m3b, E_cons_3b, E_akt_up,   with_comp=False)
re_4a = _re_metrics_v4(m4a, E_cons_4a, E_akt_down, with_comp=False)
re_4b = _re_metrics_v4(m4b, E_cons_4b, E_akt_up,   with_comp=False)

# 5a: RE ska ALLTID få kompensation (BSP → RE)
re_5a = _re_metrics_v4(m5a, E_cons_5a, E_akt_down, with_comp=True,  re_sign=+1)

# 5b: default ingen komp; om checkbox ✓ så betalar RE BSP
re_5b = _re_metrics_v4(m5b, E_cons_5b, E_akt_up,   with_comp=rev_comp_5b, re_sign=-1)


# --- Tabellstruktur ---
re_row_specs = [
    ("Inköpt el fakturerad av BRP", "EUR"),
    ("Balanskostnad fakturerad av BRP", "EUR"),
    ("Kompensationsvolym för flexibilitet", "MWh"),
    ("Kompensationsbelopp", "EUR"),
    ("Kostnad att fakturera slutkunden", "EUR"),
    ("Volym att fakturera kunden", "MWh"),
    ("Snittpris för inköp el som kan faktureras", "€/MWh"),
    ("Slutkundens elpris", "€/MWh"),
    ("Kostnad som faktureras slutkund", "EUR"),
    ("Resultat", "EUR"),
]

rows_re = []
for f, unit in re_row_specs:
    rows_re.append((
        f,
        re_1a[f], re_1b[f],
        re_2a[f], re_2b[f],
        re_3a[f], re_3b[f],
        re_4a[f], re_4b[f],
        re_5a[f], re_5b[f],
        unit
    ))

df_re = pd.DataFrame(rows_re, columns=[
    "Fält",
    "1a BRP=BSP, Upp – Bud/underlev.",
    "1b BRP=BSP, Ned – Bud/underlev.",
    "2a BRP=BSP, Upp – Bud/överlev.",
    "2b BRP=BSP, Ned – Bud/överlev.",
    "3a BRP=BSP, Upp – Uppmätt akt.",
    "3b BRP=BSP, Ned – Uppmätt akt.",
    "4a BRP≠BSP, Upp – Uppmätt (ingen komp)",
    "4b BRP≠BSP, Ned – Uppmätt (ingen komp)",
    "5a BRP≠BSP, Upp – Uppmätt (med komp)",
    "5b BRP≠BSP, Ned – Uppmätt (med komp)",
    "Enhet",
])

def _fmt_re(v, e):
    try:
        if e == "MWh":
            return f"{float(v):,.0f}"
        if e == "€/MWh":
            return f"{float(v):,.2f}"
        if e == "EUR":
            return f"{float(v):,.0f}"
    except Exception:
        return v
    return v

for col in df_re.columns[1:-1]:
    df_re[col] = [_fmt_re(v, e) for v, e in zip(df_re[col], df_re["Enhet"])]

# ---------- (NYTT) Tooltips för RE-rader ----------
re_row_tips = {
    "Inköpt el fakturerad av BRP":
        "RE:s kostnad för el som köps från BRP: −|Handel| × P_DA. Negativt värde = kostnad.",
    "Balanskostnad fakturerad av BRP":
        "Del av BRP:s balanskostnad som faktureras vidare till RE (beroende på om BRP vidarefakturerar).",
    "Kompensationsvolym för flexibilitet":
        "Volym som ligger till grund för kompensation mellan RE och BSP (ofta lika med obalansjusteringen).",
    "Kompensationsbelopp":
        "Belopp för kompensation mellan RE och BSP: re_sign × Kompensationsvolym × P_RECOMP.",
    "Kostnad att fakturera slutkunden":
        "Total kostnad (inköp + ev. balans + komp) som RE behöver täcka genom kundfakturering.",
    "Volym att fakturera kunden":
        "MWh som RE fakturerar slutkund för (normalt samma som kundens förbrukning E_cons).",
    "Snittpris för inköp el som kan faktureras":
        "Kostnadsbaserat snittpris: (Kostnad att fakturera slutkunden) / (Volym att fakturera kunden).",
    "Slutkundens elpris":
        "Elpris som faktiskt används mot slutkunden: antingen snittpriset eller P_DA om checkboxen är ikryssad.",
    "Kostnad som faktureras slutkund":
        "Beloppet på kundens faktura: Slutkundens elpris × Volym som faktureras slutkund.",
    "Resultat":
        "RE:s resultat i timmen: inköp från BRP + balanskostnad + kompensation + intäkt från slutkund.",
}

# Bygg tooltip-matris: samma form som df_re, fyll bara första kolumnen ("Fält")
tooltips_re = pd.DataFrame("", index=df_re.index, columns=df_re.columns)
for i, field in enumerate(df_re["Fält"]):
    tooltips_re.iloc[i, 0] = re_row_tips.get(field, "")

# --------- NYTT: filtrera kolumner utifrån scenario-checkboxar ---------
# Vi återanvänder samma BRP_SCENARIO_COLUMNS som för BRP- och BSP-tabellerna
visible_scenario_cols_re = [
    full_label
    for short_key, full_label in BRP_SCENARIO_COLUMNS.items()
    if st.session_state.get(f"show_brp_{short_key}", True)
]

# Se till att alltid ha Fält + Enhet kvar
ordered_cols_re = ["Fält", *visible_scenario_cols_re, "Enhet"]

df_re_visible = df_re[ordered_cols_re]
tooltips_re_visible = tooltips_re[ordered_cols_re]

# Skapa Styler med tooltips
styled_re = df_re_visible.style.set_tooltips(tooltips_re_visible)

# Visa tabellen med hover-tooltips på kolumnen "Fält"
st.table(styled_re)




# ---------- TABELL 4: Sammanställning – resultat per aktör och scenario ----------
# ---------- TABELL 4: Sammanställning – resultat per aktör och scenario ----------
# ---------- TABELL 4: Sammanställning – resultat per aktör och scenario ----------
st.markdown("## Aktörers resultat per scenario")

# --- Resultat per aktör & scenario (A/B) ---
brp_1a = m1a["BRP nettokostnad"]; brp_1b = m1b["BRP nettokostnad"]
brp_2a = m2a["BRP nettokostnad"]; brp_2b = m2b["BRP nettokostnad"]
brp_3a = m3a["BRP nettokostnad"]; brp_3b = m3b["BRP nettokostnad"]
brp_4a = m4a["BRP nettokostnad"]; brp_4b = m4b["BRP nettokostnad"]
brp_5a = m5a["BRP nettokostnad"]; brp_5b = m5b["BRP nettokostnad"]

bsp_1a_res = bsp_1a["BSP nettoresultat"]; bsp_1b_res = bsp_1b["BSP nettoresultat"]
bsp_2a_res = bsp_2a["BSP nettoresultat"]; bsp_2b_res = bsp_2b["BSP nettoresultat"]
bsp_3a_res = bsp_3a["BSP nettoresultat"]; bsp_3b_res = bsp_3b["BSP nettoresultat"]
bsp_4a_res = bsp_4a["BSP nettoresultat"]; bsp_4b_res = bsp_4b["BSP nettoresultat"]
bsp_5a_res = bsp_5a["BSP nettoresultat"]; bsp_5b_res = bsp_5b["BSP nettoresultat"]

re_1a_res = re_1a["Resultat"]; re_1b_res = re_1b["Resultat"]
re_2a_res = re_2a["Resultat"]; re_2b_res = re_2b["Resultat"]
re_3a_res = re_3a["Resultat"]; re_3b_res = re_3b["Resultat"]
re_4a_res = re_4a["Resultat"]; re_4b_res = re_4b["Resultat"]
re_5a_res = re_5a["Resultat"]; re_5b_res = re_5b["Resultat"]

# Hjälpfunktioner
def _na_or_sum(a, b, enabled: bool):
    return (a + b) if enabled else "NA"

def _na_or_sum3(a, b, c, enabled: bool):
    return (a + b + c) if enabled else "NA"

def _na_or_value(value, enabled: bool):
    return value if enabled else "NA"

# BRP=BSP i scen 1–3 (a & b). Scen 4–5 är BRP≠BSP.
en_brp_eq_bsp = {
    "1a": True, "1b": True, "2a": True, "2b": True, "3a": True, "3b": True,
    "4a": False, "4b": False, "5a": False, "5b": False
}

# Kombinerade resultat
brp_bsp_1a = _na_or_sum(brp_1a, bsp_1a_res, en_brp_eq_bsp["1a"])
brp_bsp_1b = _na_or_sum(brp_1b, bsp_1b_res, en_brp_eq_bsp["1b"])
brp_bsp_2a = _na_or_sum(brp_2a, bsp_2a_res, en_brp_eq_bsp["2a"])
brp_bsp_2b = _na_or_sum(brp_2b, bsp_2b_res, en_brp_eq_bsp["2b"])
brp_bsp_3a = _na_or_sum(brp_3a, bsp_3a_res, en_brp_eq_bsp["3a"])
brp_bsp_3b = _na_or_sum(brp_3b, bsp_3b_res, en_brp_eq_bsp["3b"])
brp_bsp_4a = _na_or_sum(brp_4a, bsp_4a_res, en_brp_eq_bsp["4a"])
brp_bsp_4b = _na_or_sum(brp_4b, bsp_4b_res, en_brp_eq_bsp["4b"])
brp_bsp_5a = _na_or_sum(brp_5a, bsp_5a_res, en_brp_eq_bsp["5a"])
brp_bsp_5b = _na_or_sum(brp_5b, bsp_5b_res, en_brp_eq_bsp["5b"])

total_1a = _na_or_sum3(brp_1a, bsp_1a_res, re_1a_res, en_brp_eq_bsp["1a"])
total_1b = _na_or_sum3(brp_1b, bsp_1b_res, re_1b_res, en_brp_eq_bsp["1b"])
total_2a = _na_or_sum3(brp_2a, bsp_2a_res, re_2a_res, en_brp_eq_bsp["2a"])
total_2b = _na_or_sum3(brp_2b, bsp_2b_res, re_2b_res, en_brp_eq_bsp["2b"])
total_3a = _na_or_sum3(brp_3a, bsp_3a_res, re_3a_res, en_brp_eq_bsp["3a"])
total_3b = _na_or_sum3(brp_3b, bsp_3b_res, re_3b_res, en_brp_eq_bsp["3b"])
total_4a = _na_or_sum3(brp_4a, bsp_4a_res, re_4a_res, en_brp_eq_bsp["4a"])
total_4b = _na_or_sum3(brp_4b, bsp_4b_res, re_4b_res, en_brp_eq_bsp["4b"])
total_5a = _na_or_sum3(brp_5a, bsp_5a_res, re_5a_res, en_brp_eq_bsp["5a"])
total_5b = _na_or_sum3(brp_5b, bsp_5b_res, re_5b_res, en_brp_eq_bsp["5b"])

# --- Målresultat (Scenario 5a – BSP resultat) ---
goal_value = bsp_5a_res  # välj 5a (nedreglering) som referens
goal_row = (
    "Målresultat för aktör (Scenario 5a – BSP resultat)",
    _na_or_value(goal_value, True),  _na_or_value(goal_value, True),
    _na_or_value(goal_value, True),  _na_or_value(goal_value, True),
    _na_or_value(goal_value, True),  _na_or_value(goal_value, True),
    _na_or_value(goal_value, False), _na_or_value(goal_value, False),
    _na_or_value(goal_value, False), _na_or_value(goal_value, False),
    "EUR/NA",
)

def _diff_or_na(goal, total, enabled: bool):
    if not enabled or isinstance(total, str):
        return "NA"
    return goal - total

diff_row = (
    "Avvikelse mot aktörers målresultat",
    _diff_or_na(goal_value, total_1a, en_brp_eq_bsp["1a"]),
    _diff_or_na(goal_value, total_1b, en_brp_eq_bsp["1b"]),
    _diff_or_na(goal_value, total_2a, en_brp_eq_bsp["2a"]),
    _diff_or_na(goal_value, total_2b, en_brp_eq_bsp["2b"]),
    _diff_or_na(goal_value, total_3a, en_brp_eq_bsp["3a"]),
    _diff_or_na(goal_value, total_3b, en_brp_eq_bsp["3b"]),
    _diff_or_na(goal_value, total_4a, en_brp_eq_bsp["4a"]),
    _diff_or_na(goal_value, total_4b, en_brp_eq_bsp["4b"]),
    _diff_or_na(goal_value, total_5a, en_brp_eq_bsp["5a"]),
    _diff_or_na(goal_value, total_5b, en_brp_eq_bsp["5b"]),
    "EUR/NA",
)

# --- Tabellinnehåll (10 kolumner: 1a–5b) ---
rows_sum = [
    ("BRP resultat",                brp_1a,       brp_1b,       brp_2a,       brp_2b,       brp_3a,       brp_3b,       brp_4a,       brp_4b,       brp_5a,       brp_5b,       "EUR"),
    ("BSP resultat",                bsp_1a_res,   bsp_1b_res,   bsp_2a_res,   bsp_2b_res,   bsp_3a_res,   bsp_3b_res,   bsp_4a_res,   bsp_4b_res,   bsp_5a_res,   bsp_5b_res,   "EUR"),
    ("Elhandlare resultat",         re_1a_res,    re_1b_res,    re_2a_res,    re_2b_res,    re_3a_res,    re_3b_res,    re_4a_res,    re_4b_res,    re_5a_res,    re_5b_res,    "EUR"),
    ("BRP+BSP resultat",            brp_bsp_1a,   brp_bsp_1b,   brp_bsp_2a,   brp_bsp_2b,   brp_bsp_3a,   brp_bsp_3b,   brp_bsp_4a,   brp_bsp_4b,   brp_bsp_5a,   brp_bsp_5b,   "EUR/NA"),
    ("BRP+BSP+Elhandlare resultat", total_1a,     total_1b,     total_2a,     total_2b,     total_3a,     total_3b,     total_4a,     total_4b,     total_5a,     total_5b,     "EUR/NA"),
    goal_row,
    diff_row,
]

df_sum = pd.DataFrame(
    rows_sum,
    columns=[
        "Fält",
        "1a BRP=BSP, Upp – Bud/underlev.",
        "1b BRP=BSP, Ned – Bud/underlev.",
        "2a BRP=BSP, Upp – Bud/överlev.",
        "2b BRP=BSP, Ned – Bud/överlev.",
        "3a BRP=BSP, Upp – Uppmätt akt.",
        "3b BRP=BSP, Ned – Uppmätt akt.",
        "4a BRP≠BSP, Upp – Uppmätt (ingen komp)",
        "4b BRP≠BSP, Ned – Uppmätt (ingen komp)",
        "5a BRP≠BSP, Upp – Uppmätt (med komp)",
        "5b BRP≠BSP, Ned – Uppmätt (med komp)",
        "Enhet",
    ],
)

def _fmt_any(v, unit):
    if isinstance(v, str):
        return v
    try:
        if unit in ("EUR", "EUR/NA"):
            return f"{float(v):,.0f}"
        if unit == "€/MWh":
            return f"{float(v):,.2f}"
        if unit == "MWh":
            return f"{float(v):,.0f}"
    except Exception:
        return str(v)
    return str(v)

for col in df_sum.columns[1:-1]:
    df_sum[col] = [_fmt_any(v, u) for v, u in zip(df_sum[col], df_sum["Enhet"])]

# ---------- (NYTT) Tooltips för sammanställningen ----------
sum_row_tips = {
    "BRP resultat":
        "BRP:s nettokostnad per scenario (från Tabell 1). Negativt = kostnad, positivt = intäkt.",
    "BSP resultat":
        "BSP:s nettoresultat per scenario (från Tabell 2). Positivt = intäkt, negativt = kostnad.",
    "Elhandlare resultat":
        "Elhandlarens (RE:s) nettoresultat per scenario (från Tabell 3). Positivt = vinst, negativt = förlust.",
    "BRP+BSP resultat":
        "Summa BRP resultat + BSP resultat i scenarion där BRP=BSP (1a–3b). I övriga scenarion visas 'NA'.",
    "BRP+BSP+Elhandlare resultat":
        "Totalsumma för BRP + BSP + RE i scenarion där BRP=BSP (1a–3b). Ger systemets samlade resultat.",
    "Målresultat för aktör (Scenario 5a – BSP resultat)":
        "Mål-/referensnivå: BSP:s nettoresultat i scenario 5a (nedreglering). Används som benchmark.",
    "Avvikelse mot aktörers målresultat":
        "Skillnad mellan målresultatet (5a, BSP) och totalsumman per scenario. "
        "Positivt = bättre än mål, negativt = sämre. 'NA' där jämförelse inte är relevant.",
}

tooltips_sum = pd.DataFrame("", index=df_sum.index, columns=df_sum.columns)
for i, field in enumerate(df_sum["Fält"]):
    tooltips_sum.iloc[i, 0] = sum_row_tips.get(field, "")

# ------- Scenario-kolumnfiltrering (samma logik som Tabell 1–3) -------

# BRP_SCENARIO_COLUMNS är samma dict som används av BRP/BSP/RE:
# { "1a": "1a BRP=BSP, Upp – Bud/underlev.",  ... }

visible_scenario_cols_sum = [
    full_label
    for short_key, full_label in BRP_SCENARIO_COLUMNS.items()
    if st.session_state.get(f"show_brp_{short_key}", True)
]

# Nya kolumnordningen
ordered_cols_sum = ["Fält", *visible_scenario_cols_sum, "Enhet"]

df_sum_visible = df_sum[ordered_cols_sum]
tooltips_sum_visible = tooltips_sum[ordered_cols_sum]

# ------- Skapa styler med tooltips -------
styled_sum = df_sum_visible.style.set_tooltips(tooltips_sum_visible)

# ------- Visa tabellen -------
st.table(styled_sum)








# ---------- TABELL 5: Slutkundens elpris per scenario ----------
# ---------- TABELL 5: Slutkundens elpris per scenario ----------
# ---------- TABELL 5: Slutkundens elpris per scenario ----------
st.markdown("## Slutkundens elpris per scenario")

# Pris per scenario (hämtat från RE-tabellen), A/B
def _price_from_re(re_row: dict) -> float:
    # Läs direkt från RE-tabellen så checkboxen "Använd DA pris…" får effekt
    return re_row["Slutkundens elpris"]


price_1a = _price_from_re(re_1a); price_1b = _price_from_re(re_1b)
price_2a = _price_from_re(re_2a); price_2b = _price_from_re(re_2b)
price_3a = _price_from_re(re_3a); price_3b = _price_from_re(re_3b)
price_4a = _price_from_re(re_4a); price_4b = _price_from_re(re_4b)
price_5a = _price_from_re(re_5a); price_5b = _price_from_re(re_5b)

# Målpris = scenario 5a (ned). Byt till price_5b om du vill jämföra mot upp.
goal_price_value = price_5a

def _fmt_any(v, unit):
    if isinstance(v, str):
        return v
    try:
        if unit in ("EUR", "EUR/NA"):
            return f"{float(v):,.0f}"
        if unit == "€/MWh":
            return f"{float(v):,.2f}"
        return v
    except Exception:
        return v

def _diff_price(goal, price):
    try:
        return price - goal
    except Exception:
        return "NA"

def _extra_cost(diff, volume):
    try:
        return diff * volume
    except Exception:
        return "NA"

# Avvikelser mot målpris
diff_1a = _diff_price(goal_price_value, price_1a); diff_1b = _diff_price(goal_price_value, price_1b)
diff_2a = _diff_price(goal_price_value, price_2a); diff_2b = _diff_price(goal_price_value, price_2b)
diff_3a = _diff_price(goal_price_value, price_3a); diff_3b = _diff_price(goal_price_value, price_3b)
diff_4a = _diff_price(goal_price_value, price_4a); diff_4b = _diff_price(goal_price_value, price_4b)
diff_5a = _diff_price(goal_price_value, price_5a); diff_5b = _diff_price(goal_price_value, price_5b)

# Ökad totalkostnad = diff * volym (volym per scenario)
extra_1a = _extra_cost(diff_1a, re_1a["Volym som faktureras slutkund"])
extra_1b = _extra_cost(diff_1b, re_1b["Volym som faktureras slutkund"])
extra_2a = _extra_cost(diff_2a, re_2a["Volym som faktureras slutkund"])
extra_2b = _extra_cost(diff_2b, re_2b["Volym som faktureras slutkund"])
extra_3a = _extra_cost(diff_3a, re_3a["Volym som faktureras slutkund"])
extra_3b = _extra_cost(diff_3b, re_3b["Volym som faktureras slutkund"])
extra_4a = _extra_cost(diff_4a, re_4a["Volym som faktureras slutkund"])
extra_4b = _extra_cost(diff_4b, re_4b["Volym som faktureras slutkund"])
extra_5a = _extra_cost(diff_5a, re_5a["Volym som faktureras slutkund"])
extra_5b = _extra_cost(diff_5b, re_5b["Volym som faktureras slutkund"])

rows_cust = [
    (
        "Slutkundens elpris (från RE-tabellen)",
        price_1a, price_1b, price_2a, price_2b, price_3a, price_3b, price_4a, price_4b, price_5a, price_5b,
        "€/MWh",
    ),
    (
        "Målresultat för slutkunds elpris (Scenario 5a – Slutkundens elpris)",
        goal_price_value, goal_price_value, goal_price_value, goal_price_value, goal_price_value,
        goal_price_value, goal_price_value, goal_price_value, goal_price_value, goal_price_value,
        "€/MWh",
    ),
    (
        "Avvikelse slutkundens elpris",
        diff_1a, diff_1b, diff_2a, diff_2b, diff_3a, diff_3b, diff_4a, diff_4b, diff_5a, diff_5b,
        "€/MWh",
    ),
    (
        "Ökad totalkostnad slutkund",
        extra_1a, extra_1b, extra_2a, extra_2b, extra_3a, extra_3b, extra_4a, extra_4b, extra_5a, extra_5b,
        "EUR",
    ),
]

df_cust = pd.DataFrame(
    rows_cust,
    columns=[
        "Fält",
        "1a BRP=BSP, Upp – Bud/underlev.",
        "1b BRP=BSP, Ned – Bud/underlev.",
        "2a BRP=BSP, Upp – Bud/överlev.",
        "2b BRP=BSP, Ned – Bud/överlev.",
        "3a BRP=BSP, Upp – Uppmätt akt.",
        "3b BRP=BSP, Ned – Uppmätt akt.",
        "4a BRP≠BSP, Upp – Uppmätt (ingen komp)",
        "4b BRP≠BSP, Ned – Uppmätt (ingen komp)",
        "5a BRP≠BSP, Upp – Uppmätt (med komp)",
        "5b BRP≠BSP, Ned – Uppmätt (med komp)",
        "Enhet",
    ],
)

for col in df_cust.columns[1:-1]:
    df_cust[col] = [_fmt_any(v, u) for v, u in zip(df_cust[col], df_cust["Enhet"])]

# ---------- (NYTT) Tooltips för kundpris-tabellen ----------
cust_row_tips = {
    "Slutkundens elpris (från RE-tabellen)":
        "Det elpris per MWh som kunden faktiskt betalar i varje scenario, hämtat direkt från RE-tabellen "
        "(påverkas av checkboxen 'Använd DA pris…').",
    "Målresultat för slutkunds elpris (Scenario 5a – Slutkundens elpris)":
        "Mål-/referenspris för slutkunden: slutkundens elpris i scenario 5a (nedreglering). Används som jämförelsenivå.",
    "Avvikelse slutkundens elpris":
        "Skillnad mellan kundens pris i respektive scenario och målpriset (5a). "
        "Positivt värde = dyrare än mål, negativt = billigare än mål.",
    "Ökad totalkostnad slutkund":
        "Extra (eller minskad) total kostnad i EUR för kunden jämfört med målpris: "
        "Avvikelse i pris × volym som faktureras slutkund i scenariot.",
}

tooltips_cust = pd.DataFrame("", index=df_cust.index, columns=df_cust.columns)
for i, field in enumerate(df_cust["Fält"]):
    tooltips_cust.iloc[i, 0] = cust_row_tips.get(field, "")

# -------- Scenario-kolumnfiltrering för Tabell 5 --------
# Använder samma BRP_SCENARIO_COLUMNS och show_brp_* som övriga tabeller

visible_scenario_cols_cust = [
    full_label
    for short_key, full_label in BRP_SCENARIO_COLUMNS.items()
    if st.session_state.get(f"show_brp_{short_key}", True)
]

ordered_cols_cust = ["Fält", *visible_scenario_cols_cust, "Enhet"]

df_cust_visible = df_cust[ordered_cols_cust]
tooltips_cust_visible = tooltips_cust[ordered_cols_cust]

# Skapa Styler med tooltips på "Fält"-kolumnen
styled_cust = df_cust_visible.style.set_tooltips(tooltips_cust_visible)

# Visa tabellen
st.table(styled_cust)

# Tillåt omvänd neutralisering till/från slutkund
allow_reverse_neutral = st.checkbox(
    "Tillåt omvänd neutralisering till/från slutkund",
    value=False,
    help="Om ikryssad neutraliseras även lägre kundpris än målpris (kund betalar tillbaka)."
)



# ---------- TABELL 6: Aktörers resultat efter kompensation (A/B) ----------
st.markdown("## Aktörers resultat efter kompensation")

def _safe_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None

def _comp_need(val, allow_reverse: bool):
    v = _safe_float(val) or 0.0
    return v if allow_reverse else (v if v > 0 else 0.0)

def _base_result(total, bsp):
    t_val = _safe_float(total)
    b_val = _safe_float(bsp)
    return t_val if t_val is not None else (b_val if b_val is not None else 0.0)

def _subtract_base(total, bsp, comp):
    base = _base_result(total, bsp)
    c_val = _safe_float(comp) or 0.0
    return base - c_val

# Kompensationsbehov = max(0, ökad totalkostnad) eller signerat om omvänd neutralisering
comp_need_1a = _comp_need(extra_1a, allow_reverse_neutral); comp_need_1b = _comp_need(extra_1b, allow_reverse_neutral)
comp_need_2a = _comp_need(extra_2a, allow_reverse_neutral); comp_need_2b = _comp_need(extra_2b, allow_reverse_neutral)
comp_need_3a = _comp_need(extra_3a, allow_reverse_neutral); comp_need_3b = _comp_need(extra_3b, allow_reverse_neutral)
comp_need_4a = _comp_need(extra_4a, allow_reverse_neutral); comp_need_4b = _comp_need(extra_4b, allow_reverse_neutral)
comp_need_5a = _comp_need(extra_5a, allow_reverse_neutral); comp_need_5b = _comp_need(extra_5b, allow_reverse_neutral)

# Resultat efter kompensation
tot_after_1a = _subtract_base(total_1a, bsp_1a_res, comp_need_1a)
tot_after_1b = _subtract_base(total_1b, bsp_1b_res, comp_need_1b)
tot_after_2a = _subtract_base(total_2a, bsp_2a_res, comp_need_2a)
tot_after_2b = _subtract_base(total_2b, bsp_2b_res, comp_need_2b)
tot_after_3a = _subtract_base(total_3a, bsp_3a_res, comp_need_3a)
tot_after_3b = _subtract_base(total_3b, bsp_3b_res, comp_need_3b)
tot_after_4a = _subtract_base(total_4a, bsp_4a_res, comp_need_4a)
tot_after_4b = _subtract_base(total_4b, bsp_4b_res, comp_need_4b)
tot_after_5a = _subtract_base(total_5a, bsp_5a_res, comp_need_5a)
tot_after_5b = _subtract_base(total_5b, bsp_5b_res, comp_need_5b)

label_neutral = (
    "Neutralisering till/från slutkund"
    if allow_reverse_neutral
    else "Kompensation till slutkund för neutralisering"
)

rows_comp_total = [
    (
        label_neutral,
        comp_need_1a, comp_need_1b, comp_need_2a, comp_need_2b,
        comp_need_3a, comp_need_3b, comp_need_4a, comp_need_4b,
        comp_need_5a, comp_need_5b,
        "EUR",
    ),
    (
        "Aktörers resultat efter kompensation",
        tot_after_1a, tot_after_1b, tot_after_2a, tot_after_2b,
        tot_after_3a, tot_after_3b, tot_after_4a, tot_after_4b,
        tot_after_5a, tot_after_5b,
        "EUR",
    ),
]

df_comp_total = pd.DataFrame(
    rows_comp_total,
    columns=[
        "Fält",
        "1a BRP=BSP, Upp – Bud/underlev.",
        "1b BRP=BSP, Ned – Bud/underlev.",
        "2a BRP=BSP, Upp – Bud/överlev.",
        "2b BRP=BSP, Ned – Bud/överlev.",
        "3a BRP=BSP, Upp – Uppmätt akt.",
        "3b BRP=BSP, Ned – Uppmätt akt.",
        "4a BRP≠BSP, Upp – Uppmätt (ingen komp)",
        "4b BRP≠BSP, Ned – Uppmätt (ingen komp)",
        "5a BRP≠BSP, Upp – Uppmätt (med komp)",
        "5b BRP≠BSP, Ned – Uppmätt (med komp)",
        "Enhet",
    ],
)

for col in df_comp_total.columns[1:-1]:
    df_comp_total[col] = [_fmt_any(v, u) for v, u in zip(df_comp_total[col], df_comp_total["Enhet"])]

# ---------- (NYTT) Tooltips för kompensations-tabellen ----------
comp_row_tips = {
    label_neutral:
        "Belopp som överförs till/från slutkund för att neutralisera prisavvikelsen: "
        "beräknas från ‘Ökad totalkostnad slutkund’. "
        "Om ‘omvänd neutralisering’ är urkryssad tas bara positiva belopp med.",
    "Aktörers resultat efter kompensation":
        "Samlat resultat för alla aktörer efter att neutraliserings-/kompensationsbeloppet "
        "dragits från utgångsresultatet (totalresultat eller BSP-resultat om total saknas).",
}

tooltips_comp_total = pd.DataFrame("", index=df_comp_total.index, columns=df_comp_total.columns)
for i, field in enumerate(df_comp_total["Fält"]):
    tooltips_comp_total.iloc[i, 0] = comp_row_tips.get(field, "")

# -------- Scenario-kolumnfiltrering för Tabell 6 --------
visible_scenario_cols_comp = [
    full_label
    for short_key, full_label in BRP_SCENARIO_COLUMNS.items()
    if st.session_state.get(f"show_brp_{short_key}", True)
]

ordered_cols_comp = ["Fält", *visible_scenario_cols_comp, "Enhet"]

df_comp_total_visible = df_comp_total[ordered_cols_comp]
tooltips_comp_total_visible = tooltips_comp_total[ordered_cols_comp]

styled_comp_total = df_comp_total_visible.style.set_tooltips(tooltips_comp_total_visible)

# Visa med hover-tooltips på kolumnen "Fält"
st.table(styled_comp_total)

st.caption(
    "Neutralisering = prisavvikelse × volym. Om ‘omvänd neutralisering’ är ikryssad kan beloppet vara negativt (kunden betalar tillbaka)."
)




# ---------- Export: Excel med alla tabeller ----------
from io import BytesIO
from datetime import datetime
import pandas as pd

def _to_excel_sheets(sheets: dict) -> BytesIO:
    output = BytesIO()
    try:
        # Försök använda XlsxWriter om det finns
        writer_engine = "xlsxwriter"
        import xlsxwriter
    except ImportError:
        # Annars använd openpyxl
        writer_engine = "openpyxl"

    with pd.ExcelWriter(output, engine=writer_engine) as writer:
        for sheet_name, df in sheets.items():
            safe_name = sheet_name[:31]
            df.to_excel(writer, index=False, sheet_name=safe_name)

            # Autofit fungerar bara om XlsxWriter används
            if writer_engine == "xlsxwriter":
                ws = writer.sheets[safe_name]
                for col_idx, col in enumerate(df.columns):
                    try:
                        max_len = max(
                            len(str(col)),
                            int(df[col].astype(str).str.len().max() or 0)
                        )
                    except Exception:
                        max_len = len(str(col))
                    ws.set_column(col_idx, col_idx, min(50, max(12, max_len + 2)))

    output.seek(0)
    return output


# Samla alla dina DataFrames här:
sheets = {
    "BRP": df_brp,
    "BSP": df_bsp,
    "RE": df_re,
    "Sammanställning": df_sum,
    "Slutkundens elpris": df_cust,
    "Kompensation": df_comp_total,
}

excel_bytes = _to_excel_sheets(sheets)

st.download_button(
    label="📥 Exportera Excel (alla tabeller)",
    data=excel_bytes,
    file_name=f"scenarios_{datetime.now().strftime('%Y-%m-%d_%H%M')}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    help="Laddar ner en Excel-fil med ett blad per tabell."
)













