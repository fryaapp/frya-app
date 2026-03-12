from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI()

# --- Health / Ping (unverändert) ---


@app.get("/health")
async def health():
    return JSONResponse(status_code=200, content={"status": "ok"})


@app.get("/v1/ping")
async def ping():
    return JSONResponse(status_code=200, content={"message": "pong"})


# --- Auth Login MVP ---


class LoginRequest(BaseModel):
    email: str
    password: str


MVP_EMAIL = "test@myfrya.de"
MVP_PASSWORD = "test1234"


@app.post("/auth/login")
async def auth_login(body: LoginRequest):
    if body.email == MVP_EMAIL and body.password == MVP_PASSWORD:
        return JSONResponse(
            status_code=200,
            content={
                "accessToken": "mvp_access_token",
                "refreshToken": "mvp_refresh_token",
                "tokenType": "Bearer",
                "expiresIn": 900,
                "refreshExpiresIn": 604800,
            },
        )
    return JSONResponse(
        status_code=401,
        content={
            "error": "invalid_credentials",
            "message": "Email or password is incorrect",
        },
    )
