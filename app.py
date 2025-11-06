import streamlit as st
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

st.set_page_config(page_title="Scenariosimulator för BRP&BSP", layout="wide")

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



# ---------- Checkbox före BRP-tabellen ----------
# Checkbox ovanför BRP-tabellen
brp_forward_balance_costs = st.checkbox(
    "BRP vidarefakturerar balanskostnader till elhandlare",
    key="brp_forward_balance_costs",   # <-- huvudnyckeln
    help="Om urkryssad står BRP själv för balanskostnaden och fakturerar inte elhandlaren."
)




# ---------- TABELL 1: BRP (Scenario 1–5 sida vid sida) ----------
st.markdown("## BRP")

def _brp_metrics(uppmatt_mwh: float, obalansjust_mwh: float):
    """
    Radvärden givet:
      - uppmätt förbrukning (uppmatt_mwh)
      - obalansjustering (obalansjust_mwh): E_bud (scen 1 & 2) eller E_akt (scen 3–5)
    """
    handel_mwh = handel_sign * V_DA  # Köp = negativt, Sälj = positivt
    kostnad_handel_eur = handel_mwh * P_DA

    # Avräkningsvolym och obalans
    summa_avr_balans_mwh = handel_mwh + obalansjust_mwh
    obalans_mwh = uppmatt_mwh + summa_avr_balans_mwh

    # Balanshandel enligt konvention
    balanshandel_mwh = -obalans_mwh

    # Balanskostnad följer balanshandelns tecken
    balanskostnad_eur = balanshandel_mwh * P_IMB

    # 🔸 Om BRP inte vidarefakturerar – elhandlaren slipper denna kostnad
    obalans_fakt_eur = 0.0 if not brp_forward_balance_costs else -balanskostnad_eur

    inkopt_el_fakt_eur = abs(handel_mwh) * P_DA
    brp_fakt_re_eur = inkopt_el_fakt_eur + obalans_fakt_eur

    # BRP:s resultat – påverkas av om vidarefakturering sker
    brp_netto_eur = kostnad_handel_eur + balanskostnad_eur + inkopt_el_fakt_eur + obalans_fakt_eur

    return {
        "Obalansjusteras baserat på": "Bud" if abs(obalansjust_mwh - E_bud) < 1e-9 else "Uppmätt aktivering",
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


# Scen 1 & 2: under/överleverans runt S (summa avräknas i balans vid bud-justering)
S = (handel_sign * V_DA) + E_bud
E_cons_s1 = E_cons
E_cons_s2 = -E_cons - 2 * S  # spegla obalansen ⇒ 92 -> 88 vid S=-90

# Scen 3–5: uppmätt aktivering som obalansjustering (uppmätt förbrukning = E_cons)
E_cons_s3 = E_cons
E_cons_s4 = E_cons  # BRP≠BSP påverkar inte BRP-graferna – fortfarande E_cons
E_cons_s5 = E_cons

m1 = _brp_metrics(E_cons_s1, E_bud)   # Scen 1
m2 = _brp_metrics(E_cons_s2, E_bud)   # Scen 2
m3 = _brp_metrics(E_cons_s3, E_akt)   # Scen 3 (BRP=BSP, uppmätt aktivering)
m4 = _brp_metrics(E_cons_s4, E_akt)   # Scen 4 (BRP≠BSP, uppmätt aktivering)
m5 = _brp_metrics(E_cons_s5, E_akt)   # Scen 5 (BRP≠BSP, uppmätt aktivering + kompensation)

rows_brp = [
    ("Obalansjusteras baserat på", m1["Obalansjusteras baserat på"], m2["Obalansjusteras baserat på"], m3["Obalansjusteras baserat på"], m4["Obalansjusteras baserat på"], m5["Obalansjusteras baserat på"], ""),
    ("Handel",                      m1["Handel"], m2["Handel"], m3["Handel"], m4["Handel"], m5["Handel"], "MWh"),
    ("DA Pris",                     m1["DA Pris"], m2["DA Pris"], m3["DA Pris"], m4["DA Pris"], m5["DA Pris"], "€/MWh"),
    ("Kostnad handel",              m1["Kostnad handel"], m2["Kostnad handel"], m3["Kostnad handel"], m4["Kostnad handel"], m5["Kostnad handel"], "EUR"),
    ("Obalansjustering",            m1["Obalansjustering"], m2["Obalansjustering"], m3["Obalansjustering"], m4["Obalansjustering"], m5["Obalansjustering"], "MWh"),
    ("Summa avräknas i balans",     m1["Summa avräknas i balans"], m2["Summa avräknas i balans"], m3["Summa avräknas i balans"], m4["Summa avräknas i balans"], m5["Summa avräknas i balans"], "MWh"),
    ("Uppmätt",                     m1["Uppmätt"], m2["Uppmätt"], m3["Uppmätt"], m4["Uppmätt"], m5["Uppmätt"], "MWh"),
    ("Balanshandel (köp − / sälj +)", m1["Balanshandel (köp − / sälj +)"], m2["Balanshandel (köp − / sälj +)"], m3["Balanshandel (köp − / sälj +)"], m4["Balanshandel (köp − / sälj +)"], m5["Balanshandel (köp − / sälj +)"], "MWh"),
    ("Obalanspris",                 m1["Obalanspris"], m2["Obalanspris"], m3["Obalanspris"], m4["Obalanspris"], m5["Obalanspris"], "€/MWh"),
    ("Balanskostnad BRP",           m1["Balanskostnad BRP"], m2["Balanskostnad BRP"], m3["Balanskostnad BRP"], m4["Balanskostnad BRP"], m5["Balanskostnad BRP"], "EUR"),
    ("Inköpt el som faktureras",    m1["Inköpt el som faktureras"], m2["Inköpt el som faktureras"], m3["Inköpt el som faktureras"], m4["Inköpt el som faktureras"], m5["Inköpt el som faktureras"], "EUR"),
    ("Obalanskostnad som faktureras", m1["Obalanskostnad som faktureras"], m2["Obalanskostnad som faktureras"], m3["Obalanskostnad som faktureras"], m4["Obalanskostnad som faktureras"], m5["Obalanskostnad som faktureras"], "EUR"),
    ("BRP fakturerar elhandlare",   m1["BRP fakturerar elhandlare"], m2["BRP fakturerar elhandlare"], m3["BRP fakturerar elhandlare"], m4["BRP fakturerar elhandlare"], m5["BRP fakturerar elhandlare"], "EUR"),
    ("BRP nettokostnad",            m1["BRP nettokostnad"], m2["BRP nettokostnad"], m3["BRP nettokostnad"], m4["BRP nettokostnad"], m5["BRP nettokostnad"], "EUR"),
]

df_brp = pd.DataFrame(rows_brp, columns=[
    "Fält",
    "Scenario 1 - BRP=BSP, bud och underleverans",
    "Scenario 2 - BRP=BSP, bud och överleverans",
    "Scenario 3 - BRP=BSP och uppmätt aktivering",
    "Scenario 4 - BRP≠BSP, uppmätt aktivering (ingen komp)",
    "Scenario 5 - BRP≠BSP, uppmätt aktivering (med komp)",
    "Enhet",
])

def _fmt_cell(v, enhet):
    try:
        if enhet == "MWh":
            return f"{float(v):,.0f}"
        if enhet == "€/MWh":
            return f"{float(v):,.2f}"
        if enhet == "EUR":
            return f"{float(v):,.0f}"
    except:
        return v
    return v

for col in df_brp.columns[1:-1]:
    df_brp[col] = [_fmt_cell(v, e) for v, e in zip(df_brp[col], df_brp["Enhet"])]

st.dataframe(df_brp, use_container_width=True, height=570)




# ---------- Checkbox för avdrag på över/underleverans ----------
apply_penalty = st.checkbox(
    "Tillämpa avdrag för över/underleverans",
    value=False,
    help="Om urkryssad sätts över/underleveranspris till 0 €/MWh.",
)


# ---------- TABELL 2: BSP (Scenario 1–5) ----------
st.markdown("## BSP")

def _bsp_metrics_for_scenario(scen: int):
    """
    scen: 1=bud+under, 2=bud+över, 3=uppmätt (BRP=BSP), 4=uppmätt (BRP≠BSP, ingen komp), 5=uppmätt (BRP≠BSP, med komp)
    - Scen 1 & 2: ersättning baseras på E_bud, avdrag mot |E_akt - E_bud|, ingen komp.
    - Scen 3: ersättning baseras på E_akt, ingen avvikelse, ingen komp.
    - Scen 4: ersättning baseras på E_akt, ingen avvikelse, ingen komp.
    - Scen 5: ersättning baseras på E_akt, ingen avvikelse, med komp (BSP betalar RE).
    """
    if scen in (1, 2):
        vol_pay = E_bud
        price_pay = P_COMP                                    
        res_pay = vol_pay * price_pay
        # Under/överleverans (mot bud) – bara scen 1 & 2
        vol_dev = abs(E_akt - E_bud)                     # MWh
        price_dev = P_PEN if apply_penalty else 0.0      # €/MWh (0 om checkbox urkryssad)
        res_dev = -(vol_dev * price_dev)                 # € (avdrag)
        vol_comp = 0.0
        price_comp = 0.0
        res_comp = 0.0
    elif scen in (3, 4):
        vol_pay = E_akt
        price_pay = P_COMP                                    
        res_pay = vol_pay * price_pay
        vol_dev = 0.0
        price_dev = 0.0
        res_dev = 0.0
        vol_comp = 0.0
        price_comp = 0.0
        res_comp = 0.0
    else:  # scen == 5
        vol_pay = E_akt
        price_pay = P_COMP                                    
        res_pay = vol_pay * price_pay
        vol_dev = 0.0
        price_dev = 0.0
        res_dev = 0.0
        vol_comp = E_akt
        price_comp = P_RECOMP
        res_comp = -(vol_comp * price_comp)  # BSP betalar komp → negativt

    res_netto = res_pay + res_dev + res_comp
    return {
        "Budvolym/Aktiverad volym": vol_pay,      # MWh (bas för ersättning)
        "Ersättningspris": price_pay,             # €/MWh
        "Ersättningsresultat": res_pay,           # €
        "Under/överleveransvolym": vol_dev,       # MWh
        "Under/överleveranspris": price_dev,      # €/MWh
        "Under/överleveransresultat": res_dev,    # €
        "Kompensationsvolym": vol_comp,           # MWh
        "Kompensationspris": price_comp,          # €/MWh
        "Kompensationsresultat": res_comp,        # €
        "BSP nettoresultat": res_netto,           # €
    }

bsp_s1 = _bsp_metrics_for_scenario(1)
bsp_s2 = _bsp_metrics_for_scenario(2)
bsp_s3 = _bsp_metrics_for_scenario(3)
bsp_s4 = _bsp_metrics_for_scenario(4)
bsp_s5 = _bsp_metrics_for_scenario(5)

row_specs_bsp = [
    ("Budvolym/Aktiverad volym",  "MWh"),
    ("Ersättningspris",           "€/MWh"),
    ("Ersättningsresultat",       "EUR"),
    ("Under/överleveransvolym",   "MWh"),
    ("Under/överleveranspris",    "€/MWh"),
    ("Under/överleveransresultat","EUR"),
    ("Kompensationsvolym",        "MWh"),
    ("Kompensationspris",         "€/MWh"),
    ("Kompensationsresultat",     "EUR"),
    ("BSP nettoresultat",         "EUR"),
]

table_rows_bsp = []
for field, unit in row_specs_bsp:
    table_rows_bsp.append((
        field,
        bsp_s1[field], bsp_s2[field], bsp_s3[field], bsp_s4[field], bsp_s5[field], unit
    ))

df_bsp = pd.DataFrame(
    table_rows_bsp,
    columns=[
        "Fält",
        "Scenario 1 - BRP=BSP, bud/under",
        "Scenario 2 - BRP=BSP, bud/över",
        "Scenario 3 - BRP=BSP, uppmätt",
        "Scenario 4 - BRP≠BSP, uppmätt (ingen komp)",
        "Scenario 5 - BRP≠BSP, uppmätt (med komp)",
        "Enhet",
    ],
)

def _fmt(v, enhet):
    try:
        if enhet == "MWh":
            return f"{float(v):,.0f}"
        if enhet == "€/MWh":
            return f"{float(v):,.2f}"
        if enhet == "EUR":
            return f"{float(v):,.0f}"
    except:
        return v
    return v

for col in df_bsp.columns[1:-1]:
    df_bsp[col] = [_fmt(v, e) for v, e in zip(df_bsp[col], df_bsp["Enhet"])]

st.dataframe(df_bsp, use_container_width=True, height=430)



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



# ---------- TABELL 3: Elhandlare / RE (Scenario 1–5) ----------
# ---------- TABELL 3: Elhandlare / RE (Scenario 1–5) ----------
# ---------- TABELL 3: Elhandlare / RE (Scenario 1–5) ----------
st.markdown("## Elhandlare")

def _re_metrics_v3(m_brp: dict, e_cons: float, obalansjust_mwh: float, with_comp: bool):
    # 1) Läs av checkboxen (hanterar dubbletter via session_state)
    re_forward_balance_costs = st.session_state.get("re_forward_balance_costs", True)

    # 2) Inköp från BRP (alltid kostnad för RE)
    re_inkop_eur = -abs(m_brp["Handel"]) * P_DA

    # 3) Balansfaktura från BRP (0 om BRP inte vidarefakturerar till RE)
    if brp_forward_balance_costs:
        re_balansfakt_eur = -m_brp["Obalanskostnad som faktureras"]   # kostnad för RE
    else:
        re_balansfakt_eur = 0.0

    # 4) Kompensationen till RE enligt scenario (kostnad för RE)
    re_comp_vol_mwh = obalansjust_mwh if with_comp else 0.0
    re_comp_eur = re_comp_vol_mwh * P_RECOMP

    # 5) Vad av detta skickar RE vidare till slutkund? (styrt av checkboxen)
    balans_till_kund_eur = re_balansfakt_eur if re_forward_balance_costs else 0.0

    # 6) Kostnad att fakturera kunden (intäkt för RE) = minus (det som skickas vidare)
    re_kostnad_att_fakturera_eur = -(re_inkop_eur + balans_till_kund_eur + re_comp_eur)

    # 7) Volym och kundpris
    re_cust_vol_mwh = e_cons
    slutkund_elpris_per_mwh = (re_kostnad_att_fakturera_eur / re_cust_vol_mwh) if re_cust_vol_mwh else 0.0
    re_cust_cost_eur = re_cust_vol_mwh * slutkund_elpris_per_mwh  # intäkt för RE

    # 8) RE:s resultat (RE:s verkliga kostnader + intäkten från kund)
    re_net_eur = re_inkop_eur + re_balansfakt_eur + re_comp_eur + re_cust_cost_eur

    return {
        "Inköpt el fakturerad av BRP": re_inkop_eur,
        "Balanskostnad fakturerad av BRP": re_balansfakt_eur,         # kostnad för RE
        "Kompensationsvolym för flexibilitet": re_comp_vol_mwh,
        "Kompensationsbelopp": re_comp_eur,                           # kostnad för RE
        "Kostnad att fakturera kunden": re_kostnad_att_fakturera_eur, # intäkt (positiv)
        "Volym som faktureras slutkund": re_cust_vol_mwh,
        "Slutkundens elpris per MWh": slutkund_elpris_per_mwh,
        "Kostnad som faktureras slutkund": re_cust_cost_eur,          # intäkt (positiv)
        "Resultat": re_net_eur,
    }



# Scenarier: 1–3 ingen komp, 4 ingen komp, 5 med kompensation
re_s1 = _re_metrics_v3(m1, E_cons_s1, E_bud, with_comp=False)
re_s2 = _re_metrics_v3(m2, E_cons_s2, E_bud, with_comp=False)
re_s3 = _re_metrics_v3(m3, E_cons_s3, E_akt, with_comp=False)
re_s4 = _re_metrics_v3(m4, E_cons_s4, E_akt, with_comp=False)
re_s5 = _re_metrics_v3(m5, E_cons_s5, E_akt, with_comp=True)

# Tabell RE – uppdaterad ordning och enheter
re_row_specs = [
    ("Inköpt el fakturerad av BRP", "EUR"),
    ("Balanskostnad fakturerad av BRP", "EUR"),
    ("Kompensationsvolym för flexibilitet", "MWh"),
    ("Kompensationsbelopp", "EUR"),
    ("Kostnad att fakturera kunden", "EUR"),      # NY
    ("Volym som faktureras slutkund", "MWh"),
    ("Slutkundens elpris per MWh", "€/MWh"),      # NY
    ("Kostnad som faktureras slutkund", "EUR"),   # ändrad beräkning
    ("Resultat", "EUR"),
]

rows_re = []
for f, unit in re_row_specs:
    rows_re.append((f, re_s1[f], re_s2[f], re_s3[f], re_s4[f], re_s5[f], unit))

df_re = pd.DataFrame(rows_re, columns=[
    "Fält",
    "Scenario 1 - BRP=BSP, bud/under",
    "Scenario 2 - BRP=BSP, bud/över",
    "Scenario 3 - BRP=BSP, uppmätt",
    "Scenario 4 - BRP≠BSP, uppmätt (ingen komp)",
    "Scenario 5 - BRP≠BSP, uppmätt (med komp)",
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
    except:
        return v
    return v

for col in df_re.columns[1:-1]:
    df_re[col] = [_fmt_re(v, e) for v, e in zip(df_re[col], df_re["Enhet"])]

st.dataframe(df_re, use_container_width=True, height=360)


st.checkbox(
    "BRP vidarefakturerar balanskostnader till elhandlare",
    key="brp_forward_balance_costs_copy",                    # <-- unik nyckel
    value=st.session_state["brp_forward_balance_costs"],     # spegla aktuellt värde
    on_change=_sync_brb_copy_to_main,                        # skriv tillbaka vid ändring
    args=("brp_forward_balance_costs_copy",),
)


def _sync_re_copy_to_main():
    st.session_state["re_forward_balance_costs"] = st.session_state["re_forward_balance_costs_copy"]

st.checkbox(
    "Elhandlaren vidarefakturerar balanskostnader till slutkunden",
    key="re_forward_balance_costs_copy",
    value=st.session_state["re_forward_balance_costs"],  # spegla aktuellt värde
    on_change=_sync_re_copy_to_main
)



# ---------- TABELL 4: Sammanställning – resultat per aktör och scenario ----------
# ---------- TABELL 4: Sammanställning – resultat per aktör och scenario ----------
# ---------- TABELL 4: Sammanställning – resultat per aktör och scenario ----------
st.markdown("## Aktörers resultat per scenario")


# Resultat per aktör & scenario
brp_s1, brp_s2, brp_s3, brp_s4, brp_s5 = (
    m1["BRP nettokostnad"], m2["BRP nettokostnad"], m3["BRP nettokostnad"],
    m4["BRP nettokostnad"], m5["BRP nettokostnad"]
)
bsp_s1_res, bsp_s2_res, bsp_s3_res, bsp_s4_res, bsp_s5_res = (
    bsp_s1["BSP nettoresultat"], bsp_s2["BSP nettoresultat"], bsp_s3["BSP nettoresultat"],
    bsp_s4["BSP nettoresultat"], bsp_s5["BSP nettoresultat"]
)
re_s1_res, re_s2_res, re_s3_res, re_s4_res, re_s5_res = (
    re_s1["Resultat"], re_s2["Resultat"], re_s3["Resultat"],
    re_s4["Resultat"], re_s5["Resultat"]
)

# Hjälpfunktioner
def _na_or_sum(a, b, enabled: bool):
    return (a + b) if enabled else "NA"

def _na_or_sum3(a, b, c, enabled: bool):
    return (a + b + c) if enabled else "NA"

def _na_or_value(value, enabled: bool):
    return value if enabled else "NA"

# Kombinerade resultat (endast scen 1–3)
brp_bsp_s1 = _na_or_sum(brp_s1, bsp_s1_res, True)
brp_bsp_s2 = _na_or_sum(brp_s2, bsp_s2_res, True)
brp_bsp_s3 = _na_or_sum(brp_s3, bsp_s3_res, True)
brp_bsp_s4 = _na_or_sum(brp_s4, bsp_s4_res, False)
brp_bsp_s5 = _na_or_sum(brp_s5, bsp_s5_res, False)

total_s1 = _na_or_sum3(brp_s1, bsp_s1_res, re_s1_res, True)
total_s2 = _na_or_sum3(brp_s2, bsp_s2_res, re_s2_res, True)
total_s3 = _na_or_sum3(brp_s3, bsp_s3_res, re_s3_res, True)
total_s4 = _na_or_sum3(brp_s4, bsp_s4_res, re_s4_res, False)
total_s5 = _na_or_sum3(brp_s5, bsp_s5_res, re_s5_res, False)

# --- NYTT: Målresultat (Scenario 5 – BSP resultat), visas bara när BRP=BSP ---
# --- NYTT: Målresultat för aktörer (Scenario 5 – BSP resultat), visas bara när BRP=BSP ---
# --- NYTT: Målresultat för aktörer (Scenario 5 – BSP resultat), visas bara när BRP=BSP ---
goal_value = bsp_s5_res

goal_row = (
    "Målresultat för aktör (Scenario 5 – BSP resultat)",
    _na_or_value(goal_value, True),
    _na_or_value(goal_value, True),
    _na_or_value(goal_value, True),
    _na_or_value(goal_value, False),
    _na_or_value(goal_value, False),
    "EUR/NA",
)

# --- NYTT: Avvikelse mot aktörers målresultat ---
def _diff_or_na(goal, total, enabled: bool):
    if not enabled or isinstance(total, str):
        return "NA"
    return goal - total

diff_row = (
    "Avvikelse mot aktörers målresultat",
    _diff_or_na(goal_value, total_s1, True),
    _diff_or_na(goal_value, total_s2, True),
    _diff_or_na(goal_value, total_s3, True),
    _diff_or_na(goal_value, total_s4, False),
    _diff_or_na(goal_value, total_s5, False),
    "EUR/NA",
)

# --- Slutkundens elpris per MWh (från RE-tabellen) per scenario ---
price_s1 = re_s1["Kostnad som faktureras slutkund"] / re_s1["Volym som faktureras slutkund"]
price_s2 = re_s2["Kostnad som faktureras slutkund"] / re_s2["Volym som faktureras slutkund"]
price_s3 = re_s3["Kostnad som faktureras slutkund"] / re_s3["Volym som faktureras slutkund"]
price_s4 = re_s4["Kostnad som faktureras slutkund"] / re_s4["Volym som faktureras slutkund"]
price_s5 = re_s5["Kostnad som faktureras slutkund"] / re_s5["Volym som faktureras slutkund"]

current_price_row = (
    "Slutkundens elpris per MWh (från RE-tabellen)",
    price_s1, price_s2, price_s3, price_s4, price_s5,
    "€/MWh",
)

# --- NYTT: Målresultat för slutkunds elpris (Scenario 5) ---
goal_price_value = price_s5
goal_price_row = (
    "Målresultat för slutkunds elpris (Scenario 5 – Slutkundens elpris per MWh)",
    _na_or_value(goal_price_value, True),
    _na_or_value(goal_price_value, True),
    _na_or_value(goal_price_value, True),
    _na_or_value(goal_price_value, False),
    _na_or_value(goal_price_value, False),
    "€/MWh",
)

# --- NYTT: Avvikelse slutkundens elpris (scenario-pris minus målpris) ---
def _diff_price_or_na(goal, price, enabled: bool):
    if not enabled or isinstance(price, str):
        return "NA"
    return price - goal

diff_price_row = (
    "Avvikelse slutkundens elpris",
    _diff_price_or_na(goal_price_value, price_s1, True),
    _diff_price_or_na(goal_price_value, price_s2, True),
    _diff_price_or_na(goal_price_value, price_s3, True),
    _diff_price_or_na(goal_price_value, price_s4, False),
    _diff_price_or_na(goal_price_value, price_s5, False),
    "€/MWh",
)



# Tabellinnehåll
rows_sum = [
    ("BRP resultat",                    brp_s1,       brp_s2,       brp_s3,       brp_s4,       brp_s5,       "EUR"),
    ("BSP resultat",                    bsp_s1_res,   bsp_s2_res,   bsp_s3_res,   bsp_s4_res,   bsp_s5_res,   "EUR"),
    ("Elhandlare resultat",             re_s1_res,    re_s2_res,    re_s3_res,    re_s4_res,    re_s5_res,    "EUR"),
    ("BRP+BSP resultat",                brp_bsp_s1,   brp_bsp_s2,   brp_bsp_s3,   brp_bsp_s4,   brp_bsp_s5,   "EUR/NA"),
    ("BRP+BSP+Elhandlare resultat",     total_s1,     total_s2,     total_s3,     total_s4,     total_s5,     "EUR/NA"),
    goal_row,
    diff_row,
]




df_sum = pd.DataFrame(
    rows_sum,
    columns=[
        "Fält",
        "Scenario 1 - BRP=BSP, bud/under",
        "Scenario 2 - BRP=BSP, bud/över",
        "Scenario 3 - BRP=BSP, uppmätt",
        "Scenario 4 - BRP≠BSP, uppmätt (ingen komp)",
        "Scenario 5 - BRP≠BSP, uppmätt (med komp)",
        "Enhet",
    ],
)

# Formattera värden
def _fmt_any(v, unit):
    # Låt "NA" passera som text
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
    
for col in df_sum.columns[1:-1]:
    df_sum[col] = df_sum[col].astype(str)

st.dataframe(df_sum, use_container_width=True, height=340)





# ---------- TABELL 5: Slutkundens elpris per scenario ----------
# ---------- TABELL 5: Slutkundens elpris per scenario ----------
# ---------- TABELL 5: Slutkundens elpris per scenario ----------
st.markdown("## Slutkundens elpris per scenario")

# Pris per scenario (hämtat från RE-tabellen)
price_s1 = re_s1["Kostnad som faktureras slutkund"] / re_s1["Volym som faktureras slutkund"] if re_s1["Volym som faktureras slutkund"] else 0.0
price_s2 = re_s2["Kostnad som faktureras slutkund"] / re_s2["Volym som faktureras slutkund"] if re_s2["Volym som faktureras slutkund"] else 0.0
price_s3 = re_s3["Kostnad som faktureras slutkund"] / re_s3["Volym som faktureras slutkund"] if re_s3["Volym som faktureras slutkund"] else 0.0
price_s4 = re_s4["Kostnad som faktureras slutkund"] / re_s4["Volym som faktureras slutkund"] if re_s4["Volym som faktureras slutkund"] else 0.0
price_s5 = re_s5["Kostnad som faktureras slutkund"] / re_s5["Volym som faktureras slutkund"] if re_s5["Volym som faktureras slutkund"] else 0.0

# Målpris = scenario 5
goal_price_value = price_s5

def _fmt_any(v, unit):
    if isinstance(v, str):
        return v
    try:
        if unit in ("EUR", "EUR/NA"):
            return f"{float(v):,.0f}"
        if unit == "€/MWh":
            return f"{float(v):,.2f}"
        return v
    except:
        return v

def _diff_price(goal, price):
    try:
        return price - goal
    except:
        return "NA"

def _extra_cost(diff, volume):
    try:
        return diff * volume
    except:
        return "NA"

# Beräkna avvikelser först
diff_s1 = _diff_price(goal_price_value, price_s1)
diff_s2 = _diff_price(goal_price_value, price_s2)
diff_s3 = _diff_price(goal_price_value, price_s3)
diff_s4 = _diff_price(goal_price_value, price_s4)
diff_s5 = _diff_price(goal_price_value, price_s5)

# Beräkna ökad totalkostnad baserat på diff * volym
extra_s1 = _extra_cost(diff_s1, re_s1["Volym som faktureras slutkund"])
extra_s2 = _extra_cost(diff_s2, re_s2["Volym som faktureras slutkund"])
extra_s3 = _extra_cost(diff_s3, re_s3["Volym som faktureras slutkund"])
extra_s4 = _extra_cost(diff_s4, re_s4["Volym som faktureras slutkund"])
extra_s5 = _extra_cost(diff_s5, re_s5["Volym som faktureras slutkund"])

rows_cust = [
    (
        "Slutkundens elpris (från RE-tabellen)",
        price_s1, price_s2, price_s3, price_s4, price_s5,
        "€/MWh",
    ),
    (
        "Målresultat för slutkunds elpris (Scenario 5 – Slutkundens elpris per MWh)",
        goal_price_value, goal_price_value, goal_price_value,
        goal_price_value, goal_price_value,
        "€/MWh",
    ),
    (
        "Avvikelse slutkundens elpris",
        diff_s1, diff_s2, diff_s3, diff_s4, diff_s5,
        "€/MWh",
    ),
    (
        "Ökad totalkostnad slutkund",
        extra_s1, extra_s2, extra_s3, extra_s4, extra_s5,
        "EUR",
    ),
]

df_cust = pd.DataFrame(
    rows_cust,
    columns=[
        "Fält",
        "Scenario 1 - BRP=BSP, bud/under",
        "Scenario 2 - BRP=BSP, bud/över",
        "Scenario 3 - BRP=BSP, uppmätt",
        "Scenario 4 - BRP≠BSP, uppmätt (ingen komp)",
        "Scenario 5 - BRP≠BSP, uppmätt (med komp)",
        "Enhet",
    ],
)

for col in df_cust.columns[1:-1]:
    df_cust[col] = [_fmt_any(v, u) for v, u in zip(df_cust[col], df_cust["Enhet"])]

st.dataframe(df_cust, use_container_width=True, height=250)

st.caption(
    "‘Ökad totalkostnad slutkund’ beräknas som (Avvikelse slutkundens elpris × volym som faktureras slutkund). "
    "Det visar hur mycket mer eller mindre slutkunden betalar totalt jämfört med scenario 5."
)




# ---------- TABELL 6: Aktörers resultat efter kompensation ----------
st.markdown("## Aktörers resultat efter kompensation")

def _safe_float(x):
    """Konverterar till float om möjligt, annars returnerar None."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return None

# Kompensationsbehov = max(0, ökad totalkostnad slutkund)
def _pos(x):
    val = _safe_float(x)
    if val is None:
        return "NA"
    return val if val > 0 else 0.0

comp_need_s1 = _pos(extra_s1)
comp_need_s2 = _pos(extra_s2)
comp_need_s3 = _pos(extra_s3)
comp_need_s4 = _pos(extra_s4)
comp_need_s5 = _pos(extra_s5)

# Hjälpfunktion för säker subtraktion
def _safe_subtract(a, b):
    a_val, b_val = _safe_float(a), _safe_float(b)
    if a_val is None or b_val is None:
        return "NA"
    return a_val - b_val

# Nya resultat efter kompensation (BRP+BSP+Elhandlare)
tot_after_s1 = _safe_subtract(total_s1, comp_need_s1)
tot_after_s2 = _safe_subtract(total_s2, comp_need_s2)
tot_after_s3 = _safe_subtract(total_s3, comp_need_s3)
tot_after_s4 = _safe_subtract(total_s4, comp_need_s4)
tot_after_s5 = _safe_subtract(total_s5, comp_need_s5)

rows_comp_total = [
    ("Kompensation till slutkund för neutralisering", comp_need_s1, comp_need_s2, comp_need_s3, comp_need_s4, comp_need_s5, "EUR"),
    ("Aktörers resultat efter kompensation",          tot_after_s1, tot_after_s2, tot_after_s3, tot_after_s4, tot_after_s5, "EUR"),
]

df_comp_total = pd.DataFrame(
    rows_comp_total,
    columns=[
        "Fält",
        "Scenario 1 - BRP=BSP, bud/under",
        "Scenario 2 - BRP=BSP, bud/över",
        "Scenario 3 - BRP=BSP, uppmätt",
        "Scenario 4 - BRP≠BSP, uppmätt (ingen komp)",
        "Scenario 5 - BRP≠BSP, uppmätt (med komp)",
        "Enhet",
    ],
)

# Formattera
for col in df_comp_total.columns[1:-1]:
    df_comp_total[col] = [_fmt_any(v, u) for v, u in zip(df_comp_total[col], df_comp_total["Enhet"])]

st.dataframe(df_comp_total, use_container_width=True, height=200)
st.caption(
    "Kompensation = max(0, ‘Ökad totalkostnad slutkund’). "
    "‘Aktörers resultat efter kompensation’ = (BRP+BSP+Elhandlare resultat) − kompensation."
)
