from flask import Flask, jsonify
from flask_cors import CORS
import requests
import datetime

app = Flask(__name__)
# Questo permette alla tua pagina su GitHub Pages di leggere i dati senza essere bloccata
CORS(app)

@app.route('/api/itinerario/<orario_arrivo>')
def calcola_itinerario(orario_arrivo):
    # Generiamo il timestamp nel formato esatto richiesto da ViaggiaTreno (ora legale GMT+0200)
    now_vt = datetime.datetime.now().strftime("%a %b %d %Y %H:%M:%S GMT+0200")
    codice_stazione = "S09218" # Napoli Piazza Garibaldi
    url_trenitalia = f"http://www.viaggiatreno.it/infomobilita/rete/viaggiatreno/partenze/{codice_stazione}/{now_vt}"
    
    try:
        # Richiesta VERA all'API di Trenitalia (niente più dati simulati!)
        response = requests.get(url_trenitalia)
        treni_in_partenza = response.json()
        
        # Filtriamo i treni: cerchiamo il primo in direzione Pozzuoli o Campi Flegrei
        treno_linea_2 = None
        for treno in treni_in_partenza:
            destinazione = treno.get("destinazione", "").upper()
            if "POZZUOLI" in destinazione or "CAMPI FLEGREI" in destinazione:
                treno_linea_2 = treno
                break
                
        # Prepariamo i dati dello step 2
        if treno_linea_2:
            ritardo = treno_linea_2.get("ritardo", 0)
            status_treno = f"In ritardo di {ritardo} min" if ritardo > 0 else "In orario"
            
            step_2_data = {
                "mezzo": f"Metro Linea 2 (Treno {treno_linea_2.get('numeroTreno')})",
                "tratta": "Garibaldi -> Campi Flegrei",
                "partenza": treno_linea_2.get("compOrarioPartenza", "N/D"),
                "arrivo": "Circa 20 min dopo", 
                "ritardo": f"{ritardo} min",
                "status": status_treno
            }
        else:
            step_2_data = {
                "mezzo": "Metro Linea 2",
                "tratta": "Garibaldi -> Campi Flegrei",
                "partenza": "N/D",
                "arrivo": "N/D",
                "ritardo": "N/D",
                "status": "Nessun treno trovato a breve"
            }

        # Ricostruiamo il JSON finale da mandare al frontend
        dati_finali = {
            "step_1": {
                "mezzo": "Circumvesuviana",
                "tratta": "Pollena Trocchia -> Napoli Garibaldi",
                "partenza": "Da definire", 
                "arrivo": "Da definire",
                "ritardo": "0 min",
                "status": "In attesa"
            },
            "step_2": step_2_data,
            "step_3": {
                "mezzo": "Bus ANM 180",
                "tratta": "Piazzale Tecchio -> Monte Sant'Angelo",
                "partenza": "Da definire",
                "arrivo": "Da definire",
                "ritardo": "Sconosciuto",
                "status": "In attesa"
            }
        }
        
        return jsonify(dati_finali)

    except Exception as e:
        return jsonify({"errore": f"Impossibile recuperare i dati: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)