# Demonstration video — current real evidence review

Local artifact: `runtime/nebius/video-live-review/IncidentPilot-real-evidence-demo.mp4`.
English captions over actual browser footage of six real Nebius/Nemotron run reports.
Every reviewed run is visibly RECORDED: video recording does not execute new model calls.
Original live executions, provider IDs, actions, independent checks and run IDs are preserved.
No fabricated live badge or operation is shown. This review is not a real-time interaction recording.

The captions cover stopped HTTP, changed dependency cause, worker retry, changed lock cause,
permission/evidence handoffs, honest small-sample comparison and product boundaries.
Public YouTube upload and free judge access remain pending owner decisions.

Reproduce after running final acceptance and the local server:

```sh
node scripts/nebius_record_review.mjs
uv run --frozen --with imageio-ffmpeg python scripts/nebius_encode_video.py --real-review
```

The earlier offline draft and its validation remain under `runtime/nebius/video/`.

## September 29 — live browser completion

The actual browser selected live mode and clicked Investigate for HTTP stopped and locked
background-task cases. Both recovered; provider tool provenance, actual business verification,
same-run cards, history labels and mobile layout passed. No JavaScript exceptions.
Run IDs: RUN-NEBIUS-b5b63ceed79a and RUN-NEBIUS-b21c1d52882f.
Evidence: runtime/nebius/browser-live/check.json. The earlier CLI-only limitation is now closed
for these two browser workflows, not for arbitrary external system integrations.

New video: runtime/nebius/video-live/IncidentPilot-live-browser-demo.mp4, 63 seconds,
English captions, actual live browser operation followed by explicitly labelled history.
Full decode PASS. Prior offline and recorded-review videos remain separate.

Cumulative ledger at browser completion: 113 requests, $0.0533151 estimated, no unresolved
usage reservations. Remaining development allowance $0.7466849; account balance/expiry
remain unverified. Browser pair cost $0.0069171 (13 requests). The ledger contained 100
requests before this pair, versus the previous recorded 96; all costs remain included.

User authorized public repository wyxaivv1018-collab/IncidentPilot and YouTube channel
@yxw-y1v. Final Devpost submission belongs to Grokbot. No hosting account was provided.
Repository/video publication and free judge access require separately verified completion.
