"""
Backend Flask per il calcolo dell'itinerario Pollena Trocchia -> Monte Sant'Angelo.

Architettura a 3 step, calcolati A RITROSO a partire dall'orario di arrivo desiderato:
  Step 3 (Bus ANM)          Piazzale Tecchio -> Monte Sant'Angelo   [orari statici/stimati]
  Step 2 (Metro Linea 2)    Garibaldi -> Campi Flegrei              [dati LIVE da ViaggiaTreno]
  Step 1 (Circumvesuviana)  Pollena Trocchia -> Garibaldi           [orari statici + ritardo simulato]

Il flusso di calcolo va dall'ultimo step al primo:
  target_arrivo -> trova bus utile -> trova treno utile -> trova Circumvesuviana utile
"""

import datetime
import os

from flask import Flask, jsonify
from flask_cors import CORS
import requests

app = Flask(__name__)

# In produzione conviene restringere l'origine al tuo dominio GitHub Pages,
# es: CORS(app, origins=["https://<tuo-utente>.github.io"])
CORS(app)


# ============================================================================
# CONFIGURAZIONE — questa è la parte che DEVI calibrare con i dati reali
# ============================================================================

# --- Step 1: Circumvesuviana (EAV) — Pollena Trocchia -> Napoli Garibaldi ---
# Le API di EAV non sono accessibili in modo affidabile: qui uso un orario
# statico. Sostituisci questi orari con quelli ufficiali (feriale) che trovi su:
#   https://www.eavsrl.it (sezione orari) oppure sull'app "EAV in Movimento".
# NOTA: questi orari sono un ESEMPIO DI STRUTTURA, non l'orario reale — vanno
# sostituiti prima di fidarti dell'app per un treno che devi prendere davvero.
EAV_TIMETABLE_POLLENA = [
    "06:12", "06:34", "06:57", "07:19", "07:41", "08:03", "08:26", "08:48",
    "09:10", "09:33", "09:55", "10:17", "10:40", "11:02", "11:24", "11:47",
    "12:09", "12:31", "12:54", "13:16", "13:38", "14:01", "14:23", "14:45",
    "15:08", "15:30", "15:52", "16:15", "16:37", "16:59", "17:22", "17:44",
    "18:06", "18:29", "18:51",
]
EAV_DURATA_MINUTI = 45          # tempo di percorrenza stimato Pollena -> Garibaldi
RITARDO_STANDARD_EAV_MIN = 5    # ritardo medio che vuoi simulare di default (modificabile)

# --- Step 3: Bus ANM — Piazzale Tecchio -> Monte Sant'Angelo -----------------
# Anche qui non esiste un'API realtime affidabile: struttura basata su orari
# stimati/programmati per linea. Aggiungi/correggi le linee che usi davvero.
# Fonte migliore degli orari "a mano": l'app ANM "Gira Napoli" (mostra le
# fermate in tempo reale) oppure Moovit. Se vuoi automatizzare del tutto
# questa parte, ANM pubblica anche un feed GTFS statico open data
# (cercalo su transit.land, feed "f-s-anm~it"): puoi scaricarlo e generare
# questa struttura via script invece di scriverla a mano — vedi il README.
ANM_LINEE = {
    "180": {
        "partenze_piazzale_tecchio": [
            "07:05", "07:20", "07:35", "07:50", "08:05", "08:20", "08:35",
            "08:50", "09:05", "09:20", "09:40", "10:00", "10:20",
        ],
        "durata_minuti": 12,
    },
    "584": {
        "partenze_piazzale_tecchio": [
            "07:00", "07:18", "07:36", "07:54", "08:12", "08:30", "08:48",
            "09:06", "09:24", "09:45", "10:05", "10:25",
        ],
        "durata_minuti": 10,
    },
    # Aggiungi qui altre linee compatibili, stesso formato:
    # "XXX": {"partenze_piazzale_tecchio": [...], "durata_minuti": N},
}

# --- Step 2: Metro Linea 2 — Garibaldi -> Campi Flegrei ---------------------
CODICE_STAZIONE_GARIBALDI = "S09109"
# Tempo di percorrenza Garibaldi -> Campi Flegrei. L'API "partenze" non
# fornisce l'orario di arrivo alla singola fermata, solo la partenza da
# Garibaldi: quindi lo stimiamo con questa costante. Calibrala confrontando
# qualche corsa reale con l'orario Trenitalia, poi tienila fissa.
DURATA_GARIBALDI_CAMPIFLEGREI_MIN = 17

# Parole chiave usate per riconoscere, tra i treni in partenza da Garibaldi,
# quelli diretti verso Campi Flegrei (cioè la tratta ovest della Linea 2).
# Se in log vedi treni scartati per errore, aggiungi qui la destinazione mancante.
DESTINAZIONI_VALIDE_LINEA2 = [
    "CAMPI FLEGREI", "POZZUOLI", "TORREGAVETA", "LICOLA", "QUARTO", "FUORIGROTTA",
]

# --- Trasferimenti a piedi tra un mezzo e l'altro ---------------------------
BUFFER_CAMPIFLEGREI_TECCHIO_MIN = 4   # a piedi da Campi Flegrei a Piazzale Tecchio
BUFFER_GARIBALDI_INTERSCAMBIO_MIN = 6  # cambio banchina EAV -> Linea 2 a Garibaldi


# ============================================================================
# UTILITY orari
# ============================================================================

def parse_time_str(s):
    """Converte 'HH:MM' o 'HH:MM:SS' in un oggetto datetime.time."""
    s = s.strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.datetime.strptime(s, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"Formato orario non riconosciuto: {s!r}")


def format_time(t):
    return t.strftime("%H:%M")


def add_minutes(t, minuti):
    dt = datetime.datetime.combine(datetime.date.today(), t) + datetime.timedelta(minutes=minuti)
    return dt.time()


def subtract_minutes(t, minuti):
    return add_minutes(t, -minuti)


# ============================================================================
# STEP 2 — Metro Linea 2 (dati LIVE da ViaggiaTreno)
# ============================================================================

def get_treni_in_partenza_da_garibaldi():
    """
    Scarica la lista dei treni in partenza da Garibaldi (S09109) dall'API
    non ufficiale di ViaggiaTreno. Solleva un'eccezione in caso di errore:
    la gestione dei fallback è responsabilità del chiamante.
    """
    timestamp = datetime.datetime.now().strftime(
        "%a %b %d %Y %H:%M:%S GMT+0200 (Ora legale dell\u2019Europa centrale)"
    )
    url = (
        "http://www.viaggiatreno.it/infomobilita/resteasy/viaggiatreno/"
        f"partenze/{CODICE_STAZIONE_GARIBALDI}/{timestamp}"
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    return response.json()


def trova_treno_linea2(deadline_arrivo_campiflegrei, treni_in_partenza):
    """
    Tra i treni live in partenza da Garibaldi, trova quello diretto verso
    Campi Flegrei con l'orario di partenza più tardivo possibile che comunque
    arriva (partenza + durata + ritardo reale) entro `deadline_arrivo_campiflegrei`.
    Ritorna None se nessun treno è compatibile.
    """
    candidati = []
    for treno in treni_in_partenza:
        destinazione = (treno.get("destinazione") or "").upper()
        if not any(dest in destinazione for dest in DESTINAZIONI_VALIDE_LINEA2):
            continue

        partenza_str = treno.get("compOrarioPartenza")
        if not partenza_str:
            continue
        try:
            partenza = parse_time_str(partenza_str)
        except ValueError:
            continue

        ritardo = treno.get("ritardo") or 0
        arrivo_stimato = add_minutes(partenza, DURATA_GARIBALDI_CAMPIFLEGREI_MIN + max(ritardo, 0))

        if arrivo_stimato <= deadline_arrivo_campiflegrei:
            candidati.append({
                "numero_treno": treno.get("numeroTreno"),
                "destinazione": treno.get("destinazione"),
                "partenza": partenza,
                "arrivo_stimato": arrivo_stimato,
                "ritardo": ritardo,
            })

    if not candidati:
        return None
    return max(candidati, key=lambda c: c["partenza"])


# ============================================================================
# STEP 3 — Bus ANM (orari statici, multi-linea)
# ============================================================================

def trova_bus_utile(deadline_arrivo_universita):
    """
    Tra tutte le linee ANM configurate, trova il bus con la partenza più
    tardiva da Piazzale Tecchio che arriva comunque entro `deadline_arrivo_universita`.
    Ritorna None se nessun bus è compatibile.
    """
    candidati = []
    for linea, dati in ANM_LINEE.items():
        durata = dati["durata_minuti"]
        for partenza_str in dati["partenze_piazzale_tecchio"]:
            partenza = parse_time_str(partenza_str)
            arrivo = add_minutes(partenza, durata)
            if arrivo <= deadline_arrivo_universita:
                candidati.append({"linea": linea, "partenza": partenza, "arrivo": arrivo})

    if not candidati:
        return None
    return max(candidati, key=lambda c: c["partenza"])


# ============================================================================
# STEP 1 — Circumvesuviana EAV (orari statici + ritardo simulato)
# ============================================================================

def trova_circumvesuviana(deadline_arrivo_garibaldi, ritardo_simulato_min=RITARDO_STANDARD_EAV_MIN):
    """
    Trova la corsa EAV da Pollena Trocchia con la partenza più tardiva che
    arrivi comunque a Garibaldi entro `deadline_arrivo_garibaldi`, includendo
    il ritardo standard simulato. Ritorna None se nessuna corsa è compatibile.
    """
    candidati = []
    for partenza_str in EAV_TIMETABLE_POLLENA:
        partenza = parse_time_str(partenza_str)
        arrivo = add_minutes(partenza, EAV_DURATA_MINUTI + ritardo_simulato_min)
        if arrivo <= deadline_arrivo_garibaldi:
            candidati.append({"partenza": partenza, "arrivo": arrivo})

    if not candidati:
        return None
    return max(candidati, key=lambda c: c["partenza"])


# ============================================================================
# ALGORITMO DI CALCOLO A RITROSO (core logic)
# ============================================================================

def calcola_itinerario_a_ritroso(orario_arrivo_desiderato, ritardo_simulato_eav_min=RITARDO_STANDARD_EAV_MIN):
    target = parse_time_str(orario_arrivo_desiderato)

    # --- Step 3: Bus ANM ---
    bus = trova_bus_utile(target)
    if bus is None:
        return {
            "fattibile": False,
            "messaggio": (
                f"Nessun bus ANM disponibile che arrivi entro le {orario_arrivo_desiderato}. "
                "Prova con un orario di arrivo più tardo, oppure aggiorna ANM_LINEE con più corse."
            ),
        }

    step_3_data = {
        "mezzo": f"Bus ANM {bus['linea']}",
        "tratta": "Piazzale Tecchio -> Monte Sant'Angelo",
        "partenza": format_time(bus["partenza"]),
        "arrivo": format_time(bus["arrivo"]),
        "ritardo": "N/D (orario stimato, non realtime)",
        "status": "Orario programmato/stimato",
    }

    # --- Step 2: Metro Linea 2 (dati live) ---
    deadline_step2 = subtract_minutes(bus["partenza"], BUFFER_CAMPIFLEGREI_TECCHIO_MIN)

    try:
        treni = get_treni_in_partenza_da_garibaldi()
    except Exception as e:
        return {
            "fattibile": False,
            "messaggio": "Impossibile recuperare i dati live di Trenitalia (ViaggiaTreno) in questo momento.",
            "dettaglio_errore": str(e),
            "step_3": step_3_data,
        }

    treno = trova_treno_linea2(deadline_step2, treni)
    if treno is None:
        return {
            "fattibile": False,
            "messaggio": (
                f"Nessun treno Linea 2 in partenza ora da Garibaldi arriva a Campi Flegrei "
                f"entro le {format_time(deadline_step2)} (deadline per il bus delle "
                f"{format_time(bus['partenza'])}). Nota: l'API ViaggiaTreno mostra solo le "
                "partenze imminenti, quindi funziona meglio se richiesta vicino all'orario del viaggio."
            ),
            "step_3": step_3_data,
        }

    ritardo = treno["ritardo"]
    step_2_data = {
        "mezzo": f"Metro Linea 2 (Treno {treno['numero_treno']})",
        "tratta": f"Garibaldi -> {treno['destinazione']}",
        "partenza": format_time(treno["partenza"]),
        "arrivo": format_time(treno["arrivo_stimato"]),
        "ritardo": f"{ritardo} min",
        "status": f"In ritardo di {ritardo} min" if ritardo > 0 else "In orario",
    }

    # --- Step 1: Circumvesuviana EAV ---
    deadline_step1 = subtract_minutes(treno["partenza"], BUFFER_GARIBALDI_INTERSCAMBIO_MIN)
    eav = trova_circumvesuviana(deadline_step1, ritardo_simulato_eav_min)
    if eav is None:
        return {
            "fattibile": False,
            "messaggio": (
                f"Nessuna corsa Circumvesuviana da Pollena arriva a Garibaldi entro le "
                f"{format_time(deadline_step1)} (deadline per la coincidenza con il treno delle "
                f"{format_time(treno['partenza'])}). Prova con un orario di arrivo più tardo."
            ),
            "step_2": step_2_data,
            "step_3": step_3_data,
        }

    step_1_data = {
        "mezzo": "Circumvesuviana (EAV)",
        "tratta": "Pollena Trocchia -> Napoli Garibaldi",
        "partenza": format_time(eav["partenza"]),
        "arrivo": format_time(eav["arrivo"]),
        "ritardo": f"{ritardo_simulato_eav_min} min (simulato)",
        "status": "Orario statico + ritardo simulato",
    }

    return {
        "fattibile": True,
        "orario_arrivo_desiderato": orario_arrivo_desiderato,
        "devi_uscire_di_casa_entro": format_time(eav["partenza"]),
        "step_1": step_1_data,
        "step_2": step_2_data,
        "step_3": step_3_data,
    }


# ============================================================================
# ROUTES
# ============================================================================

@app.route("/api/itinerario/<orario_arrivo>")
def api_itinerario(orario_arrivo):
    try:
        parse_time_str(orario_arrivo)
    except ValueError:
        return jsonify({"errore": "Formato orario non valido, usa HH:MM"}), 400

    try:
        risultato = calcola_itinerario_a_ritroso(orario_arrivo)
        return jsonify(risultato)
    except Exception as e:
        app.logger.exception("Errore nel calcolo dell'itinerario")
        return jsonify({"errore": "Errore interno nel calcolo dell'itinerario", "dettaglio": str(e)}), 500


@app.route("/api/health")
def health():
    """Endpoint semplice per gli health check di Render."""
    return jsonify({"status": "ok"})


# ============================================================================
# ENTRYPOINT
# ============================================================================

if __name__ == "__main__":
    # In locale: python app.py -> http://localhost:5000
    # Su Render: la porta viene passata via variabile d'ambiente PORT, e il
    # server va avviato con gunicorn (vedi Procfile), non con app.run().
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)