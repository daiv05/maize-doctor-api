# Taxonomy Validation and Base-URL Docs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close two gaps found in a cross-repo audit against `maize-doctor-classifier` (the ML pipeline) and `maize-doctor-app`: (1) `corrections.observed_label` and `dataset_contributions.label` currently accept any free-text string up to 64 chars, with nothing tying them to the ML pipeline's 9-class taxonomy, so a future class rename (this has already happened once — `northern_leaf_blight` → `northern_corn_leaf_blight`) can silently poison the DB with stale label strings; (2) nothing documents what base URL the mobile app should actually point at, beyond the local `docker-compose.yml` port.

**Architecture:** Add a single `app/constants.py` module mirroring the ML pipeline's canonical 9-class list (there is no shared package across these repos/languages, so this is a deliberately duplicated, clearly-commented source of truth — see Global Constraints), and validate both label fields against it. Then add a short, concrete "how the app finds this API" section to the README.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, pytest + httpx, MySQL via Docker Compose (existing test setup).

**Spec:** `docs/superpowers/specs/2026-08-16-maize-doctor-api-design.md`. Companion plans (independent, not a dependency): `maize-doctor-classifier/docs/superpowers/plans/2026-08-16-mobile-handoff-hardening.md`, `maize-doctor-app/docs/superpowers/plans/2026-08-16-fix-sync-client-and-remote-auth.md`.

## Global Constraints

- The canonical 9-class list and order lives in `maize-doctor-classifier/config/dataset.yaml -> dataset.classes`. This repo has no mechanism to import that file (different language, different repo, no shared package registry) — `app/constants.py` is a manually-synced mirror. **Order does not matter here** (this repo only ever checks set membership, never indexes by position), but the exact strings must match byte-for-byte.
- Tests in this repo run against a real MySQL instance via Docker Compose, never mocked/sqlite — see README's "Running tests" section. Every test step in this plan assumes `docker compose up -d mysql` has already been run once and stays running.
- Existing idempotency/validation tests in `tests/test_corrections.py` and `tests/test_contributions.py` follow a fixed pattern: register a user inline via `_register_and_get_token`, then assert on status code. New tests must follow the same pattern, not introduce a new one.

---

### Task 1: Validate `observed_label` / `label` against the ML taxonomy

**Files:**
- Create: `app/constants.py`
- Modify: `app/schemas/correction.py`
- Modify: `app/routers/contributions.py`
- Test: `tests/test_corrections.py`
- Test: `tests/test_contributions.py`

**Interfaces:**
- Produces: `app.constants.DIAGNOSIS_LABELS: tuple[str, ...]` — the frozen set of 9 valid class strings.
- Consumes: nothing new from other tasks.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_corrections.py`, right after `test_unknown_status_returns_422`:

```python
@pytest.mark.asyncio
async def test_unknown_observed_label_returns_422(client):
    token = await _register_and_get_token(client, "farmer7@example.com")

    response = await client.post(
        "/corrections",
        json={
            "clientId": "local-7",
            "scanId": "scan-7",
            "observedLabel": "roya_comun",
            "note": None,
            "status": "pending",
            "createdAt": datetime.now(timezone.utc).isoformat(),
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422
```

Add to `tests/test_contributions.py`, right after `test_corrupt_image_returns_422`:

```python
@pytest.mark.asyncio
async def test_unknown_label_returns_422(client, tmp_path, monkeypatch):
    monkeypatch.setattr("app.storage.settings.upload_dir", str(tmp_path))
    token = await _register_and_get_token(client, "grower5@example.com")

    response = await client.post(
        "/dataset-contributions",
        data={
            "clientId": "local-5",
            "label": "roya_comun",
            "createdAt": datetime.now(timezone.utc).isoformat(),
        },
        files={"image": ("leaf.png", _png_bytes(), "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
docker compose up -d mysql
$env:DATABASE_URL="mysql+aiomysql://root:root@localhost:3306/maize_doctor_test"
pytest tests/test_corrections.py::test_unknown_observed_label_returns_422 tests/test_contributions.py::test_unknown_label_returns_422 -v
```
Expected: both FAIL with `assert 201 == 422` (the bogus label is currently accepted).

- [ ] **Step 3: Create the constants module**

Create `app/constants.py`:

```python
"""
Espejo manual de `maize-doctor-classifier/config/dataset.yaml -> dataset.classes`.

No hay forma de importar ese archivo desde este repo (proyecto Python distinto, sin
paquete compartido), asi que esta lista se mantiene sincronizada a mano. El orden aqui
no importa - a diferencia del pipeline de ML, esta API nunca indexa por posicion, solo
valida pertenencia al conjunto - pero los strings deben coincidir exactamente.
"""

DIAGNOSIS_LABELS: tuple[str, ...] = (
    "common_rust",
    "fall_armyworm",
    "gray_leaf_spot",
    "healthy",
    "lethal_necrosis",
    "nitrogen_deficiency",
    "northern_corn_leaf_blight",
    "phosphorus_deficiency",
    "potassium_deficiency",
)
```

- [ ] **Step 4: Validate `observed_label` in `CorrectionIn`**

In `app/schemas/correction.py`, change the imports at the top from:

```python
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.base import CamelModel
```

to:

```python
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from app.constants import DIAGNOSIS_LABELS
from app.schemas.base import CamelModel
```

Then, inside `CorrectionIn`, immediately after the `observed_label: str = Field(max_length=64)` line, add:

```python

    @field_validator("observed_label")
    @classmethod
    def _validate_observed_label(cls, value: str) -> str:
        if value not in DIAGNOSIS_LABELS:
            raise ValueError(f"observed_label debe ser uno de: {DIAGNOSIS_LABELS}")
        return value
```

- [ ] **Step 5: Validate `label` in the contributions router**

In `app/routers/contributions.py`, add the import:

```python
from app.constants import DIAGNOSIS_LABELS
```

Then, inside `create_contribution`, immediately after the function signature's closing `) -> ContributionOut:` line (before the existing `user_id = user.id` line), add:

```python
    if label not in DIAGNOSIS_LABELS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"label debe ser uno de: {DIAGNOSIS_LABELS}",
        )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_corrections.py tests/test_contributions.py -v`
Expected: all PASS, including the 2 new tests and every pre-existing test (no regressions — `common_rust`/`gray_leaf_spot`/`healthy` used throughout the existing suite are all valid members of `DIAGNOSIS_LABELS`).

- [ ] **Step 7: Run the full test suite**

Run: `pytest -v`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add app/constants.py app/schemas/correction.py app/routers/contributions.py tests/test_corrections.py tests/test_contributions.py
git commit -m "feat(validation): restrict observed_label/label to the ML pipeline's 9-class taxonomy"
```

---

### Task 2: Document how the mobile app should point at this API

**Files:**
- Modify: `README.md`

**Interfaces:**
- None (documentation-only).

- [ ] **Step 1: Add a base-URL section to the README**

In `README.md`, insert a new section right after `## Local development` (before `## Running tests`):

```markdown
## Pointing `maize-doctor-app` at this API

The app reads the base URL from `EXPO_PUBLIC_API_URL` (see that repo's `.env`). This API has no CORS layer by design (`docs/superpowers/specs/2026-08-16-maize-doctor-api-design.md`) because the app calls it directly via `fetch`, not from a browser — so any reachable host:port works, there's nothing to allow-list.

- **Android emulator** talking to a server on the same host machine: `http://10.0.2.2:8000` (`localhost` from inside the emulator refers to the emulator itself, not the host).
- **Physical device** on the same network as the dev machine: `http://<dev-machine-LAN-IP>:8000` — find the IP with `ipconfig` (Windows) and make sure `docker compose up` is exposing port 8000 on all interfaces (it already does, per `docker-compose.yml`'s `ports: ["8000:8000"]`).
- **iOS simulator**: `http://localhost:8000` works as-is (the simulator shares the host's network namespace).
- **Staging/production**: no such deployment exists yet as of this API's v1 scope — when one does, document its URL here instead of leaving `EXPO_PUBLIC_API_URL` to be guessed per-developer.
```

- [ ] **Step 2: Verify the README renders sensibly**

Run: `git diff README.md`
Expected: a clean, well-formed markdown insertion with no broken headers (visually confirm the new `##` section doesn't collide with the existing `## Running tests` header immediately after it).

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document how maize-doctor-app should reach this API locally"
```
