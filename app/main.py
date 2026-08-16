from fastapi import FastAPI

app = FastAPI(title="maize-doctor-api")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
