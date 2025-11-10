import os, random
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests

AIRTABLE_TOKEN = os.getenv("AIRTABLE_TOKEN")
BASE_ID = os.getenv("AIRTABLE_BASE_ID")
TALLY_TABLE = os.getenv("AIRTABLE_TALLY_TABLE", "Tally")
PLATS_TABLE = os.getenv("AIRTABLE_PLATS_TABLE", "Plats")
ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN", "*")  # ex: https://www.lesglobetraiteurs.com

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": ALLOWED_ORIGIN}})

API_BASE = f"https://api.airtable.com/v0/{BASE_ID}"
HEADERS = {"Authorization": f"Bearer {AIRTABLE_TOKEN}"}

def airtable_get(table, params=None):
    r = requests.get(f"{API_BASE}/{table}", headers=HEADERS, params=params or {})
    r.raise_for_status()
    return r.json()

@app.get("/api/health")
def health():
    return {"status": "ok"}

@app.get("/api/get_plats")
def get_plats():
    sub_id = request.args.get("submission_id", "").strip()
    if not sub_id:
        return jsonify({"error": "missing submission_id"}), 400

    # 1) lire la culture depuis la table Tally
    params = {"filterByFormula": f"{{submission_id}}='{sub_id}'", "maxRecords": 1}
    try:
        tally = airtable_get(TALLY_TABLE, params)
    except requests.HTTPError as e:
        return jsonify({"error": f"Airtable error (Tally): {e}"}), 502

    if not tally.get("records"):
        return jsonify({"error": "submission_id not found"}), 404

    fields = tally["records"][0].get("fields", {})
    culture = fields.get("culture")
    if not culture:
        return jsonify({"error": "culture missing on submission"}), 422

    # Si culture est single select, on a une string.
    # Si culture est linked record, Airtable renvoie une liste d'IDs. Dans ce cas,
    # tu peux stocker aussi le nom dans un champ calculé, OU faire une 2e requête.
    # Ici on gère deux cas simples :
    culture_name = None
    if isinstance(culture, str):
        culture_name = culture
        plats_filter = f"{{culture}}='{culture_name}'"
    elif isinstance(culture, list):
        # Linked record → on va filtrer par FIND sur le nom stocké en clair.
        # Suppose qu’un champ rollup/lookup “culture_name” existe sur Tally avec le nom.
        culture_name = fields.get("culture_name")
        if not culture_name:
            return jsonify({"error": "culture_name missing for linked record model"}), 422
        plats_filter = f"FIND('{culture_name}', ARRAYJOIN({{culture}}))"

    # 2) récupérer les plats pour cette culture
    try:
        plats_resp = airtable_get(PLATS_TABLE, {"filterByFormula": plats_filter, "pageSize": 50})
    except requests.HTTPError as e:
        return jsonify({"error": f"Airtable error (Plats): {e}"}), 502

    plats_records = plats_resp.get("records", [])
    if not plats_records:
        return jsonify({"error": f"No dishes found for culture '{culture_name}'"}), 404

    # 3) choisir 3 plats au hasard (ou moins si <3)
    random.shuffle(plats_records)
    choisis = plats_records[:3]

    # 4) payload minimal pour le front
    out = []
    for r in choisis:
        f = r.get("fields", {})
        out.append({
            "nom": f.get("nom"),
            "description": f.get("description"),
            "image_url": f.get("image_url"),
            "culture": culture_name
        })
    return jsonify(out)
