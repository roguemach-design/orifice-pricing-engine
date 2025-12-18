from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from pricing_engine import QuoteInputs, calculate_quote

app = FastAPI(title="Orifice Pricing API", version="1.0.0")

# TODO later: restrict to your Shopify domain(s)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # replace with ["https://YOURSTORE.myshopify.com", "https://yourdomain.com"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Optional API key protection (recommended)
API_KEY = ""  # set to a real value in your deployment env var later (preferred)


class QuoteRequest(BaseModel):
    quantity: int
    material: str
    thickness: float
    handle_width: float
    handle_length_from_bore: float
    paddle_dia: float
    bore_dia: float
    bore_tolerance: float
    chamfer: bool
    ships_in_days: int


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/quote")
def quote(req: QuoteRequest, x_api_key: str | None = Header(default=None)):
    # If you want API-key protection:
    if API_KEY:
        if not x_api_key or x_api_key != API_KEY:
            raise HTTPException(status_code=401, detail="Unauthorized")

    inputs = QuoteInputs(**req.model_dump())
    return calculate_quote(inputs)
