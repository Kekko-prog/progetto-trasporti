from flask import Flask, jsonify
from flask_cors import CORS
import requests
import datetime

app = Flask(__name__)
CORS(app)

@app.route('/api/itinerario/<orario_arrivo>')
def calcola_itinerario(orario_arrivo):
    # Generiamo ESATTAMENTE la stringa che hai trovato nel browser
    # Usiamo l'apostrofo tipografico ’ (quello curvo) per matchare il loro %E2%80%99
    timestamp = datetime.datetime.now().strftime("%a %b %d %Y %H:%M:%S GMT+0200 (Ora legale dell’Europa centrale)")
    
    # Il codice stazione corretto svelato dall'API
    codice_stazione = "S09109" 
    
    # Il percorso esatto con "resteasy"
    url_trenitalia = f"http://www.viaggiatreno.it/infomobilita/resteasy/viaggiatreno/partenze/{codice_stazione}/{timestamp}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        # Passiamo l'URL a requests. Farà lui la conversione degli spazi in %20 in automatico.
        response = requests.get(url_trenitalia, headers=headers)
        response.raise_for_status() 
        
        treni_in_partenza = response.json()
        
        treno_linea_2 = None
        for treno in treni_in_partenza:
            destinazione = treno.get("destinazione", "").upper()
            if "POZZUOLI" in destinazione or "CAMPI FLEGREI" in destinazione:
                treno_linea_2 = treno
                break
                
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
                "status": "Nessun treno verso Campi Flegrei nei prossimi minuti"
            }

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
        print(f"\n--- ERRORE ---")
        print(f"URL generato: {url_trenitalia}")
        print(f"Dettaglio: {e}")
        print("------------\n")
        return jsonify({"errore": f"Impossibile recuperare i dati"}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)