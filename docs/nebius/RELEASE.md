# Reviewable release and external gates

The local source bundle, runtime evidence, English materials and recorded real-run video review are
prepared for review. Source is now public; video/judge access and submission are still incomplete. See the delivery handoff
for exact paths, hashes and current gate results.

External work remains blocked on specific inputs:

| Gate | Concrete missing item | Consequence |
| --- | --- | --- |
| Nebius live validation | Complete for six owned-service cases | PASS; see VALIDATION.md |
| Account validity | Account's exact credit expiration and remaining balance | $1/29 days is user-reported; no billing-console confirmation |
| Public source | Published with owner authorization | https://github.com/wyxaivv1018-collab/IncidentPilot |
| Judge access | Free working demo/test access through December 15, 2026 | Trial cannot cover evaluation; no additional spend authorized |
| YouTube | Owner authorized @yxw-y1v; interactive channel login pending | 63-second live-browser video ready, no public video URL |
| Devpost | Entrant identity, account and explicit final submission authorization | No submitted entry or receipt |

No deployment plan may require judges to purchase their own credit. A download containing
only offline SOP/replay is useful for inspection but is not a substitute for the submitted
agent's working live capability. A free test-build link is allowed by the rules, but its live
model access must still be supplied without exposing the owner's API key.

The current authorization does not cover topping up credit, adding billing methods, paid
cloud instances or another paid provider. None has been created. Do not publish the local
baseline archive or raw unrelated historical coordination records without reviewing their
content; the release source bundle is separately inventoried and scanned.

Once live evidence exists and the final artifacts are ready, request these publication choices
together. Do not ask for a premature Devpost approval of an unverified live submission.

## September 29 — public source published

Public source: https://github.com/wyxaivv1018-collab/IncidentPilot
Commit: 9c5a8367095b4737722d2da9bde0554c9b499b9e. Anonymous GitHub API read PASS;
GitHub detected MIT license. Four existing September 9 documentation commits were inspected
and retained. Existing docs are explicitly historical; no history was force-replaced.
142 candidate files passed secret scanning and ZIP readback; isolated extracted build passed
15 connected/API tests in 10.39 seconds. Development workspace changes were not reset or committed.

YouTube upload is authorized for @yxw-y1v and waiting for interactive owner login.
No hosting account is available; exact Nebius balance/expiry remains unanswered.
The local live system and public source are complete; publicly accessible live judge service
is not yet established. Final Devpost submission remains assigned to Grokbot.
