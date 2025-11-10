import os, random
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import urllib.parse

# ==== ENV ====
AIRTABLE_TOKEN = os.getenv("AIRTABLE_TOKEN")  # pat_...
AIRTABLE_BASE_ID = os.getenv("AIRTABLE_BASE_ID")  # appXXXXXXXXXXXX
AIRTABLE_TALLY_TABLE = os.getenv("AIRTABLE_TALLY_TABLE", "Tally")
AIRTABLE_DISHES_TABLE = os.getenv("AIRTABLE_DISHES_TABLE", "Dishes")
ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN", "https://www.lesglobetraiteurs.com")

# ==== CONST ====
TALLY_SUBMISSION_FIELD = "Submission ID"
TALLY_CUISINES_FIELD = "Par quel(s) type(s) de cuisine seriez-vous intéressé?"
DISHES_CUISINE_FIELD = "Cuisine"

API_BASE = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}"
HEADERS = {"Authorization": f"Bearer {AIRTABLE_TOKEN}"}

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": ALLOWED_ORIGIN}})

def _airtable_get(table: str, params: dict):
    r = requests.get(f"{API_BASE}/{urllib.parse.quote(table)}", headers=HEADERS, params=params or {})
    r.raise_for_status()
    return r.json()

def _escape_airtable_string(s: str) -> str:
    # Airtable formula: escape single quotes by doubling them
    return s.replace("'", "''").strip()

def _build_or_equals(field: str, values: list[str]) -> str:
    # OR({Cuisine}='Française', {Cuisine}='Sud-américaine')
    parts = [f"{{{field}}}='{_escape_airtable_string(v)}'" for v in values if v]
    if not parts:
        return "FALSE()"
    return f"OR({', '.join(parts)})"

@app.get("/api/health")
def health():
    return {"status": "ok"}

@app.get("/api/get_plats")
def get_plats():
    sub_id = (request.args.get("submission_id") or "").strip()
    if not sub_id:
        return jsonify({"error": "missing submission_id"}), 400

    # 1) Lire la soumission Tally → récupérer la(les) cuisine(s)
    # filterByFormula: {Submission ID}='XYZ'
    tally_params = {"filterByFormula": f"{{{TALLY_SUBMISSION_FIELD}}}='{_escape_airtable_string(sub_id)}'",
                    "maxRecords": 1}
    try:
        tally = _airtable_get(AIRTABLE_TALLY_TABLE, tally_params)
    except requests.HTTPError as e:
        return jsonify({"error": f"Airtable error (Tally): {e}"}), 502

    records = tally.get("records", [])
    if not records:
        return jsonify({"error": "submission_id not found"}), 404

    fields = records[0].get("fields", {})

    # 🔧 Le champ multiselect côté Tally (par ex. "Par quel(s) type(s) de cuisine seriez-vous intéressé?")
    raw_cuisines = fields.get(TALLY_CUISINES_FIELD)

    def _to_cuisine_list(value):
        # Cas 1 : le champ est un multi-select Airtable → liste de chaînes
        if isinstance(value, list):
            return [x.strip() for x in value if isinstance(x, str) and x.strip()]
        # Cas 2 : le champ est un texte CSV (ex: "Française,Sud-américaine")
        if isinstance(value, str):
            return [x.strip() for x in value.split(",") if x and x.strip()]
        return []

    # Normaliser + dédoublonner en gardant l’ordre
    seen = set()
    cuisines = [c for c in _to_cuisine_list(raw_cuisines) if not (c in seen or seen.add(c))]

    # Si aucune cuisine détectée → message d’erreur clair
    if not cuisines:
        return jsonify({
            "error": "no cuisine provided on submission",
            "field_used": TALLY_CUISINES_FIELD,
            "raw": raw_cuisines
        }), 422


    # 3) Chercher les plats correspondant à AU MOINS une des cuisines choisies
    formula = _build_or_equals(DISHES_CUISINE_FIELD, cuisines)
    dishes_params = {
        "filterByFormula": formula,
        "pageSize": 50  # ajustable
    }
    try:
        dishes = _airtable_get(AIRTABLE_DISHES_TABLE, dishes_params)
    except requests.HTTPError as e:
        return jsonify({"error": f"Airtable error (Dishes): {e}"}), 502

    dish_records = dishes.get("records", [])
    if not dish_records:
        return jsonify({"error": f"No dishes found for cuisines: {', '.join(cuisines)}"}), 404

    # 4) Tirer au hasard 3 plats
    random.shuffle(dish_records)
    picks = dish_records[:3]

    # 5) Payload : on expose des champs existants (pas d'image dans tes CSV)
    out = []
    for r in picks:
        f = r.get("fields", {})
        out.append({
            "Nom du plat": f.get("Nom du plat"),
            "Cuisine": f.get("Cuisine"),
            "Type": f.get("Type"),
            "Régimes (tags)": f.get("Régimes (tags)"),
            "Allergènes": f.get("Allergènes"),
            "Prix HT par portion (€)": f.get("Prix HT par portion (€)"),
            "Nombre de bouchées": f.get("Nombre de bouchées"),
            "Prestations": f.get("Prestations"),
            "Sucré/Salé": f.get("Sucré/Salé")
        })

    return jsonify({
        "submission_id": sub_id,
        "cuisines": cuisines,
        "count": len(out),
        "dishes": out
    })