# Official requirements checked 2026-09-23; rechecked 2026-09-29

Source: https://nebiusglobalaihackathon.devpost.com/rules

- Submission window: August 26, 2026, 09:00 Pacific to October 30, 2026, 10:00 Pacific.
- Judging: December 1, 2026, 09:00 Pacific to December 15, 2026, 12:00 Pacific.
- Track: Best Apps and Agents. A real Token Factory inference call plus NVIDIA open model use
  is required. Cloud deployment is encouraged, not required.
- Provide a working demo, hosted application or test-build URL, a public GitHub/GitLab/Bitbucket
  source repository with an open-source license and setup instructions, English materials, and
  a public YouTube demonstration under three minutes.
- Access for judges must be free and unrestricted through the end of judging. Asking judges
  to buy model credits does not satisfy that access arrangement.
- Existing projects are allowed if significantly updated during the submission period and
  their origin and updates are explained. Previous non-submission does not make an old project new.
- Include feedback about the Nebius and NVIDIA technologies actually used.

The user confirms a $1 promotional balance with roughly 29 trial days remaining. The exact
account expiration timestamp has not been verified. Even if measured from September 23, the
trial would expire around October 22, before the December judging period. Development spend
and judge-access funding are therefore separate. No payment setup, top-up or paid compute is
authorized. Publication/submission remain pending owner authorization and account access.

Model sources:
- https://github.com/nebius/token-factory-cookbook/blob/main/models/nemotron/nemotron3-super-120B.md
- https://github.com/nebius/token-factory-cookbook/blob/main/agents/agent-cost-comparison-1/agent_cost_comparison_1.py
- https://docs.tokenfactory.nebius.com/ai-models-inference/function-calling
- https://docs.tokenfactory.nebius.com/api-reference/models/list-models

Selected model: `nvidia/nemotron-3-super-120b-a12b`. Official cookbook lists $0.30 per million
input and $0.90 per million output tokens. Endpoint:
`https://api.tokenfactory.us-central1.nebius.com/v1/`. Function calling and NVIDIA Open Model
License are documented in the official model card. Account-specific availability and current
catalog pricing must be checked before the first paid call. No model comparison is planned.
