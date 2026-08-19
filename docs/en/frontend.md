# Frontend

中文版: [Frontend 前端](../frontend.md)

V2 includes a minimal usable Vue frontend for submitting natural-language requests to the backend and displaying job status, the final answer, the preview image, and download entries.

The frontend contains no raster business logic. It is responsible only for:

- entering a natural-language request;
- calling `POST /jobs` to create a task;
- polling `GET /jobs/{job_id}`;
- displaying queued / running / succeeded / failed status;
- displaying backend `message`, `final_answer`, and `error`;
- displaying `preview.png`;
- downloading `metadata.json`, `preview.png`, and `result.tif`;
- checking the configured backend address through `API Health`.

## Tech Stack

The frontend is located in `frontend/`:

```text
frontend/
  src/
    App.vue
    api.ts
    styles.css
    types.ts
  package.json
  vite.config.ts
```

Tech stack:

- Vue 3;
- Vite;
- TypeScript.

## Local Run

Start the backend first:

```bash
docker compose up --build
```

Then start the frontend:

```bash
cd frontend
npm run dev
```

Visit:

```text
http://127.0.0.1:5173
```

During local development, the frontend requests `/api`, which is forwarded by the Vite proxy to:

```text
http://127.0.0.1:8000
```

Related configuration:

```env
VITE_API_PROXY_TARGET=http://127.0.0.1:8000
VITE_API_BASE_URL=/api
```

## Online Frontend

The current V2 frontend is deployed on Vercel. Online builds require:

```env
VITE_API_BASE_URL=https://<backend-public-url>
```

This address is the public backend entry. The current project uses:

```text
local Docker backend -> intranet tunnel public URL -> Vercel frontend
```

Note: `VITE_API_BASE_URL` is a build-time variable. After modifying Vercel environment variables, the frontend must be redeployed.

```bash
cd frontend
vercel --prod
```

## API Health

The `API Health` button in the upper-right corner uses the same backend address as task requests:

```text
<VITE_API_BASE_URL>/health
```

If this button does not return:

```json
{"status":"ok"}
```

then the frontend cannot currently access the backend. Common causes include:

- Vercel has not been redeployed and is still using an old `VITE_API_BASE_URL`.
- The intranet tunnel URL has changed or disconnected.
- The backend Docker services are not running.
- Backend CORS does not allow the current Vercel domain.

## Runtime Boundaries

The current frontend is the V2 presentation layer and does not include:

- user login;
- multi-session management;
- historical task list;
- task cancellation button;
- percentage progress bar;
- interactive map browser;
- production-grade error analysis panel.

These capabilities can be expanded in later service-oriented stages.
