# RankResume Frontend

## Run locally

From the repository root, serve the project with:

```bash
python -m http.server 8080
```

Open `http://localhost:8080/Frontend/html/login.html`. The frontend uses Bootstrap 5.3, Bootstrap Icons, Inter, and Chart.js from CDNs.

## Mock data and backend

`JS/config.js` contains `RankResumeConfig.USE_MOCK_DATA`, which is `true` by default. Set it to `false` and update `API_BASE_URL` when the FastAPI service is available. All backend calls are centralized in `JS/api.js`; the mock implementation keeps every page usable without a server.

## Pages

Login, Sign Up, Dashboard, Create Job, Jobs, Job Details, Candidates, Candidate Detail, Final Results, and Reports.

Create Job accepts one PDF/DOC/DOCX job description and one ZIP resume archive without reading the archive into JavaScript memory. The mock flow simulates processing stages before navigating to the candidates page.
