# PROJECT_STATE

## 2026-09-29 — box-side PUBLIC_HOST for HF Spaces judge demo

- Work done on **Grok Bot box** under `/workspace/IncidentPilot` only (not the Windows machine).
- Added optional public hosting: `INCIDENTPILOT_PUBLIC_HOST=1` + `INCIDENTPILOT_PUBLIC_HOSTNAME`
  (or `--public-host` / `--public-hostname`). Default remains loopback-only.
- Deploy pack: `deploy/hf-space/` (Dockerfile, Linux requirements without pywin32, README).
- Credits / Devpost form submission is being handled from the **box browser separately**;
  this note does not include or trigger any Devpost submit.
- Do not commit API keys; do not rerun paid Nebius acceptance from this change set.


## Promo form (box) — 2026-09-29
- Submitted on box browser; confirmation shown; code emailed to wyxaivv1018@gmail.com (pending redeem)

## Judge hosting (2026-09-29)
- Platform: Render free web service (HF Docker Spaces requires PRO; blocked).
- URL: https://incidentpilot-judge.onrender.com/
- Secret: NEBIUS_API_KEY set in Render env (not in git).
- Promo credits through 2026-12-15: still waiting for emailed promo code redemption.

## Devpost submit attempt (box) — 2026-09-30 Asia/Shanghai ~10:20

- **Result at that time: BLOCKED — NOT SUBMITTED** (no confirmation receipt).
- Hackathon: https://nebiusglobalaihackathon.devpost.com/ (challenge_id 30790)
- Existing draft submission id **1174683** (email 2026-09-08 "Submission … started" for Untitled); edit URL requires auth:
  https://devpost.com/submit-to/30790-nebius-x-nvidia-global-ai-hackathon/manage/submissions/1174683/edit
- Box browser not logged into Devpost. Google SSO fails (`accounts.google.com` ERR_CONNECTION_CLOSED in Chrome). GitHub SSO needs credentials. Password reset blocked by reCAPTCHA.
- Handoff: user must Log in at https://secure.devpost.com/users/login then open edit URL above.
- Prepared paste payload: `runtime/nebius/devpost-submit/READY_FIELDS.md` (title, tagline, track Best Apps and Agents, GitHub, YouTube https://youtu.be/SFowqxkH0Gg, Live https://incidentpilot-judge.onrender.com/, description+feedback).
- Judge live URL / YouTube / $25 promo live-through-judge-window: per parent CONTEXT (promo redeemed 2026-09-30).
- At that time, do not claim submitted until confirmation page / finalized email exists.

## Devpost submission confirmation — 2026-09-30 Asia/Shanghai ~14:21

- **Status: SUBMITTED** (user-confirmed).
- Hackathon: **Nebius x NVIDIA Global AI Hackathon**
- Submission id: **1174683**
- Owner: **v pyw / @wyxaivv1018-collab**
- Evidence: the project page shows **SUBMITTED TO Nebius x NVIDIA Global AI Hackathon** with **Edit hackathon submission**; the YouTube embed is present.
- Live: https://incidentpilot-judge.onrender.com/
- GitHub: https://github.com/wyxaivv1018-collab/IncidentPilot
- YouTube: https://youtu.be/SFowqxkH0Gg
- No confirmation email id is recorded.
