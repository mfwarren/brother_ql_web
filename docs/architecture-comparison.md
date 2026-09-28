# Cross-judge: React static vs. server-rendered Flask

Scores use 1 (weak) to 5 (strong).

| Criterion | React static | Flask + small JS | Judgment |
| --- | ---: | ---: | --- |
| Phone editing and state clarity | 4 | 3 | React makes multi-line controls, content modes, draft state, pending preview, and save/print outcomes explicit. Server forms remain robust, but preview-enhanced form state needs careful synchronization. |
| Reuse of Python rendering and labels | 5 | 5 | Both keep `SimpleLabel` as the sole rendering authority and can preserve the JSON repository. React's adapter has more legacy wire conversion; server forms submit snapshots directly. |
| Pi runtime burden | 4 | 5 | Neither needs Node on the Pi. Flask pages add little runtime work; React adds only a static bundle but brings a development build and deployment artifact. |
| Honest hardware handling | 5 | 4 | Both distinguish simulation and physical availability. React explicitly addresses the checked-in three-worker service with interprocess serialization and webhook coordination. The server candidate's single-worker/process-lock path needs deployment enforcement or a single USB owner to be safe across workers. |
| Implementation scope | 3 | 4 | Server rendering has a shorter path from the current Flask templates and avoids an adapter/build. React's adapter and typed state cost more, while both still need printer-status and serialization work. |
| **Total** | **21** | **21** | Tie; the deciding factor is editor interaction, not runtime cost. |

## Recommendation

Choose the static React bundle served by Flask, with Python retaining preview generation, saved-label compatibility, and print admission. The phone editor has several coupled modes—per-line typography, QR/text, optional image processing, preview refresh, saved drafts, and explicit print outcomes. A typed browser draft and one transport adapter give those interactions one state owner and make stale preview and validation behavior easier to reason about. Build assets away from the Pi; do not add a Node runtime or separate frontend server there.

The server-rendered candidate is the better fallback if implementation proves the editor is mostly a sequence of simple forms. It reduces frontend tooling and can reuse the current Jinja application directly. Its central risk is that the advertised light enhancement gradually accumulates state synchronization rules for editing and preview, while React's central cost is an additional build and adapter boundary.

Before implementation, retain the React candidate's interprocess USB serialization requirement: the current Gunicorn service has three workers, so a process-local lock alone does not serialize hardware access. Keep simulation visibly separate from physical status, and make real-device readiness claims only from an actual status probe.
