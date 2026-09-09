from flask import Flask, jsonify
from flask_cors import CORS
import requests
import datetime

app = Flask(__name__)
# Questo permette alla tua pagina su GitHub Pages di leggere i dati senza essere bloccata
CORS(app)

@app.route('/api/itinerario/<orario_arrivo>')
def calcola_itinerario(orario_arrivo):
    # --- ESEMPIO: Recupero ritardi Linea 2 (ViaggiaTreno) ---
    # S09218 è il codice stazione di Napoli Piazza Garibaldi
    codice_stazione = "S09218"
    
    # Costruiamo il timestamp per l'API di ViaggiaTreno (formato: Fri%20Mar%2001%202024%2010:00:00%20GMT+0100)
    now = datetime.datetime.now().strftime("%a %b %d %Y %H:%M:%S GMT+0100")
    url_trenitalia = f"http://www.viaggiatreno.it/infomobilita/rete/viaggiatreno/partenze/{codice_stazione}/{now}"
    
    try:
        # Facciamo finta che la richiesta vada a buon fine e prendiamo il primo treno utile per Campi Flegrei
        # response = requests.get(url_trenitalia)
        # dati = response.json()
        
        # DATI SIMULATI PER IL PROTOTIPO:
        dati_simulati = {
            "step_1": {
                "mezzo": "Circumvesuviana",
                "tratta": "Pollena Trocchia -> Napoli Garibaldi",
                "partenza": "08:15",
                "arrivo": "08:35",
                "ritardo": "0 min",
                "status": "In orario"
            },
            "step_2": {
                "mezzo": "Metro Linea 2",
                "tratta": "Garibaldi -> Campi Flegrei",
                "partenza": "08:45",
                "arrivo": "09:05",
                "ritardo": "+5 min",
                "status": "Attenzione: Coincidenza stretta"
            },
            "step_3": {
                "mezzo": "Bus ANM 180",
                "tratta": "Piazzale Tecchio -> Monte Sant'Angelo",
                "partenza": "09:15",
                "arrivo": "09:30",
                "ritardo": "Sconosciuto",
                "status": "Orario programmato"
            }
        }
        return jsonify(dati_simulati)

    except Exception as e:
        return jsonify({"errore": "Impossibile recuperare i dati"}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)