import os, random
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pyairtable import Table

# --------- Config via variables d'environnement ----------
AIRTABLE_TOKEN = os.environ.get("AIRTABLE_TOKEN")            # PAT Airtable
AIRTABLE_BASE_ID = os.environ.get("AIRTABLE_BASE_ID")        # ex: appXXXXXXXXXXXXXX
AIRTABLE_DISHES_TABLE = os.environ.get("AIRTABLE_DISHES_TABLE", "Dishes")
BEARER_TOKEN = os.environ.get("BEARER_TOKEN")                # secret Make → API

if not all([AIRTABLE_TOKEN, AIRTABLE_BASE_ID, BEARER_TOKEN]):
    raise RuntimeError("Env vars missing: AIRTABLE_TOKEN / AIRTABLE_BASE_ID / BEARER_TOKEN")

dishes_tbl = Table(AIRTABLE_TOKEN, AIRTABLE_BASE_ID, AIRTABLE_DISHES_TABLE)

# --------- FastAPI ----------
app = FastAPI(title="Les Globe Traiteurs - Recommendations API")

class CreatePayload(BaseModel):
    submission_id: str
    culture: str
    source: str | None = None
    submitted_at: str | None = None

def check_auth(req: Request):
    auth = req.headers.get("authorization") or req.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer")
    token = auth.split(" ", 1)[1].strip()
    if token != BEARER_TOKEN:
        raise HTTPException(status_code=401, detail="Bad bearer")

def escape_quotes(s: str) -> str:
    # Airtable formulas need single quotes escaped as \'
    return s.replace("'", "\\'")

@app.post("/recommendations/create")
async def create_recommendations(payload: CreatePayload, request: Request):
    check_auth(request)

    submission_id = payload.submission_id.strip()
    culture = payload.culture.strip()
    if not submission_id or not culture:
        raise HTTPException(status_code=400, detail="missing_params")

    # Filtre Airtable : insensible à la casse
    # Exemple: LOWER({culture}) = LOWER('Inde')
    culture_esc = escape_quotes(culture)
    formula = f"LOWER({{culture}}) = LOWER('{culture_esc}')"

    # Récupérer tous les plats de la culture
    records = dishes_tbl.all(formula=formula)
    if len(records) < 3:
        raise HTTPException(status_code=400, detail="not_enough_dishes")

    sample = random.sample(records, 3)

    # Normaliser la sortie
    dishes = []
    for r in sample:
        f = r.get("fields", {})
        dishes.append({
            "id": r["id"],  # ID d'enregistrement Airtable
            "name": f.get("name"),
            "culture": f.get("culture"),
            "image_url": f.get("image_url"),
            "description": f.get("description"),
        })

    return JSONResponse({
        "ok": True,
        "submission_id": submission_id,
        "culture": culture,
        "count": 3,
        "dishes": dishes,
        "dish_ids": [d["id"] for d in dishes]
    })
