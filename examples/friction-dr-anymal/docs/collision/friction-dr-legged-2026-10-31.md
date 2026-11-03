# Collision search: friction randomization for legged locomotion

> Status (first version, kept): **queries planned, nothing searched yet.** Verdicts below are blank on purpose; filling them
> from memory would defeat the record. Run with the `collision-search` skill before freezing the prereg.
>
> Status (2026-10-31, later the same day): **searched and read.** The queries ran against the arXiv API.
> The five papers were read from their arXiv PDFs:
> - the text was extracted with `pdftotext`, both in layout mode and in reading order;
> - each PDF title was compared with the metadata first, and all five match;
> - passages were located by keyword ("friction", "randomi") and read in context.
>
> This is not a page-by-page read of every paper. A passage that never uses these words could have been missed.

## Claim being checked

"Training a flat-ground quadruped velocity-tracking policy with randomized robot-body friction improves
success at low friction without a nominal-friction penalty."

Expected outcome of the search: **collides** (this is the standard domain-randomization recipe). The demo
keeps going anyway because its purpose is the discipline chain, not novelty; §1 of the prereg says so.

## Queries (arXiv API, ≥ 3 s apart; also a general web search)

1. Mechanism, not application: `abs:"domain randomization" AND abs:"friction" AND abs:"robust"`
2. Quantity: `abs:"friction" AND abs:"randomization" AND abs:"success rate" AND abs:"locomotion"`
3. Ablation form: `abs:"without randomization" AND abs:"friction" AND abs:"policy"`
4. Across fields: `abs:"dynamics randomization" AND abs:"manipulation"`
5. Exceptions: `abs:"domain randomization" AND (abs:"conservative" OR abs:"over-randomization" OR abs:"performance loss")`
6. Renamed fields: "robust RL" / "system identification" / "adaptive control" with friction

### Query results (run 2026-10-31, arXiv API, relevance order, titles only)

| # | Total hits | Possibly relevant (titles only, **not read**) |
|---|---|---|
| 1 | 3 | 2608.22629 *Enhancing Sim2Real Transfer for Torque-Controlled Robots through Real2Sim Dynamics Estimation and RL* |
| 2 | 2 | 2603.14156 *TransCurriculum: Multi-Dimensional Curriculum Learning for Fast & Stable Locomotion* |
| 3 | 0 | - (the phrase "without randomization" is too narrow; the ablation is described in other words) |
| 4 | 5 | 2408.04587 *FORGE: Force-Guided Exploration for Robust Contact-Rich Manipulation under Uncertainty* |
| 5 | 22 | 2503.10484 *Learning Robotic Policy with Imagined Transition: Mitigating the Trade-off between Robustness and Optimality*; 2311.01885 *Domain Randomization via Entropy Maximization*; 2104.07662 *Auto-Tuned Sim-to-Real Transfer* |
| 6 | 2 (run as `abs:"friction" AND abs:"system identification" AND abs:"legged"`) | 2609.17832 *Adaptive-MHE: A Sampling-Based Adaptive MPC for Legged Loco-Manipulation via Moving Horizon Estimation* |

Query 5's hits matter for criterion C2 (nominal cost). 2503.10484 names a robustness–optimality
trade-off in its title, so read it before interpreting a C2 result. The general web search was not run.

## Papers read (full text, keyword-located; see status note)

| Paper | Why | Collides? |
|---|---|---|
| Tobin et al. 2017, *Domain Randomization for Transferring Deep Neural Networks from Simulation to the Real World* (arXiv 1703.06907) | origin of the DR framing (visual) | **No.** The randomization is visual. Friction appears once, in a citation of other work: "train a policy to pivot a tool held in the robot's gripper in a simulator with randomized friction and action delays". |
| Peng et al. 2017, *Sim-to-Real Transfer of Robotic Control with Dynamics Randomization* (arXiv 1710.06537) | dynamics (incl. physical parameters) randomization | **Yes, on the template and on the ablation form.** It randomizes dynamics parameters including puck friction, "logarithmically sampled". The ablation trains "with subsets of the parameters held fixed". Table III, real robot: all randomized 0.89 ± 0.06 (28 trials) vs "fixed puck friction" 0.48 ± 0.10 (27 trials). The domain differs (pushing with an arm, LSTM policy), and the domain does not count against a collision. The puck-friction range in Table I could not be read reliably from the two-column PDF text, so it is not quoted. |
| Hwangbo et al. 2019, *Learning agile and dynamic motor skills for legged robots* (arXiv 1901.08652) | legged sim-to-real | **No, not on friction.** The randomized quantities named in the text are inertial: "center of mass positions, the masses of links, and joint positions … U(-2, 2) cm, U(-15, 15) %, and U(-2, 2) cm", over 30 sampled models. Friction appears only as the contact solver's Coulomb cone and as "hand-tuned" in the passage about a comparison model. |
| Lee et al. 2020, *Learning Quadrupedal Locomotion over Challenging Terrain* (arXiv 2010.11251) | legged, randomized dynamics | **Yes, on the template.** "randomized friction coefficients between the feet and the terrain". Training terrains use a friction coefficient drawn from N(0.7, 0.2), "clipped to be above 0.1" (Table S2). Friction is also privileged information for the teacher policy. Tests sample foot–ground friction from U(0.4, 1.0). No ablation without friction randomization was found in the passages read. |
| Rudin et al. 2021, *Learning to Walk in Minutes Using Massively Parallel Deep Reinforcement Learning* (arXiv 2109.11978) | the parallel-training setup this task descends from | **Yes, most directly** (same lineage as the Isaac Lab task). §3.3: "we randomize the friction of the ground … Each robot has a friction coefficient sampled uniformly in [0.5, 1.25]", together with observation noise and pushes every 10 s. No friction-only ablation in the passages read. |

## Verdict

**Collides.** This was expected and does not stop the demo.

**What is not new, at the level of the objective:**
- The training objective is max_π E_{μ∼p(μ)} E_{τ∼π, μ}[Σ_t r_t], where μ is the contact friction coefficient and p is a uniform range.
- The comparison is against p = δ(μ₀), a fixed default.
- Randomizing friction in this way is in Peng et al. 2017 (with exactly this ablation, on a manipulation task), in Lee et al. 2020 and in Rudin et al. 2021 (legged).
- The "fixed vs randomized friction" ablation form is Peng et al.'s Table III.

**Difference this run tests:** none claimed. This run is the demo of the discipline chain on a known answer.
Two things are specific to this run and are reported as descriptive, not novel:
1. The effect size on this Isaac Lab task under this success definition.
2. Whether there is a nominal-friction cost (C2). None of the five papers reports one in the passages read.
   Query 5 suggests the trade-off is studied elsewhere, so read those papers before writing anything about C2.

**Consequence for the prereg:** §1 stands as written ("what is not new" already says the recipe is standard).
Add this record's path and the three colliding papers to §1 before freezing.
